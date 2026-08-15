# Architecture (The Second Brain's own component map)

Authoritative for the build itself. Repository reality outranks this file.
Keep this current as phases land; it was created because the Brain's own
memory subsystem did not exist yet (phases 9+), and stays authoritative now
that memory subsystems are live (milestones 09/10/16).

## Components

| Component | Files | Purpose | Ownership | Invariants |
|---|---|---|---|---|
| Path resolution | src/second_brain/paths.py | canonical root via SECOND_BRAIN_HOME, else Documents default | parent (core) | never hardcode absolute paths; layout idempotent |
| SQLite + migrations | src/second_brain/db.py, migrations/*.sql | control DB, ordered idempotent migrations | parent (core) | WAL+FK+synchronous=NORMAL; per-migration atomic; schema_version authoritative |
| Registry + attach | src/second_brain/registry.py | project identity, .brain/project.toml, AGENTS marker | parent (core) | identity: manifest > remote > path hash; never overwrite user manifest; detach byte-exact |
| Backup/restore | src/second_brain/backup.py | SHA-256 manifests, move-aside safety | parent (core) | no stale -wal replay; failure rolls aside back; restore never deletes |
| Doctor | src/second_brain/doctor.py | health checks, env-pollution warnings | parent (core) | deterministic, exit 0 only when green |
| Telemetry (Py) | src/second_brain/telemetry.py | aggregate/validate JSONL v2 | parent (core) | read-only, deterministic |
| Telemetry (TS) | brainstem/prime-extension/src/* | measurement-only Prime extension | worker-built, parent-integrated | no behavior mutation; privacy (counts/sizes, bash<=500); fire-and-forget; appendFinal on shutdown |
| Bootstrap/shim | scripts/*.ps1, brainctl.cmd | env sanitization, install/uninstall | parent (core) | PYTHONHOME sanitized; pre-install backup; idempotent |
| Working Set | src/second_brain/working_set.py | capsule/requirements/read-ledger JSON | worker (repowise-recon), parent CLI | atomic writes; enum-validated; ids unique; evidence append-only |
| JIT compiler | src/second_brain/jit.py | deterministic Task Context Capsule | worker (repowise-recon) | deterministic body; Tier1/2 only; never crashes on missing inputs |

## Limitations (current)

- Memory subsystems are live: episodic (milestone-09), semantic
  (milestone-10), procedural/skills (milestone-16). This file remains the
  authoritative component map.
- Telemetry: no per-file read ledger hook yet (Phase 5 RTD); no env snapshot
  (Phase 8); RepoWise index not initialized anywhere on this machine.
- Machine gotchas: PYTHONHOME pollution (shims sanitize); npm/.cmd need
  `cmd /c`; uv venvs have no pip by default.

## Verification map

- Python: ruff + pyright + pytest (Hypothesis on migrations/attach/recovery).
- TS: tsc + eslint + vitest + real prime-agent integration (2-run enabled/disabled).
- PowerShell: parser check + Pester.
- Phase gates: milestone reports + retained independent reviewer (fresh-context,
  requirements+diffs only).
