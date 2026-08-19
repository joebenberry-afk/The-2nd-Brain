# The Second Brain — RC2 Frozen 37-Item Roadmap Status Matrix

**Document**: `outputs/reports/rc2/01-frozen-roadmap-matrix.md`  
**Governing Authority**: Master Plan §3 / RC1→RC2 Plan §3  
**RC1 Base Commit**: `611f65f977ef217b057e367ae38de9e201e0f7a7`  
**RC2 Candidate Branch**: `brain/v1-rc2-repair`  
**Date**: 2026-08-19  

---

## Roadmap Status Ledger (Exact 37-Item Checklist)

| Item ID | Requirement Name | Implementation | Integration Status | Automated Evidence | Live Evidence | Cross-Harness Status | Token Evidence | Dogfood Evidence | Remaining Gap | Final Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **P0.1** | Automatic Brain Initialization | `autoinject.py`, `prime-extension/src/index.ts` | ACTIVE | `tests/test_autoinject.py`, `wiring.test.ts` | Prime session_start hook | Level A (Prime), Level B (Claude, AGY) | 0 token overhead on init | Used in every session | None | **PROVEN** |
| **P0.2** | Automatic Recall | `semantic.py`, `hybrid_retrieval.py` | ACTIVE | `tests/test_hybrid_retrieval.py` | Hybrid cascade Tier 0-2 live query | Level A (Prime), Level B (Claude, Codex) | ≥80% vector calls avoided | Used in retrieval | Full runtime wire (R6) | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P0.3** | Automatic Routing | `router.py`, `skills.py` | ACTIVE | `tests/test_router.py` | Intent-based domain tool/skill dispatch | Cross-harness | Descriptor-first token bounding | Used in tool/skill match | None | **PROVEN** |
| **P0.4** | Automatic Context Injection | `autoinject.py`, `vmem.py` | ACTIVE | `tests/test_autoinject.py`, `test_vmem.py` | Bounded prompt injection | Level A (Prime), Level B (Claude, Codex) | Sparse gate (0 when irrelevant) | Used in dogfood sessions | Live VMem wire in Prime | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P0.5** | Automatic Activity Capture | `ledger.py`, `session_ledger.py` | ACTIVE | `tests/test_session_ledger.py` | JSONL structured events | Universal local | Zero model calls (local write) | Used in all turns | None | **PROVEN** |
| **P0.6** | Injection Telemetry | `telemetry.py`, `governor.py` | ACTIVE | `tests/test_telemetry.py`, `test_governor.py` | `assistant_usage` & `brain_packet` tracking | Prime Level A, others Level B | Measured vs estimated separation | Verified in telemetry logs | Wire into host result loop | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P1.1** | Strict Driver/Worker Plane | `orchestration.py`, `prime-extension/src/orchestrator.ts` | PARTIAL | `tests/test_orchestration.py`, `driver-orchestrator.test.ts` | Bounded worker spawning | Prime native | Cheaper worker tokens | Used in multi-agent tests | Hard concurrency enforcement (R8) | **PARTIAL** |
| **P1.2** | Worker Communication | `orchestration.py`, `delta_sync.py` | PARTIAL | `tests/test_delta_sync.py` | Structured assignment/result packets | Prime native | Delta sync diff packets (≤20% size)| Tested in synthetic sessions | Production packet wire (R8) | **PARTIAL** |
| **P1.3** | Cache-Preserving Context | `jit.py`, `vmem.py`, `delta_sync.py` | ACTIVE | `tests/test_jit.py`, `test_vmem.py` | Stable prefix + JIT compiler | Universal | Context replacement savings | Verified in VMem tests | Prime context-replace hook wire | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P2.1** | Deterministic Projections | `db.py`, `doctor.py`, `semantic.py` | ACTIVE | `tests/test_doctor.py`, `test_db.py` | Derived DB & index rebuild | Universal local | Zero model tokens | Doctor repair proven | Rebuild verification gate (R8) | **PROVEN** |
| **P2.2** | Lossless Event Ledger & Compaction | `ledger.py`, `vmem.py` | ACTIVE | `tests/test_session_ledger.py`, `test_vmem.py` | Checkpoint + Compaction barrier | Prime native, Universal local | Compact resume state | Tested in session compact | Live compaction test (R3) | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P2.3** | Context Offloading | `artifacts.py`, `firewall.py`, `vmem.py` | ACTIVE | `tests/test_artifacts.py`, `test_firewall.py` | Content-addressed storage | Universal local | >80% observation reduction | Verified in benchmark | Host tool result filter (R2) | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P2.4** | Repository Intelligence | `scout.py`, `doctor.py` | PARTIAL | `tests/test_scout.py`, `test_doctor.py` | AST/module map inspection | Universal local | Reference-based exposure | Verified in doctor | Persistent incremental map (R8) | **PARTIAL** |
| **P2.5** | Risk-Adaptive Verification | `risk.py`, `verify.py` | ACTIVE | `tests/test_risk.py`, `test_verify.py` | Targeted vs subsystem test scaling | Universal local | Token-scaled test runs | Verified in build brief | None | **PROVEN** |
| **P2.6** | Intelligent Model Routing | `router.py`, `crossmodel.py` | PARTIAL | `tests/test_crossmodel.py`, `test_router.py` | Model tier recommendation | Universal | Premium model escalation only | Unit tested | Cost-aware token routing (R8) | **PARTIAL** |
| **P3.1** | Active State Capsule | `working_set.py` | ACTIVE | `tests/test_working_set.py` | Objective/phase/decisions capsule | Universal | Lean capsule context (~150 tokens) | Used across all runs | None | **PROVEN** |
| **P3.2** | Context Capsule | `working_set.py`, `vmem.py` | ACTIVE | `tests/test_working_set.py`, `test_vmem.py` | Minimal worker context capsule | Universal | Focused subtask injection | Used in worker dispatch | Live hook delivery (R8) | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P3.3** | Reversible Tool Distillation | `brainstem/prime-extension/src/rtd.ts` | PARTIAL | `tests/rtd.test.ts` | Shadow RTD store & execution | Prime native | Replaces model calls with script | Shadow tested | Production RTD promotion (R9) | **PARTIAL** |
| **P3.4** | Lean Code / Lean Build | `lean_runtime.py`, `prime-extension/src/lean.ts` | PARTIAL | `tests/test_lean_runtime.py`, `lean-code.test.ts` | Lean change policy | Prime native | Smallest change, minimal tokens | Shadow tested | Runtime promotion (R9) | **PARTIAL** |
| **P3.5** | Simplification Review | `contracts.py`, `governance` | ACTIVE | `tests/test_contracts.py` | Dead code/wrapper cleanup | Universal | Reduces codebase complexity | Verified in audits | None | **PROVEN** |
| **P3.6** | STOP Discipline | `contracts.py`, `cli.py` | ACTIVE | `tests/test_contracts.py` | Strict stop condition enforcement | Universal | Eliminates trailing token waste | Verified across all phases | None | **PROVEN** |
| **P3.7** | Risk-Adaptive Accuracy Gate | `verify.py`, `contracts.py` | ACTIVE | `tests/test_verify.py`, `test_contracts.py` | Evidence required before completion | Universal | Prevents invalid iterations | Verified in build brief | None | **PROVEN** |
| **P3.8** | Independent Intent Verification | `verify.py` | PARTIAL | `tests/test_verify.py` | Fresh verifier distinct from driver | Universal | Prevents self-fulfilling loops | Advisory only | Hard independent verifier wire (R9)| **PARTIAL** |
| **P3.9** | Environment Steward | `envsteward.py`, `paths.py` | ACTIVE | `tests/test_envsteward.py`, `test_paths.py` | Env/branch/worktree/port validation | Universal | Deterministic environment checks | Verified in doctor | None | **PROVEN** |
| **P3.10** | Improvement Radar | `telemetry.py` | MISSING | None | Inefficiency & thrash detector | Universal local | Detects repeated reads/searches | None | Implement Improvement Radar (R9) | **MISSING** |
| **P3.11** | Skill Forge | `skills.py`, `promotion.py` | ACTIVE | `tests/test_skills.py`, `test_promotion.py` | Candidate → Evaluation → Promotion | Universal local | Validates skill ROI | Tested in isolation | None | **PROVEN** |
| **P3.12** | Skill Verifier | `promotion.py` | ACTIVE | `tests/test_promotion.py` | Candidate vs baseline comparison | Universal local | Token & latency measurement | Tested in isolation | None | **PROVEN** |
| **P3.13** | Counterfactual Skill Evaluation | `promotion.py`, `tests/test_skills.py` | ACTIVE | `tests/test_skills.py` | Isolated offline paired eval | Universal local | Proves skill token advantage | Tested in isolation | None | **PROVEN** |
| **P3.14** | Skill ROI | `credit.py`, `skills.py` | PARTIAL | `tests/test_credit.py` | Usage & savings tracking | Universal local | Measured vs estimated savings | Basic ledger tracking | Complete Skill ROI report (R9) | **PARTIAL** |
| **P3.15** | Skill Gardener | None | MISSING | None | Proactive skill pruning/archive | Universal local | Retires low-ROI/harmful skills | None | Implement Skill Gardener (R9) | **MISSING** |
| **P3.16** | Modular Skill Visibility | `router.py`, `skills.py` | ACTIVE | `tests/test_router.py`, `test_skills.py` | Task → router → relevant skills only | Universal local | Descriptor-first, JIT instructions | Verified in router tests | None | **PROVEN** |
| **P3.17** | Brain Handoff | None | MISSING | None | Standard cross-agent handoff artifact | Cross-harness | Seamless context transfer | None | Implement Brain Handoff (R9) | **MISSING** |
| **P4.1** | Long-Running Goals | None | MISSING | None | Local Brain-owned goal state machine | Universal local | Tracks multi-day objectives | None | Implement Long-Running Goals (R10) | **MISSING** |
| **P4.2** | Schedules / Heartbeats | `cli.py:heartbeat` | PARTIAL | Basic CLI | Periodic local health probes | Universal local | No change = 0 model calls | Basic CLI | Zero-token local heartbeat (R10) | **PARTIAL** |
| **P4.3** | Operational Telemetry | `telemetry.py`, `governor.py` | ACTIVE | `tests/test_telemetry.py`, `test_governor.py` | Systemic metrics tracking | Universal local | Full feature attribution | Verified in logs | Wire new telemetry fields (R10) | **IMPLEMENTED_BUT_NOT_PROVEN** |
| **P4.4** | Bottleneck Fingerprinting | None | MISSING | None | Structural bottleneck detector | Universal local | Identifies systemic token waste | None | Implement Fingerprinting (R10) | **MISSING** |
| **P4.5** | Controlled Self-Optimization | `plasticity.py`, `promotion.py` | PARTIAL | `tests/test_plasticity.py` | Governed optimization lifecycle | Universal local | Governed promotion + rollback | Partial promotion tests | Prove real governed lifecycle (R10)| **PARTIAL** |

---

## Baseline Status Summary

- **Total Requirements**: 37
- **PROVEN**: 10
- **IMPLEMENTED_BUT_NOT_PROVEN** (Runtime Integration Needed): 8
- **PARTIAL**: 13
- **MISSING**: 6 (P3.10 Improvement Radar, P3.15 Skill Gardener, P3.17 Brain Handoff, P4.1 Long-Running Goals, P4.4 Bottleneck Fingerprinting, and missing live wires)
