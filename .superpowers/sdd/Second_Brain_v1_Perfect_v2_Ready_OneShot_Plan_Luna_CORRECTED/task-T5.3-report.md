# T5.3 — Off-policy evaluation

## Summary
Implemented off-policy evaluation (OPE) via Inverse Propensity Scoring (IPS) and Self-Normalized Inverse Propensity Scoring (SNIPS) over replayable logged decision records, added additive migration `0017_decision_inputs.sql` for durable input context persistence, updated `decisions.py` with `list_decisions` and `inputs_json` storage, implemented `ope_ips` in `economics.py`, and added the `brainctl v2 learn ope` CLI subcommand in `cli.py` with an ESS $\ge 30$ safety gate.

Key changes:
1. **Database Migration** (`src/second_brain/migrations/0017_decision_inputs.sql`):
   - Added `ALTER TABLE decisions ADD COLUMN inputs_json TEXT;`.
   - Backward-compatible: existing rows retain `NULL` without data loss or re-indexing issues.

2. **Decisions Persistence & Querying** (`src/second_brain/decisions.py`):
   - In `record(...)`: stored canonical `inputs_json` into the newly created `inputs_json` column on `INSERT OR IGNORE INTO decisions`, with `_MAX_METADATA_BYTES` bound enforcement.
   - Added `list_decisions(home, *, kind=None, session_id=None, limit=None) -> list[dict[str, Any]]`: queries the `decisions` table in chronological order (`ORDER BY created_at ASC, rowid ASC`), automatically parsing JSON fields (`chosen_json`, `alternatives_json`, `inputs_json`, `outcome_json`) into Python objects while preserving raw string representations.

3. **Off-Policy Evaluation** (`src/second_brain/economics.py`):
   - Added `ope_ips(decisions: Sequence[Mapping[str, Any]], target_policy: Any) -> dict[str, Any]`.
   - Resolves context $x_i$ (`inputs` or `inputs_json`), action $a_i$ (`chosen` or `chosen_json`), logging propensity $p_i$ (defaulting to 1.0), and reward $r_i$ (defaulting to 0.0).
   - Target policy evaluation:
     - If `callable(target_policy)`: executes `pred_a = target_policy(x_i)` and checks structural / canonical equality against $a_i$.
     - If `str`: built-in policies:
       - `"logging"` / `"current"`: identity matching ($a_i$).
       - `"always_inject"` / `"inject"`: delivery matching (empty alternatives / `withheld_id is None`).
       - `"holdout"`: holdout matching (non-empty alternatives / `withheld_id is not None`).
   - Propensity clipping: $\max(p_i, 0.05)$ to prevent infinite variance.
   - Importance weights: $w_i = \frac{\mathbb{I}[\text{target\_policy}(x_i) == a_i]}{\max(p_i, 0.05)}$ (or 0.0 on mismatch).
   - Estimators:
     - IPS: $V = \frac{1}{n} \sum_{i=1}^n w_i \cdot r_i$ (0.0 if $n=0$).
     - SNIPS: $V_{snips} = \frac{\sum w_i \cdot r_i}{\sum w_i}$ (0.0 if $\sum w = 0$).
     - ESS: $\frac{(\sum w_i)^2}{\sum w_i^2}$ (0.0 if $\sum w^2 = 0$).
   - Returns deterministic bounded dictionary: `{"value": V, "value_snips": V_snips, "n": n, "ess": ESS, "weights_sum": sum(w)}`.

4. **CLI Interface & Safety Gate** (`src/second_brain/cli.py`):
   - Registered `v2 learn ope` subcommand with arguments:
     - `--kind` (default: `"retrieval"`, validated against `decisions._DECISION_KINDS`).
     - `--policy` (required string).
     - `--json` (flag for machine-readable JSON output).
   - Queried `decisions.list_decisions(home, kind=args.kind)` and evaluated `economics.ope_ips(records, args.policy)`.
   - ESS Gate (< 30):
     - When `ess < 30`: prints `INSUFFICIENT_LOGGED_DATA (ess={ess:.1f} < 30, n={n})` (or canonical JSON with `"status": "INSUFFICIENT_LOGGED_DATA"`) and exits with return code 1. Prevents unjustified policy promotion from sparse/unreliable data.
     - When `ess >= 30`: prints human-readable OPE report (or canonical JSON with `"status": "OK"`) and exits with return code 0.

5. **Test Coverage** (`tests/test_ope.py`, `tests/test_decisions.py`):
   - `test_ips_recovers_logging_policy_value`: verified that when `target_policy` is the logging policy (or callable matching actions), IPS value and SNIPS value equal the sample average reward.
   - `test_ess_reported`: verified that ESS calculation strictly matches $(\sum w)^2 / \sum w^2$ over constructed weight distributions.
   - `test_empty_and_zero_weight_safe_handling`: verified safe handling of $n=0$ and all-zero weights.
   - `test_propensity_clipping_bound`: verified clipping to 0.05 prevents weight divergence.
   - `test_builtin_policies_always_inject_and_holdout`: verified delivery vs holdout matches for built-in policy names.
   - `test_record_and_list_decisions_roundtrip`: verified durable roundtrip of `inputs_json` and evaluation through `ope_ips`.
   - `test_cli_ope_insufficient_logged_data_boundary`: verified CLI returns 1 and outputs `INSUFFICIENT_LOGGED_DATA` when ESS < 30 (both text and JSON modes).
   - `test_cli_ope_sufficient_logged_data_success`: verified CLI returns 0 and outputs `OK` / report when ESS $\ge 30$ (both text and JSON modes).

## Verification
- Environment: Python in `.venv\Scripts\python.exe` with `PYTHONHOME` cleared, `PYTHONPATH=src`.
- Ran focused test suites:
  - `tests/test_ope.py`: 8 passed
  - `tests/test_decisions.py`: 6 passed
  - `tests/test_economics.py`: 22 passed
  - `tests/test_holdout.py`: 4 passed
  - `tests/test_db.py`: 8 passed
  - `tests/test_cli.py`: 38 passed
  - Total: 86 passed, 0 failures.
- Verified no `uv.lock` generated.

## Real-Evidence Limitations
Verification was conducted using deterministic synthetic replay fixtures, programmatic databases, and simulated holdout records; evaluating real-world counterfactual retrieval policies with high confidence requires accumulating production canary telemetry to meet the ESS $\ge 30$ threshold.
