# Milestone 03 — Project Integration (Phase 3)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_1_OneShot_Implementation_Plan.md`
Prior gate: milestone-02 (Observability) — complete.

## What changed

`brainctl project add` is now a full one-command attach: registry row, Brain
project directory (existing), `.brain/project.toml` write-back (never
overwrites a user's manifest), a minimal fenced AGENTS.md marker block (user
content preserved byte-for-byte), and RepoWise detection in `project status`.
Rollback: `project detach` (removes our marker + Brain-managed manifest,
deactivates row, restores AGENTS.md exactly) and `project remove [--purge]`.

### Exact files

- `src/second_brain/registry.py` — attach/detach/remove, manifest writer,
  fenced marker logic, RepoWise detection
- `src/second_brain/cli.py` — `project detach|remove`, `--no-marker/--no-manifest`
- `tests/test_attach.py` — 13 tests (attach, idempotency, preservation,
  byte-exact detach restoration, manifest ownership, deactivation, removal)
- `tests/test_cli.py` — updated attach assertions
- `README.md`, `CHANGELOG.md`
- `outputs/reports/milestone-03-project-integration.md` (this file)

## Requirement-to-evidence (Phase 3 acceptance, plan §99)

| # | Requirement | Evidence |
|---|---|---|
| 1 | New repo attaches in one command | Live demo on scratch git repo: `brainctl project add <repo> --name Phase3Demo` -> rc 0, manifest + marker written, status correct |
| 2 | Existing AGENTS content preserved | pytest byte-exact assertions; live demo verified original bytes intact; detach restores file byte-for-byte (incl. trailing newline semantics) |
| 3 | Rollback works | `project detach` live demo: marker removed, managed manifest removed, user AGENTS.md byte-identical, row deactivated; `project remove --purge` removes row + brain dir |
| 4 | .brain/project.toml | plan §85 minimum fields written; user's existing manifest is NEVER overwritten (id wins, content left alone) |
| 5 | Project Brain directory + current-state + lexicon seed | created by templates at attach (overview/current-state/architecture/lexicon/decisions/known-issues/knowledge-gaps/simplification-debt/rejected-findings/roadmap/references) |
| 6 | RepoWise detection | `project status` reports repowise_cli / repowise_index / policy; live: cli=True, index=False |

## Commands / checks actually run

```text
ruff check src tests            -> clean
ruff format --check             -> clean
pyright src tests               -> 0 errors
pytest -q                       -> 69 passed
live demo: attach / status / detach / remove on a scratch git repo -> all green
```

## Deviations

1. **RepoWise index creation deferred.** Plan §99 lists "RepoWise detection";
   initializing an index (`repowise init`) on a user repo is deferred until a
   phase actually consumes RepoWise (Phase 6 Scout). Detection is live in
   status. Recon shows zero usable indexes exist on this machine.
2. **`[tools]` manifest omits `sz_tool`.** The plan's example manifest lists
   `sz_tool = "auto"` (SZ-modding-specific). Generic manifests carry only
   `repowise`/`ast_grep`; projects may add `sz_tool` themselves.
3. **Marker-only AGENTS.md deletion.** If an AGENTS.md consisted solely of our
   marker, detach deletes the (now empty) file. An empty file carries no user
   content; non-empty files are restored byte-exactly.
4. **Deactivated rows persist** until `project remove`; re-attach reactivates
   the same id (identity is stable).

## Known risks

- Attach writes into the target repo's working tree (`.brain/`, `AGENTS.md`);
  it never runs `git add/commit` in user repos — the user commits the
  integration themselves.
- A repo marker written for a DIFFERENT project id is left untouched (we
  never rewrite another project's fence).

## Rollback

- `brainctl project detach <key>` (repo-side) then `project remove <key> [--purge]`
  (registry-side). Or revert this milestone's Git commit.

## Next gate

**Phase 4 — Working Set / JIT Context** (plan §100): Active State Capsule,
Requirement Ledger, JIT Context Compiler, Context Capsule, read ledger —
advisory/shadow only, no aggressive pruning.
