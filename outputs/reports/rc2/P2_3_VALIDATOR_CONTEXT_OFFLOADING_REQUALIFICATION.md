# P2.3 Context Offloading — Independent Validator Re-qualification

**Verdict:** `P2.3_PARTIAL`
**Validator:** `Brain-Validator` (`validator` profile)
**Proof timestamp:** 2026-08-23T16:06:23Z
**Scope:** Read-only qualification; no implementation changes; stopped before P2.6

This report independently re-qualifies P2.3 against the current Hermes + Second
Brain runtime. It reads current source, prior P0.4/P1.2/P1.3 evidence, fresh
runtime output, canonical telemetry, and SQLite ledgers. The frozen roadmap's
historical `PROVEN` label is treated as a contract input, not as proof.

## 1. Repository baseline

```text
root:   C:/Users/assas/Documents/The-Second-Brain
branch: brain/v1-rc4-prime-074-compat
HEAD:   0bc2b8d56ceed3c1e17576283f05b4dba6f52d91
```

The worktree was already dirty from the preceding P1.1/P1.2/P1.3 work. This
qualification did not modify implementation, source, tests, plugin,
configuration, or roadmap files. Only this evidence report was written.

## 2. Exact frozen P2.3 contract

The frozen RC2 roadmap row in `outputs/reports/rc2/01-frozen-roadmap-matrix.md`
is:

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
Remaining gap:        None (historical matrix claim)
```

The operative P2.3 requirement is stronger than merely having a reducer or a
VMem table. Large or less-relevant context must be able to leave active model
context, be represented by existing Brain artifact/VMem mechanisms, remain
durably recoverable, and later be selectively faulted back in without replaying
the full transcript/tool-result stream. Where raw output is offloaded, the
existing artifact/firewall contract requires integrity-preserving, and for RTD
raw-result paths byte-exact, recovery. The current Hermes boundary must be
checked separately from older Prime-only evidence.

## 3. Existing evidence independently re-read

### 3.1 P0.4 Hermes VMem/fault-in — proven bounded path

Source manifest:

```text
outputs/reports/rc2/P0_4_VALIDATOR_RUNTIME_PROOF.md
```

Canonical persistent Hermes Validator evidence:

```text
Hermes session: 20260821_154649_d27020
Brain session:  af616602dd028c3b4c943a1d73b2eb03033debb95b7db9557272791e799e0d49
object:        obj-f9d646c21c53
result_chars:  2517
result_sha256: f9d646c21c53f438b1630defb84f72c687d191a1bde0cd35b5d1c2cca577983a
initial state: EVICTED
faulted-in:   obj-f9d646c21c53
context_chars: 2236
context_tokens:559
```

Independent telemetry parsing of
`telemetry/agent-performance/hermes-Brain-Validator-20260821_154649_d27020.jsonl`
found the real sequence:

```text
hermes_post_tool_call: result_chars=2517, residency_state=EVICTED
hermes_pre_llm_call:   vmem_context_changed=true,
                       vmem_faulted_in_ids=[obj-f9d646c21c53],
                       vmem_context_chars=2236,
                       vmem_context_tokens=559
