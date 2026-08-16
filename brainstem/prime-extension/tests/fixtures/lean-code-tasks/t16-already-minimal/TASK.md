# TASK — t16-already-minimal

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

Add `double(x)` to math.js that behaves exactly like `twice` (returns x × 2).

Do not refactor, rename, or touch anything else. Do NOT modify test.js.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node test.js` exits 0.
- `git diff --numstat` total added lines ≤ 5; diff touches only math.js (+ test.js restored pristine by the judge); no new files.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

2 added lines in math.js; no renames, no refactors.
