"""BeaconWorks query tools: precise inputs, one output shape, clear errors.

Every tool is read-only and returns JSON in one of two shapes:
  {"ok": true, ...}                                     the data
  {"ok": false, "error": {"code": "...", "message": "..."}}  what went wrong

Error codes: invalid_arguments, not_found, too_broad, not_available.

Test every tool without calling any model:
  python3 analyst/tools.py
"""
import copy
import json
import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.lib.customers import get_customer, list_customers  # the dashboard's own data functions
from src.lib.tickets import get_ticket, list_tickets

SKIP_TICKETS = {"TICKET-0023"}  # reserved for the security section of the course
SEGMENTS = ["SMB", "Mid-Market", "Enterprise"]
REGIONS = ["APAC", "EMEA", "North America"]
STATUSES = ["open", "closed"]
URGENCIES = ["high", "medium", "low"]
CUSTOMER_ID = "^CUST-[0-9]{4}$"
TICKET_ID = "^TICKET-[0-9]{4}$"


# ---------- Inputs: the schema the model sees, and the same rules checked in our code ----------

class GetCustomerArgs(BaseModel):
    customer_id: str = Field(pattern=CUSTOMER_ID)


class FindCustomersArgs(BaseModel):
    name_contains: Optional[str] = Field(max_length=40)
    segment: Optional[Literal["SMB", "Mid-Market", "Enterprise"]]
    region: Optional[Literal["APAC", "EMEA", "North America"]]


class GetTicketArgs(BaseModel):
    ticket_id: str = Field(pattern=TICKET_ID)


class ListTicketsArgs(BaseModel):
    customer_id: Optional[str] = Field(pattern=CUSTOMER_ID)
    status: Optional[Literal["open", "closed"]]
    urgency: Optional[Literal["high", "medium", "low"]]
    limit: int = Field(ge=1, le=10)


def nullable(kind: str, description: str, **extra) -> dict:
    """In strict mode every field is required, so 'optional' means 'may be null'."""
    if "enum" in extra:
        extra["enum"] = extra["enum"] + [None]
    return {"type": [kind, "null"], "description": description, **extra}


def function(name: str, description: str, properties: dict) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "strict": True,
    }


CUSTOMER_TOOLS = [
    function(
        "get_customer",
        "Get one customer by ID. Use when the customer ID is known. Returns name, segment, "
        "region, signup date and account owner, or error not_found.",
        {"customer_id": {"type": "string", "pattern": CUSTOMER_ID, "description": "For example CUST-0002."}},
    ),
    function(
        "find_customers",
        "Find customers by part of the name, segment or region. Use when the customer ID is not known. "
        "Give at least one filter. Returns up to 10 matches with their IDs, or error too_broad.",
        {
            # Strict mode has no maxLength for strings, so the 40 character limit is checked in our code only.
            "name_contains": nullable("string", "Part of the company name, for example Ballast. Up to 40 characters."),
            "segment": nullable("string", "Customer segment.", enum=SEGMENTS),
            "region": nullable("string", "Customer region.", enum=REGIONS),
        },
    ),
]

TICKET_TOOLS = [
    function(
        "get_ticket",
        "Get one support ticket by ID. Returns customer ID, subject, category, urgency, status and "
        "created date, never the ticket body. Returns error not_found or not_available.",
        {"ticket_id": {"type": "string", "pattern": TICKET_ID, "description": "For example TICKET-0001."}},
    ),
    function(
        "list_tickets",
        "List support tickets filtered by customer ID, status and urgency. Give at least one filter. "
        "Returns the total count and up to `limit` tickets, newest first.",
        {
            "customer_id": nullable("string", "Customer ID, for example CUST-0002.", pattern=CUSTOMER_ID),
            "status": nullable("string", "Ticket status.", enum=STATUSES),
            "urgency": nullable("string", "Ticket urgency.", enum=URGENCIES),
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "description": "How many tickets to return, 1 to 10."},
        },
    ),
]

ARGS = {
    "get_customer": GetCustomerArgs,
    "find_customers": FindCustomersArgs,
    "get_ticket": GetTicketArgs,
    "list_tickets": ListTicketsArgs,
}


def tool_list(search: bool) -> list:
    """All tools sent up front, or grouped in namespaces and loaded only when tool search finds them."""
    if not search:
        return CUSTOMER_TOOLS + TICKET_TOOLS
    namespaces = [
        ("customers", "Look up and find BeaconWorks customers.", CUSTOMER_TOOLS),
        ("tickets", "Look up and list BeaconWorks support tickets.", TICKET_TOOLS),
    ]
    tools = []
    for name, description, functions in namespaces:
        deferred = [dict(copy.deepcopy(f), defer_loading=True) for f in functions]
        tools.append({"type": "namespace", "name": name, "description": description, "tools": deferred})
    return tools + [{"type": "tool_search"}]


# ---------- Outputs: one shape for data, one shape for errors ----------

def error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def run_get_customer(args: GetCustomerArgs) -> dict:
    record = get_customer(args.customer_id)
    if record is None:
        return error("not_found", f"No customer {args.customer_id}.")
    keep = ("customer_id", "name", "segment", "region", "signup_date", "account_owner")  # no contact email
    return {"ok": True, "customer": {key: record[key] for key in keep}}


