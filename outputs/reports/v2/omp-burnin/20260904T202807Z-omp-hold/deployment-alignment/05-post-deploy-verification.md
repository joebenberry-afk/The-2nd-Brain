# Deployment Alignment — Post-Deployment Verification

## Installer invocation

```text
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-prime-extension.ps1 \
  -SourceRoot "C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot"
```

## Installer output

```text
Source repository: C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot
Source commit: da37094f3114098072610fa9464ec6cca880f23f
Target: C:\Users\assas\.prime\agent\extensions\second-brain
File count: 24
Manifest SHA-256: f16a4e35edbf04550a9b2c164b7d92a65275e6471e72798c6ee101e9d4b29cff
Pre-install backup: C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\backups\20260904-195341-363-prime-extension-pre-install
```

The installer's own pre-install backup mechanism produced a second,
independent backup in addition to the manual backup captured in
`02-backup-manifest.md`. Both preserve the original pre-deployment bytes.

## Post-deployment file-by-file comparison

- Candidate file count: 24
- Deployed file count: 24
- Files only in candidate: none
- Files only in deployed: none
- **Differing files: 0**
- Identical files: 24

## Verdict

**PASS** — candidate source == deployed extension. 0 differing files, 0
missing required files, 0 unexpected files. Deployment corresponds exactly
to source commit `da37094f3114098072610fa9464ec6cca880f23f`, which is
byte-identical in `brainstem/prime-extension/src` and `types` to the runtime
qualification ancestor (`86585e1`) and the runtime/package candidate
snapshot (`0ec276e`).
