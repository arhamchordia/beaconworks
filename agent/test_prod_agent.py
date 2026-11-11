"""Offline tests for prod_agent.py: a scripted model plays the model's part. No API key, no network.

The tools are real (our Python functions); only the model is scripted. So these tests check our
wiring, our checks, memory, retries and tracing, not the model's judgment.

Run:  python3 agent/test_prod_agent.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx2  # the HTTP client openai 3.x is built on
from openai import APIConnectionError

from agents import Runner, SQLiteSession, set_trace_processors, trace
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from prod_agent import FOLLOW_UP, LocalSpanLog, build_agent, known_questions
from team import Answer, grade

MAY = "Why did revenue fall in May 2026 compared with April 2026?"
TOOL_STEP = [
    function_call("month_total", {"month": "2026-04"}, call_id="c1"),
    function_call("month_total", {"month": "2026-05"}, call_id="c2"),
    function_call("top_customer_changes", {"previous_month": "2026-04", "month": "2026-05", "limit": 5}, call_id="c3"),
]


def answer(numbers: list[int], customers=("CUST-0007",), tickets=()) -> list:
    text = Answer(answer="Revenue fell, driven by CUST-0007.", customer_ids=list(customers),
                  ticket_ids=list(tickets), key_numbers=numbers).model_dump_json()
    return [assistant_message(text)]


def offline_agent(model: ScriptedModel, inject_bug: bool = False):
    """The production agent with a scripted model and no MCP server."""
    return build_agent(server=None, inject_bug=inject_bug).clone(model=model, mcp_servers=[])


async def test_answer_passes_checks() -> None:
    model = ScriptedModel([TOOL_STEP, answer([-4758, -5101])])
    result = await Runner.run(offline_agent(model), MAY)
    assert grade(result.final_output_as(Answer), known_questions()[MAY]) == []
    assert "180118" in json.dumps(model.last_call.input), "the real tool output went back to the model"
    model.assert_complete()


async def test_wrong_number_is_caught() -> None:
    model = ScriptedModel([TOOL_STEP, answer([-4000])])
    result = await Runner.run(offline_agent(model), MAY)
    assert grade(result.final_output_as(Answer), known_questions()[MAY]) == ["number -4758 missing"]


async def test_session_remembers_the_customer() -> None:
    session = SQLiteSession("test")  # in memory
    model = ScriptedModel([TOOL_STEP, answer([-4758, -5101]), answer([2], tickets=("TICKET-0008", "TICKET-0029"))])
    agent = offline_agent(model)
    await Runner.run(agent, MAY, session=session)
    await Runner.run(agent, FOLLOW_UP, session=session)
    assert "CUST-0007" in json.dumps(model.last_call.input), "the follow-up carried the first turn"
    assert len(await session.get_items()) == 10  # 2 user, 3 calls, 3 outputs, 2 answers


async def test_retry_after_network_error() -> None:
    error = APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
    model = ScriptedModel([ModelStep.raise_error(error), answer([-4758, -5101])])
    result = await Runner.run(offline_agent(model), MAY)
    assert len(model.calls) == 2, "the first call failed and was retried once"
    assert result.final_output_as(Answer).key_numbers == [-4758, -5101]


async def test_trace_has_function_spans() -> None:
    log = Path(tempfile.mkdtemp()) / "traces.jsonl"
    set_trace_processors([LocalSpanLog(log)])  # replaces the platform exporter: nothing leaves this machine
    model = ScriptedModel([TOOL_STEP, answer([-4758, -5101])])
    with trace("offline test"):
        await Runner.run(offline_agent(model), MAY)
    spans = [json.loads(line) for line in log.read_text().splitlines()]
    functions = sorted(s["data"]["name"] for s in spans if s["type"] == "function")
    assert functions == ["month_total", "month_total", "top_customer_changes"], functions
    assert any(s["type"] == "agent" for s in spans)


async def test_injected_bug_returns_april() -> None:
    model = ScriptedModel([[function_call("month_total", {"month": "2026-05"}, call_id="c1")], answer([0])])
    await Runner.run(offline_agent(model, inject_bug=True), MAY)
    sent_back = json.dumps(model.last_call.input)
    assert "184876" in sent_back and "180118" not in sent_back, "May was answered with April's total"


async def main() -> int:
    failed = 0
    for test in (test_answer_passes_checks, test_wrong_number_is_caught, test_session_remembers_the_customer,
                 test_retry_after_network_error, test_trace_has_function_spans, test_injected_bug_returns_april):
        try:
            await test()
            print(f"PASS  {test.__name__}")
        except Exception as error:  # report every test, then fail at the end
            failed += 1
            print(f"FAIL  {test.__name__}: {type(error).__name__}: {error}")
    print(f"\n{6 - failed} of 6 passed, with no model calls")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
