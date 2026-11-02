"""
BeaconWorks MCP server -- read-only ticket and customer lookup tools.

Used for:
  21.1 Trace an MCP tool invocation (read-only ticket lookup)
  21.2 Distinguish capabilities (tools/resources/prompts)
  21.3 Connect and test a server in Codex
  21.4 Inspect authentication and trust (denied access, untrusted result)
  22.1 Build read-only Python tools
  22.2 Validate and enforce access rules
  22.3 Package a skill and server (ticket-triage plugin, Project 7)
  22.4 Add optional UI and test the workflow (headless-safe)

Deliberately read-only: no tool here can write. Any "reply" or "action"
lesson (9.x, 19.4, 25.4) goes through the approval flow in the ticket
dashboard app, not through this server -- keep that boundary visible on
screen, it's the point of lesson 21.4.

Requires: pip install mcp
"""
import json
import os

from mcp.server.mcpserver import MCPServer

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "fixtures")

with open(os.path.join(DATA_DIR, "customers.json")) as f:
    CUSTOMERS = json.load(f)
with open(os.path.join(DATA_DIR, "tickets.json")) as f:
    TICKETS = json.load(f)

mcp = MCPServer("beaconworks-ticket-triage", version="1.0.0")


@mcp.tool()
def lookup_ticket(ticket_id: str) -> dict:
    """Read-only lookup of a single support ticket by id (e.g. TICKET-0008)."""
    for t in TICKETS:
        if t["ticket_id"] == ticket_id:
            return t
    return {"error": f"ticket {ticket_id} not found"}


@mcp.tool()
def lookup_customer(customer_id: str) -> dict:
    """
    Read-only lookup of a customer by id (e.g. CUST-0001).

    Lesson 21.4 / 22.2 case: CUST-0007 is a valid-looking id that is
    deliberately absent from the customer table (see AGENTS.md and
    tests/test_customers.py in the parent repo for the same seeded gap).
    This tool must return a clean "not found" result for it, never a
    fabricated record and never an unhandled exception -- that is exactly
    what 22.2's "reject malformed queries and unauthorized records"
    validation lesson checks.
    """
    for c in CUSTOMERS:
        if c["customer_id"] == customer_id:
            return c
    return {"error": f"customer {customer_id} not found"}


@mcp.tool()
def search_tickets(category: str = "", urgency: str = "") -> list:
    """Read-only search over tickets by category and/or urgency. Empty
    filters return everything. No write parameters exist on this tool by
    design (lesson 21.1's trust boundary)."""
    results = TICKETS
    if category:
        results = [t for t in results if t["category"] == category]
    if urgency:
        results = [t for t in results if t["urgency"] == urgency]
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")
