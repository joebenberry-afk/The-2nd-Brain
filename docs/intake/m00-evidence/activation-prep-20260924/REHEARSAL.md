# M00 activation preparation — rehearsal record (2026-09-24)

**Subject:** `.worktrees/m00.3-producer-guard`, branch `brain/m00.3-producer-guard`,
HEAD `749e9cd` (final **code** subject `80f3c54`; the two later commits change
documentation only).
**Companion:** [`INVENTORY.json`](INVENTORY.json) — machine-readable production /
candidate identities, delta tables, migration list.
**Status: PREPARATION ONLY.** Nothing was installed, migrated, renamed or
configured in production. No OMP session was started that would load the
candidate extension. Production was only ever read.

## 0. How production was read (read-only statement)

| Access | Mechanism |
| --- | --- |
| Canonical DB | `sqlite3.connect("file:<path>?mode=ro", uri=True)` + `PRAGMA query_only=ON`; the rehearsal copy was produced with the **sqlite backup API from that read-only connection** (`Connection.backup`) into `%TEMP%` |
| Files | `Get-FileHash` / `hashlib.sha256`, directory listings, metadata reads |
| Git | `rev-parse` / `log` / `diff` / `status` only (no add/commit/stash/reset/checkout) |
| Sourcing | installed extension `.ts`, installer/uninstaller `.ps1`, `~/.omp/agent/config.yml`, `settings.json.bak`, Claude/Codex/Antigravity hook configs, `pyproject.toml`, venv `.pth`/`pyvenv.cfg` |
| Import probes | `<interpreter> -c "import second_brain,sys;print(...)"` with `PYTHONHOME`/`PYTHONPATH` stripped. Import-only: `second_brain/__init__.py` imports just `.paths`, whose `mkdir` lives inside `ensure_layout()` and is never called at import; nothing was written to the canonical home |

**Writes performed:** only under `C:/Users/assas/AppData/Local/Temp/m00-activation-prep/`.
Every `migrate` / `init` / `doctor` / `backup` / `restore` / `memory` run used a
disposable `SECOND_BRAIN_HOME` under `%TEMP%`. No `brainctl`/`second_brain`
command was ever pointed at the canonical home.

### Live-DB caveat (measured, not assumed)

The canonical DB is being written by running OMP sessions. Its **bytes changed
four times during this session while its content stayed identical**:

| sha256 | observed |
| --- | --- |
| `4d21d503b589357fb666319ccc7e1fa72644eeca5bf3abba5c04d09d90af3738` | first inventory read |
| `f4dfc415484277cd71ff7d42c38521aaee08712b8d0d10d5f84fd8427a5fdaee` | 2026-09-24 02:32:44 −0400 (mtime) — **the state rehearsed here** |
| `0d2f2b0fa0c752587c1a4c73282a9a1ae3b01f844c91db3b8cac474908eb7f3c` | 2026-09-24 02:38:01 −0400 (mtime) |
| `ebe4198bd6690a8a5861d946978836c799fc80b61ec55cea2bb001797008ddd9` | 2026-09-24 02:40 −0400 (final verification pass) |

Content identical in all four: `schema_version=24`, `memories=116`,
`evidence_grade='VERIFIED'` **19**, `authority_ceiling in
('project_rule','policy')` **10**, `episodes=18`, `PRAGMA integrity_check = ok`.
WAL/SHM sidecars were absent at every observation. **A real activation must be
taken with no active sessions, and its backup must record its own hash at that
moment.**

## 1. What production runs today (summary; full detail in INVENTORY.json)

