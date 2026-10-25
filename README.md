# BeaconWorks ticket dashboard

A Flask dashboard backed by generated ticket and customer fixtures.
Fixtures are generated; do not edit `src/fixtures/` by hand.

## Run and test

From the repository directory, create and activate an environment outside the repo:

```sh
python3 -m venv ../bw-venv
source ../bw-venv/bin/activate
pip install -r requirements.txt
export PYTHONDONTWRITEBYTECODE=1
python3 tests/test_priority.py && python3 tests/test_customers.py && python3 tests/test_tickets.py && python3 tests/test_health.py && python3 tests/test_summary.py && python3 tests/test_ticket_queries.py
python3 server.py
```

Each test script prints `OK` on success. Open <http://localhost:4000>.
The server defaults to port 4000; the `PORT` environment variable overrides it.
Stop the server with Ctrl+C. Restart it after changing Python code.

## Dashboard page

The page at `/` fetches the array from `GET /api/tickets` and displays ticket ID,
customer ID, subject, category, urgency, status, and **Priority score (beta)**.
Scores appear with exactly two decimal places and are a beta prioritization aid.
The page preserves API ordering and has no score sorting or query filter controls.

Click a customer ID to open the customer account section. The table immediately
shows that customer's tickets from the already loaded list, while the page
requests `GET /api/customers/<customer_id>` for the name and segment.
If that request returns 404, the account section shows
`Customer record not found for <the id>` and keeps the customer's tickets visible.
Other customer request failures show `Unable to load customer <the id>`.
**Show all tickets** closes the account section and restores the full loaded list.

## Ticket API

### Ticket list and queries

`GET /api/tickets` returns a JSON array of ticket objects, with their existing
fields and a computed numeric `priority_score`. There is no `items` wrapper.
Filtering happens first, optional ID sorting second, and pagination last.

Every successful list response includes `X-Total-Count`, the number of matching
tickets before pagination. No matches return `[]` with `X-Total-Count: 0`.
An offset beyond the matching set or `limit=0` returns `[]` while retaining the
count of all matching tickets in the header.

Supported query parameters are all optional:

| Parameter | Values and behavior | Default |
| --- | --- | --- |
| `status` | Exact, case-sensitive match against the ticket's status | All statuses |
| `urgency` | Exact, case-sensitive match against the ticket's urgency | All urgencies |
| `customer_id` | Exact, case-sensitive match against the ticket's customer ID | All customers |
| `sort` | Only `id`, sorting lexicographically by `ticket_id` | Preserve fixture order |
| `order` | `asc` or `desc`; affects ordering only when `sort=id` is supplied | `asc` |
| `limit` | Non-negative integer; `0` returns no records | No limit |
| `offset` | Non-negative integer; number of matching records to skip after sorting | `0` |

Filters combine with AND. Filter values are not validated as enums or ID formats;
unknown values and empty strings are literal matches, usually yielding no results.
Unknown query parameters are ignored. If a parameter is repeated, its first value
is used. Category, text search, date filters, `sort_by`, `page`, and `per_page` are
not supported. Priority scores cannot be used as a sort field.

Invalid `sort` or `order` values, or invalid `limit` or `offset` values, return
HTTP 400 with a JSON object containing only `error`, for example:

```json
{"error": "sort must be id"}
```

`limit` and `offset` accept ASCII digits only, including leading zeros. Signs,
spaces, decimals, exponent notation, and empty strings are rejected.

```sh
curl -i 'http://localhost:4000/api/tickets?status=open&urgency=high&sort=id&order=desc&limit=10&offset=0'
curl -i 'http://localhost:4000/api/tickets?customer_id=CUST-0007'
```

### Single tickets, customer tickets, and summaries

- `GET /api/tickets/<ticket_id>` returns one scored ticket, or HTTP 404 with
  `{"error": "ticket not found"}`.
- `GET /api/customers/<customer_id>/tickets` returns an array of scored tickets
  for that ID, in fixture order. A missing customer record does not prevent
  tickets from being returned. If there are no tickets, the response is `[]`.
- `GET /api/tickets/summary` accepts the same query parameters and validates them
  using the same parser. It counts all filtered matches, ignoring valid sorting
  and pagination options. It does not compute or aggregate priority scores.

