# M00 activation card — prepared, NOT executed (2026-09-24)

**Decision owner:** repository owner. This card is a proposal. Production is
unchanged. Status: `M00_CODE_QUALIFIED / EXTERNAL_TRUST_ROOT_PENDING`; the
authority-dependent features stay fail-closed after activation
(`../../M00-CAMPAIGN-REGISTER.md`, "M00 boundary decision").
**Evidence:** [`REHEARSAL.md`](REHEARSAL.md) (R1–R9, all PASS on disposable
copies of production bytes) and [`INVENTORY.json`](INVENTORY.json).

## Release subject

- Release worktree: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\qualified-m00`,
  **detached at `749e9cd`**. Its code equals final code subject `80f3c54`; the
  later commits change documentation only. Created for this card: production
  should run from a frozen checkout, not from the development worktree.
- Extension source in that worktree, as the installer computes it: 17 files,
  manifest `ce7fefa86ad89a607dc29ad244eedfcf588a563335f79bb73ea90b1666544421`,
  `index.ts` `10a8662f299381621a92731a20c240169f988c76f811903bb0cc2ada4f685369`
  (recomputed from `qualified-m00`; equal to the rehearsed install).
- Editable re-point rehearsed in a throwaway venv built from the canonical
  interpreter (3.13.7): `second_brain` imports from `qualified-m00\src`, and all
  three issuer registries are empty.

## Exact activation delta

| Component | Production now | After activation |
|---|---|---|
| OMP extension `%USERPROFILE%\.omp\agent\extensions\second-brain` | 26 files, `6688f073…`, `index.ts 64676a40…` (native-delegation hotfix) | 17 files, `ce7fefa8…`, `index.ts 10a8662f…`. Removed: `budget-bridge`, `driver-orchestrator`, `native-settlement`, `orchestrator-guard`, `routing-bridge`, `stop-boundary`, `worker-context-bridge`, `worker-lifecycle-bridge`, `worker-result-bridge`. Changed: `index.ts`, `injection-slots.ts`, `lean-code.ts`, `sensors.ts`, `types/prime.d.ts` |
| Python runtime: canonical `.venv` editable target (used by the extension, `brainctl`, and the Claude Code, Codex and Antigravity hooks) | `.worktrees\qualified-v2` @ `827c3df` | `.worktrees\qualified-m00` @ `749e9cd` (79 commits; removes `worker_protocol`, `worker_recovery`, `host_protocol`, `model_routing`). **No dependency change**: `pyproject.toml` differs only in its description; `dependencies = []` |
| Canonical DB `db\brain.sqlite` | schema 24 | schema 28 via migrations 25–28: additive only (new tables `budget_reservations`, `runtime_lineage`, `episode_roots`, plus `ADD COLUMN`s); no DROP or rewrite. 116 memories preserved |
| Stored authority | 19 rows `VERIFIED`, 10 rows `project_rule`/`policy` | rows unchanged on disk. Effective: **at most TESTED**, ceiling **advisory**; displayed as `TESTED (claimed VERIFIED)` |
| Config / OMP settings | — | none changed. The installer writes no settings; `init` seeds only missing defaults (0 of 25 missing); `config/orchestration.toml` becomes inert |
| Hook configs (Claude Code, Codex, Antigravity) | point at runner scripts in `qualified-v2` | **unchanged**. The runners call `autoinject claude-code-hook` / `codex-shadow` / `antigravity-hook`, all present in the release. Their Python follows the venv; they fail open |

Behavior you will notice (rehearsed in R6):

- `--grade VERIFIED` is refused (`VERIFIED_REQUIRES_ATTESTATION`).
- CRITICAL and approval-bearing `verify gate` runs cannot complete.
- `models record` refuses.
- The policy lane is empty.
- Retired orchestration commands (`worker-plane`, `stop`, the governor budget
  commands) exit 2 with `ORCHESTRATION_REMOVED`.
- Native OMP `task` delegation works without Brain admission, as with today's
  hotfix.
- `doctor` shows one expected warning: an active skill without committed
  authority (the accepted SEC-SKILL-01 residual).

## Required runtime route

Re-point the **canonical venv**. Setting `SECOND_BRAIN_PYTHON` alone is **not
sufficient**. The Antigravity hook hardcodes `<home>\.venv\Scripts\python.exe`,
and `brainctl.cmd` uses that venv too. With only the variable set, the old
`qualified-v2` code would keep running against the same migrated DB, where it
reads stored VERIFIED/`project_rule` rows as authority and can mint new ones
(rehearsal R8). That would split the runtime and defeat the fail-closed
boundary.

## Activation steps (for the owner; not executed)

PowerShell, from `C:\Users\assas\Documents\The-Second-Brain`. Set
`$env:PYTHONHOME = $null; $env:PYTHONPATH = $null` first.

```powershell
$BrainHome = "C:\Users\assas\Documents\The-Second-Brain"
$Rel  = "$BrainHome\.worktrees\qualified-m00"
$Ext  = Join-Path $env:USERPROFILE ".omp\agent\extensions\second-brain"
$Py   = "$BrainHome\.venv\Scripts\python.exe"

