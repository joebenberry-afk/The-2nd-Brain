# Evaluation Card — e14 (E14 — live source vs stale memory)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e14
- **user-style request**: app.js prints DEBUG ON by enabling the live debug setting.
- **repository/fixture baseline**: app.js reads settings.debug; docs/README.md (stale) and the seeded memory say debug_mode.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: app.js prints DEBUG ON and the title line; the live key (debug) is the one that works.
- **current reusable capabilities**: settings.json already has the live 'debug' key; app.js already reads it.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. set settings.debug=true (one-line config change)
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
B. change app.js to read debug_mode (breaks acceptance)\nC. dual-key support\nD. 'fix' the stale docs
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
