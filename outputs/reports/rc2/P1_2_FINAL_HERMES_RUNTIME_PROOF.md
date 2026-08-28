# P1.2 Final Hermes Worker Communication Runtime Proof

**Verdict:** `P1.2_PROVEN`
**Validator/implementer:** `Brain-Validator` (`validator` profile)
**Proof timestamp:** 2026-08-23T03:44:28Z
**Scope:** P1.2 only; stopped before P1.3

This proof closes the two seams identified by the independent P1.2
re-qualification: Brain-owned `context_refs` resolution and a bounded review /
correction / corrected-result return path with canonical hashes.

## Repository baseline

```text
root:   C:/Users/assas/Documents/The-Second-Brain
branch: brain/v1-rc4-prime-074-compat
HEAD:   0bc2b8d56ceed3c1e17576283f05b4dba6f52d91
```

Prime neutrality was rechecked:

```text
git grep -n -i hermes -- brainstem/prime-extension
```

Result: no matches. Prime TypeScript remains Hermes-unaware.

## Implementation closure

### Harness-neutral Brain protocol

`src/second_brain/contracts.py` now contains:

- `WorkerTaskPacket.canonical_hash()`;
- `WorkerResultPacket.canonical_hash()`;
- bounded `WorkerContextResolution`;
- bounded `WorkerCorrectionPacket`;
- `correction_of_hash` and `correction_attempt` on results;
- bounded correction-attempt enforcement;
- lifecycle types `task_context_resolved`,
  `result_correction_requested`, and `result_corrected`.

`src/second_brain/worker_protocol.py` is harness-neutral and resolves:

- `memory:<memory-id>` and `brain://<memory-id>` through canonical semantic
  memory files;
- `artifact:<hash-or-prefix>`, `brain://artifact/<hash-or-prefix>`, and
  `[brain-artifact:sha256:<hash>]` through the existing content-addressed
  artifact store.

Resolution is bounded to 2,048 visible characters per reference and 8,192 total
visible characters. Full source bytes are hashed; raw context is ephemeral worker
input only. Ledger and telemetry receive hashes, kinds, and sizes, never context
content.

### Adapter and Hermes bridge

`src/second_brain/hermes_adapter.py` now provides:

```text
prepare_worker_task
request_worker_task
review_worker_result
request_worker_correction
return_corrected_worker_result
```

The adapter mechanically validates task, result, correction, task identity,
worker role, correction attempt, original-result hash, corrected-result hash,
and corrected worker identity. It records canonical hashes on lifecycle and
review rows.

`brainstem/adapters/hermes/hermes_plugin.py` now exposes the additive tool:

```text
second_brain_correct_worker_result
```

The plugin delegates resolution and validation to the Brain adapter. It passes
resolved context ephemerally to the worker and maintains only a bounded
in-process handoff cache of the exact result object produced by the immediately
preceding delegate/correction call. The cache is capped at 16 task results and
is not a durable Hermes memory, ledger, queue, or telemetry store.

The active Integrator and Dev profile-local plugin copies were refreshed from
the repository adapter solely to exercise the real persistent runtime. Their
SHA-256 matched the repository plugin copy before the final probe.

`brainstem/adapters/hermes/plugin.yaml` declares four tools and both profile
plugin doctors passed:

```text
registrations: 4 tool(s), 5 hook(s)
```

Telemetry schema additions document context resolution, correction requests,
corrected results, packet hashes, result hashes, and correction hashes.

## Focused automated evidence

All commands used the project virtual environment with polluted Python variables
removed.

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pytest \
  tests/test_orchestration.py tests/test_hermes_adapter.py tests/test_worker_protocol.py -q
```

Passed, exit code 0.

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pytest tests/test_ledger.py tests/test_autoinject.py -q
```

Passed, exit code 0.

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pytest tests/test_delta_sync_live_integration.py -q
```

Passed, exit code 0.

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m ruff check src tests brainstem/adapters/hermes
```

`All checks passed!`

```text
git diff --check
```

Passed; only the pre-existing Git LF/CRLF warning for
`tests/test_orchestration.py` was printed.

## Final real persistent Hermes proof

The final task was run by a persistent Hermes Brain-Integrator session, which
invoked the real Brain-Dev Hermes profile twice: once for the initial result and
once for the correction.

### Parent coordinator

```text
bot:              Brain-Integrator
role:             integrator
Hermes session:   20260822_232722_4f1398
Brain session:    07864b28fd782b96cbb92eb6b234b3f9cce473915054c15139e375e3c56f4c3a
host session:     hermes:Brain-Integrator:20260822_232722_4f1398
project:          second-brain
repo:             C:/Users/assas/Documents/The-Second-Brain
branch:           brain/v1-rc4-prime-074-compat
telemetry:        telemetry/agent-performance/hermes-Brain-Integrator-20260822_232722_4f1398.jsonl
ledger:           state/sessions/07864b28fd782b96cbb92eb6b234b3f9cce473915054c15139e375e3c56f4c3a/ledger.sqlite
```

Final task:

