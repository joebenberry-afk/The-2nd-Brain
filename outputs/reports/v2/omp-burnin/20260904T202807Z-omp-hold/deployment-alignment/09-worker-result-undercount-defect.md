# Critical Finding: Worker-Result Telemetry Undercounts Real Completions

## Summary

A real 20-worker batch and a real 5-worker batch were dispatched through the
now-correctly-deployed extension using an authorized driver model
(`deepseek/deepseek-v4-pro`). All workers genuinely completed successfully
(model-confirmed: "DONE: 20 succeeded, 0 failed" and "DONE: 5 succeeded, 0
failed"). Telemetry recorded only **3 of 20** and **2 of 5**
`omp_worker_child_result` events respectively — a systematic undercount, not
a qualification-evidence problem.

## Root cause

`brainstem/prime-extension/src/index.ts`'s `recordAsyncWorkerCompletions`
(~line 836) only observes `pi.on("tool_result", …)` events where
`event.toolName === "hub"` and reads `job.id` / `job.status` from
`event.details.jobs[]`. This correctly captures completions that the model
retrieves via an **explicit** `hub jobs`/`hub wait` tool call before OMP's own
job-auto-delivery timer fires.

When a background `task` job is **not** explicitly awaited in time, OMP
auto-delivers its result as a **custom message**
(`message_end` event, `message.role === "custom"`,
`message.customType === "async-result"`) whose `content` is a
`<system-notice>` text blob embedding one or more
`<task-result id="…" status="completed" …>` blocks. This delivery path is a
`message_end` event, never a `tool_result` event for `toolName === "hub"`.
`recordAsyncWorkerCompletions` (and no other handler in the extension)
listens for `message_end`/custom messages of this shape, so these genuine,
real, successful worker completions are **silently and permanently invisible**
to Second Brain's worker-result telemetry and to
`brainstem/prime-extension/src/worker-result-bridge.ts`'s durable
Brain-side lifecycle recording.

### Evidence

- 20-worker batch (`session 01a06eea-d0ac-72c6-b1ba-f1d986fa4e12`,
  `telemetry/agent-performance/2026-09-05T00-14-37-740Z_01a06eea-…jsonl`):
  20 `omp_worker_context_handoff` records (correct), only 3
  `omp_worker_child_result` records, all `status: "completed"`.
- 5-worker batch (model `deepseek/deepseek-v4-pro`): 5 launches, only 2
  terminal results recorded. The raw session JSON contains a
  `"customType":"async-result"` message whose text embeds
  `<task-result id="ImaginativeAlpaca" … status="completed" …>`,
  `id="EqualChinchilla" … status="completed"`, and
  `id="SaltyBug" … status="completed"` — three real successful completions
  with zero corresponding `omp_worker_child_result` telemetry anywhere.

## Impact on Phase 22

This is a systematic undercount, not limited to this qualification pass. It
means Gate A (terminal worker-result lifecycle) and Gate B (successful
worker completions) counts derived from
`telemetry/agent-performance/*.jsonl` are a **lower bound**, not an accurate
measurement, whenever any worker's completion is delivered through OMP's
auto-delivery path instead of an explicit `hub jobs`/`hub wait` poll. The
existing `7/20` (Gate A) and `4/20` (Gate B) figures recorded earlier in this
campaign cannot be assumed complete either — some historical real
completions may have been silently dropped the same way.

## Disposition

This is a genuine extension source defect, not a deployment or
qualification-methodology error. It was **not fixed** in this pass: correctly
handling the auto-delivered `async-result` custom-message shape requires a
new observer path in `index.ts` (hooking `message_end`/custom messages, not
just `tool_result`), which is a nontrivial change to a file with ~10 existing
wiring tests asserting exact event shape/order/count — too invasive to
implement and verify safely as a side effect of this qualification
deployment pass.

**Workaround used for this campaign's remaining live activity:** every
subsequent worker batch explicitly polls `hub jobs` in a tight loop
(sub-5-second interval) until every dispatched job reports a non-`"running"`
status via the observed `tool_result` path, before any of them can age into
OMP's auto-delivery window. This reliably captures 100% of real completions
through the code path the extension already observes correctly (see
`10-worker-coverage.md` for the batches run this way).

## Recommendation (not implemented here)

Extend `recordAsyncWorkerCompletions` (or add a sibling handler) to also
observe `message_end` events where `message.role === "custom"` and
`message.customType === "async-result"`, parsing embedded
`<task-result id="…" status="…">` blocks the same way
`recordWorkerChildResults` parses `details.results[]`, correlating by
`pendingWorkerJobs` exactly as today. This should be proposed as a separate,
reviewed, test-covered change — not bundled into a release-qualification
pass.
