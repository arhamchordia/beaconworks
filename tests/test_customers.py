import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.lib.customers import get_customer
from server import app

known = get_customer("CUST-0001")
assert known is not None, "CUST-0001 should exist"

# This is the seeded-bug assertion for lesson 15.3: the record genuinely
# does not exist. The test documents the bug's true cause -- it is not
# testing that the app crashes, it is testing that the DATA gap is real,
# so the fix belongs in server.py's handling, not in fabricating a record.
missing = get_customer("CUST-0007")
assert missing is None, "CUST-0007 is deliberately absent"

with app.test_client() as client:
    response = client.get("/api/customers/CUST-0007")
    assert response.status_code == 404, f"expected 404, got {response.status_code}"
    assert response.get_json() == {
        "error": "customer not found", "customer_id": "CUST-0007",
    }

    response = client.get("/api/customers/CUST-9999")
    assert response.status_code == 404, f"expected 404, got {response.status_code}"
    assert response.get_json() == {
        "error": "customer not found", "customer_id": "CUST-9999",
    }

    response = client.get("/api/customers/CUST-0029")
    assert response.status_code == 200, f"expected 200, got {response.status_code}"
    assert response.get_json() == {"name": "Dovetail Furniture", "segment": "Enterprise"}

    response = client.get("/api/customers/CUST-0007/tickets")
    assert response.status_code == 200
    tickets = response.get_json()
    assert tickets, "missing customer records must not hide their tickets"
    assert all(ticket["customer_id"] == "CUST-0007" for ticket in tickets)
    assert any(ticket["ticket_id"] == "TICKET-0029" for ticket in tickets)

print("test_customers.py: OK")
