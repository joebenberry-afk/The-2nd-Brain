"""Tests for the immune system rollback gate (Phase 22)."""

import hashlib
import uuid
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import frontier, immune
from second_brain.errors import BrainError


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _policy_file(home, name="policy-one", content="good state"):
    path = home / "config" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _setup(
    home,
    metric="tests_failed",
    operator=">",
    value=0,
    window=3,
    trigger_id="t1",
    policy_id="policy-one",
    target_content="good state",
    backup_content="good state",
):
    """Target file holds the CURRENT content; backup_of is the sha256 of the
    recorded GOOD state (which may differ when the target regressed)."""
    target = _policy_file(home, policy_id, target_content)
    immune.register_trigger(
        home,
        trigger_id,
        {
            "metric": metric,
            "operator": operator,
            "value": value,
            "window": window,
        },
    )
    immune.register_policy(
        home,
        policy_id,
        {
            "rollback_trigger": trigger_id,
            "rollback_target": str(target),
            "backup_of": _sha256_text(backup_content),
        },
    )
    return target


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_register_validation(brain_home):
    with pytest.raises(BrainError, match="policy_id"):
        immune.register_policy(
            brain_home,
            "  ",
            {"rollback_trigger": "t", "rollback_target": "x", "backup_of": "a" * 64},
        )
    with pytest.raises(BrainError, match="backup_of"):
        immune.register_policy(
            brain_home, "p", {"rollback_trigger": "t", "rollback_target": "x", "backup_of": "short"}
        )
    with pytest.raises(BrainError, match="metric"):
        immune.register_trigger(
            brain_home, "t", {"metric": "nope", "operator": ">", "value": 1, "window": 2}
        )
    with pytest.raises(BrainError, match="operator"):
        immune.register_trigger(
            brain_home, "t", {"metric": "tests_failed", "operator": "~", "value": 1, "window": 2}
        )
    with pytest.raises(BrainError, match="value"):
        immune.register_trigger(
            brain_home,
            "t",
            {"metric": "tests_failed", "operator": ">", "value": "high", "window": 2},
        )  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="window"):
        immune.register_trigger(
            brain_home, "t", {"metric": "tests_failed", "operator": ">", "value": 1, "window": 0}
        )
    with pytest.raises(BrainError, match="metric"):
        immune.ingest_metric(brain_home, "bogus", 1.0, "r1")
    with pytest.raises(BrainError, match="run_id"):
        immune.ingest_metric(brain_home, "tests_failed", 1.0, "  ")


# ---------------------------------------------------------------------------
# Metrics / trigger evaluation
# ---------------------------------------------------------------------------


def test_ingest_and_window_semantics(brain_home):
    _setup(brain_home)  # tests_failed > 0, window 3
    for value in (0, 0, 2):
        immune.ingest_metric(brain_home, "tests_failed", value, f"run-{value}")
    result = immune.check_triggers(brain_home)
    assert len(result) == 1
    assert result[0]["matched"] is True
    assert result[0]["computed"] == 2.0
    assert result[0]["policy_ids"] == ["policy-one"]
    assert [s["value"] for s in result[0]["samples"]] == [0.0, 0.0, 2.0]
    # Stale samples outside the window don't match: the failing 2 scrolls out.
    for value in (0, 0):
        immune.ingest_metric(brain_home, "tests_failed", value, "run-fix")
    result = immune.check_triggers(brain_home)
    assert result[0]["matched"] is False
    assert result[0]["computed"] == 0.0


def test_trigger_operators(brain_home):
    immune.register_trigger(
        brain_home, "t2", {"metric": "f1_delta", "operator": "<=", "value": -0.1, "window": 1}
    )
    immune.ingest_metric(brain_home, "f1_delta", -0.2, "r1")
    assert immune.check_triggers(brain_home)[0]["matched"] is True
    immune.ingest_metric(brain_home, "f1_delta", 0.0, "r2")
    assert immune.check_triggers(brain_home)[0]["matched"] is False


def test_metrics_truncation(brain_home):
    for i in range(1050):
        immune.ingest_metric(brain_home, "tests_failed", float(i % 2), f"run-{i}")
    records = immune.read_metrics(brain_home)
    assert len(records) == immune.MAX_METRICS_LINES
    assert records[-1]["run_id"] == "run-1049"


def test_check_triggers_deterministic(brain_home):
    _setup(brain_home)
    immune.ingest_metric(brain_home, "tests_failed", 1.0, "r1")
    assert immune.check_triggers(brain_home) == immune.check_triggers(brain_home)


# ---------------------------------------------------------------------------
# Acceptance matrix
# ---------------------------------------------------------------------------


