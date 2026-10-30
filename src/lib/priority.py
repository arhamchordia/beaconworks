"""
Priority Scoring (v3 formula, matches data_room/product_docs/ticket_dashboard_overview.md).

score = (urgency_weight * 40) + (segment_weight * 30) + (days_open_capped * 30 / 14)

Lessons 15.1 (plan) / 15.2 (implement incrementally): this module is the
starter-repo stub. At Section 13, it exists but is NOT called from
server.py or the UI -- wiring it in is exactly what 15.2 does. If you're
using this file as the "before" state for that lecture, strip the body of
compute_score() back to a TODO and rebuild it on camera.
"""
from datetime import datetime, timezone

URGENCY_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}
SEGMENT_WEIGHT = {"Enterprise": 1.0, "Mid-Market": 0.6, "SMB": 0.4}


def days_open(created_date_iso: str, now: datetime = None) -> int:
    now = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(created_date_iso)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = now - created
    return max(0, delta.days)


def compute_score(ticket: dict, customer_segment: str, now: datetime = None) -> float:
    """Score a ticket; a missing segment (None) contributes zero segment points."""
    uw = URGENCY_WEIGHT.get(ticket["urgency"], 0)
    sw = SEGMENT_WEIGHT.get(customer_segment, 0)
    capped = min(days_open(ticket["created_date"], now), 14)
    score = uw * 40 + sw * 30 + (capped * 30) / 14
    return round(score, 2)
