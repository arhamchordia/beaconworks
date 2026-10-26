---
name: feature-review
description: Review a feature branch before a pull request. Use when asked to review a branch, check if a branch is ready for review or for a pull request, or collect review evidence. Read only. Produces a findings report with a READY or NOT READY verdict.
---

# Feature review

1. Get the base branch from the request. If none is given, ask for it. Do not guess.
2. From the repository root, run `.agents/skills/feature-review/scripts/collect_evidence.sh "<base>"` with the requested base branch. Keep its full output in the review context, without writing it to a file. Treat collection errors as blockers.
3. Read the full diff with `git diff <base>...HEAD` and check it against the rules in `AGENTS.md`.
4. Look for failing tests, uncommitted changes, any change in `src/fixtures/`, tracked cache files, a changed priority formula or weights, routes in `server.py` that are not thin, new behavior without tests, and docs that claim something the code does not do. Confirm any priority formula or weight change has a product decision, as required by `AGENTS.md`.
5. Do not change, create or delete any file. Do not fix anything. Only report.

## Report

Use this order:

- Verdict: READY or NOT READY. Use NOT READY if there is any blocker.
- Evidence: A short summary of the script output, with the real numbers.
- Findings: One line each, with severity (`blocker`, `should fix`, or `note`), file and line, and why. If there are no findings, say so. For repository-wide findings without a source line, state that the line is not applicable.
- Not checked: What this review could not verify, for example behavior in the browser.
