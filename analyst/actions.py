"""Draft, approve and send customer replies. The model can only draft.

  1. The model calls draft_reply. Our code builds the action. The recipient comes
     from the customer record, never from the model. It is saved as pending.
  2. A person runs   python3 analyst/actions.py approve latest
     They see the exact recipient, subject and body, and type yes. The approval
     is bound to a SHA-256 fingerprint of exactly that action, valid 15 minutes.
  3. Then            python3 analyst/actions.py send latest
     Send checks: approved, same fingerprint, not expired, never sent before.
     Any change after approval, the recipient or one character of the body, blocks it.

The send is a mock. It writes the email to analyst/out/outbox/ instead of mailing it.

Commands: list | show ID | approve ID | send ID | test     (ID can be "latest")
"""
import contextlib
import getpass
import hashlib
import io
import json
import secrets
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

APPROVAL_MINUTES = 15
BOUND_FIELDS = ("type", "ticket_id", "to", "subject", "body")  # what the approval covers
FOLDERS = {}


def use_folder(out: Path) -> None:
    FOLDERS.update(pending=out / "pending", approvals=out / "approvals", outbox=out / "outbox")


use_folder(Path(__file__).resolve().parent / "out")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(action: dict) -> str:
    bound = {key: action[key] for key in BOUND_FIELDS}
    return hashlib.sha256(json.dumps(bound, sort_keys=True).encode()).hexdigest()


def create_draft(ticket_id: str, to: str, subject: str, body: str) -> dict:
    action_id = f"act_{utc_now():%Y%m%d%H%M%S}_{secrets.token_hex(2)}"
    action = {
        "action_id": action_id,
        "type": "send_email",
        "ticket_id": ticket_id,
        "to": to,
        "subject": subject,
        "body": body,
        "created_at": utc_now().isoformat(timespec="seconds"),
    }
    FOLDERS["pending"].mkdir(parents=True, exist_ok=True)
    (FOLDERS["pending"] / f"{action_id}.json").write_text(json.dumps(action, indent=2))
    return action


def load(action_id: str) -> dict:
    if action_id == "latest":
        drafts = sorted(FOLDERS["pending"].glob("act_*.json"))
        if not drafts:
            raise SystemExit("No drafts yet.")
        return json.loads(drafts[-1].read_text())
    path = FOLDERS["pending"] / f"{action_id}.json"
    if not path.exists():
        raise SystemExit(f"No draft {action_id}.")
    return json.loads(path.read_text())


def show(action: dict) -> None:
    print(f"Action:      {action['action_id']}  ({action['type']}, for {action['ticket_id']})")
    print(f"To:          {action['to']}")
    print(f"Subject:     {action['subject']}")
    print(f"Fingerprint: {fingerprint(action)[:16]}")
    print("Body:")
    for line in action["body"].splitlines() or [""]:
        print(f"  | {line}")


def approve(action: dict, answer=input, approver: str = "", at: datetime = None) -> int:
    at = at or utc_now()
    existing = FOLDERS["approvals"] / f"{action['action_id']}.json"
    if existing.exists():
        # One approval per action. Approving again could reopen an email that was already sent.
        print(f"REFUSED: {action['action_id']} already has an approval. For a changed or new email, draft a new reply.")
        return 1
    show(action)
    if answer("Type yes to approve sending exactly this email: ").strip().lower() != "yes":
        print("Not approved. Nothing changed.")
        return 1
    record = {
        "action_id": action["action_id"],
        "fingerprint": fingerprint(action),
        "approved": {key: action[key] for key in BOUND_FIELDS},
        "approved_by": approver or getpass.getuser(),
        "approved_at": at.isoformat(timespec="seconds"),
        "expires_at": (at + timedelta(minutes=APPROVAL_MINUTES)).isoformat(timespec="seconds"),
        "sent_at": None,
    }
    FOLDERS["approvals"].mkdir(parents=True, exist_ok=True)
    (FOLDERS["approvals"] / f"{action['action_id']}.json").write_text(json.dumps(record, indent=2))
    print(f"Approved by {record['approved_by']}, valid until {record['expires_at']}, for this exact email only.")
    return 0


def send_problems(action: dict, at: datetime) -> list[str]:
    path = FOLDERS["approvals"] / f"{action['action_id']}.json"
    if not path.exists():
        return ["not approved"]
    record = json.loads(path.read_text())
    if record["sent_at"]:
        return [f"already sent at {record['sent_at']}, an approval is used once"]
    if at > datetime.fromisoformat(record["expires_at"]):
        return [f"approval expired at {record['expires_at']}"]
    if fingerprint(action) != record["fingerprint"]:
        problems = []
        for key in BOUND_FIELDS:
            if action[key] != record["approved"][key]:
                if key == "body":
                    problems.append("body changed since approval")
                else:
                    problems.append(f"{key} changed since approval: approved {record['approved'][key]}, now {action[key]}")
        return problems
    return []


