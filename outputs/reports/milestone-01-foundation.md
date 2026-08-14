# Milestone 01 — Foundation (Phase 0 + Phase 1)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_1_OneShot_Implementation_Plan.md` (authoritative)
Session: SECOND-BRAIN-V4-1-BUILD (Prime Agent)

## What changed

Phases 0 and 1 implemented from an empty repository. The Brain now exists at its
canonical location with a Git repo, protected constitution, policy config,
stdlib-only Python control package (`brainctl`), an idempotent SQLite migration
framework, a project registry, and verified backup/restore.

### Exact files

Canonical (new):
- `README.md`, `AGENTS.md`, `INDEX.md`, `CHANGELOG.md`, `VERSION`, `.gitignore`
- `The_Second_Brain_OS_V4_Definitive_Implementation_Plan.md` (committed as history)
- `The_Second_Brain_OS_V4_1_OneShot_Implementation_Plan.md` (authoritative spec)
- `constitution/{constitution,truth-precedence,learning-boundaries,security-boundaries,retention-policy,change-control}.md`
- `config/{brain,context,learning,retrieval,verification,environment,skills,sleep}.toml`
- `lexicon/global.md`
- `templates/project/{project.toml,overview,current-state,architecture,lexicon,decisions,known-issues,knowledge-gaps,simplification-debt,rejected-findings,roadmap,references}.md`
- `src/second_brain/{__init__,__main__,paths,db,registry,backup,doctor,cli,errors}.py`
- `src/second_brain/migrations/0001_init.sql` (projects table, plan §10 fields)
- `src/second_brain/defaults/{VERSION,config/*,templates/*}` (seed data for fresh init)
- `scripts/brainctl.py`, `scripts/bootstrap.ps1`, `scripts/doctor.ps1`, `brainctl.cmd`
- `tests/{conftest,test_paths,test_db,test_registry,test_backup,test_doctor,test_cli,test_migrations_property}.py`
- `outputs/reports/milestone-01-foundation.md` (this file)

Derived/runtime (not in Git): `db/brain.sqlite`, `backups/backup-*`,
`state/recon/{prime-extension-api,repowise}.md` (recon reports).

### User configuration mutations (recorded)

1. `SECOND_BRAIN_HOME` persisted at **User scope** =
   `C:\Users\assas\Documents\The-Second-Brain` — authorized by plan §96
   (persist only after bootstrap/doctor passes; both passed before persisting).
   Rollback: `[Environment]::SetEnvironmentVariable('SECOND_BRAIN_HOME',$null,'User')`.
2. Nothing else. No global AGENTS.md touched (Phase 3 concern). No other repo
   modified. The only externally created data: a backup directory inside the Brain.

## Requirement-to-evidence (Phase 1 acceptance, plan §97)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Fresh clone/init works | `pytest tests/test_cli.py::test_init_doctor_status_flow` green; live `brainctl init` on this repo; init seeds VERSION+config+templates from package defaults on empty dirs |
| 2 | doctor passes | Live: 16/16 PASS (rc 0). Includes layout, TOML parse, env-pollution warn, WAL+FK, migrations current, tools |
| 3 | DB migrations idempotent | `test_migrate_idempotent`; Hypothesis `test_any_prefix_then_remainder_equals_full_apply` (8 examples, prefixes 0..3); `db.migrate` returns [] on rerun |
| 4 | Backup restore works | `test_backup_roundtrip_into_empty_home`, `test_restore_refuses_without_force`, `test_restore_force_moves_current_aside`, `test_corrupt_db_hash_refused`, Hypothesis `test_backup_restore_preserves_rows` (5 examples); live backup SHA-256 verified |
| 5 | Root initialized / Git clean | git repo on `main`; `git status` contains only canonical files; derived dirs excluded via .gitignore |
| 6 | One project registered | `brainctl project add` registered "The Second Brain" itself (id `e8d8d8e1…`); `projects/<id>/` populated from templates |
| 7 | No user config lost | Only mutation listed above; init refuses non-Brain non-empty dirs without --force (STOP safety) |

## Commands / checks actually run

```text
uv venv .venv --python 3.13                       (Python 3.13.7, uv 0.11.6)
uv pip install -e . ; uv pip install pytest pytest-cov hypothesis ruff pyright
.venv python -m ruff check src tests              -> 0 errors
.venv python -m ruff format --check src tests scripts -> formatted
.venv python -m pyright src tests                 -> 0 errors, 0 warnings
.venv python -m pytest -q                         -> 49 passed (incl. 13 property examples)
.venv python -m pytest --cov=second_brain         -> 72% line coverage (cli.py exercised
                                                    via subprocess tests, hence 0% in-proc)
brainctl init (live)                              -> rc 0, applied migration 0001
brainctl doctor (live)                            -> rc 0, 16/16 PASS
brainctl project add <this repo>                  -> registered
brainctl backup --note "milestone-01 foundation gate" -> created; manifest SHA-256 matches file
scripts/bootstrap.ps1 (live, 2nd run idempotent)  -> rc 0 (uv pip path after pip-less venv fix)
brainctl.cmd status with polluted PYTHONHOME      -> rc 0 (shim sanitizes env)
powershell parser check on both .ps1 scripts      -> OK
git status / git diff --check                     -> clean, only canonical files
```

