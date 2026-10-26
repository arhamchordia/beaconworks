# Instruction map

| Instruction | Home | Status |
| --- | --- | --- |
| 1. Run all six test scripts before saying a change is done. | AGENTS.md | done |
| 2. Never edit src/fixtures, they are generated. | AGENTS.md | done |
| 3. Scoring tests use a fixed date, never today. | AGENTS.md | done |
| 4. The priority formula and weights change only with a product decision. | AGENTS.md | done |
| 5. If a test fails, try a fix at most twice, then stop and report. | AGENTS.md | done |
| 6. Before a pull request: check behavior and tests, save the evidence, run /review against the base branch, triage the findings, and write a description with risks. | Repository skill | planned: repository skill |
| 7. Debug loop: see it fail, write a failing test first, make the smallest fix, see it pass, read the diff. | Repository skill | planned: repository skill |
| 8. Write every command you run into an audit log. | Hook | planned: hook |
| 9. Look up a customer's open issues in the team's issue tracker. | MCP | planned: MCP |
| 10. Label the score column "Priority score (beta)". | Only the prompt | no rule needed, done in code |
