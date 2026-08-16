# Evaluation Card — e08 (E8 — new-tool temptation)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e08
- **user-style request**: Produce analysis.txt with per-function call counts in src/.
- **repository/fixture baseline**: src/ has app.js, util.js, db.js with small functions; no analysis tool exists.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: analysis.txt matches the canonical one-off counting command output.
- **current reusable capabilities**: shell one-liners (grep/sed/sort/uniq) or a node -e one-liner can produce the counts.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. one-liner writing analysis.txt (no new files)\nB. node -e one-liner writing analysis.txt
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. a committed analysis script with argument machinery\nD. a new CLI command/tool\nE. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
