# Phase 17-21 — Installer Rollback Byte-Exact Proof

## Rollback invocation (default path, no override — proves the uninstaller default fix too)

```text
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/uninstall-prime-extension.ps1 -SourceRoot "<worktree>"
```

Output:

```text
Removed C:\Users\assas\.omp\agent\extensions\second-brain
Restored previous extension from C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\backups\20260904-214010-140-prime-extension-pre-install\extensions\second-brain
```

The uninstaller resolved `ExtensionsDir` to `~/.omp/agent/extensions` with
**zero** explicit override, and restored from the installer's own
auto-created pre-install backup (created during the
`08-deploy-verification.md` deploy step) — end-to-end proof of
`P1-OMP-INSTALLER-DEFAULT` on the uninstall path as well as install.

## Byte-exact verification against the pre-repair manifest

Compared the restored `~/.omp/agent/extensions/second-brain` file set
against the pre-repair manifest recorded in
`07-pre-deploy-backup-manifest.md` (captured independently, before any
installer activity in this repair):

- Restored file count: 24 — expected: 24
- SHA-256 mismatches: **0**

**PASS** — the uninstaller's rollback reproduces the exact pre-repair
deployed bytes, byte-for-byte, including `index.ts`
(`7129831de5fde5c5036078b7fef13b79b80273e722c0afa2f958ceeba320686a`) and
`types/prime.d.ts`
(`5337f269578dc7736f54065b2aaa0672b542c267816a6aafd05b8d7480cb8bb7`) — the
exact two files this repair's worker-result fix changed.

## Candidate redeployed after the rollback proof

The rollback above was a proof-of-capability, not the intended final
deployed state. Re-ran the (default-path) installer immediately afterward:

```text
Source commit: 7cbc3ba06ff36230eb58db2554848ec254b7cf13
Target: C:\Users\assas\.omp\agent\extensions\second-brain
File count: 24
Manifest SHA-256: c5aa134ea5987576d1554cb8fea32c62752f33ec938154a95138907faab03882
```

Manifest SHA-256 matches the original `08-deploy-verification.md` deployment
exactly (`c5aa134ea5987576d1554cb8fea32c62752f33ec938154a95138907faab03882`)
— the repaired P1 candidate is the final deployed state at
`~/.omp/agent/extensions/second-brain` after this proof.
