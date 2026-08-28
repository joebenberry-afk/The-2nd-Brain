# P1.3 Hermes Cache-Preserving Context — Independent Re-qualification

**Verdict:** `PARTIAL`
**Validator:** `Brain-Validator` (`validator` profile)
**Proof timestamp:** 2026-08-23T04:01:51Z
**Scope:** P1.3 only; no implementation changes and no P1.4 work

This report independently re-qualifies P1.3 against the newly proven P1.1/P1.2
worker plane. It persists evidence only; it does not modify implementation.

## Repository baseline

```text
root:   C:/Users/assas/Documents/The-Second-Brain
branch: brain/v1-rc4-prime-074-compat
HEAD:   0bc2b8d56ceed3c1e17576283f05b4dba6f52d91
```

The worktree was already dirty from the P1.1/P1.2 implementation and proof
work. No implementation, test, plugin, configuration, or roadmap file was
changed by this re-qualification.

## 1. Exact frozen P1.3 contract

The frozen RC2 roadmap row in
`outputs/reports/rc2/01-frozen-roadmap-matrix.md` is:

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
Historical gap:       None (historical claim, independently re-qualified here)
```

The older frozen P1 matrix describes the same contract as:

- deterministic JIT Context Compiler;
- working-set/context assembly;
- stable-prefix preservation in the Prime integration; and
- real stable-prefix/cache-gate evidence.

The prior independent baseline re-audit is more conservative: it classified
P1.3 as `IMPLEMENTED_BUT_NOT_PROVEN` because deterministic JIT output and
static prefix tests existed, but no current host-reported cache-read/cache-write
measurement had been captured.

This re-qualification applies the requested P1.3 checks: narrow worker packets,
Brain context references, bounded deltas, VMem/AutoInject ordering, bounded
correction traffic, repeated-context reuse, telemetry granularity, and current
real Hermes evidence. Provider-native cache counters are not required by the
frozen row; they are reported when available and not inferred when absent.

## 2. Read-only inspection

### JIT compiler

`src/second_brain/jit.py::compile_context` is a deterministic local compiler.
It combines:

- active-state capsule;
- requirement ledger;
- read ledger;
- optional project state; and
- matching lexicon sections.

The body is deterministic for identical inputs; only the `compiled_at` header
changes. The output is a markdown capsule under
`outputs/context-capsules/<session>-<slug>.md`.

The JIT compiler is invoked by the Brain CLI context-compile path and is covered
by `tests/test_jit.py`. No call to `jit.compile_context` exists in the Hermes
plugin, Hermes adapter, or the new P1.2 worker preparation path.

### VMem and AutoInject

`src/second_brain/vmem.py` provides the existing resident/evicted/faulted-in
working set, deterministic token-budget eviction, compact cold-reference table,
and bounded fault-in. The Hermes `pre_llm_call` path invokes existing VMem hot
context rendering and returns it as ephemeral context. P1.2 worker telemetry
contains bounded VMem/context metrics for the parent and worker sessions.

`src/second_brain/autoinject.py` provides the existing retrieval, validity gate,
delivery deduplication, packet rendering, and token/delta budgets. Hermes uses
that existing AutoInject authority rather than a second memory system.

### Delta sync

`src/second_brain/delta_sync.py` provides memory-item deltas:

```text
ADD, MODIFY, REMOVE, SUPERSEDE, TOMBSTONE, UNCHANGED
```

It supports canonical hash verification, zero rendered text for unchanged
memory, minimal patches, and recipient/session deduplication. It is not called
by `hermes_adapter.py`, `worker_protocol.py`, or the Hermes plugin for worker
packets, resolved context, or correction traffic.

### Hermes worker bridge

The P1.2 Hermes bridge sends the worker:

```text
worker_task_packet
resolved_brain_context
worker_correction (only for correction calls)
```

The context block is bounded and derived from canonical Brain references, but the
same resolved context is re-created and placed into each initial/correction
worker prompt. The plugin has a bounded in-process result handoff cache, not a
context cache or context-delta cache.

The parent-side Hermes README states that `pre_llm_call` results are injected
into the ephemeral current user message rather than the system prompt. That is
cache-friendly ordering for the parent system prefix, but it does not invoke the
JIT compiler or establish worker-level provider-prefix reuse.

### Prime ordering and neutrality

The Prime `before_agent_start` path was re-read. Its ordering is:

```text
base system prompt
-> driver contract
-> lean kernel
-> optional dynamic recall brief
-> host-appended AutoInject custom message
```

The Prime cache-stability test verifies byte-identical driver/lean system prompt
assembly across ten simulated turns and verifies stable tool-surface hashing.
`git grep -n -i hermes -- brainstem/prime-extension` returned no matches.

## 3. Existing P1.2 real-runtime evidence reused

Final P1.2 task:

```text
task_id:                    p12-real-correction-4-20260822-232722
parent:                     hermes:Brain-Integrator:20260822_232722_4f1398
packet_sha256:              78c32868d2f4502bf8e9afb6c44832bc21dcedfcee92c9b7bf10cf271abd95cb
packet_bytes:               1094
context_ref_count:          1
context_visible_chars:      413
context_source_chars:       413
context_resolution_sha256:  0639bd83380da2bf156f447eb994b33ae444d1a3307e09299019761dffa15c73
initial_result_bytes:       878
corrected_result_bytes:     1015
```

The initial and corrected result traffic is bounded and the corrected result
cites the initial result hash. The same packet hash and context-resolution hash
are present in the initial and corrected lifecycle records. This proves stable
identity and stable context content across the correction boundary, but it does
not prove that the context was served from a cache: the bridge resolves the
references again and has no `context_cache_hit` or delta-emission record.

The P1.2 parent telemetry file is:

```text
telemetry/agent-performance/hermes-Brain-Integrator-20260822_232722_4f1398.jsonl
```

It contains `packet_bytes`, `packet_sha256`, `context_ref_count`,
`context_visible_chars`, `context_source_chars`,
`context_resolution_sha256`, `result_bytes`, and `result_sha256` for the final
worker lifecycle.

## 4. Provider-native cache counters

The current Hermes parent and worker telemetry files contain no:

```text
assistant_usage
provider_request_meta
cache_read_tokens
cache_write_tokens
```

The repository contains older Prime/provider telemetry with cache counters, but
those records are unrelated historical sessions and are not evidence for the
current Hermes P1.2 runtime. No cache percentage is inferred from them.

Therefore provider-native cache-hit proof is `UNAVAILABLE` for the current
Hermes sessions and is not used as a hidden acceptance criterion.

## 5. Fresh runtime and automated evidence

### Fresh JIT probe

Two consecutive `jit.compile_context` calls with identical inputs in an
isolated temporary Brain home produced:

```text
same_path:       True
body_bytes:      164, 164
body_sha256:     41c4a36de574cac445d5e8b5ef8e658f4dcdac83cde86a43755352b2a2f9911f
                 41c4a36de574cac445d5e8b5ef8e658f4dcdac83cde86a43755352b2a2f9911f
