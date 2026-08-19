# RC3 Token Economics Campaign Methodology

**Document ID**: `outputs/reports/rc3/11-token-campaign-method.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Status**: `METHODOLOGY_ESTABLISHED`

---

## 1. Benchmark Harness & Workload Taxonomy

The token economics campaign evaluates real paired runs across 7 distinct workload classes:
- **MICRO**: Single file lookup and precise constant retrieval.
- **STANDARD**: Everyday feature implementation, refactoring, and unit test extension.
- **DEEP**: Multi-subsystem architectural audit and file synchronization.
- **DEBUG**: Test failure triage, lock contention debugging, and memory leak analysis.
- **RESEARCH**: Algorithm comparison and cascade retrieval latency benchmarks.
- **REVIEW**: Code and test diff reviews on pull requests.
- **HANDOFF**: Driver-to-worker delegation and cross-session state transfer.

---

## 2. Experimental Rigor & Artifact Invariants

Each paired task `P-xx` executes identical prompt, environment, and repository state under two conditions:
1. **Brain OFF**: Baseline harness execution without Second Brain token primitives.
2. **Brain ON**: Production runtime execution with Observation Firewall, Context Virtual Memory, Proof-Carrying Action Cache, Delta Sync, Hybrid Retrieval, and Dynamic Tool Working Set.

All raw files are preserved in `outputs/reports/rc3/raw/token/P-xx/{off,on}/` with exact token usage in `usage.json` and manifest indexing.
