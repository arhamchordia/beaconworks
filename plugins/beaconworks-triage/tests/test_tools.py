"""Tests for the triage MCP server, through a real MCP client, in-process (no subprocess, no model).

Run:  python3 plugins/beaconworks-triage/tests/test_tools.py
"""
import asyncio
import os
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
os.environ["BW_CALLER"] = "support.lead"  # these tests check the tools; test_access.py checks who sees what

from mcp import Client  # noqa: E402
from triage_server import MAX_RESULTS, mcp  # noqa: E402


async def run(client: Client) -> None:
        tools = {t.name: t for t in (await client.list_tools()).tools}

        # Discovery: two tools, both read-only, both with an input and an output schema.
        assert sorted(tools) == ["get_customer", "search_tickets"], sorted(tools)
        for tool in tools.values():
            assert tool.output_schema, f"{tool.name} has no outputSchema"
            assert tool.annotations and tool.annotations.read_only_hint is True, tool.name
        search_in = tools["search_tickets"].input_schema["properties"]
        assert search_in["limit"]["maximum"] == MAX_RESULTS
        print("OK  discovery: 2 read-only tools, each with an input and an output schema")

        async def call(name, args):
            result = await client.call_tool(name, args)
            if not result.is_error:  # what the spec asks clients to do: check the result against the schema
                jsonschema.validate(result.structured_content, tools[name].output_schema)
            return result

        # A bounded search: total is reported, the page is capped, bodies never leave the server.
        r = await call("search_tickets", {"status": "open", "urgency": "high"})
        data = r.structured_content
        assert not r.is_error
        assert (data["total_matches"], data["returned"], data["truncated"]) == (18, 10, True), data
        assert all("body" not in t for t in data["tickets"])
        dates = [t["created_date"] for t in data["tickets"]]
        assert dates == sorted(dates, reverse=True)
        assert r.content[0].type == "text"  # the same JSON as text, for older clients
        print("OK  search_tickets open + high: 18 matches, 10 returned, truncated, no bodies, newest first")

        r = await call("search_tickets", {"customer_id": "CUST-0007"})
        assert r.structured_content["total_matches"] >= 1 and not r.structured_content["truncated"]
        print(f"OK  search_tickets CUST-0007: {r.structured_content['total_matches']} tickets, even though the customer record is missing")

        # One customer, without the email.
        r = await call("get_customer", {"customer_id": "CUST-0002"})
        assert r.structured_content == {"customer_id": "CUST-0002", "name": "Ballast Analytics", "segment": "Enterprise",
                                       "region": "APAC", "account_owner": "Diego Alves"}, r.structured_content
        print("OK  get_customer CUST-0002: Ballast Analytics, owner Diego Alves, no email")

        # Expected failures come back as tool execution errors the model can read.
        cases = [
            ("get_customer", {"customer_id": "CUST-0007"}, "No customer record available for CUST-0007"),
            ("get_customer", {"customer_id": "0002"}, "pattern"),
            ("search_tickets", {"limit": 500}, "less than or equal to 20"),
            ("search_tickets", {"urgency": "urgent"}, "high"),
        ]
        for name, args, expected in cases:
            r = await call(name, args)
            text = r.content[0].text
            assert r.is_error and expected in text, (name, args, text)
            line = next(l for l in text.splitlines() if expected in l).strip()
            print(f"OK  {name} {args}: isError, \"{line[:90]}\"")


async def main() -> int:
    failure = None
    async with Client(mcp) as client:
        try:
            await run(client)
        except AssertionError as error:  # report it after the client has closed cleanly
            failure = error
    if failure:
        print(f"FAIL {failure}")
        return 1
    print("All triage server tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
