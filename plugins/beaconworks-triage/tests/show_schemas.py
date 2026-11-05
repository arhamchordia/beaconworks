"""Print what an MCP client sees for each tool: description, input schema and output schema.

Run:  python3 plugins/beaconworks-triage/tests/show_schemas.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from mcp import Client  # noqa: E402
from triage_server import mcp  # noqa: E402


def compact(schema):
    """Drop titles and descriptions, keep what a client validates: types, enums, patterns, limits, required."""
    if isinstance(schema, dict):
        return {k: compact(v) for k, v in schema.items() if k not in ("title", "description")}
    if isinstance(schema, list):
        return [compact(item) for item in schema]
    return schema


async def main() -> None:
    async with Client(mcp) as client:
        for tool in (await client.list_tools()).tools:
            print(f"=== {tool.name} ({tool.title})")
            print(tool.description.split(". ")[0] + ".")
            print("input:", json.dumps(compact(tool.input_schema), indent=2))
            print("output:", json.dumps(compact(tool.output_schema), indent=2))
            print()


if __name__ == "__main__":
    asyncio.run(main())
