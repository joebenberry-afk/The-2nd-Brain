# T7.9 Task Report — Full Governed Self-Improvement Proof

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 697–732.

## Files

- `src/second_brain/promotion.py`
- `tests/test_v2_rollout.py` (new)
- `scripts/run_self_improvement_proof.py` (new)
- `outputs/reports/v2/v2-i/scenario-a-promoted.json` (new)
- `outputs/reports/v2/v2-i/scenario-b-rollback.json` (new)
- `outputs/reports/v2/v2-i/qualification.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.9-report.md` (new)

## Implemented contract

1. **Governed Rollout Lifecycle & Proof Path**:
   Executed the complete proof path:
   `observe -> candidate -> isolate -> evaluate -> independently verify -> canary -> promote -> monitor -> rollback/demote`.

2. **Sequential Stage Progression Enforced**:
   Rollout stages progress strictly adjacent: `OFF -> SHADOW -> ADVISORY -> CANARY -> ACTIVE`.
   Skipping stages (e.g. `OFF -> ACTIVE` or `SHADOW -> ACTIVE`) is refused with a `BrainError`.

3. **Active Promotion Guards**:
   Promotion to `ACTIVE` requires:
   - Causal credit of `DIRECT` or `CONTRIBUTORY` (unverified or `CORRELATED` credit is refused).
   - An independent verifier pass (`verifier_passed=True`).

4. **Negative Evidence Refusal & Demotion**:
   Any candidate exhibiting negative causal effects (`credit_class="UNRELATED_NEGATIVE"`) has promotion refused and is demoted back to `SHADOW` with status `HELD`. Negative evidence is preserved.

5. **Evidence & Audit History Preservation**:
   All stage transitions persist into `v2_rollout_events` and log decisions into `decisions` with `kind="learning"`. Zero historical records are deleted or overwritten during demotion or rollback.

6. **Scenario A (Successful Candidate)**:
   - Feature: `tool_working_set_reduction`.
   - Causal credit: `DIRECT` (delta $-250$ tokens).
   - Verifier passed: True.
   - Result: Promoted sequentially to `ACTIVE`.
   - Artifact: `outputs/reports/v2/v2-i/scenario-a-promoted.json`.

7. **Scenario B (Held / Rolled-Back Candidate)**:
   - Feature: `speculative_prefetch_injection`.
   - Negative effect: $+40\%$ token inflation observed in canary telemetry (`UNRELATED_NEGATIVE`).
   - Result: Promotion to `ACTIVE` refused, demoted to `SHADOW`, status `HELD`.
   - Artifact: `outputs/reports/v2/v2-i/scenario-b-rollback.json`.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_v2_rollout.py -q
4 passed

.venv/Scripts/python.exe -m pytest tests/test_promotion.py -q
27 passed
```

Named tests verified:
- `test_candidate_cannot_skip_rollout_stage`: PASS (attempts to skip stages raise BrainError)
- `test_promotion_requires_credit_and_verifier`: PASS (promotion to ACTIVE requires causal credit and verifier pass)
- `test_negative_candidate_is_held_or_demoted`: PASS (negative candidate refused promotion, demoted to SHADOW)
- `test_rollback_preserves_evidence_history`: PASS (rollout event ledger preserves all 5 lifecycle events and decisions)

## Real evidence

Machine-generated artifacts in `outputs/reports/v2/v2-i/`:
- `scenario-a-promoted.json`: Complete Scenario A proof path.
- `scenario-b-rollback.json`: Complete Scenario B proof path.
- `qualification.json`: Phase `v2-i` qualification ledger record (`status="PROVEN"`).

## Migration and rollback

Uses `v2_rollout_events` and `v2_qualification` tables created in migration 0021.
Rollback is code-revert safe.

## Commit

Commit message: `brain(core): prove governed self improvement loop`.
