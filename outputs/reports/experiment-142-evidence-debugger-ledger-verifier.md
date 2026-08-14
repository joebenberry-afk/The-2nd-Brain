# Experiment 2 (§142) — Evidence Debugger + Requirement Ledger + Intent Verifier

Date: 2026-08-14. Real debugging task: a seeded one-line aggregation bug in a
scratch copy of crossmodel.py (`state/experiments/e2/report_mini.py` —
double-counts successes in outcomes; the contract test asserts outcomes==2).

## Conditions

- BASELINE: plain tools (pytest + rg + edit), no Brain subsystems.
- BRAIN: requirement ledger (critical REQ-200 + evidence + verified status),
  intent-verifier brief, scout evidence map, THEN the same fix.

## Measurements (same machine; tool I/O bytes as token proxy)

| Metric | BASELINE | BRAIN |
|---|---|---|
| steps | 4 | 11 |
| tool I/O bytes | 12 562 | 12 711 |
| wall (s) | 17.5 (cold pytest) | 3.3 (warm pytest; confounded) |
| rework iterations | 1 | 1 |
| corrections | 1 | 1 |
| first-pass correctness | no (test discovered the bug) | no (same) |
| durable artifact | none | REQ-200 verified + evidence + brief + map |

## Verdict

NEUTRAL on fix speed for a trivial one-line bug: the Brain scaffolding did
not reduce rework (the contract test is the discovery mechanism in both
modes) and added ~150 bytes of tool I/O. HELPFUL on traceability: mode B
leaves a verified material requirement (gate passes) — the WHY and the
proof are machine-checkable afterwards; mode A leaves nothing. Reported
honestly per §95.1.

## Confound note

Wall times are not comparable (first pytest run pays interpreter/collection
startup; mode A ran cold, mode B warm). Byte counts and step counts are the
clean comparisons.
