"""Pick the right evidence source for a question, then answer from it, with citations.

  file_input   one known, small document: send the whole file with the question
  file_search  the answer is somewhere in knowledge/, not sure where: search a vector store
  web_search   current or public facts from outside BeaconWorks: search the web
  app_data     facts in our own records (tickets, customers): use the assistant's tools

Commands:
  python3 analyst/sources.py index              upload knowledge/*.md to a vector store
  python3 analyst/sources.py route "QUESTION"   only decide the source, and why
  python3 analyst/sources.py ask "QUESTION"     decide, answer, show citations and cost
  python3 analyst/sources.py cleanup            delete the vector store and its files
"""
import base64
import json
import os
import sys
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from reliability import classify, make_client

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")
ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
STORE_FILE = Path(__file__).resolve().parent / "out" / "vector_store.json"
DOCUMENTS = sorted(path.name for path in KNOWLEDGE.glob("*.md"))

# Prices in US dollars, from the OpenAI pricing page (checked November 2026). Estimates only.
PRICE_PER_INPUT_TOKEN = 0.10 / 1_000_000
PRICE_PER_OUTPUT_TOKEN = 0.50 / 1_000_000
PRICE_PER_TOOL_CALL = {"file_search_call": 2.50 / 1000, "web_search_call": 10.00 / 1000}


class Route(BaseModel):
    source: Literal["file_input", "file_search", "web_search", "app_data"]
    document: Optional[Literal[tuple(DOCUMENTS)]] = Field(description="Only for file_input: the one document to send, else null.")
    reason: str = Field(description="One short sentence explaining the choice.")


def catalog() -> str:
    lines = []
    for name in DOCUMENTS:
        title = (KNOWLEDGE / name).read_text().splitlines()[0].lstrip("# ").strip()
        lines.append(f"- {name}: {title}")
    return "\n".join(lines)


ROUTER_INSTRUCTIONS = f"""Choose the evidence source for a BeaconWorks question.
- file_input: the question names or clearly points to ONE of these documents. Set document.
- file_search: the answer is in our documents but could be in several, or you cannot tell which one.
- web_search: current or public information from outside BeaconWorks (versions, prices, news, other companies).
- app_data: live facts in our own records: tickets, customers, counts, statuses.
Our documents:
{catalog()}"""


def route(client: OpenAI, question: str) -> Route:
    response = client.responses.parse(model=MODEL, instructions=ROUTER_INSTRUCTIONS, input=question, text_format=Route)
    return response.output_parsed


def report(response, label: str) -> None:
    """Print the answer, its citations, and what it cost."""
    print(f"answer: {response.output_text}")
    calls = {}
    for item in response.output:
        if item.type in PRICE_PER_TOOL_CALL:
            calls[item.type] = calls.get(item.type, 0) + 1
        if item.type == "message":
            for part in item.content:
                for note in getattr(part, "annotations", None) or []:
                    if note.type == "file_citation":
                        print(f"  cited file: {note.filename}")
                    elif note.type == "url_citation":
                        print(f"  cited web page: {note.title} | {note.url}")
    usage = response.usage
    cost = usage.input_tokens * PRICE_PER_INPUT_TOKEN + usage.output_tokens * PRICE_PER_OUTPUT_TOKEN
    cost += sum(PRICE_PER_TOOL_CALL[kind] * count for kind, count in calls.items())
    tools = ", ".join(f"{kind} x{count}" for kind, count in calls.items()) or "none"
    print(f"  source {label} | input tokens {usage.input_tokens}, output tokens {usage.output_tokens} | "
          f"tool calls: {tools} | about ${cost:.4f}")


ANSWER_INSTRUCTIONS = (
    "Answer in at most three sentences, using only the evidence provided or found. "
    "If the evidence does not contain the answer, say so."
)


