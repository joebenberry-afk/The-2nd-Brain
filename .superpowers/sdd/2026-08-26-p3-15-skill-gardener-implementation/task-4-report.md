# Task 4 report: archive-first retirement and restore

## Status
Complete. Implemented archive-first `archive_retire` execution and verified restoration while preserving delegated behavior for non-archive actions.

## Files
- `src/second_brain/gardener.py`
  - Persists archive destination, retirement reason, and production-safety evidence in authorized records.
  - Copies the complete skill tree to staging, verifies every archived byte and `SKILL.md` lifecycle hash, persists a bounded retirement record, then removes the source lifecycle entry.
  - Cleans incomplete archive output on pre-mutation failures and preserves the source artifact.
  - Restores verified archives to the previous lifecycle directory without overwriting an existing artifact.
  - Rejects stale/invalid authorizations and active retirements lacking explicit production-safety approval.
  - Delegates all non-archive actions without content or lifecycle mutation.
- `tests/test_p3_15_skill_gardener.py`
  - Added focused coverage for operation ordering, complete retirement record fields, copy/hash/record failures, byte-identical restore, restore collision refusal, active safety gating, and delegated non-mutation.

## Tests
- `.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py -q` — **40 passed**
- `.venv/Scripts/python.exe -m py_compile src/second_brain/gardener.py tests/test_p3_15_skill_gardener.py` — passed

## Commit
`216b6cb feat(gardener): add archive retirement`

## Concerns
- No project-wide suites, formatters, or linters were run per Task 4 scope.
- Source mutation uses removal only after the archive and retirement record are durable; the archive remains the reversible copy.
