# Final P1 Repair — Starting State

## Worktree identity

Confirmed via `git worktree list`: this worktree
(`C:/Users/assas/Documents/The-Second-Brain/.worktrees/v2-one-shot`) is
checked out at the intended qualification lineage, distinct from the parent
checkout (`C:/Users/assas/Documents/The-Second-Brain`, branch
`brain/v1-rc4-prime-074-compat`, unrelated).

## Starting point

- Prior branch: `brain/v2-omp-qualification`
- Prior HEAD (documentation HEAD from the qualification pass):
  `0b2aaf9788c8df6f174bd738377333f10364fd20`
- `git status --short` at start: clean (no output)
- Repair branch created: `brain/v2-omp-final-p1-repair`, based exactly on
  `0b2aaf9788c8df6f174bd738377333f10364fd20` (no unrelated history merged)
- Repair branch HEAD immediately after creation:
  `0b2aaf9788c8df6f174bd738377333f10364fd20` (identical — branch point only)

## Preserved evidence (not rewritten)

All prior qualification evidence under
`outputs/reports/v2/omp-burnin/20260904T202807Z-omp-hold/` (including
`deployment-alignment/`) is left untouched. This repair pass creates a new,
separate `final-p1-repair/` evidence directory alongside it.

## Scope

Two P1 defects only:

1. `P1-OMP-WORKER-AUTODELIVERY` — auto-delivered worker completions
   (`message_end`/`customType:"async-result"`) are invisible to
   `omp_worker_child_result` telemetry.
2. `P1-OMP-INSTALLER-DEFAULT` — `install-prime-extension.ps1` /
   `uninstall-prime-extension.ps1` default to `~/.prime/agent/extensions`,
   which this OMP build does not auto-discover; the real default must be
   `~/.omp/agent/extensions`.

No broad re-implementation. The 146-session Phase 22 burn-in evidence from
the qualification pass remains valid production coverage and is not
repeated.
