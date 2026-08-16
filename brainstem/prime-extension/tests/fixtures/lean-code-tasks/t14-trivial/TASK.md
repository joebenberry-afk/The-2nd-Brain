# TASK — t14-trivial

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

Change the app title in config.json from `Untitled` to `P3 Eval`. Nothing else.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node app.js` prints `title: P3 Eval`.
- `git diff --name-only` shows exactly `config.json`.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

One-line edit in config.json.