def ask_file_input(client: OpenAI, question: str, document: str) -> None:
    data = base64.b64encode((KNOWLEDGE / document).read_bytes()).decode()
    content = [
        {"type": "input_file", "filename": document, "file_data": f"data:text/markdown;base64,{data}"},
        {"type": "input_text", "text": question},
    ]
    response = client.responses.create(model=MODEL, instructions=ANSWER_INSTRUCTIONS,
                                       input=[{"role": "user", "content": content}])
    report(response, f"file_input ({document}, whole file sent)")


def ask_file_search(client: OpenAI, question: str) -> None:
    if not STORE_FILE.exists():
        print("No vector store yet. Run: python3 analyst/sources.py index")
        return
    store = json.loads(STORE_FILE.read_text())
    response = client.responses.create(
        model=MODEL, instructions=ANSWER_INSTRUCTIONS, input=question,
        tools=[{"type": "file_search", "vector_store_ids": [store["vector_store_id"]], "max_num_results": 4}],
        include=["file_search_call.results"],
    )
    for item in response.output:
        if item.type == "file_search_call":
            print(f"  searched for: {item.queries}")
            for result in item.results or []:
                score = f"{result.score:.2f}" if result.score is not None else "n/a"
                print(f"  retrieved: {result.filename} (score {score})")
    report(response, "file_search")


def ask_web_search(client: OpenAI, question: str) -> None:
    response = client.responses.create(model=MODEL, instructions=ANSWER_INSTRUCTIONS, input=question,
                                       tools=[{"type": "web_search"}])
    report(response, "web_search")


def ask_app_data(client: OpenAI, question: str) -> None:
    from assistant import run  # the tool-calling assistant from the function calling lessons
    run(client, question, search=False)


def index(client: OpenAI) -> int:
    if STORE_FILE.exists():
        print(f"Already indexed: {json.loads(STORE_FILE.read_text())['vector_store_id']}. Run cleanup first to rebuild.")
        return 1
    # Expires after 1 day without use: a safety net if cleanup is forgotten.
    store = client.vector_stores.create(name="beaconworks-knowledge", expires_after={"anchor": "last_active_at", "days": 1})
    file_ids = []
    for name in DOCUMENTS:
        with (KNOWLEDGE / name).open("rb") as handle:
            added = client.vector_stores.files.upload_and_poll(vector_store_id=store.id, file=handle)
        file_ids.append(added.id)
        print(f"  {name}: {added.status}")
    STORE_FILE.parent.mkdir(exist_ok=True)
    STORE_FILE.write_text(json.dumps({"vector_store_id": store.id, "file_ids": file_ids}, indent=2))
    print(f"Vector store {store.id} ready with {len(file_ids)} files.")
    return 0


def cleanup(client: OpenAI) -> int:
    if not STORE_FILE.exists():
        print("Nothing to clean up.")
        return 0
    store = json.loads(STORE_FILE.read_text())
    client.vector_stores.delete(store["vector_store_id"])
    for file_id in store["file_ids"]:
        client.files.delete(file_id)  # files outlive the vector store unless deleted
    STORE_FILE.unlink()
    print(f"Deleted vector store {store['vector_store_id']} and {len(store['file_ids'])} files.")
    return 0


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. See analyst/.env.example.")
        return 1
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    client = make_client()
    try:
        if command == "index" and len(sys.argv) == 2:
            return index(client)
        if command == "cleanup" and len(sys.argv) == 2:
            return cleanup(client)
        if command in ("route", "ask") and len(sys.argv) == 3:
            question = sys.argv[2]
            choice = route(client, question)
            print(f"route: {choice.source}" + (f" ({choice.document})" if choice.document else "") + f" | {choice.reason}")
            if command == "route":
                return 0
            if choice.source == "file_input" and choice.document:
                ask_file_input(client, question, choice.document)
            elif choice.source in ("file_input", "file_search"):
                ask_file_search(client, question)
            elif choice.source == "web_search":
                ask_web_search(client, question)
            else:
                ask_app_data(client, question)
            return 0
    except OpenAIError as problem:
        print(f"request failed: {classify(problem).line()}")
        return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
