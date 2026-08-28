"""Current P3.11 Skill Forge lifecycle contract tests."""

import hashlib
import json

from second_brain import promotion, skillforge


def _radar_candidate(brain_home):
    radar_dir = brain_home / "state" / "radar"
    radar_dir.mkdir(parents=True)
    candidate = {
        "candidate_id": "candidate-live-read",
        "candidate_type": "REPEATED_READ",
        "project_id": "second-brain",
        "reason_codes": ["REPEATED_READ"],
        "promotion_eligible": False,
        "status": "candidate",
        "telemetry_evidence_refs": [
            {"telemetry_ref": "live-session.jsonl:4", "record_hash": "a" * 64}
        ],
        "observations": [
            {
                "observation_id": "observation-live-read",
                "session_id": "live-session",
                "telemetry_evidence_refs": [
                    {"telemetry_ref": "live-session.jsonl:4", "record_hash": "a" * 64}
                ],
            }
        ],
    }
    (radar_dir / "candidates.json").write_text(
        json.dumps([candidate]), encoding="utf-8"
    )
    return candidate


def _forge(brain_home, owner="second-brain-radar-steward"):
    source = _radar_candidate(brain_home)
    path = skillforge.forge_radar_candidate(
        brain_home,
        source["candidate_id"],
        name="read-reuse",
        project_id=source["project_id"],
        owner=owner,
    )
    return path


def test_forge_radar_candidate_persists_stable_bounded_binding(brain_home):
    config = brain_home / "config" / "skills.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[skills]\n", encoding="utf-8")
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    source = _radar_candidate(brain_home)

    first = skillforge.forge_radar_candidate(
        brain_home,
        source["candidate_id"],
        name="read-reuse",
        project_id=source["project_id"],
        owner="second-brain-radar-steward",
    )
    second = skillforge.forge_radar_candidate(
        brain_home,
        source["candidate_id"],
        name="read-reuse",
        project_id=source["project_id"],
        owner="second-brain-radar-steward",
    )

    assert first == second
    assert first == brain_home / "skills" / "candidates" / "read-reuse" / "SKILL.md"
    binding = json.loads(
        (first.parent / "candidate-binding.json").read_text(encoding="utf-8")
    )
    assert binding["candidate_id"].startswith("skill-candidate-")
    assert binding["source_radar_candidate_id"] == source["candidate_id"]
    assert binding["owner"] == "second-brain-radar-steward"
    assert binding["source_type"] == "radar"
    assert binding["source_ref"] == source["candidate_id"]
    assert promotion.promotion_status(brain_home)["skills"]["read-reuse"] == "candidate"
    assert binding["evidence_refs"] == source["telemetry_evidence_refs"]
    assert binding["lifecycle_state"] == "candidate"
    assert not (brain_home / "skills" / "active" / "read-reuse").exists()
    assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash


def test_record_evaluation_persists_quality_before_roi(brain_home):
    path = _forge(brain_home)

    result = skillforge.record_evaluation(
        brain_home,
        "read-reuse",
        {
            "evaluation_id": "eval-live-read-v1",
            "task_id": "task-read-reuse",
            "task_hash": "t" * 64,
            "repository_state_hash": "r" * 64,
            "baseline": {"input_tokens": 1000, "output_tokens": 200, "tool_calls": 3},
            "candidate": {"input_tokens": 700, "output_tokens": 180, "tool_calls": 1},
            "quality": {
                "correctness": True,
                "requirements": True,
                "protected_values": True,
                "regressions": False,
                "verification": True,
            },
            "gates": {
                "trigger": {"passed": 2, "failed": 0},
                "workflow": {"structural": True, "failed": 0},
                "regression": {"regression": False, "failed": 0},
                "security": {"passed": True, "findings": []},
            },
            "evidence_refs": ["omp-session-baseline", "omp-session-candidate"],
        },
    )

    assert result["status"] == "passed"
    assert result["roi"]["net_tokens_saved"] == 320
    assert result["quality_gate"] == "passed"
    stored = json.loads((path.parent / "evaluation.json").read_text(encoding="utf-8"))
    assert stored["gates"]["security"]["passed"] is True

    assert result["status"] == "passed"
    assert result["roi"]["net_tokens_saved"] == 320
    assert result["quality_gate"] == "passed"
    stored = json.loads((path.parent / "evaluation.json").read_text(encoding="utf-8"))
    assert stored["candidate_content_sha256"]
    assert stored["status"] == "passed"
    binding = json.loads(
        (path.parent / "candidate-binding.json").read_text(encoding="utf-8")
    )
    assert binding["evaluation_state"] == "passed"
    assert binding["promotion_state"] == "authority_review"


