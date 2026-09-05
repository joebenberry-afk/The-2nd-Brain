# P1 #1 — Worker Auto-Delivery Reproduction

## Live evidence (from the prior qualification pass)

`outputs/reports/v2/omp-burnin/20260904T202807Z-omp-hold/deployment-alignment/09-worker-result-undercount-defect.md`
directly reproduced the defect twice with real OMP 18.1.10 activity:

- 20-worker batch: 20/20 real successes, only 3 `omp_worker_child_result`
  telemetry records.
- 5-worker batch: 5/5 real successes, only 2 telemetry records.

The raw session JSON showed the missing completions arriving as a
`message_end` event, `message.role === "custom"`,
`message.customType === "async-result"`, `content` a `<system-notice>` text
blob embedding one or more `<task-result id="…" status="completed" …>`
blocks — never a second `tool_result` for `toolName === "task"` and never a
`hub` `tool_result`.

## Root cause confirmed by source inspection

`brainstem/prime-extension/src/index.ts`'s `recordAsyncWorkerCompletions`
only observed `pi.on("tool_result", …)` events where
`event.toolName === "hub"`. The extension's only `message_end` handler
existed solely for `assistant_usage` capture and never inspected
`customType`/`content`. No code path in the extension observed the
auto-delivery custom-message shape at all.

## Type shape gap

`types/prime.d.ts`'s `MessageEndMessage` interface had no explicit
`customType`/`content` fields (only an index signature falling back to
`unknown`), matching that no handler code ever needed to read them before
this repair.

## Disposition

Confirmed as a genuine, reproducible P1. Repaired in
`02-worker-autodelivery-repair.md`.
