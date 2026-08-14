"""Tests for the Skill Forge (Phase 16)."""

import json
import uuid
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import episodes, skillforge
from second_brain.errors import BrainError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "skill-eval-cases.json"


def _episode(brain_home, summary, trigger="", counter="", lesson=""):
    sections = {}
    if trigger:
        sections["Trigger signals"] = trigger
    if counter:
        sections["Counter-signals"] = counter
    if lesson:
        sections["Reusable lesson"] = lesson
    return episodes.create_episode(brain_home, "correction", summary, sections=sections)


def _forge(brain_home, name="restore-safety", eids=None):
    if eids is None:
        eids = [
            _episode(
                brain_home,
                "restore replayed stale WAL frames",
                trigger="restore failed with stale sidecar\nwal replay corruption",
                counter="clean shutdown verified",
                lesson="never leave -wal next to a restored DB",
            ),
            _episode(
                brain_home,
                "hash mismatch aborted the restore",
                trigger="hash mismatch on restore",
                lesson="verify the DB hash after restore",
            ),
        ]
    return skillforge.forge_candidate(brain_home, name, eids)


def _text(home, name):
    return _skill(home, name).read_text(encoding="utf-8")


def _skill(home, name):
    return home / "skills" / "candidates" / name / "SKILL.md"


# ---------------------------------------------------------------------------
# Forge
# ---------------------------------------------------------------------------


def test_forge_merges_episodes(brain_home):
    eids = [
        _episode(brain_home, "summary one", trigger="t1\nt2", counter="c1", lesson="lesson A"),
        _episode(brain_home, "summary two", trigger="t2\nt3", counter="c2", lesson="lesson B"),
    ]
    path = skillforge.forge_candidate(brain_home, "merged-skill", eids)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: merged-skill" in text
    assert "status: candidate" in text
    assert "source_episodes:" in text
    assert f"- {eids[0]}" in text
    assert "created_at:" in text
    # purpose = merged summaries
    assert "# Purpose\n\n- summary one\n- summary two" in text
    # triggers = union, deduped, order preserved
    assert "# Positive Triggers\n\nt1\nt2\nt3" in text
    assert "# Negative Triggers\n\nc1\nc2" in text
    # procedure = numbered merged lessons
    assert "# Procedure\n\n1. lesson A\n2. lesson B" in text
    # placeholders for the human sections
    assert "# Inputs\n\n(fill me)" in text
    assert "# Safety\n\n(review required)" in text
    assert "# Verification\n\n(eval required)" in text
    # references include episode ids
    assert f"- episode {eids[0]}" in text


def test_forge_all_required_sections(brain_home):
    path = _forge(brain_home)
    text = path.read_text(encoding="utf-8")
    for section in skillforge.REQUIRED_SECTIONS:
        assert f"# {skillforge._SECTION_TITLES[section]}" in text


def test_forge_collision_retry_and_no_overwrite(brain_home):
    first = _forge(brain_home, "dup")
    second = _forge(brain_home, "dup")
    assert first != second
    assert second.parent.name == "dup-1"
    assert first.exists() and second.exists()
    # A third forge never touches the first two.
    third = _forge(brain_home, "dup")
    assert third.parent.name == "dup-2"
    # Never overwrites: content of the first stays intact.
    assert _skill(brain_home, "dup").read_text(encoding="utf-8") == first.read_text(
        encoding="utf-8"
    )


def test_forge_unknown_episode_raises(brain_home):
    with pytest.raises(BrainError, match="Unknown episode"):
        skillforge.forge_candidate(brain_home, "bad", ["correction-20260814-00000000"])


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def test_validate_ok_on_forged(brain_home):
    _forge(brain_home)
    result = skillforge.validate_candidate(brain_home, "restore-safety")
    assert result["ok"] is True
    assert result["missing_sections"] == []
    assert result["issues"] == []


def test_validate_catches_missing_and_fill_me(brain_home):
    _forge(brain_home)
    path = _skill(brain_home, "restore-safety")
    text = path.read_text(encoding="utf-8")
    # Remove a section -> missing.
    text = text.replace("# Output\n\n(fill me)\n", "")
    # Put a forbidden placeholder into purpose.
    text = text.replace("- restore replayed stale WAL frames", "- (fill me) restore replayed")
    path.write_text(text, encoding="utf-8")
    result = skillforge.validate_candidate(brain_home, "restore-safety")
    assert result["ok"] is False
    assert "Output" in result["missing_sections"]
    assert any("(fill me)" in issue and "Purpose" in issue for issue in result["issues"])