def test_acceptance_matching_trigger_enables_rollback(brain_home):
    target = _setup(brain_home, target_content="bad state now")
    immune.ingest_metric(brain_home, "tests_failed", 3.0, "run-3")
    result = immune.rollback(brain_home, "policy-one", "t1", "tests regressed")
    assert result["rolled_back"] is True
    assert not target.exists()  # moved aside
    backup = brain_home / "immune" / "rollbacks"
    moved = list(backup.glob("policy-one-*.bak"))
    assert len(moved) == 1
    assert moved[0].read_text(encoding="utf-8") == "bad state now"
    records = immune.rollback_log(brain_home)
    assert len(records) == 1
    assert records[0]["policy_id"] == "policy-one"
    assert records[0]["trigger"] == "t1"
    assert records[0]["reason"] == "tests regressed"
    assert records[0]["restored_from_sha"] == _sha256_text("bad state now")


def test_acceptance_non_matching_metrics_no_mutation(brain_home):
    target = _setup(brain_home, target_content="bad state now")
    immune.ingest_metric(brain_home, "tests_failed", 0.0, "run-0")  # does not match > 0
    result = immune.rollback(brain_home, "policy-one", "t1", "why")
    assert result == {"rolled_back": False, "reason": "trigger_not_matched"}
    assert target.exists()  # untouched
    assert target.read_text(encoding="utf-8") == "bad state now"
    assert immune.rollback_log(brain_home) == []


def test_acceptance_frontier_approved_blocks_rollback(brain_home):
    target = _setup(brain_home, target_content="bad state now")
    frontier.frontier_review(brain_home, "policy-one", "s", "high", "r", "approve")
    immune.ingest_metric(brain_home, "tests_failed", 3.0, "run-3")
    result = immune.rollback(brain_home, "policy-one", "t1", "regressed")
    assert result == {"rolled_back": False, "reason": "frontier_approved"}
    assert target.exists()


def test_acceptance_no_change_refused(brain_home):
    target = _setup(brain_home, target_content="good state")  # matches backup_of
    immune.ingest_metric(brain_home, "tests_failed", 3.0, "run-3")
    result = immune.rollback(brain_home, "policy-one", "t1", "regressed")
    assert result == {"rolled_back": False, "reason": "no_change"}
    assert target.exists()


def test_acceptance_double_rollback_refused(brain_home):
    target = _setup(brain_home, target_content="bad state now")
    immune.ingest_metric(brain_home, "tests_failed", 3.0, "run-3")
    assert immune.rollback(brain_home, "policy-one", "t1", "r1")["rolled_back"] is True
    # Second rollback refused until re-registered.
    result = immune.rollback(brain_home, "policy-one", "t1", "r2")
    assert result == {"rolled_back": False, "reason": "already_rolled_back"}
    # Re-register (new guard) -> rollback allowed again.
    _policy_file(brain_home, "policy-one", "bad again")
    immune.register_policy(
        brain_home,
        "policy-one",
        {
            "rollback_trigger": "t1",
            "rollback_target": str(target),
            "backup_of": _sha256_text("good state"),
        },
    )
    immune.ingest_metric(brain_home, "tests_failed", 5.0, "run-5")
    assert immune.rollback(brain_home, "policy-one", "t1", "r3")["rolled_back"] is True
    assert len(immune.rollback_log(brain_home)) == 2


def test_rollback_wrong_trigger_and_unknown_policy(brain_home):
    _setup(brain_home, target_content="bad")
    with pytest.raises(BrainError, match="Unknown policy"):
        immune.rollback(brain_home, "ghost", "t1", "why")
    immune.ingest_metric(brain_home, "tests_failed", 1.0, "r")
    result = immune.rollback(brain_home, "policy-one", "other-trigger", "why")
    assert result == {"rolled_back": False, "reason": "wrong_trigger"}
    with pytest.raises(BrainError, match="reason"):
        immune.rollback(brain_home, "policy-one", "t1", "  ")


# ---------------------------------------------------------------------------
# Hypothesis: check_triggers vs brute-force reference
# ---------------------------------------------------------------------------


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(("tests_failed", "f1_delta")),
            st.floats(allow_nan=False, allow_infinity=False, min_value=-3, max_value=5),
        ),
        min_size=0,
        max_size=12,
    ),
)
def test_check_triggers_matches_reference(brain_home, samples):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    immune.register_trigger(
        home, "t1", {"metric": "tests_failed", "operator": ">", "value": 0.5, "window": 3}
    )
    immune.register_trigger(
        home, "t2", {"metric": "f1_delta", "operator": "<=", "value": -0.1, "window": 2}
    )
    for index, (metric, value) in enumerate(samples):
        immune.ingest_metric(home, metric, value, f"run-{index}")

    def reference(metric, operator, value, window):
        windowed = [v for m, v in samples if m == metric][-window:]
        if not windowed:
            return False
        latest = windowed[-1]
        return {
            "<": latest < value,
            "<=": latest <= value,
            ">": latest > value,
            ">=": latest >= value,
            "==": latest == value,
            "!=": latest != value,
        }[operator]

    results = {r["trigger_id"]: r for r in immune.check_triggers(home)}
    assert results["t1"]["matched"] == reference("tests_failed", ">", 0.5, 3)
    assert results["t2"]["matched"] == reference("f1_delta", "<=", -0.1, 2)
    assert immune.check_triggers(home) == immune.check_triggers(home)


