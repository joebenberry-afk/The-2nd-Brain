"""Tests for policy promotion with guards (Phase 23)."""

import json
import uuid
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import frontier, paths, plasticity, promotion
from second_brain.errors import BrainError

LEVELS = ("shadow", "candidate", "active")


def _skill(home, name="scout", level="shadow", marker="content"):
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"# {title}\n\n- {marker}"
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


def _approve(home, name):
    frontier.frontier_review(home, f"skill-{name}-promotion", "promote", "high", "r", "approve")


def _evidence(home, name):
    return plasticity.record_credit(home, "s1", name, "skill", "direct")


def _rollback_record(home, name):
    path = home / "immune" / "rollbacks"
    path.mkdir(parents=True, exist_ok=True)
    (path / f"skill-{name}-x.json").write_text(
        json.dumps(
            {
                "policy_id": f"skill-{name}",
                "ts": "2026-08-14T00:00:00+00:00",
                "trigger": "t",
                "reason": "r",
            }
        ),
        encoding="utf-8",
    )


def _fresh(brain_home):
    return brain_home / uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Guard failures
# ---------------------------------------------------------------------------


def test_promote_fails_without_evidence(brain_home):
    _skill(brain_home)
    _approve(brain_home, "scout")
    result = promotion.promote(brain_home, "scout", "shadow", "candidate")
    assert result["promoted"] is False
    assert result["reason"] == "no_evidence"
    assert promotion.is_active(brain_home, "scout") is False
    assert (brain_home / "skills" / "shadow" / "scout").is_dir()


def test_promote_fails_without_frontier_approve(brain_home):
    _skill(brain_home)
    _evidence(brain_home, "scout")
    result = promotion.promote(brain_home, "scout", "shadow", "candidate")
    assert result["promoted"] is False
    assert result["reason"] == "frontier_not_approved"
    assert result["frontier_verdict"] is None


def test_promote_refuses_when_rolled_back(brain_home):
    _skill(brain_home)
    _evidence(brain_home, "scout")
    _approve(brain_home, "scout")
    _rollback_record(brain_home, "scout")
    result = promotion.promote(brain_home, "scout", "shadow", "candidate")
    assert result["promoted"] is False
    assert result["reason"] == "rolled_back"


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_promote_all_guards_green_moves_and_records(brain_home):
    source = _skill(brain_home)
    _evidence(brain_home, "scout")
    _approve(brain_home, "scout")
    result = promotion.promote(brain_home, "scout", "shadow", "candidate", session_id="s9")
    assert result["promoted"] is True
    assert result["from_level"] == "shadow"
    assert result["to_level"] == "candidate"
    assert not source.exists()  # moved
    target = brain_home / "skills" / "candidates" / "scout"
    assert target.is_dir()
    assert "content" in (target / "SKILL.md").read_text(encoding="utf-8")
    record = result["record"]
    assert record["guards"] == {
        "evidence": True,
        "frontier_approved": True,
        "immune_clear": True,
        "frontier_binding_current": True,
    }
    assert record["frontier_verdict"] == "approve"
    assert record["evidence_counts"]["credit_events"] == 1
    assert record["session_id"] == "s9"
    # Record file exists on disk.
    assert Path(result["record_path"]).exists()
    assert promotion.is_active(brain_home, "scout") is False  # still candidate


def test_promote_to_active(brain_home):
    _skill(brain_home)
    _evidence(brain_home, "scout")
    _approve(brain_home, "scout")
    promotion.promote(brain_home, "scout", "shadow", "candidate")
    result = promotion.promote(brain_home, "scout", "candidate", "active")
    assert result["promoted"] is True
    assert promotion.is_active(brain_home, "scout") is True


def test_changed_skill_invalidates_frontier_approval(brain_home):
    skill = _skill(brain_home, name="stale") / "SKILL.md"
    _evidence(brain_home, "stale")
    _approve(brain_home, "stale")
    skill.write_text(skill.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    result = promotion.promote(brain_home, "stale", "shadow", "candidate")
    assert result["promoted"] is False
    assert result["reason"] == "frontier_stale"
    assert skill.parent.is_dir()


def test_incomplete_skill_cannot_become_active(brain_home):
    skill = _skill(brain_home, name="incomplete") / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8").replace("- content", "(fill me)", 1),
        encoding="utf-8",
    )
    _evidence(brain_home, "incomplete")
    _approve(brain_home, "incomplete")
    assert promotion.promote(brain_home, "incomplete", "shadow", "candidate")["promoted"]
    result = promotion.promote(brain_home, "incomplete", "candidate", "active")
    assert result["promoted"] is False
    assert result["reason"] == "execution_not_ready"


# ---------------------------------------------------------------------------
# Level rules
# ---------------------------------------------------------------------------


def test_skip_level_refused(brain_home):
    _skill(brain_home)
    _evidence(brain_home, "scout")
    _approve(brain_home, "scout")
    result = promotion.promote(brain_home, "scout", "shadow", "active")
    assert result["promoted"] is False
    assert result["reason"] == "skip_level"


def test_level_mismatch_and_already_at_level(brain_home):
    _skill(brain_home)
    _evidence(brain_home, "scout")
    _approve(brain_home, "scout")
    result = promotion.promote(brain_home, "scout", "candidate", "active")
    assert result["promoted"] is False
    assert result["reason"] == "level_mismatch"
    result = promotion.promote(brain_home, "scout", "shadow", "shadow")
    assert result["promoted"] is False
    assert result["reason"] == "already_at_level"


