# RC3 Proof-Carrying Action Cache Live Integration & Evidence Report

**Document ID**: `outputs/reports/rc3/04-action-cache-live.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Run Evidence ID**: `action-cache-001`  
**Raw Evidence Directory**: `outputs/reports/rc3/raw/action-cache-001/`  
**Status**: `LIVE_RUN_CAPTURED`

---

## 1. Live Execution Summary

- **Component**: Proof-Carrying Action Cache (`ActionCacheStore`).
- **Scenarios Evaluated**:
  1. **Valid Hit (Scenario A)**: Exact pure action executed; second identical invocation returns stored artifact in <1ms (0 tool calls, 0 subagents spawned).
  2. **Dependency Change (Scenario B)**: Input file content modified; hash mismatch forces cache miss and re-execution.
  3. **TTL Pruning (Scenario C)**: Ephemeral cached entries automatically expire and are purged by `prune_expired()`.
- **Proof Field Enforcement**: Strictly validates `git_tree_hash`, `input_hashes`, `env_fingerprint`, `ttl_seconds`, and `verification_predicate`.
- **Safety**: Unknown or unverified predicates fail closed (miss cache).

---

## 2. Raw Artifact Provenance

1. `outputs/reports/rc3/raw/action-cache-001/run.json` — Run metrics, hit latency, and validation status.
2. `outputs/reports/rc3/raw/action-cache-001/proof-validation.json` — Evaluated proof invariants.
3. `outputs/reports/rc3/raw/action-cache-001/usage.json` — Token usage and tokens saved via cache hit.
4. `outputs/reports/rc3/raw/action-cache-001/verification.txt` — Automated verification assertions.
