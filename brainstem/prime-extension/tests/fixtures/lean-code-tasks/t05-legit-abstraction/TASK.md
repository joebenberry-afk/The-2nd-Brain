# TASK — t05-legit-abstraction

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

The three validators in validators.js repeat the same check 3 times — the pattern is now proven stable.

Add a 4th validator `validateEmail(v)` with the same contract (non-empty string, max length 50), but FIRST extract the shared check into one helper named `checkText(v, max)` and make all FOUR validators use it.

Do NOT modify test.js (it already covers the new validator).

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node test.js` exits 0.
- validators.js defines `function checkText(` exactly ONCE and all four validators call it.
- No new files.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

Helper `checkText(v, max)` ~6 lines + 4 one-line validators.
