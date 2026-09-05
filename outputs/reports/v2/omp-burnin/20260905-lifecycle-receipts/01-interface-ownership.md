# Local lifecycle observation boundary

Status: authorized local design; not implemented or qualified by this note. Brain base `e9fc61cb623699cb982be4466d053944e2f8426a` preserves product `c166c9816b963d7f0e3e4f2c83179ea897651c1e`. Host base `e874b613654fd493b2bcb45c832e68f8d1a9a23e`; metadata PR branches are untouched.

## Existing call path

`TaskTool.#registerSpawnJob` -> `#executeSync` -> `runStructuredSubagent` -> `runSubprocess` / `runIsolatedSubprocess`. The executor already hands deferred cleanup to `onCleanupDeferred`. Structured execution retains that promise, but TaskTool currently receives only retained-artifact cleanup, which is NOT writer termination. `AsyncJobManager.waitForOwnerJobs` currently discovers obligations through evictable job rows. The executor currently uses `Promise.allSettled(...).then(() => {})`, so fulfillment of its deferred promise does NOT establish successful cleanup.

The supported extension seam is `ExtensionContext`, constructed by `ExtensionRunner` with session-owned providers from `AgentSession`. A separate scoped observation provider must not overwrite result-delivery sinks or produce model messages.

Brain owns task registration/projection in `worker_protocol`, durable per-session events in `LedgerStore`, and adapter ingress in `omp_adapter`. Current worker leases are liveness deadlines, not enforced resource-scope locks. `scope` is free-form packet text; existing admission only checks task ID/packet hash. This distinction must be resolved explicitly before claiming conflicting-writer exclusion.

## Minimal envelope and ownership

A host-owned manager generation plus per-registration attempt discriminator must distinguish native ID reuse. Observations also carry owner/session attribution, native job ID, expected child ID, schema version and monotonic per-attempt ordering. Brain retains packet/task correlation; OMP contains no Brain vocabulary. Only a supported scoped callback establishes host provenance; model text and arbitrary tool-result JSON do not.

Outcome, actual execution settlement and scoped resource release are independent facts. A cancelled outcome cannot imply settlement or release. Shutdown interruption retains resumability. Unknown or failed cleanup cannot release a conflicting scope. Any positive release needs evidence that the existing cleanup owner covers the actual defined resource scope, including its registered children; artifact-directory deletion is not that evidence.

## Durability and failure window

Subscribe before native dispatch. Buffer/replay only bounded native observations, with isolated bounded observer attempts; cancellation itself must never await persistence. Retain actual pending execution obligations independently of visible row eviction. Persist accepted events in the existing Brain session ledger before acknowledgment; reconstruct worker projection idempotently after an interrupted update. Existing SQLite worker metadata may receive a narrowly justified additive projection field, with migration/recovery proof.

A lost unacknowledged host observation may remain unknown. No new durable host event database or no-loss guarantee is proposed. Bounded reconciliation stops active retries at the existing deadline, records compact durable uncertainty and retains unsafe-scope restrictions without holding unrelated work active. Later authenticated observations may reconcile; no automatic side-effecting rerun or positive credit follows.

## Required primitive check before positive cleanup claims

Verify a real resource-to-conflict-domain binding and an enforced admission owner. Do not reinterpret the current free-form `scope` string or concurrency semaphore as a resource lease. If correct exclusion needs a new resource-arbitration/supervision architecture rather than a narrow existing-owner extension, stop and name that primitive. A disposable real subprocess/file-writer proof must exercise the actual owner, not substitute a test-only mutex for missing production enforcement.

No deployment, push, public PR, provider calls, adaptive activation, Gate 22/23 closure or tag. Prior proof remains carried forward only for unchanged inputs.
