from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_brain import paths, skills


def _make_skill(home: Path, name: str, level: str, purpose: str = "Handles X.") -> Path:
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n{purpose if title == 'Purpose' else '- content'}"
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


def test_eligible_skills_scans_active_candidate_shadow_only(brain_home):
    _make_skill(brain_home, "a", "active")
    _make_skill(brain_home, "c", "candidate")
    _make_skill(brain_home, "s", "shadow")
    result = {item["skill_id"]: item for item in skills.eligible_skills(brain_home)}
    assert set(result) == {"a", "c", "s"}
    assert result["a"]["lifecycle_state"] == "active"
    assert result["a"]["content_hash"] is not None


def test_descriptors_are_bounded_and_exclude_other_sections(brain_home):
    _make_skill(brain_home, "one", "active", purpose="Secret internal detail. " * 50)
    described = skills.descriptors(brain_home)["one"]
    assert len(described["descriptor_text"]) <= 400
    assert "Tools" not in described["descriptor_text"]
    assert len(described["descriptor_ref"]) == 16


def test_build_plan_selects_and_caps_at_three(brain_home, monkeypatch):
    for name in ("a", "b", "c", "d"):
        _make_skill(brain_home, name, "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a", "b", "c", "d"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    assert len(plan["selected_skill_ids"]) == 3
    assert "d" in plan["rejected_skill_ids"]
    assert plan["rejected_skill_ids"]["d"] == "over_cap"


def test_build_plan_zero_selection_is_legitimate(brain_home, monkeypatch):
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": [],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    assert plan["selected_skill_ids"] == []


def test_build_plan_rejects_unknown_and_duplicate_selection(brain_home, monkeypatch):
    _make_skill(brain_home, "a", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a", "a", "ghost"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    assert plan["selected_skill_ids"] == ["a"]
    assert plan["rejected_skill_ids"]["ghost"] == "not_eligible"


def test_hydrate_plan_rejects_stale_content_hash(brain_home, monkeypatch):
    directory = _make_skill(brain_home, "stale", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["stale"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    (directory / "SKILL.md").write_text(
        (directory / "SKILL.md").read_text(encoding="utf-8").replace("Handles X.", "Changed."),
        encoding="utf-8",
    )
    updated, bodies = skills.hydrate_plan(brain_home, plan)
    assert "stale" not in updated["hydrated_skill_ids"]
    assert updated["unavailable_skill_ids"]["stale"] == "stale_content_hash"
    assert bodies == {}


def test_hydrate_plan_hydrates_selected_only(brain_home, monkeypatch):
    _make_skill(brain_home, "picked", "shadow")
    _make_skill(brain_home, "not-picked", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["picked"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    updated, bodies = skills.hydrate_plan(brain_home, plan)
    assert updated["hydrated_skill_ids"] == ["picked"]
    assert set(bodies) == {"picked"}
    assert "not-picked" not in bodies


def test_plan_to_evidence_has_no_raw_bodies_or_task_text(brain_home, monkeypatch):
    _make_skill(brain_home, "picked", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["picked"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "super secret task text", session_id="s1", project_id="p1")
    evidence = skills.plan_to_evidence(plan)
    dumped = json.dumps(evidence)
    assert "super secret task text" not in dumped
    assert "Handles X." not in dumped


def test_resolve_visibility_mode_defaults_to_shadow(brain_home):
    assert skills.resolve_visibility_mode(brain_home) == "shadow"
    (brain_home / "config").mkdir(parents=True, exist_ok=True)
    (brain_home / "config" / "skills.toml").write_text(
        '[visibility]\nmode = "enforced"\n', encoding="utf-8"
    )
    assert skills.resolve_visibility_mode(brain_home) == "enforced"
    (brain_home / "config" / "skills.toml").write_text(
        '[visibility]\nmode = "bogus"\n', encoding="utf-8"
    )
    assert skills.resolve_visibility_mode(brain_home) == "shadow"


def test_router_failure_yields_zero_selection_not_all_skills(brain_home, monkeypatch):
    _make_skill(brain_home, "a", "shadow")

    def _boom(home, task, max_active=None, skills=None):
        raise RuntimeError("router down")

    monkeypatch.setattr("second_brain.router.route", _boom)
    with pytest.raises(RuntimeError):
        skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    # Callers (Tasks 2/4) catch this and fail open to zero selection —
    # skills.py itself must never silently substitute "select everything".
