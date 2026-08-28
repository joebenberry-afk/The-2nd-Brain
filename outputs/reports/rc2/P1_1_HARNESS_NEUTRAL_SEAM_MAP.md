# P1.1 Harness-Neutral Driver/Worker Seam Map

**Date:** 2026-08-22
**Scope:** architecture read-back before implementation
**Rule:** no Prime/Hermes source was edited to produce this map.

## Answers to Phase 0

### 1. Existing generic primitive

`src/second_brain/contracts.py` already owns the generic identity and lifecycle
substrates:

- `AgentIdentity` for driver/worker identity and parent-agent linkage;
- `TaskIdentity` for stable delegated task identity;
- `BrainLifecycleEvent` and `LifecycleEventType` for canonical lifecycle events;
- `canonical_json()` / `stable_content_hash()` for bounded deterministic wire data.

`src/second_brain/ledger.py` already persists these events to the append-only
per-session SQLite ledger, including `worker_spawned`, `worker_message`,
`worker_report`, `task_completed`, and `task_failed` event types. No new store is
needed.

There is no existing bounded `WorkerTaskPacket` or `WorkerResultPacket` data
contract. That is the minimum generic contract gap.

### 2. Policy versus Prime mechanics

Harness-neutral policy requirements:

- role authorization and identity continuity;
- bounded task/result fields and sizes;
- fan-out and depth bounds;
- explicit failure/cancellation/retry status;
- driver review and no-silent-fallback;
- lifecycle telemetry and ledger correlation.

Prime-specific mechanics that must remain untouched:

- `brainstem/prime-extension/src/driver-orchestrator.ts` model-ID role
  resolution and driver prompt contract;
- Prime `before_agent_start` injection;
- Prime `rlm()`/daemon worker spawn mechanics;
- Prime Sol tool guard.

The generic contract must not import or make the Prime TypeScript module
Hermes-aware.

### 3. Hermes callback/tool surface

The installed Hermes plugin exposes:

```text
on_session_start
pre_tool_call
post_tool_call
pre_llm_call
on_session_finalize
second_brain_writeback
```

The current plugin calls `python -m second_brain ... autoinject hermes-hook`.
There is no current Brain delegation callback, task assignment hook, worker
completion hook, or worker result callback. Hermes' generic `delegate_task` is a
separate Hermes-native tool and cannot become the canonical Brain protocol.

The bridge therefore belongs in the existing Hermes plugin/adapter boundary,
with a small explicit delegation request/response path that carries the generic
contracts and invokes a configured persistent Hermes worker profile.

### 4. Minimum representation

Task packet fields (bounded):

```text
task_id
parent_session_id
driver_identity
worker_identity / requested_role
objective (bounded)
scope (bounded)
constraints (bounded list)
evidence_requirements (bounded list)
completion_condition (bounded)
context_refs (bounded Brain refs)
fanout_index
depth
```

Result packet fields (bounded):

```text
task_id
worker_identity
status
summary (bounded)
evidence_refs (bounded)
files_changed / artifacts (bounded refs)
tests_run (bounded)
limitations (bounded)
failure_code
retryable
```

No raw parent transcript, prompt, or chain-of-thought is carried.

### 5. Existing telemetry/ledger owners

Reuse:

- `LedgerStore.append_events()` and existing `LifecycleEventType` values;
- `_append_event()` in `src/second_brain/hermes_adapter.py`;
- existing `autoinject._append_telemetry()` JSONL writer;
- `src/second_brain/cli.py::cmd_orchestration()` as the existing counter
  recorder, extended only if the generic bridge needs a correlated event;
- `AgentIdentity` / `TaskIdentity` fields and per-session ledger tables.

Required new records remain canonical Brain events, not Hermes-native records:

```text
task_created
task_assigned
worker_started
worker_completed | worker_failed | worker_cancelled
result_returned
result_reviewed
result_corrected
```

Where an existing event enum is semantically suitable, reuse it; add only
harness-neutral event values if the lifecycle cannot be represented truthfully.

### 6. Mechanical enforcement

The generic validator must enforce:

- only coordinator/driver roles create tasks;
- worker roles cannot create child tasks or claim driver role;
- packet/result field and byte bounds;
- fan-out default 1 / hard max 2;
- depth bound;
- malformed task/result deterministic failure;
- explicit unavailable/crash/cancel status;
- no silent driver fallback for a substantial delegated task.

Prime prompt text remains advisory except for its existing Sol tool guard. The
new enforcement belongs in the generic packet/bridge validation path so Hermes
and future harnesses share it.

## Smallest implementation surfaces

Expected source surfaces, only after this map:

```text
src/second_brain/contracts.py              generic bounded packet/result types
src/second_brain/hermes_adapter.py        Brain-owned task/result validation + lifecycle
brainstem/adapters/hermes/hermes_plugin.py thin Hermes callback bridge
brainstem/telemetry/SCHEMA.md              additive lifecycle/counter documentation
tests/test_orchestration.py                generic validation/bounds/role/failure tests
tests/test_hermes_adapter.py               bridge/correlation/fail-open tests
```

Prime files must not change for Hermes support. No Hermes-native queue/database,
parallel memory, or parallel telemetry system is permitted.

## Proof target

After implementation, one fresh persistent Integrator session must create a
bounded task, assign it to persistent Brain-Dev, receive a bounded result, and
record the complete canonical lifecycle. A controlled worker failure must also
record explicit failure without silently executing the delegated substantial work
in Integrator. Brain-Validator must independently re-read the session ledgers,
telemetry, packet/result objects, role/fan-out/depth fields, and P0 regressions.
