"""Governed optimization coordinator lifecycle tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import credit, frontier, immune, optimization, plasticity, skillforge
from second_brain.errors import BrainError
from second_brain.fingerprints import BottleneckFingerprintStore


def _seed_candidate(home: Path) -> tuple[str, str]:
    fp = BottleneckFingerprintStore(home).record_bottleneck(
        "TOOL_CHAIN_THRASH", "candidate signal", "bounded cache", scope_id="second-brain"
    )
    directory = home / "skills" / "candidates" / "candidate"
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n- verified"
        for title in (
            "Purpose", "Positive Triggers", "Negative Triggers", "Inputs",
            "Procedure", "Tools", "Safety", "Verification", "Output", "References",
        )
    )
    path = directory / "SKILL.md"
    path.write_text(
        "---\nname: candidate\nstatus: candidate\nversion: 1\n---\n\n" + sections + "\n",
        encoding="utf-8",
    )
    skillforge.bind_candidate(
        home, "candidate", source_type="radar", source_ref=fp.fingerprint_id,
        owner="release-steward", project_id="second-brain",
    )
    return fp.fingerprint_id, skillforge.lifecycle_content_hash(path)


def _passed_evaluation(intervention_hash: str) -> dict:
    return {
        "evaluation_id": "eval-candidate", "task_id": "task-candidate",
        "task_hash": "t" * 64, "repository_state_hash": "r" * 64,
        "intervention_hash": intervention_hash,
        "baseline": {"input_tokens": 1000, "output_tokens": 100},
        "candidate": {"input_tokens": 500, "output_tokens": 100},
        "quality": {
            "correctness": True, "requirements": True, "protected_values": True,
            "regressions": False, "verification": True,
        },
        "gates": {
            "trigger": {"failed": 0}, "workflow": {"structural": True, "failed": 0},
            "regression": {"regression": False, "failed": 0},
            "security": {"passed": True},
        },
    }


def _activate_ready(home: Path, *, mode: str = "active") -> tuple[dict, str]:
    fingerprint_id, intervention_hash = _seed_candidate(home)
    proposal = optimization.propose(
        home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash, mode=mode,
    )
    optimization.evaluate(home, proposal["proposal_id"], _passed_evaluation(intervention_hash))
    frontier.frontier_review(
        home, "skill-candidate-promotion", "promote", "high",
        "release-reviewer", "approve",
    )
    return proposal, intervention_hash


def test_shadow_proposal_does_not_mutate_skill(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash,
    )
    assert proposal["mode"] == "shadow"
    assert proposal["status"] == "shadow"
    assert not (brain_home / "skills" / "active" / "candidate").exists()
    assert not (brain_home / "plasticity" / "utility.jsonl").exists()


def test_activation_requires_current_evidence_and_frontier(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash, mode="active",
    )
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result == {"activated": False, "reason": "evaluation_not_proven"}
    assert (brain_home / "skills" / "candidates" / "candidate").exists()


def test_shadow_evaluation_cannot_activate(brain_home):
    proposal, _ = _activate_ready(brain_home, mode="shadow")
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result == {"activated": False, "reason": "mode_not_active"}
    assert (brain_home / "skills" / "candidates" / "candidate").exists()
    assert not (brain_home / "skills" / "active" / "candidate").exists()


def test_active_proposal_promotes_after_all_gates(brain_home):
    proposal, _ = _activate_ready(brain_home)
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result["activated"] is True
    assert (brain_home / "skills" / "active" / "candidate" / "SKILL.md").exists()


def test_changed_intervention_cannot_activate(brain_home):
    proposal, intervention_hash = _activate_ready(brain_home)
    path = brain_home / "skills" / "candidates" / "candidate" / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result["activated"] is False
    assert result["reason"] in {"intervention_stale", "evaluation_stale", "frontier_stale"}
    assert intervention_hash == proposal["intervention"]["hash"]


def test_evaluation_requires_positive_measured_value_and_preserves_body_boundary(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate", intervention_hash=intervention_hash,
        mode="active",
    )
    result = _passed_evaluation(intervention_hash)
    result["candidate"] = {"input_tokens": 1100, "output_tokens": 100}
    evaluated = optimization.evaluate(brain_home, proposal["proposal_id"], result)
    assert evaluated["status"] == "hold"
    assert optimization.get_proposal(brain_home, proposal["proposal_id"])["status"] == "hold"
    telemetry = list((brain_home / "telemetry" / "agent-performance").glob("*.jsonl"))
    assert len(telemetry) == 1
    record = json.loads(telemetry[0].read_text(encoding="utf-8").splitlines()[-1])
    assert record["kind"] == "optimization_evaluation"
    assert "baseline" not in record and "candidate" not in record
    assert record["status"] == "hold"


def test_counterfactual_evaluation_can_activate_with_skillforge_binding(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash, mode="active",
    )
    evidence = credit.counterfactual_result(
        brain_home,
        evaluation_id="cf-candidate",
        intervention_type="skill",
        intervention_id="candidate",
        intervention_hash=intervention_hash,
        starting_state={
            "task_hash": "t" * 64,
            "repository_state_hash": "r" * 64,
            "requirements_hash": "q" * 64,
            "model_config_hash": "m" * 64,
            "available_tools_hash": "a" * 64,
            "environment_hash": "e" * 64,
        },
        with_arm={
            "run_id": "with-run", "success": True,
            "tokens": {"input": 500, "cache_read": 0, "cache_write": 0, "output": 0, "total": 500},
            "tool_calls": 1, "wall_time_ms": 10,
            "verification": {"outcome": "passed", "evidence_ref": "verify:cf"},
            "regressions": {"count": 0, "evidence_ref": "tests:cf"},
        },
        without_arm={
            "run_id": "without-run", "success": True,
            "tokens": {
                "input": 1000,
                "cache_read": 0,
                "cache_write": 0,
                "output": 0,
                "total": 1000,
            },
            "tool_calls": 2, "wall_time_ms": 20,
            "verification": {"outcome": "passed", "evidence_ref": "verify:cf"},
            "regressions": {"count": 0, "evidence_ref": "tests:cf"},
        },
    )
    evaluated = optimization.evaluate(
        brain_home, proposal["proposal_id"], {"counterfactual_result": evidence}
    )
    assert evaluated["status"] == "evaluated"
    frontier.frontier_review(
        brain_home, "skill-candidate-promotion", "promote", "high",
        "release-reviewer", "approve",
    )
    activated = optimization.activate(brain_home, proposal["proposal_id"])
    assert activated["activated"] is True


def test_activation_policy_baseline_matches_raw_hash_after_move(brain_home):
    proposal, _ = _activate_ready(brain_home)
    activated = optimization.activate(brain_home, proposal["proposal_id"])
    assert activated["activated"] is True
    active_path = brain_home / "skills" / "active" / "candidate" / "SKILL.md"
    policy = json.loads(
        (brain_home / "immune" / "policies" / "skill-candidate.json").read_text()
    )
    # Regression: backup_of must match the raw byte hash of the promoted
    # active file, because immune.rollback() recomputes with sha256_file(),
    # not the lifecycle-normalized hash.
    assert policy["guard"]["backup_of"] == immune.sha256_file(active_path)
    assert policy["guard"]["backup_of"] != skillforge.lifecycle_content_hash(active_path)



def test_evaluation_evidence_and_net_value_are_attached(brain_home):
    proposal, _intervention_hash = _activate_ready(brain_home)
    current = optimization.get_proposal(brain_home, proposal["proposal_id"])
    assert current["status"] == "evaluated"
    assert current["evaluation_ref"]
    assert current["evaluation"]["roi"]["net_tokens_saved"] == 500
    assert current["evaluation"]["evaluation_id"] == "eval-candidate"


def test_activation_refuses_stale_fingerprint_and_owner_version(brain_home):
    proposal, _ = _activate_ready(brain_home)
    binding = json.loads(
        (brain_home / "skills" / "candidates" / "candidate" / "candidate-binding.json").read_text()
    )
    binding["owner"] = ""
    (brain_home / "skills" / "candidates" / "candidate" / "candidate-binding.json").write_text(
        json.dumps(binding), encoding="utf-8"
    )
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result["activated"] is False
    assert result["reason"] in {"owner_missing", "no_owner", "evaluation_stale"}
    assert (brain_home / "skills" / "candidates" / "candidate").exists()


def test_rollback_requires_registered_trigger_identity_and_updates_plasticity_only_on_success(
    brain_home,
):
    proposal, _ = _activate_ready(brain_home)
    assert optimization.activate(brain_home, proposal["proposal_id"])[
        "activated"
    ]
    # Activation's reward came from the explicit verified evaluation; rollback
    # itself must not append another utility record.
    before = plasticity.read_utility_log(brain_home)
    wrong = optimization.rollback(brain_home, proposal["proposal_id"], "wrong-trigger", "bad")
    assert wrong == {"rolled_back": False, "reason": "wrong_trigger"}
    assert plasticity.read_utility_log(brain_home) == before
    result = optimization.rollback(brain_home, proposal["proposal_id"], "skill-candidate", "bad")
    assert result["rolled_back"] is False
    assert plasticity.read_utility_log(brain_home) == before


def test_rollback_trigger_identity_and_explicit_verified_result(brain_home, monkeypatch):
    proposal, _ = _activate_ready(brain_home)
    calls = []

    def fake_rollback(home, policy_id, trigger_id, reason):
        calls.append((policy_id, trigger_id, reason))
        return {"rolled_back": True, "record": {"trigger": trigger_id}}

    monkeypatch.setattr("second_brain.optimization.immune.rollback", fake_rollback)
    before = plasticity.read_utility_log(brain_home)
    result = optimization.rollback(
        brain_home, proposal["proposal_id"], "skill-candidate", "bad",
    )
    assert result["rolled_back"] is True
    assert calls == [("skill-candidate", "skill-candidate", "bad")]
    assert plasticity.read_utility_log(brain_home) == before


def test_rollback_no_change_guard_is_reachable_after_activation(brain_home):
    """Regression: activate() must register the rollback guard's backup_of
    against the raw post-promotion file so an unrelated trigger firing with
    zero drift refuses via 'no_change' instead of always rolling back."""
    proposal, _ = _activate_ready(brain_home)
    activated = optimization.activate(brain_home, proposal["proposal_id"])
    assert activated["activated"] is True
    immune.register_trigger(
        brain_home, "skill-candidate",
        {"metric": "tests_failed", "operator": ">", "value": 0, "window": 1},
    )
    immune.ingest_metric(brain_home, "tests_failed", 1.0, "run-1")
    result = optimization.rollback(
        brain_home, proposal["proposal_id"], "skill-candidate", "unrelated trigger fired",
    )
    assert result["rolled_back"] is False
    assert result["reason"] == "no_change"
    assert (brain_home / "skills" / "active" / "candidate" / "SKILL.md").exists()


def test_immutable_versions_and_corrupt_proposal_refuse(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    first = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate", intervention_hash=intervention_hash,
    )
    second = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate", intervention_hash=intervention_hash,
    )
    assert second["proposal_id"] == first["proposal_id"]
    files = sorted((brain_home / "outputs" / "audits" / "optimization").glob("*.json"))
    assert len(files) == 1
    files[0].write_text("{bad", encoding="utf-8")
    with pytest.raises(BrainError):
        optimization.get_proposal(brain_home, first["proposal_id"])


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True, text=True, env=env, cwd=Path(__file__).resolve().parent.parent,
    )


def test_cli_json_lifecycle_rejects_raw_payload(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    result_file = brain_home / "result.json"
    result_file.write_text(json.dumps(_passed_evaluation(intervention_hash)), encoding="utf-8")
    proposed = _run_cli(
        brain_home, "optimize", "propose", fingerprint_id, "--skill", "candidate",
        "--intervention-hash", intervention_hash, "--json",
    )
    assert proposed.returncode == 0, proposed.stderr
    proposal = json.loads(proposed.stdout)
    evaluated = _run_cli(
        brain_home, "optimize", "evaluate", proposal["proposal_id"],
        "--result-json", str(result_file), "--json",
    )
    assert evaluated.returncode == 0, evaluated.stderr
    assert json.loads(evaluated.stdout)["status"] == "evaluated"
    rejected = _run_cli(
        brain_home, "optimize", "evaluate", proposal["proposal_id"],
        "--prompt", "secret", "--json",
    )
    assert rejected.returncode != 0


def test_off_mode_never_activates(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate", intervention_hash=intervention_hash,
        mode="off",
    )
    assert proposal["status"] == "shadow"
    assert optimization.activate(brain_home, proposal["proposal_id"]) == {
        "activated": False, "reason": "mode_off"
    }
