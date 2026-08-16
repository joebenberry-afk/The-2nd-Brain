# Evaluation Card — e06 (E6 — dependency temptation)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e06
- **user-style request**: Case-insensitive stable sort of customers by name.
- **repository/fixture baseline**: report.js sorts case-sensitively (Apple after apple); customers.csv has 4 entries.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: case-insensitive order with stable tie handling (apple inc before Apple store).
- **current reusable capabilities**: stdlib Array.prototype.sort with a comparator is sufficient; no dependencies exist.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. comparator using toLowerCase()\nB. comparator using localeCompare with sensitivity
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. new dependency (lodash/underscore)\nD. new sorting module/class\nE. database-level sort machinery
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
