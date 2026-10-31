"""BeaconWorks support chat: streaming replies and conversation state.

Modes (pick one with --mode):
  none          every turn is sent alone, so the model remembers nothing
  chain         each turn points to the previous response (previous_response_id)
  conversation  turns live in a Conversations API object that survives restarts

Run: python3 analyst/chat.py --mode chain
Type a message and press Enter. Type /quit to leave.
Extra flags: --forget-instructions (chain mode demo), --new, --delete (conversation mode)
"""
import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")
CONVERSATION_FILE = Path(__file__).resolve().parent / "out" / "conversation_id.txt"
INSTRUCTIONS = (
    "You are the BeaconWorks support assistant. Answer in at most two sentences. "
    "End every answer with the words: BeaconWorks Support."
)


def stream_reply(client: OpenAI, user_text: str, **state):
    """Send one turn, print the reply as it streams, return the final response."""
    start = time.perf_counter()
    first_token_at = None
    final = None
    stream = client.responses.create(model=MODEL, input=user_text, stream=True, **state)
    for event in stream:
        if event.type == "response.output_text.delta":
            if first_token_at is None:
                first_token_at = time.perf_counter() - start
            print(event.delta, end="", flush=True)
        elif event.type == "response.completed":
            final = event.response
        elif event.type == "response.incomplete":
            print(f"\n[incomplete: {event.response.incomplete_details.reason}]")
            final = event.response
        elif event.type == "response.failed":
            print(f"\n[failed: {event.response.error.message}]")
            return None
        elif event.type == "error":
            print(f"\n[error: {event.message}]")
            return None
    total = time.perf_counter() - start
    print()
    if final is not None:
        first = f"{first_token_at:.2f}s" if first_token_at is not None else "n/a"
        sent = "yes" if final.instructions else "no"
        print(f"  [first token {first}, total {total:.2f}s, input tokens {final.usage.input_tokens}, "
              f"output tokens {final.usage.output_tokens}, instructions {sent}]")
    return final


def conversation_id(client: OpenAI, start_new: bool) -> str:
    if CONVERSATION_FILE.exists() and not start_new:
        conv_id = CONVERSATION_FILE.read_text().strip()
        print(f"Continuing conversation {conv_id}")
        return conv_id
    conv = client.conversations.create(metadata={"app": "beaconworks-analyst"})
    CONVERSATION_FILE.parent.mkdir(exist_ok=True)
    CONVERSATION_FILE.write_text(conv.id)
    print(f"Started conversation {conv.id}")
    return conv.id


def main() -> int:
    parser = argparse.ArgumentParser(description="BeaconWorks support chat")
    parser.add_argument("--mode", choices=["none", "chain", "conversation"], required=True)
    parser.add_argument("--forget-instructions", action="store_true",
                        help="chain mode: send instructions on the first turn only (shows why you must resend them)")
    parser.add_argument("--new", action="store_true", help="conversation mode: start a new conversation")
    parser.add_argument("--delete", action="store_true", help="delete the saved conversation and exit")
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. See analyst/.env.example.")
        return 1
    client = OpenAI()

    if args.delete:
        if not CONVERSATION_FILE.exists():
            print("No saved conversation.")
            return 0
        conv_id = CONVERSATION_FILE.read_text().strip()
        client.conversations.delete(conv_id)
        CONVERSATION_FILE.unlink()
        print(f"Deleted conversation {conv_id}")
        return 0

    conv_id = conversation_id(client, args.new) if args.mode == "conversation" else None
    previous_id = None
    turn = 0
    print(f"Mode: {args.mode}. Type /quit to leave.")
    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_text == "/quit":
            break
        if not user_text:
            continue
        turn += 1
        state = {}
        # Instructions are not carried over by previous_response_id, so send them every turn.
        if not (args.forget_instructions and turn > 1):
            state["instructions"] = INSTRUCTIONS
        if args.mode == "chain" and previous_id:
            state["previous_response_id"] = previous_id
        if args.mode == "conversation":
            state["conversation"] = conv_id
        print("assistant> ", end="", flush=True)
        final = stream_reply(client, user_text, **state)
        if final is not None:
            previous_id = final.id
    return 0


if __name__ == "__main__":
    sys.exit(main())
