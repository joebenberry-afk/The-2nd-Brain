from pathlib import Path

from second_brain.skillforge import validate_execution_ready


def test_execution_active_skill_rejects_placeholders(tmp_path: Path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\nname: bad\nstatus: active\n---\n\n# Purpose\n\n(fill me)\n",
        encoding="utf-8",
    )
    result = validate_execution_ready(skill)
    assert result["ok"] is False
    assert "Purpose" not in result["missing_sections"]
    assert result["issues"]
