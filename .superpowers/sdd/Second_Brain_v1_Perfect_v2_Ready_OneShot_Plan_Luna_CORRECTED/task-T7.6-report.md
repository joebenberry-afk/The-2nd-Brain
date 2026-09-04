# T7.6 Task Report — Deterministic Engrams and Model Culture

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 609–642.

## Files

- `src/second_brain/engram.py`
- `src/second_brain/crossmodel.py`
- `tests/test_crossmodel.py`
- `tests/test_engrams_v2.py` (new)
- `scripts/run_engram_experiment.py` (new)
- `outputs/reports/v2/engrams/engram-experiment.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.6-report.md` (new)

## Implemented contract

1. **Engram Schema**:
   Defined deterministic workflow procedures with steps containing:
   `{tool, args_template, precondition:{cmd, expect_exit}, postcondition:{cmd, expect_exit}}`,
   versioned under `engrams/deterministic/{engram_id}_v{version}.json` with `valid_for = {harness, tool_versions, model}`.

2. **Detection from Ledger Tool Sequences**:
   `engram.detect_workflow_engrams` scans session events for `kind=tool_call`, extracting contiguous subsequences of length 3–5 with minimum support 2.

3. **Deterministic Execution & Zero Model Calls**:
   `engram.run_deterministic` executes procedure steps through `action_cache` (`ActionType.GENERIC_PURE`, `DependencyClass.PURE_CONSTANT`).
   Evaluates preconditions before each step and postconditions after each step. Execution makes zero model calls (`model_calls: 0`), caching identical runs.

4. **Model/Harness Culture & Distillation**:
   - `crossmodel.propose_transfer` preserves model/harness specificity, keeping transfers as candidates in `SHADOW` without granting global scope.
   - `crossmodel.evaluate_teacher_student` enforces teacher-to-student distillation requiring the cheaper student to satisfy 100% of the same postconditions and acceptance criteria before verification.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_engrams_v2.py -q
5 passed

.venv/Scripts/python.exe -m pytest tests/test_engram.py tests/test_crossmodel.py -q
39 passed
```

Named tests verified:
- `test_engram_detected_only_with_min_support`: PASS (support=1 rejected; support>=2 detected with length 3-5)
- `test_engram_run_uses_zero_model_calls`: PASS (deterministic execution with 0 model calls, second run hits action cache)
- `test_engram_postcondition_failure_marks_run_failed`: PASS (failed postcondition halts run, reports failed step)
- `test_crossmodel_transfer_stays_candidate_until_verified`: PASS (transfer remains candidate in SHADOW without global scope)
- `test_teacher_student_requires_same_acceptance`: PASS (student missing postcondition is HELD; student passing all postconditions is VERIFIED)

## Cheapest real experiment

Script `scripts/run_engram_experiment.py` distilled a 3-tool verification workflow (`read_file -> run_linter -> run_tests`) from session events with support=2:

- **Workflow length**: 3 steps
- **Workflow support**: 2 sessions
- **Model calls on execution**: 0
- **Action cache hit verified**: True
- **Teacher-student distillation**: VERIFIED (satisfied 100% same postconditions)
- Artifact saved: `outputs/reports/v2/engrams/engram-experiment.json`.

## Migration and rollback

Additive procedures and candidate transfer records; no database migration required.
Rollback is code-revert safe.

## Commit

Commit message: `brain(skill): deterministic engrams and model culture`.
