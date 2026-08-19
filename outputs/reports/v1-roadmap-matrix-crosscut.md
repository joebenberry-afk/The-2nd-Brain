# Second Brain v1.0 — Cross-Cutting Release Requirements Matrix

**P0-MATRIX-CROSSCUT** • Evidence-based • 2026-08-18

Assessment of 14 cross-cutting requirements (plan §31, lines 2282-2295) against current state.

## Token Efficiency Contract measured and satisfied

**Status**: PARTIAL

**Evidence**: outputs/reports/v1-token-baseline.md exists; token capture capability documented (input_tokens, output_tokens, cache_read/write, tool result bytes recorded in real telemetry); baseline metrics incomplete (context peak, worker turns, repeated reads, duplicate injection, compaction cost, task success rollup still MISSING)

**Missing**: Baseline measurement not yet complete; Token Governor implementation/ablation missing

---

## Token Governor/ablation evidence complete

**Status**: MISSING

**Evidence**: NO EVIDENCE FOUND (grep for ablation reports in outputs/reports/ returns zero; no governor test or ablation report exists)

**Missing**: Ablation study must compare Brain ON vs. OFF token cost on same task suite; governor config wiring must be tested

---

## Local-first/no-server requirement satisfied

**Status**: IMPLEMENTED-UNPROVEN

**Evidence**: Semantic memory uses SQLite FTS5 (local, no server); search_memories() in semantic.py is entirely local; no external HTTP/embedding API calls found in core modules; config shows no server dependencies

**Missing**: Full system proof required (audit all modules for hidden remote calls); GPU-free constraint not explicitly tested

---

## Prime Agent 0.7.3 integration proven

**Status**: MISSING

**Evidence**: NO EXPLICIT 0.7.3 QUALIFICATION VERDICT FOUND (grep 0.7.3 in outputs/reports/ returns only telemetry filenames, not a verdict statement); no Prime version qualification report

**Missing**: Explicit Prime 0.7.3 compatibility and feature parity statement required; version lock and regression verification

---

## Codex integration proven

**Status**: IMPLEMENTED-UNPROVEN

**Evidence**: brainstem/codex-hooks/hooks.toml defines 5 events (SessionStart, UserPromptSubmit, SubagentStart, Stop, SessionEnd); tests/test_autoinject_codex.py has 5 tests; run.ps1 spawns brainctl autoinject codex-shadow; SHADOW-ONLY mode (no model-visible injection by design)

**Missing**: Per grounding rule: Codex is SHADOW-ONLY and cannot be PROVEN. Real usage would require enabling Codex locally and capturing telemetry; currently documented-only.

---

## Claude Code integration proven

**Status**: PROVEN

