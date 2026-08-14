# Milestone 09 — Episodic Memory (Phase 9)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-08 (Environment Steward) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Episodic capture: immutable §46-template episode files under
memory/episodic/, `episodes` DB table (migration 0002), salience +
prediction-error fields, provenance refs, multi-agent-safe unique writes.
No semantic auto-update (Phase 10 is separate).

### Exact files

- `src/second_brain/migrations/0002_episodes.sql` — episodes table (plan §12 fields)
- `src/second_brain/episodes.py` — create/annotate/list/show/search; id
  `<type>-<date>-<8hex>` collision-checked; file-then-DB write with orphan
  cleanup; immutable body (addenda only)
- `src/second_brain/cli.py` — `episodes create|list|show|search|annotate`
- `tests/test_episodes.py` — 26 tests incl. collision recovery + concurrency
  Hypothesis; legacy tests updated for schema v2 (3 files)
- `outputs/reports/milestone-09-episodic-memory.md` (this file)

## Requirement-to-evidence (Phase 9 acceptance, plan §105)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Multi-agent-safe unique writes | id collision-checked against file+DB with retry; atomic file then transactional DB insert (orphan cleanup); Hypothesis N-sequential creates -> N unique ids/files/rows |
| 2 | Episode retrieval | list/show/search live (9 real episodes; search "WAL" hits the right episode) |
| 3 | Provenance | evidence_refs stored verbatim in frontmatter + DB (git/test/report refs per episode) |
| 4 | Salience + prediction-error fields | populated per episode from real experience (pe 0..0.9) |
| 5 | Immutability | annotate appends an Addendum section only; body never edited |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (228 tests)
live: doctor 16/16 (migrations current at version 2)
live: 9 real episodes captured; list/search verified
```

## Deviations

1. Episode files under memory/episodic/ are gitignored (raw vault per plan
   §124); promotion to experiences/ is curation (Phase 10+).
2. evidence_grade fixed to OBSERVED at capture; TESTED/VERIFIED grades come
   with curation.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: episodic memory itself (capture CLI), DB migration
  framework (0002 applied lazily on live brain), requirement ledger (Phase 9
  gate), doctor.
- How they were used: nine REAL build experiences captured — no synthetic
  filler (v4.2 Stage 4). Types: correction x3, environment x3, surprise x1,
  tool-routing x1, success x1.
- Observed benefit: the build's own failure history is now queryable with
  provenance (commit hashes, test ids, report paths).
- Observed overhead: capture ~50ms per episode.
- Token/context effect: none (nothing auto-injected into context).
- Failures or friction: first batch failed on argparse --evidence arity
  (one value per flag occurrence) — fixed in the capture helper; a useful
  CLI ergonomics note for the tool.
- Knowledge captured: 9 episode IDs (list above); content spans WAL replay,
  CRLF preservation, env pollution, daemon env pinning, shutdown race,
  tool-decline, scout success, venv pip, count accuracy.
- Memory/episode IDs: correction-20260814-ed0aee6b, -bcf7ea0b, -a6299e22;
  environment-20260814-fb37901d, -281f85e7, -3db7d00e;
  surprise-20260814-630da729; tool-routing-20260814-a3c8077e;
  success-20260814-2c753d99.
- Candidate improvements: episodes search should eventually use FTS5
  (Phase 10 consolidation); batch-capture ergonomics (--evidence repeat).
- Promotion decision: episodes -> ADVISORY (manual capture); ACTIVE
  auto-capture awaits the Prime extension hook (Phase 12+).

## Rollback

- Git: revert this milestone's commits.
- Episodes are data: memory/episodic/* + DB rows (delete = forget); the DB
  restore path keeps them with backups.

## Next gate

**Phase 10 — Semantic Memory** (plan §106): curator, evidence grades,
semantic entries, contradiction handling, current/historical distinction.
Manual curation first. Acceptance: repo contradiction supersedes stale
memory; history preserved.


## Phase 9 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase9-independent-verification.md):
1. NIT — test count corrected to 228.
2. NIT — id claim now race-safe: exclusive create (O_CREAT|O_EXCL) inside
   the retry loop; DB-failure cleanup can only delete a file we exclusively
   created (never a racing winner's).
3. NIT — db.connect moved inside the guarded try (connect failure leaves no
   orphan).
4. NIT — annotate reads with newline='' (raw bytes; no CRLF normalization).
