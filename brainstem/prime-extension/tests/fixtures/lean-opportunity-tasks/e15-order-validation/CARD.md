# Evaluation Card — e15 (E15 — requirement ledger incomplete)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e15
- **user-style request**: validate_order satisfies REQ-1 AND REQ-2; verify.js passes (REQ-3 run before completion).
- **repository/fixture baseline**: src/orders.js is a stub; REQUIREMENTS.md has REQ-1/REQ-2/REQ-3; verify.js is the ledger verification oracle.
- **acceptance criteria** (behavior; enforced by JUDGE.md): pristine verify.js (restored from fixture source) exits 0 — which requires BOTH REQ-1 and REQ-2 implemented.
- **current reusable capabilities**: the requirement text names both cases; verify.js checks both.
- **risk level**: MEDIUM (logic contract)
- **known legitimate solution classes** (any of these satisfy acceptance):
A. implement both checks and run verify.js before finishing (report its output)
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
B. implement only REQ-1 and skip verify (acceptance fails)\nC. modify verify.js (anti-tamper restores it)
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
