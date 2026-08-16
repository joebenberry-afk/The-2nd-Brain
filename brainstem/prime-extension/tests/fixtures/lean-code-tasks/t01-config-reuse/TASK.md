# TASK — t01-config-reuse

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

This app ships with a built-in debug mode. Make `node app.js` print the debug line `debug: starting logger` by changing the app's CONFIGURATION only.

Constraints: do not modify app.js; do not add files; do not add a CLI flag.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node app.js` prints a line starting with `debug: starting logger`.
- `git diff --name-only` shows exactly `config.json` (app.js untouched, no new files).

## BASELINE HINT (analysis-only — do NOT send to the arm session)

One-line config change (`verbose: true`). No code, no new files.
