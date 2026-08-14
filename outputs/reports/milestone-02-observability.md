# Milestone 02 — Observability (Phase 2)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_1_OneShot_Implementation_Plan.md`
Prior gate: milestone-01 (Foundation) — complete.

## What changed

A measurement-only Prime Agent extension now observes all 10 assumed lifecycle
events (plus `session_compact`) and appends privacy-preserving JSONL telemetry
(schema v2) to `<brain>/telemetry/agent-performance/`. Zero context mutation,
zero auto cleanup, zero skill routing. Python aggregation (`brainctl telemetry
report|validate`) and PowerShell install/uninstall complete the loop.

### Exact files

- `brainstem/prime-extension/` — TypeScript extension (worker-built, parent-integrated):
  `src/{index,config,sensors,storage}.ts`, `types/prime.d.ts` (hand-written
  ambient types), `package.json`, `tsconfig.json`, `eslint.config.mjs`,
  `README.md`, `tests/{sensors,storage,config}.test.ts`,
  `tests/integration/run-integration.sh`
- `brainstem/telemetry/SCHEMA.md` — authoritative record schema v2 + gate decisions
- `src/second_brain/telemetry.py` — report/validate aggregation
- `src/second_brain/cli.py` — `telemetry report|validate` subcommands; `--home`
  accepted before/after subcommands (verifier finding)
- `tests/test_telemetry.py` — 7 tests
- `scripts/install-prime-extension.ps1`, `scripts/uninstall-prime-extension.ps1`
- `brainstem/tests/install-prime-extension.Tests.ps1` — Pester suite (5 tests)
- `outputs/plans/phase2-observability-checklist.md`, `phase2-baseline-tasks.md`
- `outputs/reports/milestone-02-observability.md` (this file)

### Installed state (user-config mutation, recorded)

- Extension installed to `~/.prime/agent/extensions/second-brain/` (auto-discovered
  by future Prime sessions). Pre-install backup:
  `backups/20260814-010252-804-prime-extension-pre-install/`.
- Rollback: `scripts/uninstall-prime-extension.ps1` (restores previous dir) or
  `SECOND_BRAIN_OBSERVABILITY=off`. No settings.json edited.

## Requirement-to-evidence (Phase 2 acceptance, plan §98)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Telemetry accurate | Real prime-agent integration (worker + parent re-run): enabled run produced exactly one JSONL whose session stem matches the real session file; kinds session_start..session_shutdown all present; disabled run wrote nothing. Live baseline: 3 real tasks -> 3 files/46 records, `telemetry validate` 0 issues; ground-truth tool events (ipython x10) match the tasks |
| 2 | Overhead low | 3x identical runs ext-ON vs ext-OFF: median 11.54s vs 11.75s (delta -0.21s, noise). Writes are fire-and-forget promise-chain appends; only the terminal shutdown record is a sync write (see deviation 2) |
| 3 | No behavior changes | Handlers never return values; tool_call never mutates input; try/catch everywhere; unit tests assert record-only outputs; identical prompt ON/OFF produced identical "ok" outputs (6 runs) |
| 4 | Collects session/model/tools/files/tokens/context/env/commands/tests/children | Schema v2 covers: session+model+cwd (session_start), tool calls/results incl. bash command text (≤500 chars), token/context usage (turn_end), compactions. Children = separate sessions (counted). File-level ledger deferred to Phase 4; full env snapshot deferred to Phase 8 (recorded) |
| 5 | No context mutation / no auto cleanup / no auto routing | Design + code review + tests; no handler returns a context patch |
| 6 | Real workload baseline | 3 real flash-model tasks (file-ops+test, search+read, git inspection), all rc 0 with correct results; timings 24.6/15.3/15.4s; telemetry analyzed via brainctl |
| 7 | Python aggregation | 7 new tests; live validate: 6 files, 67 records, 0 issues |
| 8 | Install/uninstall safety | Pester 5/5: fresh install, idempotent re-run with backup of previous target, uninstall restores previous, missing-source exit 2 |
| 9 | Validation loops | ruff/pyright/pytest green (56 tests); tsc/eslint/vitest green (38); real Prime integration green (re-run by parent) |
| 10 | Milestone report + independent verification + commit | this report; verification via retained independent reviewer; git commits below |

## Commands / checks actually run

```text
(TS) npx tsc --noEmit            -> 0 errors        (worker + parent)
(TS) npx eslint .                 -> 0 errors        (worker + parent)
(TS) npx vitest run               -> 38 passed       (worker + parent)
(TS) bash tests/integration/run-integration.sh       -> ALL CHECKS PASSED (worker + parent re-run)
(Py) ruff check / format --check  -> clean
(Py) pyright src tests            -> 0 errors
(Py) pytest -q                    -> 54 passed
(PS) Invoke-Pester install-prime-extension.Tests.ps1 -> 5/5
brainctl telemetry validate       -> 6 files, 67 records, 0 issues (live data)
brainctl telemetry report         -> 6 sessions aggregated (live data)
3x baseline tasks + 6x overhead runs (deepseek-v4-flash, real prime-agent)
```

