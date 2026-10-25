"""Ticket lookups, backed by the fixture generated from the data room."""
import json
import os
import re
from datetime import datetime, timezone

from src.lib.customers import get_customer
from src.lib.priority import compute_score

_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "tickets.json")
with open(_FIXTURES) as f:
    TICKETS = json.load(f)


def enrich_ticket(ticket, now=None):
    """Return a scored copy, using zero segment weight for a missing customer."""
    now = now or datetime.now(timezone.utc)
    customer = get_customer(ticket["customer_id"])
    segment = customer["segment"] if customer is not None else None
    return dict(ticket, priority_score=compute_score(ticket, segment, now))


def enrich_tickets(tickets, now=None):
    """Return scored copies in source order, sharing one UTC timestamp."""
    now = now or datetime.now(timezone.utc)
    return [enrich_ticket(ticket, now) for ticket in tickets]


def list_tickets(status=None, urgency=None, customer_id=None):
    """List tickets matching every supplied filter, preserving source order."""
    filters = {"status": status, "urgency": urgency, "customer_id": customer_id}
    return [t for t in TICKETS if all(
        value is None or t[key] == value for key, value in filters.items()
    )]


def parse_ticket_query(args):
    """Return cleaned ticket options, or raise ValueError for invalid options."""
    query = {key: args[key] for key in ("status", "urgency", "customer_id") if key in args}
    query["sort"] = args.get("sort")
    query["order"] = args.get("order", "asc")
    if query["sort"] is not None and query["sort"] != "id":
        raise ValueError("sort must be id")
    if query["order"] not in {"asc", "desc"}:
        raise ValueError("order must be asc or desc")
    for key, default in (("limit", None), ("offset", 0)):
        if key not in args:
            query[key] = default
            continue
        value = args[key]
        if not re.fullmatch(r"[0-9]+", value):
            raise ValueError(key + " must be a non-negative integer")
        try:
            query[key] = int(value)
        except ValueError:
            raise ValueError(key + " must be a non-negative integer") from None
    return query


def filter_tickets(query):
    """Reuse ticket filtering for list queries and summaries."""
    return list_tickets(**{key: query[key] for key in ("status", "urgency", "customer_id")
                           if key in query})


def query_tickets(query):
    """Filter, optionally sort by ID, then paginate and return the total."""
    tickets = filter_tickets(query)
    if query["sort"] == "id":
        tickets.sort(key=lambda ticket: ticket["ticket_id"], reverse=query["order"] == "desc")
    total = len(tickets)
    start = query["offset"]
    end = None if query["limit"] is None else start + query["limit"]
    return tickets[start:end], total


def summarize_tickets(tickets):
    """Count tickets overall, by status, and by urgency."""
    by_status = {}
    by_urgency = {}
    for ticket in tickets:
        status = ticket["status"]
        urgency = ticket["urgency"]
        by_status[status] = by_status.get(status, 0) + 1
        by_urgency[urgency] = by_urgency.get(urgency, 0) + 1
    return {"total": len(tickets), "by_status": by_status, "by_urgency": by_urgency}


def get_ticket(ticket_id: str):
    for t in TICKETS:
        if t["ticket_id"] == ticket_id:
            return t
    return None


def tickets_for_customer(customer_id: str):
    return [t for t in TICKETS if t["customer_id"] == customer_id]
