# Experiment 1 (§141) — Baseline vs Brainstem SHADOW (JIT + Scout + RTD)

Date: 2026-08-14. Real non-critical task: "Find every place in
src/second_brain that writes to the SQLite database and summarize write
paths per module."

## Conditions

- BASELINE: plain `rg` (no Brain subsystems).
- Brainstem SHADOW: scout pre-pass (evidence map) + JIT context capsule
  (after recording 3 real reads). RTD is shadow-only and has no trigger
  path here (no tool results were substituted; documented honestly).

## Measurements (wall clock, same machine)

| Condition | Wall | Output size | Result |
|---|---|---|---|
| baseline rg | 0.023 s | 7.6 KB / 62 raw hits | DIRECT ANSWER: 12 modules with SQL writes |
| scout pre-pass | 1.196 s | 1.1 KB evidence map | scaffold only: 10 task-word candidates (8 correct modules, 2 false positives by task-word matching), freshness + unknowns template; did NOT answer the SQL-write question |
| JIT capsule (after 3 real reads) | 0.126 s | 647 B | retrieved exactly the 3 real reads; empty (honest) before reads existed |

## Verdict

NEUTRAL for Brainstem shadow on this narrow locator task: raw rg answered
in 23 ms; scout's value is scaffolding/ranking for exploration (as shown in
earlier phases), not keyword localization; JIT retrieval added the real
reads back once they existed. Recorded honestly per §95.1 (neutral results
are recorded, not spun).

## RTD note

RTD (artifact/RTD shadow) was not exercised here: this task involved no
tool-result substitution opportunity. Its shadow status unchanged.
