"""Customer lookup with function calling, printed step by step.

The model never runs code. It can only ask for a function by name, with
arguments. This script runs the function and sends the result back.

Run:
  python3 analyst/lookup.py "Who is customer CUST-0002, and who owns the account?"
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.lib.customers import get_customer  # the same function the dashboard uses

from reliability import classify, make_client

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")
MAX_ROUNDS = 5  # the loop must end, whatever the model asks for

INSTRUCTIONS = (
    "You answer questions about BeaconWorks customers in at most three sentences. "
    "For any fact about a specific customer, call get_customer. Never guess customer details."
)

TOOLS = [
    {
        "type": "function",
        "name": "get_customer",
        "description": (
            "Look up one BeaconWorks customer by ID. Returns the name, segment, region, "
            "signup date and account owner, or found false if no such customer exists."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID, for example CUST-0002.",
                    "pattern": "^CUST-[0-9]{4}$",
                }
            },
            "required": ["customer_id"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]


class GetCustomerArgs(BaseModel):
    # The schema already asks for this shape. We check again: arguments come from the model.
    customer_id: str = Field(pattern=r"^CUST-[0-9]{4}$")


def run_get_customer(arguments: str) -> dict:
    try:
        args = GetCustomerArgs.model_validate_json(arguments)
    except ValidationError as error:
        return {"error": f"invalid arguments: {error.errors()[0]['msg']}"}
    record = get_customer(args.customer_id)
    if record is None:
        return {"found": False, "customer_id": args.customer_id}
    # Send only what the model needs. The contact email stays in our app.
    keep = ("customer_id", "name", "segment", "region", "signup_date", "account_owner")
    return {"found": True, **{key: record[key] for key in keep}}


FUNCTIONS = {"get_customer": run_get_customer}


def item_type(item) -> str:
    if isinstance(item, dict):
        return item.get("type", "message")
    return item.type


def run(client: OpenAI, question: str) -> int:
    items = [{"role": "user", "content": question}]
    step = 1
    for round_number in range(1, MAX_ROUNDS + 1):
        sent = ", ".join(item_type(item) for item in items)
        print(f"[{step}] request {round_number} sends: {sent}")
        step += 1
        response = client.responses.create(model=MODEL, instructions=INSTRUCTIONS, input=items, tools=TOOLS)
        print(f"    input tokens {response.usage.input_tokens}, output tokens {response.usage.output_tokens}")
        # Keep everything the model returned, reasoning items included, for the next request.
        items += response.output
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            print(f"[{step}] final answer: {response.output_text}")
            return 0
        for call in calls:
            print(f"[{step}] model asks: {call.name}({call.arguments})  call_id {call.call_id}")
            step += 1
            function = FUNCTIONS.get(call.name)
            result = function(call.arguments) if function else {"error": f"unknown function {call.name}"}
            print(f"[{step}] app ran it, result: {json.dumps(result)}")
            step += 1
            items.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)})
    print(f"Stopped: still calling tools after {MAX_ROUNDS} rounds.")
    return 1


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. See analyst/.env.example.")
        return 1
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    try:
        return run(make_client(), sys.argv[1])
    except OpenAIError as error:
        print(f"request failed: {classify(error).line()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
