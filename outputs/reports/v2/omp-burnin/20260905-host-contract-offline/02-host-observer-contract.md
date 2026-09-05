# Native host and Brain observer contract

OMP current-main base:5964a0f7649275bcde818f20073193fd032451f2. Pinned release base:f241301c83726afe75a847e919b89977a54dafbe (18.1.10). Host patch:874fe1f20bc5f906812ff52c0a6a5698a59c191e; branch fix/structured-async-result-metadata on joebenberry-afk/oh-my-pi.

Production source delta is exactly6 additive lines in packages/coding-agent/src/session/async-job-delivery.ts: optional status?:AsyncJob["status"] and agentId?:string, populated only from entry.job and copied into details.jobs. Rendering template unchanged. No retention extension, polling dependency, text authority or new delivery architecture.

## Regression proof

Tests-first on each base:1pass/5expected failures because metadata omitted status/agentId. A first attempt was blocked before tests by absent native binary; it is not red proof. Supplied installed official pi-natives-win32-x64@18.1.10 baseline binary only in ignored local native directory; no native binary or dependency changes committed.

Both patched bases:47/47 tests,134 assertions. The eviction test fails the initial delivery, uses25ms test retention, and asserts getJob(jobId) is undefined inside the successful sink before constructing the message. The reconstructed job and details retain completed/Foo-t1-2/Foo-t1. Production retention remains300000ms. Existing full schema payload/image and old consumer/rendering tests pass. Current-main typecheck and changed-file oxlint pass.

## Brain migration

Source candidate:1099eb37b01f282365922b337a6069e31692b2cd. Observer source changed only after the host47/47 proof on both bases. Correlate native jobId with pending task/packet; persist native agentId and exact completed/failed/cancelled status. All text is non-authoritative, bounded2048-character batch summary. Unknown jobs ignored. Missing structured fields leave correlation pending and emit one bounded capability diagnostic per extension lifecycle. No snapshot fallback or rendered tag parsing remains.

Four new boundary regressions failed before source migration; final full Vitest689/689. Literal unmatched tags cannot suppress valid metadata. Removed3 obsolete tests that treated rendered failure wording or nested wrappers as authority. Existing replay-order, rejected/throwing persistence, cancellation serialization, recovery, native ancestry, task packet/project/role and option-preservation regressions pass.

Real offline smoke: minimal recording host API dispatches synthetic native events into the actual extension factory; actual context/result bridges invoke project Python and persist real database receipts. Driver role is an existing authorized configuration; context_refs=[] is explicit for this empty fixture. COMPLETED/FAILED/CANCELED states and result hashes verified through worker_protocol APIs. Replays before/after factory restart preserve exactly3 accepted receipts. This is not a provider-visible worker or Gate22/23 claim. Initial malformed inline-script/unauthorized worker-role/missing-capsule fixture attempts are retained, superseded by structured-durable-smoke-context.json.

Stock18.1.10 automatic capture is deliberately unsupported by the new observer. A tested patched host must be installed/restarted before future live qualification. No default deployment occurred in this pass.
