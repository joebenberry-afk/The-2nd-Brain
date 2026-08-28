# P2.3 Final Hermes Context Offloading Proof

**Verdict:** `P2.3_PROVEN`
**Validator:** `Brain-Validator` (`validator` profile)
**Implementation scope:** P2.3 only
**Proof timestamp:** 2026-08-23T16:31:34Z
**Stop boundary:** P2.6 not started

This proof records the preserve-first Hermes post-tool implementation and the
independent Validator read-back of the real oversized Hermes result, exact Brain
artifact, VMem state transition, telemetry, and canonical ledger.

## 1. Frozen contract

The RC2 frozen roadmap row is:

```text
Item:                 P2.3
Requirement:          Context Offloading
Implementation:       artifacts.py, firewall.py, vmem.py
Integration status:   ACTIVE
Automated evidence:   tests/test_firewall_live_integration.py,
                      tests/test_vmem_live_integration.py
Live evidence:        Content-addressed storage
Cross-harness:        Universal local
Token evidence:       >80% observation reduction
Dogfood evidence:     Verified in benchmark
```

The required behavior is preserve-first offloading: complete raw tool output is
stored losslessly through existing Brain artifact/Firewall/RTD mechanisms before
model-visible reduction; VMem holds a reference to the lossless artifact; active
context receives only a bounded representation; the artifact can later be
evicted and selectively faulted in without transcript replay; and the original
bytes/hash remain recoverable.

## 2. Preserve-first implementation

### Hermes transport

`brainstem/adapters/hermes/hermes_plugin.py` now sends both:

```text
result:      existing bounded compatibility representation
raw_result:  complete JSON-safe result transport
```

Bytes use a bounded JSON-safe base64 wrapper; strings and JSON-safe structures
are transported without the former 4,000-character truncation.

### Brain adapter

`src/second_brain/hermes_adapter.py::_handle_post_tool_call()` now:

1. decodes the complete raw result;
2. stores exact bytes with existing `artifacts.store_bytes()`;
3. expands and verifies the artifact before reduction;
4. runs the existing deterministic `firewall.reduce_observation()` separately;
5. records original length, original bytes, original SHA-256, visible bytes,
   reduction ratio, artifact reference, and recovery handle;
6. stores the bounded reduction in VMem with `artifact_ref=<raw_sha256>`.

### VMem

`src/second_brain/vmem.py::VMemStore.store_object()` accepts an existing
`artifact_ref`, verifies the referenced artifact hash, and records that hash in
the existing `session_vmem` row. `fault_in()` already verifies and expands the
artifact before changing residency to `FAULTED_IN`.

No Hermes-native artifact, VMem, database, cache, or offloading store was added.

## 3. Real oversized Hermes runtime

The real Validator Hermes session was:

```text
Hermes session: 20260823_122741_555728
Brain session:  17ed5d118c2693bf757f29f0488e50ecde8d930fccd845e53516072a09bc5327
Host identity:  hermes:Brain-Validator:20260823_122741_555728
Project:        second-brain
Repo:           C:/Users/assas/Documents/The-Second-Brain
Branch:         brain/v1-rc4-prime-074-compat
```

The agent executed a real project command:

```text
C:/Users/assas/Documents/The-Second-Brain/.venv/Scripts/python.exe -m pytest tests -vv
```

The successful tool result was genuinely oversized:

```text
original_result_chars: 51603
original_result_bytes:  51605
status:                 ok
```

The current Hermes telemetry record was:

```text
kind:                    hermes_post_tool_call
obj_id:                  obj-012e70234744
original_result_bytes:   51605
original_result_chars:   51603
original_result_sha256:  012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
artifact_ref:            012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
recovery_handle:         [brain-artifact:sha256:012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff]
visible_result_bytes:    631
reduction_ratio:         0.987773
distilled:               true
residency_state:         RESIDENT
```

Active visible reduction was therefore 98.7773%, above the required 80%.

## 4. Independent artifact read-back

The Validator independently expanded:

```text
C:/Users/assas/Documents/The-Second-Brain/state/artifacts/blobs/
012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff.bin
```

Read-back result:

```text
artifact bytes:          51605
artifact SHA-256:        012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
VMem content_sha256:     012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
artifact_matches_object: true
```

