"""Run the BeaconWorks agent like a production system: memory, streaming, hooks, tracing and retries.

The agent is the single design that won the team comparison. What is new is everything around it:
- memory:   SQLiteSession keeps the conversation on disk, so a follow-up works after a restart
- events:   run_streamed shows tool calls as they happen; RunHooks time every tool
- tracing:  every run is a trace (agent, model, function and MCP spans), on the platform's Traces
            page and in a local log we can search
- failures: retries for flaky model calls, and a max_turns handler that answers instead of crashing
- testing:  agent/test_prod_agent.py runs this agent with a scripted model, no API calls

Run:
  python3 agent/prod_agent.py --session may-dip --ask "QUESTION"     a turn in a saved conversation
  python3 agent/prod_agent.py --session may-dip --ask "QUESTION" --stream
  python3 agent/prod_agent.py --session may-dip --history            what the session holds
  python3 agent/prod_agent.py --trace-find 184876                    which span of the last trace has it
Options: --inject-bug (an off-by-one month_total), --max-turns N, --effort none|low|medium|high
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from agents import (Agent, ModelRetryBackoffSettings, ModelRetrySettings, ModelSettings, RunHooks, Runner,
                    SQLiteSession, add_trace_processor, custom_span, function_tool, retry_policies, trace)
from agents.items import ItemHelpers
from agents.run_error_handlers import RunErrorHandlerInput, RunErrorHandlerResult
from agents.tracing import TracingProcessor, get_current_trace

import team
from revenue_facts import REPO, month_totals, months
from team import CALLER, Answer, expectations, grade, single_design
from tool_agent import explain_error, triage_server

HOME = Path.home() / ".beaconworks"
SESSIONS = HOME / "sessions.db"
TRACE_LOG = HOME / "traces.jsonl"
FOLLOW_UP = "Which support tickets does that customer have?"


def known_questions() -> dict[str, dict]:
    """Questions whose right answer our code knows. The follow-up names no customer on purpose."""
    may, _, _, _, mixed = expectations()
    return {may["q"]: may, FOLLOW_UP: {"customers": mixed["customers"], "tickets": mixed["tickets"]}}


# ---------- Tracing: keep the platform exporter, and also write every span to a local log ----------

class LocalSpanLog(TracingProcessor):
    def __init__(self, path: Path):
        self.path = path

    def on_trace_start(self, trace) -> None:
        self._write({"trace_id": trace.trace_id, "type": "trace", "data": {"name": trace.name}})

    def on_trace_end(self, trace) -> None:
        pass

    def on_span_start(self, span) -> None:
        pass

    def on_span_end(self, span) -> None:
        self._write({"trace_id": span.trace_id, "span_id": span.span_id, "parent_id": span.parent_id,
                     "type": span.span_data.type, "data": span.span_data.export(),
                     "started_at": span.started_at, "ended_at": span.ended_at})

    def _write(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def shutdown(self) -> None:
        pass

    def force_flush(self) -> None:
        pass


def spans_of(trace_id: str) -> list[dict]:
    if not TRACE_LOG.exists():
        return []
    rows = (json.loads(line) for line in TRACE_LOG.read_text().splitlines())
    return [r for r in rows if r["trace_id"] == trace_id and r["type"] != "trace"]


def span_label(r: dict) -> str:
    d = r["data"]
    if r["type"] == "function":
        server = (d.get("mcp_data") or {}).get("server")
        return f"function {d['name']}{f' (MCP {server})' if server else ''}"
    if r["type"] == "mcp_tools":
        return f"mcp_tools {d.get('server')}: {d.get('result')}"
    name = d.get("name") or ""
    return r["type"] if name in ("", r["type"]) else f"{r['type']} {name}"


# ---------- Hooks: one line per tool, with its duration ----------

class TimingHooks(RunHooks):
    def __init__(self):
        self.started: dict[str, float] = {}

    async def on_tool_start(self, context, agent, tool) -> None:
        self.started[getattr(context, "tool_call_id", tool.name)] = time.perf_counter()

    async def on_tool_end(self, context, agent, tool, result) -> None:
        start = self.started.pop(getattr(context, "tool_call_id", tool.name), time.perf_counter())
        ms = (time.perf_counter() - start) * 1000
        print(f"  hook: {tool.name} finished in {ms:.0f} ms")


# ---------- Failures: retries for the model call, and an answer when turns run out ----------

RETRY = ModelRetrySettings(
    max_retries=2,
    backoff=ModelRetryBackoffSettings(initial_delay=1.0, max_delay=8.0, multiplier=2.0, jitter=True),
    policy=retry_policies.any(retry_policies.provider_suggested(), retry_policies.network_error(),
                              retry_policies.http_status([429, 500, 502, 503])),
)


def out_of_turns(data: RunErrorHandlerInput) -> RunErrorHandlerResult:
    answer = Answer(answer="I could not finish within the turn limit, so I have no checked answer. "
                           "Please ask again or raise the limit.", customer_ids=[], ticket_ids=[], key_numbers=[])
    return RunErrorHandlerResult(final_output=answer, include_in_history=False)  # keep the session clean


# ---------- A deliberate bug, to find with the trace ----------

@function_tool(name_override="month_total", failure_error_function=explain_error)
def month_total_with_bug(month: str) -> int:
    """Total revenue in USD for one month.

    Args:
        month: The month as YYYY-MM, for example 2026-05.
    """
    all_months = months()
    return month_totals()[all_months[all_months.index(month) - 1]]  # the bug: off by one month


def build_agent(server, inject_bug: bool) -> Agent:
    agent = single_design(server)
    tools = [month_total_with_bug if t.name == "month_total" and inject_bug else t for t in agent.tools]
    return agent.clone(tools=tools, model_settings=agent.model_settings.resolve(ModelSettings(retry=RETRY)))


# ---------- Modes ----------

async def ask(question: str, session_id: str, stream: bool, inject_bug: bool, max_turns: int) -> int:
    session = SQLiteSession(session_id, db_path=SESSIONS)
    print(f"Session {session_id}: {len(await session.get_items())} item(s) before this turn")
    server = triage_server(CALLER)
    async with server:
        agent = build_agent(server, inject_bug)
        with trace("BeaconWorks analyst", group_id=session_id, metadata={"caller": CALLER, "bug": str(inject_bug)}):
            trace_id = get_current_trace().trace_id
            if stream:
                result = Runner.run_streamed(agent, question, session=session, max_turns=max_turns,
                                             error_handlers={"max_turns": out_of_turns})
                async for event in result.stream_events():
                    if event.type == "run_item_stream_event" and event.name == "tool_called":
                        print(f"  event: tool_called {event.item.raw_item.name}({event.item.raw_item.arguments})")
                    elif event.type == "run_item_stream_event" and event.name == "tool_output":
                        print(f"  event: tool_output {str(event.item.output)[:70]}")
                    elif event.type == "run_item_stream_event" and event.name == "message_output_created":
                        print(f"  event: message_output_created ({len(ItemHelpers.text_message_output(event.item))} chars)")
            else:
                result = await Runner.run(agent, question, session=session, max_turns=max_turns,
                                          hooks=TimingHooks(), error_handlers={"max_turns": out_of_turns})
            answer = result.final_output_as(Answer)
            want = known_questions().get(question)
            with custom_span("code checks", data={"question": question}):
                problems = grade(answer, want) if want else None

    print(f"\n{answer.model_dump_json(indent=2)}")
    usage = result.context_wrapper.usage
    print(f"\nUsage: {usage.requests} request(s), {usage.input_tokens} input and {usage.output_tokens} output tokens")
    for n, entry in enumerate(usage.request_usage_entries, 1):
        print(f"  request {n}: {entry.input_tokens} in, {entry.output_tokens} out")
    print(f"Session {session_id}: {len(await session.get_items())} item(s) after this turn")

    spans = spans_of(trace_id)
    print(f"\nTrace {trace_id}, {len(spans)} spans (also on https://platform.openai.com/traces):")
    for label in sorted({span_label(s) for s in spans}):
        print(f"  {label}")
    has_function = any(s["type"] == "function" for s in spans)
    has_mcp = any(s["type"] == "mcp_tools" for s in spans)
    print(f"  {'PASS' if has_function and has_mcp else 'FAIL'}  trace has function spans and the MCP server's span")

    if problems is None:
        print("\nNo known answer for this question, so no answer checks.")
        return 0
    print("\nChecks (computed in code):")
    print("  PASS  answer matches the data" if not problems else "\n".join(f"  FAIL  {p}" for p in problems))
    return 0 if not problems else 1


async def history(session_id: str) -> int:
    items = await SQLiteSession(session_id, db_path=SESSIONS).get_items()
    print(f"Session {session_id}: {len(items)} item(s)")
    for item in items:
        kind = item.get("type") or "message"
        role = item.get("role", "")
        name = item.get("name", "")
        print(f"  {kind:<22} {role:<10} {name}")
    return 0


def trace_find(value: str) -> int:
    if not TRACE_LOG.exists():
        print("No local trace log yet. Run --ask first.")
        return 1
    last = [json.loads(line) for line in TRACE_LOG.read_text().splitlines()][-1]["trace_id"]
    hits = [s for s in spans_of(last) if value in json.dumps(s["data"], default=str)]
    print(f"Spans in trace {last} that contain {value}:")
    for s in sorted(hits, key=lambda s: s["started_at"] or ""):
        d = s["data"]
        if s["type"] == "function":
            print(f"  function {d['name']}  input {d['input']}  output {d['output']}")
        else:
            print(f"  {s['type']} {d.get('name') or ''}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="may-dip")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--inject-bug", action="store_true")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--effort", default="low", choices=["none", "low", "medium", "high"])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ask", metavar="QUESTION")
    mode.add_argument("--history", action="store_true")
    mode.add_argument("--trace-find", metavar="VALUE")
    args = parser.parse_args()
    team.EFFORT = args.effort

    if args.history:
        return asyncio.run(history(args.session))
    if args.trace_find:
        return trace_find(args.trace_find)
    load_dotenv(REPO / "analyst" / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. It is read from analyst/.env, as in the API lessons.")
        return 1
    add_trace_processor(LocalSpanLog(TRACE_LOG))  # in addition to the default exporter to the platform
    return asyncio.run(ask(args.ask, args.session, args.stream, args.inject_bug, args.max_turns))


if __name__ == "__main__":
    sys.exit(main())
