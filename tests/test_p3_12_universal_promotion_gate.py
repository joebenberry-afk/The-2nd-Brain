"""Universal §119 promotion-gate tests (P3.12): every promotion — Skill
Forge/Radar-backed or general frontier-evidence — must carry evidence,
owner, a baseline-vs-candidate comparison, rollback safety, and a valid
version, regardless of candidate source."""

import json
from pathlib import Path

from second_brain import frontier, paths, plasticity, promotion, skillforge


def _skill(home: Path, name: str = "curator", level: str = "shadow", version: int = 1) -> Path:
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"# {title}\n\n- content"
        for title in (
            "Purpose",
            "Positive Triggers",
            "Negative Triggers",
            "Inputs",
            "Procedure",
            "Tools",
            "Safety",
            "Verification",
            "Output",
            "References",
        )
    )
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\nstatus: {level}\nversion: {version}\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    return directory


def _approve(home: Path, name: str) -> None:
    frontier.frontier_review(home, f"skill-{name}-promotion", "promote", "high", "r", "approve")


def _evidence(home: Path, name: str) -> None:
    plasticity.record_credit(home, "s1", name, "skill", "direct")


def _passing_evaluation(name: str, evaluation_id: str) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "task_id": f"task-{name}",
        "task_hash": "t" * 64,
        "repository_state_hash": "r" * 64,
        "baseline": {"input_tokens": 1000, "output_tokens": 100},
        "candidate": {"input_tokens": 500, "output_tokens": 100},
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
    }


