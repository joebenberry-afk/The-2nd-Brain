# TASK — t15-substantial

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

Implement `stats.js` with CLI `node stats.js <csv>`: read the CSV (header `date,amount`) and print exactly:

```
mean: 19.94
median: 17.75
min: 8.25
max: 40.00
```

for the seeded data/transactions.csv (values rounded to 2dp — the fixture values give mean 159.5/8, median (15.5+20)/2).

Error handling: missing file → exit code 1 with a message on stderr; empty CSV (header only) → exit code 2 with a message on stderr; a row with a non-numeric amount → skip that row and note it on stderr.

This is a substantial multi-part task — complete it fully (implementation + CLI + error paths) and verify with your tests. Do NOT modify the README.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node stats.js data/transactions.csv` prints the exact four lines above.
- `node stats.js missing.csv` exits 1 (stderr message).
- empty CSV exits 2 (stderr message).
- `node test.js` exits 0 (oracle covers seeded file, missing file, empty file, bad-row file).
- New files limited to `stats.js` and `test.js`.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

One module + CLI + tests (~60-80 lines total). This is the largest fixture.
