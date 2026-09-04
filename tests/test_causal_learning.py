"""Focused T7.5 Prediction-error and causal learning loop tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from second_brain import credit, db, decisions
from second_brain.errors import BrainError


def test_prediction_error_requires_prior_expectation(brain_home: Path) -> None:
    """Every adaptive intervention requires a measurable prior expected outcome before execution."""
    # 1. Reject empty or non-measurable expectation when recording intervention
    with pytest.raises(BrainError, match="measurable expected_outcome"):
        credit.record_intervention(
            brain_home,
            intervention_type="routing_policy",
            target_ref="policy:cache_eviction",
            expected_outcome={},  # Empty expectation!
            baseline_ref="baseline:session-001",
        )

    # 2. Reject intervention record without measurable keys
    with pytest.raises(BrainError, match="measurable expected_outcome"):
        credit.record_intervention(
            brain_home,
            intervention_type="routing_policy",
            target_ref="policy:cache_eviction",
            expected_outcome={"note": "hope it runs faster"},  # Not measurable!
            baseline_ref="baseline:session-001",
        )


def test_model_self_report_is_not_observation(brain_home: Path) -> None:
    """Observations must originate from telemetry, test runner, or benchmark, never model self-assertion."""
    intv = credit.record_intervention(
        brain_home,
        intervention_type="prompt_compaction",
        target_ref="prompt:system_prefix",
        expected_outcome={"metric": "token_delta", "expected_delta": -150.0},
        baseline_ref="baseline:session-002",
    )

    # Reject model self report
    with pytest.raises(BrainError, match="Model self-report is not an observation"):
        credit.record_observation(
            brain_home,
            intervention_id=intv["intervention_id"],
            observed_data={"token_delta": -140.0},
            evidence_ref="claim:model-self-report",
            evidence_type="model_assertion",  # Forbidden!
        )

    with pytest.raises(BrainError, match="Model self-report is not an observation"):
        credit.record_observation(
            brain_home,
            intervention_id=intv["intervention_id"],
            observed_data={"token_delta": -140.0},
            evidence_ref="claim:model-self-report",
            evidence_type="self_report",  # Forbidden!
        )


def test_surprise_creates_candidate_not_active_policy(brain_home: Path) -> None:
    """Surprise from verified evidence creates a candidate policy in SHADOW, not active policy mutation."""
    intv = credit.record_intervention(
        brain_home,
        intervention_type="cache_bypass",
        target_ref="policy:retrieval_bypass",
        expected_outcome={"metric": "latency_ms", "expected_delta": -25.0},
        baseline_ref="baseline:session-003",
    )

    # Valid telemetry observation with material surprise & positive effect
    obs = credit.record_observation(
        brain_home,
        intervention_id=intv["intervention_id"],
        observed_data={
            "latency_ms": -80.0,  # Expected -25, got -80 (large surprise)
            "effect": 55.0,
            "design": "paired",
            "verdict": "POSITIVE",
        },
        evidence_ref="telemetry:run-003",
        evidence_type="telemetry",
    )

    assert obs["surprise_score"] >= 0.2
    assert obs["credit_class"] == "DIRECT"
    action = obs["candidate_action"]
    assert action["action"] == "propose_candidate_update"
    # Rule 5: Policy changes become candidates in SHADOW, never active policy!
    assert action["rollout_stage"] == "SHADOW"

    # Verify decision logged in decisions ledger
    recs = decisions.list_decisions(brain_home, kind="learning")
    assert len(recs) >= 2  # 1 for intervention, 1 for observation
    obs_dec = recs[-1]
    assert obs_dec["rollout_stage"] == "SHADOW"
    assert obs_dec["chosen"]["candidate_action"] == "propose_candidate_update"


def test_negative_effect_can_demote_candidate(brain_home: Path) -> None:
    """Interventions yielding verified negative effects produce demote_candidate actions."""
    intv = credit.record_intervention(
        brain_home,
        intervention_type="aggressive_preloading",
        target_ref="candidate:preload_rule",
        expected_outcome={"metric": "token_delta", "expected_delta": -100.0},
        baseline_ref="baseline:session-004",
    )

    # Observation shows negative effect (regressed tokens by +350)
    obs = credit.record_observation(
        brain_home,
        intervention_id=intv["intervention_id"],
        observed_data={
            "token_delta": 350.0,
            "effect": -350.0,  # Negative effect!
            "design": "paired",
            "verdict": "POSITIVE",  # Verified negative effect
        },
        evidence_ref="telemetry:run-004",
        evidence_type="telemetry",
    )

    assert obs["credit_class"] == "UNRELATED_NEGATIVE"
    action = obs["candidate_action"]
    assert action["action"] == "demote_candidate"
    assert action["rollout_stage"] == "SHADOW"
    assert action["reason"] == "negative_causal_effect"
