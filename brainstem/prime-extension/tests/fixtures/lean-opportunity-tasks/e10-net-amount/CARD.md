# Evaluation Card — e10 (E10 — small preparatory refactor)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e10
- **user-style request**: netAmount computes gross minus round2(gross * taxRate).
- **repository/fixture baseline**: lib/tax.js: netAmount has a bug (forgot gross in the tax term); the rounding expression is duplicated in both functions.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: netAmount(100,0.075)=92.5, netAmount(33.33,0.07)=31.0, grossUp values unchanged.
- **current reusable capabilities**: the duplicated expression can be extracted once (round2) and both functions can use it.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. extract a round2 helper, use it in BOTH functions, then fix netAmount (preparatory refactor)\nB. fix in place keeping the expression written once
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. rewrite the module / strategy pattern\nD. duplicate the corrected expression in both places\nE. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
