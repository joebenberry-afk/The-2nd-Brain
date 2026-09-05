# Deployment Alignment — Candidate Extension Source Resolution

## Resolved absolute worktree path

```text
C:/Users/assas/Documents/The-Second-Brain/.worktrees/v2-one-shot
```

Confirmed via `git rev-parse --show-toplevel` from inside the worktree, and
independently via `git worktree list`, which shows this exact path checked
out at branch `brain/v2-omp-qualification` @ `da37094`.

## Distinctness from the parent checkout

`git worktree list` shows the parent checkout
(`C:/Users/assas/Documents/The-Second-Brain`) is on an unrelated branch,
`brain/v1-rc4-prime-074-compat` @ `3d4cb4c` — not the qualification branch.
Any shell whose default `SECOND_BRAIN_HOME`/cwd resolves to the parent
checkout would therefore run the wrong Brain state and the wrong extension
source. This confirms the earlier-reported risk: the deployment step must use
the explicit worktree path below, never an inherited shell default.

## Source identity

```text
git -C .worktrees/v2-one-shot rev-parse HEAD
  -> da37094f3114098072610fa9464ec6cca880f23f
git -C .worktrees/v2-one-shot status --short
  -> (clean, no output)
```

## Executable source snapshot being deployed

`HEAD` (`da37094`) contains only documentation-report commits above the
runtime/package candidate snapshot (`0ec276e15f109a146199cd8b48d1e3d68cedfb54`):

```text
git diff --name-only 0ec276e15f109a146199cd8b48d1e3d68cedfb54..HEAD \
  -- brainstem/prime-extension/src brainstem/prime-extension/types
  -> (empty — no extension source changed)

git diff --stat 0ec276e15f109a146199cd8b48d1e3d68cedfb54..HEAD
  -> 5 files changed (all under outputs/reports/v2/omp-burnin/.../*.md)
```

The extension source is also unchanged between the runtime qualification
ancestor and the package candidate snapshot:

```text
git diff --name-only 86585e114115bc43bf932145e716f2ed4d3dd30e..0ec276e15f109a146199cd8b48d1e3d68cedfb54 \
  -- brainstem/prime-extension/src brainstem/prime-extension/types
  -> (empty)
```

**Conclusion:** the extension source at the current worktree HEAD
(`da37094`) is byte-identical to the extension source at both the runtime
qualification ancestor (`86585e1`) and the runtime/package candidate
snapshot (`0ec276e`). Deploying from this worktree's
`brainstem/prime-extension/src` + `types` at the current HEAD deploys exactly
the qualified runtime/extension source — not an unrelated branch checkout,
and not a documentation-only variant with different runtime behavior.

## Deployment source paths

```text
Source (src):   C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\brainstem\prime-extension\src
Source (types): C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\brainstem\prime-extension\types
Deployed:       C:\Users\assas\.prime\agent\extensions\second-brain
```