```

Independent read-only SQLite read-back of:

```text
state/sessions/af616602dd028c3b4c943a1d73b2eb03033debb95b7db9557272791e799e0d49/ledger.sqlite
```

found `tool_completed` for the same object and project identity. The VMem row
was:

```text
obj_id:            obj-f9d646c21c53
content_sha256:    f9d646c21c53f438b1630defb84f72c687d191a1bde0cd35b5d1c2cca577983a
residency_state:   FAULTED_IN
access_count:      3
```

This proves real Hermes VMem capture, eviction, durable artifact-backed storage,
and selective same-session fault-in without transcript replay for the bounded
observation captured in that run.

It does not prove full preservation of an arbitrarily large raw Hermes tool
result because that P0.4 result was 2,517 characters and the current adapter
boundary has a 4,000-character result cap.

### 3.2 P1.2 context-reference resolution — proven, but not offloading

Source proof:

```text
outputs/reports/rc2/P1_2_FINAL_HERMES_RUNTIME_PROOF.md
```

P1.2 proves Brain-owned `context_refs` resolution and bounded worker transport.
It records hashes/sizes and sends bounded ephemeral resolved references. It does
not preserve or fault in a large Hermes tool result, and it does not prove raw
result reduction/recovery.

### 3.3 P1.3 stable-context reuse/JIT delta — proven, but not raw offloading

Source proof:

```text
outputs/reports/rc2/P1_3_FINAL_HERMES_CACHE_PRESERVATION_PROOF.md
```

The final real Hermes worker plane proves:

```text
full:       handoff=5523 bytes
unchanged:  handoff=223 bytes, cache_hit=true, delta=0
changed:    handoff=454 bytes, delta=293 bytes, jit_delta=222 bytes
```

P1.3 proves context reuse and bounded delta handoff. It does not prove that a
large Hermes tool result is preserved byte-for-byte before it is removed from
active context.

## 4. Current offloading primitives

### 4.1 Artifact store

`src/second_brain/artifacts.py` provides the correct Brain primitive:

- content-addressed blobs under `state/artifacts/blobs/<sha256>.bin`;
- metadata under `state/artifacts/meta/<sha256>.json`;
- atomic writes;
- `store_bytes()` for exact raw bytes;
- `expand()` with full-hash or unique-prefix lookup;
- SHA-256 verification on recovery;
- deterministic bounded distillation.

The exact artifact contract is sound. Identical stored bytes recover identically.

### 4.2 Observation Firewall

`src/second_brain/firewall.py` provides deterministic reducers for pytest,
compiler/typecheck, git, search, JSON, logs, build, and doctor output. It
preserves raw output through the artifact store and returns a bounded reducer
packet with a recovery handle.

`tests/test_firewall_live_integration.py` directly proves the real Python path:

```text
raw tool output -> byte-exact artifact -> deterministic reducer -> compact observation
```

### 4.3 VMem

`src/second_brain/vmem.py` stores each session object through
`artifacts.store_text()`, records a content hash in the existing `session_vmem`
table, evicts low-priority objects to preserve a token budget, and fault-ins in
by:

1. reading the object row;
2. expanding the content-addressed artifact;
3. verifying the SHA-256;
4. only then mutating residency to `FAULTED_IN`.

This is a durable, integrity-preserving VMem mechanism and does not create a
parallel Hermes store.

### 4.4 Current Hermes integration boundary

`brainstem/adapters/hermes/hermes_plugin.py` currently bounds the incoming
`post_tool_call` result before sending it to Brain:

```text
result = bounded(result, 4000)
```

`src/second_brain/hermes_adapter.py::_handle_post_tool_call()` applies the same
bounded text conversion before calling `VMemStore.store_object()`.

The resulting VMem artifact is exact for the bounded 4,000-character string,
but it is not necessarily exact for the original Hermes tool result. The Hermes
path does not call `firewall.reduce_observation()` and does not preserve the raw
incoming result through `artifacts.store_bytes()` before the 4,000-character
bound is applied.

The current Hermes `pre_llm_call` path does correctly render the existing VMem
hot context and selectively fault in an evicted object referenced by object ID or
title. That establishes real selective recovery of the bounded stored object,
not full raw-result recovery.

## 5. Fresh current Hermes-adapter large-result probe

A fresh isolated Brain home was used only for this read-only qualification probe.
The current Brain adapter was given a synthetic 6,000-character tool result and
then its actual VMem/artifact/ledger/fault-in path was exercised.

Probe home:

```text
C:/Users/assas/AppData/Local/Temp/p23-hermes-offload-do2s0z4b
```

Fresh result:

```text
input_chars:            6000
obj_id:                 obj-dbbde21298b3
stored_chars:           4000
stored_bytes:           4000
stored_equals_input:   false
input_sha256:           cf4c0e85ada6b8112e95bb5083018fc03a18272cc0bbc58dcd1a5743ada3f051
stored/artifact_sha256: dbbde21298b33b52a8b2a264de456e888f53dceb980d1d48bd6c1e0f6e5af5dd
pre_fault_state:        EVICTED
evicted_count:          0
faulted_state:          FAULTED_IN
recovered_chars:        4000
recovered_equals_stored:true
```

Independent read-only SQLite/telemetry read-back of the same isolated runtime:

```text
ledger:    state/sessions/96fc6e93bee545636529182417a0cefeaadab8574c40ab14008207ecff58b551/ledger.sqlite
tool_completed.result_chars:       4000
tool_completed.result_sha256:      dbbde21298b33b52a8b2a264de456e888f53dceb980d1d48bd6c1e0f6e5af5dd
ledger VMem residency:             EVICTED at capture
VMem read-back residency:          FAULTED_IN
VMem token_estimate:                1000
VMem access_count:                  2
telemetry kind:                     hermes_post_tool_call
telemetry result_chars:             4000
telemetry result_sha256:            dbbde21298b33b52a8b2a264de456e888f53dceb980d1d48bd6c1e0f6e5af5dd
```

This is real current Hermes/Brain adapter behavior. It proves the bounded
4,000-character observation is durably recoverable and selectively faulted in,
but it also proves the exact missing behavior: the original 6,000-character
input is not recoverable because it was truncated before artifact/VMem storage.

## 6. Historical Prime RTD/Firewall gap re-evaluation

The historical concern remains documented in:

```text
outputs/reports/v1-roadmap-baseline-reaudit.md
outputs/reports/rc4/03-prime-rtd-firewall.md
outputs/reports/rc3/02-prime-firewall-live.md
```

The old Prime-specific distinction was:

- Python `firewall.py` is a Brain-native reusable reducer reachable through the
  CLI, not imported by Prime TypeScript;
- Prime's production `tool_result` path uses TypeScript RTD instead;
- current `config/context.toml` has `[rtd] enabled = false`, so RTD substitution
  is not the default current Prime behavior.

The old Prime-vs-Firewall distinction is **not by itself** the current P2.3
blocker. P2.3 is universal/local, and current Hermes now has a real VMem
capture/eviction/fault-in path. The P0.4 Hermes evidence therefore supersedes a
purely Prime-specific objection for the narrower question of whether Hermes can
page a stored context object out and later fault that object back in.

However, the universal contract still requires large offloaded context to remain
durably recoverable. The fresh Hermes 6,000-character probe fails that stronger
requirement: Hermes VMem recovered only the 4,000-character pre-truncated value.
The blocker is therefore the Hermes raw-result preservation boundary, not the
historical fact that Prime uses RTD instead of importing Python Firewall.

The Prime RTD live report remains valid evidence for a separate Prime run: its
6,851-byte pytest output was reduced to 412 visible bytes and recovered
byte-exactly. It cannot substitute for current Hermes proof because the current
Hermes path has a different pre-storage truncation behavior and current RTD is
disabled by configuration.

## 7. Requirement-by-requirement gate result

| Gate | Result | Evidence |
|---:|---|---|
| Large/less-relevant context can leave active model context | **PARTIAL** | Real Hermes VMem evicts bounded observations and renders cold refs; no current proof preserves a full large Hermes result before eviction. |
| Existing Brain artifact/VMem representation | **PASS** | VMem stores content-addressed artifact hashes in the existing `session_vmem` table and artifact store; no parallel Hermes store. |
| Durable recovery | **PARTIAL** | Stored bounded observation is durable and recoverable; original 6,000-byte probe input was not preserved. |
| Selective later fault-in | **PASS** | P0.4 real Hermes fault-in and fresh probe both show `EVICTED -> FAULTED_IN` by object reference/title without transcript replay. |
| No full transcript/tool-result replay | **PASS** | VMem fault-in reads the content-addressed object directly; P0.4 and current source show no parent transcript replay. |
| Boundedness | **PASS** | VMem token budget, 4,000-character Hermes result bound, 4,096-character rendered context bound, and 25-entry cold-ref table are enforced. |
| Byte-exact/integrity-preserving recovery | **PARTIAL** | Artifact/Firewall/RTD and VMem verify stored bytes exactly; current Hermes verifies only the pre-truncated 4,000-character value, not the original large result. |
| Ledger/telemetry reconstruction | **PASS** | P0.4 and fresh probe read back object IDs, SHA-256, residency, result sizes, identity, project, repo, and branch from canonical ledger/JSONL. |
| Identity continuity | **PASS** | P0.4 Hermes Validator identity and fresh probe Brain session/VMem ledger continuity match. |
| No parallel Hermes-native offloading store | **PASS** | Hermes delegates to Brain `VMemStore`/artifact paths; no Hermes cache/database/offload store exists. |
| Frozen >80% observation-reduction evidence | **PARTIAL** | Python Firewall and Prime RTD tests/live pilot prove reductions, but current Hermes large-result path has no raw-vs-visible reduction metric and truncates before preservation. |

## 8. Verdict and smallest exact missing seam

```text
P2.3_PARTIAL
```

The smallest exact missing seam is:

```text
Hermes post_tool_call raw result
    -> preserve original bytes first through existing Brain artifact/Firewall/RTD primitive
    -> record original byte length + original SHA-256 + recovery handle
    -> create VMem object referencing the full artifact
    -> apply bounded summary/hot-context representation
    -> fault-in through artifact expansion and verify original SHA-256
```

The seam must preserve the existing Brain-owned artifact/VMem authority. It must
not add a Hermes-native offloading store and must not replay the parent transcript.
The next proof must use a real Hermes tool result above the current 4,000-character
boundary, demonstrate >80% visible reduction, read back the full artifact
byte-exactly, and fault it in by reference with matching original SHA-256 in
ledger and telemetry.

No implementation was made during this qualification.

## 9. Next action and stop boundary

**Next unresolved requirement:** implement and independently prove raw Hermes
tool-result preservation before the existing 4,000-character VMem bound, then
re-qualify P2.3 across current Hermes and existing universal Brain paths.

Do not start P2.6.

**STOP.**