| Item | Value |
| --- | --- |
| Installed OMP extension | `C:\Users\assas\.omp\agent\extensions\second-brain` — 26 files, manifest `6688f07343ce3f02d44f2567359d28a52ff0a387d6237f3bde556e75e52ed2d3`, `index.ts` `64676a40d33ea7a644bd955f8aace7256d3c751cd0acd427b3fe9e78e0f04d55` (matches `outputs/reports/omp-native-recovery-20260923/RECOVERY.md`) |
| Preserved pre-hotfix original | `C:\Users\assas\.omp\disabled-extensions\second-brain-pre-removal-20260923` — 26 files, `33e7c72c154d0e8aeeb411093f3f2c7dcc13de2b6afff424418f9b4a91e261fe`, `index.ts` `0412eac3b857952a32bed1c311f622324b1224a90f8e8df0b1a9774a08947a84` |
| Python runtime resolution | `SECOND_BRAIN_PYTHON` (unset) → `<home>/.venv/Scripts/python.exe`, spawned with `cwd=<home>`, `SECOND_BRAIN_HOME=<home>`, `PYTHONHOME`/`PYTHONPATH` deleted |
| Resolved interpreter | `C:\Users\assas\Documents\The-Second-Brain\.venv\Scripts\python.exe` |
| Source tree it imports | `C:\Users\assas\Documents\The-Second-Brain\.worktrees\qualified-v2\src\second_brain\__init__.py` (editable `.pth`), HEAD `827c3df63335c2a9b0e9373c71b1f5f1348d8362` |
| Brain home | `C:\Users\assas\Documents\The-Second-Brain` (also the value of env `SECOND_BRAIN_HOME`) |
| OMP settings entries naming the extension | **none** — OMP auto-discovers `~/.omp/agent/extensions/*`; `~/.omp/agent/config.yml` contains no extension entry, no live `settings.json` exists (only a 68-byte `settings.json.bak`) |
| Other integrations | Claude Code hooks (5 events) → `qualified-v2\brainstem\adapters\claude-code\scripts\run-hook.ps1`; Codex hooks (5 events) → `qualified-v2\brainstem\codex-hooks\run.ps1`; Antigravity plugin `~/.gemini/config/plugins/second-brain-adapter`; `brainctl.cmd` + `.venv\Scripts\brainctl.exe` → canonical venv → qualified-v2 |

## 2. Delta the owner will get (summary; tables in INVENTORY.json)

- **Extension:** 26 → 17 files. Removed: `budget-bridge`, `driver-orchestrator`,
  `native-settlement`, `orchestrator-guard`, `routing-bridge`, `stop-boundary`,
  `worker-context-bridge`, `worker-lifecycle-bridge`, `worker-result-bridge`.
  Changed: `index.ts`, `injection-slots.ts`, `lean-code.ts`, `sensors.ts`,
  `types/prime.d.ts`. Unchanged: 12. Candidate manifest
  `ce7fefa86ad89a607dc29ad244eedfcf588a563335f79bb73ea90b1666544421`,
  `index.ts` `10a8662f299381621a92731a20c240169f988c76f811903bb0cc2ada4f685369`.
  Import-graph check: 15 relative imports, all resolve inside the candidate tree,
  zero references to removed modules.
- **Python source:** `827c3df..80f3c54` = **79 commits**, 219 files,
  +15934 / −38915 (src 37 files −9777/+1930; tests 61 −8321/+2966;
  brainstem 53 −12739/+904; docs 34 +8795/−186; scripts 28 −7729/+1273).
- **Migrations to apply:** `[25, 26, 27, 28]` — additive only (2 new tables + 2
  tables created, 2 additive `ALTER TABLE … ADD COLUMN`, one with
  `NOT NULL DEFAULT 0`); no DROP, no table rewrite.
- **Config/settings:** the installer writes **nothing** to settings (it only
  copies a given `-SettingsFile` into its backup). Migrations never touch config.
  `init`'s seeding copies only *missing* files and the real canonical home is
  missing **0 of the candidate's 25 default files**. `config/orchestration.toml`
  becomes inert (no reader in the candidate); the legacy
  `worker_slots`/`premium_model_turns` keys in `config/v2.toml` are tolerated.

## 3. Executed rehearsal — commands and results

All commands used the candidate interpreter
`C:\Users\assas\Documents\The-Second-Brain\.worktrees\m00.3-producer-guard\.venv\Scripts\python.exe`
with `PYTHONHOME`/`PYTHONPATH` stripped (`env -u`), or the production interpreter
for the rollback leg. Scratch scripts live in
`%TEMP%/m00-activation-prep/`.

