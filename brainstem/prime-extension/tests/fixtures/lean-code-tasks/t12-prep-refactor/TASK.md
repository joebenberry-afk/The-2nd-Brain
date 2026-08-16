# TASK — t12-prep-refactor

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

`netAmount(100, 0.075)` returns 99.92 but must return 92.5.

The tax-rounding expression `Math.round(x * taxRate * 100) / 100` is duplicated in both functions. Do a small preparatory refactor FIRST: extract it into one helper `round2(x)`, make BOTH functions use it, then fix netAmount's bug (it must compute the tax from gross: `gross - round2(gross * taxRate)`).

Do NOT modify test.js.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node test.js` exits 0.
- calc.js defines `function round2(` exactly ONCE and both netAmount and grossUp call it.
- No new files.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

Helper + 2 call sites + bug fix — ~6 changed lines.
