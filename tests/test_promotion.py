"""Tests for policy promotion with guards (Phase 23)."""

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import frontier, paths, plasticity, promotion, skillforge
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


def _bind(home, name, owner="steward-scout"):
    skillforge.bind_candidate(
        home,
        name,
        source_type="frontier",
        source_ref=f"frontier-{name}",
        owner=owner,
    )
    skillforge.record_evaluation(
        home,
        name,
        {
            "evaluation_id": f"eval-{name}",
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
        },
    )


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
    _bind(brain_home, "scout")
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
        "bound": True,
        "owner": True,
        "evaluation": True,
        "version": True,
    }
    assert record["owner"] == "steward-scout"
    assert record["candidate_id"].startswith("skill-candidate-")
    assert record["baseline_comparison"] == "passed"
    assert record["resulting_version"] == 1
    assert record["promotion_id"].startswith("promotion-")
    assert record["rollback_clear"] is True
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
    _bind(brain_home, "scout")
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
    _bind(brain_home, "incomplete")
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
    _bind(brain_home, "scout")
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


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.sampled_from(("shadow", "candidate", "active")),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
)
def test_guard_combos_match_reference(
    brain_home, to, has_evidence, frontier_ok, rolled_back, bound, dest_conflict
):
    home = _fresh(brain_home)
    _skill(home)
    if has_evidence:
        _evidence(home, "scout")
    if frontier_ok:
        _approve(home, "scout")
    if rolled_back:
        _rollback_record(home, "scout")
    if bound:
        _bind(home, "scout")
    if dest_conflict:
        _skill(home, name="scout", level="candidate")
    result = promotion.promote(home, "scout", "shadow", to)
    should_promote = (
        to == "candidate"
        and has_evidence
        and frontier_ok
        and not rolled_back
        and bound
        and not dest_conflict
    )
    assert result["promoted"] is should_promote
    if should_promote:
        assert (home / "skills" / "candidates" / "scout").is_dir()
    else:
        assert (home / "skills" / "shadow" / "scout").is_dir()


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
    _bind(brain_home, "record-me")
    result = promotion.promote(brain_home, "record-me", "shadow", "candidate")
    assert result["promoted"] is True
    record_path = Path(result["record_path"])
    assert record_path.parent == brain_home / "state" / "promotions"


# ---------------------------------------------------------------------------
# Audit F-01: publication and its record are one recoverable transaction
# ---------------------------------------------------------------------------


def _green_candidate(home, name="scout"):
    _skill(home, name=name)
    _evidence(home, name)
    _approve(home, name)
    _bind(home, name)


def test_promote_record_failure_rolls_back_publication(brain_home, monkeypatch):
    """A failed record write must not leave uncommitted active behaviour."""
    _green_candidate(brain_home)

    def boom(home, record):
        raise BrainError("simulated record write failure")

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_record", boom)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "record_failed"
    # Publication was rolled back: the skill is still a shadow skill.
    assert (brain_home / "skills" / "shadow" / "scout").is_dir()
    assert not (brain_home / "skills" / "candidates" / "scout").exists()
    assert promotion.promotion_status(brain_home, "scout")["records"] == []
    assert promotion.pending_publications(brain_home) == []
    # The rollback also restored the artifact's own status metadata.
    text = (brain_home / "skills" / "shadow" / "scout" / "SKILL.md").read_text(encoding="utf-8")
    assert "status: shadow" in text


def test_interrupted_publication_is_reconciled(brain_home, monkeypatch):
    """A crash between the move and the record is completed, not lost."""
    _green_candidate(brain_home)

    def boom(home, record):
        raise BrainError("simulated record write failure")

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_record", boom)
        patch.setattr(promotion, "_rollback_publication", lambda *a, **k: False)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "record_failed"
    assert result["rollback"] == "incomplete"
    assert (brain_home / "skills" / "candidates" / "scout").is_dir()
    assert len(promotion.pending_publications(brain_home)) == 1  # durable intent

    actions = promotion.reconcile_publications(brain_home)

    assert [action["action"] for action in actions] == ["committed"]
    assert promotion.pending_publications(brain_home) == []
    records = promotion.promotion_status(brain_home, "scout")["records"]
    assert len(records) == 1
    assert records[0]["to_level"] == "candidate"
    # Reconciling twice is a no-op.
    assert promotion.reconcile_publications(brain_home) == []


