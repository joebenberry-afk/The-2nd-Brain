# RC2 Qualification Status & Invalidation Record

**Project**: The Second Brain  
**Document**: `outputs/reports/rc2/00-qualification-status.md`  
**Governing Plan**: `second_brain_rc1_to_rc2_gemini_repair_qualification_plan.md`  
**Date**: 2026-08-19  
**RC1 Base SHA**: `611f65f977ef217b057e367ae38de9e201e0f7a7`  
**RC1 Branch**: `brain/v1-token-efficient`  
**RC2 Repair Branch**: `brain/v1-rc2-repair`  

---

## 1. Release Candidate Status Overview

| Candidate | Commit SHA | Qualification Status | Notes |
|---|---|---|---|
| **RC1** | `611f65f977ef217b057e367ae38de9e201e0f7a7` | **FAILED_INDEPENDENT_QUALIFICATION** | Retained immutably on `brain/v1-token-efficient` for audit trail. |
| **RC2** | (Active repair in progress) | **IN_REPAIR** | Target: Auditable Release Candidate 2 for external verification. |

---

## 2. Invalidation & Audit Findings for RC1

The independent qualification audit identified six critical findings (F1–F6) in RC1 that prevent qualification as v1.0:

1. **F1 — Final Roadmap Substitution**:
   - RC1 final closure substituted a revised phase taxonomy in place of the original frozen 37-item P0–P4 roadmap (§3 of Master Plan).
   - *Resolution*: Previous closure report `outputs/reports/v1-p0-p4-closure-report.md` is marked `INVALIDATED_FOR_RELEASE_QUALIFICATION`. The original 37-item roadmap is restored as the sole completion authority in `outputs/reports/rc2/01-frozen-roadmap-matrix.md`.
2. **F2 — Synthetic Token Economics**:
   - `tests/test_dogfood_token_economics.py` evaluated ROI classification logic using hardcoded data rather than live host-reported token telemetry from paired Brain-OFF vs Brain-ON runs.
   - *Resolution*: Execute real paired workload runs (MICRO, STANDARD, DEEP, DEBUG, RESEARCH, REVIEW, HANDOFF) capturing actual host token metrics.
3. **F3 — Primitives Not Integrated into Live Runtime Paths**:
   - Primitives (`vmem.py`, `firewall.py`, `action_cache.py`, `hybrid_retrieval.py`, `tool_working_set.py`, `delta_sync.py`) were created as standalone libraries + CLI + tests, but were not fully integrated into `brainstem/prime-extension/src/index.ts` and `src/second_brain/autoinject.py`.
   - *Resolution*: Wire all token-efficiency and context primitives directly into production hooks and autoinject dispatch.
4. **F4 — Cross-Harness Overclaims**:
   - Codex was reported as PASS despite being shadow-only, and Antigravity real-agent verification relied on historical tests.
   - *Resolution*: Perform live capability-negotiated qualification across Prime Agent (Level A), Claude Code (Level B), Codex (Level B/fallback), and Antigravity (Level B/fallback).
5. **F5 — Action Cache Incomplete Proof Validation**:
   - `ActionProof` declared fields (`git_tree_hash`, `verification_predicate`) that were not strictly enforced during cache replay.
   - *Resolution*: Harden `validate_proof()` to strictly enforce every declared dependency (file SHA, Git tree, env, TTL, predicate).
6. **F6 — Unclosed Phase-0 Gaps**:
   - Unresolved roadmap gaps (P2.4 Repository Intelligence, P3.8 Independent Verifier, P3.10 Improvement Radar, P3.14/3.15 Skill ROI & Gardener, P3.17 Brain Handoff, P4.1 Long-running Goals, P4.2 Heartbeats, P4.4 Bottleneck Fingerprinting, P4.5 Governed Self-Optimization).
   - *Resolution*: Audit and close every genuine gap against the exact 37-item matrix.

---

## 3. Governance Directives

- **Immutable Baseline**: RC1 commit `611f65f977ef217b057e367ae38de9e201e0f7a7` remains intact and unmodified on GitHub remote.
- **Frozen Scope**: No feature scope creep or roadmap alteration.
- **Release Prohibition**: The implementation agent will **not** tag `v1.0.0`, merge to `main`, or claim `Production Ready`.
- **Handoff Target**: Produce complete evidence pack in `outputs/reports/rc2/` and STOP for independent external verification.
