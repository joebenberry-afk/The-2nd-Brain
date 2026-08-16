"""Tests for cross-model memory (Phase 20)."""

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import crossmodel, db
from second_brain.errors import BrainError

SKILL = "scout"


def _fresh_home(brain_home):
    return brain_home / uuid.uuid4().hex


def _record(home, model, task, success, noise=0, f1=0.5, skill=SKILL):
    crossmodel.record_model(home, model)
    return crossmodel.record_skill_outcome(home, model, skill, task, success, noise=noise, f1=f1)


def _tables(home):
    conn = db.connect(db.db_path(home))
    try:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_0006_on_fresh_brain(brain_home):
    assert {"model_profiles", "model_skill_outcomes"} <= _tables(brain_home)
    assert db.pending_migrations(db.db_path(brain_home)) == []


def test_migration_0006_on_v5_brain(brain_home):
    dbfile = db.db_path(brain_home)
    conn = db.connect(dbfile)
    try:
        conn.execute("DROP TABLE IF EXISTS model_skill_outcomes")
        conn.execute("DROP TABLE IF EXISTS model_profiles")
        conn.execute("DROP TABLE IF EXISTS memory_fts")
        conn.execute("DROP TABLE IF EXISTS memory_index")
        conn.execute("DELETE FROM schema_version WHERE version >= 6")
        conn.commit()
    finally:
        conn.close()
    assert db.pending_migrations(dbfile) == [6, 7, 8, 9]
    profile = crossmodel.record_model(brain_home, "flash", family="deepseek")
    assert profile["model_id"] == "flash"
    assert db.pending_migrations(dbfile) == []
    assert {"model_profiles", "model_skill_outcomes"} <= _tables(brain_home)


# ---------------------------------------------------------------------------
# record / report
# ---------------------------------------------------------------------------


def test_record_model_upsert_preserves_first_seen(brain_home):
    first = crossmodel.record_model(brain_home, "flash", family="deepseek", capabilities="fast")
    second = crossmodel.record_model(
        brain_home, "flash", family="deepseek-v2", capabilities="faster"
    )
    assert first["first_seen_at"] == second["first_seen_at"]
    assert second["family"] == "deepseek-v2"
    assert second["capabilities"] == "faster"


def test_record_outcome_requires_profile(brain_home):
    with pytest.raises(BrainError, match="Unknown model profile"):
        crossmodel.record_skill_outcome(brain_home, "ghost", SKILL, "task", True)
    crossmodel.record_model(brain_home, "m1")
    with pytest.raises(BrainError, match="success"):
        crossmodel.record_skill_outcome(brain_home, "m1", SKILL, "t", "yes")  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="noise"):
        crossmodel.record_skill_outcome(brain_home, "m1", SKILL, "t", True, noise=-1)
    with pytest.raises(BrainError, match="f1"):
        crossmodel.record_skill_outcome(brain_home, "m1", SKILL, "t", True, f1=1.5)


def test_task_hash_deterministic_and_prefixed(brain_home):
    assert crossmodel.task_hash("same task") == crossmodel.task_hash("same task")
    assert len(crossmodel.task_hash("same task")) == 16
    assert crossmodel.task_hash("different") != crossmodel.task_hash("same task")


def test_report_aggregation_and_filters(brain_home):
    _record(brain_home, "flash", "t1", True, noise=1, f1=0.8)
    _record(brain_home, "flash", "t2", False, noise=2, f1=0.4)
    _record(brain_home, "flash", "t3", True, noise=0, f1=1.0)
    _record(brain_home, "pro", "t1", True, noise=0, f1=0.9)
    report = crossmodel.model_skill_report(brain_home)
    by_model = {m["model_id"]: m for m in report["models"]}
    assert by_model["flash"] == {
        "model_id": "flash",
        "outcomes": 3,
        "successes": 2,
        "f1_mean": 0.7333,
        "noise_mean": 1.0,
    }
    assert by_model["pro"] == {
        "model_id": "pro",
        "outcomes": 1,
        "successes": 1,
        "f1_mean": 0.9,
        "noise_mean": 0.0,
    }
    only_flash = crossmodel.model_skill_report(brain_home, model_id="flash")
    assert [m["model_id"] for m in only_flash["models"]] == ["flash"]


# ---------------------------------------------------------------------------
# Transfer test
# ---------------------------------------------------------------------------


def test_transfer_verdicts(brain_home):
    # Same three tasks recorded for both models; b succeeds everywhere a does.
    for task in ("t1", "t2", "t3"):
        _record(brain_home, "flash", task, True)
        _record(brain_home, "pro", task, True)
    result = crossmodel.transfer_test(brain_home, SKILL, "flash", "pro")
    assert result["verdict"] == "transfers"
    assert result["overlap_count"] == 3
    assert all(t["success_a"] == 1 and t["success_b"] == 1 for t in result["tasks"])
    # b worse on a fresh overlapping task -> does_not_transfer.
    crossmodel.record_skill_outcome(brain_home, "flash", SKILL, "t6", True)
    crossmodel.record_skill_outcome(brain_home, "pro", SKILL, "t6", False)
    result = crossmodel.transfer_test(brain_home, SKILL, "flash", "pro")
    assert result["verdict"] == "does_not_transfer"
    # No overlap -> no_data.
    crossmodel.record_model(brain_home, "nova")
    crossmodel.record_skill_outcome(brain_home, "nova", SKILL, "t9", True)
    result = crossmodel.transfer_test(brain_home, SKILL, "flash", "nova")
    assert result["verdict"] == "no_data"
    assert result["overlap_count"] == 0


