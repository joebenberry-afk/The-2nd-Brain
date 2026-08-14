# Retrieval benchmark

The benchmark used fresh temporary Brain homes and the current public
`semantic.search_memories` path. Each query had one target memory plus a
duplicate and a stale superseded-looking memory sharing the same anchor. This
is a mechanism/scale benchmark, not final holdout evidence.

| Corpus | Queries | Recall@1 | Recall@3 | Recall@5 | Precision@5 | Duplicate rate | Stale rate | Contradiction surfaced | p50 ms | p95 ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 10 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 | 0.3333 | 0.0000 | 11.4564 | 12.0246 |
| 1,000 | 25 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 | 0.3333 | 0.0000 | 123.3791 | 129.0205 |
| 10,000 | 25 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 | 0.3333 | 0.0000 | 1,374.5167 | 1,426.1416 |

Interpretation: the current substring engine can find an anchor somewhere in
the result set, but it has no relevance ranking, duplicate suppression, stale
policy, or contradiction-surfacing channel. It fails the plan’s realistic
Precision@5 (`>=0.80`), stale-dominance (`0`), contradiction (`>=0.95` when
labeled), and 10,000-memory p95 suggestion (`<=500 ms`) gates. Recall@5 alone
is not evidence of useful retrieval here.

Raw derived result hashes:

- `retrieval-100-1000.json`: `2BCB80538DE1C1E98FD431684080FE8AF7794F2680D3B7033D3ACFE1A8018D17`
- `retrieval-10000.json`: `63564B88AD351E370DAFFDBECE0BED5B4C02D222D528219A7921C7B6E2B7F9A2`

No production retrieval code was changed in this stage.
