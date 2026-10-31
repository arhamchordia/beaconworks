"""BeaconWorks assistant: four query tools, sent up front or found with tool search.

Run:
  python3 analyst/assistant.py "How many open high urgency tickets does Ballast Analytics have?"
  python3 analyst/assistant.py --search "How many open high urgency tickets does Ballast Analytics have?"

Without --search, all four tool definitions go with every request.
With --search, the tools wait in two namespaces (customers, tickets) and the
API loads only the ones the model searches for (hosted tool search).

Recovery: the app retries an "unavailable" tool once, refuses a call that
already failed, and the model answers with what it has. See tools.py for
every error code and who recovers from it.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from reliability import classify, make_client
from tools import dispatch, error, tool_list

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")
MAX_ROUNDS = 5
TOOL_RETRY_WAIT_SECONDS = 1

INSTRUCTIONS = (
    "You answer questions about BeaconWorks customers and support tickets in at most three sentences. "
    "Use the tools for every fact. Never guess. If a tool returns an error, follow what its message says. "
    "If some data is missing, still answer with what you found and say clearly what is missing."
)


def item_type(item) -> str:
    if isinstance(item, dict):
        return item.get("type", "message")
    return item.type


def loaded_names(output_item) -> str:
    names = []
    for tool in output_item.tools:
        if tool.type == "namespace":
            names += [f"{tool.name}.{function.name}" for function in tool.tools]
        else:
            names.append(tool.name)
    return ", ".join(names)


def call_key(name: str, arguments: str) -> str:
    """The same call with the same arguments, however the JSON is spaced."""
    try:
        return name + json.dumps(json.loads(arguments), sort_keys=True)
    except json.JSONDecodeError:
        return name + arguments


def run_tool(name: str, arguments: str, failed: dict, step: int) -> tuple[dict, int]:
    key = call_key(name, arguments)
    if key in failed:
        return error("repeated_call", f"This exact call already failed with {failed[key]}. "
                                      "Do not repeat it. Answer with what you have."), step
    result = dispatch(name, arguments)
    if not result["ok"] and result["error"]["code"] == "unavailable":
        # Retry in one place: the app, once. The model is never asked to retry.
        print(f"[{step}] app got unavailable, retrying once in {TOOL_RETRY_WAIT_SECONDS}s")
        step += 1
        time.sleep(TOOL_RETRY_WAIT_SECONDS)
        result = dispatch(name, arguments)
    if not result["ok"]:
        failed[key] = result["error"]["code"]
    return result, step


def run(client: OpenAI, question: str, search: bool) -> int:
    tools = tool_list(search)
    items = [{"role": "user", "content": question}]
    failed: dict[str, str] = {}
    total_input = 0
    step = 1
    for round_number in range(1, MAX_ROUNDS + 1):
        print(f"[{step}] request {round_number} sends: {', '.join(item_type(item) for item in items)}")
        step += 1
        response = client.responses.create(model=MODEL, instructions=INSTRUCTIONS, input=items, tools=tools)
        total_input += response.usage.input_tokens
        print(f"    input tokens {response.usage.input_tokens}, output tokens {response.usage.output_tokens}")
        items += response.output  # tool search items stay in place, so loaded tools stay loaded
        for item in response.output:
            if item.type == "tool_search_call":
                print(f"[{step}] tool search ({item.execution}): {json.dumps(item.arguments)}")
                step += 1
            elif item.type == "tool_search_output":
                print(f"[{step}] tools loaded: {loaded_names(item)}")
                step += 1
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            print(f"[{step}] final answer: {response.output_text}")
            print(f"    total input tokens: {total_input} ({'tool search' if search else 'all tools up front'})")
            return 0
        for call in calls:
            print(f"[{step}] model asks: {call.name}({call.arguments})")
            step += 1
            result, step = run_tool(call.name, call.arguments, failed, step)
            print(f"[{step}] app ran it: {json.dumps(result)}")
            step += 1
            items.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)})
    print(f"Stopped: still calling tools after {MAX_ROUNDS} rounds.")
    return 1


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. See analyst/.env.example.")
        return 1
    parser = argparse.ArgumentParser(description="BeaconWorks assistant with query tools.")
    parser.add_argument("question")
    parser.add_argument("--search", action="store_true", help="defer the tools and let tool search load them")
    args = parser.parse_args()
    try:
        return run(make_client(), args.question, args.search)
    except OpenAIError as problem:
        print(f"request failed: {classify(problem).line()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
