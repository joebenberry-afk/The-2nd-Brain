# RC3 Dynamic Tool Working Set Live Integration Report

**Document ID**: `outputs/reports/rc3/07-tool-working-set-live.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Run Evidence ID**: `tool-working-set-001`  
**Raw Evidence Directory**: `outputs/reports/rc3/raw/tool-working-set-001/`  
**Status**: `LIVE_RUN_CAPTURED`

---

## 1. Live Execution Summary

- **Component**: Dynamic Tool Working Set Manager (`ToolWorkingSetManager`).
- **Core Budget Enforcement**: Active base schemas kept strictly under **500 tokens** (153 tokens measured), preventing 1,500+ tokens of bloated definitions on every turn.
- **Dynamic JIT Activation**: Mentioning database domain operations dynamically activated `database_migrate_query` into active tool schemas.
- **Idle Pruning**: After 3 inactive turns without database usage, domain tool was automatically demoted back to lazy registry.

---

## 2. Raw Artifact Provenance

1. `outputs/reports/rc3/raw/tool-working-set-001/run.json` — Initial counts, token sizes, activation, and pruning traces.
2. `outputs/reports/rc3/raw/tool-working-set-001/initial-schemas.json` — Core resident tool schemas payload.
3. `outputs/reports/rc3/raw/tool-working-set-001/promoted-schemas.json` — Working set with promoted domain tool.
4. `outputs/reports/rc3/raw/tool-working-set-001/pruned-schemas.json` — Working set after idle pruning.
5. `outputs/reports/rc3/raw/tool-working-set-001/usage.json` — Active schema tokens and per-turn savings.
6. `outputs/reports/rc3/raw/tool-working-set-001/verification.txt` — Automated verification assertions.