The summary response contains `total`, `by_status`, and `by_urgency`. Only statuses
and urgencies present in the filtered tickets appear in the count maps. With no
matches it returns:

```json
{"total": 0, "by_status": {}, "by_urgency": {}}
```

`X-Total-Count` is set on the ticket list response, not on these other responses.

## Priority scoring

The ticket list, single-ticket endpoint, and customer-ticket endpoint calculate
`priority_score` at request time. Each response uses one current UTC timestamp
for all its tickets. Scoring returns copies without changing the loaded source
records or fixture files.

```text
score = urgency_weight * 40 + segment_weight * 30 + days_open_capped * 30 / 14
```

| Urgency | Weight |
| --- | ---: |
| high | 1.0 |
| medium | 0.6 |
| low | 0.3 |

| Customer segment | Weight |
| --- | ---: |
| Enterprise | 1.0 |
| Mid-Market | 0.6 |
| SMB | 0.4 |

The score is a number from 0 to 100, rounded to two decimal places. JSON numbers
do not guarantee trailing zeros; the dashboard formats the displayed value.
An unrecognized urgency or segment has weight zero.

Age is the number of completed 24-hour days since `created_date`, rather than
the number of calendar dates crossed. Creation timestamps without a timezone
are treated as UTC; timestamps with an offset retain that offset. Future dates
contribute zero days. Age is capped at 14 days, so older tickets receive no
additional age points. Ticket status does not alter the age calculation.

If the customer lookup returns no record, the segment contribution is zero.
The ticket still receives urgency and age points and remains available in the
ticket responses and dashboard. For example, a high-urgency ticket open for
7 days with a missing customer scores `40 + 0 + 15 = 55.00`.

### Fixed-date QA matrix

`tests/test_priority.py` uses **2026-10-25 00:00:00 UTC** as the fixed current time.
It generates synthetic tickets in memory for all 3 urgencies, 3 segments, and
ages 0, 7, 14, and 21 days: **36 cases**. The expected scores are fixed reference
values, independent of the production helper:

| Urgency | Segment | 0 days | 7 days | 14 days | 21 days |
| --- | --- | ---: | ---: | ---: | ---: |
| high | Enterprise | 70.00 | 85.00 | 100.00 | 100.00 |
| high | Mid-Market | 58.00 | 73.00 | 88.00 | 88.00 |
| high | SMB | 52.00 | 67.00 | 82.00 | 82.00 |
| medium | Enterprise | 54.00 | 69.00 | 84.00 | 84.00 |
| medium | Mid-Market | 42.00 | 57.00 | 72.00 | 72.00 |
| medium | SMB | 36.00 | 51.00 | 66.00 | 66.00 |
| low | Enterprise | 42.00 | 57.00 | 72.00 | 72.00 |
| low | Mid-Market | 30.00 | 45.00 | 60.00 | 60.00 |
| low | SMB | 24.00 | 39.00 | 54.00 | 54.00 |

The test explicitly checks that the 14-day and 21-day scores match for every
urgency and segment pair. One additional synthetic ticket has customer ID
`CUST-0007`, high urgency, and age 7 days. Its customer lookup returns no record,
and its expected score is **55.00**, bringing the total to **37 cases**.
No generated fixtures are edited. `tests/test_tickets.py` also exercises these
37 reference cases through the enrichment helpers and Flask ticket routes,
checking shared timestamps and preservation of source records.

## Customer details and health

`GET /api/customers/<customer_id>` returns HTTP 200 with the customer's name and
segment when the record exists. For example, `CUST-0029` returns:

```json
{"name": "Dovetail Furniture", "segment": "Enterprise"}
```

If the customer is missing, the route returns HTTP 404 with a JSON error that
includes the requested ID. For `CUST-0007`:

```json
{"error": "customer not found", "customer_id": "CUST-0007"}
```

`CUST-9999` receives the same error shape with its own ID. The route explicitly
checks for `None`; missing customers are not added to the data.
`tests/test_customers.py` checks both missing IDs, the existing `CUST-0029`
response, and that `CUST-0007` tickets remain available.

`GET /api/health` returns `{"status": "ok"}`.
