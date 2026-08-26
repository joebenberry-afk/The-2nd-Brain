"""Focused tests for the read-only P3.15 portfolio observation boundary."""

import json
from pathlib import Path

from second_brain import paths
from second_brain.gardener import SkillGardener


def _make_skill(home: Path, name: str, level: str) -> Path:
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n- verified content"
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
        f"---\nname: {name}\nstatus: {level}\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    return directory


def _lifecycle_snapshot(home: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for level_dir in paths.SKILL_LEVEL_DIRS.values():
        root = home / level_dir
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    snapshot[path.relative_to(home).as_posix()] = path.read_bytes()
    promotions = home / "state" / "promotions"
    if promotions.is_dir():
        for path in promotions.rglob("*"):
            if path.is_file():
                snapshot[path.relative_to(home).as_posix()] = path.read_bytes()
    return snapshot


def test_observe_portfolio_returns_all_lifecycle_skills_and_economics(brain_home):
    _make_skill(brain_home, "candidate-one", "candidate")
    _make_skill(brain_home, "shadow-one", "shadow")
    _make_skill(brain_home, "active-one", "active")

    result = SkillGardener(brain_home).observe_portfolio()

    assert {item["skill_name"] for item in result["skills"]} == {
        "candidate-one",
        "shadow-one",
        "active-one",
    }
    assert set(result) == {"skills", "issues", "recommendations", "economics"}
    assert result["economics"]["model_calls"] == 0
    assert result["economics"]["tool_calls"] == 0
    assert result["economics"]["tokens"] == 0
    assert result["economics"]["maintenance_work_performed"] == 0
    assert result["economics"]["records_inspected"] >= 3
    assert result["economics"]["local_processing_time_ms"] >= 0
    assert len(result["recommendations"]) == 3


def test_observe_portfolio_composes_bounded_evidence_and_issue_shape(brain_home):
    directory = _make_skill(brain_home, "bounded-skill", "candidate")
    (directory / "candidate-binding.json").write_text(
        json.dumps(
            {
                "candidate_id": "candidate-1",
                "evaluation_state": "passed",
                "evidence_refs": ["radar:candidate-1", "telemetry:window-1"],
                "source_ref": "radar:candidate-1",
            }
        ),
        encoding="utf-8",
    )
    (directory / "evaluation.json").write_text(
        json.dumps({"evaluation_id": "eval-1", "candidate_id": "candidate-1"}),
        encoding="utf-8",
    )

    result = SkillGardener(brain_home).observe_portfolio()
    skill = result["skills"][0]

    assert skill["lifecycle_state"] == "candidate"
    assert skill["skill_version"] == "1"
    assert len(skill["content_hash"]) == 64
    assert skill["binding_present"] is True
    assert skill["evaluation_present"] is True
    assert "radar:candidate-1" in skill["evidence_refs"]
    assert "verified content" not in json.dumps(result)
    assert all(
        {
            "issue_id",
            "issue_type",
            "condition_code",
            "skill_name",
            "skill_version",
            "lifecycle_state",
            "reason_codes",
            "evidence_refs",
            "measurement_state",
        }
        <= issue.keys()
        for issue in result["issues"]
    )


def test_observe_portfolio_does_not_mutate_lifecycle_or_promotion_state(brain_home):
    _make_skill(brain_home, "stable-skill", "shadow")
    before = _lifecycle_snapshot(brain_home)
    gardener = SkillGardener(brain_home)

    gardener.observe_portfolio()

    assert _lifecycle_snapshot(brain_home) == before
