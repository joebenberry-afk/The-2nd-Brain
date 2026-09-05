# P1 #2 — Installer Default-Path Regression Results

## New regression tests

Added to `brainstem/tests/install-prime-extension.Tests.ps1`:

- `install defaults ExtensionsDir/SettingsFile to the OMP auto-discovery
  path, not .prime` — overrides `$env:USERPROFILE` to an isolated fake home,
  invokes `install-prime-extension.ps1` with `-SourceRoot` only (no
  `-ExtensionsDir`/`-SettingsFile`), and asserts the extension lands at
  `<fakehome>\.omp\agent\extensions\second-brain\index.ts` and that no
  `<fakehome>\.prime` directory is ever created.
- `uninstall defaults ExtensionsDir/SettingsFile to the OMP auto-discovery
  path, not .prime` — same fake-home isolation; pre-seeds
  `<fakehome>\.omp\agent\extensions\second-brain\marker.txt`, runs
  `uninstall-prime-extension.ps1` with no `-ExtensionsDir`, and asserts the
  marker is removed (proving the default target was actually used) and no
  `.prime` directory exists.

Both tests use `-SourceRoot $script:brain` (the fake extension source tree
already built in `BeforeEach`) so they never touch the real repository's
`backups/` directory and never depend on the real installed extension.

## Focused suite

```text
powershell -NoProfile -Command "Invoke-Pester -Script brainstem\tests\install-prime-extension.Tests.ps1 -PassThru"
```

Result: **5 passed / 2 failed** (both new tests pass).

## Pre-existing baseline failures (unchanged, out of scope)

The same 2 failures reproduce identically on the unmodified qualification
HEAD (`0b2aaf9`, verified via `git stash` / `git stash pop` A-B comparison
on the exact same tree):

1. `is idempotent and backs up the previous target` — pre-existing test bug:
   invokes the installer without `-SourceRoot`, so the script's default
   `$SourceRoot` resolves to the real repository root, not the fake
   `$script:brain` tree the test built; the assertion then looks for a
   backup under `$script:brain\backups` where none was ever written. Not
   caused by, or related to, either P1 defect in this repair's scope.
2. `fails when source index.ts is missing` — same root cause: removes
   `$script:brain`'s fake `src/index.ts`, but the installer (again
   defaulting `$SourceRoot` to the real repo root) never looks there, so it
   succeeds against the real repository's own extension source instead of
   failing.

Both are pre-existing repository test-authoring defects (missing
`-SourceRoot $script:brain` on 3 of the 7 test cases), unrelated to
`P1-OMP-WORKER-AUTODELIVERY` or `P1-OMP-INSTALLER-DEFAULT`, and out of scope
per this repair's "no broad re-implementation" boundary
(`00-starting-state.md`).
