# RC3 Hybrid Cascade Retrieval Live Integration Report

**Document ID**: `outputs/reports/rc3/06-hybrid-retrieval-live.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Run Evidence ID**: `hybrid-retrieval-001`  
**Raw Evidence Directory**: `outputs/reports/rc3/raw/hybrid-retrieval-001/`  
**Status**: `LIVE_RUN_CAPTURED`

---

## 1. Live Execution Summary

- **Component**: Hybrid Multi-Tier Cascade Retriever (`HybridCascadeRetriever`) & `autoinject.py:prepare_injection`.
- **Wiring Finding F2 Closure**: `prepare_injection()` now routes all incoming query evaluation directly through `HybridCascadeRetriever.retrieve()`.
- **Cascade Behavior Evaluated**:
  1. **Tier 0 (Exact ID Lookup)**: Sub-millisecond lookup (<1ms) bypassing dense embeddings entirely.
  2. **Tier 2 (Lexical BM25 FTS5)**: Resolved high-confidence domain match without calling vector APIs.
  3. **Negative Result Cache**: Repeated un-matchable queries hit in-memory negative cache in 0.05ms with 0 downstream calls.
  4. **AutoInject End-to-End**: AutoInject successfully admitted matched memory candidate with full evidence grade and status tracking.

---

## 2. Raw Artifact Provenance

1. `outputs/reports/rc3/raw/hybrid-retrieval-001/run.json` — Tier resolution latencies, negative cache hits, and injection decisions.
2. `outputs/reports/rc3/raw/hybrid-retrieval-001/cascade-trace.json` — Detailed tier traces for exact, lexical, and negative cached queries.
3. `outputs/reports/rc3/raw/hybrid-retrieval-001/usage.json` — Token usage and vector calls avoided.
4. `outputs/reports/rc3/raw/hybrid-retrieval-001/verification.txt` — Automated verification assertions.
