# P1.3 Final Hermes Cache-Preservation Proof

**Validator verdict:** `P1.3_PROVEN`
**Validator:** `Brain-Validator` (`validator` profile)
**Proof timestamp:** 2026-08-23T13:01:45Z
**Stop boundary:** P1.4 not started

This report is the independent Validator qualification after implementing the
Brain-owned stable worker-context fingerprint/reuse and JIT delta handoff in the
existing P1.2 preparation/correction path.

## Repository baseline

```text
root:   C:/Users/assas/Documents/The-Second-Brain
branch: brain/v1-rc4-prime-074-compat
HEAD:   0bc2b8d56ceed3c1e17576283f05b4dba6f52d91
```

The worktree was already dirty from the preceding P1.1/P1.2 work. This P1.3
implementation added/changed only the worker protocol/adapter/plugin telemetry
and focused test surfaces required for this gate; no P1.4 work was begun.

## 1. Exact frozen P1.3 contract

The frozen row in `outputs/reports/rc2/01-frozen-roadmap-matrix.md` is:

```text
Item:                 P1.3
Requirement:          Cache-Preserving Context
Implementation:       jit.py, vmem.py, delta_sync.py
Integration status:   ACTIVE
Automated evidence:   tests/test_vmem_live_integration.py
Live evidence:        stable prefix + JIT compiler
Cross-harness:        Universal
Token evidence:       context replacement savings
Dogfood evidence:     verified in VMem tests
```

The frozen contract requires cache-preserving context behavior, not a guessed
provider cache percentage. This qualification therefore proves the worker
plane's stable-prefix/context handoff with bounded Brain-owned fingerprints,
reuse, JIT deltas, and measurable telemetry. Provider-native cache counters are
collected when present and are not inferred when absent.

## 2. Implemented seam independently inspected

### Brain-owned worker handoff

`src/second_brain/worker_protocol.py` now provides:

- `prepare_context_handoff()`;
- `_latest_context_snapshot()` and `_store_context_snapshot()` using the existing
  per-session `ledger.LedgerStore` object store (`object_refs`, role
  `worker_context_snapshot`), not a new database or Hermes-native memory store;
- stable fingerprints over canonical context-reference metadata and the stable
  JIT body hash;
- `full`, `unchanged`, and `delta` handoff modes;
- bounded changed-reference and unified JIT-line deltas;
- `validate_context_handoff()` so request/correction transport accepts only a
  packet-correlated, current, byte-accounted Brain handoff;
- `visible_bytes`, `visible_tokens_estimate`, handoff bytes/tokens, delta
  bytes/tokens, JIT body/delta bytes, cache-hit, reuse, and fingerprint metadata.

Volatile JIT headers are excluded from the fingerprint. The full wire-shape
byte count includes both resolved context and full-mode `jit_context`; the
canonical existing `WORKER_PACKET_MAX_BYTES = 16_384` bound is enforced.

### Existing P1.2 path

`src/second_brain/hermes_adapter.py` now:

- prepares the handoff in `prepare_worker_task()`;
- accepts the exact prepared handoff in `request_worker_task()` rather than
  resolving/rendering it again;
- accepts the exact prepared handoff in
  `return_corrected_worker_result()`;
- records additive bounded telemetry/ledger fields without raw context text.

`brainstem/adapters/hermes/hermes_plugin.py` passes
`worker_context_handoff` to the persistent worker. The worker payload contains
only the narrow task packet, the full/reuse/delta handoff, and optional bounded
correction data; it never receives parent transcript history.

`brainstem/telemetry/SCHEMA.md` documents the additive context mode, reuse,
fingerprint, byte/token, JIT, and delta fields for worker lifecycle events.

## 3. Automated evidence

Final focused/regression command:

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pytest \
  tests/test_orchestration.py tests/test_hermes_adapter.py \
  tests/test_worker_protocol.py tests/test_ledger.py tests/test_autoinject.py \
  tests/test_jit.py tests/test_vmem_live_integration.py \
  tests/test_delta_sync_live_integration.py -q
```

Result: **101 passed**, exit code 0.

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m ruff check src tests brainstem/adapters/hermes
```

Result: **All checks passed!**, exit code 0.

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pyright \
  src/second_brain/worker_protocol.py \
  src/second_brain/hermes_adapter.py \
  brainstem/adapters/hermes/hermes_plugin.py
```

Result: **0 errors, 0 warnings, 0 informations**, exit code 0.

```text
npm exec vitest run tests/cache_stability.test.ts
```

Result: **1 file, 3 tests passed**, exit code 0.

The Prime cache-stability suite independently proves byte-identical stable
system-prompt assembly over ten turns and deterministic provider-prefix/tool
surface fingerprints. `git grep -n -i hermes -- brainstem/prime-extension`
returned no matches, so Prime TypeScript remains Hermes-unaware.

Hermes plugin doctor passed for both active profiles:

```text
integrator: runtime discovery, manifest parsing, import, registration passed
           4 tools, 5 hooks
 dev:      runtime discovery, manifest parsing, import, registration passed
           4 tools, 5 hooks
