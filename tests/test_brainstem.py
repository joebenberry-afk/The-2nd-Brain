"""Focused T7.4 Brainstem attention/intervention coordinator tests."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import ModuleType

import pytest

from second_brain import brainstem, decisions
from second_brain.errors import BrainError


def test_brainstem_missing_signal_uses_conservative_default(brain_home: Path) -> None:
    """Missing signals produce conservative, non-escalated defaults."""
    empty_signals = brainstem.BrainstemSignals()
    decision = brainstem.decide(brain_home, empty_signals)

    assert decision.retrieve is False
    assert decision.inject_budget == 500
    assert decision.route_floor == "T0"
    assert decision.evict is False
    assert decision.verify_level == "targeted"
    assert decision.scout_allowed is False
    assert "CONSERVATIVE_DEFAULTS_APPLIED" in decision.reason_codes


def test_brainstem_decision_is_deterministic(brain_home: Path) -> None:
    """Identical signals produce identical decisions and reason codes."""
    signals = brainstem.BrainstemSignals(
        budget_tokens_used=1200,
        budget_tokens_cap=2500,
        budget_hard_cap=4000,
        resident_tokens=7000,
        context_token_limit=8000,
        task_class="debugging",
        risk_class="HIGH",
    )

    dec1 = brainstem.decide(brain_home, signals)
    dec2 = brainstem.decide(brain_home, signals)

    assert dec1.retrieve == dec2.retrieve
    assert dec1.inject_budget == dec2.inject_budget
    assert dec1.route_floor == dec2.route_floor
    assert dec1.evict == dec2.evict
    assert dec1.verify_level == dec2.verify_level
    assert dec1.scout_allowed == dec2.scout_allowed
    assert dec1.reason_codes == dec2.reason_codes


def test_brainstem_records_decision(brain_home: Path) -> None:
    """Every brainstem decision is recorded in the decisions ledger with kind='brainstem'."""
    signals = brainstem.BrainstemSignals(
        task_class="implementation",
        risk_class="LOW",
        budget_tokens_cap=1500,
    )
    decision = brainstem.decide(brain_home, signals)

    assert decision.decision_ref is not None
    rows = decisions.list_decisions(brain_home, kind="brainstem")
    assert len(rows) >= 1
    logged = rows[-1]
    assert logged["decision_id"] == decision.decision_ref
    assert logged["kind"] == "brainstem"
    assert logged["chosen"]["route_floor"] == decision.route_floor
    assert logged["chosen"]["verify_level"] == decision.verify_level
    assert logged["inputs"]["task_class"] == "implementation"


def test_learned_override_cannot_bypass_budget_or_authority(brain_home: Path) -> None:
    signals = brainstem.BrainstemSignals(
        budget_tokens_used=1800,
        budget_tokens_cap=2000,
        budget_hard_cap=2500,
        resident_tokens=1000,
        context_token_limit=8000,
        risk_class="HIGH",
        task_class="implementation",
    )

    decision = brainstem.decide(
        brain_home,
        signals,
        learned_override={
            "inject_budget": 50000,
            "verify_level": "none",
            "route_floor": "cheap",
        },
    )

    assert decision.inject_budget == 700
    assert any(
        "OVERRIDE_BUDGET_CAPPED_AT_APPLICABLE_LIMIT" in reason for reason in decision.reason_codes
    )
    assert decision.verify_level == "full"
    assert "OVERRIDE_VERIFY_FLOOR_REJECTED" in decision.reason_codes
    assert decision.route_floor == "T2"
    assert "OVERRIDE_ROUTE_FLOOR_REJECTED" in decision.reason_codes


def test_budget_nearly_exhausted_abstains(brain_home: Path) -> None:
    decision = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(
            budget_tokens_used=2990,
            budget_tokens_cap=2000,
            budget_hard_cap=3000,
            resident_tokens=0,
            context_token_limit=8000,
        ),
    )

    assert decision.inject_budget == 0
    assert "INJECTION_ABSTAINED_BELOW_USEFUL_MINIMUM:10" in decision.reason_codes


@pytest.mark.parametrize("used", [3000, 3001])
def test_budget_exhausted_or_over_abstains(brain_home: Path, used: int) -> None:
    decision = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(
            budget_tokens_used=used,
            budget_tokens_cap=2000,
            budget_hard_cap=3000,
            resident_tokens=0,
            context_token_limit=8000,
        ),
    )

    assert decision.inject_budget == 0


def test_explicit_zero_disables_allowance_but_missing_uses_policy_default(
    brain_home: Path,
) -> None:
    missing = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(task_class="implementation"),
    )
    zero_operation = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(task_class="implementation", budget_tokens_cap=0),
    )
    zero_total = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(task_class="implementation", budget_hard_cap=0),
    )
    zero_context = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(task_class="implementation", context_token_limit=0),
    )

    assert missing.inject_budget == 500
    assert zero_operation.inject_budget == 0
    assert zero_total.inject_budget == 0
    assert zero_context.inject_budget == 0
    missing_override = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(),
        learned_override={"inject_budget": 50000},
    )

    assert missing_override.inject_budget == 500


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        (
            brainstem.BrainstemSignals(
                budget_tokens_used=0,
                budget_tokens_cap=300,
                budget_hard_cap=3000,
                resident_tokens=0,
                context_token_limit=8000,
            ),
            300,
        ),
        (
            brainstem.BrainstemSignals(
                budget_tokens_used=2600,
                budget_tokens_cap=2000,
                budget_hard_cap=3000,
                resident_tokens=0,
                context_token_limit=8000,
            ),
            400,
        ),
        (
            brainstem.BrainstemSignals(
                budget_tokens_used=0,
                budget_tokens_cap=2000,
                budget_hard_cap=3000,
                resident_tokens=6000,
                context_token_limit=8000,
            ),
            400,
        ),
        (
            brainstem.BrainstemSignals(
                budget_tokens_used=0,
                budget_tokens_cap=199,
                budget_hard_cap=3000,
                resident_tokens=0,
                context_token_limit=8000,
            ),
            0,
        ),
    ],
)
def test_budget_is_bounded_by_each_applicable_allowance(
    brain_home: Path,
    signals: brainstem.BrainstemSignals,
    expected: int,
) -> None:
    assert brainstem.decide(brain_home, signals).inject_budget == expected


def test_pressure_and_override_paths_obey_final_allowance(brain_home: Path) -> None:
    pressure = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(
            budget_tokens_used=2990,
            budget_tokens_cap=2000,
            budget_hard_cap=3000,
            resident_tokens=7000,
            context_token_limit=8000,
        ),
    )
    override = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(
            budget_tokens_used=2300,
            budget_tokens_cap=2000,
            budget_hard_cap=3000,
            resident_tokens=1000,
            context_token_limit=8000,
        ),
        learned_override={"inject_budget": 50000},
    )
    below_minimum_override = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(
            budget_tokens_used=0,
            budget_tokens_cap=2000,
            budget_hard_cap=3000,
            resident_tokens=0,
            context_token_limit=8000,
        ),
        learned_override={"inject_budget": 199},
    )

    assert pressure.evict is True
    assert pressure.inject_budget == 0
    assert override.inject_budget == 700
    assert below_minimum_override.inject_budget == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("budget_tokens_used", -1),
        ("budget_tokens_cap", math.inf),
        ("budget_hard_cap", math.nan),
        ("resident_tokens", True),
        ("context_token_limit", "8000"),
    ],
)
def test_budget_inputs_reject_invalid_token_counts(
    brain_home: Path,
    field: str,
    value: object,
) -> None:
    with pytest.raises(BrainError):
        brainstem.decide(
            brain_home,
            {field: value},
        )


@pytest.mark.parametrize("value", [-1, math.inf, math.nan, True, "500"])
def test_override_budget_rejects_invalid_token_counts(
    brain_home: Path,
    value: object,
) -> None:
    with pytest.raises(BrainError):
        brainstem.decide(
            brain_home,
            brainstem.BrainstemSignals(),
            learned_override={"inject_budget": value},
        )


def test_budget_invariant_across_bounded_ranges(brain_home: Path) -> None:
    for hard_cap in (0, 10, 199, 200, 500):
        for used in (0, 10, 200, 600):
            for operation_cap in (0, 199, 200, 700):
                decision = brainstem.decide(
                    brain_home,
                    brainstem.BrainstemSignals(
                        budget_tokens_used=used,
                        budget_tokens_cap=operation_cap,
                        budget_hard_cap=hard_cap,
                        resident_tokens=6200,
                        context_token_limit=8000,
                    ),
                )
                allowance = min(
                    operation_cap,
                    max(0, hard_cap - used),
                    200,
                )
                assert 0 <= decision.inject_budget <= allowance
                assert decision.inject_budget == 0 or decision.inject_budget >= 200


def _load_brainstem_experiment() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_brainstem_experiment.py"
    spec = importlib.util.spec_from_file_location("run_brainstem_experiment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_experiment_caller_keeps_shadow_decisions_observational(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _load_brainstem_experiment()
    output = tmp_path / "brainstem-experiment.json"
    monkeypatch.setattr(experiment, "OUTPUT_PATH", output)

    manifest = experiment.run_brainstem_experiment()

    assert output.is_file()
    assert all(
        scenario["decision"]["rollout_stage"] == "SHADOW" for scenario in manifest["scenarios"]
    )
    assert manifest["adversarial_override_proof"]["actual_budget"] == 500
