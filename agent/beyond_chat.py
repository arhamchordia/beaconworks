"""Agents beyond chat: a sandbox agent that writes and runs its own analysis, and a voice agent.

Sandbox: a SandboxAgent gets a private workspace with a read-only copy of the sales CSV. It writes
analysis.py, runs it with the shell tool, and produces a CSV and an SVG chart. We copy the outputs
out, check every number in code, and check that the repo and our API key were never in reach.

Voice: a RealtimeAgent hears a recorded question (a WAV file), calls our revenue tools, and answers
in speech. We save the spoken answer as a WAV file and check what it said.

Run:
  python3 agent/beyond_chat.py --sandbox
  python3 agent/beyond_chat.py --voice ~/.beaconworks/question.wav
Options: --effort none|low|medium|high (sandbox model, default low)
"""
import argparse
import asyncio
import csv
import hashlib
import io
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

from dotenv import load_dotenv
from openai.types.shared import Reasoning

from agents import ModelSettings, Runner
from agents.run import RunConfig
from agents.sandbox import FileMode, Manifest, Permissions, SandboxAgent, SandboxRunConfig
from agents.sandbox.capabilities import Capabilities
from agents.sandbox.entries import Dir, LocalFile
from agents.sandbox.sandboxes.unix_local import UnixLocalSandboxClient

from revenue_facts import REPO, SALES_CSV, month_totals
from tool_agent import FUNCTION_TOOLS

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")
VOICE_MODEL = os.environ.get("BW_VOICE_MODEL", "gpt-realtime-2.1-mini")
OUT = Path.home() / ".beaconworks" / "sandbox_output"
ANSWER_WAV = Path.home() / ".beaconworks" / "answer.wav"
RATE = 24000  # pcm16, mono, 24 kHz: what the Realtime API takes and returns

TASK = """The sales data is in data/sales_transactions.csv (columns: transaction_id, customer_id, month,
segment, amount_usd). Using only the Python standard library:
1. Write analysis.py and run it with python3.
2. It must write output/monthly_revenue.csv with the header month,revenue_usd and one row per month,
   oldest first, revenue as a whole number.
3. It must write output/monthly_revenue.svg: a bar chart with one bar per month, each bar labelled
   with its revenue as a whole number without commas.
Then answer in two sentences: which month fell most against the month before, and by how much."""


# ---------- Sandbox agent ----------

def sandbox_agent() -> SandboxAgent:
    read_only = Permissions(owner=FileMode.READ, group=FileMode.READ, other=FileMode.NONE)
    return SandboxAgent(
        name="BeaconWorks sandbox analyst",
        instructions="You are the BeaconWorks data analyst. Work only inside your workspace. "
                     "Every number you report must come from a script you ran.",
        model=MODEL,
        model_settings=ModelSettings(reasoning=Reasoning(effort=EFFORT)),
        default_manifest=Manifest(entries={
            "data/sales_transactions.csv": LocalFile(src=SALES_CSV, permissions=read_only),  # a copy
            "output": Dir(),
        }),
        capabilities=Capabilities.default(),  # Filesystem (apply_patch, view_image), Shell, Compaction
    )


def repo_fingerprint() -> tuple[str, str]:
    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout
    return status, hashlib.sha256(SALES_CSV.read_bytes()).hexdigest()


async def read_text(sandbox, path: str) -> str:
    handle = await sandbox.read(Path(path))
    try:
        data = handle.read()
    finally:
        handle.close()
    return data if isinstance(data, str) else bytes(data).decode()


async def run_sandbox() -> int:
    before = repo_fingerprint()
    client = UnixLocalSandboxClient(inherit_host_environment=False)  # commands do not get our API key
    agent = sandbox_agent()
    sandbox = await client.create(manifest=agent.default_manifest)
    async with sandbox:  # developer-owned: we read the outputs before the workspace is removed
        workspace = Path(sandbox.state.manifest.root)
        print(f"Sandbox workspace: {workspace}")
        result = await Runner.run(agent, TASK, max_turns=20, run_config=RunConfig(
            sandbox=SandboxRunConfig(session=sandbox), workflow_name="BeaconWorks sandbox analysis"))
        calls = [i.raw_item for i in result.new_items if i.type == "tool_call_item"]
        print(f"Tool calls: {', '.join(getattr(c, 'name', None) or c.get('name', '?') for c in calls)}")
        print(f"\nAgent: {result.final_output}\n")
        OUT.mkdir(parents=True, exist_ok=True)
        files = {}
        for name in ("analysis.py", "output/monthly_revenue.csv", "output/monthly_revenue.svg"):
            try:
                files[name] = await read_text(sandbox, name)
                (OUT / Path(name).name).write_text(files[name])
            except Exception as error:  # a missing file is a failed check below, not a crash
                print(f"Could not read {name}: {type(error).__name__}")
        env = (await sandbox.exec("env")).stdout.decode()
    await client.delete(sandbox)  # we created it, so we remove its workspace
    print(f"Copied out to {OUT}: {', '.join(Path(n).name for n in files)}")

    truth = month_totals()
    rows = list(csv.DictReader(io.StringIO(files.get("output/monthly_revenue.csv", ""))))
    got = {r.get("month"): int(float(r.get("revenue_usd") or 0)) for r in rows}
    svg = files.get("output/monthly_revenue.svg", "")
    labels = set(re.findall(r">\s*(\d+)\s*<", svg))
    worst = min(zip(list(truth)[1:], list(truth)), key=lambda p: truth[p[0]] - truth[p[1]])
    print(f"Code says: the biggest fall is {worst[0]}, {truth[worst[0]] - truth[worst[1]]:+,} against {worst[1]}")
    checks = {
        f"CSV has all {len(truth)} months, every total exact": got == truth,
        "SVG has one bar per month, each labelled with the exact total":
            svg.count("<rect") >= len(truth) and {str(v) for v in truth.values()} <= labels,
        "OPENAI_API_KEY was not in the sandbox environment": "OPENAI_API_KEY" not in env,
        "repo unchanged (git status and the CSV's SHA-256)": repo_fingerprint() == before,
        "workspace deleted after the run": not workspace.exists(),
    }
    print("\nChecks (computed in code):")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


