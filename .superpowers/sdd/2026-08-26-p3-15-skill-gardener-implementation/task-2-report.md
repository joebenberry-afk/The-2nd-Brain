# Task 2 Report: Differentiated condition classification

## Status
Complete. `SkillGardener.observe_portfolio()` now composes bounded, read-only evidence into independently classified P3.15 conditions while preserving the six required issue types.

## Files
- `src/second_brain/gardener.py`
  - Added deterministic condition classification for `evidence_stale`, `dead_skill`, `capability_overlap`, `false_trigger`, `measured_zero_use`, `measured_negative`, `exact_duplicate`, `scope_too_broad`, `scope_too_narrow`, `model_specific_quirk`, and explicit `superseded` replacement findings.
  - Preserved unknown usage as bounded `usage_unavailable`; estimated/unavailable ROI cannot produce `measured_negative`.
  - Reused lifecycle audit, P3.14 ledger/evaluation/counterfactual evidence, telemetry, and bounded capability/replacement evidence without mutation.
- `tests/test_p3_15_skill_gardener.py`
  - Added focused coverage for every condition code, unknown versus zero usage, estimated-only ROI, exact duplicate versus capability overlap, supersession requirements, and bounded refs.

## Tests
- `.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py -q`
- Result: **19 passed**.
- Project-wide suites, formatters, and linters were intentionally skipped.

## Commit
- `0087ba0 feat(gardener): classify portfolio conditions`
- `dcb6580 fix(gardener): accept explicit failure markers`

## Concerns
- Model/scope/trigger findings require explicit persisted evidence fields; arbitrary or unknown values are ignored conservatively.
- `usage_unavailable` is represented as an `unused`-bucket evidence issue with `reason_codes=["usage_unavailable"]`, never as measured zero use.
- Authorization, maintenance execution, and P3.16/Lean behavior remain out of scope.
