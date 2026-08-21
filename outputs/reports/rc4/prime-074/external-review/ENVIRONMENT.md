# ENVIRONMENT.md

## Resolved paths (discovered, not assumed)

- Live Prime root: C:\Tools\prime-agent (confirmed via
  PRIME_AGENT_LAUNCHER_PATH env var and direct directory inspection)
- Candidate v0.7.4 worktree: C:\Users\assas\.prime\agent\
  prime-upgrade-worktrees\prime-074 (isolated, detached, both local
  patches applied)
- Second Brain repository root: C:\Users\assas\Documents\
  The-Second-Brain
- Live agent/config dir: C:\Users\assas\.prime\agent (env
  PRIME_AGENT_CODING_AGENT_DIR)
- Candidate isolated agent dir (from the prior qualification pass, still
  present, reused): C:\Users\assas\.prime-074-compat\agent
- Live daemon socket: \\.\pipe\prime-agent-daemon (default)
- Throwaway v0.7.3 worktree (for A/B + rollback proof, reused from the
  prior pass): C:\Users\assas\.prime-074-compat\throwaway-073
- Python env for Brain tests: C:\Users\assas\Documents\
  The-Second-Brain\.venv\Scripts\python.exe (Python 3.13.7)
- Node/npm for Brain TS tests: Node v26.7.0, npm 11.19.0
- Telemetry: C:\Users\assas\Documents\The-Second-Brain\telemetry\
  agent-performance\<session-id>.jsonl
- Per-session ledger: C:\Users\assas\Documents\The-Second-Brain\
  state\sessions\<sha256(session-id)>\ledger.sqlite

## Infrastructure anomaly discovered during this review pass (important --
affects the scope actually completed fresh in this pass)

While attempting to spawn a fresh RLM sub-agent to carry out the bulk of
this external review (the normal delegation pattern used throughout this
whole RC4 campaign), THREE consecutive spawn attempts all failed
identically, before any of the child's own task code could run:

```
Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink
'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe'
```

Investigation (read-only, by the reviewing session itself, which
retained a working kernel throughout):
- The reviewing session's OWN kernel remained healthy and functional the
  entire time (proof: this evidence file, and every other file in this
  review, was produced by that same kernel).
- `C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe`
  itself is unmodified (mtime 2026-08-14, unchanged) -- the live shared
  kernel-venv's actual interpreter binary was NOT corrupted or altered by
  this review or by the failed spawn attempts.
- Exactly one process (the reviewing session's own kernel,
  `ipykernel_launcher`) was found holding that exact file open at the
  time of the failures.
- The kernel-venv directory (`C:\Users\assas\.prime\agent\
  kernel-venv\Scripts\`) contains ONLY `python.exe` -- no `pyvenv.cfg`,
  no `Lib/`, no bootstrap-version marker file -- consistent with a
  minimal/shim interpreter whose "readiness" check
  (`kernelReady()`/`bootstrapVersionCurrent()` in Prime's own
  `bootstrap.ts`, read directly from the live source this pass) fails
  its version/identity check on a fresh sub-agent spawn, triggering a
  full re-provision attempt that then hits EPERM trying to unlink/replace
  the interpreter file while the reviewing session's own kernel has it
  open -- a genuine Windows file-locking race in Prime's OWN kernel
  bootstrap logic, in the LIVE 0.7.3 installation, unrelated to the
  candidate 0.7.4 code under review.

Consequence: this review pass could NOT delegate to a fresh sub-agent as
originally planned, and could NOT (within a reasonable effort budget)
re-execute a brand-new, fully-fresh live isolated-0.7.4 session (Phase E)
or a fresh full Prime-vitest A/B reproduction (Phase I) from scratch in
this specific pass -- both are expensive, multi-minute operations that
would each have required spawning additional processes under conditions
that had just demonstrated real instability. Instead, this pass performed
direct, hands-on re-verification (by the reviewing session's own working
kernel) of every cheaper, still-genuinely-load-bearing claim: candidate/
patch identity, patch apply-checks against a pristine worktree, the "zero
adapter changes" diff, BOTH full Brain regression suites (freshly
re-run, not cited), RTD artifact byte-exact recomputation, telemetry
record-count recomputation, and direct ledger queries including a
cross-session isolation check. See REVIEW_SUMMARY.md for the resulting
scope disposition and verdict.

This anomaly is itself a real, evidence-based finding: it demonstrates a
genuine, reproducible operational fragility in the CURRENT live 0.7.3
daemon's sub-agent kernel-bootstrap path under concurrent-kernel
conditions. It is not a Prime 0.7.4 compatibility finding (the failure
occurred entirely within live 0.7.3 infrastructure, before any candidate
code was ever reached), but it is directly relevant to the promotion
decision's overall risk posture -- see REVIEW_SUMMARY.md.