# ---------- Voice agent ----------

def read_question(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
            raise SystemExit(f"{path} must be 24 kHz, mono, 16-bit. "
                             f"It is {w.getframerate()} Hz, {w.getnchannels()} channel(s), {8 * w.getsampwidth()}-bit.")
        return w.readframes(w.getnframes())


def transcripts(history) -> tuple[str, str]:
    """What the user said (input transcription) and what the agent said (its audio transcript)."""
    heard, said = "", ""
    for item in history:
        if getattr(item, "type", None) != "message":
            continue
        for part in item.content:
            text = getattr(part, "transcript", None) or getattr(part, "text", None) or ""
            if item.role == "user":
                heard = text or heard
            elif item.role == "assistant":
                said = text or said
    return heard, said


async def run_voice(question_wav: Path) -> int:
    from agents.realtime import RealtimeAgent, RealtimeRunner  # needs the realtime extra
    from agents.realtime.model_inputs import RealtimeModelSendRawMessage

    question = read_question(question_wav)
    agent = RealtimeAgent(
        name="BeaconWorks voice analyst",
        instructions="You are the BeaconWorks revenue analyst, speaking to a colleague. Answer in at most "
                     "three short sentences. Get every number from your tools, and say amounts in US dollars. "
                     "If a tool gives a customer's name as not available, say the name is not available.",
        tools=FUNCTION_TOOLS,
    )
    runner = RealtimeRunner(agent, config={"model_settings": {
        "model_name": VOICE_MODEL,
        "audio": {
            "input": {"format": "pcm16", "transcription": {"model": "gpt-transcribe"}, "turn_detection": None},
            "output": {"format": "pcm16", "voice": "marin"},
        },
    }})
    audio, history, tools_used = bytearray(), [], []
    session = await runner.run()
    async with session:
        await session.send_audio(question, commit=True)  # one recorded turn, committed by us
        await session.model.send_event(RealtimeModelSendRawMessage(message={"type": "response.create"}))
        async with asyncio.timeout(120):
            async for event in session:
                if event.type == "audio":
                    audio.extend(event.audio.data)
                elif event.type == "tool_start":
                    tools_used.append(event.tool.name)
                    print(f"  tool_start {event.tool.name}({event.arguments})")
                elif event.type == "tool_end":
                    print(f"  tool_end   {event.tool.name} -> {str(event.output)[:60]}")
                elif event.type == "history_updated":
                    history = list(event.history)
                elif event.type == "history_added":
                    history = [i for i in history if i.item_id != event.item.item_id] + [event.item]
                elif event.type == "error":
                    print(f"  error: {event.error}")
                    break
                elif event.type == "agent_end" and audio:  # the spoken answer is complete
                    break

    ANSWER_WAV.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ANSWER_WAV), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(audio))
    heard, said = transcripts(history)
    seconds = len(audio) / (2 * RATE)
    print(f"\nHeard: {heard}\nSaid:  {said}\nSaved {seconds:.1f} s of speech to {ANSWER_WAV}")

    totals = month_totals()
    drop = totals["2026-04"] - totals["2026-05"]
    spoken = said.lower().replace(",", "")
    checks = {
        "the answer is real audio, longer than one second": seconds > 1,
        "the numbers came from our tools": bool(set(tools_used) & {"month_total", "top_customer_changes"}),
        f"the answer states the drop of ${drop:,}": str(drop) in spoken or "four thousand seven hundred" in spoken,
    }
    print("\nChecks (computed in code):")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


def main() -> int:
    global EFFORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--effort", default="low", choices=["none", "low", "medium", "high"])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sandbox", action="store_true")
    mode.add_argument("--voice", metavar="QUESTION_WAV", type=Path)
    args = parser.parse_args()
    EFFORT = args.effort
    load_dotenv(REPO / "analyst" / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. It is read from analyst/.env, as in the API lessons.")
        return 1
    return asyncio.run(run_sandbox() if args.sandbox else run_voice(args.voice.expanduser()))


EFFORT = "low"

if __name__ == "__main__":
    sys.exit(main())
