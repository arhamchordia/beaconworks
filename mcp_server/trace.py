"""Trace one MCP tool call, message by message, with no SDK in the way.

This script plays the host and its MCP client. It starts the BeaconWorks MCP
server as a subprocess (the stdio transport), writes JSON-RPC requests to the
server's stdin, one per line, and reads each response from the server's stdout.

Protocol revision 2026-07-28 has no handshake: every request carries the
protocol version and the client's capabilities in params._meta.

Run:
  python3 mcp_server/trace.py               look up TICKET-0008
  python3 mcp_server/trace.py TICKET-0029   look up another ticket
"""
import json
import subprocess
import sys
from pathlib import Path

PROTOCOL_VERSION = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "beaconworks-trace", "version": "1.0.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}
SERVER_COMMAND = [sys.executable, str(Path(__file__).with_name("server.py"))]


def shorten(value, limit=100):
    """Keep the printed messages readable: long strings are cut, structure is kept."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, list):
        return [shorten(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: shorten(item, limit) for key, item in value.items()}
    return value


def show(direction: str, message: dict) -> None:
    print(f"\n{direction}")
    print(json.dumps(shorten(message), indent=2))


class StdioClient:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose  # False: send and receive the same messages, without printing them
        # The client starts the server. stderr is kept apart: the spec reserves stdout for MCP messages only.
        self.server = subprocess.Popen(SERVER_COMMAND, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
        self.next_id = 1

    def request(self, method: str, params: dict, allow_error: bool = False) -> dict:
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": {**params, "_meta": META}}
        self.next_id += 1
        if self.verbose:
            show(f"client -> server   ({method})", message)
        self.server.stdin.write(json.dumps(message) + "\n")  # one message per line, no newlines inside
        self.server.stdin.flush()
        line = self.server.stdout.readline()
        if not line:
            raise SystemExit("The server exited. Its error output:\n" + self.server.stderr.read())
        reply = json.loads(line)
        if self.verbose:
            show("server -> client", reply)
        if reply.get("id") != message["id"]:
            raise SystemExit(f"Reply id {reply.get('id')} does not match request id {message['id']}.")
        if "error" in reply and not allow_error:
            raise SystemExit(f"\nThe server refused {method}: error {reply['error']['code']}, {reply['error']['message']}")
        return reply

    def close(self) -> int:
        # Graceful shutdown in the stdio transport: close the server's input, then wait for it to exit.
        self.server.stdin.close()
        return self.server.wait(timeout=10)


def main() -> int:
    ticket_id = sys.argv[1] if len(sys.argv) > 1 else "TICKET-0008"
    client = StdioClient()
    try:
        discover = client.request("server/discover", {})
        listing = client.request("tools/list", {})
        call = client.request("tools/call", {"name": "lookup_ticket", "arguments": {"ticket_id": ticket_id}})
    finally:
        exit_code = client.close()

    info = discover["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]
    tools = [tool["name"] for tool in listing["result"]["tools"]]
    result = call["result"]
    data = json.loads(result["content"][0]["text"])
    print("\n--- summary ---")
    print(f"server: {info['name']} {info['version']}, supports {discover['result']['supportedVersions']}")
    print(f"tools offered: {', '.join(tools)}")
    print(f"lookup_ticket({ticket_id}): isError {result['isError']}, "
          f"returned {', '.join(data)}" if "error" not in data else f"lookup_ticket({ticket_id}): {data['error']}")
    print(f"server exited with code {exit_code} after its input was closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