```text
task_id:                    p12-real-correction-4-20260822-232722
packet_sha256:              78c32868d2f4502bf8e9afb6c44832bc21dcedfcee92c9b7bf10cf271abd95cb
packet_bytes:               1094
context_resolution_sha256:  0639bd83380da2bf156f447eb994b33ae444d1a3307e09299019761dffa15c73
context_ref_count:          1
fanout:                     1
fanout_index:               0
depth:                       0
failure_code:               null
```

The resolved reference was the existing canonical Brain memory
`brain://mem-7ee245204a5e`. Telemetry recorded the memory body hash and 413
source/visible characters without storing the body.

### Initial persistent worker result

```text
worker bot:                 Brain-Dev
worker role:                dev
Hermes session:             20260822_234220_1a2197
Brain session:              96c7e1b3f3afdef58619913f987dd743a28f245e696e2fd0797da356011edc11
result_bytes:               878
result_sha256:              fb5514e377fa8eb420cdfff6b1e471da9f5983d7a1690bda141db79eb1fe816f
status:                     completed
failure_code:               null
retryable:                  false
telemetry:                  telemetry/agent-performance/hermes-Brain-Dev-20260822_234220_1a2197.jsonl
ledger:                     state/sessions/96c7e1b3f3afdef58619913f987dd743a28f245e696e2fd0797da356011edc11/ledger.sqlite
```

Parent ledger sequence for this task begins:

```text
task_created
 task_assigned
 task_context_resolved
 worker_started
 worker_completed
 result_returned
```

### Rejection and bounded correction request

The parent coordinator rejected the initial result through the Brain review path:

```text
result_reviewed
reviewed:                 true
approved:                 false
status:                   rejected
result_sha256:            fb5514e377fa8eb420cdfff6b1e471da9f5983d7a1690bda141db79eb1fe816f
```

It then created the bounded correction packet:

```text
result_correction_requested
correction_attempt:       1
original_result_sha256:   fb5514e377fa8eb420cdfff6b1e471da9f5983d7a1690bda141db79eb1fe816f
correction_sha256:        8fd49874bae99f944ed06c7d3e3dbfc2ec9e7ee81f9eb4897463b2a6bf240d0f
requested_change_count:   1
evidence_requirement_count: 1
status:                   requested
```

### Corrected persistent worker result

```text
worker bot:                 Brain-Dev
worker role:                dev
Hermes session:             20260822_234241_11f823
Brain session:              a1ebba272775615f3460e196a2ad28b62194b9d811eb928c1bf372765c377534
result_bytes:               1015
result_sha256:              2bdd70c1188ae4e6db1d50817ec4d2c4d0b4e4e86eb962342ba634bd6d92174b
correction_of_hash:         fb5514e377fa8eb420cdfff6b1e471da9f5983d7a1690bda141db79eb1fe816f
correction_attempt:         1
status:                     corrected
failure_code:               null
retryable:                  false
telemetry:                  telemetry/agent-performance/hermes-Brain-Dev-20260822_234241_11f823.jsonl
ledger:                     state/sessions/a1ebba272775615f3460e196a2ad28b62194b9d811eb928c1bf372765c377534/ledger.sqlite
```

Parent ledger then records:

```text
result_corrected
result_returned
```

with the same packet hash, context-resolution hash, correction hash, original
result hash, corrected result hash, worker role, and task identity.

### Final review

```text
result_reviewed
reviewed:                 true
approved:                 true
status:                   reviewed
result_sha256:            2bdd70c1188ae4e6db1d50817ec4d2c4d0b4e4e86eb962342ba634bd6d92174b
correction_of_hash:       fb5514e377fa8eb420cdfff6b1e471da9f5983d7a1690bda141db79eb1fe816f
correction_attempt:       1
```

The final parent telemetry rows and the read-only SQLite ledger agree on the
complete lifecycle. Both worker telemetry files independently show
`Brain-Dev`, role `dev`, project `second-brain`, the same repository and branch,
and finalized/checkpointed sessions.

## Canonical read-back result

The parent ledger was opened with Python sqlite3 URI `mode=ro`, as were both
worker ledgers. Read-back verified:

- exact task identity and parent session continuity;
- one resolved Brain context reference;
- bounded packet/result sizes;
- initial result hash equals rejected review hash;
- correction packet hash and attempt are stable;
- corrected result cites the initial result hash;
- corrected result hash equals final approved review hash;
- rejection has `reviewed=true, approved=false`;
- final acceptance has `reviewed=true, approved=true`;
- no failure code on the successful final task;
- two real persistent Brain-Dev sessions;
- no A2A or Hermes-native chat used as canonical evidence;
- Prime TypeScript remains Hermes-unaware.

Earlier probes with deliberately non-identical result objects were rejected with
`CORRECTION_MISMATCH` / `MALFORMED_RESULT`; those failures confirm the hash and
correlation guard rather than being used as success evidence.

## Final gate

```text
P1.2_PROVEN
```

P1.2 is closed. The next roadmap item is P1.3, but no P1.3 work was started.
STOP.
