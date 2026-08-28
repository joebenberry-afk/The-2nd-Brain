# Task 4: Implement archive-first retirement and restore

Read the approved design and implementation plan first. Task 1/2/3 already provide observation, differentiated issues, recommendations, and fail-closed authorization in `src/second_brain/gardener.py`.

Implement only execution for an already-authorized `archive_retire` and restoration; do not redesign observation/classification/authorization or implement P3.16.

Required APIs:
- `SkillGardener.execute_maintenance(authorization: dict) -> dict`: accepts only a current valid authorization record. For `archive_retire`, execute strictly: copy complete source skill directory to archive staging/final destination -> verify archived bytes and SKILL.md content hash -> persist bounded retirement record -> only then disable/remove source lifecycle entry. Any failure before source mutation leaves the source unchanged and removes only incomplete staging. Never permanently delete the only copy. All non-archive actions must return delegated-task metadata without editing content/lifecycle.
- `SkillGardener.restore_retirement(retirement_record_id: str) -> dict`: verify retirement record and archived bytes/hash; restore to previous lifecycle location; refuse to overwrite an existing artifact.

Retirement record must preserve: retirement_record_id, skill identity, skill version/content hash, owner, retirement reason, issue/evidence refs, replacement identity/version when applicable, previous lifecycle state, archive location/reference, rollback/restore reference, timestamp. Active production retirement requires explicit production-safety approval and must never be automatic. Reuse existing paths/lifecycle/promotions/governance; do not add a second registry, editor, promotion engine, or economics system. Do not call promotion.promote automatically.

Add focused tests proving archive copy/hash/record/source ordering, archive failure leaves original unchanged, archive hash mismatch leaves original unchanged, restore returns byte-identical artifact, restore refuses overwrite, active retirement requires safety approval, and delegated non-archive actions do not mutate. Run only focused tests; skip formatters, linters, and project-wide suites. Write `.superpowers/sdd/2026-08-26-p3-15-skill-gardener-implementation/task-4-report.md`, commit relevant source/tests, and return status/commit/tests/concerns.