def test_destination_conflict_refuses(brain_home):
    _skill(brain_home)
    _skill(brain_home, name="scout", level="candidate")  # conflict target
    _evidence(brain_home, "scout")
    _approve(brain_home, "scout")
    result = promotion.promote(brain_home, "scout", "shadow", "candidate")
    assert result["promoted"] is False
    assert result["reason"] == "destination_exists"


def test_unknown_skill_raises(brain_home):
    with pytest.raises(BrainError, match="No skill"):
        promotion.promote(brain_home, "ghost", "shadow", "candidate")


# ---------------------------------------------------------------------------
# Demote
# ---------------------------------------------------------------------------


def test_demote_moves_and_records_reason(brain_home):
    _skill(brain_home, name="scout", level="active")
    result = promotion.demote(brain_home, "scout", "shadow", "underperformed")
    assert result["demoted"] is True
    assert result["from_level"] == "active"
    assert result["to_level"] == "shadow"
    assert result["record"]["reason"] == "underperformed"
    assert (brain_home / "skills" / "shadow" / "scout").is_dir()
    assert promotion.is_active(brain_home, "scout") is False
    status = promotion.promotion_status(brain_home, "scout")
    assert status["level"] == "shadow"
    assert len(status["records"]) == 1


def test_demote_not_a_demote(brain_home):
    _skill(brain_home, name="scout", level="candidate")
    result = promotion.demote(brain_home, "scout", "candidate", "why")
    assert result == {"demoted": False, "reason": "not_a_demote", "actual_level": "candidate"}


def test_promote_downward_allowed_without_guards(brain_home):
    _skill(brain_home, name="scout", level="active")
    result = promotion.promote(brain_home, "scout", "active", "candidate")
    assert result["promoted"] is True  # demote via promote: no guards needed
    assert result["record"]["reason"] == "demoted-via-promote"
    assert (brain_home / "skills" / "candidates" / "scout").is_dir()


# ---------------------------------------------------------------------------
# Status / determinism
# ---------------------------------------------------------------------------


def test_promotion_status_and_determinism(brain_home):
    _skill(brain_home, name="alpha", level="shadow")
    _skill(brain_home, name="beta", level="active")
    status = promotion.promotion_status(brain_home)
    assert status["skills"] == {"alpha": "shadow", "beta": "active"}
    assert promotion.is_active(brain_home, "beta") is True
    assert promotion.promotion_status(brain_home) == promotion.promotion_status(brain_home)
    # Refusals are deterministic too.
    _skill(brain_home, name="gamma", level="shadow")
    first = promotion.promote(brain_home, "gamma", "shadow", "candidate")
    second = promotion.promote(brain_home, "gamma", "shadow", "candidate")
    assert first == second


# ---------------------------------------------------------------------------
# Hypothesis: guard combos vs brute-force reference
# ---------------------------------------------------------------------------


def _reference(to, has_evidence, frontier_ok, rolled_back, dest_conflict):
    if to == "shadow":
        return "already_at_level"
    if to == "active":
        return "skip_level"
    if not has_evidence:
        return "no_evidence"
    if not frontier_ok:
        return "frontier_not_approved"
    if rolled_back:
        return "rolled_back"
    if dest_conflict:
        return "destination_exists"
    return "promoted"


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.sampled_from(("shadow", "candidate", "active")),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
)
def test_guard_combos_match_reference(
    brain_home, to, has_evidence, frontier_ok, rolled_back, dest_conflict
):
    home = _fresh(brain_home)
    _skill(home)
    if has_evidence:
        _evidence(home, "scout")
    if frontier_ok:
        _approve(home, "scout")
    if rolled_back:
        _rollback_record(home, "scout")
    if dest_conflict:
        _skill(home, name="scout", level="candidate")
    result = promotion.promote(home, "scout", "shadow", to)
    expected = _reference(to, has_evidence, frontier_ok, rolled_back, dest_conflict)
    if expected == "promoted":
        assert result["promoted"] is True
        assert (home / "skills" / "candidates" / "scout").is_dir()
    else:
        assert result["promoted"] is False
        assert result["reason"] == expected


# ---------------------------------------------------------------------------
# SEC-03: promotion cannot escape skill roots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["../escape", "..\\escape", "a/b", "a\\b", "/abs", "a\nb", "a*b", ".", "..", ""],
)
def test_promote_demote_reject_hostile_skill_names(brain_home, bad):
    with pytest.raises(BrainError):
        promotion.promote(brain_home, bad, "shadow", "candidate")
    with pytest.raises(BrainError):
        promotion.demote(brain_home, bad, "shadow", "reason")
    with pytest.raises(BrainError):
        promotion.is_active(brain_home, bad)
    assert not (brain_home.parent / "escape").exists()


def test_promotion_record_names_contained(brain_home):
    """Promotion records for a valid skill stay under state/promotions/."""
    _skill(brain_home, name="record-me")
    _evidence(brain_home, "record-me")
    _approve(brain_home, "record-me")
    result = promotion.promote(brain_home, "record-me", "shadow", "candidate")
    assert result["promoted"] is True
    record_path = Path(result["record_path"])
    assert record_path.parent == brain_home / "state" / "promotions"


