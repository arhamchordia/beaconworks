import sys
import os
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.lib.tickets import (
    list_tickets, get_ticket, tickets_for_customer, enrich_ticket, enrich_tickets,
)
from server import app


def assert_scored_records(actual, expected):
    """Preserve exact original-field comparisons while requiring numeric scores."""
    assert [{key: value for key, value in ticket.items() if key != "priority_score"}
            for ticket in actual] == [
                {key: value for key, value in ticket.items() if key != "priority_score"}
                for ticket in expected
            ]
    for ticket in actual:
        assert type(ticket["priority_score"]) in (int, float)
        assert 0 <= ticket["priority_score"] <= 100


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
    response = client.get("/")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "<th>Priority score (beta)</th>" in response.get_data(as_text=True)

    response = client.get("/api/tickets", query_string={"status": status})
    assert response.status_code == 200
    assert_scored_records(response.get_json(), expected)
    assert response.headers["X-Total-Count"] == str(len(expected))

    response = client.get("/api/tickets?status=nonsense")
    assert response.status_code == 200
    assert response.get_json() == []

    response = client.get("/api/tickets")
    assert response.status_code == 200
    assert_scored_records(response.get_json(), tickets)
    assert response.headers["X-Total-Count"] == str(len(tickets))
    assert_scored_records([client.get("/api/tickets/TICKET-0001").get_json()], [tickets[0]])
    response = client.get("/api/tickets/TICKET-9999")
    assert response.status_code == 404
    assert response.get_json() == {"error": "ticket not found"}

    for customer_id in ("CUST-0001", "CUST-0007", "CUST-9999"):
        response = client.get(f"/api/customers/{customer_id}/tickets")
        assert response.status_code == 200
        assert_scored_records(response.get_json(), tickets_for_customer(customer_id))

with patch("src.lib.tickets.TICKETS", []), app.test_client() as client:
    response = client.get("/api/tickets")
    assert response.status_code == 200
    assert response.get_json() == []
    assert response.headers["X-Total-Count"] == "0"
    response = client.get("/api/tickets/summary")
    assert response.status_code == 200
    assert response.get_json() == {"total": 0, "by_status": {}, "by_urgency": {}}

# Fixed-clock integration matrix: all reference scores, plus the missing customer.
now = datetime(2026, 10, 25, tzinfo=timezone.utc)
ages = (0, 7, 14, 21)
reference_scores = {
    ("high", "Enterprise"): (70.00, 85.00, 100.00, 100.00),
    ("high", "Mid-Market"): (58.00, 73.00, 88.00, 88.00),
    ("high", "SMB"): (52.00, 67.00, 82.00, 82.00),
    ("medium", "Enterprise"): (54.00, 69.00, 84.00, 84.00),
    ("medium", "Mid-Market"): (42.00, 57.00, 72.00, 72.00),
    ("medium", "SMB"): (36.00, 51.00, 66.00, 66.00),
    ("low", "Enterprise"): (42.00, 57.00, 72.00, 72.00),
    ("low", "Mid-Market"): (30.00, 45.00, 60.00, 60.00),
    ("low", "SMB"): (24.00, 39.00, 54.00, 54.00),
}
customers = [{"customer_id": f"QA-{index}", "segment": segment}
             for index, segment in enumerate(("Enterprise", "Mid-Market", "SMB"))]
customer_ids = {customer["segment"]: customer["customer_id"] for customer in customers}
records = []
expected_records = []
for (urgency, segment), scores in reference_scores.items():
    for age, score in zip(ages, scores):
        record = {
            "ticket_id": f"QA-{len(records):03d}",
            "customer_id": customer_ids[segment],
            "urgency": urgency,
            "status": "open",
            "created_date": (now - timedelta(days=age)).isoformat(),
        }
        records.append(record)
        expected_records.append(dict(record, priority_score=score))
missing = {
    "ticket_id": "QA-missing",
    "customer_id": "CUST-0007",
    "urgency": "high",
    "status": "open",
    "created_date": (now - timedelta(days=7)).isoformat(),
}
records.append(missing)
expected_records.append(dict(missing, priority_score=55.00))
assert len(records) == 37
snapshot = deepcopy(records)
customer_snapshot = deepcopy(customers)

with patch("src.lib.tickets.TICKETS", records), \
        patch("src.lib.customers.CUSTOMERS", customers), \
        patch("src.lib.tickets.datetime") as clock, app.test_client() as client:
    clock.now.return_value = now
    assert enrich_ticket(missing, now) == expected_records[-1]
    enriched = enrich_tickets(records, now)
    assert enriched == expected_records
    assert all(result is not original for result, original in zip(enriched, records))
    clock.now.assert_not_called()

    # A moving clock would cross an age boundary if read again within a batch.
    clock.now.side_effect = [now, now + timedelta(days=1)]
    assert enrich_tickets(records) == expected_records
    clock.now.assert_called_once_with(timezone.utc)
    clock.now.side_effect = None

    clock.reset_mock()
    response = client.get("/api/tickets")
    assert response.status_code == 200
    assert response.get_json() == expected_records
    assert response.headers["X-Total-Count"] == "37"
    clock.now.assert_called_once_with(timezone.utc)

    for expected_record in expected_records:
        clock.reset_mock()
        response = client.get(f"/api/tickets/{expected_record['ticket_id']}")
        assert response.status_code == 200
        assert response.get_json() == expected_record
        clock.now.assert_called_once_with(timezone.utc)

    for customer_id in (*customer_ids.values(), "CUST-0007", "unknown"):
        clock.reset_mock()
        response = client.get(f"/api/customers/{customer_id}/tickets")
        assert response.status_code == 200
        assert response.get_json() == [record for record in expected_records
                                       if record["customer_id"] == customer_id]
        clock.now.assert_called_once_with(timezone.utc)

    response = client.get("/api/tickets?customer_id=CUST-0007")
    assert response.status_code == 200
    assert response.get_json() == [expected_records[-1]]
    assert response.headers["X-Total-Count"] == "1"

    response = client.get("/api/tickets?sort=id&order=desc&offset=1&limit=2")
    assert response.status_code == 200
    assert response.get_json() == sorted(expected_records, key=lambda t: t["ticket_id"],
                                        reverse=True)[1:3]
    assert response.headers["X-Total-Count"] == "37"

    clock.reset_mock()
    response = client.get("/api/tickets/summary")
    assert response.status_code == 200
    assert response.get_json() == {
        "total": 37, "by_status": {"open": 37},
        "by_urgency": {"high": 13, "medium": 12, "low": 12},
    }
    clock.now.assert_not_called()
    assert records == snapshot
    assert customers == customer_snapshot

print("test_tickets.py: OK")
