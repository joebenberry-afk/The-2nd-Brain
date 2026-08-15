# Retrieval benchmark — Phase 6 (SQLite FTS5 vs linear scan)

Date: 2026-08-15. Harness: `proof/runner/retrieval_bench.py` (v4.3 §14 Phase 3
labeled-corpus format: JSONL `{query, must_retrieve[], may_retrieve[],
must_not_retrieve[], critical_ground_truth}`). Seed 20260815; 25 query anchors
x 2 query styles (topic-phrase-only and topic-phrase + unique case token) =
~50 queries per corpus size. Synthetic-but-realistic memories: canonical
markdown frontmatter (id/title/scope/project/status/grade/version/created_at)
+ body; ~10% superseded duplicates, ~8% archived, ~8% contradiction pairs.

Quality gates are enforced from Phase 7+; this table is the Phase 6 baseline.

| Corpus | Engine | Recall@1 | Recall@3 | Recall@5 | Precision@5 | MRR | Dup rate | Stale rate | Contradiction surfaced | Tokens/query | p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | fts | 0.5600 | 0.7200 | 0.8800 | 0.1760 | 0.6647 | 0.6667 | 0.0400 | 0.0000 | 222.6 | 2.59 | 2.70 |
| 1,000 | fts | 0.5102 | 0.5102 | 0.5306 | 0.1061 | 0.5153 | 0.6711 | 0.1141 | 0.0000 | 227.2 | 3.94 | 5.00 |
| 10,000 | fts | 0.5000 | 0.5000 | 0.5000 | 0.1000 | 0.5000 | 0.6667 | 0.0600 | 0.0000 | 222.4 | 11.68 | 17.86 |
| 100 | linear | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0 | 11.20 | 13.39 |
| 1,000 | linear | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0 | 135.45 | 145.16 |
| 10,000 | linear | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0 | 1,407.73 | 1,440.23 |

Interpretation (Phase 6, no quality gates yet):

- **Latency target met for later phases**: FTS5 10k p95 = 17.9 ms (plan
  Phase 23 target: p95 <= 200 ms). Linear scan at 10k: p95 = 1,440 ms — the
  FTS5 path is ~80x faster at 10k.
- **Recall/ranking are raw**: bm25-only ranking finds the labeled target at
  rank 1 for the exact (uid) queries (Recall@1 = 0.5 = uid-query share) but
  phrase-only queries return same-family docs ranked together — expected with
  no hard filters (Phase 7), dedupe (Phase 8), or ranking formula (Phase 9).
- **Duplicate rate ~0.67**: same-family (current + superseded copy) docs co-
  retrieved — dedupe is Phase 8.
- **Stale rate 0.04-0.11**: archived/superseded docs retrieved — stale
  exclusion is Phase 7.
- **Contradiction surfaced 0.0**: the Phase 6 engine has no contradiction
  channel — Phase 10.
- **Linear Recall@1 = 0.0 on the same queries**: whole-string substring
  matching cannot match multi-word tokenized queries verbatim; the FTS5
  engine is also a functional improvement, not only a speed one.
- 50k corpus: optional per plan; not run in this pass (build time ~30+ min at
  current add_memory rate). Harness supports it via `--corpus 50000`.

Reproduce:

```powershell
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
.venv\Scripts\python.exe -m proof.runner.retrieval_bench --corpus 100 1000 10000 --engine fts
.venv\Scripts\python.exe -m proof.runner.retrieval_bench --corpus 100 1000 10000 --engine linear
```

## Phase 7 addition — hard filters on/off (2026-08-15)

Phase 7 implemented hard filters (REJECTED always excluded; archived and
superseded excluded unless `include_history`; superseded rows with
current_version > 1 retained as uniquely useful evidence — schema-adapted,
the schema has no superseded_by column; project filter when a project context
is supplied). Same harness, same seed, same labeled corpora:

