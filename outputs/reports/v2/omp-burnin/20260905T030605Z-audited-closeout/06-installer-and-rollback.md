# Installer and rollback closeout

## Scope and safety

Reviewed and changed only the scratch-safe installer surface:

- `scripts/install-prime-extension.ps1`
- `scripts/uninstall-prime-extension.ps1`
- `brainstem/tests/install-prime-extension.Tests.ps1`

No deployment was performed. No production extension directory, real user home, provider, configuration, or Brain state was touched. All destructive and injected-failure fixtures target a unique directory below `$env:TEMP`.

## Initial dispositions

| Stage F requirement | Initial disposition | Closeout disposition |
|---|---|---|
| Native OMP default under alternate `USERPROFILE` | **PASS, retain** — the completed fix already used `.omp\agent\extensions`; its two default-path regressions passed previously. | Retained and strengthened. Both install and uninstall remain covered with an alternate scratch `USERPROFILE`; `.prime` must remain absent. |
| Explicit `-ExtensionsDir` override | **PASS, incomplete regression**. | Covered independently of the default profile. The explicit target receives the extension and the default `.omp` tree is not created. |
| Source independent of `SECOND_BRAIN_HOME` | **PASS in source, incomplete Pester regression** — source resolved from `-SourceRoot` or `$PSScriptRoot`. | Covered with a conflicting decoy state home; only the explicit source is deployed. |
| Intended deployed manifest | **REPAIR** — the expected manifest began with a recursive whole-package manifest and then filtered it, so nested `src`/`types` files could be treated as deployable even though copy semantics are top-level `src/*.ts` flattened into the target plus top-level `types/*.d.ts`. | Expected entries are now generated directly from those two deployed sets. Tests add nested source/types, tests, `node_modules`, and metadata and require the exact three-file fixture layout. |
| Exact backup and failure-safe replacement | **REPAIR** — backup bytes were copied, but the active target was deleted before the staged directory was moved into place. A move failure could leave no active extension. | Backups carry a target-bound manifest record and are verified after copy. Replacement moves the active directory aside, moves the verified stage into place, and restores the displaced directory if replacement fails. Stage, copy, and move failures are injected in scratch fixtures. |
| Explicit rollback prevalidation and unrelated-backup rejection | **REPAIR** — uninstall removed the active target before checking `-BackupDir` and otherwise selected the newest filename globally. | Explicit backup existence, installer metadata, recorded destination, prior-presence state, and backup manifest are validated before mutation. No backup is selected implicitly. Restore is copied and verified in a stage, then swapped with rollback on move failure. Missing, wrong, wrong-destination, unrelated-latest, restore-copy, and restore-move regressions are included. |
| Configuration ownership | **REPAIR** — scripts invented a default settings path even though they never owned settings. | No settings path is inferred. An explicitly supplied compatibility `-SettingsFile` may still be copied into evidence, but install and uninstall never modify or restore it. Regressions prove default and explicit configuration preservation. |
| Existing relevant Pester failures | **REPAIR** — old fixtures omitted `-SourceRoot`, so they exercised the repository source while asserting against the scratch source; the missing-source case also pinned an unreliable exact process code. | Every source-dependent fixture passes the scratch `-SourceRoot`; failure contracts require nonzero status plus preservation of the observable target, not a shell-specific number. No failure-count waiver is used. |

## Resulting rollback contract

Each new installer backup keeps the existing directory convention:

```text
backups/<timestamp>-prime-extension-pre-install/
  install.json
  extensions/second-brain/...   # only when an extension existed
  settings/settings.json        # only when -SettingsFile was explicit and existed
```

`install.json` records schema version 1, the normalized destination, whether an extension existed, and its byte-hash manifest. `-BackupDir` is therefore explicit and destination-bound. A backup representing a previously absent extension restores absence. Omitting `-BackupDir` performs uninstall-only behavior and explicitly does not search for a “latest” backup.

## Regression inventory

The focused Pester file now covers:

1. explicit destination override and exact flattened `src`/`types` layout;
2. repeated installation and backup of the prior target;
3. state-home-independent source selection;
4. default install and uninstall under an alternate scratch `USERPROFILE`;
5. byte-exact nested/binary backup restoration;
6. install stage creation, stage copy, and replacement move failures;
7. missing, malformed/non-owned, tampered, and wrong-destination explicit backups;
8. refusal to auto-select an unrelated newest-looking backup;
9. explicit settings snapshot compatibility without configuration restoration or mutation;
10. restore copy and replacement move failures;
11. missing source preserving the current extension.

## Validation status and exact commands

**UNEXECUTED in this concurrent closeout stage.** Per the convergence rule, no Pester, pytest, parser, formatter, linter, build, deployment, or user-home command was run by this worker.

Use the same focused command first in the isolated pre-fix snapshot and then in the converged candidate; compare failed test identities, not only counts:

```powershell
$r = Invoke-Pester -Script "brainstem\tests\install-prime-extension.Tests.ps1" -PassThru
if ($r.TotalCount -ne 18 -or $r.FailedCount -ne 0) { exit 1 }
```

Run the adjacent existing Python contract in the converged candidate:

```powershell
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null; .venv\Scripts\python.exe -m pytest -q tests\test_prime_installer.py
```

For post-convergence proof, the expected focused Pester outcome is zero failed tests, all fixtures confined to `$env:TEMP`, and no `.second-brain-*` staging directories left by injected move/copy failures. The result remains **UNVERIFIED** until Main records the actual command output and counts.

## Main pre-fix execution

The frozen suite enumerated **18**, not 17, tests. Executed against isolated
`f5089ac1b6e27f0b3329196cec7e74f402cd0636`: **5 passed / 13 failed**.
Raw results: `artifacts/installer-before.json`. Missing and wrong explicit
backups and unrelated-latest selection failed directly. Nested source files
reproduced the manifest mismatch and prevented several later setup steps;
those blocked cases are not claimed as independent fault reproductions.

## Main post-convergence execution

Executed the candidate's unchanged 18-case Pester suite: **18 passed, 0 failed,
0 skipped**, approximately 12.2 seconds. Raw counts and named cases:
`artifacts/installer-after.json`; console output: `artifacts/installer-after.txt`.
The adjacent Python installer contract also passed in the focused 154-test
gate (`artifacts/pytest-after.txt`). This supersedes the worker's
UNEXECUTED/UNVERIFIED checkpoint above. It is scratch proof, not deployment.
