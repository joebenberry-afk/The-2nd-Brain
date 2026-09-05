# Native OMP worker contract and observer

Contract pinned to OMP 18.1.10 commit `f241301c83726afe75a847e919b89977a54dafbe`.

## Primary sources

- [Task tool contract](https://raw.githubusercontent.com/can1357/oh-my-pi/f241301c83726afe75a847e919b89977a54dafbe/docs/tools/task.md): named batch items, supported effort/schema/isolation options, progress and synchronous result fields.
- [Native async delivery builder](https://raw.githubusercontent.com/can1357/oh-my-pi/f241301c83726afe75a847e919b89977a54dafbe/packages/coding-agent/src/session/async-job-delivery.ts): `role=custom`, `customType=async-result`, structured `details.jobs[{jobId,type,...}]`, string or text/image content blocks. Status is rendered in the outer task-result block, not supplied in jobs metadata.
- [Extension handler types](https://raw.githubusercontent.com/can1357/oh-my-pi/f241301c83726afe75a847e919b89977a54dafbe/packages/coding-agent/src/extensibility/extensions/types.ts): handlers may return promises; message_end is a notification, not a supported context-mutation hook.
- [Native session journal](https://raw.githubusercontent.com/can1357/oh-my-pi/f241301c83726afe75a847e919b89977a54dafbe/packages/coding-agent/src/session/session-manager.ts): custom entries are existing bookkeeping storage; getEntries supplies replay input. appendCustomEntry does not itself certify a Brain receipt; native flush reports disk failures.

## Candidate behavior

The observer requires the native custom-message envelope and task job identities. It recognizes only outermost task-result blocks, never nested quoted results. Only completed/failed/cancelled are terminal. It rejects stale-parent correlation and unknown jobs without fabricating a worker result. Envelopes are capped at 128 job metadata entries, 128 outer blocks, and 256 KiB text; malformed or invalid-status delivery produces a bounded extension error. Non-task background deliveries remain outside this observer.

The original message and role are returned unchanged. Existing assistant usage capture remains independent. Native async settlement is awaited instead of launching an untracked persistence child process. Synchronous task results and hub jobs/wait observations use the same settlement function. The observer does not poll hub or invoke a model.

Task transformation preserves top-level context and all original item fields, replacing only task text with the original untruncated task plus the bounded Brain handoff. IDs hash `[session, host toolCallId, item position]`; repeated delivery of one dispatch is stable, while identical text in separate items or later calls is distinct. A missing host dispatch identity is rejected, not guessed from truncated task text.

## Evidence and limits

`artifacts/worker-paging-before.json` and `artifacts/dispatch-identity-before.json` reproduce initial failures on immutable f5089ac. `artifacts/vitest-after.json` records all 20 then-current worker/paging scenarios passing. The later added synchronous thrown-error scenario and final full-suite result are tracked separately in `artifacts/vitest-final-full.json`.

These are offline hook-contract regressions, not provider-backed natural worker completions. Fresh native default loading, effective named-agent options, actual job delivery, and post-restart behavior remain separate live qualification gates.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
