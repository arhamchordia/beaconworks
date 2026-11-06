"""Release check for the installed beaconworks-triage plugin, headless.

Tests what Codex will really run, not the repo:
  1. the installed version is the version in plugin.json
  2. no config entry shadows the plugin's server
  3. the installed copy has exactly the repo's runtime files (no stale copy)
  4. the server starts exactly as Codex starts it: same command, folder and the few
     environment variables Codex passes, plus PLUGIN_ROOT and PLUGIN_DATA
  5. both tools are there, read-only, with output schemas; a declared UI resolves
  6. a search returns what the caller may see, computed from the plugin's own data
With --with-model, also:
  7. Codex runs the whole workflow (skill, tools, report) with `codex exec`, and the
     report is compared with the same expected values

Run:  python3 plugins/beaconworks-triage/tests/release_check.py [--with-model]
"""
import hashlib
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

PLUGIN = "beaconworks-triage"
PLUGIN_ID = "beaconworks-triage@beaconworks-local"
REPO_PLUGIN = Path(__file__).resolve().parents[1]
APP_MIME_TYPE = "text/html;profile=mcp-app"
CODEX_ENV = ("HOME", "LOGNAME", "PATH", "SHELL", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR", "TZ")
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "beaconworks-release-check", "version": "1.0.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}
PROMPT = ("Use the ticket-triage skill to triage the open high urgency tickets. "
          "Return the report as JSON that matches the output schema. Use [] for gaps if there are none.")

results = []


def check(ok, label, detail=""):
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f": {detail}" if detail else ""))
    return ok


def codex(*args):
    run = subprocess.run([shutil.which("codex") or "codex", *args], capture_output=True, text=True)
    return run.returncode, run.stdout


def files(root: Path) -> dict:
    """Every file Codex can run or read: manifests, server, skills, data. Tests and caches are not compared."""
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.relative_to(root).parts[0] != "tests"}


def expected_view(data_dir: Path, caller: str) -> dict:
    """What the caller should see, computed from the data, independent of the server's code."""
    tickets = json.loads((data_dir / "tickets.json").read_text())
    customers = {c["customer_id"]: c for c in json.loads((data_dir / "customers.json").read_text())}
    regions = json.loads((REPO_PLUGIN / "server" / "access.json").read_text())["callers"][caller]["regions"]
    def visible(t):
        record = customers.get(t["customer_id"])
        return "*" in regions or (record is not None and record["region"] in regions)
    matches = sorted((t for t in tickets if t["status"] == "open" and t["urgency"] == "high" and visible(t)),
                     key=lambda t: t["created_date"], reverse=True)
    newest = [{"ticket_id": t["ticket_id"],
               "customer": customers.get(t["customer_id"], {}).get("name", "not available"),
               "account_owner": customers.get(t["customer_id"], {}).get("account_owner", "not available")}
              for t in matches[:5]]
    return {"regions": regions, "total": len(matches), "by_category": dict(Counter(t["category"] for t in matches)),
            "newest": newest}


