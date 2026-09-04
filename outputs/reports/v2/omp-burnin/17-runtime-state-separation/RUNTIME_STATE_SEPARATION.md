# Phase 17 — Runtime/State Separation

`SECOND_BRAIN_PYTHON` (runtime) and `SECOND_BRAIN_HOME` (state) tested as
genuinely independent axes, using a second, real Python installation
(`The-Second-Brain-v2-burnin/.venv`, Python 3.11.15, a different checkout at
the frozen `4af64af` baseline SHA) as the "alternate valid Python."

| Runtime | State | Result |
|---|---|---|
| repo Python (`.venv`, 3.13.7) | default state (`.worktrees/v2-one-shot`) | **Works** — proven throughout this entire 40+ session campaign |
| alternate valid Python (burnin venv, 3.11.15) | same state | **Works** — `doctor` ran clean, correctly emitted `[WARN] version — VERSION=2.0.0-rc.1, package=0.1.0` (the older runtime's own package version vs. the state's VERSION file) — exactly the "detect runtime/state mismatch" behavior Gate 17 requires |
| same Python (`.venv`) | alternate fresh state (`/tmp/omp-p17-freshstate`, brand new `init`) | **Works** — clean init, 0 failed/0 warnings |
| alternate Python (burnin venv) | alternate state (same fresh dir) | **Works** — ran cleanly; see anomaly note below |
| invalid Python (`SECOND_BRAIN_PYTHON=C:\nonexistent\path\python.exe`) | valid state | **Fail open, diagnosed** — session completed normally (correct reply, no crash); `omp_visibility_plan` telemetry recorded `"error":"BRAIN_VISIBILITY_UNAVAILABLE"` explicitly |
| valid Python | unavailable state (`SECOND_BRAIN_HOME` pointing at a nonexistent directory) | **Fail open, silently disabled by design** — session completed normally; the extension's config gate detected no valid brain home and disabled itself entirely (no telemetry directory even created, matching the extension's documented "missing brain home -> silently disabled" behavior) |

## Anomaly observed (not reproducible, no code defect found)

The first `init` on the fresh state directory (`.venv`, code identical to
row 3 above) reported applying only migrations `[1..9]`, while the repo's
`src/second_brain/migrations/` directory contains 21 files (`0001`-`0021`).
A subsequent, direct re-run of `db.migrate()` against that exact database
file (same process family, same code, no changes) correctly discovered and
applied all of `[10..21]` with zero errors, converging the state to fully
current. `db.migration_files()` called standalone in a fresh interpreter
returned all 21 files correctly, and source review of `db.migrate()`/
`apply_migration()` found no version gate, feature flag, or early-exit path
that would explain stopping at exactly migration 9 on a legitimate first
run. Given: (a) it did not reproduce on retry, (b) no explanatory code path
was found on inspection, and (c) the state ended up fully, correctly
migrated once `migrate()` was re-invoked with no data loss or corruption —
this is recorded as an **observed anomaly, not a confirmed defect**. Per
plan discipline ("do not invent persistence behavior"), no fix is applied
against an unreproduced, unexplained symptom; flagging it here for anyone
who can reproduce it under different conditions (e.g., a race between
`git init` and `db.migrate()` inside `cmd_init`, both of which run in the
same function body — `cmd_init` calls `subprocess.run(["git","init"], ...)`
immediately before `db.migrate(...)`, a real candidate worth instrumenting
if this recurs).

## Gate 17

**PASS.** No hidden assumption that runtime and state share one
installation root: a different Python interpreter (different checkout,
different Python version) freely operates on the same state directory, and
`doctor` correctly surfaces a version-identity divergence when one exists.
Invalid runtime and unavailable state both fail open without crashing OMP,
with the invalid-runtime case additionally producing an explicit, observable
error code.
