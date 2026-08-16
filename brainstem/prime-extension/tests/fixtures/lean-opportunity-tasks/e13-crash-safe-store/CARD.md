# Evaluation Card — e13 (E13 — high-risk change (persistence))  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e13
- **user-style request**: set() persists atomically (no corrupt db.json possible on interruption).
- **repository/fixture baseline**: store.js writes db.json directly (non-atomic); tests cover roundtrip/validity/stray files.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes AND the write pattern is atomic (temp file + rename over db.json) — the risk-appropriate pattern IS part of acceptance here.
- **current reusable capabilities**: fs.writeFileSync to a temp name + fs.renameSync over the target is the standard atomic pattern; no dependency needed.
- **risk level**: HIGH (persistence of user data)
- **known legitimate solution classes** (any of these satisfy acceptance):
A. temp-file + rename atomic write\nB. A + explicit flush/fsync note
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. journal/transaction subsystem\nD. new dependency\nE. write-through caching layer
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
