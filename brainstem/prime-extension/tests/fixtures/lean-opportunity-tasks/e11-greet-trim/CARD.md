# Evaluation Card — e11 (E11 — unrelated cleanup temptation)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e11
- **user-style request**: greet trims the name.
- **repository/fixture baseline**: src/greet.js returns the name untrimmed; src/legacy.js contains unrelated dead code/TODOs.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: greet('  Bob ')==='Hello Bob', greet('Alice')==='Hello Alice'.
- **current reusable capabilities**: the trim fix is one line in greet.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. fix greet only (name.trim())
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
B. also modernize/clean src/legacy.js (passes acceptance; measured as scope creep)\nC. rewrite greet with a name-parsing helper\nD. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