| Corpus | Filters | Rec@1 | Rec@3 | Rec@5 | P@5 | MRR | Dup | Stale | Contr | p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | on | 0.5400 | 0.7200 | 0.9200 | 0.1840 | 0.6627 | 0.6667 | 0.0000 | 0.0400 | 3.37 | 4.39 |
| 1,000 | on | 0.4898 | 0.4898 | 0.5102 | 0.1020 | 0.4939 | 0.6711 | 0.0000 | 0.0000 | 5.12 | 6.04 |
| 10,000 | on | 0.5000 | 0.5000 | 0.5000 | 0.1000 | 0.5000 | 0.6667 | 0.0000 | 0.0000 | 12.49 | 20.71 |
| 100 | off | 0.5600 | 0.7200 | 0.8800 | 0.1760 | 0.6610 | 0.6667 | 0.0267 | 0.0400 | 2.65 | 2.75 |
| 1,000 | off | 0.4898 | 0.4898 | 0.5306 | 0.1020 | 0.5007 | 0.6711 | 0.0671 | 0.0000 | 4.05 | 5.21 |
| 10,000 | off | 0.5000 | 0.5000 | 0.5000 | 0.1000 | 0.5050 | 0.6667 | 0.0933 | 0.0000 | 10.74 | 15.27 |

Effect of filters: **stale activation rate drops to 0.0000 at every corpus
size** (superseded/archived rows never enter top-5; off-mode stale rates were
0.027-0.093). Recall/MRR essentially unchanged (uid queries unaffected; the
retained unique-evidence exception keeps self-versioned superseded lines
retrievable). Duplicate rate unchanged (Phase 8 dedupe). Contradiction
co-retrieval 0.04 at 100 (both members current; surfacing is Phase 10).
Latency stays far below the 200 ms target (10k p95 20.7 ms with filters).

Reproduce: add `--history` to the FTS command for the "off" column.

## Phase 8 addition — dedupe on/off (2026-08-15)

Phase 8 implemented post-filter, pre-budget dedupe: same-fact families =
normalized-title equality (primary) + body-token Jaccard >= 0.8 (secondary,
bounded by a 200-row work guard so broad queries stay fast); representative =
highest current_version, then status (current > labile > candidate > archived
> superseded), then newest updated_at, then evidence grade, then memory_id.
Scope rule: under a project context, global/domain-scope rows are a DISTINCT
bucket (comparison may be required); otherwise families dedupe. The fixture
now uses per-fact families (contradiction pairs are NOT duplicates; the dup
metric measures genuine near-identical-version injection), and ~12% of
memories get a near-duplicate current copy (identical title, labile status).

| Corpus | Mode | Rec@1 | Rec@5 | MRR | Dup | Stale | Contr | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 100 | filters+dedupe | 0.6122 | 0.8163 | 0.6850 | 0.0000 | 0.0000 | 0.0204 | 2.85 |
| 1,000 | filters+dedupe | 0.5000 | 0.5400 | 0.5090 | 0.0000 | 0.0000 | 0.0000 | 9.23 |
| 10,000 | filters+dedupe | 0.5000 | 0.5000 | 0.5000 | 0.0000 | 0.0000 | 0.0000 | 21.06 |
| 100 | filters (no dedupe) | 0.5510 | 0.8571 | 0.6650 | 0.0067 | 0.0000 | 0.0000 | 2.84 |
| 1,000 | filters (no dedupe) | 0.5000 | 0.5400 | 0.5167 | 0.0000 | 0.0000 | 0.0000 | 4.72 |
| 10,000 | filters (no dedupe) | 0.5000 | 0.5000 | 0.5000 | 0.0000 | 0.0000 | 0.0000 | 18.60 |
| 100 | raw | 0.5510 | 0.8367 | 0.6578 | 0.0000 | 0.0067 | 0.0000 | 3.01 |
| 1,000 | raw | 0.5000 | 0.5400 | 0.5140 | 0.0000 | 0.0267 | 0.0000 | 10.56 |
| 10,000 | raw | 0.5000 | 0.5000 | 0.5000 | 0.0200 | 0.0600 | 0.0000 | 22.48 |

