"""Show the three kinds of capability this MCP server offers, with one real example of each.

  tools      model-controlled        the model decides when to call one
  resources  application-controlled  the host decides what to attach, by URI
  prompts    user-controlled         the user picks one, like a slash command

Uses the stdio client from trace.py, quietly. Run: python3 mcp_server/capabilities.py
"""
import json
import sys

from trace import StdioClient

TICKET = "TICKET-0008"


def subject_of(text: str) -> str:
    return json.loads(text)["subject"]


def main() -> int:
    client = StdioClient(verbose=False)
    try:
        tools = client.request("tools/list", {})["result"]["tools"]
        resources = client.request("resources/list", {})["result"]["resources"]
        templates = client.request("resources/templates/list", {})["result"]["resourceTemplates"]
        prompts = client.request("prompts/list", {})["result"]["prompts"]

        print("TOOLS      model-controlled: the model decides when to call one")
        for tool in tools:
            print(f"  {tool['name']}({', '.join(tool['inputSchema'].get('properties', {}))})")
        print("RESOURCES  application-controlled: the host decides what to attach")
        for resource in resources:
            print(f"  {resource['uri']}  [{resource['mimeType']}]  {resource['title']}")
        for template in templates:
            print(f"  {template['uriTemplate']}  [{template['mimeType']}]  {template['title']}  (template)")
        print("PROMPTS    user-controlled: the user picks one, like a slash command")
        for prompt in prompts:
            arguments = ", ".join(a["name"] + (" (required)" if a.get("required") else "") for a in prompt.get("arguments", []))
            print(f"  {prompt['name']}({arguments})  {prompt['title']}")

        print(f"\nSame ticket, two shapes:")
        call = client.request("tools/call", {"name": "lookup_ticket", "arguments": {"ticket_id": TICKET}})["result"]
        print(f"  tool call      lookup_ticket -> content[0].type {call['content'][0]['type']}, isError {call['isError']}, "
              f"subject \"{subject_of(call['content'][0]['text'])}\"")
        read = client.request("resources/read", {"uri": f"beaconworks://tickets/{TICKET}"})["result"]["contents"][0]
        print(f"  resource read  {read['uri']} -> mimeType {read['mimeType']}, subject \"{subject_of(read['text'])}\"")

        policy = client.request("resources/read", {"uri": "beaconworks://policies/approval"})["result"]["contents"][0]
        print(f"\nA document as a resource: {policy['uri']} [{policy['mimeType']}]")
        print("  " + "\n  ".join(policy["text"].splitlines()[:3]))

        got = client.request("prompts/get", {"name": "triage_ticket", "arguments": {"ticket_id": TICKET}})["result"]
        print(f"\nA prompt, filled in: triage_ticket({TICKET}) returns {len(got['messages'])} message(s)")
        for message in got["messages"]:
            print(f"  [{message['role']}] {message['content']['text']}")

        print("\nWhen something is wrong:")
        missing = client.request("resources/read", {"uri": "beaconworks://tickets/TICKET-0099"}, allow_error=True)
        print(f"  resources/read TICKET-0099 -> error {missing['error']['code']}: {missing['error']['message']}")
        bad = client.request("prompts/get", {"name": "triage_ticket", "arguments": {"ticket_id": "8"}}, allow_error=True)
        print(f"  prompts/get ticket_id \"8\" -> error {bad['error']['code']}: {bad['error']['message']}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
