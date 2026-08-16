# P0-P2 Campaign — RESUME AFTER PRIME RESTART

Written 2026-08-16 before a user-initiated Prime daemon restart (required to purge stale
extension versions in long-lived daemon workers).

## State
- Branch: brain/p0-p2-production-core @ 647175f (tree clean except pre-existing untracked
  memory/semantic/mem-ae7a34f105c5.md - never touch)
- P0 code complete + unit-proven: pytest 699/2, vitest 241, ruff/pyright clean
- Extension deployed + synced: ~/.prime/agent/extensions/second-brain/ (10/10 hash match
  with repo; backups second-brain.bak-*)
- config/autoinject.toml [autoinject] mode = "shadow" (safe default)

## IMMEDIATE NEXT ACTION (final G1 live observation)
1. Flip: config/autoinject.toml [autoinject] mode = "advisory" (only that line)
2. Spawn fresh worker (deepseek-v4-flash) with task text containing "adaptive fan-out policy"
   and these instructions: (a) check own context for custom_message "[BRAIN_CONTEXT_DELTA v1]"
   and quote it; (b) tail telemetry/agent-performance/<sid>.jsonl for brain_retrieval_attempt /
   brain_packet_delivered / autoinject_shadow_decision (fields mode, result_patch,
   handler_returned_message, cli_packet_chars, emit_index, cache_hit); (c) flip config back to
   "shadow"; (d) reply verdict.
3. Expected after restart: ONE spawn, emit 2..N served by file cache (cache_hit=true),
   result_patch=true, and the [BRAIN_CONTEXT_DELTA v1] custom_message IN context.
4. If observed: update outputs/reports/p0-autoinject-gate.md verdict to P0 PASS (G1 in-context
   arm proven), commit, then proceed to Phase D (P1 orchestration per amendment).
5. If still absent: record honestly; P0 = PARTIAL with exact missing item; proceed to Phase D.

## Phase D (next) — P1 per amendment sec 12/31
- Owner worker: phase0a-audit2 (retained, holds all context; reuse via agent_message steer)
- Scope: primitive-selection policy (driver MAY do trivial deterministic work; adaptive
  fan-out replaces hard 2-worker cap), verifier role, A2A coordination, driver contract +
  brainstem/policies updates, orchestration telemetry, delegation-purity dogfood.
- Known constraints: RLM_MAX_DEPTH=1 (child recursion unsupported by daemon config);
  root-vs-child token attribution UNAVAILABLE.

## Phase G (P2) — after P1
- Session ledger (contracts.py exists: BrainLifecycleEvent/RequestEpoch/SessionSegment/
  LedgerHeader), migration 0009, projections, replay, Prime artifact referencing,
  compaction barrier via session_before_compact, recovery tests.

## Required final deliverables (original plan + amendment)
outputs/reports/p0-p2-current-state-audit.md DONE
outputs/reports/p0-p2-amendment-gap-matrix.md DONE
outputs/reports/p0-p2-harness-capability-probe.md DONE
outputs/reports/p0-autoinject-gate.md (finalize after G1 observation)
outputs/reports/p1-orchestration-cache-gate.md
outputs/reports/p2-session-continuity-gate.md
outputs/reports/P0_P2_FINAL_IMPLEMENTATION_REPORT.md
docs/research/p0-p2-upstream-reference-map.md

## Commits so far
5472937 0A audit | 9c88c70 0B contracts | 6c3a8cf 0008 db | 87f1315 0C core |
1ea08bb/113f092 0C adapters | 843c5bf/ead00bb 0D | 6888286 gap matrix |
b8195a7 capability probe | bc7c2ca C1 gate | 3f35bd1 C2 | feda116 C3 |
186d20b C4 | c97f2b8 seeds | 647175f C5-C8 emit-stable
