# TASK — t02-existing-reuse

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

Add a `title` command to cli.js: `node cli.js title hello world` must print `Hello World` (each argument capitalized).

Reuse the existing helper in lib/strings.js — do not duplicate its logic.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node cli.js title hello world` prints `Hello World`.
- `node cli.js title oNCE uPON A` prints `Once Upon A`.
- cli.js references lib/strings.js (`require("./lib/strings")`).
- No new files.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

~5 added lines in cli.js calling the existing `capitalize`.
