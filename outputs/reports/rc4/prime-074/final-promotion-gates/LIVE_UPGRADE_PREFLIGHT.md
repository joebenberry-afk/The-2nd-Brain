# LIVE_UPGRADE_PREFLIGHT.md

## Pre-upgrade identity (captured immediately before any live mutation)

```
git rev-parse HEAD:            61131b2d195ba7a67a4ce8ac60bb10cecae07b67
git describe --tags --always:  v0.7.3-dirty
git status --short:
 M packages/coding-agent/src/core/kernel/bootstrap.ts
 M packages/coding-agent/src/core/session-lease.ts
?? .repowise/
?? Prime_Agent_Codex_Fix_Status.md
?? outputs/
?? prime-agent.sh.pre-tsconfig-fix.bak

Target v0.7.4 tag resolves to: af0b8e00b9f704e834787fd321065ca78281f2aa
(matches the exact commit qualified throughout this entire campaign, cross-checked
against CANDIDATE_IDENTITY.txt from the prior external review and every isolated
prime-074 worktree operation in this pass)

Patch hashes (pre-upgrade, live):
  bootstrap.ts:      f0ccf80567a35b51baed769d79df00a70cf444400f5e5251a75037c498d44c23
  session-lease.ts:  b128dd81f703d65fd1b324d600e1937e9378919dfe5f0725e676cdb155998ea3
(identical to every prior recording of these hashes across this entire campaign --
FINAL_VERDICT.md, REVIEW_VERDICT.md, and this pass's own throwaway-073/prime-074
worktree copies -- zero drift.)
```

## CRITICAL FINDING: this session is itself the live daemon's active worker

```
$ prime-agent list   (run against the LIVE daemon, C:\Tools\prime-agent)
name  id            status    age  model                      messages  clients
      b0d00e4ed1e7  working   1s   anthropic/claude-sonnet-5  560       1

PRIME_AGENT_INTERNAL_DAEMON_WORKER_ACTIVE_SESSION_ID (this session's own env) =
  b0d00e4ed1e7
```

Session `b0d00e4ed1e7` -- reported as `working` (i.e. actively mid-turn) by the live
daemon's own session list -- IS this exact session. This is not a coincidence or a
false positive: the env var this session was launched with matches the session ID
exactly.

This means the Phase M pre-flight requirement "confirm no important active Prime
child/session is mid-write" cannot be satisfied by stopping the daemon from *within*
this session: this session is that active session. Issuing a daemon-stop command from
this kernel would very likely terminate this exact kernel process (a child of the
worker process that the stop targets) before the remaining Phase M/N steps (patch
application confirmation, daemon restart, post-upgrade smoke gate) could be completed
or reported from this same session.

See the parent turn's message to the user for the resulting safe-execution plan
(external, non-sandboxed shutdown/promotion/restart, matching the Phase I/J external-
daemon pattern already proven necessary and safe in this campaign, followed by
post-upgrade smoke verification from whatever session context is available after
restart).
