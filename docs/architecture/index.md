# Architecture (Stage 0 Bootstrap)

The Second Brain OS is a self-hosting, stdlib-only Python control layer plus a
measurement-only TypeScript Prime extension. A canonical home root
(`SECOND_BRAIN_HOME`, else `%USERPROFILE%\Documents\The-Second-Brain`) is laid
out by `paths.py` and bootstrapped by PowerShell shims that sanitize a
known-bad `PYTHONHOME`. A SQLite control DB (WAL, foreign keys, ordered
idempotent migrations) backs the project registry and will back later memory
phases; backup/restore snapshots the DB and canonical directories with sha256
manifests and move-aside safety. On top sit the working set (capsule,
requirement + read ledgers), the deterministic JIT context compiler, the
content-addressed RTD artifact store with pure distillers, the isolated Scout
explorer, and the `brainctl` CLI that dispatches to all of them. The Prime
extension records telemetry JSONL (schema v2) with strict privacy and zero
behavior mutation; Phase 5 RTD is currently shadow-only. The authoritative,
living component map for the build itself is
`projects/second-brain/architecture.md`; these docs are the durable Stage-0
record per v4.2 plan §95.1.

## Component map

| Component | Files | Doc | Phase status |
|---|---|---|---|
| Paths & bootstrap & shims | `src/second_brain/paths.py`, `scripts/bootstrap.ps1`, `brainctl.cmd`, `scripts/doctor.ps1` | [brain-paths-bootstrap](components/brain-paths-bootstrap.md) | 1 complete |
| DB & migrations | `src/second_brain/db.py`, `src/second_brain/migrations/*.sql` | [db-migrations](components/db-migrations.md) | 1 complete |
| Project registry & attach | `src/second_brain/registry.py` | [project-registry-attach](components/project-registry-attach.md) | 1+3 complete |
| Backup/restore | `src/second_brain/backup.py` | [backup-restore](components/backup-restore.md) | 1 complete |
| Doctor | `src/second_brain/doctor.py` | [doctor](components/doctor.md) | 1 complete |
| Telemetry/observability | `src/second_brain/telemetry.py`, `brainstem/prime-extension/src/*.ts` | [telemetry-observability](components/telemetry-observability.md) | 2 complete |
| Artifacts/RTD | `src/second_brain/artifacts.py`, `brainstem/prime-extension/src/rtd.ts` | [artifacts-rtd](components/artifacts-rtd.md) | 5 in progress (shadow) |
| Working set | `src/second_brain/working_set.py` | [working-set](components/working-set.md) | 4 complete |
| JIT context | `src/second_brain/jit.py` | [jit-context](components/jit-context.md) | 4 complete |
| Scout | `src/second_brain/scout.py` | [scout](components/scout.md) | 6 implemented; live experiment pending |
| brainctl CLI | `src/second_brain/cli.py` | [brainctl-cli](components/brainctl-cli.md) | 1-6 wired |

Phase status per `projects/second-brain/current-state.md`: Phases 0-4
complete and independently verified; Phase 5 shadow-only in progress;
Phase 6 Python side implemented, parent runs the baseline-vs-scout gate.
