# Changelog

Format: Keep a Changelog-ish. Entries reference milestone reports under
`outputs/reports/`.

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
