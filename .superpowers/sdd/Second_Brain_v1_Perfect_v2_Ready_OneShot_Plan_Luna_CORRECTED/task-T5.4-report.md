# T5.4 — Design-derived credit classes

## Summary
Implemented design-derived causal credit classification (`DIRECT`, `CONTRIBUTORY`, `CORRELATED`, `UNRELATED_NEGATIVE`) in `credit.py`, cleanly renamed `credit.counterfactual_eval` to `credit.routing_counterfactual` without deprecated aliases or shims, updated promotion guard G1 in `promotion.py` to strictly require at least one `DIRECT` or `CONTRIBUTORY` credit event, and added comprehensive test coverage in `tests/test_credit_classes.py`.

Key changes:
1. **Design-Derived Credit Classification** (`src/second_brain/credit.py`):
   - Added `CreditClass(enum.StrEnum)` supporting case-insensitive equality (`c == "direct"`, `c == "DIRECT"`, `c == CreditClass.DIRECT`).
   - Added `classify_credit(evidence: Mapping[str, Any] | Any) -> str` implementing exact plan rules:
     - Non-mapping inputs default safely to `CORRELATED`.
     - Paired design with negative effect ($< 0$) classifies as `UNRELATED_NEGATIVE`.
     - Paired design with interaction (`interaction_significant`, `interaction_term`, `has_interaction`, or `significant_interaction`) classifies as `CONTRIBUTORY` if `verdict != "INSUFFICIENT"`, else `CORRELATED`.
     - Holdout or paired designs with `verdict != "INSUFFICIENT"` classify as `DIRECT`.
     - All other designs (observational, other, or insufficient evidence) classify as `CORRELATED`.
     - Supports verdicts embedded either at top level or nested under `economics.verdict`.

2. **Clean Rename of `counterfactual_eval` to `routing_counterfactual`**:
   - In `src/second_brain/credit.py`: renamed `def counterfactual_eval` to `def routing_counterfactual`. Updated internal callers (`eval_skill_credit`) and module docstrings.
   - Enforced zero deprecated aliases: `hasattr(credit, "counterfactual_eval")` is strictly `False`.
   - In `src/second_brain/cli.py`: updated CLI invocation in `cmd_credit` to `credit.routing_counterfactual`.
   - In `tests/test_credit.py`: updated test calls to `credit.routing_counterfactual`.

3. **Promotion Guard G1 Causal Requirement** (`src/second_brain/promotion.py`):
   - Added `_causal_credit_count(home: Path, skill_name: str) -> int`, querying `credit_events` where `subject_id = ? AND LOWER(credit_level) IN ('direct', 'contributory')`.
   - Updated `_evidence_counts` to track `credit_events`, `causal_credit_events`, and `model_skill_outcomes`.
   - Updated `_guard_checks`: `guards["evidence"] = _causal_credit_count(home, skill_name) >= 1`.
   - Mere `model_skill_outcomes` or `correlated` credit events no longer satisfy G1 evidence. Upward adjacent promotion strictly requires proven causal credit.
   - Preserved all other gates: G2 frontier approve, G3 immune rollback check, version monotonic increment, and baseline-vs-candidate evaluation checks.

4. **Test Coverage** (`tests/test_credit_classes.py`):
   - `test_observational_evidence_is_correlated`: verified non-mapping inputs, observational designs, holdout/paired with `verdict="INSUFFICIENT"`, and paired with interaction but insufficient verdict all evaluate to `CORRELATED`.
   - `test_holdout_evidence_can_be_direct`: verified holdout with sufficient verdict produces `DIRECT`, paired with negative effect produces `UNRELATED_NEGATIVE`, paired with interaction produces `CONTRIBUTORY`, and verified string/enum equality and case insensitivity.
   - `test_promotion_requires_causal_credit`: verified that a skill with no evidence, only `model_skill_outcomes`, or only `correlated` credit fails G1 (`guards["evidence"] is False`, reason `"no_evidence"`), while a skill with `contributory` or `direct` credit satisfies G1 and promotes successfully.
   - `test_routing_counterfactual_clean_rename_no_alias`: verified absence of `counterfactual_eval` attribute, presence of `routing_counterfactual`, and correct execution.

## Verification
- Environment: Python in `.venv/Scripts/python.exe` with `PYTHONHOME` cleared and `PYTHONPATH=src`.
- Focused test suites executed:
  - `tests/test_credit_classes.py`: 4 passed
  - `tests/test_credit.py`: 24 passed
  - `tests/test_promotion.py`: 31 passed
  - `tests/test_decisions.py`: 6 passed
  - Total: 65 passed, 0 failures in 9.55s.
- Verified no `uv.lock` generated.

## Real-Evidence Limitations
Credit classification logic evaluates structured evidence payloads produced by evaluation protocols (e.g. holdout or paired designs); in production deployments, gathering statistically valid paired and holdout evidence requires running controlled A/B canary runs before claiming causal credit.
