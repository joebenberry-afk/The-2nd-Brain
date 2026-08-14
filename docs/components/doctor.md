# Doctor

## Purpose
Deterministic, evidence-based health checks for a Brain installation (Phase 1; `brainctl doctor`).

## Problem it solves
One command proves a Brain is healthy — or says exactly what is missing.

## Responsibilities
`run_doctor(home)` checks: home exists + Brain marker (VERSION or config/brain.toml); layout (all `MAJOR_DIRS`); config (8 TOML parse); version file vs `__version__`; env (`SECOND_BRAIN_HOME` warn if unset; PYTHONHOME/PYTHONPATH/UV_INTERNAL__PYTHONHOME pollution warn); python/sqlite3 versions; git present + home is a repo; database (openable, wal, fk, no pending migrations); tools rg/ast-grep/repowise/uv (warn-only). `format_result` prints; exit 0 only when no FAIL.

## Non-responsibilities
Read-only; never fixes; warnings never fail.

## Inputs
`home` (or `paths.resolve_home()`); PATH.

## Outputs
`DoctorResult` (checks, `failed`, `warnings`) + formatted output; exit code.

## State ownership
None.

## Invariants
Deterministic per environment; exit 0 iff all checks pass; each failure is actionable; env pollution is a warning (shims are the fix).

## Interactions
`paths`, `db`, `__version__`; consumed by bootstrap (gates `-PersistEnv`), `brainctl doctor`, phase gates.

## Failure behavior
Probes never raise; `_run` reports missing binary/timeout (tools warn, git fails).

## Verification
`tests/test_doctor.py` (8): pass on fresh brain; fail on missing home/layout/config/DB; fail on pending migration; pollution warning; formatting.

## Known limitations
RepoWise index freshness not checked yet; tools warn-only; no disk/perf checks.

## Future extension
RepoWise freshness check; environment-steward checks (Phase 8); memory health (9-10).

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #2.

## Relevant tests
`tests/test_doctor.py`, `tests/test_cli.py::test_init_doctor_status_flow`.
