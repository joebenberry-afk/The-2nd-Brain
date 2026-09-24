# T6.1 — Dead Code and State Deletion

## Summary
Executed dead code, dead state, demo module, and unwired config cleanup across the Second Brain v2 codebase per plan section §377 (Task T6.1):
1. **ResidencyState Cleanup** (`src/second_brain/vmem.py`):
   - Deleted dead residency states `STORED = "STORED"`, `SUPERSEDED = "SUPERSEDED"`, and `PURGED = "PURGED"`.
   - `ResidencyState` now strictly contains only the 3 live states: `RESIDENT = "RESIDENT"`, `EVICTED = "EVICTED"`, `FAULTED_IN = "FAULTED_IN"`.
   - Cleaned up obsolete tests in `tests/test_vmem.py` and updated lifecycle docstrings.

2. **ToolOutcomeState & Upgrader Removal in Contracts** (`src/second_brain/contracts.py`):
   - Deleted unused `ToolOutcomeState` class.
   - Deleted stub `UPGRADERS` dictionary.
   - Replaced `while version < LEDGER_SCHEMA_VERSION` upgrader lookup in `read_ledger_header` with an explicit check:
     `if version != LEDGER_SCHEMA_VERSION: raise BrainError(f"unsupported ledger schema version {version} (expected {LEDGER_SCHEMA_VERSION})")`.
   - Updated `tests/test_contracts.py` to remove `ToolOutcomeState` tests and verify `BrainError` on schema version mismatch.

3. **Upgrader Removal in Ledger** (`src/second_brain/ledger.py`):
   - Deleted stub `UPGRADERS` dictionary.
   - Replaced upgrader iteration loop in `LedgerStore._check_version` with an explicit check:
     `if version != LEDGER_SCHEMA_VERSION: raise BrainError(f"ledger schema version {version} unsupported (this runtime requires {LEDGER_SCHEMA_VERSION})")`.
   - Updated `tests/test_ledger.py:test_schema_versioning` to expect `BrainError` with "unsupported" on version mismatch.

4. **Demo Module `tool_working_set.py` & CLI Deletion**:
   - Deleted `src/second_brain/tool_working_set.py`.
   - Removed CLI parser `tool-set` and command handler `cmd_tool_set` from `src/second_brain/cli.py`.
   - Removed `tool_working_set = true` feature flag from `config/governor.toml`.
   - Deleted test suites `tests/test_tool_working_set.py` and `tests/test_tool_working_set_live_integration.py`.
   - Updated `tests/test_dogfood_token_economics.py` to remove the dead import and calls.
   - Kept telemetry kind `prime_tool_surface` in `telemetry.py:KNOWN_KINDS` untouched.

5. **Unwired Config Cleanup**:
   - `config/context.toml`: Removed unwired `[governor]` bands section (`green_until_pct = 60`, `yellow_until_pct = 75`, `orange_until_pct = 85`).
   - `config/retrieval.toml`: Removed unwired `[lateral_inhibition]` and `[decay]` sections and updated header comment.
   - **Amendment (post-review)**: The seed template copies `src/second_brain/defaults/config/context.toml` and `src/second_brain/defaults/config/retrieval.toml` — copied into every new Brain home by `cli.py`'s `init`/`_seed_defaults` — still contained the identical dead `[governor]` and `[lateral_inhibition]`/`[decay]` sections after the first pass. Removed them there too, identically to the repo-root dev copies, and updated the `retrieval.toml` header comment to match.

6. **Action Cache LRU Enforcement** (`src/second_brain/action_cache.py`):
   - Added `max_entries` parameter (default `DEFAULT_CACHE_MAX_ENTRIES` = 5000) to `ActionCacheStore.__init__` and `store_action`.
   - Added index on `last_accessed_at` in `_ACTION_CACHE_SCHEMA`.
   - In `store_action`, after insert/update, checks if row count exceeds `effective_max`. If so, evicts oldest entries by `last_accessed_at`:
     `DELETE FROM action_cache WHERE action_key IN (SELECT action_key FROM action_cache ORDER BY last_accessed_at ASC LIMIT ?)` with `(excess,)`.
   - Added alias `put = store_action` on `ActionCacheStore` and module-level alias `ActionCache = ActionCacheStore`.

7. **Verification & Test Coverage** (`tests/test_cleanup_t61.py`):
   - Added comprehensive test suite verifying:
     - `ResidencyState` contains only RESIDENT, EVICTED, FAULTED_IN.
     - `contracts.ToolOutcomeState` and `contracts.UPGRADERS` / `ledger.UPGRADERS` are removed.
     - `read_ledger_header` and `LedgerStore._check_version` raise on version mismatch.
     - `tool_working_set` cannot be imported and `tool-set` CLI is rejected.
     - Config files have unwired sections removed — checked in both the repo-root dev copies (`config/context.toml`, `config/retrieval.toml`) and the seed template copies (`src/second_brain/defaults/config/context.toml`, `src/second_brain/defaults/config/retrieval.toml`) that `cli.py` copies into every new Brain home.
     - `ActionCacheStore` / `ActionCache` enforces LRU eviction on `put` and method override.

## Verification
- Environment: Python in `.venv/Scripts/python.exe` with `PYTHONHOME` cleared and `PYTHONPATH=src`.
- Ran full test sweep across all affected modules:
  - `tests/test_cleanup_t61.py`: 9 passed
  - `tests/test_vmem.py`, `tests/test_vmem_live_integration.py`, `tests/test_vmem_coverage.py`: 105 passed
  - `tests/test_contracts.py`: 40 passed
  - `tests/test_ledger.py`: 39 passed
  - `tests/test_action_cache.py`, `tests/test_action_cache_safety_proof.py`: 17 passed
  - `tests/test_governor.py`: 48 passed
  - `tests/test_dogfood_token_economics.py`: 3 passed
  - `tests/test_retrieval_ranking.py`, `tests/test_retrieval_budget.py`: 17 passed
  - `tests/test_cache_breakpoints.py`: 1 passed
  - Total: 279 passed in 41.5s, 0 failures.

## Amendment (post-review, same commit `f7fa517` amended)
Adversarial review (ReviewT61) caught that the initial config cleanup pass only edited the repo-root dev copies `config/context.toml` and `config/retrieval.toml`, missing the actual seed template `src/second_brain/defaults/config/context.toml` and `src/second_brain/defaults/config/retrieval.toml` that `cli.py::_seed_defaults()`/`cmd_init` copies into every new Brain home. Those seed files still had the full dead `[governor]` block (`green_until_pct`/`yellow_until_pct`/`orange_until_pct`/`actions`) and `[lateral_inhibition]`/`[decay]` sections plus a stale "NOT WIRED" header comment.
- Fixed: removed the same dead sections from both seed files, updated the `retrieval.toml` seed header comment to match the repo-root copy's wording.
- Regression coverage: extended `tests/test_cleanup_t61.py::test_config_cleanups` to additionally load and assert against the `src/second_brain/defaults/config/` copies, so this exact gap (root copy clean, seed copy stale) cannot silently reappear.
- Re-ran focused tests after the fix: `tests/test_cleanup_t61.py` (9 passed), plus `tests/test_cli.py`, `tests/test_governor.py`, `tests/test_retrieval_ranking.py`, `tests/test_retrieval_budget.py` (112 passed total, 0 failures) — same environment (`.venv/Scripts/python.exe`, `PYTHONHOME` cleared, `PYTHONPATH=src`).
- Commit amended in place via `git commit --amend --no-edit` (subject unchanged: `brain(core): remove dead states and demo modules`).
