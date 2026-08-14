# Baseline Benchmark Suite (plan §95)

Run BEFORE Brainstem actively changes behavior (i.e., before Phase 7 accuracy
features go active; Phase 6 Scout promotion also compares against this).
Each task runs twice minimum (BASELINE vs intervention) in fresh sessions on
the same model; record all KPIs (plan §93) from telemetry + observed results.

Tasks (one real but non-critical instance of each):

1. tiny-known-file fix          — one-file edit in a familiar repo, known location
2. unfamiliar repo bug          — localization-heavy bug in an unknown repo
3. difficult state bug          — nondeterministic/timing bug
4. noisy logs                   — extract signal from large output
5. over-engineering temptation  — feature request inviting extra deps/abstractions
6. architecture audit           — read-only architecture review of a mid repo
7. detailed handoff plan        — write a handoff for another agent
8. multi-agent task             — delegation with independent subagents
9. long context task            — task spanning many files/turns
10. misleading/incomplete test  — planted requirement/test mismatch
11. cross-project transfer      — reuse knowledge from another project
12. cross-model executor        — cheap model executes a distilled plan

## KPI record format (per task run)

```json
{
  "task_id": 1, "name": "...", "variant": "baseline|intervention",
  "model": "...", "session": "...",
  "verified_success": null, "first_pass_success": null,
  "user_corrections": 0, "reverts": 0,
  "tokens_in": null, "tokens_out": null,
  "tool_calls": 0, "tool_result_bytes": 0,
  "time_s": 0, "peak_context_pct": null,
  "files_read": 0, "files_edited": 0,
  "children": 0, "failed_commands": 0,
  "new_dependencies": 0
}
```

## Status

Not yet run. Phase 2 runs a compact 3-task real workload baseline
(see milestone-02); this full suite runs at the gate before the first
behavior-changing phase and results land in outputs/reports/.
