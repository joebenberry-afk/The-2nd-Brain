"""Tests for the frontier review gate (Phase 21)."""

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import frontier
from second_brain.errors import BrainError


def _review(brain_home, cid="change-one", risk="high", verdict="approve", reviewer="r"):
    return frontier.frontier_review(brain_home, cid, "summary", risk, reviewer, verdict)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_review_validation(brain_home):
    with pytest.raises(BrainError, match="change_id"):
        frontier.frontier_review(brain_home, "  ", "s", "high", "r", "approve")
    with pytest.raises(BrainError, match="summary"):
        frontier.frontier_review(brain_home, "c1", "  ", "high", "r", "approve")
    with pytest.raises(BrainError, match="reviewer"):
        frontier.frontier_review(brain_home, "c1", "s", "high", "", "approve")
    with pytest.raises(BrainError, match="risk"):
        frontier.frontier_review(brain_home, "c1", "s", "extreme", "r", "approve")
    with pytest.raises(BrainError, match="verdict"):
        frontier.frontier_review(brain_home, "c1", "s", "high", "r", "maybe")


def test_review_file_content(brain_home):
    path = frontier.frontier_review(
        brain_home, "c1", "summary text", "medium", "alice", "request_changes", notes="add tests"
    )
    assert path == brain_home / "frontier" / "c1.md"
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["change_id"] == "c1"
    assert data["summary"] == "summary text"
    assert data["risk"] == "medium"
    assert data["reviewer"] == "alice"
    assert data["verdict"] == "request_changes"
    assert data["notes"] == "add tests"
    assert data["reviewed_at"]


# ---------------------------------------------------------------------------
# Sequence / collision / finality
# ---------------------------------------------------------------------------


def test_review_sequence_latest_wins(brain_home):
    first = _review(brain_home, verdict="approve")
    assert first.name == "change-one.md"
    second = _review(brain_home, verdict="request_changes")
    assert second.name == "change-one-2.md"
    third = _review(brain_home, verdict="approve")
    assert third.name == "change-one-3.md"
    assert frontier.gate_check(brain_home, "change-one")["ok"] is True
    assert frontier.frontier_status(brain_home, "change-one")["latest_verdict"] == "approve"


def test_reject_is_final(brain_home):
    _review(brain_home, verdict="approve")
    rejected = _review(brain_home, verdict="reject")
    assert rejected.name == "change-one-2.md"
    assert frontier.gate_check(brain_home, "change-one")["ok"] is False
    assert "rejected" in frontier.gate_check(brain_home, "change-one")["missing"][0]
    with pytest.raises(BrainError, match="rejected and cannot be re-reviewed"):
        _review(brain_home, verdict="approve")  # final: even approve cannot follow reject
    assert frontier.gate_check(brain_home, "change-one")["ok"] is False  # permanently blocked


def test_first_review_file_exclusive(brain_home):
    _review(brain_home)
    # Re-review after approve uses the -2 sequence, never overwrites c1.md.
    path = _review(brain_home, verdict="request_changes")
    assert path.name == "change-one-2.md"
    first = (brain_home / "frontier" / "change-one.md").read_text(encoding="utf-8")
    assert '"verdict": "approve"' in first  # untouched


# ---------------------------------------------------------------------------
# Gate semantics matrix + acceptance
# ---------------------------------------------------------------------------


def test_gate_semantics_matrix(brain_home):
    assert frontier.gate_check(brain_home, "never-reviewed") == {
        "ok": False,
        "missing": ["no review"],
    }
    _review(brain_home, cid="appr", verdict="approve")
    assert frontier.gate_check(brain_home, "appr") == {"ok": True, "missing": []}
    _review(brain_home, cid="req", verdict="request_changes")
    gate = frontier.gate_check(brain_home, "req")
    assert gate["ok"] is False and "request_changes" in gate["missing"][0]
    _review(brain_home, cid="rej", verdict="reject")
    gate = frontier.gate_check(brain_home, "rej")
    assert gate["ok"] is False and "rejected" in gate["missing"][0]