```

`git diff --check` passed; the only output is the pre-existing Git LF/CRLF
warning for `tests/test_orchestration.py`.

## 4. Fresh real persistent Hermes runtime

The final fresh runtime used one persistent interactive Hermes Integrator
process so the exact canonical worker result remained available across the
review/correction calls. The parent session was:

```text
Hermes session: 20260823_084923_c59f26
Brain session:  13700b00ab5fb02453a59097517710896a7f48fed2d9369a1827de1b56c86758
Host identity:  hermes:Brain-Integrator:20260823_084923_c59f26
Role:           Brain-Integrator / integrator
Project:        second-brain
Repo:           C:/Users/assas/Documents/The-Second-Brain
Branch:         brain/v1-rc4-prime-074-compat
Task:           p13-interactive-20260823-084923
```

The initial packet used one Brain reference:

```text
context_refs:              [brain://mem-7ee245204a5e]
packet_bytes:              900
packet_sha256:             15f0d5e16a64f7b177906f12be434c8e888cd02d7d000d1926bf8119f0722ca5
context_ref_count:         1
context_visible_chars:     413
context_visible_bytes:     413
context_visible_tokens:    103 (bounded estimate)
context_resolution_sha256: 0639bd83380da2bf156f447eb994b33ae444d1a3307e09299019761dffa15c73
```

### Initial full handoff

Real worker result:

```text
worker role:               Brain-Dev / dev
worker Brain session:      a32fea817d1a5d3ddd1ef6cd4a4306b26850f437e7402b05b3d4c37b65399572
result_bytes:              1693
context_mode:              full
context_cache_hit:         false
context_reused:            false
context_handoff_bytes:     5523
context_delta_bytes:       0
jit_body_bytes:            4570
jit_delta_bytes:           0
resolved_context_sent:     true (worker report)
```

### Unchanged-context correction

The same task was corrected without changing the Brain reference or JIT
working-set context. Independent parent ledger/telemetry read-back shows:

```text
worker Brain session:      e286d6e2771ceb40c91786eaa9a1ad7b99ba864828ec77f8b79ed494a31e6148
context_mode:              unchanged
context_cache_hit:         true
context_reused:            true
context_fingerprint:       6a555f1f68b52fc16b97fe111c5f73add3d5c2f36df58e76757edd8712e9afa4
previous_fingerprint:      6a555f1f68b52fc16b97fe111c5f73add3d5c2f36df58e76757edd8712e9afa4
context_handoff_bytes:     223
context_delta_bytes:       0
context_delta_tokens:      0
jit_delta_bytes:           0
resolved_context_sent:     false (worker report)
result_bytes:              1388
```

A second identical correction also recorded the same `unchanged`/`cache_hit`
state. Repeated identical context preparation is deduplicated in the append-only
ledger by its stable resolution key while every preparation remains measurable
in telemetry.

### Changed-context correction

Only the parent session's existing derived Brain working-set capsule was changed
between corrections. The `context_refs` memory content remained unchanged, so
this isolates the JIT delta path. Independent read-back shows:

```text
worker Brain session:      0583c557d8e9e33bb3f2f26dc99101db6aed8b27a545412d62ca5d04a240c5ef
context_mode:              delta
context_cache_hit:         false
context_reused:            false
context_fingerprint:       1ca9df2c04f7902feeceaeabcb58032d4143e7c865875480bc5eb65e20a366f3
previous_fingerprint:      6a555f1f68b52fc16b97fe111c5f73add3d5c2f36df58e76757edd8712e9afa4
context_handoff_bytes:     454
context_delta_bytes:       293
context_delta_tokens:      73
changed_ref_count:          0
removed_ref_count:          0
jit_body_bytes:             4683
jit_delta_bytes:            222
resolved_context_sent:      false (worker report)
result_bytes:               1824
```

The changed case therefore sent only the bounded JIT delta and did not resend
resolved context. The full-to-unchanged handoff reduction was 5,300 bytes; the
full-to-delta reduction was 5,069 bytes. These are byte counts of the canonical
handoff wire shape, not inferred provider cache percentages.

The focused protocol test additionally proves a changed Brain reference case:
`changed_ref_count=1`, `resolved_context=[]`, one changed reference in
`context_delta.changed_refs`, and `context_delta_bytes <= 16,384`.

## 5. Independent persistent ledger read-back

The parent ledger was opened independently with Python `sqlite3` URI
`mode=ro`:

```text
state/sessions/13700b00ab5fb02453a59097517710896a7f48fed2d9369a1827de1b56c86758/ledger.sqlite
```

Read-back result:

```text
parent events:       31
worker snapshots:    2 existing LedgerStore object_refs
raw "content" key:   absent from every worker lifecycle/context payload
```

The parent ledger reconstructs the initial task and all correction records,
including full, unchanged, and delta context modes. The packet SHA-256 remains
constant across those records, the context-resolution SHA-256 remains constant,
and only the stable context fingerprint/JIT delta fields change in the changed
case.

The persistent Brain-Dev ledgers independently read back successfully with
`sqlite3` URI `mode=ro`:

```text
full worker:       a32fea817d1a5d3ddd1ef6cd4a4306b26850f437e7402b05b3d4c37b65399572
                   9 events; Brain-Dev/dev; project/repo/branch continuous
unchanged worker:  e286d6e2771ceb40c91786eaa9a1ad7b99ba864828ec77f8b79ed494a31e6148
                   4 events; Brain-Dev/dev; project/repo/branch continuous
duplicate reuse:   1c7ab821b511beeff8aba01333fb0f7b5f4d7a34a271b4f3b6473bbce49ea686
                   5 events; Brain-Dev/dev; project/repo/branch continuous
delta worker:      0583c557d8e9e33bb3f2f26dc99101db6aed8b27a545412d62ca5d04a240c5ef
                   7 events; Brain-Dev/dev; project/repo/branch continuous
```

All four worker ledgers contain real Hermes session start/finalization and
Brain project/repository/branch continuity. No parent transcript is present in
the worker payload; workers receive the bounded worker packet/handoff only.

## 6. Telemetry read-back

Parent telemetry:

```text
telemetry/agent-performance/hermes-Brain-Integrator-20260823_084923_c59f26.jsonl
```

Independent parser output for the relevant records:

```text
hermes_worker_context_resolved  full       cache_hit=false handoff=5523 delta=0   jit_delta=0   visible_bytes=413 visible_tokens=103
hermes_worker_result_corrected  unchanged  cache_hit=true  handoff=223  delta=0   jit_delta=0   result_bytes=1388
hermes_worker_result_corrected  unchanged  cache_hit=true  handoff=223  delta=0   jit_delta=0   result_bytes=1467
hermes_worker_result_corrected  delta      cache_hit=false handoff=454  delta=293 jit_delta=222 result_bytes=1824
```

The telemetry fields distinguish packet bytes, context visible bytes/tokens,
full handoff bytes/tokens, delta bytes/tokens, JIT body/delta bytes, result
bytes, reuse/cache state, fingerprints, and canonical hashes. Worker telemetry
contains the corresponding real Brain-Dev session identities.

The current parent telemetry contains no `assistant_usage` or
`provider_request_meta` records and therefore no current Hermes provider-native
cache counters. No cache-hit percentage was inferred. The frozen contract does
not require provider-native cache counters.

## 7. Requirement gate results

| Gate | Result | Evidence |
|---:|---|---|
| 1. Parent/coordinator context is not copied wholesale | **PASS** | Worker invocation source sends only `worker_task_packet`, `worker_context_handoff`, and optional correction; real unchanged/delta reports say `resolved_context_sent=false`. |
| 2. WorkerTaskPacket is narrow/bounded | **PASS** | Final packet is 900 bytes, below the 16,384-byte canonical bound; schema/list/text/fanout/depth validation remains active. |
| 3. Context comes through context_refs/Brain retrieval | **PASS** | One real `brain://mem-7ee245204a5e` reference resolved to 413 bounded visible bytes; telemetry stores hashes/sizes, not transcript text. |
| 4. Stable context is reused | **PASS** | Same fingerprint on unchanged correction; `context_mode=unchanged`, `cache_hit=true`, `reused=true`, 223-byte handoff, no resolved context. |
| 5. Changed context is a bounded delta | **PASS** | Real JIT-only change emitted `context_mode=delta`, 293-byte/73-token bounded delta and 222-byte JIT delta; changed-ref unit/integration test emits only one changed reference when a Brain memory changes. |
| 6. Result/correction traffic stays bounded | **PASS** | Real result sizes 1,388–1,824 bytes; correction attempts remain within the existing maximum of 3; no parent transcript transport. |
| 7. AutoInject/VMem/cache-friendly ordering remains intact | **PASS** | Existing Prime stable-prefix suite 3/3; Prime is Hermes-unaware; real parent telemetry preserves AutoInject/VMem measurements and worker context is separate from the parent system prefix. |
| 8. Telemetry distinguishes packet/context/result/reuse | **PASS** | Independent JSONL read-back contains packet bytes, context visible bytes/tokens, handoff/delta bytes/tokens, JIT bytes, result bytes, fingerprints, and cache/reuse booleans. |
| 9. No unnecessary full resend | **PASS** | Full handoff only on first use; unchanged correction sends no resolved context; changed correction sends only JIT/reference delta and no resolved context. |
| 10. Real measurable runtime evidence | **PASS** | Fresh persistent Hermes Integrator plus four persistent Brain-Dev sessions, independently read from canonical telemetry and SQLite ledgers. |

## 8. Final classification

```text
P1.3_PROVEN
```

The smallest previously missing seam is now present and proven:

```text
Brain worker preparation/correction
    -> existing LedgerStore object_refs snapshot
    -> stable context fingerprint
    -> full / unchanged / bounded delta handoff
    -> exact prepared-handoff validation at transport
    -> bounded reuse/delta/JIT telemetry
```

No new Hermes-native memory/cache store was introduced. Existing Brain JIT,
VMem/AutoInject ordering, context-reference resolution, ledger object storage,
and delta-oriented bounded protocol primitives remain the authority.

## 9. Stop boundary

P1.3 is independently qualified as proven. No P1.4 implementation, proof, or
roadmap work was started.

**STOP.**
