# Task 3 report: bounded recommendations and authorization

## Status
Complete. Implemented only `recommend_maintenance()` and `authorize_maintenance()` in `SkillGardener`; archive/restore execution remains unimplemented for Task 4.

## Files
- `src/second_brain/gardener.py`
  - Added bounded action recommendations with negative-ROI review-only handling.
  - Added fail-closed current hash/version, owner, issue-evidence, approval, non-regression, rollback, survivor, reversible-target, archive, and active-production safety gates.
  - Persists authorization records under `state/maintenance/authorizations/`.
  - Delegated action records identify existing authority and remain `action_executed: false`; no skill, lifecycle, promotion, routing, or content mutation is performed.
- `tests/test_p3_15_skill_gardener.py`
  - Added focused coverage for negative ROI, keep/no-action, missing gates, stale hashes, duplicate survivor requirements, active production safety, delegated non-mutation, and persisted authorization records.

## Tests
`.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py -q`

Result: **28 passed**.

## Commit
`8067cff feat(gardener): gate maintenance authorization`

## Concerns
- `execute_maintenance()` and `restore_retirement()` are intentionally deferred to Task 4.
- Authorization consumes explicit bounded evidence references and persisted candidate owner evidence; execution of delegated authorities remains outside Gardener as required by the action-authority table.

## Review fixes
- Prioritized measured-negative issues across mixed findings so recommendations remain review-only.
- Archive authorization now requires the complete current issue set for the current skill/hash.
- Rejected self-survivors and required replacement capability to bind to a current artifact hash or recomputed normalized identity.
- Corrected merge/supersede delegation metadata to the existing lifecycle/promotion primitive.
- Derived lifecycle state from the resolved directory and require production-safety evidence whenever path or frontmatter indicates active.

Focused test result after fixes: **32 passed**.

Additional implementation commit: `cd08377 fix(gardener): close authorization review gaps`.

## Final authority correction
- `merge` delegates to the existing `skill-lifecycle/content` path.
- `supersede` delegates to the existing `lifecycle/promotion` primitive.
- Added a focused successful merge authorization assertion; no delegated action executes.

Focused test result after correction: **33 passed**.
