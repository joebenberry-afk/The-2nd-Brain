# AGENTS.md — working inside The Second Brain repository

This file governs agents working **on the Brain itself** (this repo).
It is not the global AGENTS.md marker that Brain installs into managed
projects (that is Phase 3+ and lives elsewhere).

## Authority

- `The_Second_Brain_OS_V4_1_OneShot_Implementation_Plan.md` is the
  authoritative specification (the older V4 Definitive plan is research
  history only).
- Repository code, tests, and verified runtime behavior outrank assumptions.
- The plan is implemented phase-by-phase. Do not jump ahead of the current
  phase gate. Milestone reports in `outputs/reports/` record gate evidence.

## Rules

1. **Constitution is protected.** Files in `constitution/` change only through
   explicit, reviewed change control — never as a side effect of another edit,
   and never by automatic learning machinery.
2. **Canonical vs derived.** Human-readable knowledge under `memory/`,
   `experiences/`, `decisions/`, `projects/`, `skills/`, `engrams/`,
   `constitution/`, `config/` is canonical and Git-versioned. Everything under
   `db/`, `state/`, `telemetry/`, `plasticity/`, `sleep/*` is derived and
   rebuildable. Do not hand-edit derived data; rebuild it.
3. **No secrets.** Never write credential values, tokens, or private keys into
   any file in this repository.
4. **Small increments.** After Python changes: `ruff check`, `pyright`, focused
   `pytest`. After TypeScript changes: ESLint, `tsc --noEmit`, Vitest. After DB
   changes: test fresh create, reopen, migration idempotency, backup/restore.
5. **Git policy.** `main` holds stable Brain state. Feature branches:
   `brain/<feature>`. Commit categories: `brain(core)`, `brain(memory)`,
   `brain(skill)`, `brain(policy)`, `brain(project)`, `brain(immune)`,
   `brain(db)`, `brain(adapter)`.
6. **Stop conditions.** If a plan STOP condition fires (see plan §147), stop
   and report; do not improvise around it.

## Environment gotchas (this machine)

- The user-level `PYTHONHOME` env var points at a corrupted uv CPython 3.11
  tree. Running Python with that env breaks with `AssertionError: SRE module
  mismatch`. Always run the project venv Python with `PYTHONHOME` and
  `PYTHONPATH` removed from the environment, e.g.:

  ```powershell
  $env:PYTHONHOME = $null; $env:PYTHONPATH = $null
  .venv\Scripts\python.exe -m second_brain doctor
  ```

  The `brainctl.cmd` shim and `scripts/bootstrap.ps1` do this automatically.

## Commands

```text
.venv\Scripts\python -m second_brain doctor   # health check
.venv\Scripts\python -m pytest                 # test suite
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m pyright
```

<!-- The-Second-Brain:begin id=second-brain -->
## The Second Brain

Canonical Brain: `%SECOND_BRAIN_HOME%`.

For substantive work:
- current repo/tests outrank memory;
- use targeted Brain recall;
- do not preload the Brain;
- use Brainstem signals where available;
- preserve durable validated learning.
<!-- The-Second-Brain:end -->
