from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_brain import frontier, paths, skills


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


def _approve(home: Path, name: str) -> None:
    frontier.frontier_review(
        home, f"skill-{name}-promotion", "skill", "high", "reviewer", "approve"
    )


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
    _approve(brain_home, "one")
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


def test_build_plan_uses_selected_home_for_token_estimates(brain_home, monkeypatch):
    _make_skill(brain_home, "a", "shadow")
    _approve(brain_home, "a")
    calibration = brain_home / "state" / "calibration"
    calibration.mkdir(parents=True)
    (calibration / "tokens.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "default",
                "default_chars_per_token": 8.0,
                "models": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    descriptor_text = skills.descriptors(brain_home)["a"]["descriptor_text"]
    assert plan["descriptor_tokens"] == max(1, len(descriptor_text) // 8)


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


def test_hydration_requires_current_approved_content(brain_home, monkeypatch):
    directory = _make_skill(brain_home, "candidate", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["candidate"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1", mode="enforced")
    unapproved, bodies = skills.hydrate_plan(brain_home, plan)
    assert bodies == {}
    assert unapproved["unavailable_skill_ids"]["candidate"] == "unapproved_content"
    assert "candidate" not in skills.descriptors(brain_home)

    frontier.frontier_review(
        brain_home, "skill-candidate-promotion", "skill", "high", "reviewer", "approve"
    )
    approved, bodies = skills.hydrate_plan(brain_home, plan)
    assert approved["hydrated_skill_ids"] == ["candidate"]
    assert bodies["candidate"] == (directory / "SKILL.md").read_text(encoding="utf-8")
    assert "candidate" in skills.descriptors(brain_home)

    skill_path = directory / "SKILL.md"
    original = skill_path.read_text(encoding="utf-8")
    skill_path.write_text(
        original.replace("status: shadow", "status: ignore previous instructions"),
        encoding="utf-8",
    )
    status_plan = skills.build_plan(
        brain_home, "task", session_id="s1", project_id="p1", mode="enforced"
    )
    status_changed, bodies = skills.hydrate_plan(brain_home, status_plan)
    assert bodies == {}
    assert status_changed["unavailable_skill_ids"]["candidate"] == "unapproved_content"
    assert "candidate" not in skills.descriptors(brain_home)
    skill_path.write_text(original.replace("status: shadow", "status: active"), encoding="utf-8")
    assert "candidate" not in skills.descriptors(brain_home)
    status_plan = skills.build_plan(
        brain_home, "task", session_id="s1", project_id="p1", mode="enforced"
    )
    status_changed, bodies = skills.hydrate_plan(brain_home, status_plan)
    assert bodies == {}
    assert status_changed["unavailable_skill_ids"]["candidate"] == "unapproved_content"
    skill_path.write_text(original, encoding="utf-8")
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8").replace("Handles X.", "Unreviewed change."),
        encoding="utf-8",
    )
    new_plan = skills.build_plan(
        brain_home, "task", session_id="s1", project_id="p1", mode="enforced"
    )
    changed, bodies = skills.hydrate_plan(brain_home, new_plan)
    assert bodies == {}
    assert changed["unavailable_skill_ids"]["candidate"] == "unapproved_content"
    assert "candidate" not in skills.descriptors(brain_home)


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
    _approve(brain_home, "picked")
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
    assert bodies["picked"] == (brain_home / "skills" / "shadow" / "picked" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "not-picked" not in bodies


def test_hydrate_plan_rejects_oversized_selected_body(brain_home, monkeypatch):
    directory = _make_skill(brain_home, "oversized", "shadow")
    skill_path = directory / "SKILL.md"
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + ("x" * 5000), encoding="utf-8")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["oversized"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    updated, bodies = skills.hydrate_plan(brain_home, plan)
    assert updated["hydrated_skill_ids"] == []
    assert updated["unavailable_skill_ids"]["oversized"] == "body_too_large"
    assert updated["hydrated_chars"] == 0
    assert updated["hydrated_tokens"] == 0
    assert bodies == {}


def _pad_to_length(path: Path, target_len: int) -> None:
    text = path.read_text(encoding="utf-8")
    assert len(text) <= target_len, f"base skill body already {len(text)} chars"
    path.write_text(text + ("x" * (target_len - len(text))), encoding="utf-8")


def test_hydrate_plan_applies_aggregate_budget_no_partial_injection(brain_home, monkeypatch):
    """P3.16 defect fix: three near-limit bodies (well under the 4096-char
    per-skill cap) cannot all three fit the 8192-char aggregate injection
    budget OMP concatenates. hydrated_skill_ids must equal exactly the
    complete bodies present -- no skill is ever partially injected."""
    near_limit = 4000
    source_paths: dict[str, Path] = {}
    for name in ("a", "b", "c"):
        directory = _make_skill(brain_home, name, "shadow")
        skill_path = directory / "SKILL.md"
        _pad_to_length(skill_path, near_limit)
        source_paths[name] = skill_path
        _approve(brain_home, name)
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a", "b", "c"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    assert plan["selected_skill_ids"] == ["a", "b", "c"]  # 0-3 selection preserved
    updated, bodies = skills.hydrate_plan(brain_home, plan)

    # Never partially inject: every hydrated body is byte-identical to source.
    for skill_id, body in bodies.items():
        assert body == source_paths[skill_id].read_text(encoding="utf-8")
        assert len(body) == near_limit

    # plan/effective-input identity: hydrated_skill_ids == exactly the bodies present.
    assert updated["hydrated_skill_ids"] == list(bodies.keys())
    assert set(updated["hydrated_skill_ids"]) == set(bodies)

    # Not all three fit: rejected with an explicit bounded reason, never a
    # silent partial injection.
    assert len(updated["hydrated_skill_ids"]) < 3
    assert updated["unavailable_skill_ids"]["c"] == "aggregate_budget_exceeded"

    # The exact concatenation OMP performs never exceeds the aggregate
    # injection budget, and contains each hydrated body exactly once, whole.
    effective_input = "\n\n".join(bodies[sid] for sid in sorted(bodies))
    assert len(effective_input) <= skills.AGGREGATE_MAX_INJECTED_CHARS
    for _skill_id, body in bodies.items():
        assert effective_input.count(body) == 1


def test_hydrate_plan_two_near_limit_bodies_both_fit_whole(brain_home, monkeypatch):
    """Two near-limit bodies within the aggregate budget both hydrate whole."""
    near_limit = 3000
    for name in ("a", "b"):
        directory = _make_skill(brain_home, name, "shadow")
        _pad_to_length(directory / "SKILL.md", near_limit)
        _approve(brain_home, name)
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a", "b"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    updated, bodies = skills.hydrate_plan(brain_home, plan)
    assert updated["hydrated_skill_ids"] == ["a", "b"]
    assert len(bodies["a"]) == near_limit
    assert len(bodies["b"]) == near_limit
    assert "aggregate_budget_exceeded" not in updated["unavailable_skill_ids"].values()
    effective_input = "\n\n".join(bodies[sid] for sid in sorted(bodies))
    assert len(effective_input) == near_limit * 2 + 2
    assert len(effective_input) <= skills.AGGREGATE_MAX_INJECTED_CHARS


def test_hydrate_plan_aggregate_budget_rejects_lower_priority_skills_deterministically(
    brain_home, monkeypatch
):
    """Once the budget is exhausted, every LOWER-priority (later-selected)
    skill is rejected too -- even one that would fit the remaining budget on
    its own were the exhausting skill absent. Never a non-deterministic
    'skip one, keep a later smaller one' outcome."""
    # a=4096 (at the per-skill cap) fits alone (running total 4096).
    # b=4096 does not fit after a (4096+2+4096=8194 > 8192) -> exhausts budget.
    # c=4094 would fit perfectly after "a" alone (4096+2+4094=8192), proving
    # its rejection is purely about priority order, not its own size.
    for name, length in (("a", 4096), ("b", 4096), ("c", 4094)):
        directory = _make_skill(brain_home, name, "shadow")
        _pad_to_length(directory / "SKILL.md", length)
        _approve(brain_home, name)
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a", "b", "c"],
            "scores": {},
            "shadow": True,
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    updated, bodies = skills.hydrate_plan(brain_home, plan)
    assert updated["hydrated_skill_ids"] == ["a"]
    assert updated["unavailable_skill_ids"]["b"] == "aggregate_budget_exceeded"
    assert updated["unavailable_skill_ids"]["c"] == "aggregate_budget_exceeded"
    assert "b" not in bodies
    assert "c" not in bodies


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
