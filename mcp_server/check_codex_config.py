"""Check that Codex can start the BeaconWorks MCP server, exactly as Codex is configured to.

It reads the server's entry with `codex mcp get <name> --json` (so it sees what
Codex sees, from ~/.codex/config.toml), then starts that exact command from
your home folder, not from this repo. Codex can start the server from another
folder, for example when you open a different project, so the command must not
depend on where you happen to be.

Then it asks the server who it is and which tools it has, and compares that
with enabled_tools.

Run:
  python3 mcp_server/check_codex_config.py               checks the server named beaconworks
  python3 mcp_server/check_codex_config.py other-name    checks another configured server
"""
import json
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

PROTOCOL_VERSION = "2026-07-28"  # same revision as trace.py: no handshake, _meta on every request
META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "beaconworks-config-check", "version": "1.0.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}

results = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f": {detail}" if detail else ""))
    return ok


def read_config(name: str) -> dict:
    codex = shutil.which("codex")
    if not codex:
        raise SystemExit("codex is not on your PATH. Install the Codex CLI first.")
    run = subprocess.run([codex, "mcp", "get", name, "--json"], capture_output=True, text=True)
    if run.returncode != 0:
        raise SystemExit(f"Codex has no MCP server named {name}. Add it with codex mcp add first.")
    return json.loads(run.stdout)


def ask(server: subprocess.Popen, request_id: int, method: str, timeout: float) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {"_meta": META}}
    try:
        server.stdin.write(json.dumps(message) + "\n")
        server.stdin.flush()
    except BrokenPipeError:
        raise RuntimeError("the server exited before it could answer")
    ready, _, _ = select.select([server.stdout], [], [], timeout)
    line = server.stdout.readline() if ready else ""
    if not line:
        if server.poll() is not None:
            raise RuntimeError(f"the server exited with code {server.returncode} before answering {method}")
        raise RuntimeError(f"no answer to {method} within {timeout:g}s")
    return json.loads(line)


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "beaconworks"
    config = read_config(name)
    transport = config["transport"]
    command, args = transport.get("command"), transport.get("args") or []
    cwd = transport.get("cwd")
    start_in = cwd or str(Path.home())
    timeout = float(config.get("startup_timeout_sec") or 10)

    print(f"Codex config for '{name}':")
    print(f"  command  {command}")
    print(f"  args     {' '.join(args)}")
    print(f"  cwd      {cwd or '(not set)'}")
    print(f"  enabled_tools  {', '.join(config['enabled_tools']) if config.get('enabled_tools') else '(not set: every tool)'}")
    print("\nChecks:")

    if not check(transport.get("type") == "stdio", "stdio transport", transport.get("type", "")):
        return 1
    absolute = os.path.isabs(command or "")
    check(absolute, "command is a full path",
          "" if absolute else f"'{command}' is looked up on the PATH of whatever starts it, which may not be your venv")
    script_args = [a for a in args if a.endswith(".py")]
    for arg in script_args:
        path = Path(arg) if os.path.isabs(arg) else Path(start_in) / arg
        check(path.is_file(), f"server file exists from {start_in}", str(path))

    print(f"\nStarting the server from {start_in} ...")
    env = {**os.environ, **(transport.get("env") or {})}
    try:
        server = subprocess.Popen([command, *args], cwd=start_in, env=env, text=True,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as error:
        check(False, "server starts", str(error))
        return 1
    try:
        discover = ask(server, 1, "server/discover", timeout)
        listing = ask(server, 2, "tools/list", timeout)
    except RuntimeError as error:
        server.kill()
        last_error = server.stderr.read().strip().splitlines()[-1:] or ["(no error output)"]
        check(False, "server answers", f"{error}. Its last error line: {last_error[0]}")
        return 1
    server.stdin.close()
    server.wait(timeout=10)

    info = discover["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]
    check(True, "server answers", f"{info['name']} {info['version']}")
    offered = [tool["name"] for tool in listing["result"]["tools"]]
    enabled = config.get("enabled_tools")
    disabled = config.get("disabled_tools") or []
    if enabled:
        unknown = [tool for tool in enabled if tool not in offered]
        check(not unknown, "every name in enabled_tools exists on the server",
              f"unknown: {', '.join(unknown)} (a typo hides a tool without any error)" if unknown else "")
    visible = [t for t in offered if (not enabled or t in enabled) and t not in disabled]
    hidden = [t for t in offered if t not in visible]

    print(f"\nTools on the server:   {', '.join(offered)}")
    print(f"Codex will offer:      {', '.join(visible) or '(none)'}")
    print(f"Hidden from the model: {', '.join(hidden) or '(none)'}")
    passed = all(results)
    print(f"\n{'All checks passed' if passed else 'Some checks failed'}: {sum(results)} of {len(results)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