## Metrics

- Extension: 4 source modules, 38 unit tests, ~zero wall-time overhead (measured).
- Live telemetry: 6 real sessions, 67 records, 0 validation issues, 0 extension
  errors, 0 failed tool results; max context 1.1%; kinds distribution in report.
- Baseline task times: 24.6s / 15.3s / 15.4s (flash model, print mode).
- Python suite: 54 tests. Pester: 5. TS: 38 + 2-run integration.

## Deviations from the specification

1. **Hand-written ambient types** (`types/prime.d.ts`) instead of importing
   `@earendil-works/pi-coding-agent`: local Prime is v0.7.2, unpublished on npm
   (latest 0.84.1 — drift risk). Types cover exactly the used surface; the real
   integration test guards runtime drift. (plan §5 assumed SDK types)
2. **`session_shutdown` uses one synchronous final write** (`appendFinal`):
   Prime's supervisor `process.exit()` races async fire-and-forget appends and
   drops the terminal record (verified in Prime source). One sync append at
   session end; nothing else blocks.
3. **Integration runs use a dedicated `--daemon-socket` per run**: Prime routes
   print-mode runs through a daemon that pins only its own client env vars; a
   shared daemon would write telemetry to the real brain home and break the
   disabled-run assertion (verified empirically).
4. **Session stem sanitized** to `[A-Za-z0-9._-]` (no path escape); anonymous
   `anon-*` ids for `--no-session` runs.
5. **Production env note**: `SECOND_BRAIN_HOME` must be set before prime-agent
   starts (daemon env inheritance) — documented in extension README + SCHEMA.md.
6. **gitignore anchor**: root `/telemetry/` only; canonical schema docs under
   `brainstem/telemetry/` are tracked.

## Known risks / limitations (recorded, not hidden)

- Token numbers come from `ctx.getContextUsage()`; when the runtime reports
  null, `used` is null (best-effort).
- File-level read ledger, environment snapshot (branch/HEAD/dirty), RepoWise
  freshness, and parent/child session linkage are deferred to Phases 3/4/8.
- The extension measures sessions of ANY prime-agent run on this machine once
  auto-discovered (by design); disable via env var or uninstall script.
- No RepoWise index exists yet (recon: none usable on this machine) — nothing
  to measure until Phase 3 initializes one.

## Rollback

- `powershell -ExecutionPolicy Bypass -File scripts\uninstall-prime-extension.ps1`
  (restores the pre-install directory from
  `backups/20260814-010252-804-prime-extension-pre-install/`).
- Or set `SECOND_BRAIN_OBSERVABILITY=off` before starting prime-agent.
- Telemetry data is derived: delete `telemetry/agent-performance/*.jsonl`.
- Git: revert the Phase 2 commits (`3d6d388`, `dc0e49d`-partial).

## Next gate

**Phase 3 — Project Integration** (plan §99): `brainctl project add` full
integration (`.brain/project.toml` write-back, minimal AGENTS marker block with
content preservation + rollback), project Brain directory + current-state +
lexicon seed, RepoWise detection and (first) index init. Blocked on nothing.


## Independent verification reconciliation (post-gate)

Retained independent reviewer verdict: **PASS-WITH-FINDINGS** (report:
`state/recon/phase2-independent-verification.md`). All findings reconciled:

1. **MAJOR — collect-list gap vs §98 (accepted deferral, explicit).** The three
   formal acceptance bullets (accurate / low overhead / no behavior change)
   pass. Schema v2 covers: session, model, cwd, tool events (names/ids/sizes/
   bash commands), tokens/context usage, compactions, extension errors, and
   sessions (children appear as separate sessions). The following §98 items are
   **explicitly deferred with owner phases**: per-file read ledger -> Phase 4;
   environment snapshot (branch/HEAD/dirty/worktrees) -> Phase 8; RepoWise
   freshness -> Phase 3/6 (no index exists on this machine yet); test-command
   classification -> derived later from bash records when tools use bash;
   parent/child session linkage -> Phase 8 (harness API research needed).
2. **MINOR — installer missed `types/`** (sibling of `src/`): fixed in
   `scripts/install-prime-extension.ps1` (copies `types/*.d.ts`); Pester
   fixture now mirrors the real layout. Harmless at runtime (type-only imports
   are erased), but installs are now faithful mirrors.
3. **MINOR — no wiring-level unit tests for `safeHandler`**: follow-up Vitest
   tests added by the retained TS worker covering void-return, input
   non-mutation, and throw-swallowing invariants.
4. **NIT — test count corrected** to 54 (reviewer's independent collect).
5. **NIT — extension README install steps aligned** with the canonical PS
   installer (dev-only npm usage now clearly separated).
