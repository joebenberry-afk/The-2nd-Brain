# Milestone 10 — Semantic Memory (Phase 10)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-09 (Episodic Memory) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Semantic memory with evidence grades, curation rules, versioned supersede,
and contradiction detection. Canonical files under memory/semantic/ (Git-
versioned) + memories/memory_sources/memory_versions tables (migration 0003).
Manual curation only, per plan §106.

### Exact files

- `src/second_brain/migrations/0003_semantic.sql` — memories + sources + versions
  (CHECK constraints on grade/status/scope)
- `src/second_brain/semantic.py` — add/curate/list/show/supersede/history/
  contradictions; one-step grade upgrades; REJECTED from anywhere; history
  preserved on supersede
- `src/second_brain/cli.py` — `memory add|curate|list|show|supersede|history|contradictions`
- `tests/test_semantic.py` — 30 tests incl. grade-transition + Hypothesis
  add/curate/supersede consistency
- 3 curated memories (real build evidence; see Dogfooding)
- `outputs/reports/milestone-10-semantic-memory.md` (this file)

## Requirement-to-evidence (Phase 10 acceptance, plan §106)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Repo contradiction correctly supersedes stale memory | live: memory narrowed after repo reality changed -> v2 current, v1 preserved with change note; contradictions detector stays quiet on the updated pair |
| 2 | History preserved | history shows v1 (path + note) + v2 (current); v1 file untouched |
| 3 | Evidence grades | grade transitions enforced (one-step upgrades; direct INFERRED->VERIFIED rejected in tests); VERIFIED sets last_verified_at |
| 4 | Current/historical distinction | superseded versions live in memory_versions; current row carries current_version; show prints the stored grade — never silently upgraded |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (258 tests)
live: 3 memories added + curated; supersede/history/contradictions demo
```

## Deviations

1. `contradictions` compares title + body hash (not semantic similarity) —
   deterministic first cut; semantic review is the curator's job (Phase 15).
2. Memory files are canonical; DB is an index (plan §7) — both kept in sync
   by the same transaction discipline as episodes.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: semantic memory (capture + curation), episodes (sources),
  requirement ledger (gate record), migrations (0003 lazy-applied live).
- How they were used: three memories consolidated from VERIFIED build
  evidence (v4.2 Stage 5) — env pollution, WAL-restore rule, daemon env
  pinning — each with episode/test/doc/git provenance; one was then
  superseded to simulate a repo-reality change, proving the acceptance flow.
- Observed benefit: durable machine-readable rules now outlive this session
  with explicit evidence grades; the WAL rule is grade VERIFIED.
- Observed overhead: add/curate ~40ms each.
- Token/context effect: none auto-injected (retrieval arrives Phase 15).
- Failures or friction: two CLI-API mismatches found live (sources dict
  shape; unknown source kinds) — fixed with kind mapping + tests.
- Knowledge captured: mem-b67de5057f76 (v2), mem-29557f93448f,
  mem-b0d6cc3de0ab.
- Memory/episode IDs: see above + the 9 episode sources.
- Candidate improvements: FTS5 search when the corpus grows; contradiction
  pairing should include status/grade filters (Phase 15 reconsolidation).
- Promotion decision: semantic memory -> ADVISORY (manual curation); ACTIVE
  curation automation waits for consolidation (Phase 14 sleep).

## Rollback

- Git: revert this milestone's commits (memory files are tracked).
- DB rows: derived index; rebuildable from files.

## Next gate

**Phase 11 — Metacognitive Monitor** (plan §107): trajectory-based confidence
categories (LOW/MEDIUM/HIGH) from failed commands, hypothesis reversals,
contradictions, untested requirements, stale source, repeated reads, verifier
disagreement, flaky tests, speculative edits, context pressure; shadow mode
only; compare against actual verification results/user corrections.