**Evidence**: brainstem/adapters/claude-code/hooks.json defines 3 events (SessionStart, PreCompact, Stop); tests/test_claude_code_adapter.py has 26 tests covering all events and fail-open behavior; real telemetry: 37 claude_code_stop_turn records in C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/*.jsonl

**Missing**: None (real usage artifact exists)

---

## Antigravity/agy integration proven

**Status**: PARTIAL

**Evidence**: brainstem/adapters/antigravity/hooks.json defines 3 events (PreInvocation, PostInvocation, PostToolUse); tests/test_antigravity_adapter.py has 17 tests; agy CLI installed (1.1.13, C:/Users/assas/AppData/Local/agy/bin/agy.exe); adapter installed at ~/.gemini/config/plugins/second-brain-adapter (frozen-environment.json confirms)

**Missing**: Adapter installed but NOT ENABLED in agy config; real Antigravity campaign blocked per frozen-environment.json manual_next_actions. No real telemetry from agy runs found.

---

## Cross-harness Brain Handoff proven

**Status**: IMPLEMENTED-UNPROVEN

**Evidence**: backup.py (create_backup, restore_backup) + working_set.py (session state serialization); tests/test_backup.py has 19 tests covering backup/restore cycle; CLI: cmd_backup, cmd_restore wired; ledger checkpoint events recorded

**Missing**: Cross-session handoff format (deterministic goal/evidence/decisions tuple) not yet specified; resume capability TBD

---

## Dogfooding proven

**Status**: IMPLEMENTED-UNPROVEN

**Evidence**: outputs/reports/p2-dogfood-raw-evidence.md exists (P2 phase dogfood evidence); outputs/reports/p3-full-dogfood.md exists (P3 phase dogfood runs); P3 campaign (30 test arms across e01-e06 valid + e07-e16 synthetic) represents controlled evaluation, not full production dogfood

**Missing**: Full production dogfood (extended real-world use with real agents on real tasks) not yet complete; only controlled/pilot runs recorded

---

## Backup/restore proven

**Status**: PROVEN

**Evidence**: backup.py (create_backup:1, restore_backup:50) implements full cycle; tests/test_backup.py (19 tests) covers create, list, restore, corruption detection, byte-identity verification; CLI: cmd_backup, cmd_restore tested

**Missing**: None (create/restore/verify cycle proven by tests + CLI)

---

## Security/integrity qualification proven

**Status**: MISSING

**Evidence**: NO EVIDENCE FOUND (no dedicated security audit, integrity test suite, or qualification report in outputs/reports/)

**Missing**: Security audit required: input sanitization, SQL injection prevention (FTS5), file access controls, credential handling (no secrets leak), privilege isolation, threat model & mitigations

---

## Clean install/recovery/concurrency/failure injection proven

**Status**: PARTIAL

**Evidence**: scripts/bootstrap.ps1 exists (clean install); scripts/doctor.ps1 exists (health check); tests found: test_ledger.py (recovery/durability), test_migrations_property.py (schema recovery), test_scout.py (concurrent access patterns). No specific concurrency stress tests or failure-injection suite found.

**Missing**: Dedicated concurrency test suite (parallel session creation, simultaneous ledger writes, backup during active session) missing; failure-injection tests (disk full, corruption recovery, process crash during write) missing

---

## Burn-in complete

**Status**: MISSING

**Evidence**: NO EVIDENCE FOUND (grep for burn-in reports in outputs/reports/ returns zero; no extended stress test or burn-in campaign report)

**Missing**: Burn-in campaign required: 1000+ tasks, 10k+ turns, 100+ sessions, memory growth monitoring, resource leak detection, crash recovery validation

---

## Full regression green

**Status**: MISSING

**Evidence**: NO EVIDENCE FOUND (no regression test report in outputs/reports/; test suite exists but no "full regression passed" verdict recorded)

**Missing**: Full pytest run must pass (51 test files discoverable); regression report capturing baseline test results required before v1.0 freeze

---


## Summary

| Requirement | Status |
|---|---|
| Token Efficiency Contract measured and satisfied | PARTIAL |
| Token Governor/ablation evidence complete | MISSING |
| Local-first/no-server requirement satisfied | IMPLEMENTED-UNPROVEN |
| Prime Agent 0.7.3 integration proven | MISSING |
| Codex integration proven | IMPLEMENTED-UNPROVEN |
| Claude Code integration proven | PROVEN |
| Antigravity/agy integration proven | PARTIAL |
| Cross-harness Brain Handoff proven | IMPLEMENTED-UNPROVEN |
| Dogfooding proven | IMPLEMENTED-UNPROVEN |
| Backup/restore proven | PROVEN |
| Security/integrity qualification proven | MISSING |
| Clean install/recovery/concurrency/failure injection proven | PARTIAL |
| Burn-in complete | MISSING |
| Full regression green | MISSING |

### Status Breakdown

- PROVEN: 2
- IMPLEMENTED-UNPROVEN: 4
- PARTIAL: 3
- MISSING: 5

### Blocker Summary

**BLOCKING v1.0 release** (MISSING status):
- Token Governor/ablation evidence
- Prime 0.7.3 qualification verdict
- Security/integrity qualification
- Burn-in test campaign
- Full regression green (test report)

**READY with caveats** (PROVEN or IMPLEMENTED-UNPROVEN):
- Claude Code integration (PROVEN by real telemetry)
- Backup/restore (PROVEN by tests + CLI)
- Local-first architecture (IMPLEMENTED-UNPROVEN; audit needed)
- Dogfooding (IMPLEMENTED-UNPROVEN; pilot runs recorded, production dogfood pending)
