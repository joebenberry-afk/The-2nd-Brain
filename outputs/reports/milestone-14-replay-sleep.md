# Milestone 14 — Replay / Sleep (Phase 14)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-13 (Plasticity) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Manual conservative sleep: prioritized replay queue (plan §54), deterministic
lesson clustering, provenance-linked memory strengthening, utility
aggregation, contradiction scan, and a human-readable consolidation report.
No dream pass yet (plan §53 conservative-first).

### Exact files

- `src/second_brain/sleep.py` — replay_queue/cluster/strengthen_memories/
  utility_report/consolidate
- `src/second_brain/cli.py` — `sleep consolidate [--apply]`, `sleep queue`
- `tests/test_sleep.py` — 25 tests (ranking, jaccard clustering, strength cap,
  no-mutation byte-compare, dry-run purity, determinism)
- `outputs/reports/milestone-14-replay-sleep.md` (this file)

## Requirement-to-evidence (Phase 14 acceptance, plan §110)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Manual brainctl sleep | live: queue ranked by priority (corrections first); dry-run then --apply |
| 2 | Conservative pass only (no dream) | sleep.py contains ONLY the consolidation path (asserted in tests); no candidate generation exists |
| 3 | No invented verified facts | strengthen_memories never creates memories, never edits bodies/titles/grades — byte-compared in tests; live apply left memory/semantic/*.md untouched in git |
| 4 | All semantic updates provenance-linked | every strength bump appends one memory_source {ref: episode_id, kind: episode}; live: 5/4/2 episode sources on the three memories |
| 5 | Candidate ideas remain candidate | no promotion path exists; utility is aggregated into the report only |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (311 tests)
live: sleep queue (9 episodes, corrections ranked 3.7/3.4/2.6 first)
live: consolidate dry-run (no writes) then --apply (strengths 0.5->0.6..0.9 capped,
      sources provenance-linked, bodies byte-untouched, contradictions 0)
```

## Deviations

1. report_path added to the consolidate result (was missing — the live apply
   run exposed the KeyError; fixed + determinism tests updated to exclude the
   timestamped path).
2. Dry-run display shows per-cluster deltas (sequential apply semantics);
   the applied totals cap at strength 1.0.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: sleep/consolidation, episodes (queue), semantic memory
  (strengthening targets), plasticity (utility aggregation), contradictions.
- How they were used: the build's own 9 real episodes formed the first real
  replay queue; three curated memories were strengthened from cluster
  evidence with episode provenance — the first complete
  episode->strengthening cycle on real data (v4.2 Stage 5 continued).
- Observed benefit: memory strength now reflects verified reuse evidence;
  the report is an auditable record of what sleep did and did NOT change.
- Observed overhead: full consolidation <200ms on this corpus.
- Token/context effect: none (manual; reports are files).
- Failures or friction: report_path KeyError on first live apply (fixed);
  dry-run delta display ambiguity (documented).
- Knowledge captured: sleep/reports/consolidation-*.md; strengthened
  memories mem-29557f93448f (0.9), mem-b67de5057f76 (0.8),
  mem-b0d6cc3de0ab (0.6).
- Memory/episode IDs: sources above; 9 episodes queued.
- Candidate improvements: dream pass as candidate-only (Phase 14+ later);
  cluster merging across sessions (Phase 15+).
- Promotion decision: sleep -> ADVISORY (manual --apply); auto-scheduling
  explicitly not built (plan: manual first).

## Rollback

- Git: revert this milestone's commits.
- Sleep reports are derived; strength bumps are data (restore pre-sleep
  backup: backups/backup-20260814-060833-738077 predates them).

## Next gate

**Phase 15 — Reconsolidation / Forgetting** (plan §111): activation tracking,
strength, labile state, supersede, hot/warm/cold/archive; forgetting starts
advisory only. Acceptance: stale memory loses hot priority; critical protected
memory does not decay; history still recoverable.


## Phase 14 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase14-independent-verification.md):
1. MINOR — plasticity docstring E501 at HEAD: wrapped (ruff green again).
2. NIT — test count corrected to 311.
3. NIT — re-apply now dedupes episode provenance sources (one row per
   episode per memory; regression test added).
4. NIT — §54 priority is a documented subset (pe*2 + salience + correction
   bonus; no old-case interleaving yet) — recorded as a known limitation;
   extended when replay volume justifies it.
