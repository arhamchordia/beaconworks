"""Revenue by customer segment. A fixed calculation: no model, no agent.

Same input, same answer, every time, in milliseconds, for free.
Run: python3 agent/segment_revenue.py
"""
from revenue_facts import load_sales, segment_totals

totals = segment_totals()
grand_total = sum(totals.values())
print(f"{len(load_sales())} transactions\n")
for segment, amount in totals.items():
    print(f"{segment:<22} ${amount:>11,}  {amount / grand_total:6.1%}")
print(f"{'Total':<22} ${grand_total:>11,}")
