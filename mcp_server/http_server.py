"""The same BeaconWorks MCP server, over Streamable HTTP, with a bearer token.

stdio needs no login: only the program that started the server can talk to it.
Over HTTP, anything that can reach the port can talk to it, so every request
must carry   Authorization: Bearer <token>   with the token in BW_MCP_TOKEN.

It listens on 127.0.0.1 only, never on the network.

Run:
  export BW_MCP_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  python3 mcp_server/http_server.py
Then the endpoint is http://127.0.0.1:8765/mcp
"""
import hmac
import json
import os
import sys

import uvicorn

from server import mcp  # the same tools, resources and prompt as the stdio server

HOST, PORT = "127.0.0.1", 8765
TOKEN = os.environ.get("BW_MCP_TOKEN", "")


class RequireBearerToken:
    """Refuse any HTTP request that does not carry exactly our token."""

    def __init__(self, app, token: str):
        self.app, self.expected = app, f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            sent = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(sent, self.expected):  # constant time, no timing hints
                print(f"refused {scope['method']} {scope['path']}: {'wrong' if sent else 'no'} token", flush=True)
                body = json.dumps({"error": "unauthorized"}).encode()
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="beaconworks"')]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


if __name__ == "__main__":
    if len(TOKEN) < 32:
        sys.exit("Set BW_MCP_TOKEN to a long random token first (see the top of this file).")
    app = RequireBearerToken(mcp.streamable_http_app(host=HOST), TOKEN)
    print(f"BeaconWorks MCP over HTTP on http://{HOST}:{PORT}/mcp, token required", flush=True)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
