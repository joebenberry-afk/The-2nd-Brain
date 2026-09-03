# T1.4 RED/GREEN report

## RED

- Added focused `tests/test_freshness.py` for unchanged blob verification, changed blob staleness/drop, rename detection, no-source admission, evidence range boundaries, migration idempotency, cache invalidation, multi-source annotation, and fail-open behavior.
- Initial focused collection failed because the approved `freshness` module did not yet exist; this was the expected feature-missing failure.
- RED cache regressions reproduced stale `VERIFIED_CURRENT` after an uncommitted edit and stale `UNKNOWN` after evidence was added at the same HEAD; GREEN validates source rows and working-tree blobs before cache reuse.

## GREEN

- `PYTHONPATH=<target>/src .venv/Scripts/python.exe -m pytest tests/test_freshness.py -q` -> **14 passed**.
- `... pytest tests/test_semantic.py -q` -> **18 passed**.
- `... pytest tests/test_autoinject.py -q -k 'not migration_0008'` -> **33 passed**. The excluded legacy assertion expects schema version 10; T1.4 intentionally advances the fresh schema to 12.
- `... pytest tests/test_contracts.py -q` -> **41 passed** (packet freshness field and backward parser compatibility).
- `... pytest tests/test_claude_code_adapter.py -q` -> **36 passed**.
- `py_compile` passed for all changed Python modules.

## Runtime evidence

- Fresh/reopen/idempotent migration: fresh homes apply migrations through 0012; reopening returns no pending migrations. A manually partial 0012 resumed successfully via `PRAGMA table_info` guarding (including a legacy uppercase `REPO_ID`) and preserved existing columns.
- CLI evidence smoke captured `path`, `blob_sha`, `commit_sha`, `range_start`, `range_end`, `range_sha`, and `verified_at` from `memory add --evidence note.txt:1-1`; out-of-bounds ranges are rejected.
- Packet smoke rendered `freshness: VERIFIED_CURRENT` and the required `Evidence: <path>@<blob-prefix> unchanged since <verified_at>` text; parsing preserves the field and old packets default to `UNKNOWN`.
- Real git rename probe returned `SOURCE_MOVED` from current `HEAD` history; resolver and capture use fixed-argv subprocess calls (no shell interpolation).
- Claude marker smoke accepts `Evidence:` as well as lowercase `evidence:`. Existing Claude adapter focused tests remain green.
- Cache checks invalidate uncommitted blob edits and newly-added source rows at unchanged HEAD, and recompute stale/missing states after edit reverts/restores; matching-source annotation and freshness failures are covered.

No model calls, secrets, formatter, linter, or project-wide validation were used.
