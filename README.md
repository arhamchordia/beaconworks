# BeaconWorks ticket dashboard

A Flask dashboard backed by generated ticket and customer fixtures.

## Run and test

From the repository directory, create and activate an environment outside the repo:

```sh
python3 -m venv ../bw-venv
source ../bw-venv/bin/activate
pip install -r requirements.txt
export PYTHONDONTWRITEBYTECODE=1
python3 tests/test_priority.py && python3 tests/test_customers.py && python3 tests/test_tickets.py && python3 tests/test_health.py && python3 tests/test_summary.py
python3 server.py
```

Open <http://localhost:4000>. Stop the server with Ctrl+C.

## Ticket API

`GET /api/tickets` filters first, sorts second, and paginates last. It returns:

```json
{"items": [], "total": 0, "page": 1, "per_page": 50, "pages": 0}
```

`items` contains ticket objects with their existing fields. `total` is the count
of all matching tickets before pagination; `pages` is the total page count.
Pages beyond the last page return an empty `items` array while retaining the
matching total. No matches means `total: 0` and `pages: 0`.

**Response migration:** the list endpoint previously returned a bare array.
Clients must now read `response.items`. The bundled dashboard does this.

All parameters are optional and may be supplied once:

| Parameter | Values / behavior | Default |
| --- | --- | --- |
| `status` | `open`, `closed` | All |
| `urgency` | `low`, `medium`, `high` | All |
| `category` | `account`, `api`, `billing`, `bug`, `feature_request`, `performance` | All |
| `customer_id` | Exact ID in the form `CUST-0001`; unknown IDs return no matches | All |
| `q` | Case-insensitive literal substring in subject or body; trimmed, 1–200 characters | All |
| `created_from` | Inclusive lower creation date, `YYYY-MM-DD` | Unbounded |
| `created_to` | Inclusive upper creation date, `YYYY-MM-DD` | Unbounded |
| `sort_by` | `ticket_id`, `customer_id`, `subject`, `category`, `urgency`, `status`, `created_date` | `ticket_id` |
| `order` | `asc`, `desc` | `asc` |
| `page` | Integer from 1 through 999999999 | `1` |
| `per_page` | Integer from 1 through 100 | `50` |

Filters combine with AND. Enum values and customer IDs are case-sensitive.
Date bounds must be real calendar dates, and the lower bound cannot exceed the
upper bound. Sorting uses case-insensitive text, chronological dates, and
low → medium → high urgency; descending reverses the chosen field. Ties always
use ascending ticket IDs to keep pagination stable. Priority scores are not
computed or sortable.

```sh
curl 'http://localhost:4000/api/tickets?status=open&urgency=high&sort_by=created_date&order=desc&page=1&per_page=10'
curl 'http://localhost:4000/api/tickets?q=dashboard&created_from=2026-08-01&created_to=2026-08-31'
```

`GET /api/tickets/summary` accepts and validates exactly the same parameters.
It counts **all filtered matches**, ignoring valid sort and pagination options:

```json
{"total": 0, "by_status": {}, "by_urgency": {}}
```

Only statuses and urgencies present in the matching tickets appear in the
count maps. Use the same filters for the list and summary to keep dashboard
totals consistent:

```sh
curl 'http://localhost:4000/api/tickets/summary?status=open&urgency=high'
```

Both endpoints return HTTP 400 with `{"error": "…", "parameter": "…"}`
for unknown parameters, duplicate parameters, empty/blank values, unsupported
values, malformed numbers or dates, or reversed date bounds. Integers use ASCII
digits only, without signs, spaces, decimals or exponent notation (maximum nine
digits). Invalid status filters now return 400 rather than an empty list.

`GET /api/tickets/<ticket_id>` returns one ticket or a JSON 404 error.
`GET /api/health` returns `{"status": "ok"}`. Customer endpoints are unchanged.
Fixtures are generated; do not edit `src/fixtures/` by hand.
