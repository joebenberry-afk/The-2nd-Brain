# T5.2 — Retrieval injection holdout

## Summary
Implemented retrieval injection holdout in `autoinject.py` and `decisions.py`, adding randomized holdouts on advisory retrieval items for low-risk task classes when rollout stage is at or above CANARY, with replayable decision logging and session finalization outcome tracking.

Key changes:
1. **Contracts & Dataclasses** (`src/second_brain/contracts.py`):
   - Added `NoInjectionReason.HOLDOUT = "HOLDOUT"`.
   - Added `authority: str = "advisory"` attribute to `PacketItem` with backward-compatible defaults in `PacketItem(...)` and `PacketItem.from_dict()`.

2. **Decisions Logging** (`src/second_brain/decisions.py`):
   - Added `record_outcome = set_outcome` alias to support outcome recording on decision identities.

3. **Rollout Stage and Epsilon Helpers** (`src/second_brain/autoinject.py`):
   - Added `_ROLLOUT_STAGE_RANKS = {"OFF": 0, "SHADOW": 1, "ADVISORY": 2, "CANARY": 3, "ACTIVE": 4}`.
   - Added `_retrieval_holdout_stage(home)`: reads `SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE` or `config/v2.toml [rollout] retrieval_holdout` (defaults to `"SHADOW"`).
   - Added `_retrieval_holdout_epsilon(home)`: reads `SECOND_BRAIN_HOLDOUT_EPSILON` or `[retrieval_holdout] epsilon` from `config/v2.toml` / `config/retrieval.toml` (defaults to `0.1`).

4. **Holdout Pipeline Execution** (`src/second_brain/autoinject.py`):
   - Added `seed: Any = None` and `random_fn: Callable[[], float] | None = None` to `prepare_injection` and `BrainLifecycle.prepare_injection` for deterministic control in tests and replays.
   - Preserved all upstream gates: soft budget check, project filtering, cascade retrieval, validity filtering, freshness resolution, role profile filtering, confidence gate, delivery dedupe, contradiction resolution, and ACT-R need-cost ROI filtering.
   - Evaluated 3 holdout eligibility predicates after budget fit:
     1. Stage eligibility: stage rank $\ge$ CANARY rank (3). Stages `OFF`, `SHADOW`, and `ADVISORY` never hold out.
     2. Task class eligibility: `model_routing.classify_task(intent.task_text)` must be strictly one of `trivial`, `navigation`, `implementation`. Other classes (`debugging`, `verification`, `exploration`, `high_risk`, `continuation`) or tasks with `risk_class in ("HIGH", "CRITICAL")` never hold out.
     3. Authority eligibility: `intent.lane != "policy"`, and every selected item has `authority == "advisory"` and `row.get("authority_ceiling") in ("advisory", None, "")`. Items with `policy` or `project_rule` ceiling never hold out.
   - When eligible and items exist:
     - With probability epsilon: withhold top candidate (`withheld = selected[0]`, `delivered = selected[1:]`), record decision with `kind="retrieval"`, `chosen=[i.memory_id for i in delivered]`, `alternatives=[withheld.memory_id]`, `propensity=epsilon`, `randomized=True`, `policy_version="v5.2"`, `stage=stage`, `inputs={"task_sha256": ..., "withheld_id": withheld.memory_id, "task_class": t_class.value}`.
     - If `delivered` is empty: return `BrainInjectionDecision(decision=NO_INJECTION, reason=NoInjectionReason.HOLDOUT, selected_ids=[])`.
     - If `delivered` has items: deliver remaining items in packet and delivery ledger.
     - When holdout is not triggered: record delivery decision with `chosen=[i.memory_id for i in selected]`, `alternatives=[]`, `propensity=1.0 - epsilon`, `randomized=True`, and deliver all selected items.
   - When ineligible: deliver all selected items without recording a holdout decision.

5. **Session Finalization** (`src/second_brain/autoinject.py`):
   - Updated `finalize_session(self, *, tool_call_args=None, final_message=None, session_id=None, acceptance_passed: bool | None = None, tokens_total: int | None = None)`.
   - Queries `decisions` for this session where `kind = 'retrieval' AND outcome_json IS NULL`.
   - Computes `tokens_total` using explicit argument, or from `<home>/telemetry/agent-performance/<session>.jsonl` via `governor._session_total_tokens` with fallback line-level parser.
   - Sets `reward = 1.0 if acceptance_passed else 0.0`.
   - Records outcome via `decisions.record_outcome(self._home, dec_id, outcome={"acceptance_passed": bool(acceptance_passed), "tokens_total": tokens_total}, reward=reward)`.
   - Preserves existing `_record_activation_feedback` and `session_finalized` telemetry.

6. **Test Coverage** (`tests/test_holdout.py`):
   - `test_holdout_never_when_stage_below_canary`: verified holdout never fires when rollout stage is `OFF`, `SHADOW`, or `ADVISORY`, and verified it fires when stage is `CANARY`.
   - `test_holdout_only_on_advisory_items_and_low_risk_classes`: verified holdout only fires on advisory items and trivial/navigation/implementation task classes; verified non-advisory items (`project_rule`, `policy`), policy lane, or debugging/verification/exploration/continuation/high_risk tasks never hold out.
   - `test_holdout_deterministic_seed_and_single_item`: verified deterministic random function, propensities (0.2 and 0.8), and single-item holdout returning `NoInjectionReason.HOLDOUT`.
   - `test_finalize_session_updates_retrieval_decisions`: verified `outcome_json` recording with reward 1.0 for passed acceptance, 0.0 for failed acceptance, and token parsing from session telemetry files.

## Verification
- Environment: Python in `.venv\Scripts\python.exe` with `PYTHONPATH=src`.
- Ran focused test suites:
  - `tests/test_holdout.py`: 4 passed
  - `tests/test_decisions.py`: 6 passed
  - `tests/test_autoinject.py`: 37 passed
  - `tests/test_autoinject_codex.py`: 12 passed
  - `tests/test_contracts.py`: 36 passed
  - Total: 95 passed, 0 failures.
- No `uv.lock` generated.

## Real-Evidence Limitations
Verification was conducted through deterministic database unit and integration tests using mocked seeds, synthetic session telemetry, and exact SQLite decision queries; real LLM live agent-loop performance differences between held-out and delivered sessions require subsequent online canary measurement and telemetry ingestion.