Effect: duplicate injection rate 0.0000 with dedupe (filters-only 0.0067@100;
raw 0.02@10k from unmerged superseded copies); stale activation 0.0000 with
filters/dedupe (raw 0.007-0.06); recall/MRR do not regress; 10k p95 stays
~21 ms (<= 200 ms target). The Phase 8 dup-rate delta is small in absolute
terms because the per-fact metric is strict and bm25 already ranks copies low;
the merging MECHANISM is proven by unit tests (identical-title families,
representative selection, scope rule). An O(n^2) body-Jaccard scan observed
during development (2.7 s at 10k on broad queries) was bounded with a
deterministic 200-row work guard (title families always apply); latency is
back at ~20 ms.


## Phase 9 addition — full formula scoring, current engine (2026-08-15, worker-a)

Seed 20260815, 50 queries per corpus, default path `semantic.search_memories`
(FTS5 + Phase 7 hard filters + Phase 8 dedupe + Phase 9 scoring; linear via
`_search_linear` with the same filters/dedupe/scoring).

| Corpus | Engine | Recall@1 | Recall@3 | Recall@5 | Precision@5 | MRR | Dup rate | Stale rate | Contradiction surfaced | Tokens/query | p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | fts | 0.9375 | 0.9375 | 1.0000 | 0.2000 | 0.9516 | 0.0000 | 0.0000 | 0.0000 | 192.8 | 3.94 | 4.67 |
| 1,000 | fts | 0.9600 | 0.9600 | 0.9800 | 0.1960 | 0.9650 | 0.0000 | 0.0000 | 0.0000 | 230.4 | 4.42 | 5.56 |
| 10,000 | fts | 0.9800 | 0.9800 | 0.9800 | 0.1960 | 0.9800 | 0.0000 | 0.0000 | 0.0000 | 235.6 | 8.98 | 9.96 |
| 100 | linear | 0.9375 | 0.9375 | 1.0000 | 0.2000 | 0.9516 | 0.0000 | 0.0000 | 0.0000 | 192.8 | 14.71 | 16.83 |
| 1,000 | linear | 0.9600 | 0.9600 | 0.9800 | 0.1960 | 0.9650 | 0.0000 | 0.0000 | 0.0000 | 230.4 | 136.32 | 139.98 |

Interpretation:

- **Recall@1 = 0.94-0.98** (recorded Phase 6 defect was 0.0; raw bm25 Phase 6
  FTS was 0.50). The canonical target — created at slot 5 so bm25/rowid ties
  cannot favor it, curated VERIFIED/current with decision value — now ranks
  first because trust * decision scoring breaks the bm25 tie and the Phase 7/8
  channels remove stale/duplicate rows entirely (dup/stale rate 0.0).
- **FTS p95 <= 9.96 ms at 10k** (plan Phase 23 target: <= 200 ms; ~20x margin).
  Linear fallback p95 at 1k = 140 ms; 10k linear remains the slow file-scan
  path (~1.4 s/query, Phase 6 measurement) — FTS is the primary path.
- **Linear fallback consistency fix (this pass)**: `_search_linear` now
  matches tokenized queries with FTS-consistent token-AND semantics (was
  verbatim whole-string substring, which cannot match multi-word phrase
  queries: linear Recall@1 = 0.0) and feeds the dedupe/scorer the clean body
  (frontmatter stripped via `_body_text`), so the same family threshold that
  merges duplicates on the FTS path also merges them on the fallback
  (frontmatter-polluted Jaccard 0.65 vs clean 0.86 had split the two paths).
  Non-tokenizable queries (symbols, non-ASCII) keep legacy substring matching.
- **Contradiction surfacing remains 0.0**: Phase 10 channel is not built yet
  (the `contradictions()` same-title API exists; search does not surface
  contradiction pairs). Precision@5 ~0.20 is harness-inherent: labels carry 1-2
  relevant docs per query while the engine returns 5 (top-k trimming is the
  Phase 11 TODO).
