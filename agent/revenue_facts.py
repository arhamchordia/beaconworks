"""BeaconWorks revenue facts, computed in plain Python. No model involved.

Agents in this folder use these numbers as their evidence, and our checks use the
same numbers to grade what an agent says. Code computes, the agent explains.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SALES_CSV = REPO / "data" / "sales_transactions.csv"
CUSTOMERS_JSON = REPO / "src" / "fixtures" / "customers.json"


def load_sales() -> list[dict]:
    with SALES_CSV.open(newline="") as f:
        return [{**row, "amount_usd": int(row["amount_usd"])} for row in csv.DictReader(f)]


def load_customers() -> dict[str, dict]:
    return {c["customer_id"]: c for c in json.loads(CUSTOMERS_JSON.read_text())}


def months() -> list[str]:
    return sorted({row["month"] for row in load_sales()})


def month_totals() -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for row in load_sales():
        totals[row["month"]] += row["amount_usd"]
    return dict(sorted(totals.items()))


def segment_totals() -> dict[str, int]:
    """Revenue per segment from the customer records. Unknown customers are reported, not dropped."""
    customers = load_customers()
    totals: dict[str, int] = defaultdict(int)
    for row in load_sales():
        record = customers.get(row["customer_id"])
        totals[record["segment"] if record else "Unmatched customer ID"] += row["amount_usd"]
    return dict(sorted(totals.items(), key=lambda item: -item[1]))


def customer_changes(previous_month: str, month: str) -> list[dict]:
    """Revenue per customer in two months, and the change, biggest fall first."""
    customers = load_customers()
    before: dict[str, int] = defaultdict(int)
    after: dict[str, int] = defaultdict(int)
    for row in load_sales():
        if row["month"] == previous_month:
            before[row["customer_id"]] += row["amount_usd"]
        elif row["month"] == month:
            after[row["customer_id"]] += row["amount_usd"]
    rows = []
    for customer_id in sorted(set(before) | set(after)):
        record = customers.get(customer_id)
        rows.append({
            "customer_id": customer_id,
            "name": record["name"] if record else "not available",
            "previous_usd": before[customer_id],
            "month_usd": after[customer_id],
            "change_usd": after[customer_id] - before[customer_id],
        })
    return sorted(rows, key=lambda r: r["change_usd"])
