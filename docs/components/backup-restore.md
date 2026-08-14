# Backup & Restore

## Purpose
Create consistent, verifiable Brain snapshots and restore them safely (plan §126-127).

## Problem it solves
Durable state (DB + config + constitution + projects) must never be lost; restoring over a live Brain must never silently destroy current data or resurrect stale WAL frames.

## Responsibilities
- `create_backup`: `backups/backup-<UTC>/` with consistent DB snapshot (sqlite3 `backup()` API, WAL-safe), copies of config/constitution/projects + VERSION, `manifest.json` `{format:1, created_at, note, db:{file, sha256}, copied}`.
- `list_backups` (newest first); `load_manifest` (format-validated).
- `restore_backup`: verify manifest + DB hash; refuse without `--force` when real data exists; with `--force` move current state to `backups/pre-restore-<ts>/` (never delete); roll back on failure; drop stale `-wal`/`-shm`; byte-verify restored DB; `db.migrate`; `git init` target if needed.

## Non-responsibilities
Does not back up `state/`, `outputs/`, `telemetry/`, `.venv`, git objects; never deletes user data.

## Inputs
`home`; backup dir; `--force`.

## Outputs
Backup trees + manifests; restored home state.

## State ownership
`backups/` (derived, non-Git) and transient `pre-restore-*` dirs.

## Invariants
Consistent snapshot under WAL; restore refused without force when data would be overwritten; corrupt manifest/hash mismatch → `BackupError`; no stale WAL/SHM next to restored DB; failed restore preserves previous state.

## Interactions
`db` (snapshot, migrate), `paths`; `brainctl backup|restore`; backup precedes adapter/config changes (plan §126).

## Failure behavior
All failures → `BackupError`; restore failure rolls the aside back and reports the previous state preserved.

## Verification
`tests/test_backup.py` (11): roundtrip, consistency, refusal, force move-aside, hash verification, stale sidecars, rollback, migration re-apply, git init.

## Known limitations
No dedup/retention; shallow `projects/` copy (fine for current layout).

## Future extension
Retention/rotation; encrypted off-site targets; memory/skill phase backups.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #2, #10.

## Relevant tests
`tests/test_backup.py`, `tests/test_cli.py::test_backup_restore_cli`, `tests/test_migrations_property.py::test_backup_restore_preserves_rows`.
