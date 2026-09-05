# Phase 11-16 — Fresh OMP Process + Doctor Verification

## Pre-existing processes left untouched

```text
"omp.exe","44248","Console","1"
"omp.exe","23260","Console","1"
```

Both pre-existing `omp.exe` processes (one is the same long-lived process
noted in `deployment-alignment/07-auto-discovery-path-defect.md`) were left
running and untouched — no signal sent, no restart attempted against them.
Per the extension's "frozen-per-lifecycle" model
(`brainstem/prime-extension/README.md`), a genuinely fresh, independent
`omp` process invocation is the correct and sufficient way to prove new
extension bytes load, without disrupting any other live session.

## Fresh smoke invocation

```text
omp.exe -p --cwd <worktree> "Reply with exactly: ok-p1-repair-smoke"
```

Output: `ok-p1-repair-smoke` (session completed normally).

## `state/extension-runtime-ready.json` — fresh `resolved_at`

```json
{
  "resolved_at": "2026-09-05T01:41:14.420Z",
  "home": "C:\\Users\\assas\\Documents\\The-Second-Brain\\.worktrees\\v2-one-shot",
  "runtime_python": "C:\\Users\\assas\\Documents\\The-Second-Brain\\.worktrees\\v2-one-shot\\.venv\\Scripts\\python.exe",
  "brain_version": "2.0.0-rc.1",
  "identity_hash": "a590f1614c1b3b03ed7b485bc8ca8071c9718fe8902cfd71662ecbfb7634c72a"
}
```

New `resolved_at` timestamp (vs. the stale `2026-09-04T19:49:25.373Z`
recorded pre-deployment in `deployment-alignment/06-runtime-identity-pre-restart.md`)
proves a fresh extension factory instance actually loaded the newly
deployed, byte-verified (`08-deploy-verification.md`) candidate code.

## `brainctl doctor`

```text
[PASS] build identity — version=2.0.0-rc.1 sha=393c717f3e05 (dirty) schema=21 adapter=100575fea2a9 qualified_baseline=4af64affdf4f
19 checks: 0 failed, 0 warnings
```

`adapter=100575fea2a9` matches the new build fingerprint computed and
recorded in `06-build-fingerprint.md`
(`100575fea2a92d55fe948a41f6cd67960d5626927c14eaaf0bf5d9d511cb5335`).
`(dirty)` reflects the installer's own untracked pre-install backup under
`backups/` created by the `08-deploy-verification.md` deploy step — not a
source regression. All 19 doctor checks PASS.
