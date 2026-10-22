"""Ticket lookups, backed by the fixture generated from the data room."""
import json
import os

_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "tickets.json")
with open(_FIXTURES) as f:
    TICKETS = json.load(f)


def list_tickets(status=None):
    """List all tickets, or only those with the given status."""
    if status is None:
        return TICKETS
    return [t for t in TICKETS if t["status"] == status]


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