def test_reconcile_discards_publication_that_never_happened(brain_home, monkeypatch):
    """A journal entry for a move that never ran must not invent authority."""
    _green_candidate(brain_home)

    def boom(*args, **kwargs):
        raise BrainError("simulated move failure")

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_move_skill", boom)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "move_failed"
    assert promotion.pending_publications(brain_home) == []
    assert (brain_home / "skills" / "shadow" / "scout").is_dir()
    assert promotion.promotion_status(brain_home, "scout")["records"] == []


def test_demote_record_failure_rolls_back(brain_home, monkeypatch):
    _skill(brain_home, name="scout", level="active")

    def boom(home, record):
        raise BrainError("simulated record write failure")

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_record", boom)
        result = promotion.demote(brain_home, "scout", "shadow", "underperformed")

    assert result["demoted"] is False
    assert result["reason"] == "record_failed"
    assert promotion.is_active(brain_home, "scout") is True
    assert promotion.pending_publications(brain_home) == []


# ---------------------------------------------------------------------------
# Audit F-03: missing authority history fails closed
# ---------------------------------------------------------------------------


def test_promote_after_demote_requires_version_bump(brain_home):
    """The version gate still binds after a legitimate demotion."""
    _green_candidate(brain_home)
    assert promotion.promote(brain_home, "scout", "shadow", "candidate")["promoted"] is True
    assert promotion.promote(brain_home, "scout", "candidate", "active")["promoted"] is True
    assert promotion.demote(brain_home, "scout", "candidate", "incident")["demoted"] is True

    result = promotion.promote(brain_home, "scout", "candidate", "active")

    assert result["promoted"] is False
    assert result["reason"] == "version_not_incremented"


def test_version_baseline_survives_record_loss(brain_home):
    """The artifact-carried baseline stops a silent reset to first release."""
    _green_candidate(brain_home)
    assert promotion.promote(brain_home, "scout", "shadow", "candidate")["promoted"] is True
    assert promotion.promote(brain_home, "scout", "candidate", "active")["promoted"] is True
    marker = brain_home / "skills" / "active" / "scout" / promotion.AUTHORITY_MARKER
    assert json.loads(marker.read_text(encoding="utf-8"))["last_active_version"] == 1
    # Simulate a restore that carried the artifact but not its governance records.
    for record in (brain_home / "state" / "promotions").glob("*.json"):
        record.unlink()
    assert promotion.demote(brain_home, "scout", "candidate", "lossy restore check")["demoted"]

    result = promotion.promote(brain_home, "scout", "candidate", "active")

    assert result["promoted"] is False
    assert result["reason"] == "version_not_incremented"


def test_promote_fails_closed_when_no_version_history_survives(brain_home):
    """No records and no carried baseline: refuse, never grant first release."""
    _green_candidate(brain_home)
    assert promotion.promote(brain_home, "scout", "shadow", "candidate")["promoted"] is True
    assert promotion.promote(brain_home, "scout", "candidate", "active")["promoted"] is True
    assert promotion.demote(brain_home, "scout", "candidate", "incident")["demoted"] is True
    for record in (brain_home / "state" / "promotions").glob("*.json"):
        payload = json.loads(record.read_text(encoding="utf-8"))
        if payload.get("to_level") == "active":
            record.unlink()
    (brain_home / "skills" / "candidates" / "scout" / promotion.AUTHORITY_MARKER).unlink()

    result = promotion.promote(brain_home, "scout", "candidate", "active")

    assert result["promoted"] is False
    assert result["reason"] == "history_unavailable"
    assert (brain_home / "skills" / "candidates" / "scout").is_dir()