body_identical:  True
compiled_at_diff: True
```

This independently proves deterministic JIT body reuse, but only for the JIT
compiler itself, not Hermes worker hot-path invocation.

### Fresh focused suites

```text
env -u PYTHONHOME -u PYTHONPATH -u UV_INTERNAL__PYTHONHOME -u PYTHONSTARTUP \
  .venv/Scripts/python.exe -m pytest tests/test_jit.py tests/test_vmem_live_integration.py -q
```

Passed, exit code 0.

```text
npm exec vitest run tests/cache_stability.test.ts
```

Passed: 1 file, 3 tests.

The Python VMem suite proves budget eviction, pinned-state preservation,
fault-in, compaction snapshot/resume, and cold-reference rendering. The Prime
cache suite proves deterministic stable system-prompt assembly and tool-surface
hash stability.

## 6. Requirement-by-requirement classification

| # | Requirement | Classification | Independent evidence / limitation |
|---:|---|---|---|
| 1 | Stable parent/coordinator context is not recopied wholesale into worker requests | **PROVEN** | Worker prompt contains only the bounded task packet, resolved Brain context, and optional bounded correction; no parent transcript is copied. |
| 2 | WorkerTaskPacket remains narrow and bounded | **PROVEN** | P1.2 final packet is 1,094 bytes versus the 16,384-byte limit; task fields and list/text bounds are mechanically validated. |
| 3 | Worker context comes through `context_refs` / Brain retrieval rather than duplicated transcript text | **PROVEN** | Final Hermes task resolved `brain://mem-7ee245204a5e`; telemetry recorded one reference and hashes/sizes only. |
| 4 | Repeated worker operations reuse stable context rather than rebuilding changing prefixes | **PARTIAL** | Initial/corrected operations share packet/context hashes, but the bridge resolves and sends the same context again; no context cache hit or reuse counter exists. Each correction uses a new worker session. |
| 5 | Task-specific context is appended/retrieved as a bounded delta | **PARTIAL** | Context is bounded and appended ephemerally, but Hermes worker traffic does not call `delta_sync.py` or emit a worker-context delta/unchanged record. |
| 6 | Result/correction traffic remains bounded and does not destabilize parent context unnecessarily | **PROVEN** | Initial result 878 bytes, corrected result 1,015 bytes, correction packet bounded, result cache capped at 16, and no transcript copying. |
| 7 | AutoInject/VMem/context-ref behavior preserves cache-friendly ordering and stable prefixes | **PARTIAL** | Hermes preserves the parent system prefix by returning context through the ephemeral current-user/custom-message path; Prime system-prefix ordering is tested. Hermes worker JIT/delta integration is absent. |
| 8 | Telemetry distinguishes packet bytes, resolved-context bytes/tokens, result bytes, and repeated/deduplicated context where available | **PARTIAL** | Packet/result bytes and context source/visible characters plus resolution hash are recorded. Resolved-context bytes/tokens and cache-hit/dedup fields are not recorded; provider counters are unavailable in current Hermes files. |
| 9 | No unnecessary full-resend behavior remains in Hermes worker lifecycle | **PARTIAL** | Parent transcript is not resent, but the same resolved context is included again in correction worker input; no delta/unchanged suppression is present for worker context. |
| 10 | Real runtime produces measurable P1.3 evidence | **PARTIAL** | Real Hermes telemetry provides bounded packet/context/result measurements and stable hashes; fresh JIT/VMem/Prime tests prove deterministic primitives. Current Hermes provider cache counters and worker prefix fingerprints are absent. |

## 7. Verdict and smallest exact missing seam

```text
P1.3_PARTIAL
```

The existing JIT, VMem, AutoInject, delta-sync, and Prime stable-prefix
primitives are implemented and tested. The newly proven P1.2 Hermes plane is
bounded and does not copy parent transcripts. However, P1.3 is not proven for
the current Hermes worker lifecycle because the worker bridge does not connect
the existing JIT/delta machinery to repeated worker context operations.

The smallest exact missing seam is:

```text
prepare_worker_task / correction worker preparation
    -> stable context fingerprint/cache or delta lookup
    -> JIT/delta-aware bounded context payload
    -> telemetry: context bytes/tokens + cache_hit/dedup/unchanged state
```

That seam must reuse the existing JIT, VMem, AutoInject, and delta-sync
primitives. It must not copy the parent transcript, create a Hermes-native
context store, or require inferred provider cache percentages.

## 8. Next action and stop boundary

Next action, not performed here: implement and independently prove the smallest
harness-neutral worker-context cache/delta handoff above, including stable-prefix
and repeated-context telemetry. Provider-native cache counters should remain
optional and explicitly unavailable when the host does not emit them.

No implementation was changed in this qualification. Do not begin P1.4.
STOP at `P1.3_PARTIAL`.
