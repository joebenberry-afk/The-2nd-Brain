# Phase 22 Counter Recalculation

## Source and method

Read-only aggregation was run against the current
`telemetry/agent-performance/*.jsonl` corpus with:

```text
.venv/Scripts/python.exe -m second_brain telemetry report --json
```

The report contained 3,134 records across 82 sessions. The newest telemetry
record is `2026-09-04T19:49:50.909Z`; no later OMP activity is present.
Worker result status was independently counted from
`omp_worker_child_result` records. Project transitions were independently
counted as adjacent `project_id` changes in timestamp-ordered
`brain_retrieval_attempt` records (85 retrieval attempts).

## Phase 22 coverage

| Target | Current evidence | Gate result |
|---|---:|---|
| 50+ OMP sessions | 82 sessions | PASS |
| 100+ normal turns | 190 `turn_start` records | PASS |
| 25+ tool calls | 152 `tool_call` records | PASS |
| 20+ worker launches | 19 `omp_worker_context_handoff` records | HOLD — 1 short |
| 20+ terminal worker results | 7 `omp_worker_child_result` records: 4 `completed`, 3 `failed` | HOLD — 13 short |
| 10+ session compactions | 8 `session_before_compact` + 8 `session_compact` pairs | HOLD — 2 short |
| 10+ clean restarts | 85 shutdown records across 76 unique sessions | PASS |
| 3+ interrupted/recovery cases | 3 documented live cases | PASS |
| 20+ project switches | 11 adjacent project transitions | HOLD — 9 short |
| 2+ conflicting controlled projects | `p10-project-alpha` and `p10-project-bravo` alternating sentinels | PASS |

Worker result failures remain legitimate terminal result events under the
recorded Phase 22 semantics; no running or stale task was counted.

## Decision

Phase 22 is **not qualified**. Four independent count gates remain below
minimum, so the release remains **HOLD**. No derived state was edited, no
counter was synthesized, and no new provider-backed OMP activity was started
while the reported HTTP 429 cooldown remained active.
