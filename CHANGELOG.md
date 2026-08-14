# Changelog

Format: Keep a Changelog-ish. Entries reference milestone reports under
`outputs/reports/`.

## [0.4.0] — Working Set / JIT Context (Phase 4)

- Active State Capsule, Requirement-to-Evidence Ledger (material-unverified
  completion gate), Read Ledger.
- Deterministic JIT Context Compiler -> Task Context Capsules.
- First dogfooding: the build manages its own Phase 5 task via capsule +
  requirements + read ledger + compiled capsule.
- See `outputs/reports/milestone-04-working-set-jit.md`.

## [0.3.0] — Project Integration (Phase 3)

- `brainctl project add` = full attach: `.brain/project.toml` (never overwrites
  user manifests), fenced AGENTS.md marker block (byte-exact preservation),
  RepoWise detection.
- `project detach` (rollback) + `project remove [--purge]`.
- See `outputs/reports/milestone-03-project-integration.md`.

## [0.2.0] — Observability (Phase 2)

- Prime Agent measurement extension (`brainstem/prime-extension/`): 11
  lifecycle events -> schema v2 JSONL telemetry, privacy-preserving,
  config-gated, fire-and-forget writes. Installed globally.
- `brainctl telemetry report|validate`.
- Install/uninstall PowerShell scripts + Pester suite.
- See `outputs/reports/milestone-02-observability.md`.

## [0.1.0] — Foundation (Phase 0–1)

- Initial repository: canonical layout, constitution, config defaults.
- Python package `second_brain` (stdlib-only) with `brainctl`:
  `init`, `doctor`, `status`, `project add|list|status`, `backup`, `restore`.
- SQLite migration framework (WAL, foreign keys, idempotent migrations).
- Project registry + backup/restore with verified roundtrip.
- See `outputs/reports/milestone-01-foundation.md`.
