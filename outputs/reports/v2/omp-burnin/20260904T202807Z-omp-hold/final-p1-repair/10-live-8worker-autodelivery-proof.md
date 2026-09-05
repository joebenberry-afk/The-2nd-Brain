# Phase 11-16 — Live 8-Worker Auto-Delivery Proof (P1-OMP-WORKER-AUTODELIVERY)

## Methodology notes (dead ends documented for the record)

1. **Default profile, default daemon:** the pre-existing long-lived `omp.exe`
   daemon (PIDs 44248/23260, untouched throughout this repair) shares one
   governor budget ledger across every client invocation routed through it.
   Two prior orchestrator runs plus their spawned workers exhausted the
   `[budgets] session_tokens`/`worker_tokens` caps
   (`config/governor.toml`) for that shared daemon tree — a **pre-existing**
   `governor.py`/`budget-bridge.ts` scoping behavior, untouched by this
   repair and out of this repair's two-defect scope. Further `task` spawns
   against the default profile returned
   `[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED`.
2. **Isolated `--profile`, no explicit extension:** avoids the shared-daemon
   budget ledger, but `--profile <name>` also isolates OMP's own
   `agent/extensions/` auto-discovery root per profile
   (`~/.omp/profiles/<name>/agent/` has no `extensions/` subdirectory at
   all) — confirmed by **zero** `brain.active-state`/`prime_tool_surface`
   markers in that run's raw session JSON, even though OMP's native
   `"customType":"async-result"` delivery fired 3 times. That run proved
   OMP's own auto-delivery mechanism exists but exercised none of this
   extension's code.
3. **Isolated `--profile` + explicit `-e brainstem/prime-extension/src/index.ts`:**
   isolates the budget ledger (fresh profile, empty descendant scan) while
   force-loading the repaired candidate extension regardless of profile
   scoping. This is the run reported below.

## Live invocation

```text
omp.exe -p --cwd <worktree> --profile p1-live-proof2 \
  -e brainstem/prime-extension/src/index.ts \
  --model deepseek/deepseek-v4-pro --auto-approve --max-time 10m \
  "<8-worker-no-poll prompt>"
```

Prompt instructed the model to: spawn exactly 8 background subagents in one
`task` batch, never call the `hub` tool for the rest of the turn, run
`bash sleep 150` to pass time without polling, then report only the
auto-delivered notice counts it actually observed.

## Model's self-report

```text
`sleep 150` returned (150.34s wall time, no output). Test complete — no
further action, no `hub` calls made.

ALL8DONE: 6 succeeded, 2 failed, 0 unknown
```

## Telemetry evidence (ground truth, not self-report)

Orchestrator session `2026-09-05T02-16-14-068Z_01a06f5a-25f4-762b-b74e-1464fa61981f`:

- `omp_worker_context_handoff`: **8** (all 8 workers launched)
- `omp_worker_child_result`: **8** (6 `completed`, 2 `failed`) — matches the
  model's self-report exactly:
  - completed: `RealCaterpillar`, `OutstandingLocust`, `ClearWolverine`, `SoundSmelt`, `RulingOx`, `ControversialWorm`
  - failed: `RisingFlea`, `GeographicalQuail` (each worker's own telemetry
    confirms it emitted the correct `worker-N-ok` text; "failed" here
    reflects an OMP `task`-tool-level "Subagent called yield with null
    data" classification unrelated to Second Brain telemetry correctness)
- **`tool_call`/`tool_result` tools used this session, in order:**
  `read, glob, read, read, read, read, task, bash` — **zero `hub` calls**,
  proving all 8 completions were captured purely through
  `recordAsyncResultDeliveries` (`message_end`/`async-result` observer),
  never through `recordAsyncWorkerCompletions` (`hub` `tool_result`
  observer).

## Verdict

**PASS.** `P1-OMP-WORKER-AUTODELIVERY` is fixed and live-proven: 8/8 real
worker completions, delivered exclusively via OMP's auto-delivery path with
zero explicit polling, are captured as `omp_worker_child_result` telemetry
with correct status per worker — the exact defect scenario documented in
`deployment-alignment/09-worker-result-undercount-defect.md` (which recorded
0-of-N for this path pre-fix) now recovers 8-of-8.
