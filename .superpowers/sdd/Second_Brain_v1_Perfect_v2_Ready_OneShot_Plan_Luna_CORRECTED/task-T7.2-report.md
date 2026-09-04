# T7.2 Task Report — Governed Reconsolidation and Strategic Forgetting

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 487–514.

## Files

- `src/second_brain/reconsolidation.py`
- `src/second_brain/semantic.py`
- `src/second_brain/db.py`
- `tests/test_meta_memory.py` (new)
- `scripts/run_reconsolidation_experiment.py` (new)
- `outputs/reports/v2/reconsolidation/reconsolidation-experiment.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.2-report.md` (new)

## Implemented contract

1. **Allowed Transitions & Vocabulary**:
   Defined `RECONSOLIDATION_ACTIONS`:
   `("strengthen", "narrow", "update", "split", "merge", "supersede", "demote", "archive")`.

2. **ACT-R & Contradiction-Aware Reconsolidation**:
   - Folded T5.1 ACT-R base activation $B = \ln(\sum t_j^{-d})$ and need probability $P_{\text{need}} = \text{sigmoid}((B - \tau)/s)$ into `evaluate_memory` and `decay_pass`.
   - Contradiction counts and activations (`outcome == "contradicted"`) strictly prevent silent strengthening.
   - Any memory with `contradiction_count > 0` is restricted to `narrow` or `demote`, preventing escalation to `HOT` heat or `strengthen` action.

3. **Hot-Set Demotion Distinct from Evidence Deletion**:
   - `demote_memory` transitions heat (HOT -> WARM -> COLD) and updates metadata.
   - The memory row in SQLite, canonical markdown file on disk (`body_path`), all entries in `memory_sources`, and all historical records in `memory_versions` remain 100% intact and non-empty.

4. **Reversible Plans & SHADOW Candidate Gating**:
   - Automatic merge and supersede proposals use `propose_plan` which starts in `rollout_stage = "SHADOW"` and `status = "planned"`.
   - Captures `before_state` (exact version, title, body_path, status, grade, heat, body) and generates a deterministic `plan_id`.
   - No mutation occurs while in SHADOW.
   - `apply_plan` executes the plan (e.g. calling `semantic.supersede`), records CANARY/SHADOW stage in decisions, and marks status `"applied"`.
   - `revert_plan` and `revert_supersede` safely reverse mutations back to the exact prior version, preserving both old and new version snapshots and files.

5. **Decision Provenance**:
   - Every automatic evaluation, decay change, plan proposal, plan execution, and plan reversal is recorded in `decisions` table with `kind="reconsolidation"`.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_meta_memory.py tests/test_reconsolidation.py tests/test_activation.py -q
23 passed

.venv/Scripts/python.exe -m pytest tests/test_semantic.py tests/test_earned_memory.py -q
26 passed
```

Named tests verified:
- `test_reconsolidation_preserves_evidence`: PASS (sources, files, and versions completely intact through evaluation, demotion, supersede, and reversal)
- `test_contradiction_prevents_silent_strengthening`: PASS (contradicted memories reject strengthening and stay COLD)
- `test_supersede_is_reversible`: PASS (SHADOW plan emits without mutation, applies to v2, reverts to v1 with both versions preserved)
- `test_hotset_demotion_does_not_delete_memory`: PASS (demoting out of hot set changes heat but preserves disk file, DB row, and body content)

## Cheapest real experiment

Script `scripts/run_reconsolidation_experiment.py` evaluated 20 real/representative memories across repeated retrieval, stale evidence, contradictions, labile scope, and superseded archives:

- **Total memories evaluated**: 20
- **Concordance with manual expert classification**: 20/20 (100.0%)
- **Contradiction strengthening block rate**: 1.0 (100.0%)
- **Evidence destruction count**: 0 (zero sources, files, or versions deleted)
- **Reversibility success rate**: 1.0 (100.0%)
- **Reconsolidation decisions logged**: 24

Artifact saved: `outputs/reports/v2/reconsolidation/reconsolidation-experiment.json`.

## Migration and rollback

No new table added; reuses existing `memories`, `memory_sources`, `memory_versions`, `memory_activations`, and `decisions` tables in full adherence to the T7.0 plan reconciliation contract.
Rollback is code-revert safe: all changes preserve backward database compatibility.

## Commit

Commit message: `brain(memory): governed reconsolidation and strategic forgetting`.
