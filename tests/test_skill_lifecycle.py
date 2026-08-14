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
    assert promotion.promote(brain_home, "good", "shadow", "candidate")["promoted"]
    assert promotion.promote(brain_home, "good", "candidate", "active")["promoted"]
    result = skillforge.audit_lifecycle(brain_home)
    assert result["ok"] is True
