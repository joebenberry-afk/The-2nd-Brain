"""Run the governed self-improvement mechanism simulation for T7.9.

This disposable-state runner exercises positive and negative state-machine paths.
It is explicitly ineligible for live economics, production activation, or release
qualification; the historical proof artifacts are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from second_brain import contracts, credit, db, promotion
from second_brain.errors import BrainError

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "reports" / "v2" / "v2-i"
SCENARIO_A_PATH = OUTPUT_DIR / "scenario-a-mechanism.json"
SCENARIO_B_PATH = OUTPUT_DIR / "scenario-b-mechanism.json"
QUALIFICATION_PATH = OUTPUT_DIR / "qualification-mechanism.json"


def run_scenario_a(home: Path) -> dict[str, Any]:
    """Exercise the positive mechanism without authorizing ACTIVE."""
    feature = "tool_working_set_reduction"
    evidence_ref = "simulation:tool-working-set-positive"
    intervention = credit.record_intervention(
        home,
        intervention_type="tool_working_set_optimization",
        target_ref=f"policy:{feature}",
        expected_outcome={
            "metric": "tokens_delta",
            "expected_delta": -200.0,
            "direction": "decrease",
            "expected_range": [-201.0, -199.0],
            "horizon": 1,
            "confidence": 0.95,
            "evaluator": "simulation-runner",
        },
        baseline_ref="simulation:baseline-arm-off",
        session_id="simulation-scenario-a",
    )
    observation = credit.record_observation(
        home,
        intervention_id=intervention["intervention_id"],
        observed_data={
            "tokens_delta": -250.0,
            "effect": 250.0,
            "design": "paired",
            "verdict": "POSITIVE",
        },
        evidence_ref=evidence_ref,
        evidence_type="benchmark",
        evidence_classification="simulation",
        evaluator_ref="simulation-runner",
        session_id="simulation-scenario-a",
    )

    promotion.transition_rollout_stage(
        home, feature, "SHADOW", reason="Begin simulated shadow evaluation"
    )
    promotion.transition_rollout_stage(
        home, feature, "ADVISORY", reason="Exercise simulated advisory transition"
    )
    promotion.transition_rollout_stage(
        home, feature, "CANARY", reason="Exercise simulated canary transition"
    )
    refusal = None
    try:
        promotion.transition_rollout_stage(
            home,
            feature,
            "ACTIVE",
            reason="Simulation must not activate production behavior",
            credit_observation_id=observation["observation_id"],
        )
    except BrainError as exc:
        refusal = str(exc)
    assert refusal is not None
    assert promotion.get_feature_stage(home, feature) == "CANARY"

    return {
        "scenario": "Scenario A — Positive Mechanism Simulation",
        "classification": "simulation",
        "qualification_eligible": False,
        "live_economics_eligible": False,
        "production_activation_eligible": False,
        "feature": feature,
        "proof_path": [
            "observe_simulation",
            "candidate",
            "isolate",
            "evaluate_mechanism",
            "shadow",
            "advisory",
            "canary",
            "refuse_active_without_real_evidence",
        ],
        "evidence": {
            "source_evidence": evidence_ref,
            "intervention_id": intervention["intervention_id"],
            "observation_id": observation["observation_id"],
            "credit_class": observation["credit_class"],
            "qualification_eligible": observation["qualification_eligible"],
            "active_refusal": refusal,
            "final_stage": promotion.get_feature_stage(home, feature),
        },
        "rollout_transitions": promotion.list_rollout_events(home, feature=feature),
        "conclusion": "SHADOW: positive mechanism exercised; real promotion remains unqualified.",
    }


def run_scenario_b(home: Path) -> dict[str, Any]:
    """Exercise negative-evidence refusal and rollback in disposable state."""
    feature = "speculative_prefetch_injection"
    intervention = credit.record_intervention(
        home,
        intervention_type="speculative_prefetch",
        target_ref=f"policy:{feature}",
        expected_outcome={
            "metric": "latency_ms",
            "expected_delta": -50.0,
            "direction": "decrease",
            "expected_range": [-51.0, -49.0],
            "horizon": 1,
            "confidence": 0.95,
            "evaluator": "simulation-runner",
        },
        baseline_ref="simulation:prefetch-arm-off",
        session_id="simulation-scenario-b",
    )
    promotion.transition_rollout_stage(home, feature, "SHADOW", reason="Simulated shadow")
    promotion.transition_rollout_stage(home, feature, "ADVISORY", reason="Simulated advisory")
    promotion.transition_rollout_stage(home, feature, "CANARY", reason="Simulated canary")
    observation = credit.record_observation(
        home,
        intervention_id=intervention["intervention_id"],
        observed_data={
            "latency_ms": 120.0,
            "effect": -120.0,
            "design": "paired",
            "verdict": "POSITIVE",
        },
        evidence_ref="simulation:negative-effect",
        evidence_type="benchmark",
        evidence_classification="simulation",
        evaluator_ref="simulation-runner",
        session_id="simulation-scenario-b",
    )
    demotion = promotion.transition_rollout_stage(
        home,
        feature,
        "ACTIVE",
        reason="Exercise negative-evidence refusal",
        credit_observation_id=observation["observation_id"],
    )
    assert demotion["promotion_refused"] is True
    assert promotion.get_feature_stage(home, feature) == "SHADOW"

    return {
        "scenario": "Scenario B — Negative Mechanism Simulation",
        "classification": "simulation",
        "qualification_eligible": False,
        "live_economics_eligible": False,
        "production_activation_eligible": False,
        "feature": feature,
        "evidence": {
            "intervention_id": intervention["intervention_id"],
            "observation_id": observation["observation_id"],
            "credit_class": observation["credit_class"],
            "demotion_event": demotion,
            "final_stage": promotion.get_feature_stage(home, feature),
        },
        "rollout_transitions": promotion.list_rollout_events(home, feature=feature),
        "conclusion": "SHADOW: negative mechanism exercised and evidence preserved.",
    }


def run_proof() -> dict[str, Any]:
    temp_dir = Path(tempfile.mkdtemp(prefix="second_brain_p79_mechanism_"))
    try:
        db.migrate(db.db_path(temp_dir))
        scenario_a = run_scenario_a(temp_dir)
        scenario_b = run_scenario_b(temp_dir)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        SCENARIO_A_PATH.write_text(json.dumps(scenario_a, indent=2), encoding="utf-8")
        SCENARIO_B_PATH.write_text(json.dumps(scenario_b, indent=2), encoding="utf-8")

        now = datetime.now(UTC).isoformat()
        artifact_hash = hashlib.sha256(
            (contracts.canonical_json(scenario_a) + contracts.canonical_json(scenario_b)).encode(
                "utf-8"
            )
        ).hexdigest()
        report = {
            "phase": "v2-i",
            "requirement": "governed_self_improvement_proof",
            "status": "SHADOW",
            "classification": "simulation",
            "qualification_eligible": False,
            "live_economics_eligible": False,
            "production_activation_eligible": False,
            "ledger_recorded": False,
            "supersedes_claim_without_overwriting": [
                "scenario-a-promoted.json",
                "scenario-b-rollback.json",
                "qualification.json",
            ],
            "scenarios": {
                "positive_mechanism": True,
                "negative_refusal_mechanism": True,
                "production_active": False,
            },
            "artifact_hash": artifact_hash,
            "generated_at": now,
        }
        QUALIFICATION_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote Scenario A mechanism evidence to {SCENARIO_A_PATH}")
        print(f"Wrote Scenario B mechanism evidence to {SCENARIO_B_PATH}")
        print(f"Wrote ineligible mechanism report to {QUALIFICATION_PATH}")
        return report
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_proof()
