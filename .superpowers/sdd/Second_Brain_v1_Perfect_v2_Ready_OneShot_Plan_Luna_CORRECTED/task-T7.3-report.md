# T7.3 Task Report — Retrieval Intelligence 2.0 Scoring

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 515–544.

## Files

- `src/second_brain/hybrid_retrieval.py`
- `tests/test_retrieval_intelligence_v2.py` (new)
- `scripts/run_retrieval_economics.py` (new)
- `outputs/reports/v2/retrieval/retrieval-economics.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.3-report.md` (new)

## Implemented contract

1. **Explicit, Inspectable Score Components**:
   Extended scoring across `relevance`, `authority`, `scope`, `freshness`, `contradiction`, `activation_need`, `diversity`, and `final_score`.
   `RetrievalMatch` dataclass exposes `score_components: dict[str, float]` and serializes them in `to_dict()` with 4-decimal precision.

2. **Diversity via MMR**:
   Implemented `apply_mmr(matches, lambda_param=0.7, top_k=10)` using token Jaccard similarity:
   $$\text{MMR} = \lambda \cdot \text{relevance} - (1 - \lambda) \cdot \max_{s \in S} \text{Sim}_{\text{Jaccard}}(c, s)$$
   Redundant near-duplicates are penalized by $(1 - 0.7) \cdot \text{Sim}$, re-ranking diverse relevant memories above duplicate entries in top-$k$.

3. **Exact-ID & Reference Safety**:
   Exact-ID lookups (e.g. `mem-...`) bypass semantic scoring uncertainty with Tier 0 resolution and score 1.0, but strictly enforce authority and status safety:
   - Fails closed (`decision="NO_INJECTION"`, `reason="AUTHORITY_VIOLATION"`) when advisory-ceiling memory is queried in the `policy` lane.
   - Rejects excluded statuses (`reason="EXCLUDED_STATUS"`) when memories are `REJECTED`, `archived`, or `superseded`.
   - Surfaces contradictions if the exact reference has recorded contradictions.

4. **Contradiction Surfacing**:
   Contradictions are never averaged away into an opaque score.
   `CascadeResult.contradictions` surfaces all contradictory memory IDs, titles, contradiction counts, and details.
   Each `RetrievalMatch` flags `has_contradiction: bool` and provides `contradiction_details: list[str]`.

5. **Multi-View Control**:
   Multi-view retrieval is disabled by default (`self.multiview_enabled = False` on retriever, `multiview = False` argument). Only runs when explicitly enabled by caller or telemetry.
   `CascadeResult` records `multiview_invoked: bool`.

6. **Local-First Architecture**:
   Zero external vector dependencies or GPU requirements; all scoring uses fast token Jaccard, SQLite FTS5 BM25, and local ACT-R calculations.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_retrieval_intelligence_v2.py tests/test_hybrid_retrieval.py -q
17 passed

.venv/Scripts/python.exe -m pytest tests/test_dogfood_token_economics.py -q
3 passed
```

Named tests verified:
- `test_retrieval_exposes_score_components`: PASS (all 8 score components present, numerical, and serialized in `to_dict()`)
- `test_contradiction_is_surfaced`: PASS (contradicted memory surfaces in `res.contradictions` and match flag)
- `test_exact_ref_bypasses_relevance_not_authority`: PASS (bypasses semantic scoring, blocks policy lane injection of advisory ceiling and rejected status)
- `test_mmr_reduces_duplicate_topk`: PASS (MMR diversity penalizes duplicate memory, promoting diverse candidate into top-2)
- `test_multiview_off_by_default`: PASS (multiview disabled by default, `multiview_invoked is False`)

## Economics

Paired economics benchmark run via `scripts/run_retrieval_economics.py` comparing base retrieval (without MMR) against Retrieval Intelligence 2.0 (with MMR $\lambda=0.7$):

- Evaluated 8 paired queries across database, caching, storage, networking, architecture, data layer, and resilience tasks.
- `economics.verdict`:
  - `n`: 8
  - `r_bar`: 0.0
  - `lambda`: 1.0
  - `verdict`: `"INSUFFICIENT"` (non-negative, expected for small isolated fixture)
  - `success_delta`: 0.0 (100% acceptance maintained)
  - `turns_delta`: 0.0 (zero turn inflation)
  - `dollars_delta`: 0.0 (no cost regression)
- Artifact saved: `outputs/reports/v2/retrieval/retrieval-economics.json`.

## Migration and rollback

In-memory and algorithmic extension of `hybrid_retrieval.py`; no database schema modification required.
Rollback is code-revert safe.

## Commit

Commit message: `brain(memory): retrieval intelligence 2 scoring`.
