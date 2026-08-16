# TASK — t11-high-risk

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

`set()` must persist ATOMICALLY: write the new state to a temp file inside data/, then rename it over db.json, so a crash can never leave a half-written db.json.

This is a persistence-safety change: preserve load() behavior, leave NO temp files behind, and verify carefully with the tests. Do NOT modify test.js.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node test.js` exits 0.
- store.js writes a temp file (name contains `tmp`) and renames it over db.json (`rename` present).
- data/ contains only db.json after the tests.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

~8 changed lines inside set() (writeFileSync to tmp + renameSync).