def test_authority_gaps_reports_active_skill_without_history(brain_home):
    _skill(brain_home, name="orphan", level="active")

    assert promotion.authority_gaps(brain_home) == ["orphan"]
    assert promotion.promotion_status(brain_home)["authority_gaps"] == ["orphan"]
    assert promotion.promotion_status(brain_home, "orphan")["authority_gaps"] == ["orphan"]


# ---------------------------------------------------------------------------
# Audit follow-up: failure boundaries found by the independent verification
# ---------------------------------------------------------------------------


def test_record_directory_failure_rolls_back_publication(brain_home):
    """A record-write failure of any kind must not leave usable active state."""
    _green_candidate(brain_home)
    # Make the record directory unusable: a file where the directory belongs.
    (brain_home / "state" / "promotions").write_text("not a directory", encoding="utf-8")

    result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] in {"journal_failed", "record_failed"}
    assert (brain_home / "skills" / "shadow" / "scout").is_dir()
    assert not (brain_home / "skills" / "candidates" / "scout").exists()
    assert promotion.pending_publications(brain_home) == []


def test_unexpected_record_error_rolls_back_publication(brain_home, monkeypatch):
    """An error that is not a BrainError must still roll the move back."""
    _green_candidate(brain_home)

    def boom(*args, **kwargs):
        raise PermissionError("simulated permission failure")

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_record", boom)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] == "record_failed"
    assert (brain_home / "skills" / "shadow" / "scout").is_dir()
    assert promotion.pending_publications(brain_home) == []


def test_reconcile_skips_in_flight_publication(brain_home, monkeypatch):
    """Automatic recovery must not commit a publication a caller is finishing."""
    _green_candidate(brain_home)

    def boom(*args, **kwargs):
        raise PermissionError("simulated permission failure")

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_record", boom)
        patch.setattr(promotion, "_rollback_publication", lambda *a, **k: False)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["rollback"] == "incomplete"
    assert len(promotion.pending_publications(brain_home)) == 1
    # A fresh journal is in flight: automatic recovery leaves it alone.
    actions = promotion.reconcile_publications(
        brain_home, min_age_seconds=promotion.RECONCILE_GRACE_SECONDS
    )
    assert [a["action"] for a in actions] == ["in_flight"]
    assert promotion.promotion_status(brain_home, "scout")["records"] == []

    # An operator pass reconciles it, record and authority marker together.
    actions = promotion.reconcile_publications(brain_home)
    assert [a["action"] for a in actions] == ["committed"]
    assert len(promotion.promotion_status(brain_home, "scout")["records"]) == 1
    marker = brain_home / "skills" / "candidates" / "scout" / promotion.AUTHORITY_MARKER
    assert json.loads(marker.read_text(encoding="utf-8"))["last_active_version"] is None


def test_reconcile_rejects_hostile_journal(brain_home):
    """A journal is data: it may not name a path outside the skill tree."""
    _skill(brain_home, name="scout")
    outside = brain_home.parent / "outside-hostile"
    pending = brain_home / "state" / "promotions" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "hostile.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-hostile",
                    "skill_name": str(outside),
                    "from_level": "shadow",
                    "to_level": "candidate",
                    "ts": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert [a["action"] for a in actions] == ["invalid"]
    assert not outside.exists()
    assert not list(brain_home.parent.glob("outside-hostile*"))
    assert promotion.pending_publications(brain_home) == ["hostile.json"]


