# P3.3 Reversible Tool Distillation — OMP Primary Qualification

**Verdict:** `P3.3_PROVEN`
**Stop boundary:** P3.4 not started.

## Minimal seam closed

The existing `tool_completed` ledger mirror now carries only bounded RTD/VMem
correlation metadata after the existing RTD and VMem operations complete:

```text
rtd_distilled
rtd_original_chars
rtd_visible_chars
rtd_saved_chars
rtd_artifact_sha256
rtd_artifact_ref
rtd_command_class
vmem_obj_id
recovery_status
tool_call_id
```

Child workers also emit an existing `task_context_resolved` ledger row from the
P3.2 task marker, carrying `task_id`, `packet_sha256`, and `worker_session_id`.
No raw tool output is stored in ledger or telemetry. No new store or event
system was created.

## Runtime provenance

- OMP: `omp/18.0.4`
- Extension: `brainstem/prime-extension/src/index.ts`
- Repository: `brain/v1-rc4-prime-074-compat`
- HEAD: `0bc2b8d56ceed3c1e17576283f05b4dba6f52d91`
- Current extension SHA-256: `9251a9dc0694c5401dba4a9e493423e1c3f5f3969dc2481b8c9a3098f7656423`
- Fresh parent session: `2026-08-24T15-17-41-937Z_01a03459-49b1-7403-ba0e-0583f21ebc4c`
- Fresh worker session: `GitLogWorker`

Runtime gates used the existing configuration path:

```text
[rtd] enabled = true
[vmem_admission] enabled = true
[context_paging] enabled = true
```

## Parent lifecycle reconstruction

Parent telemetry:

```text
telemetry/agent-performance/2026-08-24T15-17-41-937Z_01a03459-49b1-7403-ba0e-0583f21ebc4c.jsonl:17
```

```text
tool_call_id:       call_UgAv67R464CLlAtX5TP4JEy2|fc_0e7e809898073f56016a8c60b3e72087d297721eb5267b9143
command_class:      git
original_chars:     51331
visible_chars:      2606
saved_chars:        48725
artifact_sha256:    b13bfa80fa95d6088bb4ee1f59774d702f0755b0c68eb383948c6d6db497a297
distilled:          true
```

Artifact metadata/blob and `artifact expand` agree on SHA-256 and size:

```text
size: 51331
sha256: b13bfa80fa95d6088bb4ee1f59774d702f0755b0c68eb383948c6d6db497a297
```

Parent VMem object:

```text
obj-92326190505d
artifact_ref: b13bfa80fa95d6088bb4ee1f59774d702f0755b0c68eb383948c6d6db497a297
```

The object was moved `RESIDENT -> EVICTED` with `vmem compact-prep`, then
resolved through `vmem resolve --json`:

```text
resolution: artifact
byte_exact: true
residency_state: FAULTED_IN
access_count: 2
```

Canonical parent ledger:

```text
state/sessions/0eb040118cbb40a48d9cc557cb4836fc09c2710f70c7e37f7547187898a046f6/ledger.sqlite
```

`events.seq=5`, `tool_completed`, contains the same tool-call identity,
artifact SHA/reference, RTD sizes, `vmem_obj_id=obj-92326190505d`, and
`recovery_status=admitted`.

## Worker lifecycle reconstruction

Worker telemetry:

```text
telemetry/agent-performance/GitLogWorker.jsonl:14
```

```text
tool_call_id:       call_1SxYYV1sTuNQtF4wM8lv0d5c|fc_04cdd1244f2f7558016a8c60f8416c87d2aa7122437d32e41b
command_class:      git
original_chars:     51331
visible_chars:      2606
saved_chars:        48725
artifact_sha256:    f56264669bf91e238dccbebf710c06ad8d41c800e6698b3709d9224febea32c3
distilled:          true
```

Artifact metadata/blob and `artifact expand` agree on SHA-256 and size:

```text
size: 51331
sha256: f56264669bf91e238dccbebf710c06ad8d41c800e6698b3709d9224febea32c3
```

Worker VMem object:

```text
obj-5572195690e7
artifact_ref: f56264669bf91e238dccbebf710c06ad8d41c800e6698b3709d9224febea32c3
```

The worker object was moved `RESIDENT -> EVICTED` with `vmem compact-prep`,
then resolved through `vmem resolve --json`:

```text
resolution: artifact
byte_exact: true
residency_state: FAULTED_IN
access_count: 2
```

Canonical worker ledger:

```text
state/sessions/b575d8fc369c9cea647fe183ab8cdca95f022e204559d11c9c7e37241cd82273/ledger.sqlite
```

`events.seq=1`, `task_context_resolved`, binds the worker session to the P3.2
packet/task identity. `events.seq=5`, `tool_completed`, contains the worker
tool-call identity, artifact SHA/reference, RTD sizes, `vmem_obj_id`, and
`recovery_status=admitted`.

## Parent/worker identity agreement

Parent ledger `events.seq=11` records the worker task packet and parent session:

```text
parent_session_id: 2026-08-24T15-17-41-937Z_01a03459-49b1-7403-ba0e-0583f21ebc4c
task_id:           omp-d723b8376c4e758812159d72b23c56a5122f2a3be15ce796ef34172a989d9e42
packet_sha256:     ffebd7874a6586fa31289883837e9dbe73bceaeb75151bae2bf57068ed0f164d
```

Worker ledger `events.seq=1` repeats the same task/packet identity and records:

```text
worker_session_id: GitLogWorker
```

The worker RTD `tool_completed` row then binds the child tool result to its
own artifact and VMem object. Telemetry corroborates the same tool-call and
artifact identities; it is not the sole correlation source.

## Safety and verification

- Raw result remains outside ledger/telemetry; only hashes, references, sizes,
  status, and identities are persisted.
- Existing ineligible-result and disabled-gate tests remain passing.
- OMP suite: **22 files, 580 tests passed**.
- TypeScript typecheck passed.
- ESLint passed.
- Focused artifact, Firewall, Action Cache, VMem, worker, RTD, and wiring tests
  passed.
- Parent and worker artifact expansion returned matching SHA-256 values.
- Parent and worker VMem readback returned `byte_exact=true`.
- Independent Validator readback confirmed the canonical ledger fields now bind
  RTD artifact, VMem object, recovery status, tool identity, and parent/worker
  session identity.

## Final disposition

```text
P3.3_PROVEN
```

P3.4 was not started.
