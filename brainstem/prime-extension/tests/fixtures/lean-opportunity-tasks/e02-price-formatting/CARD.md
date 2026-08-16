# Evaluation Card — e02 (E2 — existing function extension)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e02
- **user-style request**: Negative amounts format as -$12.50 (minus before $); positives unchanged.
- **repository/fixture baseline**: lib/format.js formatPrice handles n >= 0 only; formatQty exists; ledger uses formatPrice.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: positives unchanged, negatives render -$X.XX, ledger line renders correctly.
- **current reusable capabilities**: formatPrice already does $ + 2dp; formatQty patterns to mirror; renderLine reuses it.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. extend formatPrice in place to handle the sign\nB. small local helper in format.js used by formatPrice
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. new formatCredit/formatMoney duplicate in another module\nD. Money class / currency strategy\nE. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
