"""Access rule tests for the triage MCP server, through a real MCP client, in-process.

Each case sets BW_CALLER the way Codex would when it starts the server, then calls the tools.

Run:  python3 plugins/beaconworks-triage/tests/test_access.py
"""
import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from mcp import Client  # noqa: E402
from triage_server import CUSTOMERS, mcp  # noqa: E402

OPEN_HIGH = {"status": "open", "urgency": "high", "limit": 20}


async def run(client: Client) -> None:
    async def call(caller, tool, args):
        if caller is None:
            os.environ.pop("BW_CALLER", None)
        else:
            os.environ["BW_CALLER"] = caller
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            result = await client.call_tool(tool, args)
        audit = [json.loads(line) for line in log.getvalue().splitlines() if line.startswith('{"audit"')]
        return result, audit

    # 1. Fail closed: no caller, or a caller not in access.json, sees nothing.
    for caller in ("", "eve.unknown"):  # "" overrides any ~/.beaconworks/caller file on this machine
        r, audit = await call(caller, "search_tickets", OPEN_HIGH)
        assert r.is_error and "without a known caller" in r.content[0].text, r.content[0].text
        assert audit[-1]["decision"] == "denied: unknown caller"
    print("OK  no caller and unknown caller: denied, nothing returned")

    # 2. Row-level filtering: each owner sees only their region's open high urgency tickets.
    expected = {"marcus.cole": (["EMEA"], 9), "priya.nair": (["North America"], 5),
                "diego.alves": (["APAC"], 4), "support.lead": (["*"], 18)}
    for caller, (regions, total) in expected.items():
        r, _ = await call(caller, "search_tickets", OPEN_HIGH)
        data = r.structured_content
        assert data["visible_regions"] == regions and data["total_matches"] == total, (caller, data["total_matches"])
        if regions != ["*"]:
            assert all(CUSTOMERS[t["customer_id"]]["region"] in regions for t in data["tickets"]), caller
    print("OK  open + high per caller: marcus.cole 9 (EMEA), priya.nair 5, diego.alves 4, support.lead 18")

    # 3. Object-level check: an owner cannot read another region's customer, and the refusal
    #    looks exactly like "does not exist", so it does not reveal that the record is there.
    r_hidden, audit = await call("marcus.cole", "get_customer", {"customer_id": "CUST-0002"})
    r_none, _ = await call("marcus.cole", "get_customer", {"customer_id": "CUST-0099"})
    assert r_hidden.is_error and r_none.is_error
    assert r_hidden.content[0].text.replace("CUST-0002", "X") == r_none.content[0].text.replace("CUST-0099", "X")
    assert audit[-1]["decision"] == "denied: outside the caller's regions"
    print("OK  marcus.cole get_customer CUST-0002 (APAC): denied, same message as a customer that does not exist")
    print("    the audit log still knows the real reason: \"denied: outside the caller's regions\"")

    r, _ = await call("marcus.cole", "get_customer", {"customer_id": "CUST-0001"})
    assert not r.is_error and r.structured_content["name"] == "Alden Freight Co"
    print("OK  marcus.cole get_customer CUST-0001 (EMEA): Alden Freight Co")

    r, _ = await call("marcus.cole", "search_tickets", {"customer_id": "CUST-0002"})
    assert r.structured_content["total_matches"] == 0
    print("OK  marcus.cole search_tickets CUST-0002: 0 matches, the filter cannot reach other regions")

    # 4. The model cannot change who it is: an extra "caller" argument is not a parameter, so it changes nothing.
    r, _ = await call("marcus.cole", "get_customer", {"customer_id": "CUST-0002", "caller": "support.lead"})
    assert r.is_error and "No customer record available" in r.content[0].text
    print("OK  marcus.cole sends caller=support.lead as an argument: still denied")

    # 5. Tickets whose customer record is missing (CUST-0007) have no region: only a lead sees them.
    r_owner, _ = await call("marcus.cole", "search_tickets", {"customer_id": "CUST-0007"})
    r_lead, _ = await call("support.lead", "search_tickets", {"customer_id": "CUST-0007"})
    assert r_owner.structured_content["total_matches"] == 0 and r_lead.structured_content["total_matches"] == 2
    print("OK  CUST-0007 tickets (no customer record): marcus.cole 0, support.lead 2")


async def main() -> int:
    failure = None
    async with Client(mcp) as client:
        try:
            await run(client)
        except AssertionError as error:
            failure = error
    if failure:
        print(f"FAIL {failure}")
        return 1
    print("All access tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