def test_validate_unknown_candidate_raises(brain_home):
    with pytest.raises(BrainError, match="No candidate skill"):
        skillforge.validate_candidate(brain_home, "nope")


# ---------------------------------------------------------------------------
# Trigger / workflow / regression evals
# ---------------------------------------------------------------------------


def test_trigger_eval_boundary_math(brain_home):
    _forge(brain_home)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = skillforge.trigger_eval(brain_home, "restore-safety", data["trigger_cases"])
    assert result["total"] == 8
    assert result["failed"] == 0
    # Negative override: a positive match plus a negative phrase -> no trigger.
    negative_override = [
        {
            "text": "restore failed with stale sidecar but clean shutdown verified",
            "expect": "no_trigger",
        }
    ]
    assert skillforge.trigger_eval(brain_home, "restore-safety", negative_override)["passed"] == 1


def test_trigger_eval_deterministic(brain_home):
    _forge(brain_home)
    cases = [
        {"text": "wal replay corruption", "expect": "trigger"},
        {"text": "clean shutdown verified", "expect": "no_trigger"},
    ]
    assert skillforge.trigger_eval(brain_home, "restore-safety", cases) == (
        skillforge.trigger_eval(brain_home, "restore-safety", cases)
    )


def test_workflow_eval_structural(brain_home):
    _forge(brain_home)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = skillforge.workflow_eval(brain_home, "restore-safety", data["workflow_scenarios"])
    assert result["structural"] is True
    assert result["procedure_steps"] >= 1
    assert result["failed"] == 0
    assert "caller's job" in result["note"]


def test_regression_eval(brain_home):
    _forge(brain_home)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ok = skillforge.regression_eval(brain_home, "restore-safety", data["regression_baselines"])
    assert ok["regression"] is False
    # Tamper the positive triggers so a baseline case stops matching -> regression.
    path = _skill(brain_home, "restore-safety")
    text = path.read_text(encoding="utf-8").replace("restore failed with stale sidecar", "zzz")
    path.write_text(text, encoding="utf-8")
    bad = skillforge.regression_eval(brain_home, "restore-safety", data["regression_baselines"])
    assert bad["regression"] is True
    assert bad["failed"] == 1


# ---------------------------------------------------------------------------
# Security review
# ---------------------------------------------------------------------------


def test_security_review_flags_heuristics(brain_home):
    _forge(brain_home)
    path = _skill(brain_home, "restore-safety")
    dirty = json.loads(FIXTURE.read_text(encoding="utf-8"))["dirty_security"]
    path.write_text(dirty, encoding="utf-8")
    result = skillforge.security_review(brain_home, "restore-safety")
    assert result["passed"] is False
    categories = {f["category"] for f in result["findings"]}
    assert categories == {"destructive", "secret", "exfiltration", "instruction-injection"}


def test_security_review_clean_passes(brain_home):
    _forge(brain_home)
    result = skillforge.security_review(brain_home, "restore-safety")
    assert result["passed"] is True
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# Shadow
# ---------------------------------------------------------------------------


def test_shadow_refuses_unvalidated_and_moves_validated(brain_home):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _forge(brain_home)
    # A tampered candidate fails validation -> refuse.
    path = _skill(brain_home, "restore-safety")
    path.write_text(
        path.read_text(encoding="utf-8").replace("# Output\n\n(fill me)\n", ""), encoding="utf-8"
    )
    with pytest.raises(BrainError, match="Refusing to shadow"):
        skillforge.shadow_candidate(
            brain_home,
            "restore-safety",
            trigger_cases=data["trigger_cases"],
            baseline_cases=data["regression_baselines"],
        )
    assert skillforge.list_candidates(brain_home) == ["restore-safety"]
    assert skillforge.list_shadow(brain_home) == []
    # Drop the tampered candidate and forge fresh under a new name.
    import shutil as _sh

    for leftover in list((brain_home / "skills" / "candidates").iterdir()):
        _sh.rmtree(leftover)
    _forge(brain_home, name="good-skill")
    target = skillforge.shadow_candidate(
        brain_home,
        "good-skill",
        trigger_cases=data["trigger_cases"],
        baseline_cases=data["regression_baselines"],
    )
    assert target == brain_home / "skills" / "shadow" / "good-skill"
    assert skillforge.list_candidates(brain_home) == []
    assert skillforge.list_shadow(brain_home) == ["good-skill"]
    assert (target / "SKILL.md").exists()
    # No double move: shadow target exists -> refuse.
    _forge(brain_home, name="good-skill")
    with pytest.raises(BrainError, match="Shadow target already exists"):
        skillforge.shadow_candidate(
            brain_home,
            "good-skill",
            trigger_cases=data["trigger_cases"],
            baseline_cases=data["regression_baselines"],
        )


