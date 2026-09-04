# T7.5 Task Report — Prediction-Error and Causal Learning Loop

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 584–608.

## Files

- `src/second_brain/credit.py`
- `src/second_brain/decisions.py`
- `src/second_brain/migrations/0020_causal_learning.sql` (new)
- `tests/test_causal_learning.py` (new)
- `tests/test_plasticity.py`
- `scripts/run_causal_learning_experiment.py` (new)
- `outputs/reports/v2/learning/causal-loop-experiment.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.5-report.md` (new)

## Implemented contract

1. **Causal Data Flow**:
   Implemented the complete closed loop:
   `decision -> expected_outcome -> observed_outcome -> prediction_error -> credit_class -> candidate policy update`.

2. **Prior Measurable Expectation Enforced**:
   `credit.record_intervention` requires a non-empty, measurable `expected_outcome` before an intervention can execute. Empty expectations or vague unmeasurable strings are rejected (`BrainError`).
   Persists into `v2_interventions` with `status='PENDING'`.

3. **Ground-Truth Observation Boundary**:
   `credit.record_observation` strictly requires evidence from `telemetry`, `test_runner`, `acceptance_check`, or `benchmark`. Model self-assertion or self-report is explicitly rejected (`BrainError`).

4. **Prediction Error & Bounded Surprise**:
   Computes structured prediction error comparing expected and observed metrics, deriving a normalized `surprise_score` in $[0.0, 1.0]$. Only material surprise triggers candidate policy actions.

5. **Design-Derived Credit Assignment**:
   Integrates T5.4 `classify_credit`:
   - `DIRECT`: verified holdout or paired positive effect without interaction.
   - `CONTRIBUTORY`: paired design with significant interaction.
   - `CORRELATED`: non-experimental correlation.
   - `UNRELATED_NEGATIVE`: negative effect or verified regression.

6. **Governed Candidate Actions in SHADOW**:
   - Verified positive interventions produce `candidate_action={"action": "propose_candidate_update", "rollout_stage": "SHADOW"}`.
   - Verified negative interventions produce `candidate_action={"action": "demote_candidate", "rollout_stage": "SHADOW"}`.
   - Zero direct self-mutation: all updates remain candidates in SHADOW stage.

7. **Retained Database Tables & Decisions Ledger**:
   - Created `v2_interventions` and `v2_observations` in migration `0020_causal_learning.sql`.
   - Added `"learning"` to `_DECISION_KINDS` in `decisions.py`. Every intervention and observation records its immutable provenance in `decisions`.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_causal_learning.py -q
4 passed

.venv/Scripts/python.exe -m pytest tests/test_credit.py tests/test_plasticity.py -q
44 passed
```

Named tests verified:
- `test_prediction_error_requires_prior_expectation`: PASS (empty or non-measurable expectation rejected before execution)
- `test_model_self_report_is_not_observation`: PASS (model self-assertion rejected; requires telemetry or test proof)
- `test_surprise_creates_candidate_not_active_policy`: PASS (material surprise creates candidate in SHADOW, not active mutation)
- `test_negative_effect_can_demote_candidate`: PASS (regressed / negative effect produces `demote_candidate` action)

## Cheapest real experiment

Script `scripts/run_causal_learning_experiment.py` replayed the full causal update path using paired and holdout evidence from T0.5 and T5.2:

- Positive intervention: `tool_working_set_filter` with expected delta $-200$ tokens, observed $-250$ tokens. Attributed `DIRECT` credit, generated `propose_candidate_update` action.
- Negative intervention: `speculative_memory_injection` with expected delta $-150$ tokens, observed $+400$ tokens (regression). Attributed `UNRELATED_NEGATIVE` credit, generated `demote_candidate` action.
- Proved distinct evidence-grounded outcomes with 100% SHADOW rollout compliance.
- Artifact saved: `outputs/reports/v2/learning/causal-loop-experiment.json`.

## Migration and rollback

Migration `0020_causal_learning.sql` creates `v2_interventions` and `v2_observations` using `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
Migration idempotency verified (`db.migrate()` runs cleanly and returns `[]` on repeat).
Rollback is code-revert safe.

## Commit

Commit message: `brain(learning): prediction error causal loop`.
