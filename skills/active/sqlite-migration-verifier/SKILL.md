---
name: sqlite-migration-verifier
status: active
version: 1
source_episodes:
- success-20260814-025897e6
- success-20260814-7e49e733
- correction-20260814-ed0aee6b
created_at: 2026-08-14T08:27:59.248862+00:00
---

# Purpose

- Migration landings follow a repeated verification loop (occurrences: 0002, 0003)
- Migration landings follow a repeated verification loop (occurrences: 0004, 0005)
- Restore could replay stale WAL frames (matching salts) and resurrect moved-aside rows

# Positive Triggers

- schema version assertions or pinned tables change
- a new NNNN_*.sql migration file exists in the diff
(none)

# Negative Triggers

- documentation-only change
- no schema change in the diff
(none)

# Inputs

- migration SQL files changed by the task
- the isolated SQLite database or fresh Brain home under test
- the affected migration and backup/restore tests

# Procedure

1. 1. Run fresh-create migration; 2. Re-run migrate (idempotent); 3. Reopen DB; 4. Backup/restore roundtrip; 5. Update version-pinned legacy tests.
2. Never leave stale -wal/-shm beside a restored SQLite file; move the full DB file set and drop sidecars after copy.

# Tools

- `.venv\Scripts\python -m pytest`
- `brainctl`
- `git diff --check`

# Safety

- never test against the canonical live database when an isolated copy is available
- preserve and inspect the complete SQLite file set; never restore beside stale `-wal` or `-shm`
- do not modify original game, user, or repository data outside the requested scope

# Verification

- fresh-create migrations succeed
- a second migrate is idempotent
- the database reopens with `PRAGMA integrity_check = ok` and an empty foreign-key check
- backup/restore preserves schema and known rows without stale WAL/SHM resurrection

# Output

- exact commands and exit codes
- schema version, integrity checks, backup manifest hash, and restored-row evidence
- unresolved failures with the isolated path and rollback state

# References

- episode success-20260814-025897e6
- episode success-20260814-7e49e733
- episode correction-20260814-ed0aee6b
- evidence git:migration commits 0002-0003
- evidence git:migration commits 0004-0005
- evidence git:dc0e49d
- evidence report:outputs/reports/milestone-01-foundation.md reconciliation
- evidence test:tests/test_backup.py::test_restore_drops_stale_wal_shm