The expanded artifact is byte-identical to the complete raw Hermes result
represented by the recorded original SHA-256.

## 5. Independent VMem eviction and selective fault-in

The Validator opened the existing VMem session, evicted the object with the
existing budget mechanism, then called the current Hermes Brain `pre_llm_call`
path with the object ID as the selective recovery reference.

```text
before fault-in:          EVICTED
pre_llm status:            ok
vmem_context_changed:     true
vmem_faulted_in_ids:      [obj-012e70234744]
vmem_context_chars:       2236
vmem_context_tokens:      559
fault marker present:     true
after fault-in:           FAULTED_IN
access_count:             2
recovered bytes:          51605
recovered SHA-256:        012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
recovered exact:          true
```

The faulted-in active context remained bounded at 2,236 characters / 559 token
estimate. Relative to the 51,605-byte raw artifact, this is a 95.6671% reduction
even on the selective fault-in response; the original full bytes remained in the
artifact store and were independently recovered exactly.

No parent transcript or full tool-result replay was used to recover the object.

## 6. Independent canonical ledger read-back

The parent ledger was opened with Python `sqlite3` URI `mode=ro`:

```text
state/sessions/17ed5d118c2693bf757f29f0488e50ecde8d930fccd845e53516072a09bc5327/ledger.sqlite
```

The `tool_completed` row independently read back:

```text
obj_id:                   obj-012e70234744
original_result_bytes:    51605
original_result_sha256:   012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
artifact_ref:             012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
recovery_handle:          [brain-artifact:sha256:012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff]
visible_result_bytes:     631
reduction_ratio:          0.987773
residency at capture:     RESIDENT
bot_name:                 Brain-Validator
bot_role:                 validator
project_id:               second-brain
repo_root:                C:/Users/assas/Documents/The-Second-Brain
branch_id:                brain/v1-rc4-prime-074-compat
```

The subsequent Brain packet ledger row independently read back:

```text
vmem_context_changed:     true
vmem_faulted_in_ids:      [obj-012e70234744]
vmem_context_chars:       2236
vmem_context_tokens:      559
```

The existing ledger/session identity, VMem table, and artifact store are the
only durable offloading authorities used by this path.

## 7. Independent telemetry read-back

Telemetry file:

```text
telemetry/agent-performance/hermes-Brain-Validator-20260823_122741_555728.jsonl
```

The Validator independently read:

```text
hermes_post_tool_call:
  original_result_bytes: 51605
  original_result_sha256: 012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
  artifact_ref: 012e70234744265f11feab68ca53c9b90a1272e76f5eca7a66fb16caef8735ff
  visible_result_bytes: 631
  reduction_ratio: 0.987773
  residency_state: RESIDENT

hermes_pre_llm_call:
  vmem_context_changed: true
  vmem_faulted_in_ids: [obj-012e70234744]
  vmem_context_chars: 2236
  vmem_context_tokens: 559
```

Telemetry contains only bounded metadata, hashes, sizes, residency, and recovery
handles; it does not contain the raw result body.

## 8. Verification checks

Passed:

- Hermes adapter focused suite including the oversized preserve/reduce/fault-in
  test;
- Firewall live integration, artifact, and VMem live integration tests;
- worker protocol, ledger, and AutoInject regression tests;
- Ruff across `src`, `tests`, and Hermes adapter;
- Pyright: `0 errors, 0 warnings, 0 informations`;
- Prime RTD, VMem, context-paging, and cache-stability tests: 165 passed;
- Hermes Validator plugin doctor;
- `git diff --check`.

Prime remains Hermes-unaware. No P2.6 work was started.

## 9. Final classification

```text
P2.3_PROVEN
```

All required P2.3 gates are now independently proven:

- complete raw Hermes result preserved before visible reduction;
- artifact reference, original length, and SHA-256 recorded;
- visible context reduced by more than 80%;
- VMem object points to the lossless artifact;
- object evicted and selectively faulted in by reference;
- recovered artifact is byte-exact/SHA-256-identical;
- canonical ledger and telemetry reconstruct the full lifecycle;
- no Hermes-native offloading store exists.

**STOP. Do not start P2.6.**
