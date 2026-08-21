# LIVE_PROMOTION_CHECKPOINT.md

Written immediately before the first live-mutating command of Phase M. If this
session disappears when the live daemon is stopped, a FRESH session should read this
file first, before anything else, to resume safely without reconstructing the
investigation. Everything a fresh session needs is below or linked by exact path.

## 1. Current live v0.7.3 identity (pre-upgrade, captured this pass)

```
Path:                C:\Tools\prime-agent
git rev-parse HEAD:   61131b2d195ba7a67a4ce8ac60bb10cecae07b67
git describe --tags:  v0.7.3-dirty
git status --short:
 M packages/coding-agent/src/core/kernel/bootstrap.ts
 M packages/coding-agent/src/core/session-lease.ts
?? .repowise/
?? Prime_Agent_Codex_Fix_Status.md
?? outputs/
?? prime-agent.sh.pre-tsconfig-fix.bak

Pre-upgrade daemon status (`prime-agent status`):
socket                         pid    version  status   sessions
\\.\pipe\prime-agent-daemon *  30012  0.7.3    current  2
(worker PID 12144, socket \\.\pipe\prime-agent-worker-2245fa1c0e38-45f9cdc04667;
 this session's own worker/session)
```

## 2. Exact qualified v0.7.4 target

```
git tag v0.7.4 resolves to: af0b8e00b9f704e834787fd321065ca78281f2aa
```

Cross-checked identical, this entire campaign, in: CANDIDATE_IDENTITY.txt (prior
external review), every isolated `prime-074` worktree operation in this pass
(RLM_074_PASS.txt daemon hello: `appVersion: "0.7.4"`, `buildId: "release-0.7.4"`),
and PRIME_AB_074.txt.

## 3. The two qualified Windows patches (and ONLY these two)

```
Patch file (reusable, already verified to apply cleanly to BOTH v0.7.3 and v0.7.4
trees throughout this campaign):
  outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff

Files touched: packages/coding-agent/src/core/kernel/bootstrap.ts,
               packages/coding-agent/src/core/session-lease.ts

Post-patch hashes (identical whether applied to v0.7.3 or v0.7.4 -- confirmed by
direct `diff` between the throwaway-073 and prime-074 worktrees' patched files,
byte-identical, zero output):
  bootstrap.ts:      f0ccf80567a35b51baed769d79df00a70cf444400f5e5251a75037c498d44c23
  session-lease.ts:  b128dd81f703d65fd1b324d600e1937e9378919dfe5f0725e676cdb155998ea3
```

## 4. Candidate 3rd bootstrap patch: MUST NOT BE APPLIED

A 3rd, unqualified candidate patch was designed and validated ONLY in isolation this
pass (RLM_FIX_DIFF.txt, `.stale-<timestamp>-<pid>` rename-out-of-tree fix for the
kernel-venv rebuild race). It was deliberately never applied to either the isolated
v0.7.3 worktree, the isolated v0.7.4 worktree, or the live install. **Do not apply it
now or at any point during this promotion.** Both qualified worktrees remain, and the
live install must remain, on exactly the 2 patches in section 3 -- nothing else.

## 5. Gate result authorizing this promotion

`PRE_PROMOTION_GATE.md` (same directory): **APPROVED_FOR_LIVE_PROMOTION**, all 7
required gates PASS (RLM root cause, RLM 0.7.3 3/3, RLM 0.7.4 3/3, flaky A/B no
regression, prior review still valid, live tree untouched-until-now, rollback ready).

## 6. Rollback procedure (proven, exact)

If any Phase N post-upgrade smoke check fails, or the daemon does not come back up
correctly, execute exactly this, from an external, non-Prime-session shell:

```powershell
cd C:\Tools\prime-agent
git checkout -- packages/coding-agent/src/core/kernel/bootstrap.ts packages/coding-agent/src/core/session-lease.ts
git checkout 61131b2d195ba7a67a4ce8ac60bb10cecae07b67
git apply "C:\Users\assas\Documents\The-Second-Brain\outputs\reports\rc4\prime-074\raw\01-local-patches-073.diff"
git status --short   # expect exactly the 2 patch files modified, nothing else
git rev-parse HEAD   # expect 61131b2d195ba7a67a4ce8ac60bb10cecae07b67
```
Then restart the daemon (any client command, e.g. `status`, will auto-spawn it) and
re-verify `prime-agent status` reports version `0.7.3`. Record the result in
`ROLLBACK_LOG.md` in this same directory. This exact sequence (checkout + patch
apply + `--version` executability) was independently proven this pass and in the
prior external review (ROLLBACK_PROOF.md).

## 7. Exact point where this session is stopping

This session (`b0d00e4ed1e7`, worker PID 12144 under supervisor PID 30012, socket
`\\.\pipe\prime-agent-daemon`) will hand off the Phase M external commands to the
user now. This session's own kernel is a child of the exact daemon process tree that
Step 1 (`shutdown --force`) will stop. **This session must be assumed to terminate
the moment Step 1 succeeds.** All work up to and including PRE_PROMOTION_GATE.md is
already committed to git (`outputs/reports/rc4/prime-074/final-promotion-gates/`) as
of commit `0c31666` and earlier. Nothing beyond this checkpoint file exists only in
this session's live memory.

## 8. Instructions for a fresh session to resume Phase N

If this session disappears:

