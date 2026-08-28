# P1.2 Worker Communication — Independent Re-qualification

**Verdict:** `PARTIAL`
**Validator:** `Brain-Validator` (`validator` profile)
**Date:** 2026-08-23T02:30:06Z
**Scope:** P1.2 only; no implementation, P1.3, Prime promotion, or roadmap work

This report records an independent read-back against the newly proven P1.1
harness-neutral worker plane. It does not promote P1.2 and does not modify
implementation.

## Repository baseline

```text
root:   C:/Users/assas/Documents/The-Second-Brain
branch: brain/v1-rc4-prime-074-compat
HEAD:   0bc2b8d56ceed3c1e17576283f05b4dba6f52d91
```

The worktree was already dirty before this report. The existing implementation,
test, plugin, configuration, P1.1 proof, and roadmap changes were not altered by
this validation. This report is the only artifact persisted by this task.

## 1. Exact frozen P1.2 contract

The frozen RC2 roadmap row is read from
`outputs/reports/rc2/01-frozen-roadmap-matrix.md`:

```text
Item:                 P1.2
Requirement:          Worker Communication
Implementation:       repository_intelligence.py, delta_sync.py
Automated evidence:   tests/test_delta_sync_live_integration.py
Live evidence:        structured assignment & result packets
Cross-harness:        Level A (Prime), Level B (Codex)
Token evidence:       delta sync diff packets <=20% size
Dogfood evidence:     used in worker dispatch
Historical status:    PROVEN (not accepted without independent read-back)
```

The earlier independent roadmap re-audit gives the more specific frozen
communication expectation: a distinct worker-packet taxonomy for assignment,
status, findings, artifacts, evidence, blockers, dependencies, and handoff;
canonical deterministic serialization; and real communication evidence rather
than only AutoInject or generic ledger events.

The canonical driver policy additionally requires:

- narrow worker objective, scope, constraints, required evidence, and completion
  condition;
- concise structured worker evidence rather than a raw transcript;
- driver inspection and acceptance of worker evidence;
- explicit targeted follow-up/correction when evidence is insufficient; and
- observable worker communication and lifecycle behavior.

The current P1.2 qualification also applies the requested explicit gates:
identity correlation, narrow context, Brain reference resolution where intended,
mechanical packet/result validation, deterministic failure, review/correction
return, canonical reconstructability, harness neutrality, and exclusion of
arbitrary A2A chat as canonical worker communication.

## 2. Read-only sources inspected

```text
outputs/reports/rc2/01-frozen-roadmap-matrix.md
outputs/reports/rc2/P1_1_FINAL_HERMES_RUNTIME_PROOF.md
outputs/reports/rc2/P1_1_HARNESS_NEUTRAL_SEAM_MAP.md
outputs/reports/v1-roadmap-baseline-reaudit.md
outputs/reports/v1-roadmap-matrix-p0p1p2p4.md
brainstem/policies/driver-orchestration.md
src/second_brain/contracts.py
src/second_brain/hermes_adapter.py
brainstem/adapters/hermes/hermes_plugin.py
brainstem/adapters/hermes/plugin.yaml
src/second_brain/ledger.py
brainstem/telemetry/SCHEMA.md
src/second_brain/delta_sync.py
src/second_brain/repository_intelligence.py
tests/test_orchestration.py
tests/test_hermes_adapter.py
tests/test_delta_sync_live_integration.py
brainstem/prime-extension/src/driver-orchestrator.ts
```

The Prime source was checked with:

```text
git grep -n -i hermes -- brainstem/prime-extension
```

Result: no matches. Prime TypeScript remains Hermes-unaware.

## 3. Protocol inspection

`src/second_brain/contracts.py` defines the new harness-neutral packet types:

```text
WorkerTaskPacket
WorkerResultPacket
WORKER_PACKET_MAX_BYTES = 16384
WORKER_RESULT_MAX_BYTES = 16384
WORKER_TEXT_MAX_CHARS = 4096
WORKER_LIST_MAX_ITEMS = 16
WORKER_REF_MAX_CHARS = 512
WORKER_DEFAULT_FANOUT = 1
WORKER_MAX_FANOUT = 2
WORKER_MAX_DEPTH = 1
```

`WorkerTaskPacket` carries task/session/driver identity, requested worker role,
objective, scope, constraints, evidence requirements, completion condition,
context references, fan-out, depth, project, and repository identity. Its
validator enforces coordinator and worker roles, list/text/reference bounds,
fan-out/depth limits, and serialized byte size.

`WorkerResultPacket` carries task identity, worker identity, status, summary,
evidence references, files changed, artifacts, tests run, limitations, failure
code, and retryability. Its validator enforces worker role, completed/failed/
cancelled status, result field bounds, mandatory failure code for failed results,
boolean retryability, task/result size, and malformed-result rejection.

The Hermes plugin exposes `second_brain_delegate` and
`second_brain_review_worker_result`. The adapter validates the packet before
creating lifecycle events and validates the result before returning it. The
persistent worker invocation sends a JSON object containing only
`worker_task_packet`; the prompt explicitly prohibits parent-history copying,
A2A, delegation, edits, and memory writes.

