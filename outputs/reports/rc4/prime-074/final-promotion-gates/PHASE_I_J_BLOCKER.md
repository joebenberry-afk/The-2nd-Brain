# PHASE_I_J_BLOCKER.md

## Status: Phase I/J blocked on a NEW, distinct environmental limitation (not the known
## reprovision collision)

Attempting to build the isolated driver+daemon rig required for the literal
"driver -> spawn one real RLM child -> child executes a trivial task -> result returned
-> child exits cleanly" test (Phase I on patched isolated v0.7.3, Phase J on patched
isolated v0.7.4) surfaced a different, previously-undocumented obstacle:

**Every attempt to start a brand-new Prime daemon on a fresh, never-before-used
`--daemon-socket` named pipe fails with `EACCES: operation not permitted, listen
'\\.\pipe\<name>'`, at the raw `net.Server.listen()` call inside Prime's own
`daemon-mode.ts` / `daemon-supervisor.ts`.**

## What was ruled out (systematically, with direct evidence)

- Not a name-collision or stale-process issue: multiple distinct, never-before-used
  pipe names all failed identically; no stale process was found holding any of them
  (`Get-CimInstance Win32_Process` clean before each attempt).
- Not specific to the isolated `throwaway-073` worktree or a corrupted isolated agent
  dir: reproduced identically from a brand-new, never-used agent dir
  (`.prime-eperm-repro/freshagent-073`), AND reproduced identically running directly
  against the LIVE install's own source (`C:\Tools\prime-agent`, read-only invocation,
  a fresh custom socket name, live's actual already-running daemon on
  `\\.\pipe\prime-agent-daemon` left completely untouched throughout).
- Not specific to git-bash/MSYS: reproduced identically via native PowerShell
  invocation and via direct `node --require ... --import ...` invocation (bypassing the
  `tsx.cmd` batch wrapper entirely).
- Not an environment-variable artifact (NO_COLOR/FORCE_COLOR/etc.): reproduced
  identically with a fully stripped, minimal `env -i` environment.
- Not a genuine OS-level named-pipe restriction in general: a plain, minimal
  `node -e "net.createServer().listen('\\.\pipe\\...')"` run directly, and the
  identical pattern run through the exact same tsx loader Prime uses, both succeed
  immediately (`LISTENING OK`) for multiple distinct fresh pipe names.
- Checked Windows Defender's operational event log around the failure timestamps: only
  routine health-report events, no explicit block/detection event logged for this
  activity (inconclusive either way; many EDR/sandbox layers do not log to that
  channel).

## Working hypothesis (not yet independently confirmed)

This session's own kernel is itself a Prime Agent daemon **worker** process
(`PRIME_AGENT_INTERNAL_DAEMON_WORKER=1`, confirmed in `STARTING_STATE.md`). The
consistent, universal, worktree-independent, version-independent failure -- combined
with a plain equivalent script succeeding from the exact same process family/loader --
is most consistent with a deliberate sandbox/security boundary already built into the
Prime kernel/worker execution environment itself: code running inside a Prime kernel
session is allowed to use its own already-established daemon connection, but is not
permitted to stand up brand-new listening named-pipe servers (a sensible safety
boundary, since that is exactly the primitive needed to run an independent background
service from inside an AI-controlled execution context). This was not independently
proven (would require testing from a non-sandboxed shell outside any Prime session),
but it is the best-supported explanation given the evidence above, and it is clearly a
**different phenomenon from the RLM_ROOT_CAUSE.md defect** (that defect is a real
Node/Windows file-locking race reachable via `bootstrap-cli.ts`'s `ensureKernelPython()`
with no daemon/pipe involved at all; this new blocker is specific to opening a new
listening daemon socket and never reaches kernel-bootstrap code at all).

## What this means for Phase I/J

- The literal "spin up an isolated driver+daemon, have the model decide to spawn an RLM
  child, observe the round trip" test cannot be completed for either version from
  *inside this sandboxed session* via a brand-new custom `--daemon-socket`.
- This is **not** the known reprovision collision from RLM_ROOT_CAUSE.md, so per the
  user's own instruction ("stop and report" applies specifically to failures caused by
  the known collision) this is being reported rather than worked around with the
  unqualified third patch (which would not fix this anyway -- this blocker never
  reaches the kernel-bootstrap code path at all).
- Two partial, real, non-workaround alternatives are available and are being used
  instead, clearly labeled as such:
  1. **v0.7.3**: this session's own live daemon connection (already established,
     already permitted, not a new pipe, not a restart/modification of the live
     install) can be used to perform real, fresh RLM child spawns against the actual
     live v0.7.3 (patched) install -- the same code under test in RLM_073_PASS.txt.
  2. **v0.7.4**: no equivalent already-established live connection exists (only 0.7.3
     is live). The strongest available fallback is the already-validated
     `bootstrap-cli.ts`-level steady-state proof (RLM_EPERM_REPRO.md /
     RLM_ENVIRONMENT_MATRIX.md, cases 4/1: fresh bootstrap succeeds cleanly for both
     versions with no collision present), which exercises the literal
     `ensureKernelPython()` function every real RLM child spawn depends on, but stops
     short of a full daemon-mediated model-driven round trip.
