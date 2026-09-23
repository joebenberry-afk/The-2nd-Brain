"""Brainstem recommendations affect Brain context, never host execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from second_brain import brainstem, capabilities, decisions
from second_brain.errors import BrainError


def test_missing_signals_do_not_claim_retrieval_evidence(brain_home: Path) -> None:
    result = brainstem.decide(brain_home, brainstem.BrainstemSignals())
    assert result.retrieve is False
    assert result.evict is False
    assert result.inject_budget == 500
    assert (
        result.decision_ref
        == decisions.list_decisions(brain_home, kind="brainstem")[-1]["decision_id"]
    )


@pytest.mark.parametrize(
    ("cap", "resident", "limit", "expected"),
    [
        (300, 0, 8000, 300),
        (199, 0, 8000, 0),
        (2000, 6000, 8000, 400),
        (2000, 6300, 8000, 0),
        (0, 0, 8000, 0),
        (2000, 0, 0, 0),
    ],
)
def test_injection_is_bounded_only_by_brain_context(
    brain_home: Path, cap: int, resident: int, limit: int, expected: int
) -> None:
    result = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(
            budget_tokens_cap=cap,
            resident_tokens=resident,
            context_token_limit=limit,
            task_class="implementation",
        ),
    )
    assert result.inject_budget == expected
    assert result.evict is (resident * 5 >= limit * 4)


def test_legacy_agent_spend_cannot_change_retrieval_or_model_choice(brain_home: Path) -> None:
    signal = {
        "budget_tokens_cap": 1000,
        "resident_tokens": 0,
        "context_token_limit": 8000,
        "task_class": "implementation",
    }
    baseline = brainstem.decide(brain_home, signal)
    legacy = brainstem.decide(
        brain_home,
        {
            **signal,
            "budget_tokens_used": 10**9,
            "budget_hard_cap": 0,
            "worker_pressure": 1.0,
            "provider_quota_remaining": 0,
        },
        learned_override={"route_floor": "premium", "scout_allowed": True},
    )
    assert legacy.retrieve is baseline.retrieve is True
    assert legacy.inject_budget == baseline.inject_budget == 1000
    assert "route_floor" not in legacy.to_dict()
    assert "scout_allowed" not in legacy.to_dict()


def test_learning_cannot_exceed_context_or_lower_evidence_floor(brain_home: Path) -> None:
    result = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(
            budget_tokens_cap=2000,
            resident_tokens=6000,
            context_token_limit=8000,
            risk_class="HIGH",
            task_class="implementation",
        ),
        learned_override={"inject_budget": 50000, "verify_level": "none"},
    )
    assert result.inject_budget == 400
    assert result.verify_level == "full"
    assert "OVERRIDE_VERIFY_FLOOR_REJECTED" in result.reason_codes


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("budget_tokens_cap", -1),
        ("budget_tokens_cap", True),
        ("resident_tokens", -1),
        ("context_token_limit", "8000"),
    ],
)
def test_invalid_context_measurements_refuse(brain_home: Path, field: str, value: object) -> None:
    with pytest.raises(BrainError):
        brainstem.decide(brain_home, {field: value})


def test_declared_host_support_cannot_qualify_injection(brain_home: Path) -> None:
    capabilities.declare(brain_home, "host", "prompt_injection", True, version="v1")
    result = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(task_class="implementation"),
        host_context={"harness_id": "host", "host_version": "v1", "config_binding": "cfg"},
    )
    assert result.inject_budget == 0
    assert "INJECTION_ABSTAINED_CAPABILITY_UNOBSERVED" in result.reason_codes


def test_observed_prompt_injection_is_host_bound_not_execution_permission(brain_home: Path) -> None:
    capabilities.observe(
        brain_home, "host", "brain_packet_delivered", version="v1", config_binding="cfg"
    )
    signals = brainstem.BrainstemSignals(
        task_class="implementation",
        budget_tokens_cap=700,
        resident_tokens=0,
        context_token_limit=8000,
    )
    current = brainstem.decide(
        brain_home,
        signals,
        host_context={"harness_id": "host", "host_version": "v1", "config_binding": "cfg"},
    )
    stale = brainstem.decide(
        brain_home,
        signals,
        host_context={"harness_id": "host", "host_version": "v2", "config_binding": "cfg"},
    )
    assert current.inject_budget == 700
    assert stale.inject_budget == 0
    assert current.retrieve is stale.retrieve is True
    assert "route_floor" not in current.to_dict()


def test_capability_snapshot_cannot_rebind_another_host(brain_home: Path) -> None:
    host = {"harness_id": "host", "host_version": "v1", "config_binding": "cfg"}
    snapshot = capabilities.snapshot(brain_home, **host)
    with pytest.raises(BrainError, match="does not match host context"):
        brainstem.decide(
            brain_home,
            brainstem.BrainstemSignals(task_class="implementation"),
            host_context={**host, "harness_id": "other"},
            capability_snapshot=snapshot,
        )
