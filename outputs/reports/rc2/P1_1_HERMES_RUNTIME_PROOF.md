# P1.1 Hermes Driver/Worker Runtime Proof

**Status:** runtime evidence persisted; independent Validator gate pending
**Scope:** P1.1 only; no P1.2+, Lean, Prime promotion, or roadmap work
**Harness:** Hermes Agent + Second Brain plugin

This manifest was written while the parent Integrator Hermes session was still
live. It indexes canonical parent/worker telemetry and SQLite ledgers and records
both one successful delegation/review and one controlled unavailable-worker
failure.

## Parent coordinator

```text
Hermes profile:       integrator
Bot:                  Brain-Integrator
Role:                 integrator
Hermes session:       20260822_125930_f81689
Host session:         hermes:Brain-Integrator:20260822_125930_f81689
Brain session:        43a4ec676f2ed9104c5822f9b3c8d8dad747f79fec3988c619d4c5104aa1bf53
Project:              second-brain
Repository:           C:/Users/assas/Documents/The-Second-Brain
Branch:               brain/v1-rc4-prime-074-compat
Model:                gpt-5.6-luna
```

Parent telemetry:

```text
telemetry/agent-performance/hermes-Brain-Integrator-20260822_125930_f81689.jsonl
```

Parent ledger:

```text
state/sessions/43a4ec676f2ed9104c5822f9b3c8d8dad747f79fec3988c619d4c5104aa1bf53/ledger.sqlite
```

## Success case

Coordinator called the installed `second_brain_delegate` tool once with a
bounded `WorkerTaskPacket`:

```text
task_id:          p11-hermes-success-20260822-125930
requested_role:   dev
fanout:           1
fanout_index:     0
depth:             0
packet_bytes:     1235
parent_session:   hermes:Brain-Integrator:20260822_125930_f81689
project_id:       second-brain
```

Canonical parent ledger sequence:

```text
seq=5  task_created
seq=6  task_assigned
seq=7  worker_started
seq=8  worker_completed
seq=9  result_returned
seq=12 result_reviewed (approved=true)
```

Worker identity:

```text
Bot:                 Brain-Dev
Role:                dev
Hermes session:      20260822_130018_dc4aa1
Host session:        hermes:Brain-Dev:20260822_130018_dc4aa1
Brain session:       d4ac5c69a937d2c8723f53248ddf26c5d8fb98edbdb5d01298fd03036f2a648f
Project:             second-brain
Repository:          C:/Users/assas/Documents/The-Second-Brain
Branch:              brain/v1-rc4-prime-074-compat
```

The worker’s actual canonical telemetry is:

```text
telemetry/agent-performance/hermes-Brain-Dev-20260822_130018_dc4aa1.jsonl
```

The worker ledger is:

```text
state/sessions/d4ac5c69a937d2c8723f53248ddf26c5d8fb98edbdb5d01298fd03036f2a648f/ledger.sqlite
```

The worker session performed the bounded read-only inspection task through its
own persistent Brain-Dev profile and finalized with `checkpoint_ok=true`.

Result read-back from the parent lifecycle:

```text
status:             completed
failure_code:       null
retryable:          false
worker_agent_id:    hermes:Brain-Dev
worker_role:        dev
worker_session_id:  d4ac5c69a937d2c8723f53248ddf26c5d8fb98edbdb5d01298fd03036f2a648f
result_bytes:       4828
reviewed:           true
```

The result was returned to the coordinator, and the coordinator invoked the
explicit review tool with `approved=true`; it did not perform the delegated
inspection itself.

## Controlled failure case

The same persistent coordinator then called `second_brain_delegate` with a
bounded packet requesting role `worker`, for which no persistent profile was
configured:

```text
task_id:          p11-hermes-failure-20260822-125930
requested_role:   worker
fanout:           1
fanout_index:     0
depth:             0
packet_bytes:     973
status:           failed
failure_code:     WORKER_UNAVAILABLE
retryable:        true
```

Parent telemetry line 16 records `hermes_worker_lifecycle` with the explicit
failure. Parent ledger contains the corresponding `worker_failed` and
`result_returned` events. No worker session was created for the unavailable
profile, and no local delegated task execution occurred.

## Boundedness and enforcement

- Task packet sizes are validated by `WorkerTaskPacket` and capped at 16,384
  serialized bytes.
- Result sizes are validated by `WorkerResultPacket` and capped at 16,384
  serialized bytes.
- Text fields are capped at 4,096 characters; lists are capped at 16 entries;
  references are capped at 512 characters.
- Coordinator roles are limited to `integrator`, `driver`, `orchestrator`, and
  `hard_orchestrator`.
- Worker roles are limited to `dev`, `validator`, and `worker`.
- Fan-out defaults to 1 and is capped at 2.
- Depth is capped at 1.
- Malformed task/result, unauthorized role, fan-out overflow, depth overflow,
  unavailable worker, and malformed failure are explicit machine-readable codes.
- The worker prompt contains only the bounded packet, not parent transcript or
  chain-of-thought.
- Hermes tool-result capture remains bounded by the existing 4,000-character
  VMem limit.

## Existing primitives reused

```text
src/second_brain/contracts.py       WorkerTaskPacket/WorkerResultPacket,
                                    AgentIdentity, canonical_json, hash helpers
src/second_brain/hermes_adapter.py  validation, identity binding, lifecycle
                                    ledger/telemetry writes, worker bridge
src/second_brain/ledger.py          append-only canonical SQLite events
src/second_brain/autoinject.py      existing telemetry writer and Brain context
brainstem/adapters/hermes/          thin delegate/review tools and persistent
                                    Hermes worker subprocess bridge
```

No Hermes-native queue, database, memory, retrieval, or parallel telemetry store
was added. Prime TypeScript was not made Hermes-aware.

## Proof boundary

This runtime proves the real success and controlled unavailable-worker paths for
one persistent Brain-Integrator coordinator and one persistent Brain-Dev worker,
including bounded packet/result sizes, role/session/project identity, canonical
lifecycle events, result review, and explicit failure. Independent Validator
must re-read this manifest, both telemetry files, both ledgers, and the source/
test diff after the parent session boundary.