# ---------------------------------------------------------------------------
# SEC-05: arbitrary immune rollback filesystem target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../outside",
        "..\\outside",
        "/etc/passwd",
        "C:\\windows\\system32\\config",
        "\\server\\share\\x",
        "a:b",
        ".",
        "..",
        "",
    ],
)
def test_register_policy_rejects_hostile_targets(brain_home, bad):
    """SEC-T048/T049: rollback targets must be Brain-managed, not arbitrary."""
    with pytest.raises(BrainError, match="rollback_target"):
        immune.register_policy(
            brain_home,
            "policy-safe",
            {"rollback_trigger": "t", "rollback_target": bad, "backup_of": "a" * 64},
        )


def test_register_policy_rejects_absolute_target_outside_home(brain_home):
    outside = brain_home.parent / "not-a-brain-file.toml"
    outside.write_text("x", encoding="utf-8")
    try:
        with pytest.raises(BrainError, match="outside"):
            immune.register_policy(
                brain_home,
                "policy-outside",
                {
                    "rollback_trigger": "t",
                    "rollback_target": str(outside),
                    "backup_of": "a" * 64,
                },
            )
    finally:
        outside.unlink()


def test_policy_target_stored_relative_and_revalidated(brain_home):
    """The stored target is home-relative; rollback re-proves containment."""
    target = _policy_file(brain_home, "policy-rel", "good state")
    immune.register_policy(
        brain_home,
        "policy-rel",
        {
            "rollback_trigger": "t1",
            "rollback_target": str(target),
            "backup_of": _sha256_text("good state"),
        },
    )
    record = immune._read_json(brain_home / "immune" / "policies" / "policy-rel.json")
    stored = record["guard"]["rollback_target"]
    assert "\\" not in stored  # stored as posix relative
    assert not Path(stored).is_absolute()
    assert (brain_home / stored).resolve() == target.resolve()


def _register_trigger_t1(home):
    immune.register_trigger(
        home, "t1", {"metric": "tests_failed", "operator": ">", "value": 0, "window": 3}
    )


def test_rollback_refuses_tampered_absolute_target(brain_home):
    """A policy file edited to an absolute external target fails closed."""
    target = _policy_file(brain_home, "policy-tamper", "bad state")
    _register_trigger_t1(brain_home)
    immune.register_policy(
        brain_home,
        "policy-tamper",
        {
            "rollback_trigger": "t1",
            "rollback_target": str(target),
            "backup_of": _sha256_text("good state"),
        },
    )
    immune.ingest_metric(brain_home, "tests_failed", 3.0, "run-3")
    # Tamper: rewrite the stored target to an absolute path outside the home.
    policy_path = brain_home / "immune" / "policies" / "policy-tamper.json"
    data = immune._read_json(policy_path)
    outside = brain_home.parent / "external-target.toml"
    outside.write_text("external", encoding="utf-8")
    try:
        data["guard"]["rollback_target"] = str(outside)
        import json as _json

        policy_path.write_text(_json.dumps(data), encoding="utf-8")
        with pytest.raises(BrainError, match="Unsafe rollback target"):
            immune.rollback(brain_home, "policy-tamper", "t1", "regressed")
        assert outside.exists()  # never moved
        assert target.exists()  # policy file untouched
    finally:
        outside.unlink()


def test_rollback_target_symlink_escape_rejected(brain_home):
    """SEC-T050: a target that is a symlink to outside is refused."""
    target = _policy_file(brain_home, "policy-sym", "bad state")
    _register_trigger_t1(brain_home)
    immune.register_policy(
        brain_home,
        "policy-sym",
        {
            "rollback_trigger": "t1",
            "rollback_target": str(target),
            "backup_of": _sha256_text("good state"),
        },
    )
    immune.ingest_metric(brain_home, "tests_failed", 3.0, "run-3")
    outside = brain_home.parent / "symlink-victim.toml"
    outside.write_text("victim", encoding="utf-8")
    import os as _os

    target.unlink()
    try:
        _os.symlink(outside, target)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")
    try:
        with pytest.raises(BrainError, match="Unsafe rollback target"):
            immune.rollback(brain_home, "policy-sym", "t1", "regressed")
        assert outside.read_text(encoding="utf-8") == "victim"
    finally:
        outside.unlink()


def test_rollback_stays_in_authorized_domain(brain_home):
    """SEC-T051: a successful rollback moves the target into immune/rollbacks/."""
    target = _setup(brain_home, target_content="bad state now")
    immune.ingest_metric(brain_home, "tests_failed", 3.0, "run-3")
    result = immune.rollback(brain_home, "policy-one", "t1", "tests regressed")
    assert result["rolled_back"] is True
    backup = Path(result["backup"])
    assert backup.parent == brain_home / "immune" / "rollbacks"
    assert not target.exists()