def test_acceptance_high_risk_requires_approval(brain_home):
    # High-risk change with no review: NOT activatable.
    hold = frontier.require_review(brain_home, "pol-change", "flip default policy", risk="high")
    assert hold is None  # hard gate
    assert frontier.gate_check(brain_home, "pol-change")["ok"] is False
    assert frontier.list_pending(brain_home) == ["pol-change"]
    assert frontier.frontier_status(brain_home)["pending_high_risk"] == ["pol-change"]
    # Approve clears the gate.
    _review(brain_home, cid="pol-change", verdict="approve")
    assert frontier.gate_check(brain_home, "pol-change")["ok"] is True
    assert frontier.list_pending(brain_home) == []  # hold remains but gate is cleared
    # Rejected change is permanently blocked.
    _review(brain_home, cid="pol-change", verdict="reject")
    assert frontier.gate_check(brain_home, "pol-change")["ok"] is False


def test_require_review_noop_with_existing_review(brain_home):
    _review(brain_home, cid="c1", verdict="approve")
    path = frontier.require_review(brain_home, "c1", "summary", risk="high")
    assert path == brain_home / "frontier" / "c1.md"
    assert frontier.list_pending(brain_home) == []


def test_require_review_low_risk_draft_marker(brain_home):
    hold = frontier.require_review(brain_home, "low-change", "docs tweak", risk="low")
    assert hold is not None  # draft-only marker, not a hard gate
    assert hold.name == "low-change.hold"
    assert frontier.gate_check(brain_home, "low-change")["ok"] is False  # still needs approval
    assert frontier.list_pending(brain_home) == ["low-change"]


def test_status_counts_by_latest_verdict(brain_home):
    _review(brain_home, cid="a", risk="low", verdict="approve")
    _review(brain_home, cid="b", risk="high", verdict="reject")
    _review(brain_home, cid="c", risk="medium", verdict="request_changes")
    _review(brain_home, cid="d", risk="high", verdict="approve")
    _review(brain_home, cid="d", risk="high", verdict="request_changes")  # superseded
    status = frontier.frontier_status(brain_home)
    assert status["total"] == 4
    assert status["approved"] == 1  # d's latest is request_changes
    assert status["rejected"] == 1
    assert status["request_changes"] == 2
    assert status["by_risk"] == {"low": 1, "medium": 1, "high": 2}


def test_status_and_gate_deterministic(brain_home):
    _review(brain_home, cid="c1", verdict="approve")
    _review(brain_home, cid="c1", verdict="request_changes")
    assert frontier.frontier_status(brain_home) == frontier.frontier_status(brain_home)
    assert frontier.gate_check(brain_home, "c1") == frontier.gate_check(brain_home, "c1")


# ---------------------------------------------------------------------------
# Hypothesis: verdict sequences vs brute-force reference
# ---------------------------------------------------------------------------


def _reference(verdicts):
    """Brute-force gate reference: reject is terminal; else latest wins."""
    latest = None
    for verdict in verdicts:
        if verdict == "reject":
            return "blocked"
        latest = verdict
    return "ok" if latest == "approve" else "blocked"


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.sampled_from(("approve", "reject", "request_changes")), min_size=0, max_size=8))
def test_verdict_sequences_match_reference(brain_home, verdicts):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    rejected = False
    for verdict in verdicts:
        if verdict == "reject":
            if rejected:
                # A second reject (after an existing reject) is refused.
                with pytest.raises(BrainError, match="cannot be re-reviewed"):
                    frontier.frontier_review(home, "change", "s", "high", "r", verdict)
            else:
                # The first reject is recordable and seals finality.
                frontier.frontier_review(home, "change", "s", "high", "r", verdict)
                rejected = True
            break  # terminal: nothing can be recorded after a reject
        frontier.frontier_review(home, "change", "s", "high", "r", verdict)
    expected_ok = _reference(verdicts) == "ok"
    assert frontier.gate_check(home, "change")["ok"] is expected_ok
    # Determinism.
    assert frontier.gate_check(home, "change") == frontier.gate_check(home, "change")


