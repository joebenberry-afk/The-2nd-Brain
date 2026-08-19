# Hybrid Retrieval Validation

Phase R8. Per the plan's explicit instruction ("Review and test it. Do not
rewrite unless a defect exists"): no code changed. RC3's `prepare_injection()`
→ `_CASCADE.retrieve()` wiring is verified genuinely live, tested against
the checklist, and one honest gap is documented (not fixed — not a defect,
a documented capability boundary).

## 1. The wiring is real (confirmed by source, not RC3's claim)

`src/second_brain/autoinject.py:684-689` — `prepare_injection()` calls
`_CASCADE.retrieve(home, intent.task_text, project_id=proj_filter,
top_k=_MAX_CANDIDATES)` as the **primary** search path, before an
OR-fallback (`_search_or_fallback`) that only runs `if not rows`. A second
`_CASCADE.retrieve()` call (unscoped, `project_id=None`) runs only when the
scoped search returned nothing, specifically to distinguish
`WRONG_PROJECT` from `NO_RELEVANT_MEMORY` in the decision telemetry. This
is genuine production wiring, not a stub.

## 2. Plan §14 checklist, verified against real tests

| Requirement | Status | Evidence |
|---|---|---|
| Exact tier (Tier 0) | ✅ | `test_hybrid_retrieval_live_integration.py::test_tier_0_exact_ref_resolution` — component-level, direct `HybridCascadeRetriever` call |
| Lexical tier (Tier 2) | ✅ | `...::test_tier_2_lexical_fts5_resolution` |
| Project isolation | ✅ | `test_retrieval_isolation.py`: `test_identical_keywords_different_project_isolated`, `test_high_semantic_score_wrong_project_never_crowds_out_right_project`, `test_global_policy_retrievable_across_all_projects`, `test_unresolved_project_identity_fails_safe_to_global_only`, `test_unresolved_project_default_memory_suppressed_and_global_policy_allowed` — all exercise **`prepare_injection()` itself**, the production entry point, not just the cascade component |
| Semantic fallback if enabled | ⚠️ **gap found** | see §3 below |
| Negative miss cache invalidation | ✅ (moot by architecture) | see §4 below |
| Zero result → zero injection | ✅ | `prepare_injection()`'s `empty`/`decision()` helpers default to `NO_INJECTION`; every retrieval path that finds nothing falls through to a `NoInjectionReason` decision, never fabricating a packet |
| Contradiction/supersession filters | ✅ | `test_materially_updated_memory_delivered_with_supersede_pointer`, `test_deduplication_suppresses_repeated_unchanged_delta` |
| Token budget | ✅ | `test_delta_stricter_than_startup_budget_and_confidence` |

## 3. Gap found: Tier 3/4 dense vector semantic fallback is never enabled

`HybridCascadeRetriever.retrieve()` accepts an optional `vector_searcher:
Callable[[str, str | None], list[dict]] | None = None` parameter
(`hybrid_retrieval.py:131`) — when supplied, Tier 3 (`TIER_3_VECTOR_
SEMANTIC`) and Tier 4 (`TIER_4_DYNAMIC_EXPANDER`) become reachable.
`prepare_injection()`'s two `_CASCADE.retrieve()` calls (§1) never pass
this argument. Grepping the whole codebase for `vector_searcher` /
`VectorSearcher` outside `hybrid_retrieval.py` found **zero** matches —
there is no dense-vector search implementation anywhere in this repo to
even pass in. This is a real, confirmed capability boundary: Tiers 0-2
(exact/metadata/lexical) and the OR-fallback are the entire live retrieval
surface today; Tiers 3-4 are a designed extension seam with no
implementation behind it.

Not treated as a defect and not fixed this pass: building a dense-vector
search engine is a substantially larger undertaking than "verify, don't
rebuild" scopes for R8, and nothing in the plan's R8 section requires it
to exist — only that its presence/absence be verified, which this report
does.

## 4. Negative miss cache: invalidation is architecturally unnecessary here

`HybridCascadeRetriever.invalidate_negative_cache()` exists and is called
from one CLI command (`cli.py:3927`) and its own unit test — never from
`semantic.add_memory()`/`curate()`. This looked like a potential staleness
bug (a cached miss could outlive a newly added matching memory) until
tracing the actual call path: `_CASCADE` (`autoinject.py:76`) is a
**module-level singleton**, but `prepare_injection()` is only ever invoked
from a fresh `python -m second_brain autoinject ...` subprocess spawned
per Prime event (`brainstem/prime-extension/src/autoinject.ts`, `execFile`
— same one-shot-subprocess pattern as RTD/VMem/ledger). Each invocation
gets a brand-new `_CASCADE` instance with an empty negative cache, so
there is no persistent state across calls for a stale entry to survive
in. `invalidate_negative_cache()` matters only for the CLI's own
longer-lived in-process usage, which already calls it correctly.

## 5. Verification

```
.venv\Scripts\python -m pytest tests/test_retrieval_isolation.py \
  tests/test_hybrid_retrieval.py tests/test_hybrid_retrieval_live_integration.py \
  tests/test_autoinject.py -v
  → 44 passed
```

No files changed this phase.
