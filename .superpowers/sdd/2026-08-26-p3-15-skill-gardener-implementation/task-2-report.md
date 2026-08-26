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

## Reviewer fixes
- Unknown usage is now skill-level bounded evidence (`usage_state=unknown`, `usage_evidence_refs`), not an `unused` issue.
- Capability overlap requires a dict with a distinct target and `material=true`; supersession requires an existing surviving replacement with matching current capability identity/version.
- Negative ROI ledger fallback is content-hash bound with bounded ledger refs; stale identities suppress current trigger/scope/model/replacement findings; audit bare missing-section titles are recognized.
- Telemetry usage is collected once per observation, and duplicate tests assert the peer has no capability-overlap issue.

## Concerns
- Model/scope/trigger findings require explicit persisted evidence fields; arbitrary or unknown values are ignored conservatively.
- Authorization, maintenance execution, and P3.16/Lean behavior remain out of scope.

## Fix-round commit
- `da942d7 fix(gardener): harden evidence classification`

## Re-review fix
- `_replacement_evidence()` now extracts `normalized_hash`, `capability_hash`, or `content_hash` from nested `capability_evidence` and only returns verifiable capability identity.
- Added focused regression coverage for nested normalized replacement capability proof.
- Focused tests: **20 passed**.

## Re-review fix commit
- `1364998 fix(gardener): verify nested capability proofs`
