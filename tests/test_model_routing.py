"""Focused tests for the P2.6 Brain-owned model decision layer."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from second_brain import model_routing


def _candidate(
    provider: str,
    model: str,
    *,
    tier: str,
    cost: str,
    roles: tuple[str, ...] = (),
    available: bool = True,
    max_risk: str = "CRITICAL",
    capabilities: tuple[str, ...] = (),
) -> model_routing.ModelCandidate:
    return model_routing.ModelCandidate(
        provider=provider,
        model=model,
        tier=tier,
        cost_class=cost,
        roles=roles,
        available=available,
        max_risk=max_risk,
        capabilities=capabilities,
    )


def test_decision_is_bounded_round_trippable_and_task_text_free() -> None:
    decision = model_routing.route_model(
        "routine task with private transcript that must not persist",
        [
            _candidate("provider-b", "balanced", tier="balanced", cost="medium"),
            _candidate("provider-a", "efficient", tier="efficient", cost="low"),
            _candidate("provider-c", "premium", tier="premium", cost="high"),
        ],
        role="dev",
        brain_session_id="brain-session",
        host_session_id="hermes-session",
        project_id="project",
        bot_name="Brain-Dev",
        created_at="2026-08-23T00:00:00+00:00",
    )

    payload = decision.to_dict()
    encoded = decision.canonical_json()
    assert decision.status == "selected"
    assert decision.selected_model == "efficient"
    assert len(decision.task_hash) == 16
    assert "private transcript" not in encoded
    assert len(encoded.encode("utf-8")) < 16_384
    assert model_routing.ModelDecision.from_dict(json.loads(encoded)) == decision
    assert decision.decision_id.startswith("model-decision-")
    assert payload["schema_version"] == model_routing.MODEL_ROUTING_SCHEMA_VERSION


def test_low_risk_routine_prefers_lowest_cost_and_does_not_escalate_premium() -> None:
    decision = model_routing.select_model(
        "summarize the README",
        [
            _candidate("p", "premium", tier="premium", cost="high"),
            _candidate("p", "efficient", tier="efficient", cost="low"),
            _candidate("p", "balanced", tier="balanced", cost="medium"),
        ],
        role="dev",
    )

    assert decision.selected_model == "efficient"
    assert decision.selected_tier == "efficient"
    assert decision.reason_code == "LOWEST_COST_ELIGIBLE"
    premium = next(item for item in decision.eligible_candidates if item.model == "premium")
    assert premium.eligible is False
    assert premium.exclusion_reason == "PREMIUM_NOT_JUSTIFIED"


def test_worker_cannot_force_premium_with_request_policy_knobs() -> None:
    decision = model_routing.route_model(
        "summarize the README",
        [
            _candidate("p", "efficient", tier="efficient", cost="low"),
            _candidate("p", "premium", tier="premium", cost="high"),
        ],
        role="worker",
        risk_class="CRITICAL",
        risk_level="CRITICAL",
        minimum_tier="premium",
        premium_authorized=True,
        premium_justification="security",
        repeated_failure=True,
        ambiguity=True,
        required_capabilities=("architecture",),
        min_quality_score=1.0,
    )

    assert decision.selected_model == "efficient"
    assert decision.risk_class == "LOW"
    premium = next(item for item in decision.eligible_candidates if item.model == "premium")
    assert premium.exclusion_reason == "PREMIUM_NOT_JUSTIFIED"


@pytest.mark.parametrize(
    "field",
    ("available", "policy_eligible", "eligible", "fallback_eligible", "risk_suitable"),
)
def test_candidate_assessment_rejects_non_boolean_flags(field: str) -> None:
    decision = model_routing.route_model(
        "routine task",
        [_candidate("p", "efficient", tier="efficient", cost="low")],
    )
    payload = decision.to_dict()["eligible_candidates"][0]
    payload[field] = "false"

    with pytest.raises(model_routing.ModelRoutingError, match="MALFORMED_DECISION"):
        model_routing.CandidateAssessment.from_dict(payload)


def test_fallback_validation_requires_selected_fallback_identity() -> None:
    decision = model_routing.route_model(
        "critical incident investigation",
        [
            _candidate("p", "premium", tier="premium", cost="high", available=False),
            _candidate("p", "balanced-fallback", tier="balanced", cost="medium"),
        ],
        role="validator",
        risk_class="HIGH",
    )

    with pytest.raises(model_routing.ModelRoutingError, match="MALFORMED_DECISION"):
        replace(decision, fallback_provider="wrong-provider").validate()
    with pytest.raises(model_routing.ModelRoutingError, match="MALFORMED_DECISION"):
        replace(decision, selected_tier="premium").validate()


def test_quality_stats_are_skipped_for_ambiguous_provider_model(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_routing.router,
        "route",
        lambda home, task: {"selected": ["skill"], "scores": {}},
    )
    calls = 0

    def report(home: Path, model_id: str, skill_name: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"models": [{"model_id": model_id, "outcomes": 2, "successes": 0}]}

    monkeypatch.setattr(model_routing.crossmodel, "model_skill_report", report)
    decision = model_routing.route_model(
        "routine task",
        [
            _candidate("provider-a", "shared", tier="balanced", cost="medium"),
            _candidate("provider-b", "shared", tier="balanced", cost="medium"),
        ],
        home=brain_home,
    )

    assert all(item.quality_score is None for item in decision.eligible_candidates)
    assert decision.selected_provider == "provider-a"
    assert calls == 0


def test_high_risk_signal_justifies_premium_escalation() -> None:
    decision = model_routing.route_model(
        "review a critical production architecture change",
        [
            _candidate("p", "balanced", tier="balanced", cost="medium", max_risk="CRITICAL"),
            _candidate(
                "p",
                "premium",
                tier="premium",
                cost="high",
                max_risk="CRITICAL",
                capabilities=("architecture",),
            ),
        ],
        role="integrator",
        risk_class="HIGH",
    )

    assert decision.selected_model == "premium"
    assert decision.selected_tier == "premium"
    assert decision.reason_code == "PREMIUM_ESCALATION_JUSTIFIED"
    assert decision.risk_class == "HIGH"
    assert decision.capability_requirements == ("architecture",)


def test_role_and_capability_constraints_are_hard_filters() -> None:
    decision = model_routing.select_model(
        "routine implementation",
        [
            _candidate(
                "p",
                "validator-only",
                tier="efficient",
                cost="low",
                roles=("validator",),
                capabilities=("coding",),
            ),
            _candidate(
                "p",
                "dev-model",
                tier="balanced",
                cost="medium",
                roles=("dev",),
                capabilities=("coding",),
            ),
        ],
        role="dev",
        required_capabilities=("coding",),
    )

    assert decision.selected_model == "dev-model"
    validator = next(
        item for item in decision.eligible_candidates if item.model == "validator-only"
    )
    assert validator.exclusion_reason == "ROLE_NOT_ALLOWED"


def test_unavailable_preferred_model_uses_explicit_declared_fallback() -> None:
    decision = model_routing.route_model(
        "critical incident investigation",
        [
            _candidate(
                "p",
                "premium",
                tier="premium",
                cost="high",
                available=False,
                max_risk="CRITICAL",
            ),
            _candidate(
                "p",
                "balanced-fallback",
                tier="balanced",
                cost="medium",
                max_risk="CRITICAL",
            ),
        ],
        role="validator",
        risk_class="HIGH",
    )

    assert decision.status == "selected"
    assert decision.fallback_used is True
    assert decision.original_selected_model == "premium"
    assert decision.selected_model == "balanced-fallback"
    assert decision.fallback_model == "balanced-fallback"
    assert decision.fallback_reason == "MODEL_UNAVAILABLE"
    assert decision.reason_code == "MODEL_UNAVAILABLE_FALLBACK"
    assert decision.to_dict()["fallback_used"] is True


def test_unavailable_model_without_fallback_is_explicit_failure() -> None:
    decision = model_routing.select_model(
        "critical incident investigation",
        [_candidate("p", "premium", tier="premium", cost="high", available=False)],
        role="validator",
        risk_class="HIGH",
    )

    assert decision.status == "failed"
    assert decision.failure_code == "NO_AVAILABLE_MODEL"
    assert decision.selected_model is None
    assert decision.original_selected_model == "premium"
    assert decision.fallback_used is False


def test_identical_inputs_have_stable_candidate_order_and_decision_id() -> None:
    candidates = [
        _candidate("b", "balanced", tier="balanced", cost="medium"),
        _candidate("a", "efficient", tier="efficient", cost="low"),
    ]
    kwargs: dict[str, Any] = {
        "role": "dev",
        "project_id": "project",
        "brain_session_id": "session",
        "created_at": "2026-08-23T00:00:00+00:00",
    }
    first = model_routing.select_model("same task", candidates, **kwargs)
    second = model_routing.select_model("same task", list(reversed(candidates)), **kwargs)

    assert first.decision_id == second.decision_id
    assert first.candidate_set_hash == second.candidate_set_hash
    assert [item.model for item in first.eligible_candidates] == ["efficient", "balanced"]
    assert first.canonical_json() == second.canonical_json()


def test_malformed_and_duplicate_candidates_are_rejected() -> None:
    with pytest.raises(model_routing.ModelRoutingError, match="MALFORMED_CANDIDATE"):
        model_routing.select_model("task", [{"provider": "p"}])
    candidate = _candidate("p", "same", tier="efficient", cost="low")
    with pytest.raises(model_routing.ModelRoutingError, match="DUPLICATE_CANDIDATE"):
        model_routing.select_model("task", [candidate, candidate])


def test_existing_router_surface_is_consumed_without_persisting_task_text(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_routing.router,
        "route",
        lambda home, task: {"selected": ["verification-skill"], "scores": {task: 1.0}},
    )
    decision = model_routing.select_model(
        "verify the bounded routing decision",
        [_candidate("p", "efficient", tier="efficient", cost="low")],
        home=brain_home,
        role="validator",
        created_at="2026-08-23T00:00:00+00:00",
    )

    assert decision.selected_routes == ("verification-skill",)
    assert decision.routing_error is False
    assert "verify the bounded routing decision" not in decision.canonical_json()
