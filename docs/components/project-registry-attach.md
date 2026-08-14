# Project Registry & Attach/Detach

## Purpose
Register external repos as Brain projects and attach/detach them safely (plan §10, §99, §130).

## Problem it solves
Stable project identity without trusting directory names; reversible attach/detach that never destroys user content.

## Responsibilities
- Identity priority: `.brain/project.toml` id → Git remote → repo-root path hash (`detect_explicit_id`/`detect_git_remote`/`path_hash`).
- `add_project` (idempotent row + `projects/<id>/` seeded from templates); `list_projects`/`get_project` (id, id-prefix, name)/`project_status` (incl. RepoWise CLI/index detection).
- Phase 3: `write_project_manifest` (create-only), fenced AGENTS.md marker, `attach_project`, `detach_project` (byte-exact marker removal, managed-manifest removal, row deactivation), `remove_project` (`--purge`).

## Non-responsibilities
Never overwrites a user-owned manifest; never edits AGENTS.md outside the fenced block; malformed markers left alone.

## Inputs
Repo path or key; `--name`/`--id`/`--no-marker`/`--no-manifest`.

## Outputs
Registry row; `projects/<id>/`; optional `.brain/project.toml` and AGENTS.md marker.

## State ownership
`projects` table + `projects/<id>/`; repo-side files only inside exact fenced spans.

## Invariants
Manifest > remote > path hash; re-attach idempotent; detach restores AGENTS.md byte-for-byte incl. CRLF/no-trailing-newline; manifest create-only; marker-only AGENTS.md deletable (decision #7).

## Interactions
`db` (rows), `paths`, templates; consumed by `brainctl project`, `scout.resolve_repo`, JIT project state.

## Failure behavior
Missing path/invalid manifest/missing repo → BrainError; detach is safe on no-op cases.

## Verification
`tests/test_registry.py` (8) + `tests/test_attach.py` (19): identity precedence, idempotency, byte-exact/CRLF restore, attach-detach-reattach cycles, manifest ownership, purge.

## Known limitations
Git remote detection needs git on PATH; path-hash identity moves with the repo; RepoWise detection presence-only (decision #4).

## Future extension
Phase 6+ consumes records for Scout/RepoWise index init; memory phases scope per project.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #4, #6, #7.

## Relevant tests
`tests/test_registry.py`, `tests/test_attach.py`, `tests/test_cli.py::test_project_add_list_status`.