def run_find_customers(args: FindCustomersArgs) -> dict:
    if args.name_contains is None and args.segment is None and args.region is None:
        return error("too_broad", "Give at least one of name_contains, segment or region.")
    matches = [
        {key: c[key] for key in ("customer_id", "name", "segment", "region")}
        for c in list_customers()
        if (args.name_contains is None or args.name_contains.lower() in c["name"].lower())
        and (args.segment is None or c["segment"] == args.segment)
        and (args.region is None or c["region"] == args.region)
    ]
    return {"ok": True, "total": len(matches), "customers": matches[:10]}


def run_get_ticket(args: GetTicketArgs) -> dict:
    if args.ticket_id in SKIP_TICKETS:
        return error("not_available", f"{args.ticket_id} is not available to this assistant.")
    ticket = get_ticket(args.ticket_id)
    if ticket is None:
        return error("not_found", f"No ticket {args.ticket_id}.")
    keep = ("ticket_id", "customer_id", "subject", "category", "urgency", "status", "created_date")  # no body
    return {"ok": True, "ticket": {key: ticket[key] for key in keep}}


def run_list_tickets(args: ListTicketsArgs) -> dict:
    if args.customer_id is None and args.status is None and args.urgency is None:
        return error("too_broad", "Give at least one of customer_id, status or urgency.")
    found = [
        t for t in list_tickets(status=args.status, urgency=args.urgency, customer_id=args.customer_id)
        if t["ticket_id"] not in SKIP_TICKETS
    ]
    found.sort(key=lambda t: t["created_date"], reverse=True)
    keep = ("ticket_id", "customer_id", "subject", "urgency", "status", "created_date")
    return {"ok": True, "total": len(found), "tickets": [{key: t[key] for key in keep} for t in found[: args.limit]]}


RUNNERS = {
    "get_customer": run_get_customer,
    "find_customers": run_find_customers,
    "get_ticket": run_get_ticket,
    "list_tickets": run_list_tickets,
}


def dispatch(name: str, arguments: str) -> dict:
    """Check the model's arguments, then run the tool. Never raises."""
    if name not in RUNNERS:
        return error("not_found", f"No tool named {name}.")
    try:
        args = ARGS[name].model_validate_json(arguments)
    except ValidationError as problem:
        first = problem.errors()[0]
        field = ".".join(str(part) for part in first["loc"]) or "arguments"
        return error("invalid_arguments", f"{field}: {first['msg']}")
    return RUNNERS[name](args)


# ---------- Self test: run with  python3 analyst/tools.py ----------

def self_test() -> int:
    checks = []

    def check(label, ok):
        checks.append(ok)
        print(("PASS " if ok else "FAIL ") + label)

    for tool in CUSTOMER_TOOLS + TICKET_TOOLS:
        params = tool["parameters"]
        fields = set(ARGS[tool["name"]].model_fields)
        check(f"schema {tool['name']}: strict, no extra fields, all required, matches the Pydantic model",
              tool["strict"] and params["additionalProperties"] is False
              and set(params["required"]) == set(params["properties"]) == fields)

    def run(name, **arguments):
        return dispatch(name, json.dumps(arguments))

    out = run("get_customer", customer_id="CUST-0002")
    check("get_customer CUST-0002 returns Ballast Analytics, no email",
          out["ok"] and out["customer"]["name"] == "Ballast Analytics" and "primary_contact_email" not in out["customer"])
    check("get_customer CUST-0007 returns not_found", run("get_customer", customer_id="CUST-0007")["error"]["code"] == "not_found")
    check("get_customer 0002 returns invalid_arguments", run("get_customer", customer_id="0002")["error"]["code"] == "invalid_arguments")
    out = run("find_customers", name_contains="ballast", segment=None, region=None)
    check("find_customers 'ballast' finds CUST-0002", out["ok"] and [c["customer_id"] for c in out["customers"]] == ["CUST-0002"])
    check("find_customers with no filter returns too_broad",
          run("find_customers", name_contains=None, segment=None, region=None)["error"]["code"] == "too_broad")
    check("find_customers segment 'Large' returns invalid_arguments",
          run("find_customers", name_contains=None, segment="Large", region=None)["error"]["code"] == "invalid_arguments")
    out = run("get_ticket", ticket_id="TICKET-0001")
    check("get_ticket TICKET-0001 has a subject and no body", out["ok"] and "subject" in out["ticket"] and "body" not in out["ticket"])
    check("get_ticket TICKET-0999 returns not_found", run("get_ticket", ticket_id="TICKET-0999")["error"]["code"] == "not_found")
    check("get_ticket TICKET-0023 returns not_available", run("get_ticket", ticket_id="TICKET-0023")["error"]["code"] == "not_available")
    out = run("list_tickets", customer_id="CUST-0002", status="open", urgency="high", limit=10)
    check("list_tickets CUST-0002 open high returns 2 tickets", out["ok"] and out["total"] == 2)
    out = run("list_tickets", customer_id="CUST-0025", status=None, urgency=None, limit=10)
    check("list_tickets never returns TICKET-0023", all(t["ticket_id"] != "TICKET-0023" for t in out["tickets"]))
    check("list_tickets limit 50 returns invalid_arguments",
          run("list_tickets", customer_id=None, status="open", urgency=None, limit=50)["error"]["code"] == "invalid_arguments")
    check("unknown tool returns not_found", dispatch("delete_customer", "{}")["error"]["code"] == "not_found")
    print(f"{sum(checks)} of {len(checks)} checks passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(self_test())
