"""Append shell commands from hook input to the project audit log."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    try:
        payload = json.load(sys.stdin)
        command = payload["tool_input"]["command"]
        if isinstance(command, list):
            command = " ".join(command)
        if not isinstance(command, str):
            return
        session_id = payload["session_id"][:8]
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp} | {session_id} | {command}\n"
        log_path = Path(__file__).resolve().parent.parent / "audit.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(line)
    except Exception:
        pass


if __name__ == "__main__":
    main()
