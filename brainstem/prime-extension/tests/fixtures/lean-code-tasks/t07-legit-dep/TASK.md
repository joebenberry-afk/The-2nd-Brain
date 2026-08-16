# TASK — t07-legit-dep

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

`loadConfig` must parse config.json5, which contains `//` comments and a trailing comma.

The repo ships `confparse` (node_modules/confparse — the maintained JSONC parser) exactly for this purpose: use it. Do NOT hand-roll a comment stripper.

Do NOT modify test.js.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node test.js` exits 0.
- load.js uses confparse (requires it); no hand-rolled parser added; no new files.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

Swap `JSON.parse` for `confparse.parse` in load.js — ~2 lines.
