import sys
import os
import json
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.lib.tickets import summarize_tickets
from server import app

with open(os.path.join(os.path.dirname(__file__), "..", "src", "fixtures", "tickets.json")) as f:
    tickets = json.load(f)

summary = summarize_tickets(tickets)
assert set(summary) == {"total", "by_status", "by_urgency"}
assert summary["total"] == len(tickets)
assert sum(summary["by_status"].values()) == summary["total"]
assert sum(summary["by_urgency"].values()) == summary["total"]
assert summary["by_status"] == dict(Counter(t["status"] for t in tickets))
assert summary["by_urgency"] == dict(Counter(t["urgency"] for t in tickets))
assert summarize_tickets([]) == {"total": 0, "by_status": {}, "by_urgency": {}}

with app.test_client() as client:
    response = client.get("/api/tickets/summary")
    assert response.status_code == 200
    result = response.get_json()
    assert set(result) == {"total", "by_status", "by_urgency"}
    assert result["total"] == len(tickets)
    assert result == summary

    response = client.get("/api/tickets/summary?status=nonsense")
    assert response.status_code == 200
    assert response.get_json() == summary

print("test_summary.py: OK")