Important limitations found in the same source:

1. `context_refs` are only bounded strings in `WorkerTaskPacket`. No adapter or
   plugin code resolves them through Brain retrieval, `artifact` expansion, or a
   canonical reference reader.
2. The worker CLI output is truncated to 4096 characters and placed into the
   `summary` field. The packet shape is mechanically validated, but no parser
   mechanically verifies the policy-level Conclusion/Evidence/
   Files-symbols/Commands-tests/Changes/Uncertainty/Next-action/Artifacts
   structure inside the worker's text.
3. `review_worker_result` emits only `RESULT_REVIEWED` with approved/rejected
   status. There is no `result_corrected` lifecycle enum, correction packet,
   targeted follow-up request, or worker correction return path.
4. The adapter's lifecycle payloads preserve bounded metadata and byte counts,
   not the packet/result bodies or Brain reference-resolution outcomes.

The older `repository_intelligence.py` worker plane is not the new Hermes
communication bridge. It uses a separate `state/repo_intel/repo_intel.sqlite`
store and its `WorkerAssignmentPacket`/`WorkerResultPacket` are not the
harness-neutral contracts used by `hermes_adapter.py`. The frozen
`delta_sync.py` module is a memory-item delta/progressive-disclosure mechanism,
not a worker task/result transport.

## 4. Existing P1.1 real-runtime read-back

The previously persisted P1.1 runtime evidence was re-read, not accepted as a
mere report claim.

### Parent coordinator

```text
bot:              Brain-Integrator
role:             integrator
Hermes session:   20260822_131527_09877a
Brain session:    b52a2289da2958fb800aff8425ad9d7d9b58e73aebafe9bc4319a8b6f5112a1e
project:          second-brain
repo:             C:/Users/assas/Documents/The-Second-Brain
branch:           brain/v1-rc4-prime-074-compat
telemetry:        telemetry/agent-performance/hermes-Brain-Integrator-20260822_131527_09877a.jsonl
ledger:           state/sessions/b52a2289da2958fb800aff8425ad9d7d9b58e73aebafe9bc4319a8b6f5112a1e/ledger.sqlite
```

### Persistent worker

```text
bot:              Brain-Dev
role:             dev
Hermes session:   20260822_131609_d3247b
Brain session:    a33da89d24314e0fb1627ebfa23536cc85d24136c567117517242f16cc04c07c
project:          second-brain
repo:             C:/Users/assas/Documents/The-Second-Brain
branch:           brain/v1-rc4-prime-074-compat
telemetry:        telemetry/agent-performance/hermes-Brain-Dev-20260822_131609_d3247b.jsonl
ledger:           state/sessions/a33da89d24314e0fb1627ebfa23536cc85d24136c567117517242f16cc04c07c/ledger.sqlite
```

### Success communication

Task `p11-final-success-20260822-131527` is present in the parent ledger with:

```text
task_created, task_assigned, worker_started,
worker_completed, result_returned, result_reviewed
```

The lifecycle read-back contains:

```text
status:         completed
packet_bytes:   1135
result_bytes:   3744
fanout:         1
fanout_index:   0
depth:           0
requested_role: dev
worker:         Brain-Dev
worker_session: a33da89d24314e0fb1627ebfa23536cc85d24136c567117517242f16cc04c07c
```

The review row contains:

```text
approved: true
reviewed: true
status: reviewed
```

An additional bounded-size discrepancy is present in the canonical read-back:
the `worker_completed`/`result_returned` lifecycle reports `result_bytes=3744`,
while the later `result_reviewed` payload reports `result_bytes=3751`. Both are
below the 16384-byte limit, but no canonical result body or result hash is
stored, so the difference cannot be reconciled from Brain evidence. This does
not change the P1.2 classification; it reinforces the content-level
reconstruction limitation recorded below.

The parent telemetry independently contains a completed
`hermes_worker_lifecycle` record with the same task, identity, packet/result
sizes, fan-out, index, depth, and worker session. The worker telemetry contains
a separate persistent Brain-Dev session with the same project, repository, and
branch continuity and a successful finalization/checkpoint.

### Controlled failure communication

Task `p11-final-failure-20220822-131527` is present in the parent ledger with:

```text
worker_failed
result_returned
failure_code: WORKER_UNAVAILABLE
retryable: true
worker_session_id: unavailable
```

There is no Brain-Worker session ledger. The parent did not execute the
substantial delegated task locally and did not silently retry it. This is a
canonical deterministic failure path, not arbitrary chat evidence.

Both ledgers were opened independently using Python sqlite3 URI mode `mode=ro`.
The parent and worker session/agent rows preserve their distinct Hermes and Brain
identities. The canonical ledger contains lifecycle metadata sufficient to
reconstruct event order and correlation, but not the original packet/result
bodies.

## 5. Focused execution evidence

