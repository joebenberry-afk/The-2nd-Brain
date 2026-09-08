"""Focused T7.9 Full governed self-improvement rollout lifecycle tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_brain import build_identity, credit, db, decisions, promotion
from second_brain.errors import BrainError


def test_candidate_cannot_skip_rollout_stage(brain_home: Path) -> None:
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


def _record_bound_observation(
    brain_home: Path,
    feature: str,
    observed_data: dict,
    *,
    artifact_overrides: dict | None = None,
    caller_classification: str = "observed",
) -> dict:
    intervention = credit.record_intervention(
        brain_home,
        "routing_policy",
        f"policy:{feature}",
        {
            "metric": "tokens_delta",
            "expected_delta": -10.0,
            "direction": "decrease",
            "expected_range": [-11.0, -9.0],
            "horizon": 1,
            "confidence": 0.95,
            "evaluator": "test-evaluator",
        },
        "baseline:control",
    )
    repo = Path(__file__).resolve().parents[1]
    artifact = {
        "classification": "observed",
        "qualification_eligible": True,
        "feature": feature,
        "target_ref": f"policy:{feature}",
        "source_commit": build_identity.git_sha(repo),
        "source_tree_sha256": build_identity.source_tree_fingerprint(repo),
        "config_sha256": build_identity.configuration_fingerprint(brain_home),
        "observed_data": observed_data,
    }
    artifact.update(artifact_overrides or {})
    path = brain_home / "qualification" / f"{feature}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return credit.record_observation(
        brain_home,
        intervention["intervention_id"],
        observed_data,
        path.relative_to(brain_home).as_posix(),
        "benchmark",
        evidence_classification=caller_classification,
    )


def test_caller_cannot_relabel_arbitrary_file_observed(brain_home: Path) -> None:
    observed = {
        "tokens_delta": -20.0,
        "effect": 10.0,
        "design": "paired",
        "verdict": "POSITIVE",
    }
    intervention = credit.record_intervention(
        brain_home,
        "routing_policy",
        "policy:arbitrary-file",
        {
            "metric": "tokens_delta",
            "expected_delta": -10.0,
            "direction": "decrease",
            "expected_range": [-11.0, -9.0],
            "horizon": 1,
            "confidence": 0.95,
            "evaluator": "test-evaluator",
        },
        "baseline:control",
    )
    arbitrary_path = brain_home / "qualification" / "arbitrary.json"
    arbitrary_path.parent.mkdir(parents=True, exist_ok=True)
    arbitrary_path.write_text('{"unrelated":"file"}', encoding="utf-8")
    arbitrary = credit.record_observation(
        brain_home,
        intervention["intervention_id"],
        observed,
        arbitrary_path.relative_to(brain_home).as_posix(),
        "benchmark",
        evidence_classification="observed",
    )
    assert arbitrary["qualification_eligible"] is False
    assert arbitrary["observed_data"]["_evidence"]["classification"] == "unknown"


@pytest.mark.parametrize(
    "artifact_classification",
    ["simulation", "simulated", "fixture", "mechanism", "unknown"],
)
def test_caller_cannot_relabel_nonproduction_artifact_observed(
    brain_home: Path, artifact_classification: str
) -> None:
    observed = {
        "tokens_delta": -20.0,
        "effect": 10.0,
        "design": "paired",
        "verdict": "POSITIVE",
    }
    observation = _record_bound_observation(
        brain_home,
        f"relabelled-{artifact_classification}",
        observed,
        artifact_overrides={"classification": artifact_classification},
        caller_classification="observed",
    )
    assert observation["qualification_eligible"] is False
    assert observation["observed_data"]["_evidence"]["classification"] == artifact_classification


@pytest.mark.parametrize(
    "artifact_overrides",
    [
        {"target_ref": "policy:other-feature"},
        {"source_commit": "0" * 40},
        {"source_tree_sha256": "0" * 64},
        {"config_sha256": "0" * 64},
        {
            "observed_data": {
                "tokens_delta": -999.0,
                "effect": 999.0,
                "design": "paired",
                "verdict": "POSITIVE",
            }
        },
    ],
)
def test_observation_artifact_must_match_target_metrics_and_current_build(
    brain_home: Path, artifact_overrides: dict
) -> None:
    feature = "bound-credit"
    observation = _record_bound_observation(
        brain_home,
        feature,
        {
            "tokens_delta": -20.0,
            "effect": 10.0,
            "design": "paired",
            "verdict": "POSITIVE",
        },
        artifact_overrides=artifact_overrides,
    )
    assert observation["qualification_eligible"] is False
    for stage in ("SHADOW", "ADVISORY", "CANARY"):
        promotion.transition_rollout_stage(brain_home, feature, stage, reason="mechanism")
    with pytest.raises(BrainError, match="cannot authorize promotion"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="mismatched artifact",
            credit_observation_id=observation["observation_id"],
        )
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"


def test_promotion_requires_persisted_credit_and_real_verifier_artifact(
    brain_home: Path,
) -> None:
    feature = "action_cache_v2"
    for stage in ("SHADOW", "ADVISORY", "CANARY"):
        promotion.transition_rollout_stage(brain_home, feature, stage, reason="mechanism")

    with pytest.raises(BrainError, match="persisted credit observation"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="Caller supplied no independently resolvable evidence",
        )
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"


def test_tampered_credit_artifact_cannot_authorize_active(brain_home: Path) -> None:
    feature = "tampered-artifact"
    observation = _record_bound_observation(
        brain_home,
        feature,
        {
            "tokens_delta": -20.0,
            "effect": 10.0,
            "design": "paired",
            "verdict": "POSITIVE",
        },
    )
    assert observation["qualification_eligible"] is True
    evidence_path = brain_home / observation["observed_data"]["_evidence"]["path"]
    evidence_path.write_text('{"tampered":true}', encoding="utf-8")
    for stage in ("SHADOW", "ADVISORY", "CANARY"):
        promotion.transition_rollout_stage(brain_home, feature, stage, reason="mechanism")

    with pytest.raises(BrainError, match="stale or tampered"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="tampered artifact",
            credit_observation_id=observation["observation_id"],
        )
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"


def test_stored_credit_class_cannot_authorize_active(brain_home: Path) -> None:
    feature = "tampered-credit"
    observation = _record_bound_observation(
        brain_home,
        feature,
        {
            "tokens_delta": -20.0,
            "effect": 10.0,
            "design": "paired",
            "verdict": "POSITIVE",
        },
    )
    for stage in ("SHADOW", "ADVISORY", "CANARY"):
        promotion.transition_rollout_stage(brain_home, feature, stage, reason="mechanism")
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "UPDATE v2_observations SET credit_class = 'CONTRIBUTORY' WHERE observation_id = ?",
            (observation["observation_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(BrainError, match="credit class is tampered"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="stored credit edit",
            credit_observation_id=observation["observation_id"],
        )
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"


def test_stored_target_cannot_move_unrelated_credit_to_feature(brain_home: Path) -> None:
    observation = _record_bound_observation(
        brain_home,
        "unrelated-source",
        {
            "tokens_delta": -20.0,
            "effect": 10.0,
            "design": "paired",
            "verdict": "POSITIVE",
        },
    )
    feature = "target-victim"
    for stage in ("SHADOW", "ADVISORY", "CANARY"):
        promotion.transition_rollout_stage(brain_home, feature, stage, reason="mechanism")
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "UPDATE v2_interventions SET target_ref = ? WHERE intervention_id = ?",
            (f"policy:{feature}", observation["intervention_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(BrainError, match="intervention provenance is tampered"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="stored target edit",
            credit_observation_id=observation["observation_id"],
        )
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"


@pytest.mark.parametrize(
    "observed",
    [
        {"tokens_delta": 350.0, "effect": -350.0, "design": "paired", "verdict": "POSITIVE"},
        {"tokens_delta": 350.0},
    ],
)
def test_negative_candidate_is_held_or_demoted(
    brain_home: Path, observed: dict[str, float | str]
) -> None:
    """Intervention with verified negative effect refuses promotion and demotes candidate."""
    feature = "speculative_prefetch"

    # Advance to CANARY and persist the negative observation used by the gate.
    promotion.transition_rollout_stage(brain_home, feature, "SHADOW", reason="step 1")
    promotion.transition_rollout_stage(brain_home, feature, "ADVISORY", reason="step 2")
    promotion.transition_rollout_stage(brain_home, feature, "CANARY", reason="step 3")
    intervention = credit.record_intervention(
        brain_home,
        "speculative_prefetch",
        f"policy:{feature}",
        {
            "metric": "tokens_delta",
            "expected_delta": -100.0,
            "direction": "decrease",
            "expected_range": [-101.0, -99.0],
            "horizon": 1,
            "confidence": 0.95,
            "evaluator": "test-evaluator",
        },
        "simulation:baseline",
    )
    observation = credit.record_observation(
        brain_home,
        intervention["intervention_id"],
        observed,
        "simulation:negative-effect",
        "benchmark",
        evidence_classification="simulation",
    )
    demote_res = promotion.transition_rollout_stage(
        brain_home,
        feature,
        to_stage="ACTIVE",
        reason="Canary evidence shows token inflation",
        credit_observation_id=observation["observation_id"],
    )

    assert demote_res["promotion_refused"] is True
    assert demote_res["status"] == "HELD"
    assert demote_res["to_stage"] == "SHADOW"
    assert promotion.get_feature_stage(brain_home, feature) == "SHADOW"


def test_rollback_preserves_evidence_history(brain_home: Path) -> None:
    """Demotion writes an immutable event and preserves prior transitions."""
    feature = "tool_working_set_filter"
    promotion.transition_rollout_stage(brain_home, feature, "SHADOW", reason="start shadow")
    promotion.transition_rollout_stage(brain_home, feature, "ADVISORY", reason="advisory stage")
    promotion.transition_rollout_stage(brain_home, feature, "CANARY", reason="canary test")
    rollback = promotion.transition_rollout_stage(
        brain_home,
        feature,
        "SHADOW",
        reason="Canary alert triggered: edge case regression discovered",
        evidence_refs=["telemetry:canary-alert"],
    )
    assert rollback["status"] == "DEMOTED"
    assert promotion.get_feature_stage(brain_home, feature) == "SHADOW"
    events = promotion.list_rollout_events(brain_home, feature=feature)
    assert [(event["from_stage"], event["to_stage"]) for event in events] == [
        ("OFF", "SHADOW"),
        ("SHADOW", "ADVISORY"),
        ("ADVISORY", "CANARY"),
        ("CANARY", "SHADOW"),
    ]

    dec_rows = decisions.list_decisions(brain_home, kind="learning")
    assert len(dec_rows) >= 4
