# Evaluation Card — e16 (E16 — stop-after-proof)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e16
- **user-style request**: app title becomes 'P3 Eval'.
- **repository/fixture baseline**: config/app.json has title 'Untitled'; app.js prints it.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes and app.js prints 'title: P3 Eval'.
- **current reusable capabilities**: the title lives in config; tests exist.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. edit config/app.json, run the test, stop
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
B. also rewrite README/optional docs (passes acceptance; measured)\nC. add extra tests/verifier\nD. spawn a worker for a one-line edit
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
