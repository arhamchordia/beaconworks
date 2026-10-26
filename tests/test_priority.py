import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.lib.priority import compute_score, days_open
from src.lib.customers import get_customer

# Expected scores are copied from the approved plan, independently of the helper.
now = datetime(2026, 10, 25, 0, 0, 0, tzinfo=timezone.utc)
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

case_count = 0
for (urgency, segment), expected_scores in reference_scores.items():
    actual_scores = []
    for age, expected in zip(ages, expected_scores):
        ticket = {
            "urgency": urgency,
            "created_date": (now - timedelta(days=age)).isoformat(),
        }
        actual = compute_score(ticket, segment, now)
        assert actual == expected, (
            f"{urgency}, {segment}, {age} days: expected {expected}, got {actual}"
        )
        actual_scores.append(actual)
        case_count += 1
    assert actual_scores[2] == actual_scores[3], (urgency, segment, "age cap")

# The fixture gap is intentional. Exercise the scorer with no segment without
# adding customer enrichment or changing generated customer/ticket data.
missing_customer_ticket = {
    "customer_id": "CUST-0007",
    "urgency": "high",
    "created_date": (now - timedelta(days=7)).isoformat(),
}
customer = get_customer(missing_customer_ticket["customer_id"])
assert customer is None, "CUST-0007 must remain absent from customer data"
actual = compute_score(missing_customer_ticket, None, now)
assert actual == 55.00, f"missing customer: expected 55.00, got {actual}"
case_count += 1

future_ticket = {
    "urgency": "high",
    "created_date": (now + timedelta(days=7)).isoformat(),
}
assert days_open(future_ticket["created_date"], now) == 0, "future dates must clamp to zero days"
actual = compute_score(future_ticket, "Enterprise", now)
assert actual == 70.00, f"future date: expected 70.00, got {actual}"
case_count += 1
assert case_count == 38

print(f"test_priority.py: OK ({case_count} cases)")
