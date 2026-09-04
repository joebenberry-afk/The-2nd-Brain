# Second Brain v2 Roadmap Status

Generated at: 2026-09-04T08:54:34.725012+00:00

| Task | Description | Status | Evidence | Tests | Economics | Source Commit |
|---|---|---|---|---|---|---|
| `T0.1` | Record v2-0 gate baseline | **PROVEN** | `outputs/reports/v2/v2-0/qualification.json` | 12 passed | `BASELINE` | `05bea1e` |
| `T0.2` | Aggregate telemetry kinds and Hermes usage | **PROVEN** | `.superpowers/sdd/.../task-T0.2-report.md` | 18 passed | `N/A` | `05bea1e` |
| `T0.3` | Capture Claude Code transcript usage | **PROVEN** | `.superpowers/sdd/.../task-T0.3-report.md` | 15 passed | `N/A` | `05bea1e` |
| `T0.4` | Add decision log and propensities | **PROVEN** | `src/second_brain/decisions.py` | 14 passed | `N/A` | `05bea1e` |
| `T0.5` | Implement paired economics estimator | **PROVEN** | `scripts/run_paired_economics.py` | 16 passed | `POSITIVE` | `05bea1e` |
| `T0.6` | Calibrate shared token estimator | **PROVEN** | `src/second_brain/contracts.py` | 12 passed | `N/A` | `05bea1e` |
| `T1.1` | Add IDF query builder | **PROVEN** | `src/second_brain/semantic.py` | 14 passed | `N/A` | `05bea1e` |
| `T1.2` | Add retrieval abstention gate | **PROVEN** | `src/second_brain/hybrid_retrieval.py` | 18 passed | `NON_NEGATIVE` | `05bea1e` |
| `T1.3` | Wire corpus admission feedback | **PROVEN** | `src/second_brain/semantic.py` | 12 passed | `N/A` | `05bea1e` |
| `T1.4` | Add evidence freshness resolver | **PROVEN** | `src/second_brain/freshness.py` | 15 passed | `N/A` | `05bea1e` |
| `T1.5` | Persist read-ledger delta sync | **PROVEN** | `src/second_brain/delta_sync.py` | 16 passed | `POSITIVE` | `05bea1e` |
| `T1.6` | Add low-friction memory I/O | **PROVEN** | `src/second_brain/semantic.py` | 14 passed | `N/A` | `05bea1e` |
| `T1.7` | Bind origin authority at write | **PROVEN** | `src/second_brain/semantic.py` | 15 passed | `N/A` | `05bea1e` |
| `T2.0` | Add coverage-before-reclaim | **PROVEN** | `src/second_brain/vmem.py` | 18 passed | `NON_NEGATIVE` | `05bea1e` |
| `T2.1` | Add cache-model eviction | **PROVEN** | `src/second_brain/vmem.py` | 14 passed | `POSITIVE` | `05bea1e` |
| `T2.2` | Add fault-in hysteresis | **PROVEN** | `src/second_brain/vmem.py` | 12 passed | `NON_NEGATIVE` | `05bea1e` |
| `T2.3` | Batch cache-breakpoint paging | **PROVEN** | `src/second_brain/vmem.py` | 16 passed | `POSITIVE` | `05bea1e` |
| `T2.4` | Stabilize prefix-tail injection | **PROVEN** | `src/second_brain/autoinject.py` | 15 passed | `POSITIVE` | `05bea1e` |
| `T2.5` | Attribute cache epochs | **PROVEN** | `src/second_brain/db.py` | 14 passed | `NON_NEGATIVE` | `05bea1e` |
| `T2.6` | Add provider capability table | **PROVEN** | `src/second_brain/capabilities.py` | 16 passed | `N/A` | `05bea1e` |
| `T3.1` | Enforce hard-soft budget caps | **PROVEN** | `src/second_brain/governor.py` | 18 passed | `NON_NEGATIVE` | `05bea1e` |
| `T3.2` | Calibrate risk weights | **PROVEN** | `scripts/calibrate_risk.py` | 14 passed | `N/A` | `05bea1e` |
| `T3.3` | Route by expected cost | **PROVEN** | `src/second_brain/model_routing.py` | 15 passed | `POSITIVE` | `05bea1e` |
| `T3.4` | Add Lean opportunity controller | **PROVEN** | `src/second_brain/lean_runtime.py` | 16 passed | `POSITIVE` | `05bea1e` |
| `T4.1` | Add worker lifecycle leases | **PROVEN** | `src/second_brain/worker_protocol.py` | 24 passed | `NON_NEGATIVE` | `05bea1e` |
| `T4.2` | Validate results and session IDs | **PROVEN** | `src/second_brain/contracts.py` | 22 passed | `N/A` | `05bea1e` |
| `T4.3` | Add capability profiles and tiers | **PROVEN** | `src/second_brain/capabilities.py` | 18 passed | `N/A` | `05bea1e` |
| `T4.4` | Move harness parsing into adapters | **PROVEN** | `src/second_brain/adapters/` | 26 passed | `N/A` | `05bea1e` |
| `T5.1` | Implement ACT-R activation | **PROVEN** | `src/second_brain/reconsolidation.py` | 17 passed | `POSITIVE` | `05bea1e` |
| `T5.2` | Add retrieval injection holdout | **PROVEN** | `src/second_brain/autoinject.py` | 16 passed | `NON_NEGATIVE` | `05bea1e` |
| `T5.3` | Implement off-policy evaluation | **PROVEN** | `src/second_brain/economics.py` | 15 passed | `N/A` | `05bea1e` |
| `T5.4` | Derive design-based credit classes | **PROVEN** | `src/second_brain/credit.py` | 28 passed | `N/A` | `05bea1e` |
| `T6.1` | Delete dead code and state | **PROVEN** | `src/second_brain/` | 32 passed | `N/A` | `05bea1e` |
| `T6.2` | Fix listed integration defects | **PROVEN** | `src/second_brain/` | 24 passed | `N/A` | `05bea1e` |
| `T6.3` | Add artifact GC and hash chain | **PROVEN** | `src/second_brain/artifacts.py` | 18 passed | `N/A` | `05bea1e` |
| `T6.4` | Reconcile roadmap vocabulary | **PROVEN** | `docs/` | Docs verified | `N/A` | `05bea1e` |
| `T6.5` | Add cache dependency classes | **PROVEN** | `tests/test_action_cache_deps.py` | 31 passed | `NON_NEGATIVE` | `f51139e` |
| `T7.0` | Fold old v2 plan into owners | **PROVEN** | `docs/superpowers/plans/...` | Docs verified | `N/A` | `83f8d22` |
| `T7.1` | Implement earned-memory friction gate | **PROVEN** | `outputs/reports/v2/earned-memory/replay-experiment.json` | 32 passed | `NON_NEGATIVE` | `4767259` |
| `T7.2` | Govern reconsolidation and forgetting | **PROVEN** | `outputs/reports/v2/reconsolidation/reconsolidation-experiment.json` | 23 passed | `NON_NEGATIVE` | `0376172` |
| `T7.3` | Add explainable retrieval intelligence | **PROVEN** | `outputs/reports/v2/retrieval/retrieval-economics.json` | 17 passed | `INSUFFICIENT` | `b50e873` |
| `T7.4` | Add Brainstem coordinator | **PROVEN** | `outputs/reports/v2/brainstem/brainstem-experiment.json` | 4 passed | `NON_NEGATIVE` | `ef624a3` |
| `T7.5` | Add prediction-error causal loop | **PROVEN** | `outputs/reports/v2/learning/causal-loop-experiment.json` | 48 passed | `POSITIVE` | `1826757` |
| `T7.6` | Add deterministic engrams and culture | **PROVEN** | `outputs/reports/v2/engrams/engram-experiment.json` | 44 passed | `NON_NEGATIVE` | `5ffaba1` |
| `T7.7` | Complete universal control plane | **PROVEN** | `outputs/reports/v2/control-plane/capability-matrix.json` | 54 passed | `N/A` | `7f44665` |
| `T7.8` | Add decision-linked frontier | **PROVEN** | `outputs/reports/v2/frontier/frontier-experiment.json` | 37 passed | `NON_NEGATIVE` | `a3efb64` |
| `T7.9` | Prove governed self-improvement | **PROVEN** | `outputs/reports/v2/v2-i/qualification.json` | 31 passed | `POSITIVE` | `a3a7961` |
