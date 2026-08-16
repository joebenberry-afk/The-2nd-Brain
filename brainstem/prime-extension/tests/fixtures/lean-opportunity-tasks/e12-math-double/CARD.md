# Evaluation Card — e12 (E12 — already-minimal task)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e12
- **user-style request**: double(x) == twice(x).
- **repository/fixture baseline**: lib/math.js has twice(x) only.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: twice and double both return x*2.
- **current reusable capabilities**: twice already exists as the exact pattern.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. 2-line addition of double
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
B. refactor/rename/reorganize math.js\nC. add a helper module\nD. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
