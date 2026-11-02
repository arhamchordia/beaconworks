"""Evaluate retrieval against purpose-made failures: missing, outdated and contradictory documents.

The eval corpus is knowledge/*.md plus two older copies of the dashboard doc in eval/old_docs/:
  ticket_dashboard_v1.md   2 March 2026, an old access rule and no Priority Scoring
  ticket_dashboard_v2.md   20 June 2026, an older formula that contradicts the current one
Every file gets attributes when indexed: status (current or superseded) and updated (a date).

Each case in eval/retrieval_cases.json is graded in code, in two parts:
  retrieval  was the expected document retrieved? did superseded documents come along?
  answer     is "supported" right? does it include what it must, and avoid what it must not?
A failed case gets a diagnosis and a corrective action.

Commands:
  python3 analyst/retrieval_eval.py index
  python3 analyst/retrieval_eval.py run              search all documents
  python3 analyst/retrieval_eval.py run --current    search only documents with status "current"
  python3 analyst/retrieval_eval.py cleanup
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from docs_assistant import CHUNKING, INSTRUCTIONS, TOP_K, Answer, chunk_text
from reliability import classify, make_client

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")
ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "eval" / "retrieval_cases.json"
STORE_FILE = Path(__file__).resolve().parent / "out" / "eval_store.json"
RESULTS_FILE = Path(__file__).resolve().parent / "out" / "retrieval_eval.json"
CURRENT_ONLY = {"type": "eq", "key": "status", "value": "current"}

# What we know about each document. In a real system this lives with the document.
SUPERSEDED = {"ticket_dashboard_v1.md": "2026-03-02", "ticket_dashboard_v2.md": "2026-06-20"}
UPDATED = {"ticket_dashboard.md": "2026-09-08"}

FIXES = {
    "unsupported answer": "the model answered beyond the documents: keep the 'not supported' rule strict, "
                          "and add the document if this answer should exist",
    "retrieval miss": "the right document was not retrieved: check chunking, the question wording and TOP_K",
    "stale evidence": "a superseded document reached the model: mark it superseded and filter it out, or archive it",
    "wrong answer": "the right evidence was there but the answer is wrong: improve the instructions",
}


def corpus() -> list[Path]:
    return sorted((ROOT / "knowledge").glob("*.md")) + sorted((ROOT / "eval" / "old_docs").glob("*.md"))


def attributes(name: str) -> dict:
    if name in SUPERSEDED:
        return {"status": "superseded", "updated": SUPERSEDED[name]}
    return {"status": "current", "updated": UPDATED.get(name, "undated")}


def index(client: OpenAI) -> int:
    if STORE_FILE.exists():
        print(f"Already indexed: {json.loads(STORE_FILE.read_text())['vector_store_id']}. Run cleanup first.")
        return 1
    store = client.vector_stores.create(name="beaconworks-eval", expires_after={"anchor": "last_active_at", "days": 1})
    file_ids = []
    for path in corpus():
        with path.open("rb") as handle:
            added = client.vector_stores.files.upload_and_poll(
                vector_store_id=store.id, file=handle, chunking_strategy=CHUNKING, attributes=attributes(path.name),
            )
        file_ids.append(added.id)
        print(f"  {path.name}: {added.status}  {attributes(path.name)}")
    STORE_FILE.parent.mkdir(exist_ok=True)
    STORE_FILE.write_text(json.dumps({"vector_store_id": store.id, "file_ids": file_ids}, indent=2))
    print(f"Eval vector store {store.id} ready with {len(file_ids)} files.")
    return 0


def run_case(client: OpenAI, store_id: str, case: dict, current_only: bool) -> dict:
    search = {"query": case["question"], "max_num_results": TOP_K}
    if current_only:
        search["filters"] = CURRENT_ONLY
    results = list(client.vector_stores.search(store_id, **search).data)
    sources = "\n".join(
        f'<source id="{n}" file="{r.filename}">\n{chunk_text(r)}\n</source>' for n, r in enumerate(results, start=1)
    )
    answer = client.responses.parse(
        model=MODEL, instructions=INSTRUCTIONS, text_format=Answer,
        input=f"<sources>\n{sources}\n</sources>\n\nQuestion: {case['question']}",
    ).output_parsed
    retrieved = [r.filename for r in results]
    cited = [results[i - 1].filename for i in answer.source_ids if 1 <= i <= len(results)]
    text = answer.answer.lower()

    # Retrieval checks
    stale_retrieved = sorted({f for f in retrieved if f in case["stale_files"]})
    expected_hit = case["expected_file"] is None or case["expected_file"] in retrieved
    # Answer checks
    supported_ok = answer.supported == case["expect_supported"]
    missing_words = [w for w in case["must_include"] if w.lower() not in text]
    forbidden_words = [w for w in case["must_not_include"] if w.lower() in text]
    stale_cited = sorted({f for f in cited if f in case["stale_files"]})

    problem = ""
    if case["expect_supported"] is False and answer.supported:
        problem = "unsupported answer"
    elif not expected_hit:
        problem = "retrieval miss"
    elif stale_retrieved or stale_cited or forbidden_words:
        problem = "stale evidence"
    elif not supported_ok or missing_words:
        problem = "wrong answer"
    return {
        "id": case["id"], "kind": case["kind"], "passed": not problem, "problem": problem,
        "answer": answer.answer, "supported": answer.supported, "retrieved": retrieved, "cited": cited,
        "stale_retrieved": stale_retrieved, "stale_cited": stale_cited,
        "missing_words": missing_words, "forbidden_words": forbidden_words,
    }


def run(client: OpenAI, current_only: bool) -> int:
    if not STORE_FILE.exists():
        print("No eval index yet. Run: python3 analyst/retrieval_eval.py index")
        return 1
    store_id = json.loads(STORE_FILE.read_text())["vector_store_id"]
    cases = json.loads(CASES_FILE.read_text())
    print(f"mode: {'current documents only' if current_only else 'all documents'}  |  {len(cases)} cases")
    outcomes = []
    for case in cases:
        outcome = run_case(client, store_id, case, current_only)
        outcomes.append(outcome)
        print(f"{'PASS' if outcome['passed'] else 'FAIL'}  {outcome['id']:18} ({outcome['kind']})")
        print(f"      answer: {outcome['answer']}")
        if outcome["stale_retrieved"]:
            print(f"      stale retrieved: {', '.join(f'{f} (updated {SUPERSEDED[f]})' for f in outcome['stale_retrieved'])}")
        if outcome["stale_cited"]:
            print(f"      stale cited: {', '.join(outcome['stale_cited'])}")
        if outcome["forbidden_words"]:
            print(f"      says what it must not: {outcome['forbidden_words']}")
        if outcome["missing_words"]:
            print(f"      missing: {outcome['missing_words']}")
        if outcome["problem"]:
            print(f"      diagnosis: {outcome['problem']}. Fix: {FIXES[outcome['problem']]}")
    passed = sum(o["passed"] for o in outcomes)
    RESULTS_FILE.parent.mkdir(exist_ok=True)
    RESULTS_FILE.write_text(json.dumps({"current_only": current_only, "outcomes": outcomes}, indent=2))
    print(f"passed {passed} of {len(cases)}  |  details in {RESULTS_FILE.relative_to(ROOT)}")
    return 0 if passed == len(cases) else 1


def cleanup(client: OpenAI) -> int:
    if not STORE_FILE.exists():
        print("Nothing to clean up.")
        return 0
    store = json.loads(STORE_FILE.read_text())
    client.vector_stores.delete(store["vector_store_id"])
    for file_id in store["file_ids"]:
        client.files.delete(file_id)
    STORE_FILE.unlink()
    print(f"Deleted vector store {store['vector_store_id']} and {len(store['file_ids'])} files.")
    return 0


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. See analyst/.env.example.")
        return 1
    args = sys.argv[1:]
    client = make_client()
    try:
        if args == ["index"]:
            return index(client)
        if args == ["cleanup"]:
            return cleanup(client)
        if args in (["run"], ["run", "--current"]):
            return run(client, current_only=len(args) == 2)
    except OpenAIError as problem:
        print(f"request failed: {classify(problem).line()}")
        return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
