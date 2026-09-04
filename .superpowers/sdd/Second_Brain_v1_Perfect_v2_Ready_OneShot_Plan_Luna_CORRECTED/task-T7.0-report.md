# T7.0 Task Report — Repository-true v2 plan ownership

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 418–453.

## Files

- `docs/superpowers/plans/2026-09-02-second-brain-v2-implementation.md` (restored from commit `05bea1e`, then reconciled)
- `outputs/reports/v2/v2-plan-fold/owner-diff.md` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.0-report.md` (new)

No source code, tests, configuration, migrations, database state, or runtime artifacts changed.

## Reconciliation result

- Replaced the legacy parallel-owner sketch with repository-true ownership and explicit P0-P6 inheritance.
- Classified all 16 legacy implementation module/script proposals: 2 `KEEP`, 12 `FOLD`, and 2 `DELETE_FROM_PLAN`. The 11 corrected-plan owner mappings are included exactly; the additional five legacy implementation surfaces are also classified so none remain implicit.
- Kept Brainstem as the T7.4-approved new owner.
- Classified all 14 legacy table proposals: 6 `KEEP` and 8 `DELETE_FROM_PLAN`.
- Retained exactly `v2_candidates`, `v2_interventions`, `v2_observations`, `v2_frontier_items`, `v2_rollout_events`, and `v2_qualification`.
- Removed authorization for duplicate memory utility/meta, retrieval outcome, Brainstem decision, engram, profile, and capability tables; their repository-true existing owners are recorded in both reconciliation artifacts.
- Reordered the plan to: `V2-0 → V2-A' Trusted Retrieval/Freshness → V2-B' Low-Friction I/O → Earned Memory → Meta-Memory → Retrieval 2.0 → Brainstem → Causal Learning → Engrams/Culture → Universal Control Plane → Frontier → Self-Improvement Proof`.
- Converted already-delivered P0-P6 behavior from proposed recreation work into explicit inherited baselines, leaving only phase-specific gaps.
- Preserved the legacy plan's load-bearing behavioral gates inside repository-true owners: the exact four causal credit classes and correlation-only non-promotion; the complete evidence-preserving reconsolidation action set and archive semantics; real installed-host rich↔limited handoff proof with honest unavailable-host evidence and no mocks; and mandatory representative scale/performance plus event-count burn-in before tagging.

## Mechanical checks

Text searches over the plan and owner diff established:

- exactly 12 phase headings, once each, in the required order;
- exactly 16 classified historical implementation module/script rows in the owner diff;
- exactly 14 classified historical table rows in the owner diff;
- exactly six entries in the plan's retained-table enumeration, matching the required set;
- zero matches for creation/addition/modification proposals targeting folded parallel modules;
- folded legacy paths occur only in clearly labeled historical mapping rows;
- `git diff --check` produced no output.

No code tests, formatters, linters, builds, database commands, or runtime commands were run, as T7.0 is documentation-only.

## Commit

Exact commit message: `brain(core): fold v2 plan into existing owners`.
