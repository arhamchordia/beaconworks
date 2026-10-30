# BeaconWorks revenue analysis

## Definitions

Revenue is the sum of amount_usd across every transaction, including zero-amount rows. Segments come from the customer table; missing customers are classified as Unmatched. Monthly revenue is summed by the month value in the sales file. The largest drop is the most negative change between consecutive months; its drivers are the three customers with the most negative changes, including unmatched customers. A customer absent in either month has zero revenue in that month.

**Total revenue: $3,284,340.0 across 540 transactions.**

## Revenue by segment

| Segment | Revenue | Share of total | Share of matched revenue |
| --- | ---: | ---: | ---: |
| Enterprise | $1,103,106.0 | 33.6% | 34.3% |
| Mid-Market | $989,601.0 | 30.1% | 30.7% |
| SMB | $1,127,017.0 | 34.3% | 35.0% |
| Unmatched | $64,616.0 | 2.0% | N/A |

Matched revenue is $3,219,724.0; Unmatched is excluded from that denominator.

## Monthly revenue

| Month | Revenue |
| --- | ---: |
| 2025-04 | $183,665.0 |
| 2025-05 | $181,918.0 |
| 2025-06 | $183,979.0 |
| 2025-07 | $185,137.0 |
| 2025-08 | $182,917.0 |
| 2025-09 | $184,188.0 |
| 2025-10 | $182,724.0 |
| 2025-11 | $185,403.0 |
| 2025-12 | $184,511.0 |
| 2026-01 | $184,902.0 |
| 2026-02 | $182,203.0 |
| 2026-03 | $182,264.0 |
| 2026-04 | $184,876.0 |
| 2026-05 | $180,118.0 |
| 2026-06 | $177,534.0 |
| 2026-07 | $178,639.0 |
| 2026-08 | $179,121.0 |
| 2026-09 | $180,241.0 |

## The largest drop and what drove it

Revenue fell from $184,876.0 in 2026-04 to $180,118.0 in 2026-05: a change of -$4,758.0 (-2.6%). The largest customer declines were:

| Customer | Revenue change |
| --- | ---: |
| CUST-0007 — Unmatched | -$5,101.0 |
| CUST-0016 — Pinnacle Energy | -$410.0 |
| CUST-0010 — Juniper Health Systems | -$361.0 |

These customers contributed -$5,872.0 in combined changes; all other customers contributed a net $1,114.0. These are arithmetic contributors; the sales file does not establish the business causes.

## Data notes

All 540 rows were retained, including 5 zero-amount transactions.

- CUST-0007: 18 transactions totaling $64,616.0 (2.0% of total revenue) have no customer-table match.

Unmatched revenue remains in the total and monthly figures. Its segment cannot be verified from the customer table, so it is reported separately. Excluding it would understate revenue; assigning the sales-file segment would bypass the agreed definition. The missing customer reference needs reconciliation before segment attribution.
