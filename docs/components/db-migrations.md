# Database & Migrations

## Purpose
Own the SQLite control DB and the ordered, idempotent migration framework that keeps every Brain on the current schema (plan §8-9).

## Problem it solves
Reliable control store (WAL + foreign keys) whose schema evolves without manual steps and without corrupting existing Brains.

## Responsibilities
- `connect()`: `row_factory=Row`, `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`, `busy_timeout=5000`; read-only via `mode=ro`.
- `split_statements()`: parse scripts with `sqlite3.complete_statement` (strings/comments handled; incomplete tail raises `MigrationError`).
- `migration_files()`: ordered `NNNN_*.sql`; `current_version`/`pending_migrations` via `schema_version` table.
- `apply_migration()`: per-file atomic (`BEGIN IMMEDIATE` → statements → version row → commit; rollback on error).
- `migrate()`: apply pending, return versions applied.

## Non-responsibilities
Does not store knowledge/memories; never silently drops data.

## Inputs
`db.db_path(home)` → `db/brain.sqlite`; `migrations/*.sql`.

## Outputs
Migrated DB + `schema_version` rows.

## State ownership
`db/brain.sqlite` (+ WAL/SHM sidecars); migration history authoritative in `schema_version`.

## Invariants
WAL+FK+synchronous=NORMAL always on write connections; migrate idempotent; migration-prefix property (any prefix then remainder == full apply); FK enforced.

## Interactions
Used by `brainctl init`, doctor (pending check), backup restore (re-migrate), registry, telemetry.

## Failure behavior
Failing migration rolls back atomically → `MigrationError`; doctor reports pending migrations as FAIL; corrupt DB → doctor FAIL.

## Verification
`tests/test_db.py` (8: pragmas, idempotency, FK, statement splitting, custom dir ordering); `tests/test_migrations_property.py` (2 Hypothesis: prefix+remainder equivalence, backup/restore preserves rows).

## Known limitations
Single SQLite file; migrations append-only by convention (backup restore is the rollback path).

## Future extension
Memory/skills/immune phases add their own `NNNN_*.sql` migrations. Committed: `0007_memory_index.sql` — derived FTS5 index metadata for retrieval (commit `2ce8c0f`); live DB reindexed to schema v7.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #2 (stdlib-only).

## Relevant tests
`tests/test_db.py`, `tests/test_migrations_property.py`, `tests/test_backup.py::test_restore_applies_pending_migrations`.
