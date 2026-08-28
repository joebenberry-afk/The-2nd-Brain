# Task 3: Add bounded recommendations and authorization

Read the approved spec at `docs/superpowers/specs/2026-08-26-p3-15-skill-gardener-design.md` and Task 3 of the implementation plan. Task 1/2 already provide bounded observe_portfolio() and differentiated issue records in `src/second_brain/gardener.py`.

Implement only recommendation and authorization; do not implement archive/restore execution yet.

Required APIs:
- `recommend_maintenance(observation: dict) -> dict`: bounded result with `evidence_detected`, `action_recommended`, `action_authorized=False`, `action_executed=False`, issue IDs and evidence refs. Use approved actions keep/repair/merge/narrow/demote/hide/supersede/archive_retire/no_action. Negative ROI defaults to repair/no_action, never archive_retire.
- `authorize_maintenance(recommendation: dict, *, actor: str, approval_ref: str, non_regression_ref: str, rollback_ref: str, replacement: dict | None = None) -> dict`: fail closed on missing/invalid actor, current skill hash, issue evidence, action-specific evidence, approval, non-regression, rollback, or verified replacement. Persist a bounded authorization record under a state maintenance/authorization area.

Action authority must follow the approved table exactly: keep/no_action record only; repair/narrow emit an authorized task for existing skill-development/evaluation path; merge/supersede require verified survivor and delegate resulting content/lifecycle work; demote delegates to existing promotion.demote; hide delegates to existing visibility primitive without a new registry; archive_retire is the only Gardener-owned mutation (Task 4).

P3.12 owner/version/rollback evidence must be consumed where applicable. Negative ROI is review-only. No audit/recommendation mutates lifecycle. No promotion engine/editor/registry/economics subsystem. Preserve P3.16/Lean.

Add focused tests for negative ROI review-only, keep/no_action, missing gate evidence refusals, stale skill hash refusal, duplicate/supersede survivor requirement, active-skill production safety requirement, and delegated action records being non-mutating. Run only focused tests, skip formatters/linters/project-wide suites. Write `.superpowers/sdd/2026-08-26-p3-15-skill-gardener-implementation/task-3-report.md`, commit relevant files, and return status/commit/tests/concerns.
