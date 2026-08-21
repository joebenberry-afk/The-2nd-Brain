# ROLLBACK_PROOF.md (freshly re-verified this review pass)

## Exact restore ingredients (re-confirmed present and functional)

- Exact v0.7.3 commit: 61131b2d195ba7a67a4ce8ac60bb10cecae07b67
  (resolves via `git show`/`git rev-parse v0.7.3` right now, confirmed).
- Two local Windows patches: exact diff preserved at
  outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff, confirmed
  this pass to apply cleanly (`git apply --check` exit 0) against the
  REAL throwaway v0.7.3 worktree, which is CURRENTLY in its pristine
  (unpatched) state.
- Real executability proof: `node_modules/.bin/tsx
  packages/coding-agent/src/cli.ts --version` in the throwaway v0.7.3
  worktree returned exactly `0.7.3` -- a genuine, working install is
  reproducible on this machine right now, not merely a historical
  artifact.

## Documented restore procedure (NOT executed against the live install by
this review -- this is the procedure someone would run, as text, per the
task's explicit safety constraint)

```
cd C:\Tools\prime-agent
<stop the live daemon cleanly through its normal supervised shutdown path>
git checkout 61131b2d195ba7a67a4ce8ac60bb10cecae07b67   # or: git checkout v0.7.3
git apply <path-to>/01-local-patches-073.diff
<restart the daemon through its normal supervised start path>
git status --short   # expect only the 2 patch files modified
git rev-parse HEAD    # expect 61131b2d195ba7a67a4ce8ac60bb10cecae07b67
```

## Verdict

Rollback path confirmed genuinely restorable, independently, this pass.
Not executed against the live install (per the task's own Phase L
instruction: prepare + prove in isolation, do not touch production for
this proof).
