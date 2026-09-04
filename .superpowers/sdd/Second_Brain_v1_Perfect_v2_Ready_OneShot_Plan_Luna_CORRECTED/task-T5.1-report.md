# T5.1 — ACT-R activation replaces counters

## Summary
Replaced counter- and fixed-TTL-based memory decay with ACT-R base-level activation ($B$) and need probability ($P_{\text{need}}$).

Key changes:
1. **Migration 0016** (`src/second_brain/migrations/0016_actr_activation.sql`):
   - Added `kind TEXT` column to `memory_activations`.
   - Added `retrieval_strength REAL NOT NULL DEFAULT 1.0` and `storage_strength REAL NOT NULL DEFAULT 1.0` to `memories`.
   - Backfilled existing `memory_activations`: set `kind = 'used'` where `outcome = 'correct'` and `kind IS NULL`.

2. **Reconsolidation & Activation Engine** (`src/second_brain/reconsolidation.py`):
   - Updated `record_activation`: accepts `kind: str | None = None` (defaulting to `"used"` if `outcome == "correct"` else `outcome`). Increments `storage_strength` by 0.1 for `kind in ("used", "success", "verified")`. `storage_strength` never decreases.
   - Verified `record_retrieval` does not increment `storage_strength`.
   - Added `compute_base_level_activation(home, memory_id, now=None, d=0.5) -> float`:
     - Queries `memory_activations` for `kind in ('used', 'success', 'verified')` or `(kind is NULL and outcome == 'correct')`.
     - Excludes retrieval-only events.
     - Computes event age $t_j = \max(\Delta t / 3600, 0.001)$ in hours.
     - Returns $B = \ln(\sum t_j^{-d})$; defaults to $-10.0$ when no matching events exist.
   - Added `compute_p_need(home, memory_id, now=None, tau=0.0, s=1.0, d=0.5) -> float`:
     - Computes $P_{\text{need}} = \text{sigmoid}((B - \tau) / s)$ with input clamped to $[-40, 40]$ to prevent math overflow.
   - Updated `decay_pass`:
     - Uses ACT-R base activation $B$ when activations exist: HOT when $B > 0$ (requires `status='current'` and `evidence_grade in ('VERIFIED', 'TESTED')`), WARM when $-3 < B \le 0$, COLD when $B \le -3$.
     - Preserves manual-only archiving, protected rules (`status='current' and evidence_grade='VERIFIED'` or title keywords), and never deletes evidence.
     - Retains legacy TTL/retrieval fallback for memories with no recorded activation history, preserving full backwards compatibility.

3. **Semantic Scoring** (`src/second_brain/semantic.py`):
   - In `_score_row`: replaced `freshness * decision_value` term with `(0.5 + P_need)`.
   - Retained all other terms: `relevance`, `trust`, `scope`, `negative`, `token`.

4. **AutoInject Gate** (`src/second_brain/autoinject.py`):
   - In `prepare_injection`: filtered candidate items in `fresh` before `_fit_budget` using $P_{\text{need}} \times \text{value} < \text{token\_cost\_ratio}$, where:
     - $\text{value} = \text{trust} \times \text{relevance}$
     - $\text{token\_cost\_ratio} = \text{item\_tokens} / \max(1, \text{active\_budget.target\_tokens})$
     - Items with insufficient ROI relative to token cost are skipped.
   - Preserved all T1.2/T1.4 safety gates (abstention, freshness, contradiction).

5. **Test Coverage** (`tests/test_activation.py`):
   - `test_activation_ignores_retrieval_only_events`: proved `record_retrieval` leaves $B$ and `storage_strength` unchanged, while `record_activation(..., kind="used")` increments them.
   - `test_recent_used_memory_outranks_old`: proved a recently used memory obtains higher $B$ and outranks an older memory with identical text.
   - `test_low_need_high_cost_item_skipped`: proved an item with low $P_{\text{need}}$ and high token cost ratio is skipped in `prepare_injection` under `CONTEXT_PRESSURE`, and admitted when recently activated.
   - `test_boundary_and_overflow`: verified fallback to $-10.0$, $t_j = 0$ clamping, and sigmoid $[-40, 40]$ overflow bounds.
   - `test_decay_pass_actr_heat_transitions`: verified ACT-R base activation thresholds in `decay_pass`.

## Verification
- Environment: Python 3.13.7 in `.venv\Scripts\python.exe` with `PYTHONPATH=src`.
- Ran focused test suites:
  - `tests/test_activation.py`: 5 passed
  - `tests/test_reconsolidation.py`: 12 passed
  - `tests/test_semantic.py`: 18 passed
  - `tests/test_autoinject.py` (excluding pre-existing hardcoded version test): 36 passed
  - `tests/test_hybrid_retrieval.py`: 12 passed
  - Total: 83 passed, 0 failures.
- No `uv.lock` generated.

## Qualification Limitations
No live LLM runtime experiment was executed; verification was conducted through deterministic database unit and integration tests with synthetic time offsets and exact token budget accounting.
