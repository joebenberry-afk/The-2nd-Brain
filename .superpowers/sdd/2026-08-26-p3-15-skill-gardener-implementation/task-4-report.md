# Task 4 report: archive-first retirement and restore

## Status
Complete. Implemented archive-first `archive_retire` execution and verified restoration while preserving delegated behavior for non-archive actions. Review follow-up closes archive-inside-source overlap, authorization replay, incomplete retirement-record restore gaps, source-removal recovery deadlock, partial-deletion risk, quarantine-root destination collision, focused lint issues, focused type-check issues, and missing authorization gate references.

## Files
- `src/second_brain/gardener.py`
  - Persists archive destination, retirement reason, and production-safety evidence in authorized records.
  - Copies the complete skill tree to staging, verifies every archived byte and `SKILL.md` lifecycle hash, persists a bounded retirement record, then atomically moves the source into a quarantine location outside lifecycle directories.
  - Cleans incomplete archive output on pre-mutation failures and preserves the source artifact.
  - Restores verified archives to the previous lifecycle directory without overwriting an existing artifact.
  - Rejects stale/invalid authorizations and active retirements lacking explicit production-safety approval.
  - Delegates all non-archive actions without content or lifecycle mutation.
- `tests/test_p3_15_skill_gardener.py`
  - Added focused coverage for operation ordering, complete retirement record fields, copy/hash/record failures, archive overlap, quarantine-root collision, byte-identical restore, restore collision refusal, authorization replay refusal, incomplete-record refusal, source-removal recovery, missing-gate rejection, active safety gating, and delegated non-mutation.

## Tests
- `.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py -q` — **47 passed**
- `.venv/Scripts/python.exe -m py_compile src/second_brain/gardener.py tests/test_p3_15_skill_gardener.py` — passed

## Commit
`216b6cb feat(gardener): add archive retirement`; `0db28d3 fix(gardener): close retirement replay gaps`; `a33fbe7 fix(gardener): recover failed source removal`; `825db11 fix(gardener): quarantine source atomically`; `bbcdeaa fix(gardener): reject quarantine collisions`; `dc91628 style(gardener): satisfy focused Ruff gate`; `1179ff0 fix(gardener): narrow archive types`; `ccecccc fix(gardener): require retirement gate refs`; `591f2c3 style(gardener): format gate regression`

## Concerns
- Focused `ruff format` applied to the two changed Python files; focused `ruff check` passed with no findings.
- Focused `pyright` passed with 0 errors, 0 warnings, and 0 informations.
- Project-wide suites remain intentionally skipped per Task 4 scope.
- Source mutation uses an atomic same-volume quarantine move after the archive and retirement record are durable; simulated partial-delete behavior cannot affect the source path, and restore remains byte-identical.
- Consumed authorizations are durably marked after successful source mutation; an in-progress marker is reset when source removal fails, allowing safe retry. In-progress authorizations reject replay if post-removal marker persistence itself fails.