# 0. Close every OMP, Claude Code, Codex and Antigravity session: the live DB
#    changed bytes four times during preparation.

# 1. Freeze the rollback baseline (production runtime; the manifest records the DB sha256)
& $Py -m second_brain --home $BrainHome backup --note "pre-M00-activation"
Copy-Item -Recurse -Force $Ext "$env:TEMP\m00-preactivation-extension-second-brain"
#    confirm the copy: 26 files, manifest 6688f073…, index.ts 64676a40…

# 2. Extension. Keep the printed "Pre-install backup:" path; expect manifest ce7fefa8…
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File "$Rel\scripts\install-prime-extension.ps1" -SourceRoot $Rel

# 3. Runtime: re-point the canonical venv
uv pip install -e $Rel --python $Py
& $Py -c "import second_brain; print(second_brain.__file__)"   # expect ...\qualified-m00\src\...

# 4. Database: expect "applied migrations [25, 26, 27, 28]"
& $Py -m second_brain --home $BrainHome init

# 5. Verify (read-only checks and refusals only)
& $Py -m second_brain --home $BrainHome doctor                        # 0 failed; 1 expected skill-authority warning
& $Py -m second_brain --home $BrainHome memory list                   # stored VERIFIED rows read "TESTED (claimed VERIFIED)"
& $Py -m second_brain --home $BrainHome memory add "probe" --grade VERIFIED   # expect rc 2 VERIFIED_REQUIRES_ATTESTATION

# 6. Start OMP fresh; a running process keeps the module it already loaded.
```

## Rollback (reverse order; see REHEARSAL.md §4)

Rolling back restores the old runtime, and with it the SEC-AUTH-01/02
behavior: caller-minted VERIFIED and authority come back. Treat a rollback as a
security regression, taken only to restore service.

```powershell
# close all sessions first
# a. Extension (rehearsed R9: byte-identical restore to 6688f073… / 64676a40…)
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File "$Rel\scripts\uninstall-prime-extension.ps1" `
  -ExtensionsDir (Join-Path $env:USERPROFILE ".omp\agent\extensions") -BackupDir "<Pre-install backup path from step 2>"
#    fallback, with OMP stopped: remove $Ext, then copy back "$env:TEMP\m00-preactivation-extension-second-brain".
#    Do NOT use disabled-extensions\second-brain-pre-removal-20260923: that is the
#    pre-hotfix original, which re-breaks native task delegation.

# b. Runtime
uv pip install -e "$BrainHome\.worktrees\qualified-v2" --python $Py
& $Py -c "import second_brain; print(second_brain.__file__)"   # expect ...\qualified-v2\src\...

# c. Database: optional for function (R8: the old build reads and writes schema 28 cleanly).
#    Required only to return to the pre-activation data state; discards later writes.
& $Py -m second_brain --home $BrainHome restore "<backup dir from step 1>"
```

After rollback, verify: extension 26 files / `6688f073…` / `index.ts 64676a40…`;
import from `qualified-v2`; DB `integrity ok` at schema 24 (restored) or 28
(left migrated), with `memories ≥ 116`.

## Not claimed

- No independent approval, protected custody or cryptographic signing exists.
- Activation re-enables none of the fail-closed capabilities.
- A real OMP session with the **installed** release extension against the
  **canonical** home has not been run; that is step 6 of the activation. The
  same candidate extension bytes were already exercised in real OMP through `-e`
  with disposable homes (`../native-noninterference-20260923.json`,
  `../memory-realpath-20260923.json`).
