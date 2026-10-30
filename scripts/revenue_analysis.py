"""Generate BeaconWorks revenue outputs using only the standard library."""

import csv
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from src.lib.customers import list_customers


def number(value):
    """Keep whole dollars as integers and serialize fractional dollars as numbers."""
    return int(value) if value == value.to_integral_value() else float(value)


def money(value):
    return f"{'-' if value < 0 else ''}${abs(value):,.1f}"


def share(value, denominator):
    return f"{value / denominator * 100:.1f}%" if denominator else "N/A"


def main():
    customers = {c["customer_id"]: c for c in list_customers()}
    segments = defaultdict(Decimal)
    months = defaultdict(Decimal)
    customer_months = defaultdict(lambda: defaultdict(Decimal))
    unmatched = defaultdict(Decimal)
    unmatched_rows = defaultdict(int)
    rows = zero_rows = 0
    with (ROOT / "data/sales_transactions.csv").open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            amount = Decimal(row["amount_usd"])
            customer_id = row["customer_id"]
            customer = customers.get(customer_id)
            segment = customer["segment"] if customer is not None else "Unmatched"
            segments[segment] += amount
            months[row["month"]] += amount
            customer_months[row["month"]][customer_id] += amount
            rows += 1
            zero_rows += amount == 0
            if customer is None:
                unmatched[customer_id] += amount
                unmatched_rows[customer_id] += 1

    total = sum(months.values(), Decimal(0))
    matched_total = total - sum(unmatched.values(), Decimal(0))
    ordered_months = sorted(months)
    changes = [(months[end] - months[start], start, end)
               for start, end in zip(ordered_months, ordered_months[1:])]
    drop = min(changes, default=None)
    top_customers = []
    if drop is not None:
        change, start, end = drop
        ids = customer_months[start].keys() | customer_months[end].keys()
        customer_changes = sorted(
            ((customer_months[end].get(cid, Decimal(0))
              - customer_months[start].get(cid, Decimal(0)), cid) for cid in ids)
        )
        top_customers = [(cid, delta) for delta, cid in customer_changes if delta < 0][:3]
        largest_drop = {
            "from_month": start, "to_month": end, "change": number(change),
            "top_customers": [{"customer_id": cid, "change": number(delta)}
                              for cid, delta in top_customers],
        }
    else:
        largest_drop = {"from_month": None, "to_month": None,
                        "change": None, "top_customers": []}

    summary = {
        "total": number(total), "rows": rows,
        "segments": {key: number(segments[key]) for key in sorted(segments)},
        "months": {key: number(months[key]) for key in ordered_months},
        "largest_drop": largest_drop,
    }
    lines = [
        "# BeaconWorks revenue analysis", "", "## Definitions", "",
        "Revenue is the sum of amount_usd across every transaction, including zero-amount rows. "
        "Segments come from the customer table; missing customers are classified as Unmatched. "
        "Monthly revenue is summed by the month value in the sales file. "
        "The largest drop is the most negative change between consecutive months; "
        "its drivers are the three customers with the most negative changes, "
        "including unmatched customers. A customer absent in either month has zero revenue in that month.",
        "", f"**Total revenue: {money(total)} across {rows:,} transactions.**", "",
        "## Revenue by segment", "",
        "| Segment | Revenue | Share of total | Share of matched revenue |",
        "| --- | ---: | ---: | ---: |",
    ]
    for segment in sorted(segments):
        amount = segments[segment]
        matched_share = "N/A" if segment == "Unmatched" else share(amount, matched_total)
        lines.append(f"| {segment} | {money(amount)} | {share(amount, total)} | {matched_share} |")
    lines += ["", f"Matched revenue is {money(matched_total)}; Unmatched is excluded from that denominator.",
              "", "## Monthly revenue", "", "| Month | Revenue |", "| --- | ---: |"]
    lines += [f"| {month} | {money(months[month])} |" for month in ordered_months]
    lines += ["", "## The largest drop and what drove it", ""]
    if drop is None:
        lines.append("There are fewer than two months, so no month-to-month change can be calculated.")
    elif change >= 0:
        lines.append(f"There was no revenue decline. The smallest change was {money(change)}, "
                     f"from {start} to {end}.")
    else:
        lines.append(f"Revenue fell from {money(months[start])} in {start} to {money(months[end])} "
                     f"in {end}: a change of {money(change)} ({share(change, months[start])}). "
                     "The largest customer declines were:")
        lines += ["", "| Customer | Revenue change |", "| --- | ---: |"]
        for cid, delta in top_customers:
            name = customers[cid]["name"] if cid in customers else "Unmatched"
            lines.append(f"| {cid} — {name} | {money(delta)} |")
        drivers = sum((delta for _, delta in top_customers), Decimal(0))
        lines += ["", f"These customers contributed {money(drivers)} in combined changes; "
                  f"all other customers contributed a net {money(change - drivers)}. "
                  "These are arithmetic contributors; the sales file does not establish the business causes."]
    lines += ["", "## Data notes", "",
              f"All {rows:,} rows were retained, including {zero_rows:,} zero-amount transactions.", ""]
    for cid in sorted(unmatched):
        lines.append(f"- {cid}: {unmatched_rows[cid]:,} transactions totaling {money(unmatched[cid])} "
                     f"({share(unmatched[cid], total)} of total revenue) have no customer-table match.")
    if unmatched:
        lines.append("\nUnmatched revenue remains in the total and monthly figures. Its segment cannot be "
                     "verified from the customer table, so it is reported separately. Excluding it would "
                     "understate revenue; assigning the sales-file segment would bypass the agreed definition. "
                     "The missing customer reference needs reconciliation before segment attribution.")
    else:
        lines.append("Every transaction has a matching customer-table record.")

    output = ROOT / "reports"
    output.mkdir(parents=True, exist_ok=True)
    (output / "revenue_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output / "revenue_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Total revenue: {money(total)} | Rows: {rows:,}")
    for segment in sorted(segments):
        print(f"{segment}: {money(segments[segment])}")
    if drop is not None:
        print(f"Largest month-to-month change: {start} to {end}: {money(change)}")


if __name__ == "__main__":
    main()