def test_general_frontier_candidate_refused_without_binding(brain_home):
    """§119: a skill that never went through bind_candidate() (no owner, no
    baseline comparison, no rollback-scoped identity) cannot be promoted
    even with evidence and frontier approval — the universal gate applies
    to every candidate source, not only Skill Forge."""
    _skill(brain_home, "curator")
    _evidence(brain_home, "curator")
    _approve(brain_home, "curator")

    result = promotion.promote(brain_home, "curator", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "no_promotion_binding"


def test_general_frontier_candidate_refused_without_owner(brain_home):
    """bind_candidate() itself refuses an empty/missing owner."""
    _skill(brain_home, "curator")
    try:
        skillforge.bind_candidate(
            brain_home,
            "curator",
            source_type="frontier",
            source_ref="frontier-curator",
            owner="   ",
        )
    except Exception as exc:
        assert "owner" in str(exc).lower()
    else:
        raise AssertionError("blank owner must be rejected")


def test_general_frontier_candidate_refused_without_baseline_comparison(brain_home):
    """Bound with an owner but no evaluation ever recorded: HOLD."""
    _skill(brain_home, "curator")
    _evidence(brain_home, "curator")
    _approve(brain_home, "curator")
    skillforge.bind_candidate(
        brain_home,
        "curator",
        source_type="frontier",
        source_ref="frontier-curator",
        owner="repo-stewards",
    )

    result = promotion.promote(brain_home, "curator", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "evaluation_not_proven"


def test_general_frontier_candidate_promotes_with_full_universal_evidence(brain_home):
    """§119 §7B: a fresh, non-Skill-Forge candidate that supplies owner,
    baseline comparison, evidence, rollback-clear, and version reaches the
    same universal authority and is promoted — proving the general path is
    not blocked merely for lacking a Radar origin."""
    _skill(brain_home, "curator")
    _evidence(brain_home, "curator")
    _approve(brain_home, "curator")
    skillforge.bind_candidate(
        brain_home,
        "curator",
        source_type="frontier",
        source_ref="frontier-curator",
        owner="repo-stewards",
    )
    skillforge.record_evaluation(
        brain_home, "curator", _passing_evaluation("curator", "eval-curator-v1")
    )

    result = promotion.promote(brain_home, "curator", "shadow", "candidate", session_id="s1")

    assert result["promoted"] is True
    record = result["record"]
    assert record["owner"] == "repo-stewards"
    assert record["candidate_id"].startswith("skill-candidate-")
    assert record["baseline_comparison"] == "passed"
    assert record["resulting_version"] == 1
    assert record["promotion_id"].startswith("promotion-")
    assert record["rollback_clear"] is True


def test_version_missing_blocks_promotion(brain_home):
    _skill(brain_home, "curator")
    directory = brain_home / "skills" / "shadow" / "curator"
    text = (directory / "SKILL.md").read_text(encoding="utf-8")
    (directory / "SKILL.md").write_text(text.replace("version: 1\n", ""), encoding="utf-8")
    _evidence(brain_home, "curator")
    _approve(brain_home, "curator")
    skillforge.bind_candidate(
        brain_home,
        "curator",
        source_type="frontier",
        source_ref="frontier-curator",
        owner="repo-stewards",
    )
    skillforge.record_evaluation(
        brain_home, "curator", _passing_evaluation("curator", "eval-curator-missing-version")
    )

    result = promotion.promote(brain_home, "curator", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "version_missing"


def test_version_malformed_blocks_promotion(brain_home):
    _skill(brain_home, "curator")
    directory = brain_home / "skills" / "shadow" / "curator"
    text = (directory / "SKILL.md").read_text(encoding="utf-8")
    updated = text.replace("version: 1", "version: notanumber")
    (directory / "SKILL.md").write_text(updated, encoding="utf-8")
    _evidence(brain_home, "curator")
    _approve(brain_home, "curator")
    skillforge.bind_candidate(
        brain_home,
        "curator",
        source_type="frontier",
        source_ref="frontier-curator",
        owner="repo-stewards",
    )
    skillforge.record_evaluation(
        brain_home, "curator", _passing_evaluation("curator", "eval-curator-bad-version")
    )

    result = promotion.promote(brain_home, "curator", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "version_invalid"


def test_version_not_incremented_blocks_reactive_promotion(brain_home):
    """A skill previously ACTIVE at version 1 cannot go active again at the
    same (or lower) version — the version must strictly increase relative
    to the last version that was actually promoted to active."""
    _skill(brain_home, "curator", level="candidate", version=1)
    _evidence(brain_home, "curator")
    _approve(brain_home, "curator")
    skillforge.bind_candidate(
        brain_home,
        "curator",
        source_type="frontier",
        source_ref="frontier-curator",
        owner="repo-stewards",
    )
    skillforge.record_evaluation(
        brain_home, "curator", _passing_evaluation("curator", "eval-curator-v1-active")
    )
    first = promotion.promote(brain_home, "curator", "candidate", "active")
    assert first["promoted"] is True
    assert first["record"]["resulting_version"] == 1

    promotion.demote(brain_home, "curator", "candidate", "revise")
    skillforge.bind_candidate(
        brain_home,
        "curator",
        source_type="frontier",
        source_ref="frontier-curator-revision",
        owner="repo-stewards",
    )
    skillforge.record_evaluation(
        brain_home, "curator", _passing_evaluation("curator", "eval-curator-v1-again")
    )

    second = promotion.promote(brain_home, "curator", "candidate", "active")

    assert second["promoted"] is False
    assert second["reason"] == "version_not_incremented"


def test_radar_backed_candidate_still_promotes_through_universal_gate(brain_home):
    """§119 §7A: the already-proven Skill Forge/Radar lifecycle continues
    to work through the strengthened universal gate without regression."""
    radar_dir = brain_home / "state" / "radar"
    radar_dir.mkdir(parents=True)

    candidate = {
        "candidate_id": "candidate-universal-gate",
        "candidate_type": "REPEATED_READ",
        "project_id": "second-brain",
        "reason_codes": ["REPEATED_READ"],
        "promotion_eligible": False,
        "status": "candidate",
        "telemetry_evidence_refs": [
            {"telemetry_ref": "session.jsonl:1", "record_hash": "b" * 64}
        ],
        "observations": [],
    }
    (radar_dir / "candidates.json").write_text(json.dumps([candidate]), encoding="utf-8")

    path = skillforge.forge_radar_candidate(
        brain_home,
        "candidate-universal-gate",
        name="reuse-gate",
        project_id="second-brain",
        owner="second-brain-radar-steward",
    )
    skillforge.record_evaluation(
        brain_home, "reuse-gate", _passing_evaluation("reuse-gate", "eval-reuse-gate")
    )
    _evidence(brain_home, "reuse-gate")
    _approve(brain_home, "reuse-gate")

    result = promotion.promote(brain_home, "reuse-gate", "candidate", "active")

    assert result["promoted"] is True
    assert result["record"]["owner"] == "second-brain-radar-steward"
    assert result["record"]["resulting_version"] == 1
    assert (brain_home / "skills" / "active" / "reuse-gate").is_dir()
    assert path.exists() is False  # moved
