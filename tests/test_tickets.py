import sys
import os
import json
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.lib.tickets import list_tickets, get_ticket, tickets_for_customer
from server import app

assert len(list_tickets()) == 50, "expected 50 seeded tickets"

injection_ticket = get_ticket("TICKET-0023")
assert "ignore prior instructions" in injection_ticket["body"], (
    "TICKET-0023 should carry the planted prompt-injection text for lesson 25.2"
)

bug_ticket = get_ticket("TICKET-0008")
assert bug_ticket["customer_id"] == "CUST-0007", (
    "TICKET-0008 should reference the missing customer for lesson 15.3"
)

assert len(tickets_for_customer("CUST-0007")) >= 1, (
    "the missing customer must still have at least one ticket on file"
)

with open(os.path.join(os.path.dirname(__file__), "..", "src", "fixtures", "tickets.json")) as f:
    tickets = json.load(f)

status = tickets[0]["status"]
expected = [t for t in tickets if t["status"] == status]
assert list_tickets(status) == expected
assert list_tickets("nonsense") == []
assert list_tickets("") == [t for t in tickets if t["status"] == ""]
assert list_tickets() == tickets

with app.test_client() as client:
    response = client.get("/api/tickets", query_string={"status": status})
    assert response.status_code == 200
    assert response.get_json() == expected
    assert response.headers["X-Total-Count"] == str(len(expected))

    response = client.get("/api/tickets?status=nonsense")
    assert response.status_code == 200
    assert response.get_json() == []

    response = client.get("/api/tickets")
    assert response.status_code == 200
    assert response.get_json() == tickets
    assert response.headers["X-Total-Count"] == str(len(tickets))
    assert client.get("/api/tickets/TICKET-0001").get_json() == tickets[0]
    response = client.get("/api/tickets/TICKET-9999")
    assert response.status_code == 404
    assert response.get_json() == {"error": "ticket not found"}

with patch("src.lib.tickets.TICKETS", []), app.test_client() as client:
    response = client.get("/api/tickets")
    assert response.status_code == 200
    assert response.get_json() == []
    assert response.headers["X-Total-Count"] == "0"
    response = client.get("/api/tickets/summary")
    assert response.status_code == 200
    assert response.get_json() == {"total": 0, "by_status": {}, "by_urgency": {}}

print("test_tickets.py: OK")