def test_shadow_requires_evals(brain_home):
    _forge(brain_home, name="needs-evals")
    # Without passing trigger cases, a case that fails blocks the move.
    with pytest.raises(BrainError, match="trigger eval failed"):
        skillforge.shadow_candidate(
            brain_home,
            "needs-evals",
            trigger_cases=[{"text": "unrelated text", "expect": "trigger"}],
            baseline_cases=[{"text": "unrelated text", "expect": "trigger"}],
        )
    assert skillforge.list_candidates(brain_home) == ["needs-evals"]


def test_list_candidates_and_shadow_empty(brain_home):
    assert skillforge.list_candidates(brain_home) == []
    assert skillforge.list_shadow(brain_home) == []


# ---------------------------------------------------------------------------
# Hypothesis: trigger_eval is deterministic
# ---------------------------------------------------------------------------


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.text(min_size=1, max_size=60), min_size=0, max_size=8))
def test_trigger_eval_random_deterministic(brain_home, texts):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    _forge(home, name="skill")
    cases = [
        {"text": text, "expect": "trigger" if index % 2 == 0 else "no_trigger"}
        for index, text in enumerate(texts)
    ]
    first = skillforge.trigger_eval(home, "skill", cases)
    second = skillforge.trigger_eval(home, "skill", cases)
    assert first == second
    assert first["total"] == len(cases)


def test_security_review_ruff_format_is_clean(brain_home):
    _forge(brain_home)
    path = _skill(brain_home, "restore-safety")
    path.write_text(
        "# Safety\nrun ruff format on the edited files only.\n# Procedure\n1. restore the backup\n",
        encoding="utf-8",
    )
    result = skillforge.security_review(brain_home, "restore-safety")
    assert result["passed"] is True


def test_security_review_disk_format_flagged(brain_home):
    _forge(brain_home)
    path = _skill(brain_home, "restore-safety")
    path.write_text(
        "# Safety\nformat c: /q to wipe the drive.\n# Procedure\n1. restore the backup\n",
        encoding="utf-8",
    )
    result = skillforge.security_review(brain_home, "restore-safety")
    assert result["passed"] is False
    assert any(f["category"] == "destructive" for f in result["findings"])


# ---------------------------------------------------------------------------
# SEC-03: skill lifecycle path escape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "..\\escape",
        "a/b",
        "a\\b",
        "/abs",
        "C:\\abs",
        "\\srv\\share",
        "a\nb",
        "a*b",
        ".",
        "..",
        "",
    ],
)
def test_forge_rejects_hostile_skill_names(brain_home, bad):
    """SEC-T038: traversal/hostile skill names cannot reach the filesystem."""
    with pytest.raises(BrainError):
        skillforge.forge_candidate(brain_home, bad, ["ep-1"])
    # nothing escaped the candidates root
    candidates = brain_home / "skills" / "candidates"
    assert list(candidates.iterdir()) == [] if candidates.exists() else True
    with pytest.raises(BrainError):
        skillforge.validate_candidate(brain_home, bad)
    with pytest.raises(BrainError):
        skillforge.security_review(brain_home, bad)
    with pytest.raises(BrainError):
        skillforge.skill_path(brain_home, bad)


def test_skill_lifecycle_files_never_leave_intended_root(brain_home):
    """SEC-T041 helper: lifecycle ops stay inside skills/ roots."""
    eids = [
        episodes.create_episode(
            brain_home,
            "correction",
            "summary",
            sections={"Trigger signals": "t", "Reusable lesson": "l"},
        )
    ]
    path = skillforge.forge_candidate(brain_home, "safe-skill-1", eids)
    assert path.parent == brain_home / "skills" / "candidates" / "safe-skill-1"
    shadow = skillforge.shadow_candidate(brain_home, "safe-skill-1", [], [])
    assert shadow == brain_home / "skills" / "shadow" / "safe-skill-1"
    assert (brain_home / "skills" / "candidates" / "safe-skill-1").exists() is False
