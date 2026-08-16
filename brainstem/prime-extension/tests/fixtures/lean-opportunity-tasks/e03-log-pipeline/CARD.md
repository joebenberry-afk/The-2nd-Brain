# Evaluation Card — e03 (E3 — existing tool composition)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e03
- **user-style request**: Summarize error-line amounts from data/*.log via the existing filter + stats tools.
- **repository/fixture baseline**: filter.js filters lines by regex; stats.js summarizes a CSV FILE (not stdin); logs carry amount= on error lines.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: the composed command prints mean/min/max of error amounts (mean 13.94, min 8.25, max 25.00).
- **current reusable capabilities**: filter.js already extracts matching lines; stats.js already computes mean/min/max; logs are regular files.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. compose the two tools (one-liner), extending stats.js minimally to read stdin when no file arg is given\nB. same + a 1-2 line npm script entry for repeatability
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. new 'error-report' tool with argument machinery\nD. logging framework / plugin system\nE. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