class Server:
    def __init__(self, transport):
        env = {k: os.environ[k] for k in CODEX_ENV if k in os.environ} | (transport.get("env") or {})
        self.proc = subprocess.Popen([transport["command"], *transport["args"]], cwd=transport.get("cwd"), env=env,
                                     text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0

    def ask(self, method, params=None, timeout=15):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": {**(params or {}), "_meta": META}}
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except BrokenPipeError:
            raise RuntimeError("the server exited before it could answer")
        ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
        line = self.proc.stdout.readline() if ready else ""
        if not line:
            raise RuntimeError(f"no answer to {method}; last error line: "
                               f"{(self.proc.stderr.read() if self.proc.poll() is not None else '').strip()[-200:]}")
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error']}")
        return reply["result"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


def main() -> int:
    with_model = "--with-model" in sys.argv[1:]
    repo_version = json.loads((REPO_PLUGIN / "plugin.json").read_text())["version"]
    print(f"Release check for {PLUGIN_ID}, repo version {repo_version}\n")

    print("Installed plugin")
    _, out = codex("plugin", "list", "--json")
    installed = next((p for p in json.loads(out or "{}").get("installed", []) if p["pluginId"] == PLUGIN_ID), None)
    if not check(installed and installed["installed"] and installed["enabled"], "installed and enabled"):
        return finish()
    check(installed["version"] == repo_version, "installed version is the repo version",
          f"installed {installed['version']}, repo {repo_version}")

    code, out = codex("mcp", "get", PLUGIN, "--json")
    transport = json.loads(out)["transport"] if code == 0 else {}
    root = Path((transport.get("env") or {}).get("PLUGIN_ROOT", "/nonexistent"))
    check(transport.get("command") == "sh" and "/plugins/cache/" in " ".join(transport.get("args", [])),
          "Codex starts the plugin's server, not a config entry",
          f"command {transport.get('command')} {' '.join(transport.get('args', []))}")
    repo_files, installed_files = files(REPO_PLUGIN), files(root)
    changed = sorted(f for f in repo_files.keys() | installed_files.keys() if repo_files.get(f) != installed_files.get(f))
    check(not changed, "installed copy matches the repo",
          f"{len(changed)} different: {', '.join(changed[:4])}" if changed else f"{len(repo_files)} files, {root}")

    print("\nServer, started exactly as Codex starts it")
    caller_file = Path.home() / ".beaconworks" / "caller"
    caller = caller_file.read_text().strip() if caller_file.is_file() else ""
    if not check(caller, "caller is set", caller or f"no {caller_file}: run server/setup.sh"):
        return finish()
    server = Server(transport)
    try:
        info = server.ask("server/discover")["_meta"]["io.modelcontextprotocol/serverInfo"]
        check(True, "server answers", f"{info['name']} {info['version']}")
        tools = {t["name"]: t for t in server.ask("tools/list")["tools"]}
        check(sorted(tools) == ["get_customer", "search_tickets"], "two tools", ", ".join(sorted(tools)))
        check(all(t.get("outputSchema") and (t.get("annotations") or {}).get("readOnlyHint") for t in tools.values()),
              "both read-only, both with an output schema")
        uri = ((tools.get("search_tickets", {}).get("_meta") or {}).get("ui") or {}).get("resourceUri")
        if uri:
            contents = server.ask("resources/read", {"uri": uri})["contents"][0]
            check(contents.get("mimeType") == APP_MIME_TYPE and "ui/initialize" in contents.get("text", ""),
                  "optional UI resolves", f"{uri}, {contents.get('mimeType')}")
        else:
            print("  INFO  no UI declared (optional)")
        result = server.ask("tools/call", {"name": "search_tickets",
                                           "arguments": {"status": "open", "urgency": "high", "limit": 20}})
        data = result.get("structuredContent") or {}
        want = expected_view(root / "data", caller)
        check(not result.get("isError") and data.get("visible_regions") == want["regions"]
              and data.get("total_matches") == want["total"],
              f"{caller} sees {want['total']} open high urgency tickets", f"server said {data.get('total_matches')}")
    except RuntimeError as error:
        check(False, "server answers", str(error))
        return finish()
    finally:
        server.close()

    if with_model:
        print("\nWhole workflow through Codex (codex exec, with the model)")
        schema = REPO_PLUGIN / "tests" / "triage_report.schema.json"
        with tempfile.TemporaryDirectory() as tmp:
            report_file = Path(tmp) / "report.json"
            # stdin is closed on purpose: with a piped stdin, codex exec waits to append it to the prompt.
            try:
                run = subprocess.run(["codex", "exec", "--ephemeral", "--sandbox", "read-only",
                                      "--output-schema", str(schema), "-o", str(report_file), PROMPT],
                                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                check(False, "Codex returned a JSON report", "codex exec did not finish within 5 minutes")
                return finish()
            text = report_file.read_text() if report_file.is_file() else ""
        try:
            report = json.loads(text)
        except json.JSONDecodeError:
            check(False, "Codex returned a JSON report", f"exit {run.returncode}: {(run.stderr or text).strip()[-200:]}")
            return finish()
        check(True, "Codex returned a JSON report")
        check(report["total_matches"] == want["total"], "total", f"{report['total_matches']}, expected {want['total']}")
        got = {c["category"]: c["count"] for c in report["by_category"]}
        check(got == want["by_category"], "by category", f"{got}, expected {want['by_category']}")
        check([n["ticket_id"] for n in report["newest"]] == [n["ticket_id"] for n in want["newest"]],
              "newest five tickets", ", ".join(n["ticket_id"] for n in report["newest"]))
        check([(n["customer"], n["account_owner"]) for n in report["newest"]]
              == [(n["customer"], n["account_owner"]) for n in want["newest"]], "customers and owners, none guessed")
        check(not report["gaps"], "gaps", ", ".join(report["gaps"]) or "none")
    return finish()


def finish() -> int:
    passed = all(results)
    print(f"\n{'RELEASE CHECK PASSED' if passed else 'RELEASE CHECK FAILED'}: {sum(results)} of {len(results)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
