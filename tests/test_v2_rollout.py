"""Focused T7.9 Full governed self-improvement rollout lifecycle tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from second_brain import decisions, promotion
from second_brain.errors import BrainError


def test_candidate_cannot_skip_rollout_stage(brain_home: Path) -> None:
    """Features must advance adjacent (OFF -> SHADOW -> ADVISORY -> CANARY -> ACTIVE). Skipping is refused."""
    feature = "retrieval_intelligence_v2"

    # Initially OFF
    assert promotion.get_feature_stage(brain_home, feature) == "OFF"

    # Attempt to skip directly from OFF to ACTIVE: REFUSED!
    with pytest.raises(BrainError, match="Cannot skip rollout stages"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            to_stage="ACTIVE",
            reason="Skip directly to active without canary",
        )

    # Attempt to skip from OFF to CANARY: REFUSED!
    with pytest.raises(BrainError, match="Cannot skip rollout stages"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            to_stage="CANARY",
            reason="Skip to canary",
        )

    # Valid adjacent transition: OFF -> SHADOW
    ev1 = promotion.transition_rollout_stage(
        brain_home,
        feature,
        to_stage="SHADOW",
        reason="Activate shadow observation",
        evidence_refs=["evidence:t05-baseline"],
    )
    assert ev1["status"] == "PROMOTED"
    assert promotion.get_feature_stage(brain_home, feature) == "SHADOW"

    # Attempt to skip from SHADOW to ACTIVE: REFUSED!
    with pytest.raises(BrainError, match="Cannot skip rollout stages"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            to_stage="ACTIVE",
            reason="Skip directly to active from shadow",
        )


def test_promotion_requires_credit_and_verifier(brain_home: Path) -> None:
    """Promotion to ACTIVE strictly requires verified causal credit AND independent verifier pass."""
    feature = "action_cache_v2"

    # Advance sequentially to CANARY
    promotion.transition_rollout_stage(brain_home, feature, "SHADOW", reason="step 1")
    promotion.transition_rollout_stage(brain_home, feature, "ADVISORY", reason="step 2")
    promotion.transition_rollout_stage(brain_home, feature, "CANARY", reason="step 3")
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"

    # 1. Attempt CANARY -> ACTIVE without credit: REFUSED!
    with pytest.raises(BrainError, match="requires causal credit DIRECT or CONTRIBUTORY"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="Promote without credit",
            credit_class=None,
            verifier_passed=True,
        )

    # 2. Attempt CANARY -> ACTIVE with CORRELATED credit (insufficient): REFUSED!
    with pytest.raises(BrainError, match="requires causal credit DIRECT or CONTRIBUTORY"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="Promote with only correlated credit",
            credit_class="CORRELATED",
            verifier_passed=True,
        )

    # 3. Attempt CANARY -> ACTIVE with DIRECT credit but NO verifier pass: REFUSED!
    with pytest.raises(BrainError, match="requires an independent verifier pass"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="Promote without verifier pass",
            credit_class="DIRECT",
            verifier_passed=False,
        )

    # 4. Valid promotion: DIRECT credit + verifier_passed=True -> SUCCEEDS!
    prom = promotion.transition_rollout_stage(
        brain_home,
        feature,
        "ACTIVE",
        reason="Verified positive paired economics and verifier qualification pass",
        credit_class="DIRECT",
        verifier_passed=True,
        evidence_refs=["telemetry:t05-paired-pass", "verifier:qualification-pass"],
    )
    assert prom["status"] == "PROMOTED"
    assert prom["to_stage"] == "ACTIVE"
    assert promotion.get_feature_stage(brain_home, feature) == "ACTIVE"


def test_negative_candidate_is_held_or_demoted(brain_home: Path) -> None:
    """Intervention with verified negative effect refuses promotion and demotes candidate."""
    feature = "speculative_prefetch"

    # Advance to CANARY
    promotion.transition_rollout_stage(brain_home, feature, "SHADOW", reason="step 1")
    promotion.transition_rollout_stage(brain_home, feature, "ADVISORY", reason="step 2")
    promotion.transition_rollout_stage(brain_home, feature, "CANARY", reason="step 3")

    # Observed negative effect (regressed tokens during canary evaluation)
    demote_res = promotion.transition_rollout_stage(
        brain_home,
        feature,
        to_stage="ACTIVE",
        reason="Canary telemetry shows 40% token inflation",
        credit_class="UNRELATED_NEGATIVE",
        evidence_refs=["telemetry:canary-token-regression"],
    )

    assert demote_res["promotion_refused"] is True
    assert demote_res["status"] == "HELD"
    assert demote_res["to_stage"] == "SHADOW"
    assert promotion.get_feature_stage(brain_home, feature) == "SHADOW"


def test_rollback_preserves_evidence_history(brain_home: Path) -> None:
    """Demotion and rollback write immutable event records and preserve all historical decisions."""
    feature = "tool_working_set_filter"

    # Sequence: OFF -> SHADOW -> ADVISORY -> CANARY -> ACTIVE -> demote to SHADOW
    promotion.transition_rollout_stage(brain_home, feature, "SHADOW", reason="start shadow")
    promotion.transition_rollout_stage(brain_home, feature, "ADVISORY", reason="advisory stage")
    promotion.transition_rollout_stage(brain_home, feature, "CANARY", reason="canary test")
    promotion.transition_rollout_stage(
        brain_home,
        feature,
        "ACTIVE",
        reason="promote",
        credit_class="DIRECT",
        verifier_passed=True,
    )
    assert promotion.get_feature_stage(brain_home, feature) == "ACTIVE"

    # Rollback from ACTIVE to SHADOW
    rollback = promotion.transition_rollout_stage(
        brain_home,
        feature,
        "SHADOW",
        reason="Canary alert triggered: edge case regression discovered",
        evidence_refs=["telemetry:canary-alert"],
    )
    assert rollback["status"] == "DEMOTED"
    assert rollback["to_stage"] == "SHADOW"
    assert promotion.get_feature_stage(brain_home, feature) == "SHADOW"

    # Verify that all 5 rollout events remain preserved in the audit log
    events = promotion.list_rollout_events(brain_home, feature=feature)
    assert len(events) == 5
    transitions = [(e["from_stage"], e["to_stage"]) for e in events]
    expected_transitions = [
        ("OFF", "SHADOW"),
        ("SHADOW", "ADVISORY"),
        ("ADVISORY", "CANARY"),
        ("CANARY", "ACTIVE"),
        ("ACTIVE", "SHADOW"),
    ]
    assert transitions == expected_transitions

    # Decisions log retains entries for every transition
    dec_rows = decisions.list_decisions(brain_home, kind="learning")
    assert len(dec_rows) >= 5
