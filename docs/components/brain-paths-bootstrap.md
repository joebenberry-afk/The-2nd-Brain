# Brain Paths & Bootstrap (shims)

## Purpose
Resolve the canonical Brain root and bootstrap a fresh Windows installation without hardcoding absolute paths (plan §1, §83).

## Problem it solves
Source needs one stable root (`SECOND_BRAIN_HOME`, else `%USERPROFILE%\Documents\The-Second-Brain`); this machine's `PYTHONHOME`/`PYTHONPATH`/`UV_INTERNAL__PYTHONHOME` are polluted and break Python ("SRE module mismatch"), so every launcher must sanitize them.

## Responsibilities
- `paths.py`: `resolve_home`/`default_home`; idempotent `ensure_layout` of all `MAJOR_DIRS`; `db_path`; `backups_dir`; `REQUIRED_CONFIG_FILES` (8 TOML).
- `scripts/bootstrap.ps1`: resolve root; refuse non-empty non-Brain dirs unless `-Force`; verify Python+Git; create venv; editable install (uv, fallback pip); `git init` if missing; `python -m second_brain init`; doctor; persist `SECOND_BRAIN_HOME` (User scope) only with `-PersistEnv` AND doctor pass; exit with doctor's code.
- `brainctl.cmd` / `scripts/doctor.ps1`: clear the three env vars, then run `.venv\Scripts\python.exe -m second_brain [doctor]`.

## Non-responsibilities
Never edits global agent configs (adapters are a separate step); does not install adapters/tools; does not persist env unless asked AND healthy.

## Inputs
`SECOND_BRAIN_HOME`, `USERPROFILE`; flags `-Force`/`-PersistEnv`/`-SkipVenv`.

## Outputs
Layout skeleton (VERSION, config/*.toml, major roots), `.venv`, `.git`, migrated `db/brain.sqlite`, doctor report.

## State ownership
Root directory skeleton and environment hygiene; refuses to touch non-Brain user content.

## Invariants
Source never hardcodes the Brain path; `ensure_layout` idempotent; no Python launch with polluted env vars.

## Interactions
bootstrap → `init` (layout+seed+migrate) → doctor; `brainctl.cmd` wraps every CLI call; doctor warns when pollution is detected.

## Failure behavior
Non-Brain non-empty dir without `-Force`: exit 2, no changes; missing Python/Git: exit 1; any failed step aborts (`$ErrorActionPreference="Stop"`); doctor failure blocks env persistence.

## Verification
`tests/test_paths.py` (4: env-wins/default resolution, idempotent layout); `tests/test_doctor.py::test_doctor_warns_on_python_env_pollution`. Shims are thin; exercised by every real bootstrap/doctor run.

## Known limitations
Windows/PowerShell only; no automated Pester test for bootstrap.ps1 itself.

## Future extension
Non-Windows bootstrap; adapter install step.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #2 (stdlib-only), #8 (reuse idle workers).

## Relevant tests
`tests/test_paths.py`, `tests/test_doctor.py`.
