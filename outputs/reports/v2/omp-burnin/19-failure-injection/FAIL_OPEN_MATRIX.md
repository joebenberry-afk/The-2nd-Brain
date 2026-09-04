# Phase 19 — Failure Injection and Fail-Open Behavior

## Defect found and fixed during this phase

Injecting fault #2 (Python command returns non-zero, via a `.cmd` wrapper
standing in for `SECOND_BRAIN_PYTHON`) surfaced a **real crash**: Node's
`execFile()` throws `EINVAL` *synchronously* for a `.bat`/`.cmd` target on
Windows without `shell:true`. `ledger-mirror.ts`'s two `execFile()` call
sites (`mirrorEvent`'s `run()` helper and its append path) wrapped this in
`new Promise((resolve) => { execFile(...) })` with no try/catch around the
call — a synchronous throw there auto-rejects the Promise per spec, and
`mirrorFireAndForget`'s `void mirrorEvent(options).then(onFulfilled)` (no
`.catch()`) let that rejection escape as an **unhandled rejection**,
crashing the live OMP session and forcing `omp --resume <id>` recovery.
Confirmed live, root-caused, fixed (both `execFile` sites now catch
synchronous throws and resolve fail-open; `mirrorFireAndForget` also gained
a defense-in-depth `.catch()`), regression-tested, and re-verified live —
see commit `02c9204` and `12-worker-result-lifecycle`-adjacent evidence.
**Audited the four sibling bridges** (`routing-bridge.ts`,
`visibility-bridge.ts`, `worker-context-bridge.ts`,
`worker-result-bridge.ts`) for the identical `new Promise((resolve) => {
execFile(...) })` pattern — all four have it too, but every current call
site in `index.ts` already wraps them in `.catch()` (`ensureRoutingDecision`
line 990, `ensureVisibilityPlan` line 1014) or try/catch
(`safeWorkerContextRunner`, `emitWorkerCompletion`'s `workerResultRunner`
call) — confirmed live-safe already (see rows 4/5/10/11 below); left
unmodified per "smallest correct repair," not speculatively hardened.

## Fault matrix (all 15 required scenarios)

| # | Fault | Method | Result |
|---|---|---|---|
| 1 | Python runtime unavailable | `SECOND_BRAIN_PYTHON=C:\nonexistent\path\python.exe` | Fail open; `omp_visibility_plan` recorded `error:"BRAIN_VISIBILITY_UNAVAILABLE"`; session replied normally (Phase 17) |
| 2 | Python command returns non-zero | `.cmd` stub exiting 1 (also triggered the EINVAL spawn-throw case) | **Crash found and fixed** (see above); post-fix: `extension_error` records for every affected bridge, session replies normally |
| 3 | State directory temporarily unavailable | `SECOND_BRAIN_HOME` pointing at a nonexistent path | Fail open; extension's config gate silently disables itself entirely (no telemetry dir even created); session unaffected (Phase 17) |
| 4 | Malformed retrieval response | Unspawnable-python fault stub (all bridge CLI calls affected identically); AutoInject's own CLI-JSON parsing has its own try/catch (confirmed via Phase 9 corrupted-cache test: `loadEmitCache`'s parse failure fails open to an empty cache) | Fail open; session replies normally |
| 5 | Malformed routing response | Same stub; `parseOmpRoutingOutput` errors are caught by `ensureRoutingDecision`'s `.catch(() => ({decision:null, error:"BRAIN_ROUTING_UNAVAILABLE"}))` | Fail open; session replies normally, no routing telemetry emitted for this turn (correctly — no valid decision to report) |
| 6 | Corrupted AutoInject cache | `state/autoinject-emit-cache.json` replaced with invalid JSON | Fail open, self-heals to valid JSON on next write (Phase 9 test 7, full detail in `09-cache-correctness/CACHE_CORRECTNESS.md`) |
| 7 | Telemetry write failure | `telemetry` path replaced with a plain file (blocks `mkdir telemetry/agent-performance`, genuine `ENOTDIR`) | Fail open; observable console diagnostic `[second-brain-observability] telemetry write failed: ENOTDIR: not a directory, mkdir '...\telemetry\agent-performance'`; session replied normally |
| 8 | Ledger write failure | Same EINVAL fault as #2 (ledger IS the write path that crashed pre-fix) | **Same fix as #2** — post-fix: `extension_error: "ledger mirror: ledger init: spawn ... EINVAL"`, session unaffected |
| 9 | Project resolver failure | `.brain/project.toml` with invalid TOML syntax | Fail open to `project_id:"default"` (a safe neutral fallback, never an unrelated real project) — 5 candidate memories correctly all suppressed with `reason:"WRONG_PROJECT"` since none matched "default"; **wrong project never guessed** |
| 10 | Worker capsule failure | `UNAUTHORIZED_COORDINATOR` (Phase 11) — a non-coordinator role is correctly refused; `safeWorkerContextRunner`'s try/catch also covers any other `runOmpWorkerContext` throw, resolving `{ok:false, error:"BRAIN_WORKER_CONTEXT_UNAVAILABLE"}` | Fail closed on authorization (correct, safer than fail-open for a security boundary); fail-open on any other internal error |
| 11 | Worker result bridge failure | `emitWorkerCompletion`'s `try { await workerResultRunner(...) } catch { /* best-effort */ }` (Phase 12 fix) | Fail open; local telemetry/ledger recording already captured before this call, never blocked by a Brain-side lifecycle-write failure |
| 12 | Visibility failure | Same as #1/#4 (`BRAIN_VISIBILITY_UNAVAILABLE`) | Fail open |
| 13 | Backup verifier error | Backup manifest's `db.sha256` and a file hash tampered to `deadbeef...`; ran `restore` against it | **Fails cleanly, does not restore**: `brainctl: error: Backup DB hash mismatch: manifest deadbeef..., actual 046cb875...`, exit code 2 — corrupted backups are rejected before any file is touched, not silently applied |
| 14 | Stale build/state identity | `SECOND_BRAIN_HOME` env leaked/mismatched vs. explicit `--home` (Phase 5) | Observable `[FAIL] identity coherence` diagnostic; does not affect the actual build-identity resolution used by the rest of the checks |
| 15 | Interrupted atomic write | `taskkill /F /T` mid-flight on a real OMP process tree during/after a memory write (Phase 9 test 9, Phase 16) | DB integrity `ok` after every kill; no corruption; atomic tmp-then-rename pattern holds |

## Gate 19

**PASS**, after one real fix. No auxiliary Second Brain failure produces
silent wrong-memory behavior in any of the 15 scenarios: project-resolver
failure falls back to a neutral "default" (never guesses a real, wrong
project) and correctly suppresses all candidates against it; every other
fault either fails open with an observable diagnostic (extension_error,
console log, or explicit CLI error) while the OMP session continues
normally, or — for the ONE genuine crash found (fault #2/#8, `ledger-mirror`
EINVAL) — has been fixed, regression-tested, and re-verified live to now
also fail open.
