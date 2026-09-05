# Phase 11-16 — Deploy Candidate + Byte-Exact Verification

## Installer invocation (no `-ExtensionsDir` override — proves the repaired default)

```text
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-prime-extension.ps1 -SourceRoot "<worktree>"
```

## Installer output

```text
Source repository: C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot
Source commit: 393c717f3e055a9a6eb9c18398ce858f8ce6790c
Target: C:\Users\assas\.omp\agent\extensions\second-brain
File count: 24
Manifest SHA-256: c5aa134ea5987576d1554cb8fea32c62752f33ec938154a95138907faab03882
Pre-install backup: C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\backups\20260904-214010-140-prime-extension-pre-install
Restart OMP or run /reload to load the extension.
```

The installer resolved `Target` to `~/.omp/agent/extensions/second-brain`
with **zero** explicit `-ExtensionsDir`/`-SettingsFile` — directly
demonstrating `P1-OMP-INSTALLER-DEFAULT` is fixed: the documented default
command now deploys to OMP's real auto-discovery directory.

## Post-deployment file-by-file comparison (candidate source vs. deployed bytes)

- Candidate file count (`brainstem/prime-extension/{src,types}`): 24
- Deployed file count (`~/.omp/agent/extensions/second-brain`): 24
- Files only in candidate: none
- Files only in deployed: none
- **Differing files: 0**
- Identical files: 24

**PASS** — candidate source == deployed extension, byte-for-byte (SHA-256
per file), at commit `393c717` (repair branch `brain/v2-omp-final-p1-repair`,
HEAD after the build-fingerprint commit).

## Files changed vs. the pre-deploy backup (`07-pre-deploy-backup-manifest.md`)

Exactly the 2 files this repair's worker-result fix touched, as expected:

| Path | Pre-repair SHA-256 | Deployed (post-repair) SHA-256 | Bytes before → after |
|---|---|---|---|
| `index.ts` | `7129831de5fde5c5036078b7fef13b79b80273e722c0afa2f958ceeba320686a` | `d2b44f3dbc0e1082ac6d17859953ffb36afeedd6fba92c79cb7ef2f94ffddd68` | 125590 → 129507 |
| `types/prime.d.ts` | `5337f269578dc7736f54065b2aaa0672b542c267816a6aafd05b8d7480cb8bb7` | `927f807d7cc1eb3566a54f3f28a194800f9605baec12652316b78b81fa5925f0` | 10153 → 10539 |

All other 22 files are byte-identical to the pre-deploy backup (unrelated to
either P1 fix, as expected).
