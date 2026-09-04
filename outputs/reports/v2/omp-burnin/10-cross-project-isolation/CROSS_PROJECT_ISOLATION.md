# Phase 10 — Cross-Project Isolation

## Setup

Two independent, real git repositories with explicit `.brain/project.toml`
manifests (canonical project-identity priority 1, per `registry.detect_explicit_id`):

- `/tmp/omp-p10-alpha` — `id = "p10-project-alpha"`, sentinel memory
  `mem-8d921d1a71f0` ("OMP_ISOLATION_SENTINEL value for this project is
  ALPHA."), grade TESTED, status current.
- `/tmp/omp-p10-bravo` — `id = "p10-project-bravo"`, sentinel memory
  `mem-633f43de8534` ("...is BRAVO."), grade TESTED, status current.

Same `SECOND_BRAIN_HOME` (`.worktrees/v2-one-shot`) for both — isolation
must come from project resolution, not from separate Brain homes.

## Alternating live sessions (A -> B -> A -> B)

Each session: fresh `omp` process, fresh `--session-dir`, cwd set to the
respective repo, task: *"What is the OMP_ISOLATION_SENTINEL value for this
project?"* (same task text/hash — `1a8dc9b8a6c55040` — across all four, so
only project resolution differs).

| Session | cwd | telemetry `project_id` | `selected_ids` | Model's answer |
|---|---|---|---|---|
| A1 | `/tmp/omp-p10-alpha` | `p10-project-alpha` | `["mem-8d921d1a71f0"]` | Cites the ALPHA memory as unverified advisory; does not confirm BRAVO |
| B1 | `/tmp/omp-p10-bravo` | `p10-project-bravo` | `["mem-633f43de8534"]` | Cites BRAVO as advisory; explicitly flags it as looking like a possible injected claim, does not treat as fact |
| A2 | `/tmp/omp-p10-alpha` | `p10-project-alpha` | `["mem-8d921d1a71f0"]` | Cites ALPHA (`mem-8d921d1a71f0`) as advisory-only |
| B2 | `/tmp/omp-p10-bravo` | `p10-project-bravo` | `["mem-633f43de8534"]` | Cites BRAVO as advisory-only |

**Zero cross-contamination across all four alternating sessions** — every
`brain_packet_delivered` record's `project_id` and `selected_ids` match only
that session's own project's sentinel; the other project's sentinel never
appears in any packet. `candidate_count:3` on every session (other memories —
this campaign's earlier `second-brain`-project sentinels plus the sibling
alpha/bravo memory — were correctly considered as candidates and correctly
NOT selected for the wrong project).

Every `autoinject_shadow_decision` on all four sessions shows `cache_hit:false`
(each is a distinct fresh session id, and `session` is part of the AutoInject
emit-cache key — no accidental cross-session cache reuse either).

## Ledgers / provenance attribution

Every retrieval/delivery telemetry record above carries the correct
`project_id` field, sourced from the SAME `ledger-mirror.ts` `mirror()` call
path that writes the session ledger — telemetry and ledger attribution share
one project-resolution call, so correct telemetry `project_id` is direct
evidence of correct ledger attribution (they are not independently-computed
values that could silently diverge).

## Deferred to dedicated phases (not duplicated here)

- **Worker capsules remain project-scoped** — covered by Phase 11 (OMP
  Worker Context Capsule), which will include a cross-project angle.
- **Compaction does not import the other project's state** — covered by
  Phase 15 (Compaction Continuity).

## Exact-memory-ID lookup bypass

Not exercised: this v2 build's retrieval path (`hybrid_retrieval.py`) has no
documented explicit-memory-ID bypass distinct from normal project-scoped
retrieval in the code reviewed this campaign; no such path was found to test.

## Gate 10

**PASS.** No accidental cross-project injection occurred in any of the 4
alternating sessions — the strongest possible live evidence against the P0
release-blocker condition this gate exists to catch.
