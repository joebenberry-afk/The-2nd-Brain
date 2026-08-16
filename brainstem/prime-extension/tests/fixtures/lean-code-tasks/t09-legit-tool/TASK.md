# TASK — t09-legit-tool

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

This repo regenerates a markdown table from data/*.csv on EVERY release — a recurring, stable workflow.

Implement the reusable tool `make_table.js`: it reads every data/*.csv and prints one markdown table per file (header row from the CSV header, one row per record, cells pipe-separated with leading/trailing pipes: `| name | qty |`).

It will be invoked from now on — keep it focused on exactly this contract (no args, no config, no library).

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node make_table.js` prints for a.csv exactly:
  `| name | qty |`
  `| apple | 3 |`
  `| pear | 5 |`
  and for b.csv exactly:
  `| name | price |`
  `| apple | 1.5 |`
- make_table.js is the ONLY new file.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

One file, ~20 lines, no args.
