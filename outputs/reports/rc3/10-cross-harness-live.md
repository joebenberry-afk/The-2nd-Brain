# RC3 Real Cross-Harness Qualification Report

**Document ID**: `outputs/reports/rc3/10-cross-harness-live.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Scope**: Empirical live proof on all 4 target harnesses (Prime Agent, Claude Code, Codex, Antigravity).  
**Raw Evidence Base**: `outputs/reports/rc3/raw/cross-harness/`  
**Status**: `LIVE_RUNS_CAPTURED`

---

## 1. Cross-Harness Execution Matrix

| Harness | Integration Level | Active Lifecycle Hook Capabilities Verified | Fail-Open Tested? | Raw Evidence Directory |
| :--- | :--- | :--- | :--- | :--- |
| **Prime Agent** | Level A | SessionInit, AutoInject, Hybrid retrieval, Tool Firewall, VMem, Compaction barrier, Worker event, Telemetry, Handoff | YES | `outputs/reports/rc3/raw/cross-harness/prime/` |
| **Claude Code** | Level B | SessionStart, memory injection, PreCompact checkpoint, Stop writeback, handoff resume | YES | `outputs/reports/rc3/raw/cross-harness/claude-code/` |
| **Codex** | Level B | Startup/bootstrap, model-visible Brain context, retrieval, handoff | YES | `outputs/reports/rc3/raw/cross-harness/codex/` |
| **Antigravity (AGY)** | Level A/B | PreInvocation, PostToolUse, AutoInject, Firewall reducer, Handoff, Stop | YES | `outputs/reports/rc3/raw/cross-harness/antigravity/` |

---

## 2. Raw Artifact Provenance

- **Prime Agent**: `outputs/reports/rc3/raw/cross-harness/prime/run.json`, `usage.json`, `verification.txt`
- **Claude Code**: `outputs/reports/rc3/raw/cross-harness/claude-code/run.json`, `usage.json`, `verification.txt`
- **Codex**: `outputs/reports/rc3/raw/cross-harness/codex/run.json`, `usage.json`, `verification.txt`
- **Antigravity**: `outputs/reports/rc3/raw/cross-harness/antigravity/run.json`, `usage.json`, `verification.txt`
