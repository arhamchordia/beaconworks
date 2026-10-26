#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
    printf 'Usage: %s <base-branch>\n' "$0" >&2
    exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
export GIT_OPTIONAL_LOCKS=0
base=$1
git rev-parse --verify --end-of-options "${base}^{commit}" >/dev/null

printf '## Current branch and base\n'
printf 'Current branch: '
git symbolic-ref --short -q HEAD || git rev-parse --short HEAD
printf 'Base: %s\n' "$base"

printf '\n## Commits since base\n'
git log --oneline "${base}..HEAD" --

printf '\n## Files changed\n'
git diff --stat "${base}...HEAD" --

printf '\n## Uncommitted changes (should be empty)\n'
git status --short

printf '\n## Fixture changes (both should be empty)\n'
printf 'Committed fixture changes:\n'
git diff --stat "${base}...HEAD" -- src/fixtures
printf 'Uncommitted fixture changes:\n'
git status --short -- src/fixtures

printf '\n## Tracked cache files (should be 0)\n'
git ls-files -z | python3 -c 'import sys; print(sum(b"__pycache__" in path.split(b"/") for path in sys.stdin.buffer.read().split(b"\0") if path))'

printf '\n## Tests (last output line and exit status)\n'
result=0
shopt -s nullglob
tests=(tests/test_*.py)
if [[ ${#tests[@]} -eq 0 ]]; then
    printf 'No tests/test_*.py files found.\n' >&2
    exit 1
fi
for test in "${tests[@]}"; do
    if output=$(python3 "$test" 2>&1); then
        status=0
    else
        status=$?
        result=1
    fi
    printf '%s (exit %s): %s\n' "$test" "$status" "${output##*$'\n'}"
done
exit "$result"