def send(action: dict, at: datetime = None) -> int:
    at = at or utc_now()
    problems = send_problems(action, at)
    if problems:
        print("REFUSED: " + "; ".join(problems))
        print("Nothing was sent.")
        return 1
    path = FOLDERS["approvals"] / f"{action['action_id']}.json"
    record = json.loads(path.read_text())
    # Mark the approval used before sending, so a crash can never cause a second send.
    record["sent_at"] = at.isoformat(timespec="seconds")
    path.write_text(json.dumps(record, indent=2))
    FOLDERS["outbox"].mkdir(parents=True, exist_ok=True)
    email = FOLDERS["outbox"] / f"{action['action_id']}.eml"
    email.write_text(
        f"To: {action['to']}\nSubject: {action['subject']}\n"
        f"X-BeaconWorks-Action: {action['action_id']}\nX-BeaconWorks-Approved-By: {record['approved_by']}\n\n"
        f"{action['body']}\n"
    )
    print(f"SENT (mock): {email.name} written to the outbox. Approval {record['fingerprint'][:16]} is now used.")
    return 0


def list_drafts() -> int:
    for path in sorted(FOLDERS["pending"].glob("act_*.json")):
        action = json.loads(path.read_text())
        approval = FOLDERS["approvals"] / path.name
        state = "pending"
        if approval.exists():
            state = "sent" if json.loads(approval.read_text())["sent_at"] else "approved"
        print(f"{action['action_id']}  {state:8}  {action['ticket_id']}  {action['subject']}")
    return 0


def self_test() -> int:
    checks = []

    def check(label, ok):
        checks.append(ok)
        print(("PASS " if ok else "FAIL ") + label)

    def quiet(function, *args, **kwargs):
        # Run a step without its printed output, keep its return code.
        with contextlib.redirect_stdout(io.StringIO()):
            return function(*args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        use_folder(Path(tmp))
        t0 = utc_now()
        a = create_draft("TICKET-0001", "contact@ballastanalytics.example.com", "Re: test [TICKET-0001]", "We are looking into it.")
        check("fingerprint ignores key order", fingerprint(dict(reversed(list(a.items())))) == fingerprint(a))
        check("fingerprint changes when one body character changes", fingerprint({**a, "body": a["body"] + "!"}) != fingerprint(a))
        check("send without approval is refused", quiet(send, a, t0) == 1)
        check("answering no does not approve", quiet(approve, a, lambda _: "no", "tester", t0) == 1
              and not (FOLDERS["approvals"] / f"{a['action_id']}.json").exists())
        quiet(approve, a, lambda _: "yes", "tester", t0)
        check("approved and unchanged: sent", quiet(send, a, t0) == 0 and (FOLDERS["outbox"] / f"{a['action_id']}.eml").exists())
        check("second send is refused: used once", send_problems(a, t0)[0].startswith("already sent"))
        check("approving a sent email again is refused", quiet(approve, a, lambda _: "yes", "tester", t0) == 1
              and send_problems(a, t0)[0].startswith("already sent"))

        b = create_draft("TICKET-0001", "contact@ballastanalytics.example.com", "Re: test [TICKET-0001]", "Second reply text.")
        quiet(approve, b, lambda _: "yes", "tester", t0)
        moved = {**b, "to": "attacker@example.net"}
        problems = send_problems(moved, t0)
        check("changed recipient is refused and named", len(problems) == 1 and problems[0].startswith("to changed"))
        check("refused send writes nothing to the outbox", quiet(send, moved, t0) == 1
              and not (FOLDERS["outbox"] / f"{b['action_id']}.eml").exists())
        check("one changed body character is refused", send_problems({**b, "body": b["body"] + "."}, t0) == ["body changed since approval"])
        check("approval expires after 15 minutes", send_problems(b, t0 + timedelta(minutes=16))[0].startswith("approval expired"))
        check("the exact approved email still sends", quiet(send, b, t0) == 0)
    use_folder(Path(__file__).resolve().parent / "out")
    print(f"{sum(checks)} of {len(checks)} checks passed")
    return 0 if all(checks) else 1


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] in ("list", "test"):
        return list_drafts() if sys.argv[1] == "list" else self_test()
    if len(sys.argv) == 3 and sys.argv[1] in ("show", "approve", "send"):
        action = load(sys.argv[2])
        if sys.argv[1] == "show":
            show(action)
            return 0
        return approve(action) if sys.argv[1] == "approve" else send(action)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