def test_reconcile_survives_corrupt_record_store(brain_home):
    """When a damaged record cannot even be set aside, recovery reports it."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    (promotions / "scout-1.json").write_text("{", encoding="utf-8")
    (promotions / "corrupt").write_text("blocked", encoding="utf-8")  # quarantine unavailable
    pending = promotions / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "shadow",
                    "to_level": "shadow",
                    "ts": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert [a["action"] for a in actions] == ["records_unreadable"]
    assert promotion.pending_publications(brain_home) == ["p1.json"]
    assert promotion.unreadable_publications(brain_home) == []


def test_reconcile_heals_status_of_unpublished_skill(brain_home):
    """A status change without the move is repaired, not left mismatched."""
    _skill(brain_home, name="scout")
    skill_file = brain_home / "skills" / "shadow" / "scout" / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("status: shadow", "status: candidate"),
        encoding="utf-8",
    )
    pending = brain_home / "state" / "promotions" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "shadow",
                    "to_level": "candidate",
                    "ts": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert [a["action"] for a in actions] == ["discarded"]
    assert "status: shadow" in skill_file.read_text(encoding="utf-8")


def test_demote_seeds_marker_from_committed_history(brain_home):
    """A demotion reconstructs the active version from committed records."""
    _skill(brain_home, name="scout", level="active")
    promotion._write_record(
        brain_home,
        {
            "promotion_id": "promotion-historic",
            "skill_name": "scout",
            "from_level": "candidate",
            "to_level": "active",
            "ts": "2026-01-01T00:00:00+00:00",
            "session_id": "",
            "resulting_version": 5,
        },
    )

    result = promotion.demote(brain_home, "scout", "candidate", "planned demotion")

    assert result["demoted"] is True
    marker = brain_home / "skills" / "candidates" / "scout" / promotion.AUTHORITY_MARKER
    assert json.loads(marker.read_text(encoding="utf-8"))["last_active_version"] == 5


def test_recovery_ignores_an_inflated_journal_version(brain_home):
    """A journal cannot raise the recorded baseline above the artifact's own."""
    skill_dir = brain_home / "skills" / "active" / "scout"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scout\nstatus: active\nversion: 1\n---\n\n# scout\n", encoding="utf-8"
    )
    pending = brain_home / "state" / "promotions" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "candidate",
                    "to_level": "active",
                    "ts": "2026-01-01T00:00:00+00:00",
                    "resulting_version": 999,
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert [a["action"] for a in actions] == ["committed"]
    records = promotion.promotion_status(brain_home, "scout")["records"]
    assert records[0]["resulting_version"] == 1
    marker = skill_dir / promotion.AUTHORITY_MARKER
    assert json.loads(marker.read_text(encoding="utf-8"))["last_active_version"] == 1


def test_recovery_keeps_intent_when_marker_write_fails(brain_home, monkeypatch):
    """The intent survives until authority really is carried by the artifact."""
    skill_dir = brain_home / "skills" / "active" / "scout"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scout\nstatus: active\nversion: 1\n---\n\n# scout\n", encoding="utf-8"
    )
    pending = brain_home / "state" / "promotions" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "candidate",
                    "to_level": "active",
                    "ts": "2026-01-01T00:00:00+00:00",
                    "resulting_version": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_authority_marker", lambda *a, **k: False)
        actions = promotion.reconcile_publications(brain_home)

    assert [a["action"] for a in actions] == ["marker_failed"]
    assert promotion.pending_publications(brain_home) == ["p1.json"]

    # A later pass repairs the marker instead of reporting nothing to do.
    actions = promotion.reconcile_publications(brain_home)
    assert [a["action"] for a in actions] == ["already_committed"]
    marker = skill_dir / promotion.AUTHORITY_MARKER
    assert json.loads(marker.read_text(encoding="utf-8"))["last_active_version"] == 1


def test_recovery_quarantines_another_skills_damaged_record(brain_home):
    """Damage blocks the store as a whole, so quarantine must scan it as a whole."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    (promotions / "other-1.json").write_text("{", encoding="utf-8")
    pending = promotions / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "shadow",
                    "to_level": "shadow",
                    "ts": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert actions[0]["action"] == "committed"
    assert actions[0]["records_quarantined"] == ["other-1.json"]
    archived = {
        p.read_text(encoding="utf-8") for p in (promotions / "corrupt").glob("other-1.*.json")
    }
    assert archived == {"{"}


def test_recovery_quarantines_a_non_object_record(brain_home):
    """The reader rejects non-object JSON, so quarantine must treat it as damage."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    (promotions / "scout-1.json").write_text("[]", encoding="utf-8")
    pending = promotions / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "shadow",
                    "to_level": "shadow",
                    "ts": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert actions[0]["action"] == "committed"
    assert actions[0]["records_quarantined"] == ["scout-1.json"]
    archived = {
        p.read_text(encoding="utf-8") for p in (promotions / "corrupt").glob("scout-1.*.json")
    }
    assert archived == {"[]"}


