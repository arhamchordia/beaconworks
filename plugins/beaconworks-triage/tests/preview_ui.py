"""A minimal MCP Apps host, to preview the triage board in your own browser.

It does what a host like ChatGPT does, in one HTML page:
  1. asks the server which UI search_tickets points at (_meta.ui.resourceUri),
  2. reads that ui:// resource and checks its MIME type,
  3. calls search_tickets as the caller in ~/.beaconworks/caller (or BW_CALLER),
  4. writes a page that loads the board in a sandboxed iframe and answers its
     ui/initialize handshake, then sends the tool result.

Run:  python3 plugins/beaconworks-triage/tests/preview_ui.py
Then open the file it prints (on macOS: open ~/.beaconworks/preview.html).
"""
import asyncio
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from mcp import Client  # noqa: E402
from triage_server import mcp  # noqa: E402

APP_MIME_TYPE = "text/html;profile=mcp-app"
OUT = Path.home() / ".beaconworks" / "preview.html"
ARGUMENTS = {"status": "open", "urgency": "high", "limit": 20}

HOST_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Local MCP Apps host: triage board</title>
<style>body{margin:0;padding:16px;background:#e9e6df;font:13px system-ui,sans-serif;color:#1F3A5F}
header{margin-bottom:8px}iframe{width:100%;height:760px;border:1px solid #c9c4b8;border-radius:8px;background:#fff}
#log{margin-top:8px;font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap}</style></head>
<body><header><b>Local MCP Apps host</b>: search_tickets __ARGS__, rendered with __URI__</header>
<iframe id="view" sandbox="allow-scripts allow-same-origin" srcdoc="__SRCDOC__"></iframe>
<div id="log"></div>
<script>
const TOOL_INPUT = __INPUT__;
const TOOL_RESULT = __RESULT__;
const frame = document.getElementById("view");
const log = (line) => { document.getElementById("log").textContent += line + "\\n"; };
const toView = (message) => frame.contentWindow.postMessage({ jsonrpc: "2.0", ...message }, "*");
window.addEventListener("message", (event) => {
  if (event.source !== frame.contentWindow) return;
  const m = event.data || {};
  if (m.method === "ui/initialize") {
    log("view -> host  ui/initialize from " + m.params.appInfo.name + ", protocol " + m.params.protocolVersion);
    toView({ id: m.id, result: { protocolVersion: "2026-01-26", hostInfo: { name: "beaconworks-local-preview", version: "1.0.0" },
                                 hostCapabilities: {}, hostContext: { theme: "light", displayMode: "inline" } } });
  } else if (m.method === "ui/notifications/initialized") {
    log("view -> host  ui/notifications/initialized");
    toView({ method: "ui/notifications/tool-input", params: { arguments: TOOL_INPUT } });
    toView({ method: "ui/notifications/tool-result", params: TOOL_RESULT });
    log("host -> view  ui/notifications/tool-input, ui/notifications/tool-result");
  }
});
</script></body></html>
"""


async def main() -> int:
    async with Client(mcp) as client:
        tool = next(t for t in (await client.list_tools()).tools if t.name == "search_tickets")
        uri = ((tool.meta or {}).get("ui") or {}).get("resourceUri")
        if not uri:
            print("search_tickets has no _meta.ui.resourceUri: there is no UI to preview.")
            return 1
        resource = (await client.read_resource(uri)).contents[0]
        print(f"UI resource: {uri}, {resource.mime_type}, {len(resource.text)} characters")
        if resource.mime_type != APP_MIME_TYPE:
            print(f"Expected {APP_MIME_TYPE}")
            return 1
        result = await client.call_tool("search_tickets", ARGUMENTS)
        if result.is_error:
            print("search_tickets failed:", result.content[0].text)
            return 1
        data = result.structured_content
        print(f"search_tickets: {data['total_matches']} matches, regions {data['visible_regions']}")
    tool_result = {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": False}
    page = (HOST_PAGE.replace("__SRCDOC__", html.escape(resource.text, quote=True))
            .replace("__INPUT__", json.dumps(ARGUMENTS)).replace("__RESULT__", json.dumps(tool_result))
            .replace("__ARGS__", html.escape(json.dumps(ARGUMENTS))).replace("__URI__", html.escape(uri)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print(f"Preview written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
