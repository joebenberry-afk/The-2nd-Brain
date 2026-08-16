# TASK — t03-tiny-bugfix

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

`rangeSum(1, 5)` returns 10 but must return 15 (the range is INCLUSIVE).

Fix the smallest thing in sum.js. Do NOT modify test.js.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node test.js` exits 0.
- `git diff --name-only` shows exactly `sum.js` (test.js unchanged).

## BASELINE HINT (analysis-only — do NOT send to the arm session)

One-character fix: `i < b` → `i <= b`.
