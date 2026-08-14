# Retention Policy

## Canonical vs derived vs raw

- **Canonical** (Git-versioned, human-readable): constitution, semantic
  knowledge, decisions, project state, skills, engram definitions, high-value
  experiences, policies/config, lexicons.
- **Derived** (rebuildable, ignored by Git): SQLite indexes, FTS rows, routing
  statistics, telemetry rollups, caches, working-set state, artifact
  summaries.
- **Raw evidence** (preserved, not auto-injected): tool output, logs, test
  output, imported source, large JSON, session traces.

## Forgetting

States: `HOT → WARM → COLD → ARCHIVED`.

- Forgetting means moving out of the hot set — never destroying canonical
  evidence by default.
- Protected from decay: constitution, security rules, accepted decisions,
  critical failure immunizations, explicit user preferences, current
  invariants.

## Episodes

- Episodes are written immediately, are immutable, and are never merged
  automatically.
- Only high-value episodes become durable files (`experiences/`); the rest
  stay in the episodic vault / telemetry.

## Backups

- Before adapter or global-config changes: `backups/<timestamp>/` containing
  global AGENTS, harness settings, skill runtime dirs, Brain config, DB
  snapshot.
- `brainctl backup` snapshots the Brain itself (DB + config + constitution +
  projects) with a SHA-256-verified manifest.
- Backups are derived data: kept on disk, not in Git.
