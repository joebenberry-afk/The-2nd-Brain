# Task 4 report: archive-first retirement and restore

## Status
Complete. Final review follow-up hardens legacy ROI schema migration, concrete evidence, malformed counterfactual handling (including invalid UTF-8 and boolean totals), per-skill recommendation scoping, canonical Radar/promotion/counterfactual references, demotion governance validation, and stale freshness evidence.

## Files
- `src/second_brain/gardener.py`
  - Persists archive destination, retirement reason, and production-safety evidence in authorized records.
  - Copies the complete skill tree to staging, verifies every archived byte and `SKILL.md` lifecycle hash, persists a bounded retirement record, then atomically moves the source into a quarantine location outside lifecycle directories.
  - Adds idempotent additive migration for legacy ROI ledger columns and fail-closed malformed P3.13 records.
  - Restores verified archives to the previous lifecycle directory without overwriting an existing artifact.
  - Rejects stale/invalid authorizations and active retirements lacking explicit production-safety approval, concrete issue evidence, or demotion promotion-governance evidence.
  - Delegates all non-archive actions without content or lifecycle mutation.
- `tests/test_p3_15_skill_gardener.py`
  - Added focused coverage for operation ordering, complete retirement record fields, copy/hash/record failures, archive overlap, quarantine-root collision, byte-identical restore, restore collision refusal, authorization replay refusal, incomplete-record refusal, source-removal recovery, missing-gate rejection, marker-only evidence rejection, legacy ledger migration, malformed counterfactual evidence, forged demotion governance rejection, active safety gating, and delegated non-mutation.

## Tests
- `.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py -q` — **52 passed**
- `.venv/Scripts/python.exe -m py_compile src/second_brain/gardener.py tests/test_p3_15_skill_gardener.py` — passed

## Commit
`216b6cb feat(gardener): add archive retirement`; `0db28d3 fix(gardener): close retirement replay gaps`; `a33fbe7 fix(gardener): recover failed source removal`; `825db11 fix(gardener): quarantine source atomically`; `bbcdeaa fix(gardener): reject quarantine collisions`; `dc91628 style(gardener): satisfy focused Ruff gate`; `1179ff0 fix(gardener): narrow archive types`; `ccecccc fix(gardener): require retirement gate refs`; `591f2c3 style(gardener): format gate regression`; `480a97f fix(gardener): harden evidence composition`; `f450d95 fix(gardener): close evidence edge cases`

## Concerns
- Focused `pyright` passed with 0 errors, 0 warnings, and 0 informations.
- Focused `ruff check` passed; focused `ruff format --check` reports both files already formatted; focused `pyright` passed with 0 errors, 0 warnings, and 0 informations.
- Project-wide suites remain intentionally skipped per Task 4 scope.
- Source mutation uses an atomic same-volume quarantine move after the archive and retirement record are durable; simulated partial-delete behavior cannot affect the source path, and restore remains byte-identical.
- Consumed authorizations are durably marked after successful source mutation; an in-progress marker is reset when source removal fails, allowing safe retry. In-progress authorizations reject replay if post-removal marker persistence itself fails.
