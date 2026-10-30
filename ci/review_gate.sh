#!/usr/bin/env bash
# Review gate: run the six tests, ask Codex (read only) to review the
# uncommitted changes as JSON, then exit 0 for pass or 1 for fail.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
mkdir -p ci-out

TESTS_OK=1
for t in tests/test_priority.py tests/test_customers.py tests/test_tickets.py tests/test_health.py tests/test_summary.py tests/test_ticket_queries.py; do
  if python3 "$t" > /dev/null 2>&1; then echo "test ok:     $t"; else echo "test FAILED: $t"; TESTS_OK=0; fi
done
export TESTS_OK

echo "running codex review..."
codex exec --ephemeral \
  --output-schema ci/review_schema.json \
  -o ci-out/review.json \
  "$(cat ci/review_prompt.md)" > /dev/null 2> ci-out/codex.log \
  || { echo "codex exec failed, see ci-out/codex.log"; exit 2; }

python3 - <<'PY'
import json, os, sys
r = json.load(open("ci-out/review.json"))
tests_ok = os.environ["TESTS_OK"] == "1"
print("codex verdict:", r["verdict"])
print("summary:", r["summary"])
for f in r["findings"]:
    print(f"- [{f['severity']}] {f['file']}: {f['message']}")
ok = tests_ok and r["verdict"] == "pass"
print("GATE:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
PY
