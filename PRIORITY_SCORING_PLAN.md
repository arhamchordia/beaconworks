# Priority Scoring

## Agreed behavior

Every ticket response will include numeric `priority_score` from 0–100:

`urgency_weight × 40 + segment_weight × 30 + min(days_open, 14) × 30 / 14`

Retain the existing weights, completed 24-hour days, zero age for future dates, and two-decimal rounding. Missing customers contribute zero segment points. Calculate scores at request time using one UTC timestamp per response.

The dashboard will display a **Priority score** column with two decimals and retain existing ordering.

## Ordered implementation and checks

1. **Verify scoring with a fixed-date QA matrix.**  
   Files: `src/lib/priority.py`, `tests/test_priority.py`.  
   Retain the existing formula and injectable clock; clarify missing-segment behavior. Use **2026-10-25 00:00:00 UTC** as the fixed current date. Generate synthetic tickets covering every combination of:

   - Urgency: high, medium, low.
   - Segment: Enterprise, Mid-Market, SMB.
   - Age: 0, 7, 14, 21 days.

   This produces **36 cases**, plus **one 7-day-old, high-urgency ticket for missing customer `CUST-0007`**, for **37 cases total**. Use in-memory records without editing fixtures.

   **Check:** Assert independently calculated expected scores. Verify 14-day and 21-day scores match for each urgency/segment pair. The missing-customer ticket must score **55.00**.

2. **Add reusable ticket enrichment.**  
   File: `src/lib/tickets.py`.  
   Add helpers that look up each ticket’s customer and return copied ticket objects containing `priority_score`. Handle missing customers without dereferencing `None`. Preserve original records and generated fixtures.

   **Check:** Use the fixed-date records to verify customer lookup, score bounds, a shared timestamp per batch, and unchanged source records.

3. **Connect all ticket responses.**  
   Files: `server.py`, `tests/test_tickets.py`, `tests/test_ticket_queries.py`.  
   Keep routes thin and call the enrichment helpers for:

   - `GET /api/tickets`
   - `GET /api/tickets/<ticket_id>`
   - `GET /api/customers/<customer_id>/tickets`

   Preserve the list’s array response, existing fields, filters, ordering, pagination, `X-Total-Count`, and summary behavior. Update existing exact-response assertions for the added field.

   **Check:** Use Flask’s test client with synthetic records and the same fixed clock. Verify exact scores, existing 404 behavior, empty results, query compatibility, and successful ticket responses for `CUST-0007`.

4. **Display the score.**  
   Files: `public/index.html`, `tests/test_tickets.py`.  
   Fix the page’s existing response mismatch by reading the returned array directly. Add the score header and cells, formatted to two decimals; update the introductory text.

   **Check:** Add a page-route assertion for the column. In the running dashboard, verify tickets render, displayed scores match the API, and missing-customer tickets remain visible without browser errors.

5. **Document QA and complete verification.**  
   File: `README.md`.  
   Document the score field, formula, age rules, missing-customer fallback, fixed-date matrix, and actual existing API contract. Remove conflicting claims about response format and supported queries.

   **Check:** Run the full required command:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 tests/test_priority.py && \
   PYTHONDONTWRITEBYTECODE=1 python3 tests/test_customers.py && \
   PYTHONDONTWRITEBYTECODE=1 python3 tests/test_tickets.py && \
   PYTHONDONTWRITEBYTECODE=1 python3 tests/test_health.py && \
   PYTHONDONTWRITEBYTECODE=1 python3 tests/test_summary.py && \
   PYTHONDONTWRITEBYTECODE=1 python3 tests/test_ticket_queries.py
   ```

   Confirm all six print `OK`. Start the server on port 4000, verify `/api/tickets` returns HTTP 200 and scores, then inspect the dashboard. Present the Git diff and changed-file list.

## QA reference values

| Urgency | Segment | 0 days | 7 days | 14 days | 21 days |
|---|---|---:|---:|---:|---:|
| High | Enterprise | 70.00 | 85.00 | 100.00 | 100.00 |
| High | Mid-Market | 58.00 | 73.00 | 88.00 | 88.00 |
| High | SMB | 52.00 | 67.00 | 82.00 | 82.00 |
| Medium | Enterprise | 54.00 | 69.00 | 84.00 | 84.00 |
| Medium | Mid-Market | 42.00 | 57.00 | 72.00 | 72.00 |
| Medium | SMB | 36.00 | 51.00 | 66.00 | 66.00 |
| Low | Enterprise | 42.00 | 57.00 | 72.00 | 72.00 |
| Low | Mid-Market | 30.00 | 45.00 | 60.00 | 60.00 |
| Low | SMB | 24.00 | 39.00 | 54.00 | 54.00 |

The additional `CUST-0007` case is high urgency, 7 days old, with expected score **55.00**.

## Out of scope

- Editing or regenerating fixtures.
- Fixing the separate customer-details route crash.
- Score sorting, filtering, colors, or interactive QA controls.
- New endpoints, persisted scores, or summary score aggregates.
- Changing age calculations based on ticket status.