The exact historical delta-sync test was run from the project virtual
environment:

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pytest tests/test_delta_sync_live_integration.py -q
```

Result: passed, exit code 0.

A combined focused read-only run was also executed:

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pytest \
  tests/test_orchestration.py tests/test_hermes_adapter.py \
  tests/test_delta_sync_live_integration.py -q
```

Result: passed, exit code 0 (`.......................... [100%]`).

The delta-sync test itself proves unchanged memory suppression, a small memory
field diff, hash/disclosure behavior, and progressive disclosure. It does not
send a `WorkerTaskPacket`, receive a `WorkerResultPacket`, resolve `context_refs`,
or exercise result correction. Therefore its pass is supporting bounded-delta
evidence only, not complete P1.2 worker-communication evidence.

`git diff --check` passed with only the pre-existing Git line-ending warning for
`tests/test_orchestration.py`; no implementation files were changed by this
qualification.

## 6. Requirement-by-requirement classification

| # | Requirement | Classification | Independent evidence / exact limitation |
|---:|---|---|---|
| 1 | Driver -> worker through a defined bounded protocol | **PROVEN** | `WorkerTaskPacket` is canonical, bounded, role-checked, and the real P1.1 success path reached a separate persistent Brain-Dev session. |
| 2 | Worker -> driver through a defined bounded protocol | **PROVEN at transport/schema level** | `WorkerResultPacket` is bounded and task-correlated; the real success lifecycle records a returned result. The worker output-to-summary adapter is not a strict semantic result parser. |
| 3 | Correlated by task/session/worker identity | **PROVEN** | Task ID, parent session, worker session/agent, worker role, project, repository, and branch are preserved across source, telemetry, and parent/worker ledgers. |
| 4 | Narrow task context, not parent transcript | **PROVEN** | Worker invocation serializes only the bounded packet and explicit worker instructions; source forbids copying parent history. No parent transcript is present in the worker telemetry. |
| 5 | Context references resolve through Second Brain where intended | **NOT PROVEN** | `context_refs` is validated as a bounded list only. No resolver, fault-in, artifact expansion, or canonical read-back path consumes it. |
| 6 | Concise, structured, mechanically validated results | **PARTIAL** | Packet fields, status, failure code, list/text bounds, and bytes are mechanically validated. Worker output is raw bounded text in `summary`; policy-level result sections are requested but not structurally parsed or required. |
| 7 | Communication failures explicit and deterministic | **PROVEN** | Malformed/unauthorized/oversize errors and real `WORKER_UNAVAILABLE` with `retryable=true` are explicit; no local fallback was observed. |
| 8 | Result review/correction has a defined return path | **PARTIAL** | Review and approval/rejection return exists through `second_brain_review_worker_result` and `RESULT_REVIEWED`. No correction packet, targeted follow-up transport, `result_corrected` event, or worker correction return exists. |
| 9 | Events reconstructable from canonical telemetry/ledger | **PARTIAL** | Lifecycle order, IDs, status, sizes, identity, and failure/review metadata are reconstructable in canonical ledger/telemetry. Packet/result bodies and reference-resolution results are not stored, so content-level reconstruction is unavailable. |
| 10 | Protocol remains harness-neutral, not Hermes-specific | **PARTIAL** | Packet/result contracts are generic and Prime has zero Hermes references. The only real transport and runtime proof is the Hermes plugin/CLI bridge; no generic transport seam or Prime/Codex worker round trip was independently proven. |
| 11 | No arbitrary A2A chat mistaken for canonical communication | **PROVEN** | P1.1 worker proof uses persistent worker profile execution plus Brain-owned ledger/telemetry. The worker prompt explicitly forbids A2A, and no A2A transcript was used as evidence. |

## 7. Verdict and smallest missing seam

```text
P1.2_PARTIAL
```

The new P1.1 plane proves a real bounded task/result transport, persistent worker
identity continuity, deterministic failure, and canonical lifecycle metadata.
That is meaningful P1.2 implementation and runtime evidence, but it does not
satisfy the full frozen Worker Communication contract.

The smallest exact missing **single return-path seam** is a generic correction
conversation at the Brain protocol boundary:

```text
review/reject -> bounded correction request -> same-task worker correction
-> bounded corrected result -> canonical result_corrected/reviewed lifecycle
```

The current code stops at `review_worker_result()` and `RESULT_REVIEWED`; it has
no correction request/result contract or lifecycle event.

A second independently blocking seam is explicit `context_refs` resolution:
`WorkerTaskPacket.context_refs` must be consumed by a Brain-owned bounded resolver
and its resolved/faulted-in references must be represented in the returned
canonical evidence. Neither seam should be implemented by copying parent history
or by creating a Hermes-native store.

## 8. Next action and stop boundary

Next action, not performed here:

1. define the smallest harness-neutral correction and context-reference return
   contracts at the existing Brain boundary;
2. wire one real persistent worker round trip that includes a resolvable Brain
   reference and a rejected-result correction; and
3. independently read back packet/result identity, correction lifecycle,
   reference resolution, telemetry, and ledger evidence.

Do not begin P1.3. This validator stops at the `P1.2_PARTIAL` gate.