def test_changed_candidate_content_invalidates_evaluation(brain_home):
    path = _forge(brain_home)
    path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    try:
        skillforge.record_evaluation(
            brain_home,
            "read-reuse",
            {
                "evaluation_id": "eval-stale",
                "task_id": "task-read-reuse",
                "task_hash": "t" * 64,
                "repository_state_hash": "r" * 64,
                "baseline": {"input_tokens": 1000},
                "candidate": {"input_tokens": 700},
                "quality": {"correctness": True, "requirements": True},
            },
        )
    except Exception as exc:
        assert "content" in str(exc).lower()
    else:
        raise AssertionError("changed candidate content must reject old evaluation")
def test_changed_candidate_cannot_use_old_evaluation_for_promotion(brain_home):
    path = _forge(brain_home)
    skillforge.record_evaluation(
        brain_home,
        "read-reuse",
        {
            "evaluation_id": "eval-freshness",
            "task_id": "task-read-reuse",
            "task_hash": "t" * 64,
            "repository_state_hash": "r" * 64,
            "baseline": {"input_tokens": 1000, "output_tokens": 100},
            "candidate": {"input_tokens": 700, "output_tokens": 100},
            "quality": {
                "correctness": True,
                "requirements": True,
                "protected_values": True,
                "regressions": False,
                "verification": True,
            },
            "gates": {
                "trigger": {"failed": 0},
                "workflow": {"structural": True, "failed": 0},
                "regression": {"regression": False, "failed": 0},
                "security": {"passed": True},
            },
        },
    )
    path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    result = promotion.promote(brain_home, "read-reuse", "candidate", "active")

    assert result["promoted"] is False
    assert result["reason"] == "evaluation_stale"
    assert not (brain_home / "skills" / "active" / "read-reuse").exists()
def test_promotion_authority_holds_without_evaluation(brain_home):
    _forge(brain_home)

    result = promotion.promote(brain_home, "read-reuse", "candidate", "active")

    assert result["promoted"] is False
    assert result["reason"] == "evaluation_not_proven"
    assert (brain_home / "skills" / "candidates" / "read-reuse").is_dir()

def test_successful_evaluation_still_requires_external_authority(brain_home):
    _forge(brain_home)
    skillforge.record_evaluation(
        brain_home,
        "read-reuse",
        {
            "evaluation_id": "eval-positive",
            "task_id": "task-read-reuse",
            "task_hash": "t" * 64,
            "repository_state_hash": "r" * 64,
            "baseline": {"input_tokens": 1000, "output_tokens": 100},
            "candidate": {"input_tokens": 700, "output_tokens": 100},
            "quality": {
                "correctness": True,
                "requirements": True,
                "protected_values": True,
                "regressions": False,
                "verification": True,
            },
            "gates": {
                "trigger": {"failed": 0},
                "workflow": {"structural": True, "failed": 0},
                "regression": {"regression": False, "failed": 0},
                "security": {"passed": True},
            },
        },
    )

    result = promotion.promote(brain_home, "read-reuse", "candidate", "active")

    assert result["promoted"] is False
    assert result["reason"] == "no_evidence"
    assert not (brain_home / "skills" / "active" / "read-reuse").exists()
def test_failed_gate_blocks_positive_roi_evaluation(brain_home):
    _forge(brain_home)

    result = skillforge.record_evaluation(
        brain_home,
        "read-reuse",
        {
            "evaluation_id": "eval-gate-fail",
            "task_id": "task-read-reuse",
            "task_hash": "t" * 64,
            "repository_state_hash": "r" * 64,
            "baseline": {"input_tokens": 1000, "output_tokens": 100},
            "candidate": {"input_tokens": 700, "output_tokens": 100},
            "quality": {
                "correctness": True,
                "requirements": True,
                "protected_values": True,
                "regressions": False,
                "verification": True,
            },
            "gates": {
                "trigger": {"passed": 0, "failed": 1},
                "workflow": {"structural": True, "failed": 0},
                "regression": {"regression": False, "failed": 0},
                "security": {"passed": True, "findings": []},
            },
        },
    )

    assert result["quality_gate"] == "failed"
    assert result["status"] == "hold"