| # | Step | Verdict |
| --- | --- | --- |
| R1 | DB copy via sqlite backup API from a read-only source connection | **PASS** |
| R2 | Disposable home fixture (config, VERSION, content dirs, layout, git init) | **PASS** |
| R3 | Candidate migrate on the copy | **PASS** |
| R4 | Candidate `init` on an existing home copy (the activation command) | **PASS** |
| R5 | Candidate `doctor` on the migrated home | **PASS** (0 failed, 1 pre-existing warning) |
| R6 | Owner-visible fail-closed behaviour transcript | **PASS** |
| R7 | Candidate `backup` + `restore` on the temp home | **PASS** (byte-exact) |
| R8 | Rollback proof: pristine copy reopens; production build works against the migrated DB | **PASS** |
| R9 | Installer on **production bytes** → uninstaller restore | **PASS** |

### R1 — copy the canonical DB read-only

```bash
env -u PYTHONHOME -u PYTHONPATH <candidate>.venv/Scripts/python.exe s1-copy.py \
  "C:/Users/assas/Documents/The-Second-Brain/db/brain.sqlite" "<tmp>/rehearsal/pre/brain.sqlite"
# same again into <tmp>/rehearsal/home/db/brain.sqlite
```

Observed: `source_sha256 f4dfc415484277cd71ff7d42c38521aaee08712b8d0d10d5f84fd8427a5fdaee`,
`source_schema_version 24`, `source_integrity ok`; each destination
`integrity ok`, `schema_version 24`, `memories 116`, `verified_stored 19`,
`authority_elevated 10`, `sha256 1819e50c8f5fb7517b2182daea81ea5a2be7c5b17a652e72f8daa6eba4d0b16f`.
The copy hash differs from the source because the backup API writes a fresh page
layout — equivalence is content-verified (integrity + counts), not byte-identity.

### R2 — disposable home fixture

```bash
cp -r "<home>/config" "<tmp>/rehearsal/home/config"; cp "<home>/VERSION" "<tmp>/rehearsal/home/VERSION"
for d in memory experiences decisions skills projects constitution engrams lexicon plasticity proof frontier immune; do cp -r "$d/." "<tmp>/rehearsal/home/$d/"; done
git init -q <tmp>/rehearsal/home        # doctor requires a git repo
```

`paths.ensure_layout(home)` (candidate code) created the 70 major roots.
Honest note: the first attempt used `cp -r memory <existing>/memory`, which
nested a copy; `doctor` correctly flagged the missing body
(`memory/semantic/mem-0fcad79fd46b.md`) and the fixture was rebuilt with `dir/.`
merge semantics.

### R3 — migrate the copy (candidate runtime)

```bash
env -u PYTHONHOME -u PYTHONPATH <candidate>.venv/Scripts/python.exe s2-migrate.py "<tmp>/rehearsal/home"
```

Observed:

```
module_file  ...\m00.3-producer-guard\src\second_brain\__init__.py
dbfile_sha256_before 1819e50c8f5fb7517b2182daea81ea5a2be7c5b17a652e72f8daa6eba4d0b16f
pending_before [25, 26, 27, 28]
counts_before {"memories": 116, "verified_stored": 19, "authority_elevated": 10, "episodes": 18}
applied_migrations [25, 26, 27, 28]
max_schema_version 28
integrity_check ok          quick_check ok          foreign_key_violations 0
counts_after  {"memories": 116, "verified_stored": 19, "authority_elevated": 10, "episodes": 18}
counts_preserved True
tables_added ["budget_reservations", "episode_roots", "runtime_lineage"]
tables_removed []
rows_downgraded_by_effective_grade 19
rows_downgraded_by_effective_ceiling 10
sample_regraded [["mem-29557f93448f","VERIFIED","TESTED"], ...]
sample_re_ceiling [["mem-3693230ebaf0","project_rule","advisory"], ...]
dbfile_sha256_after 474a24452bb9ea8be759334c68d9469d135c9422f8cf883dcb4b0d8c1765afbb
```

### R4 — the activation command itself (`init`) on a second pristine copy