def test_quarantine_archives_every_damaged_payload(brain_home):
    """Repeated damage under one record name keeps every payload."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    (promotions / "scout-1.json").write_text("{first", encoding="utf-8")
    assert promotion._quarantine_corrupt_records(brain_home) == ["scout-1.json"]
    # The store reuses the name for a new record, which is damaged in turn.
    (promotions / "scout-1.json").write_text("{second", encoding="utf-8")
    assert promotion._quarantine_corrupt_records(brain_home) == ["scout-1.json"]

    archived = {p.read_text(encoding="utf-8") for p in (promotions / "corrupt").glob("*.json")}
    assert archived == {"{first", "{second"}


def test_record_name_claim_is_kept_after_the_commit(brain_home):
    """A committed name is never handed out again, and its record survives."""
    _skill(brain_home, name="scout")
    first = promotion._write_record(
        brain_home,
        {
            "promotion_id": "promotion-1",
            "skill_name": "scout",
            "from_level": "shadow",
            "to_level": "shadow",
            "ts": "2026-01-01T00:00:00+00:00",
        },
    )
    second = promotion._write_record(
        brain_home,
        {
            "promotion_id": "promotion-2",
            "skill_name": "scout",
            "from_level": "shadow",
            "to_level": "shadow",
            "ts": "2026-01-02T00:00:00+00:00",
        },
    )

    assert first.name == "scout-1.json"
    assert second.name == "scout-2.json"
    assert json.loads(first.read_text(encoding="utf-8"))["promotion_id"] == "promotion-1"


def test_marker_write_failure_keeps_the_intent_and_retries(brain_home, monkeypatch):
    """A publication whose marker could not be written stays retryable."""
    _green_candidate(brain_home)
    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_authority_marker", lambda *a, **k: False)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is True
    assert result["authority_marker"] == "unavailable"
    # The intent survives, so the missing baseline is not silently accepted.
    assert promotion.pending_publications(brain_home) == [
        f"{result['record']['promotion_id']}.json"
    ]

    actions = promotion.reconcile_publications(brain_home)

    assert [a["action"] for a in actions] == ["already_committed"]
    assert promotion.pending_publications(brain_home) == []
    records = promotion.promotion_status(brain_home, "scout")["records"]
    assert len(records) == 1  # the retry wrote no second record


def test_journal_cleanup_failure_does_not_fail_the_publication(brain_home, monkeypatch):
    """A completed publication does not report failure because cleanup failed."""
    _green_candidate(brain_home)
    real_unlink = Path.unlink

    def deny_journal(self, *args, **kwargs):
        if self.suffix == ".json" and self.parent.name == "pending":
            raise PermissionError("simulated journal cleanup failure")
        return real_unlink(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", deny_journal)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is True
    assert (brain_home / "skills" / "candidates" / "scout").is_dir()
    assert len(promotion.promotion_status(brain_home, "scout")["records"]) == 1
    # The leftover intent is reported, and reconciliation clears it.
    actions = promotion.reconcile_publications(brain_home)
    assert [a["action"] for a in actions] == ["already_committed"]
    assert promotion.pending_publications(brain_home) == []


def test_recovery_quarantines_undecodable_bytes(brain_home):
    """Damage is not always valid UTF-8; it must be quarantined all the same."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    (promotions / "other-1.json").write_bytes(b"\xff")
    pending = promotions / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "shadow",
                    "to_level": "shadow",
                    "ts": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert actions[0]["action"] == "committed"
    assert actions[0]["records_quarantined"] == ["other-1.json"]
    archived = {p.read_bytes() for p in (promotions / "corrupt").glob("other-1.*.json")}
    assert archived == {b"\xff"}


