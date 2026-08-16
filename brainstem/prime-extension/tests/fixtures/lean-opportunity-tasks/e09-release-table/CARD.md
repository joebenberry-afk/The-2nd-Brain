# Evaluation Card — e09 (E9 — legitimate new tool)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e09
- **user-style request**: A reusable make_table.js producing markdown tables for every data/*.csv.
- **repository/fixture baseline**: data/a.csv, b.csv, c.csv exist; docs/README documents the recurring need; no table tool exists.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: `node make_table.js` prints all three tables in the exact format.
- **current reusable capabilities**: Node stdlib fs is enough; the tool will be called from two consumers on every release (repeated stable workflow).
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. single-purpose make_table.js (one file, no args)\nB. A + a small test
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. configurable generic table engine with options\nD. plugin system\nE. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