```bash
env -u PYTHONHOME -u PYTHONPATH SECOND_BRAIN_HOME=<copy> <candidate>.venv/Scripts/python.exe \
  -m second_brain --home <copy> init
```

Observed: `applied migrations [25, 26, 27, 28]`, `rc=0`; the copy reopened at
`schema_version 28` with counts preserved (116 / 19 / 10 / 18). (It reported
`seeded 13 default files` only because this fixture lacked most content dirs.)
Computed for the **real** canonical home, read-only: **0 of 25** candidate
default files are missing, so the same command would seed nothing there.

### R5 — doctor on the migrated home

```bash
env -u PYTHONHOME -u PYTHONPATH SECOND_BRAIN_HOME=<tmp home> <candidate>.venv/Scripts/python.exe \
  -m second_brain --home <tmp home> doctor
```

`21 checks: 0 failed, 1 warnings` — the warning is
`governance authority — active skills without committed authority: sqlite-migration-verifier`,
the SEC-SKILL-01 issuer dependency the register already dispositions as accepted
pending an external trust root. Relevant passes: `migrations — current at
version 28`, `canonical memories — current and historical files present`,
`database — journal_mode=wal`.

### R6 — owner-visible behaviour (verbatim, disposable home)

| Command | Observed |
| --- | --- |
| `memory show mem-29557f93448f` | `grade: TESTED (claimed VERIFIED)` (rc 0) |
| `memory list` | rows read `TESTED (claimed VERIFIED)` for stored `VERIFIED` rows |
| `memory search "migration order"` | `mem-a8d221e64549  [current/TESTED] Migration ordering` |
| `memory curate mem-29557f93448f --status current` | `mem-29557f93448f -> grade=TESTED (claimed VERIFIED) status=current` |
| `memory add … --grade VERIFIED` | rc 2, `VERIFIED_REQUIRES_ATTESTATION: add_memory cannot write grade VERIFIED from a caller-supplied claim…` |
| `memory curate … --grade VERIFIED` | rc 2, `VERIFIED_REQUIRES_ATTESTATION: curate cannot write grade VERIFIED …` |
| `models record probe-model probe-skill probe-task --success true` | rc 2, `MODEL_IDENTITY_NOT_AUTHENTICATED: … records nothing` |
| `verify gate s1 <repo> --criticality CRITICAL --action "run tests=passed" --json` | rc 1, `"completion_allowed":false`, `"approval_state":"required"`, `"approval_attestation":"unavailable"`, `"decision_reason":"independent_verification_missing"` |
| `--home <ABSENT> worker-plane spawn s t --json` | rc 2, `{"status":"failed","failure_code":"ORCHESTRATION_REMOVED"}`; absent home **not** created |
| `--home <ABSENT> stop decide --session s --task-id t` | rc 2, same refusal; absent home not created |
| `--home <ABSENT> governor check-budget --session s --json` | rc 2, same refusal; absent home not created |

`semantic._lane_authorized` reads `effective_authority_ceiling`; with 10/10
elevated rows resolving to `advisory`, the policy lane admits nothing.

### R7 — candidate `backup` / `restore`

```bash
<python> -m second_brain --home <tmp home> backup --note "m00 rehearsal pre-rollback"
# -> <tmp home>/backups/backup-20260924-063443-123585  (manifest.json format 2, schema_version 28,
#    db sha256 fb4853fa1de1f73f6e5593a98f1cbf0c7b08f4af3bc582e56b6a9c84c9f67808)
<python> -m second_brain --home <fresh tmp home> restore <that backup dir>
```

Restore rc 0; restored DB sha256 `fb4853fa…` — **byte-identical to the manifest**,
integrity ok, `schema_version 28`, counts preserved.

### R8 — rollback proof

* Pristine pre-migration copy unchanged and healthy:
  `1819e50c…`, `schema_version 24`, `integrity ok` — the same bytes that exist
  only in `%TEMP%` today would be the restore source.
