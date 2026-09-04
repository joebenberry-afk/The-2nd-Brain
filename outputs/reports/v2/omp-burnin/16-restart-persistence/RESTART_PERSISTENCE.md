# Phase 16 — OMP Restart Persistence

## Architecture note

This harness has no persistent OMP daemon shared across sessions — every
`omp --print` invocation is a genuinely independent OS process with no
shared in-memory state (confirmed throughout this entire campaign: 40+
separate `omp` invocations, none sharing a process). This makes "restart"
the DEFAULT condition for every test in this campaign, not a special case
to construct — but this phase still performs the plan's exact clean and
unclean sequences explicitly.

## Clean shutdown -> restart -> retrieve

1. `omp` session A: clean single-turn session, exits normally.
2. `.venv/Scripts/python.exe -m second_brain memory add "P16_RESTART_SENTINEL"
   "...DELTA_ninety_seven..." --grade TESTED` + `memory curate --status current`
   — canonical persistence verified via `db/brain.sqlite` checksum change.
3. Brand-new `omp` process (`/tmp/omp-p16-session-b`, fresh session dir, no
   relation to session A) asked "What is the P16_RESTART_SENTINEL value?":
   > "P16_RESTART_SENTINEL = **DELTA_ninety_seven** — Source:
   > `memory/semantic/mem-38d87196587e.md` (confirmed in repo, matches the
   > injected memory packet — no conflicting repo evidence found)."

Retrieval succeeded from a process that never existed when the memory was
written — durable state, not stale in-memory carryover (there is no
in-memory carryover possible in this architecture to begin with).

## Unclean/interrupted termination

Launched a real `omp` process performing: (1) `second_brain memory add
"P16_INTERRUPTED_SENTINEL_TWO"`, then (2) `sleep 60`. After confirming the
memory write had already landed on disk (`memory/semantic/mem-74dda20ea9e8.md`
present) but while the process was still alive inside the `sleep 60` window
(~20s in, 40s remaining), killed the **entire process tree** abruptly:
```
taskkill /F /T /PID 34396
SUCCESS: PID 26532 (child of 34396) terminated.
SUCCESS: PID 54060 (child of 34396) terminated.
SUCCESS: PID 34396 (child of 53932) terminated.
```
Post-kill verification:
- `PRAGMA integrity_check` on `db/brain.sqlite` -> `ok`.
- `memory/semantic/mem-74dda20ea9e8.md` intact, correct frontmatter and body.
- Process tree confirmed fully gone (`tasklist` no longer lists the PID).
- A subsequent fresh `omp` session (`/tmp/omp-p16-session-c`) correctly
  retrieved: "P16_INTERRUPTED_SENTINEL_TWO = EPSILON_eighty_eight (per brain
  memory mem-74dda20ea9e8@1)."

The write that completed **before** the kill survived intact and remained
correctly retrievable; the abrupt kill of the surrounding process caused no
database corruption and no stale-state confusion for the next session.

## Gate 16

**PASS.** Durable Second Brain state (memory records, `db/brain.sqlite`)
survives both a clean process exit and an abrupt mid-flight kill of the
OMP process tree; a fresh session never depends on — and cannot depend on,
by this architecture's own design — any prior process's in-memory state.