1. A fresh Prime session will start against the (by then) restarted live daemon.
2. Read this file (`LIVE_PROMOTION_CHECKPOINT.md`) first, then `PRE_PROMOTION_GATE.md`,
   then the Phase M step log the user will have pasted/confirmed (steps 1-8 below),
   to know exactly which steps completed and what the last confirmed state was.
3. Do NOT re-run Phase I, Phase J, or Phase K -- they are already complete and
   committed (RLM_073_PASS.txt, RLM_074_PASS.txt, PRIME_AB_COMPARISON.md).
4. Confirm the live daemon is actually up and reports v0.7.4 (`prime-agent status`)
   before doing anything else.
5. Proceed directly to the Phase N post-upgrade smoke checklist (section 9 below).
6. If Phase N passes, write `FINAL_VERDICT.md` with verdict
   `PRIME_0_7_4_PROMOTED`, commit, and STOP -- do not begin any further work
   (no Brain-OFF/Brain-ON economics, no new features).
7. If Phase N fails, execute the rollback (section 6), write `ROLLBACK_LOG.md` and
   `FINAL_VERDICT.md` with verdict `PRIME_0_7_4_PROMOTION_ROLLED_BACK`, commit, and
   STOP.

## 9. Phase N post-upgrade smoke checklist (to run once v0.7.4 is confirmed live)

1. **Live Prime identity** -- `prime-agent status` reports version `0.7.4`, a daemon
   PID, and `current` status; `git rev-parse HEAD` in `C:\Tools\prime-agent` equals
   `af0b8e00b9f704e834787fd321065ca78281f2aa`; `git status --short` shows only the 2
   patch files.
2. **Second Brain AutoInject** -- start a fresh session against the new live daemon
   from within the Second Brain repo/project context and confirm Brain injection
   fires as expected (matches the mechanism already proven in the prior external
   review's INTEGRATION_EVIDENCE.md).
3. **Basic Brain retrieval** -- retrieve a known-safe memory/reference and confirm a
   real, correct result.
4. **RTD minimal path** -- exercise a minimal RTD (recall/retrieve) flow and confirm
   real, non-empty, correct output.
5. **Ledger activity** -- confirm the new live session creates correct per-session
   ledger activity (direct SQL query against the session's ledger.sqlite, matching
   the method used in LEDGER_EVIDENCE.md from the prior review).
6. **Usage/cache telemetry** -- confirm telemetry records are generated for the new
   live session.
7. **Fresh RLM child spawn** -- run at least 2 real driver -> live-daemon -> child ->
   result -> clean-exit spawns against the NOW-LIVE v0.7.4 daemon (not an isolated
   worktree this time -- the actual production path), independently verified via the
   real rlm-ledger the same way Phase I/J were verified.
8. **Both Windows patch behaviors** -- confirm patch 1 (bootstrap.ts
   Scripts/python.exe path resolution) and patch 2 (session-lease.ts EPERM-as-lease-
   conflict handling) are both present and functioning (e.g. a fresh kernel spawn
   succeeds using the win32 Scripts path, and no unhandled EPERM crash occurs on a
   session-lease contention if one is naturally exercised).

## 10. Mandatory rollback conditions

Roll back immediately (do not attempt a speculative production fix) if ANY of:
- `prime-agent status` does not report version `0.7.4` within a reasonable startup
  window, or reports an error/crash loop.
- The daemon fails to start at all, or starts but immediately exits.
- AutoInject, Brain retrieval, or RTD fail outright (not "slow", but wrong/missing
  output or an exception).
- Fresh RLM child spawn fails to complete a full spawn -> result -> clean-exit cycle
  at least once after a reasonable number of attempts (compare against the 3/3
  isolated success rate already proven -- a live failure here is a release-critical
  regression, not noise).
- Either Windows patch's behavior is missing or broken (e.g. `Scripts\python.exe`
  path resolution reverts to the pre-patch `bin/python` bug, or an EPERM session-
  lease conflict now throws instead of being handled).
- Any unexplained discrepancy versus the isolated v0.7.4 qualification evidence
  (RLM_074_PASS.txt, PRIME_AB_074.txt) that cannot be immediately, confidently
  attributed to a known, already-documented, non-blocking cause (e.g. the fsync-on-
  directory EPERM class, which is expected and non-fatal).

## Discovery-context discrepancy: root cause confirmed and documented

External PowerShell's `os.homedir()` resolution did not match this session's live
`PRIME_AGENT_CODING_AGENT_DIR` (`C:\Users\assas\.prime\agent`), causing
`findAllTrackedWorkers()` (the only functional Windows discovery path, since
`scanListeningDaemons()`/`scanSocketDir()` are hardcoded to return `[]` on win32 --
see `packages/coding-agent/src/cli/daemon-ps.ts` lines ~177-242) to look in the wrong
directory and find nothing. Explicitly setting `$env:PRIME_AGENT_CODING_AGENT_DIR`
before invoking any `prime-agent` discovery/lifecycle command resolves it -- confirmed
live: external PowerShell with the explicit env var now sees socket
`\\.\pipe\prime-agent-daemon`, PID 30012, version 0.7.3, status current, 2 sessions,
matching this session's own view exactly.

This is a real, additional Windows-specific finding in Prime's own daemon discovery
code (a genuine second gap distinct from RLM_ROOT_CAUSE.md), worth carrying forward as
a known operational note for any future external/scripted daemon lifecycle command on
this machine: always pass `PRIME_AGENT_CODING_AGENT_DIR` explicitly.