* The **production** build (`.venv` → `qualified-v2`, HEAD `827c3df`) was run
  against a copy of the **migrated** (schema 28) DB in a temp home:
  - read: `memory list` rc 0 and shows the **stored** `VERIFIED` — the effective-grade
    downgrade is a property of the candidate runtime, not of the DB;
  - write: `memory add …` rc 0; afterwards `integrity ok`, `schema_version 28`,
    `memories` 116 → 117, no error from the unknown tables;
  - old behaviour returns with the old runtime: `memory add … --grade VERIFIED`
    rc 0 and the row lists as `VERIFIED`.
  **Conclusion:** migrations 25–28 are backward-compatible for the old build's
  reads and writes; a DB rollback is therefore optional, not mandatory, for
  restoring basic function — but see §5.2 for what the old build then re-exposes.

### R9 — installer / uninstaller on production bytes

The installer's only repo write is `<SourceRoot>/backups/<stamp>-prime-extension-pre-install`,
so the run used `-SourceRoot` = a **`%TEMP%` mirror** of the candidate
`brainstem/prime-extension/src` + `types` (byte copies). The digest computed
from the real candidate source was compared separately and is identical.

```powershell
# 1. seed the disposable destination with the CURRENT production extension bytes
Copy-Item -Recurse -Force "$env:USERPROFILE\.omp\agent\extensions\second-brain" "<tmp>/extensions/second-brain"
# 2. install (settings file supplied only to exercise the settings-backup path)
powershell -NoProfile -ExecutionPolicy Bypass -File "<candidate>\scripts\install-prime-extension.ps1" `
  -ExtensionsDir "<tmp>/extensions" -SettingsFile "<tmp>/settings.json" -SourceRoot "<tmp>/candidate-mirror"
# 3. roll back with the backup the installer produced
powershell -NoProfile -ExecutionPolicy Bypass -File "<candidate>\scripts\uninstall-prime-extension.ps1" `
  -ExtensionsDir "<tmp>/extensions" -SourceRoot "<tmp>/candidate-mirror" -BackupDir "<installer 'Pre-install backup:' path>"
```

| Check | Result |
| --- | --- |
| seed (production bytes) | 26 files, `6688f073…`, `index.ts 64676a40…` |
| install exit | 0 |
| installer stdout | `File count: 17`, `Manifest SHA-256: ce7fefa86ad89a607dc29ad244eedfcf588a563335f79bb73ea90b1666544421` |
| installed tree | 17 files, `ce7fefa8…`, `index.ts 10a8662f…`; **equals** the digest computed from the real candidate source |
| installer pre-install backup | 26 files, `6688f073…`, `index.ts 64676a40…`, `backup_matches_seed: true`, settings backup present, `install.json` `schema_version 1` |
| uninstall exit | 0 |
| restored tree | 26 files, `6688f073…`, `index.ts 64676a40…`, `restored_matches_production_seed: true` |

Raw transcript: `%TEMP%/m00-activation-prep/rehearsal/installer-rehearsal.json`.

## 4. Rollback runbook

Stop or restart OMP at every step that touches the loaded extension; a running
process keeps the module it already imported.

### 4.0 Freeze the rollback baseline (before activating)

```powershell
$BrainHome = "C:\Users\assas\Documents\The-Second-Brain"
$Ext  = Join-Path $env:USERPROFILE ".omp\agent\extensions\second-brain"

# a) coherent DB backup with the PRODUCTION runtime (records its own hash in manifest.json)
& "$BrainHome\.venv\Scripts\python.exe" -m second_brain --home $BrainHome backup --note "pre-M00-activation <UTC>"

# b) out-of-band copy of today's extension bytes (independent of the installer's own backup)
Copy-Item -Recurse -Force $Ext "$env:TEMP\m00-preactivation-extension-second-brain"
```

Expected baseline: 26 files, manifest `6688f07343ce3f02d44f2567359d28a52ff0a387d6237f3bde556e75e52ed2d3`,
`index.ts` `64676a40d33ea7a644bd955f8aace7256d3c751cd0acd427b3fe9e78e0f04d55`.

### 4.1 Extension rollback

Preferred — the installer-owned backup (the path the installer printed as
`Pre-install backup:`, by default `<SourceRoot>\backups\<stamp>-prime-extension-pre-install`):

