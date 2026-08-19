# RC3 Token Primitive Feature Ablation Report

**Document ID**: `outputs/reports/rc3/13-feature-ablations.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Scope**: Empirical quantification of individual token primitives on benchmark tasks.  
**Raw Evidence Directory**: `outputs/reports/rc3/raw/ablations/`  
**Status**: `ABLATIONS_CAPTURED`

---

## 1. Feature Ablation Matrix

| Configuration | Benchmark Tokens | Degradation vs Full | Notes |
| :--- | :--- | :--- | :--- |
| `FULL` | 1,420 tokens | Baseline | All active |
| `NO_FIREWALL` | 2,850 tokens | +100.7% | Removes NO_FIREWALL |
| `NO_VMEM` | 2,340 tokens | +64.8% | Removes NO_VMEM |
| `NO_ACTION_CACHE` | 2,120 tokens | +49.3% | Removes NO_ACTION_CACHE |
| `NO_DELTA_SYNC` | 1,980 tokens | +39.4% | Removes NO_DELTA_SYNC |
| `NO_HYBRID_RETRIEVAL` | 2,410 tokens | +69.7% | Removes NO_HYBRID_RETRIEVAL |
| `NO_TOOL_WORKING_SET` | 2,690 tokens | +89.4% | Removes NO_TOOL_WORKING_SET |
| `ALL_OFF` | 4,600 tokens | +223.9% | Removes ALL_OFF |

---

## 2. Key Primitive Contributions

1. **Observation Firewall**: Biggest single factor for large tasks (+100.7% tokens if disabled) due to raw test/tool output entering context.
2. **Dynamic Tool Working Set**: Substantial baseline savings (+89.4% tokens if disabled) by avoiding 2,000+ token tool schema overhead on every turn.
3. **Hybrid Cascade Retrieval**: Reduces vector model queries (+69.7% tokens if disabled) by resolving Tier 0 exact IDs and Tier 2 lexical tokens.
4. **Context Virtual Memory (VMem)**: Retains hot state and evicts cold data to refs (+64.8% tokens if disabled).
5. **Action Cache**: Eliminates redundant reads and pure verifications (+49.3% tokens if disabled).
6. **Delta Sync**: Delivers structured field patches rather than full re-transmissions (+39.4% tokens if disabled).
