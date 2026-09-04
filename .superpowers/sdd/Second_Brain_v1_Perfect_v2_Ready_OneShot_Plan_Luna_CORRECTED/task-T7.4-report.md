# T7.4 Task Report — Deterministic Brainstem Attention Controller

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 545–583.

## Files

- `src/second_brain/brainstem.py` (new)
- `tests/test_brainstem.py` (new)
- `scripts/run_brainstem_experiment.py` (new)
- `outputs/reports/v2/brainstem/brainstem-experiment.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.4-report.md` (new)

## Implemented contract

1. **Owner**:
   Created `src/second_brain/brainstem.py` as the attention, budget, and intervention coordinator approved in T7.0.

2. **Repository-True Structured Signals**:
   `BrainstemSignals` encapsulates the structured inputs without synthesizing artificial defaults:
   `budget_tokens_used`, `budget_tokens_cap`, `budget_hard_cap`, `cache_epoch`, `cache_is_cold`, `resident_tokens`, `context_token_limit`, `model_provider`, `model_name`, `model_tier`, `task_class`, `risk_class`, `retrieval_confidence`, `worker_pressure`, `recent_failures`, `provider_quota_remaining`.
   Missing signals remain `None`/`null`; conservative defaults are applied when signals are absent.

3. **Deterministic Decision Output**:
   `BrainstemDecision` outputs the required compact, deterministic fields:
   `{retrieve, inject_budget, route_floor, evict, verify_level, scout_allowed, reason_codes, decision_ref, rollout_stage}`.
   No free-form reasoning text is stored as canonical policy.

4. **Hard Budget & Safety Enforcement**:
   Adaptive learned overrides remain in `SHADOW` stage and can only alter bounded fields already represented in the deterministic decision.
   Bypass attempts are strictly refused:
   - `inject_budget` cannot exceed `budget_hard_cap`.
   - `verify_level` cannot downgrade below the deterministic floor (e.g. HIGH risk requires `full`).
   - `route_floor` cannot downgrade below risk requirements.

5. **Decision Ledger**:
   Every decision is recorded in `decisions` table with `kind="brainstem"`, inputs hash, and chosen configuration.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_brainstem.py -q
4 passed
```

Named tests verified:
- `test_brainstem_missing_signal_uses_conservative_default`: PASS (conservative non-escalated defaults applied when signals are missing)
- `test_brainstem_decision_is_deterministic`: PASS (identical inputs yield identical decisions, budget, verify level, and reason codes)
- `test_brainstem_records_decision`: PASS (logged in SQLite decisions table with kind='brainstem')
- `test_learned_override_cannot_bypass_hard_budget_or_authority`: PASS (hard budget cap 2500 tokens enforced against 50000 request; verify floor full enforced against none request)

## Cheapest real experiment

Script `scripts/run_brainstem_experiment.py` replayed 6 representative session telemetry scenarios (routine pilot, extreme context pressure, high risk security, trivial turn, exploratory scout, cold start with missing signals):

- **Total scenarios replayed**: 6
- **Concordance with manual expert decisions**: 6/6 (100.0%)
- **Replay determinism rate**: 1.0 (100.0%)
- **Safety bypass refusal rate**: 1.0 (100.0%)
- **Decisions recorded**: 7
- Artifact saved: `outputs/reports/v2/brainstem/brainstem-experiment.json`.

## Migration and rollback

Pure additive coordinator module and decision logging reusing existing `decisions` table (`kind="brainstem"` was pre-allocated in `decisions.py`).
Rollback is code-revert safe.

## Commit

Commit message: `brain(core): deterministic brainstem attention controller`.
