# RC2 Token Fabric & Runtime Integration Audit

**Document**: `outputs/reports/rc2/02-token-fabric-live-wiring-audit.md`  
**Phase**: R1 — Runtime Integration Audit  
**Date**: 2026-08-19  
**Candidate**: `brain/v1-rc2-repair`  

---

## 1. Executive Summary & Audit Mandate

An implementation artifact in isolation (CLI command, standalone library, or passing unit test) does **not** constitute runtime integration. This audit evaluates every token-efficiency and context primitive against live production execution paths across Prime Agent 0.7.3, Claude Code, Codex, and Antigravity.

---

## 2. Token Fabric Primitive Live Wiring Matrix

| Primitive | Module | Implemented? | CLI? | Unit Tested? | Live Prime-Wired? | Claude-Wired? | Codex-Wired? | AGY-Wired? | Dogfooded? | Token Impact Measured? |
|---|---|---|---|---|---|---|---|---|---|---|
| **Token Governor** | `governor.py` | YES | YES | YES (33 tests) | PARTIAL (Telemetry measured; switchboard not yet gating hooks) | NO | NO | NO | PARTIAL | PARTIAL (A-I profiles configured) |
| **Observation Firewall** | `firewall.py` | YES | YES | YES (18 tests) | PARTIAL (TypeScript RTD present; Python reducers need live hook wire) | NO | NO | NO | PARTIAL | YES (>80% reduction proven) |
| **Context Virtual Memory** | `vmem.py` | YES | YES | YES (9 tests) | PARTIAL (Compaction barrier present; auto-paging needs live loop wire) | NO | NO | NO | PARTIAL | YES (1,500 token budget enforced) |
| **Action Cache** | `action_cache.py` | YES | YES | YES (9 tests) | NO (Needs wiring into deterministic tool executions / file reads) | NO | NO | NO | PARTIAL | YES (0 net model tokens on hit) |
| **Delta Sync** | `delta_sync.py` | YES | YES | YES (8 tests) | NO (Needs direct integration into `autoinject.py` delivery ledger) | NO | NO | NO | PARTIAL | YES (≤20% patch size, 0 tokens on unchanged) |
| **Hybrid Retrieval** | `hybrid_retrieval.py`| YES | YES | YES (7 tests) | NO (Needs integration into `autoinject.py:prepare_injection` & `recallBrief`) | NO | NO | NO | PARTIAL | YES (80% short-circuit ratio) |
| **Tool Working Set** | `tool_working_set.py`| YES | YES | YES (6 tests) | NO (Needs host tool registration and intent dispatch wire) | NO | NO | NO | PARTIAL | YES (≤500 tokens initial footprint) |
| **JIT Context Compiler** | `jit.py` | YES | YES | YES | YES (Active in autoinject and context assembly) | NO | NO | NO | YES | YES (Prefix caching preserved) |
| **FTS5 Lexical Search** | `semantic.py` | YES | YES | YES | YES (Active in `autoinject.py` and `recallBrief`) | YES | YES | YES | YES | YES (Deterministic BM25) |
| **Session Ledger** | `ledger.py` | YES | YES | YES | YES (Live telemetry mirror on all turns) | YES | YES | YES | YES | YES (0 token local write) |
| **Working Set Capsule** | `working_set.py` | YES | YES | YES | YES (Context capsule injected in session start) | YES | YES | YES | YES | YES (~150 token lean state) |
| **Tool Distillation (RTD)** | `rtd.ts` | YES | YES | YES | YES (Shadow/Advisory mode in Prime `tool_result`) | NO | NO | NO | PARTIAL | YES (Byte-exact artifact recovery) |

---

## 3. Repair Roadmap for Live Wiring (Phases R2–R7)

1. **R2 (Observation Firewall)**:
   - Wire `firewall.reduce_observation` into host tool result handlers (Python `autoinject` and TypeScript `prime-extension`).
   - Deliver compact summary + lossless recovery handle (`/brain-expand <hash>`).
2. **R3 (Context Virtual Memory)**:
   - Wire `VMemStore` into the session lifecycle: record tool findings as transient session objects, enforce token budget, and preserve continuity across compactions.
3. **R4 (Proof-Carrying Action Cache)**:
   - Harden `validate_proof()` to check Git tree hash, env variables, TTL, and verification predicates.
   - Intercept pure actions (file reads, directory scans, verification checks) before execution.
4. **R5 (Delta Sync)**:
   - Integrate `DeltaSyncEngine` into `autoinject.py` so memory deliveries send only minimal JSON diffs and emit 0 tokens for unchanged items.
5. **R6 (Hybrid Cascade Retrieval)**:
   - Replace linear recall with `HybridCascadeRetriever` (Tiers 0–4) in `autoinject.py:prepare_injection` and `prime-extension/src/recall.ts`.
6. **R7 (Dynamic Tool Working Set)**:
   - Integrate `ToolWorkingSetManager` with tool registration, pruning idle domain tools dynamically.
