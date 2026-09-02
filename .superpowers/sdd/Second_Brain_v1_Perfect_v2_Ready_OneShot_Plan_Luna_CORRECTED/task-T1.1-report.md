# T1.1 IDF query builder report

## RED

Command (after adding the three required tests, before implementation):

```text
./.venv/Scripts/python.exe -m pytest tests/test_semantic_query.py -q
```

Result: 3 failed. The failures were the expected missing `semantic.build_query`, long prompts returning no rows through the prior all-token FTS AND query, and AutoInject continuing to use task text instead of the active capsule objective/next action.

## GREEN

Focused command (worktree source selected explicitly with `PYTHONPATH=src`):

```text
./.venv/Scripts/python.exe -m pytest tests/test_semantic_query.py -q
```

Result: 3 passed.

Focused compatibility command:

```text
./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py::test_fail_open_retrieval_error -q
```

Result: 1 passed. Semantic retrieval infrastructure errors preserve `NO_INJECTION(BRAIN_UNAVAILABLE)` and do not enter the hybrid negative cache.

Focused retrieval command:

```text
./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py tests/test_hybrid_retrieval.py -q
```

Result: all T1.1-relevant tests passed; one existing migration-version assertion is incompatible with this worktree's current migration set (`11` observed versus the test's historical `10` expectation). No migration files were changed.

## Changes

- `src/second_brain/semantic.py`
  - Lazily and idempotently creates `memory_fts_vocab` beside `memory_fts`.
  - Adds literal local stopword vocabulary and ASCII tokenization/casefolding.
  - Adds bounded `build_query(text, k=8, msm=0.5, *, conn=None)` with safe quoted OR terms, IDF from vocabulary `doc` and `COUNT(*)` from `memories`, deterministic tie ordering, and empty output for fewer than two eligible terms.
  - Keeps the existing linear path for non-ASCII/small/unbuilt queries and the established single-token FTS search behavior.
  - Applies minimum-should-match post-filtering through token overlap before ranking.
  - Removes the old all-token `_fts_query` implementation.
- `src/second_brain/autoinject.py`
  - Removes per-token `_search_or_fallback`.
  - Uses capsule `objective` plus `next_action` as retrieval source when a capsule exists; falls back to task text when absent/unreadable.
  - Migrates scoped and unscoped retrieval to the single IDF/cascade path.
- `src/second_brain/hybrid_retrieval.py`
  - Adds an explicit non-content `retrieval_error` marker so semantic infrastructure exceptions remain distinguishable from genuine no-match results.
  - Avoids negative-cache poisoning on retrieval errors.
- `tests/test_semantic_query.py`
  - Adds the three required RED/GREEN behavior tests.
- `tests/test_autoinject.py`
  - Migrates old OR-fallback expectations to the IDF query mode and removes obsolete fallback wording.

## Test scope

Only focused semantic query, semantic index/retrieval, AutoInject, and hybrid retrieval tests were run. No formatter, linter, project-wide suite, or project-wide build was run.

## Concerns

- The existing migration assertion in `tests/test_autoinject.py` and `tests/test_memory_index.py` expects schema version 10, while this checkout applies version 11. This is pre-existing repository state and unrelated to T1.1; migration files were not modified.
- `build_query` accepts an optional SQLite connection because IDF requires per-database vocabulary state; normal callers use the connection internally through `search_memories`.

## Follow-up regression correction

The first implementation incorrectly fell through to the linear AND path when a multi-token prompt had only one term present in the vocabulary. Added `test_multi_token_query_keeps_single_eligible_term` RED first; it failed with an empty result, then passed after the FTS plan retained the one eligible term for search while public `build_query` still returns `[]` for fewer than two output terms.

Correction command:

```text
./.venv/Scripts/python.exe -m pytest tests/test_semantic_query.py -q
```

Result: 4 passed. The literal stoplist was also tightened to exactly 200 words and verified directly.

The query planner now initializes the vocabulary itself when given a
connection, making lazy setup idempotent for direct builder callers as well
as `search_memories`. A multi-token prompt with one eligible indexed term
uses that safe single-term FTS expression; a true no-match remains
`NO_RELEVANT_MEMORY`.

Post-correction focused retrieval command (excluding only the unrelated
historical migration-version assertion):

```text
./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py tests/test_hybrid_retrieval.py -q -k "not migration_0008_fresh_and_v7_upgrade"
```

Result: 27 passed.

Final focused parity/contraction correction:

```text
./.venv/Scripts/python.exe -m pytest tests/test_semantic_query.py tests/test_memory_index.py::test_search_parity_fts_vs_linear -q
```

Result: 6 passed. The tokenizer now derives a normalized fragment stopset
from the literal 200-word list, so contraction fragments cannot leak into
queries. The parity fixture's multi-token expectation was migrated to the
specified OR/minimum-should-match behavior.
