---
date: 2026-09-24
type: report
authority: proposed
status: awaiting owner approval (decision D8)
scope: v3-currentness-sweep
supersedes: none-additive
superseded-by: none
promoted:
---

# V3 currentness sweep — proposed changes to the 20 `current` memories

Source: the live corpus (116 memories) converted with `brain convert` into a scratch home; no
canonical memory has been changed. The 91 `candidate` records stay candidates (never pushed,
visible to `brain q` with their label). Applying this list is an owner decision (D8): once
approved, the converted records are written to `records/` and these actions run through
`brain supersede` / `brain retire`, which keep full as-of history (a retired record still
answers `brain q --as-of <earlier date>` and `--history`).

## Retire (Brain orchestration was removed on 2026-09-23)

| Record | Title | Action |
|---|---|---|
| `mem-174b3f5abbba` | Driver may execute trivial deterministic work | `retire`, effective 2026-09-23, reason "Brain orchestration removed (orchestrator-removal gate)" |
| `mem-f745bcb2eff2` | Adaptive fan-out replaces the hard 2-worker cap | same |

## Review — phase checkpoints that read as current state

| Record | Title | Proposal |
|---|---|---|
| `mem-3d8ffbd6538d` | P0-P2 closure checkpoint (2026-08-24) | retire as historical (superseded by the M00 activation) |
| `mem-7ee245204a5e` | Hermes persistent three-bot runtime gate checkpoint (2026-08-21) | retire as historical |
| `mem-99df66e3c8f6` | P3 Antigravity repair state: READY_FOR_REAL_CAMPAIGN (2026-08-16) | owner states the current Antigravity status; retire unless still true |
| `mem-bb634354ec69` | Antigravity completion claim invalidated; repair required (2026-08-16) | same |

## Keep, with a type (improves the brief's sections)

| Record | Title | Type |
|---|---|---|
| `mem-b67de5057f76` | PYTHONHOME pollution breaks bare python launches | `gotcha`, trigger error `SRE module mismatch` (becomes an error-time correction) |
| `mem-a8d221e64549` | Migration ordering | `procedure` |
| `mem-79d7c4fd9876` | Antigravity hook contract (from installed app bundles) | `locator` |
| `mem-d2f7df353130` | RLM child recursion is daemon-blocked (RLM_MAX_DEPTH=1) | `fact` (host constraint; its design note is historical) |
| 10 × `OMP 18.1.15 …` (2026-09-11) | documented capabilities, configuration, memory backends, release notes | `fact`, kept; note that OMP is now 18.3.0, so these are version-scoped and a later 18.3 capability pass should supersede them |

## Effect on the Second Brain brief

Today (converted as-is): 20 lines, all under "Facts", ~483 tokens, including the two
orchestration records. After this sweep: ≤ 14 current records under Gotchas / Procedures /
Where things are / Facts, the orchestration and checkpoint records gone from push, still
reachable through history.
