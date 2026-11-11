"""The BeaconWorks analyst, as a first OpenAI Agents SDK agent.

The question "why did revenue fall in a month?" has no fixed steps, so it is an
agent's job. This first version has no tools yet: the evidence is computed in
code and put into the agent's instructions for each run (dynamic instructions).
The agent explains it and returns a typed Finding, which our code then checks.

Run:
  python3 agent/first_agent.py                    one run (Runner.run_sync), then the checks
  python3 agent/first_agent.py --stream           the explanation streamed as it is written
  python3 agent/first_agent.py --repl             chat with the agent in the terminal
  python3 agent/first_agent.py --month 2026-06    the same agent, another month
Options: --effort none|low|medium|high (default low)
"""
import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai.types.shared import Reasoning
from openai.types.responses import ResponseTextDeltaEvent
from pydantic import BaseModel, Field

from agents import Agent, ModelSettings, RunContextWrapper, Runner, run_demo_loop

from revenue_facts import customer_changes, month_totals, months

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")  # set explicitly: the SDK's own default is a different model


@dataclass
class AnalystContext:
    """Local context: available to our code during the run. The model sees only what we put in the prompt."""
    month: str
    previous_month: str
    totals: dict
    changes: list


class Finding(BaseModel):
    month: str = Field(description="The month investigated, YYYY-MM")
    previous_total_usd: int
    month_total_usd: int
    change_usd: int = Field(description="month_total_usd minus previous_total_usd")
    change_pct: float = Field(description="Change as a percentage of the previous month, one decimal")
    main_driver_customer_id: str = Field(description="The customer with the largest change in the direction of the total")
    main_driver_name: str = Field(description="Name from the evidence, or 'not available'")
    main_driver_change_usd: int
    other_customers_change_usd: int = Field(description="Net change of all other customers together")
    explanation: str = Field(description="Two sentences for a business reader")


def analyst_instructions(ctx: RunContextWrapper[AnalystContext], agent: Agent[AnalystContext]) -> str:
    """Dynamic instructions: rebuilt for every run from the local context."""
    c = ctx.context
    table = "\n".join(f"{r['customer_id']} | {r['name']} | {r['previous_usd']} | {r['month_usd']} | {r['change_usd']}"
                      for r in c.changes)
    return f"""You are the BeaconWorks revenue analyst. Your one job: explain why revenue changed in {c.month}
compared with {c.previous_month}, using only the evidence below.

Rules:
- Use only these numbers. Do not estimate, round differently or invent data.
- Copy names exactly from the evidence. If a name is "not available", write "not available". Never guess one.
- The main driver is the single customer whose change best explains the total change.

Evidence (computed in code from data/sales_transactions.csv):
Total {c.previous_month}: {c.totals[c.previous_month]} USD
Total {c.month}: {c.totals[c.month]} USD
customer_id | name | {c.previous_month} USD | {c.month} USD | change USD
{table}"""


def build_agent() -> Agent[AnalystContext]:
    return Agent[AnalystContext](
        name="BeaconWorks analyst",
        instructions=analyst_instructions,
        model=MODEL,
        model_settings=ModelSettings(reasoning=Reasoning(effort=EFFORT)),
        output_type=Finding,
    )


def make_context(month: str) -> AnalystContext:
    all_months = months()
    if month not in all_months or all_months.index(month) == 0:
        sys.exit(f"--month must be one of {all_months[1]} to {all_months[-1]}")
    previous = all_months[all_months.index(month) - 1]
    return AnalystContext(month, previous, month_totals(), customer_changes(previous, month))


def check(finding: Finding, c: AnalystContext) -> bool:
    """Grade the agent with numbers computed in code, never with another model."""
    before, after = c.totals[c.previous_month], c.totals[c.month]
    change = after - before
    driver = min(c.changes, key=lambda r: r["change_usd"]) if change < 0 else max(c.changes, key=lambda r: r["change_usd"])
    expected = {
        "previous_total_usd": before,
        "month_total_usd": after,
        "change_usd": change,
        "change_pct": round(change / before * 100, 1),
        "main_driver_customer_id": driver["customer_id"],
        "main_driver_name": driver["name"],
        "main_driver_change_usd": driver["change_usd"],
        "other_customers_change_usd": change - driver["change_usd"],
    }
    print("\nChecks (computed in code):")
    passed = True
    for field, want in expected.items():
        got = getattr(finding, field)
        ok = abs(got - want) < 0.05 if isinstance(want, float) else got == want
        passed &= ok
        print(f"  {'PASS' if ok else 'FAIL'}  {field}: {got}" + ("" if ok else f" (expected {want})"))
    print(f"\n{'All checks passed' if passed else 'Some checks failed'}")
    return passed


def run_once(agent: Agent[AnalystContext], c: AnalystContext) -> int:
    question = f"Why did revenue change in {c.month}?"
    result = Runner.run_sync(agent, question, context=c)
    finding = result.final_output_as(Finding)
    print(f"Agent: {result.last_agent.name}   model: {MODEL}   effort: {EFFORT}")
    print(finding.model_dump_json(indent=2))
    usage = result.context_wrapper.usage
    print(f"\nRun: {len(result.new_items)} new item(s), {usage.requests} model request(s), "
          f"{usage.input_tokens} input tokens, {usage.output_tokens} output tokens")
    return 0 if check(finding, c) else 1


async def run_stream(agent: Agent[AnalystContext], c: AnalystContext) -> int:
    writer = agent.clone(name="BeaconWorks analyst (text)", output_type=None)  # same agent, plain text out
    result = Runner.run_streamed(writer, f"Explain in three short sentences why revenue changed in {c.month}.", context=c)
    async for event in result.stream_events():
        if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
            print(event.data.delta, end="", flush=True)
    print()
    return 0


def main() -> int:
    global EFFORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="2026-05")
    parser.add_argument("--effort", default="low", choices=["none", "low", "medium", "high"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stream", action="store_true")
    mode.add_argument("--repl", action="store_true")
    args = parser.parse_args()
    EFFORT = args.effort

    load_dotenv(Path(__file__).resolve().parents[1] / "analyst" / ".env")  # the key from the API lessons
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. It is read from analyst/.env, as in the API lessons.")
        return 1
    agent, context = build_agent(), make_context(args.month)
    if args.repl:
        print(f"Chat with the analyst about {args.month}. Type exit to leave.")
        asyncio.run(run_demo_loop(agent.clone(output_type=None), context=context))
        return 0
    if args.stream:
        return asyncio.run(run_stream(agent, context))
    return run_once(agent, context)


EFFORT = "low"

if __name__ == "__main__":
    sys.exit(main())