```powershell
$Ext = Join-Path $env:USERPROFILE ".omp\agent\extensions"
powershell -NoProfile -ExecutionPolicy Bypass -File "<candidate>\scripts\uninstall-prime-extension.ps1" `
  -ExtensionsDir $Ext -BackupDir "<installer Pre-install backup path>"
```

The uninstaller refuses if the backup's `install.json` target does not match the
destination, or if the backup contents do not match its own manifest; it stages,
verifies, then swaps (rehearsed: R9).

Fallback — restore the §4.0 copy by hand (with OMP stopped):

```powershell
$live = Join-Path $env:USERPROFILE ".omp\agent\extensions\second-brain"
if (Test-Path $live) { Remove-Item -Recurse -Force $live }
Copy-Item -Recurse -Force "$env:TEMP\m00-preactivation-extension-second-brain" $live
```

**Do not** point this fallback at
`%USERPROFILE%\.omp\disabled-extensions\second-brain-pre-removal-20260923`: that
is the **pre-hotfix original** (`index.ts 0412eac3…`), not what production runs
today. Restoring it would additionally restore
`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` for native `task` calls
(see `outputs/reports/omp-native-recovery-20260923/RECOVERY.md`).

### 4.2 DB rollback

```powershell
$BrainHome = "C:\Users\assas\Documents\The-Second-Brain"
# production runtime, restoring a pre-activation backup taken by §4.0
& "$BrainHome\.venv\Scripts\python.exe" -m second_brain --home $BrainHome restore "<backup dir>"
```

* This **discards every write after the backup point** (rehearsed restore is
  byte-exact against the backup manifest).
* **Is it required?** Rehearsal R8 says no for basic operation: the production
  build read *and* wrote the schema-28 DB with rc 0 and `integrity ok`, so the
  old runtime works against a migrated DB. Roll the DB back only if you want the
  pre-activation *data* state. If you leave it migrated, be aware that the old
  build re-exposes the 19 stored `VERIFIED` / 10 `project_rule` rows as
  authority and can mint new ones.
* Never copy a live DB with a raw file copy — the `-wal` sidecar makes it
  incoherent. Use `backup`/`restore` or the sqlite backup API.

### 4.3 Python runtime rollback

| Activation route | Rollback |
| --- | --- |
| `SECOND_BRAIN_PYTHON` pointed at the candidate venv | remove/blank that user env var — the extension and the Claude/Codex launchers fall back to `<home>\.venv\Scripts\python.exe` |
| canonical venv re-pointed (`uv pip install -e <candidate> --python <home>\.venv\Scripts\python.exe`) | re-point it back: `uv pip install -e "C:\Users\assas\Documents\The-Second-Brain\.worktrees\qualified-v2" --python "C:\Users\assas\Documents\The-Second-Brain\.venv\Scripts\python.exe"` (uv 0.12.17 is installed) |

Note: the **Antigravity** hook launcher hardcodes `<home>\.venv\Scripts\python.exe`
and ignores `SECOND_BRAIN_PYTHON`; it follows only the venv's editable target.

### 4.4 Verification after rollback

```powershell
# a) interpreter -> source tree
& "C:\Users\assas\Documents\The-Second-Brain\.venv\Scripts\python.exe" -c "import second_brain,sys;print(second_brain.__file__, sys.executable)"
# expected: ...\.worktrees\qualified-v2\src\second_brain\__init__.py
& "C:\Users\assas\Documents\The-Second-Brain\.worktrees\m00.3-producer-guard\.venv\Scripts\python.exe" -c "import second_brain,sys;print(second_brain.__file__, sys.executable)"
# expected: ...\.worktrees\m00.3-producer-guard\src\second_brain\__init__.py

# b) extension tree digest
$Root = Join-Path $env:USERPROFILE ".omp\agent\extensions\second-brain"
$Manifest = @(Get-ChildItem -Path $Root -File -Recurse | Sort-Object FullName | ForEach-Object {
  $rel = $_.FullName.Substring($Root.Length).TrimStart("\","/").Replace("\","/")
  "$rel`t$((Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLowerInvariant())" })
$sha = [Security.Cryptography.SHA256]::Create()
$digest = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($Manifest -join "`n"))))).Replace("-","").ToLowerInvariant()
"files=$($Manifest.Count) manifest=$digest index.ts=$((Get-FileHash -Algorithm SHA256 -Path (Join-Path $Root 'index.ts')).Hash.ToLowerInvariant())"