def test_change_id_digit_suffix_rejected(brain_home):
    from second_brain import frontier

    for fn in (
        lambda cid: frontier.frontier_review(brain_home, cid, "s", "high", "r", "approve"),
        lambda cid: frontier.require_review(brain_home, cid, "s"),
        lambda cid: frontier.gate_check(brain_home, cid),
    ):
        with pytest.raises(BrainError):
            fn("policy-2")


# ---------------------------------------------------------------------------
# SEC-04: frontier ID traversal / glob injection
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
        "*",
        "?",
        "[x]",
        "a*b",
        ".",
        "..",
        "",
        "  ",
    ],
)
def test_frontier_rejects_hostile_change_ids(brain_home, bad):
    """SEC-T043/T044: traversal and glob metacharacters are rejected."""
    with pytest.raises(BrainError):
        frontier.frontier_review(brain_home, bad, "s", "high", "r", "approve")
    with pytest.raises(BrainError):
        frontier.require_review(brain_home, bad, "s", risk="high")
    with pytest.raises(BrainError):
        frontier.gate_check(brain_home, bad)
    with pytest.raises(BrainError):
        frontier.latest_review(brain_home, bad)
    assert not (brain_home.parent / "escape").exists()


def test_frontier_review_artifacts_remain_inside_root(brain_home):
    """SEC-T045: review and hold artifacts stay beneath frontier/."""
    path = _review(brain_home, cid="contained-change")
    assert path.parent == brain_home / "frontier"
    hold = frontier.require_review(brain_home, "hold-change", "s", risk="low")
    assert hold is not None
    assert hold.parent == brain_home / "frontier" / "pending"
    # sequence files also stay inside
    frontier.frontier_review(brain_home, "contained-change", "s2", "high", "r", "approve")
    files = sorted(brain_home.rglob("contained-change*.md"))
    assert all(brain_home / "frontier" in f.parents for f in files)
    # reading a similar-named id cannot reach another id's files
    assert frontier.latest_review(brain_home, "contained") is None


def test_frontier_review_files_exact_name_matching(brain_home):
    """A change id must not match sibling ids via glob-like prefix expansion."""
    _review(brain_home, cid="alpha")
    _review(brain_home, cid="alphabet")
    assert frontier.frontier_status(brain_home, "alpha")["latest_verdict"] == "approve"
    assert frontier.frontier_status(brain_home, "alphabet")["latest_verdict"] == "approve"
    files = [p.name for p in (brain_home / "frontier").iterdir() if p.suffix == ".md"]
    assert "alphabet.md" in files and "alpha.md" in files
    # alpha's file set does not include alphabet.md
    from second_brain.frontier import _review_files

    assert [p.name for p in _review_files(brain_home, "alpha")] == ["alpha.md"]


def test_frontier_status_validates_change_id_before_read(brain_home):
    """SEC-T046 regression (validator-found): frontier_status must validate
    change_id before building any path; hostile ids cannot read files
    outside frontier/."""
    # A sentinel that would raise a distinctive error if it were read.
    sentinel = brain_home / "secret.md"
    sentinel.write_text("NOT JSON {{{", encoding="utf-8")
    bad_ids = [
        "../secret",
        "..\\secret",
        "foo*",
        "foo?",
        "/abs",
        "C:\\abs",
        "\\srv\\share",
        "a\nb",
    ]
    for bad in bad_ids:
        with pytest.raises(BrainError, match="Invalid"):
            frontier.frontier_status(brain_home, bad)
    # The sentinel was never read: the failure was identifier rejection, not
    # a corrupt-file error.
    assert sentinel.read_text(encoding="utf-8") == "NOT JSON {{{"


def test_frontier_status_valid_change_id_still_works(brain_home):
    _review(brain_home, cid="status-ok")
    result = frontier.frontier_status(brain_home, "status-ok")
    assert set(result) == {"change_id", "reviews", "latest_verdict"}
    assert result["change_id"] == "status-ok"
    assert result["latest_verdict"] == "approve"
    assert len(result["reviews"]) == 1