def test_stale_marker_level_is_not_authority(brain_home):
    """A marker naming another level is reported, and never read as authority."""
    skill_dir = brain_home / "skills" / "shadow" / "scout"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scout\nstatus: shadow\nversion: 1\n---\n\n# scout\n", encoding="utf-8"
    )
    (skill_dir / promotion.AUTHORITY_MARKER).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "skill_name": "scout",
                "last_level": "active",
                "last_active_version": 3,
                "last_promotion_id": "promotion-1",
            }
        ),
        encoding="utf-8",
    )

    assert promotion.stale_authority_markers(brain_home) == ["scout"]
    marker = promotion._read_authority_marker(brain_home, "scout")
    assert marker["stale_level"] == "active"
    assert marker["last_level"] is None
    # The version the marker carries still raises the baseline, but a marker
    # claiming "active" no longer counts as release history for a shadow skill.
    assert promotion._active_version_baseline(brain_home, "scout") == (3, True)

    (skill_dir / promotion.AUTHORITY_MARKER).write_text(
        json.dumps({"schema_version": 1, "skill_name": "scout", "last_level": "active"}),
        encoding="utf-8",
    )
    assert promotion._active_version_baseline(brain_home, "scout") == (None, False)


def test_doctor_reports_a_stale_marker(brain_home):
    """Doctor surfaces the mismatch instead of reporting clean authority."""
    from second_brain import doctor as doctor_mod

    skill_dir = brain_home / "skills" / "shadow" / "scout"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scout\nstatus: shadow\nversion: 1\n---\n\n# scout\n", encoding="utf-8"
    )
    (skill_dir / promotion.AUTHORITY_MARKER).write_text(
        json.dumps({"schema_version": 1, "skill_name": "scout", "last_level": "active"}),
        encoding="utf-8",
    )
    checks: list = []

    doctor_mod.check_governance(brain_home, checks)

    marker_checks = [c for c in checks if c.name == "governance marker"]
    assert len(marker_checks) == 1
    assert "scout" in marker_checks[0].detail


def test_superseded_publication_leaves_no_stale_marker(brain_home, monkeypatch):
    """A later move of the artifact must not leave a marker claiming the old level."""
    _green_candidate(brain_home)
    original_write_record = promotion._write_record

    def commit_then_supersede(home, record):
        path = original_write_record(home, record)
        # Model a concurrent publication for the same skill finishing after
        # this one committed: the artifact ends up back at shadow.
        source = home / "skills" / "candidates" / "scout"
        target = home / "skills" / "shadow" / "scout"
        source.rename(target)
        return path

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_record", commit_then_supersede)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is True
    assert result["authority_marker"] == "unavailable"
    assert promotion._read_authority_marker(brain_home, "scout").get("last_level") != "candidate"
    # The intent is not silently dropped: the next pass sees the artifact
    # elsewhere and discards it.
    actions = promotion.reconcile_publications(brain_home)
    assert [a["action"] for a in actions] == ["discarded"]


def test_quarantine_ignores_a_record_that_replaced_the_damage(brain_home):
    """Bytes that are a valid record are never archived as damage."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    healthy = json.dumps(
        {
            "promotion_id": "promotion-1",
            "skill_name": "scout",
            "from_level": "shadow",
            "to_level": "shadow",
            "ts": "2026-01-01T00:00:00+00:00",
        }
    )
    (promotions / "scout-1.json").write_text(healthy, encoding="utf-8")

    assert promotion._quarantine_corrupt_records(brain_home) == []
    assert (promotions / "scout-1.json").read_text(encoding="utf-8") == healthy
    assert not (promotions / "corrupt").exists()


def test_quarantine_republishes_an_incomplete_archive(brain_home):
    """A partial archive from an interrupted pass is not trusted as evidence."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    (promotions / "corrupt").mkdir(parents=True, exist_ok=True)
    damaged = "{truncated"
    digest = hashlib.sha256(damaged.encode()).hexdigest()
    # A leftover partial archive naming this content, holding different bytes.
    (promotions / "corrupt" / f"scout-1.{digest}.json").write_text("{partial", encoding="utf-8")
    (promotions / "scout-1.json").write_text(damaged, encoding="utf-8")

    assert promotion._quarantine_corrupt_records(brain_home) == ["scout-1.json"]
    archived = (promotions / "corrupt" / f"scout-1.{digest}.json").read_text(encoding="utf-8")
    assert archived == damaged
    assert not (promotions / "scout-1.json").exists()


