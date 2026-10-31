"""BeaconWorks assistant: four query tools, sent up front or found with tool search.

Run:
  python3 analyst/assistant.py "How many open high urgency tickets does Ballast Analytics have?"
  python3 analyst/assistant.py --search "How many open high urgency tickets does Ballast Analytics have?"

Without --search, all four tool definitions go with every request.
With --search, the tools wait in two namespaces (customers, tickets) and the
API loads only the ones the model searches for (hosted tool search).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from reliability import classify, make_client
from tools import dispatch, tool_list

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")
MAX_ROUNDS = 5

INSTRUCTIONS = (
    "You answer questions about BeaconWorks customers and support tickets in at most three sentences. "
    "Use the tools for every fact. Never guess. If a tool returns an error, say what the error means."
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


def run(client: OpenAI, question: str, search: bool) -> int:
    tools = tool_list(search)
    items = [{"role": "user", "content": question}]
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
            result = dispatch(call.name, call.arguments)
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
    except OpenAIError as error:
        print(f"request failed: {classify(error).line()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
