import sys
import os
import json
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.lib.tickets import summarize_tickets

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

print("test_summary.py: OK")