# c) DB read-only check (schema_version + counts + integrity)
<py> check-db.py "<home>/db/brain.sqlite" post-rollback
```

Expected values:

| State | files | manifest | `index.ts` |
| --- | --- | --- | --- |
| production today (= rollback target) | 26 | `6688f073…` | `64676a40…` |
| candidate (activated) | 17 | `ce7fefa8…` | `10a8662f…` |
| pre-hotfix original (only on request) | 26 | `33e7c72c…` | `0412eac3…` |

After a rollback the DB is expected at `schema_version 24`
(**if** you also restored the backup) or `28` (if you left it migrated) with
`memories ≥ 116`, `integrity ok`.

### 4.5 The activation itself (for reference; not executed)

**Superseded by [`ACTIVATION-CARD.md`](ACTIVATION-CARD.md)**, which is the
authoritative order. Re-point the runtime *before* `init`: only the release
code carries migrations 25–28.

```powershell
# 1. freeze (4.0), with no OMP sessions running
# 2. extension
powershell -NoProfile -ExecutionPolicy Bypass -File "<candidate>\scripts\install-prime-extension.ps1" -SourceRoot "<candidate>"
#    (optional) -SettingsFile <path> to have OMP settings copied into the backup; settings are never modified
# 3. database
& "<runtime python>" -m second_brain --home "C:\Users\assas\Documents\The-Second-Brain" init
#    -> "Database ready: … (applied migrations [25, 26, 27, 28])"
# 4. runtime switch: re-point the canonical venv editable install at the release worktree.
#    SECOND_BRAIN_PYTHON alone is NOT sufficient (driver correction; see ACTIVATION-CARD.md)
# 5. verify: doctor (expect 0 failed), extension digest = ce7fefa8…, schema_version = 28
# 6. restart OMP (a running process keeps the old module)
```

## 5. What could not be determined

1. **Byte-stability of the canonical DB at activation time** — the live DB
   changed bytes four times in ten minutes (§0). The rehearsal migrated a
   point-in-time copy; a real activation must re-take the backup and hash.
2. **Python route — decided by the driver after this record:** re-point the
   canonical venv. `SECOND_BRAIN_PYTHON` alone would leave the Antigravity hook
   and `brainctl` on `qualified-v2`, and R8 shows that old runtime still trusts
   and mints VERIFIED against the shared, migrated DB. Neither route was
   executed against production. The driver rehearsed the editable re-point in
   a throwaway venv (see ACTIVATION-CARD.md).
3. **This rehearsal started no OMP session.** Correction by the driver: this
   does not reopen `M00-NATIVE-ORCH-01`. The same candidate extension bytes
   (`brainstem/prime-extension/src` and `types` are unchanged from `7ce548c` to
   `749e9cd`) were already run in real OMP via `-e` against disposable homes:
   `../native-noninterference-20260923.json` and
   `../memory-realpath-20260923.json`. What remains unexecuted is the
   *installed* extension against the *canonical* home, which is activation
   step 6.
4. **Long-horizon decay behaviour** of the 10 legacy elevated rows (loss of the
   protected-memory exemption) — asserted in the authority-closure record, not
   executed here.
5. **Project-wide gates** (full pytest, ruff, pyright, tsc, vitest) — owned by
   the main agent's validation; this record only contains the scoped proofs above.

## 6. Reproduce

Scratch scripts (kept out of the repo, in `%TEMP%/m00-activation-prep/`):
`ext-manifest.ps1`, `db-inventory.py`, `db-extras.py`, `s1-copy.py`,
`s2-migrate.py`, `s3-behaviour.sh`, `s4-installer-rehearsal.ps1`, `check-db.py`,
plus `rehearsal/installer-rehearsal.json` and the three DB copies
(`rehearsal/pre`, `rehearsal/home/db`, `rehearsal/restore-home/db`).
