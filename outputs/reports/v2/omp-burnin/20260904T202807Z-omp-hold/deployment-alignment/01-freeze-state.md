# Deployment Alignment — Pre-Deployment Freeze

Recorded at `2026-09-04T23:50:54Z`, before any deployed-extension modification.

## Candidate identity

- Branch: `brain/v2-omp-qualification`
- Local HEAD: `da37094f3114098072610fa9464ec6cca880f23f`
- Remote HEAD (`origin/brain/v2-omp-qualification`): `da37094f3114098072610fa9464ec6cca880f23f`
- `git status --short`: clean (no output)
- Runtime qualification ancestor: `86585e114115bc43bf932145e716f2ed4d3dd30e`
- Runtime/package candidate snapshot: `0ec276e15f109a146199cd8b48d1e3d68cedfb54`
- Candidate worktree: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot`

## Environment

- `SECOND_BRAIN_HOME` (intended): `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot`
- `SECOND_BRAIN_PYTHON` (intended): `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\.venv\Scripts\python.exe`
- OMP executable: `C:\Users\assas\.bun\bin\omp.exe`
- OMP version: `omp/18.1.10`

## Build/runtime identity (candidate source, before deployment change)

```text
package_version: 2.0.0-rc.1
git_sha: da37094f3114098072610fa9464ec6cca880f23f
dirty: False
db_schema_version: 21
adapter_build_fingerprint: 56b61076903f681215426ae38d6ff47225739283bff731d85db1c71e25d81f68
qualification_baseline_sha: 4af64affdf4f1ec07b9483b67f440394d2853b32
qualification_baseline_current: False
```

## Deployed extension state (before change)

Path: `C:\Users\assas\.prime\agent\extensions\second-brain`

Contains 24 files (`*.ts` + `types/prime.d.ts`), previously found to differ
from the candidate source across 15 files (see
`../GITHUB_SYNC_AUDIT.md` history and the prior-turn comparison). This
directory has not yet been touched by this deployment-alignment pass.

## Stale runtime-ready status file (not yet refreshed)

`state/extension-runtime-ready.json`:

```json
{
  "resolved_at": "2026-09-04T19:49:25.373Z",
  "home": "C:\\Users\\assas\\Documents\\The-Second-Brain\\.worktrees\\v2-one-shot",
  "runtime_python": "C:\\Users\\assas\\Documents\\The-Second-Brain\\.worktrees\\v2-one-shot\\.venv\\Scripts\\python.exe",
  "brain_version": "2.0.0-rc.1",
  "identity_hash": "a590f1614c1b3b03ed7b485bc8ca8071c9718fe8902cfd71662ecbfb7634c72a"
}
```

This file is written once per extension factory lifecycle (frozen-per-lifecycle
model). It predates the HTTP 429 provider boundary and will only be refreshed
by a fresh OMP `/reload` or process restart after the extension is
resynchronized.

## Managed processes (hub)

No hub-managed long-running OMP host process is currently registered; the
`hub ps` snapshot shows only unrelated exited jobs from prior campaigns
(`p16-kill-test`, `p9-kill-test`, `hermes-handoff-probe`, `p35-*`, `p34-*`),
all already exited. No stale OMP host process was found to terminate via
`hub`.
