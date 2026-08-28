from pathlib import Path
from typing import cast

from second_brain import frontier, paths, plasticity, promotion, skillforge


def _skill(home: Path, name: str, level: str, body: str = "ready") -> Path:
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"# {title}\n\n- {body}"
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
    path = directory / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\nstatus: {level}\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    return path


def test_lifecycle_audit_rejects_mismatch_and_incomplete_active(brain_home):
    path = _skill(brain_home, "bad", "active", body="(fill me)")
    path.write_text(
        path.read_text(encoding="utf-8").replace("status: active", "status: candidate"),
        encoding="utf-8",
    )
    result = skillforge.audit_lifecycle(brain_home)
    assert result["ok"] is False
    issues = cast(list[str], result["issues"])
    assert any("frontmatter status" in issue for issue in issues)
    assert any("placeholder" in issue for issue in issues)


def test_lifecycle_audit_accepts_promoted_execution_ready_skill(brain_home):
    _skill(brain_home, "good", "shadow")
    plasticity.record_credit(brain_home, "s1", "good", "skill", "direct")
    frontier.frontier_review(
        brain_home,
        "skill-good-promotion",
        "promote good",
        "high",
        "reviewer",
        "approve",
    )
    skillforge.bind_candidate(
        brain_home,
        "good",
        source_type="frontier",
        source_ref="frontier-good",
        owner="steward-good",
    )
    skillforge.record_evaluation(
        brain_home,
        "good",
        {
            "evaluation_id": "eval-good",
            "task_id": "task-good",
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
        },
    )
    assert promotion.promote(brain_home, "good", "shadow", "candidate")["promoted"]
    assert promotion.promote(brain_home, "good", "candidate", "active")["promoted"]
    result = skillforge.audit_lifecycle(brain_home)
    assert result["ok"] is True
