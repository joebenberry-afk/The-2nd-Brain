# TASK — t04-duplication-temptation

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

Add `tieredFee(amount, tiers)` to fees.js: tiers is an array of `{limit, rate}` brackets; fee = sum of (amount in bracket × rate), rounded to 2 decimals ONCE at the end.

Example: `tieredFee(250, [{limit:100, rate:0.02},{limit:Infinity, rate:0.01}])` → 100×0.02 + 150×0.01 = 3.5.

The two existing fee paths are NOT yet a stable pattern — do not extract a shared fee engine. Do NOT modify test.js (it already covers the new function).

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node test.js` exits 0.
- No new files, no new modules (git status shows only `M fees.js` — test.js is restored pristine by the judge).

## BASELINE HINT (analysis-only — do NOT send to the arm session)

One exported function (~10 lines) inside fees.js.