def test_recovery_quarantines_a_corrupt_record(brain_home):
    """A damaged record is preserved aside, and recovery still completes."""
    _skill(brain_home, name="scout")
    promotions = brain_home / "state" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    (promotions / "scout-1.json").write_text("{", encoding="utf-8")
    pending = promotions / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "p1.json").write_text(
        json.dumps(
            {
                "record": {
                    "promotion_id": "promotion-1",
                    "skill_name": "scout",
                    "from_level": "shadow",
                    "to_level": "shadow",
                    "ts": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    actions = promotion.reconcile_publications(brain_home)

    assert actions[0]["action"] == "committed"
    assert actions[0]["records_quarantined"] == ["scout-1.json"]
    archived = {
        p.read_text(encoding="utf-8") for p in (promotions / "corrupt").glob("scout-1.*.json")
    }
    assert archived == {"{"}
    assert promotion.pending_publications(brain_home) == []


def test_concurrent_commit_completes_the_publication(brain_home, monkeypatch):
    """A record another writer committed for this publication is never deleted.

    Recovery can commit the journal while the original writer is failing; the
    store is append-only, so the consistent outcome is a completed publication
    whose authority marker matches the committed record.
    """
    _green_candidate(brain_home)
    original_write_record = promotion._write_record

    def commit_then_fail(home, record):
        # Model a recovery pass committing this publication's record first.
        original_write_record(home, record)
        raise PermissionError("simulated record failure after commit")

    with monkeypatch.context() as patch:
        patch.setattr(promotion, "_write_record", commit_then_fail)
        result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is True
    assert result["record_recovered"] is True
    assert (brain_home / "skills" / "candidates" / "scout").is_dir()
    records = promotion.promotion_status(brain_home, "scout")["records"]
    assert [r["promotion_id"] for r in records] == [result["record"]["promotion_id"]]
    assert result["record_path"] == str(brain_home / "state" / "promotions" / "scout-1.json")
    marker = json.loads(
        (brain_home / "skills" / "candidates" / "scout" / promotion.AUTHORITY_MARKER).read_text(
            encoding="utf-8"
        )
    )
    assert marker["last_level"] == "candidate"
    assert promotion.pending_publications(brain_home) == []
    # The authority the concurrent writer committed is still there and usable.
    assert promotion._active_version_baseline(brain_home, "scout")[0] is None


def test_move_failure_keeps_status_consistent(brain_home):
    """A destination conflict must not leave the artifact claiming the target level."""
    _green_candidate(brain_home)
    # Block the candidate parent directory so the move cannot happen.
    candidates = brain_home / "skills" / "candidates"
    for child in sorted(candidates.iterdir()):
        if child.is_dir():
            import shutil as _shutil

            _shutil.rmtree(child)
    candidates.rmdir()
    candidates.write_text("blocked", encoding="utf-8")

    result = promotion.promote(brain_home, "scout", "shadow", "candidate")

    assert result["promoted"] is False
    assert result["reason"] in {"move_failed", "destination_exists"}
    skill_file = brain_home / "skills" / "shadow" / "scout" / "SKILL.md"
    assert "status: shadow" in skill_file.read_text(encoding="utf-8")
    assert promotion.pending_publications(brain_home) == []