def test_transfer_rejects_zero_success_and_one_task_evidence(brain_home):
    _record(brain_home, "flash", "both-fail", False)
    _record(brain_home, "pro", "both-fail", False)
    assert crossmodel.transfer_test(brain_home, SKILL, "flash", "pro")["verdict"] == (
        "does_not_transfer"
    )

    _record(brain_home, "flash", "mixed", False)
    _record(brain_home, "pro", "mixed", True)
    result = crossmodel.transfer_test(brain_home, SKILL, "flash", "pro")
    assert result["verdict"] == "insufficient_evidence"
    assert result["strong_evidence"] is False

    for task in ("both-fail-2", "mixed-2"):
        _record(brain_home, "flash", task, False)
        _record(brain_home, "pro", task, True)
    result = crossmodel.transfer_test(brain_home, SKILL, "flash", "pro")
    assert result["verdict"] == "insufficient_evidence"


# ---------------------------------------------------------------------------
# Contamination guard
# ---------------------------------------------------------------------------


def test_contamination_guard_acceptance(brain_home):
    # Model a: 4/5 successes (rate 0.8). Model b: 0/5 failures (rate 0.0).
    for i in range(5):
        _record(brain_home, "good", f"task-{i}", i < 4)
        _record(brain_home, "bad", f"task-{i}", False)
    stats = crossmodel.global_policy_stats(brain_home, SKILL)
    assert stats["models_included"] == ["good"]
    assert stats["models_excluded"] == ["bad"]
    assert stats["successes"] == 4
    assert stats["outcomes"] == 5
    assert stats["success_rate"] == 0.8
    assert stats["global_scope_eligible"] is False
    assert stats["worst_model_success_rate"] == 0.0
    # The gate: stats over everything (with the failing model excluded by the
    # guard) equal stats over a world where the failing model never existed.
    home_a_only = _fresh_home(brain_home)
    for i in range(5):
        _record(home_a_only, "good", f"task-{i}", i < 4)
    alone = crossmodel.global_policy_stats(home_a_only, SKILL)
    # Model-specific failures did NOT contaminate policy: every aggregate
    # number is identical to a world where the failing model never existed.
    for key in ("models_included", "outcomes", "successes", "success_rate"):
        assert stats[key] == alone[key], key


def test_contamination_threshold_boundary(brain_home):
    _record(brain_home, "zero", "t1", False)
    # Default threshold excludes a 0-success model entirely.
    stats = crossmodel.global_policy_stats(brain_home, SKILL)
    assert stats["models_excluded"] == ["zero"]
    assert stats["outcomes"] == 0
    # Boundary: min_success_per_model=0.0 includes it (0.0 >= 0.0).
    stats = crossmodel.global_policy_stats(brain_home, SKILL, min_success_per_model=0.0)
    assert stats["models_included"] == ["zero"]
    assert stats["outcomes"] == 1
    assert stats["success_rate"] == 0.0


def test_global_stats_deterministic(brain_home):
    _record(brain_home, "good", "t1", True)
    _record(brain_home, "bad", "t1", False)
    assert crossmodel.global_policy_stats(brain_home, SKILL) == (
        crossmodel.global_policy_stats(brain_home, SKILL)
    )
    assert crossmodel.model_skill_report(brain_home) == crossmodel.model_skill_report(brain_home)
    assert crossmodel.transfer_test(brain_home, SKILL, "good", "bad") == (
        crossmodel.transfer_test(brain_home, SKILL, "good", "bad")
    )


# ---------------------------------------------------------------------------
# Hypothesis: report aggregation cross-check
# ---------------------------------------------------------------------------


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(("m1", "m2")), st.booleans(), st.integers(min_value=0, max_value=3)
        ),
        min_size=0,
        max_size=10,
    ),
)
def test_report_matches_brute_force(brain_home, outcomes):
    home = _fresh_home(brain_home)
    crossmodel.record_model(home, "m1")
    crossmodel.record_model(home, "m2")
    for index, (model, success, noise) in enumerate(outcomes):
        crossmodel.record_skill_outcome(
            home, model, SKILL, f"t{index}-{model}-{success}", success, noise=noise, f1=0.5
        )
    report = crossmodel.model_skill_report(home)
    by_model = {entry["model_id"]: entry for entry in report["models"]}
    expected: dict[str, dict] = {}
    for model, success, noise in outcomes:
        entry = expected.setdefault(model, {"outcomes": 0, "successes": 0, "f1": 0.0, "noise": 0})
        entry["outcomes"] += 1
        entry["successes"] += 1 if success else 0
        entry["f1"] += 0.5
        entry["noise"] += noise
    for model, data in expected.items():
        entry = by_model[model]
        assert entry["outcomes"] == data["outcomes"]
        assert entry["successes"] == data["successes"]
        assert entry["f1_mean"] == round(data["f1"] / data["outcomes"], 4)
        assert entry["noise_mean"] == round(data["noise"] / data["outcomes"], 4)