## Metrics

- Python package: 9 modules, 635 statements, stdlib-only runtime dependencies
  (dev-only: pytest, pytest-cov, hypothesis, ruff, pyright).
- Tests: 49 passing. Coverage (in-process): paths 100%, registry 95%,
  backup 92%, db 92%, doctor 88%.
- DB: schema version 1, WAL, FK enforced, synchronous=NORMAL, busy_timeout 5s.
- Live doctor: 16 checks, 0 failed, 0 warnings.
- Performance (Phase 1 budget check, plan §122): `brainctl status` < 1s; backup
  of this tiny DB completes in ms; no measurable overhead to worry about yet.

## Tool installation / availability inventory (plan §5.4)

| Tool | Available | Version | Path | Required now | Action |
|---|---|---|---|---|---|
| python (venv) | yes | 3.13.7 | `.venv\Scripts\python.exe` | yes | none |
| uv | yes | 0.11.6 | `C:\Users\assas\.local\bin\uv.EXE` | yes | none |
| git | yes | 2.55.0 | `C:\Program Files\Git\mingw64\bin\git.EXE` | yes | none |
| ruff | yes | 0.16.3 | `.venv\Scripts\ruff.exe` | yes | none |
| pyright | yes | 1.1.411 | `.venv\Scripts\pyright.exe` | yes | none |
| pytest / pytest-cov / hypothesis | yes | 9.1.1 / 7.15.4 / 6.165.6 | `.venv\Scripts` | yes | none |
| rg | yes | 15.2.0 | Codex bin | yes | none |
| ast-grep | yes | 0.45.1 | Python313 Scripts | yes | none |
| repowise | yes | 0.41.0 | Python313 Scripts | later (Phase 2/3) | `repowise init` when a RepoWise milestone needs it; index is a derived artifact |
| node / npm | yes | v25.7.0 / 11.19.0 | `C:\Program Files\nodejs` | Phase 2 | none |
| PowerShell | yes | 5.1.26100.9168 | system | yes | none |
| sqlite3 (Python module) | yes | 3.50.4 | venv | yes | none |
| sqlite3.exe CLI | no | — | — | optional | not installed; Python module suffices |
| pester | no | — | — | optional (Phase 3+) | deferred: bootstrap is one script; adapters not built yet |

## Deviations from the specification

1. **`.brain/project.toml` write-back deferred to Phase 3.** Plan §10 lists the
   repo-side manifest; Phase 1 scopes only the registry. `brainctl project add`
   currently reads an existing `.brain/project.toml` id (identity priority 1)
   but does not write one. Recorded so Phase 3 completes it.
2. **RepoWise index not created in Phase 1.** Recon (state/recon/repowise.md):
   installed but zero usable indexes on this machine. RepoWise is first
   required by later phases; init deferred until needed (avoids an unused
   derived index). `.repowise/` is gitignored.
3. **`SECOND_BRAIN_HOME` persisted earlier than "implementation stable".**
   Plan §96 allows persistence once bootstrap/doctor pass; the Foundation gate
   is the first milestone where both passed, so it was persisted here.
4. **Backup restore "existing data" check ignores empty skeleton dirs.**
   Spec requires refusing unsafe overwrite; an empty `config/` contains no user
   data, so overlay is safe. Real (non-empty) targets still refuse without
   --force, and --force moves the current state aside, never deletes it.
5. **Env gotcha (machine-specific):** user-level `PYTHONHOME`/`UV_INTERNAL__PYTHONHOME`
   point at a corrupted uv CPython 3.11 tree (SRE module mismatch). All shims
   (`brainctl.cmd`, bootstrap.ps1, doctor.ps1, scripts/brainctl.py) sanitize it;
   doctor reports it as a warning. Documented in `AGENTS.md`.

## Known risks

- **Fresh-init config drift:** `src/second_brain/defaults/config/*` duplicates
  `config/*`. Edits must stay in sync (cheap; doctor warns on parse failures,
  not drift). Consider a `brainctl config check-defaults` in a later phase if
  drift becomes real.
- **Windows TOML path escaping:** project manifests store repo paths with
  forward slashes (valid on Windows; DB holds the true normalized path).
- **Doctor tool checks are warnings, not failures** (correct for degradation
  model §132).
- RepoWise presence is detected but freshness/indexing is a later phase.

## Rollback

- Git: this milestone is the first commit on `main`; `git reset --hard` to
  `main~1` removes it (plan document remains on disk).
- User env var: see user-configuration mutation #1 above.
- DB/config: `brainctl restore <backup dir>` (live backup
  `backups/backup-20260814-043717-369761`) or `--force` variant which moves
  current state aside.
- Brainstem is not installed anywhere yet (no adapters), so nothing to disable.

## Next gate

**Phase 2 — Observability** (plan §98): Prime Agent measurement-only extension
(`brainstem/prime-extension/`), zero context mutation, low overhead, then a
baseline real-workload run. Blocked on nothing: Prime Agent v0.7.2 extension
API verified by recon (state/recon/prime-extension-api.md) — all 10 assumed
lifecycle events exist via `pi.on(event, handler)`; install path
`~/.prime/agent/extensions/*.ts`.
