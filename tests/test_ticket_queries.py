import sys
import os
from collections import Counter
from copy import deepcopy
from itertools import combinations
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import app
from src.lib.tickets import list_tickets, parse_ticket_query


def expected_summary(tickets):
    return {"total": len(tickets),
            "by_status": dict(Counter(t["status"] for t in tickets)),
            "by_urgency": dict(Counter(t["urgency"] for t in tickets))}


def check_list(client, query, expected, total):
    response = client.get("/api/tickets", query_string=query)
    assert response.status_code == 200, query
    assert response.mimetype == "application/json"
    assert response.get_json() == expected, query
    assert response.headers["X-Total-Count"] == str(total), query


with app.test_client() as client:
    tickets = list_tickets()
    assert tickets
    check_list(client, {}, tickets, len(tickets))
    filters = {key: tickets[0][key] for key in ("status", "urgency", "customer_id")}
    for size in (1, 2, 3):
        for keys in combinations(filters, size):
            query = {key: filters[key] for key in keys}
            matched = [t for t in tickets if all(t[key] == value for key, value in query.items())]
            assert matched
            check_list(client, query, matched, len(matched))
            descending = sorted(matched, key=lambda t: t["ticket_id"], reverse=True)
            check_list(client, dict(query, sort="id", order="desc", offset=1, limit=2),
                       descending[1:3], len(matched))
            for options in (query, dict(query, sort="id", order="desc", offset=999, limit=0)):
                response = client.get("/api/tickets/summary", query_string=options)
                assert response.status_code == 200
                assert response.get_json() == expected_summary(matched)

    for key in filters:
        for value in ("no-match", ""):
            query = {key: value}
            check_list(client, query, [], 0)
            response = client.get("/api/tickets/summary", query_string=query)
            assert response.status_code == 200
            assert response.get_json() == expected_summary([])

    ascending = sorted(tickets, key=lambda t: t["ticket_id"])
    check_list(client, {"sort": "id"}, ascending, len(tickets))
    check_list(client, {"sort": "id", "order": "asc"}, ascending, len(tickets))
    check_list(client, {"sort": "id", "order": "desc"}, ascending[::-1], len(tickets))
    for query, expected in (
        ({"limit": 2}, tickets[:2]),
        ({"offset": 2}, tickets[2:]),
        ({"limit": 2, "offset": 1}, tickets[1:3]),
        ({"limit": 0}, []),
        ({"offset": 0}, tickets),
        ({"offset": len(tickets)}, []),
        ({"offset": 10**30}, []),
        ({"limit": 10**30}, tickets),
    ):
        check_list(client, query, expected, len(tickets))

    invalid_queries = [{"sort": value} for value in ("ticket_id", "urgency", "", "ID")]
    invalid_queries += [{"order": value} for value in ("up", "ASC", "", "descending")]
    for key in ("limit", "offset"):
        invalid_queries += [{key: value} for value in
                            ("-1", "1.5", "abc", "", " 1", "+1", "1e2", "١", "1\n")]
    for query in invalid_queries:
        try:
            parse_ticket_query(query)
        except ValueError:
            pass
        else:
            assert False, query
        for endpoint in ("/api/tickets", "/api/tickets/summary"):
            response = client.get(endpoint, query_string=query)
            assert response.status_code == 400, (endpoint, query)
            assert response.mimetype == "application/json"
            error = response.get_json()
            assert set(error) == {"error"}
            assert isinstance(error["error"], str) and error["error"]

    options = parse_ticket_query({"limit": "02", "offset": "0", "sort": "id"})
    assert options["limit"] == 2 and options["offset"] == 0
    assert options["order"] == "asc"

# Unsorted in-memory records verify that default queries preserve source order
# and explicit sorting never mutates the source. No fixture files are changed.
records = [dict(tickets[0], ticket_id=identifier)
           for identifier in ("TICKET-0003", "TICKET-0001", "TICKET-0002")]
snapshot = deepcopy(records)
with patch("src.lib.tickets.TICKETS", records), app.test_client() as client:
    check_list(client, {}, records, 3)
    check_list(client, {"order": "desc"}, records, 3)
    check_list(client, {"sort": "id", "offset": 1, "limit": 1}, [records[2]], 3)
    check_list(client, {"sort": "id", "order": "desc"},
               [records[0], records[2], records[1]], 3)
    assert records == snapshot

print("test_ticket_queries.py: OK")
