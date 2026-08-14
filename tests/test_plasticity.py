"""Tests for the plasticity shadow-learning layer (Phase 13)."""

import json
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import db, plasticity
from second_brain.errors import BrainError


def _fresh_home(brain_home):
    return brain_home / uuid.uuid4().hex


def _rows(home, table):
    conn = db.connect(db.db_path(home))
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).fetchone()
        if exists is None:
            return []  # utility-only replays never create the tables
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Prediction error math
# ---------------------------------------------------------------------------


def test_prediction_error_math(brain_home):
    hit = plasticity.record_prediction(brain_home, "s1", "query", "localize", "localize", "repo")
    miss = plasticity.record_prediction(brain_home, "s1", "query", "localize", "search", "repo")
    rows = {r["prediction_id"]: r for r in _rows(brain_home, "predictions")}
    assert rows[hit]["prediction_error"] == 0
    assert rows[miss]["prediction_error"] == 1
    assert rows[hit]["kind"] == "repo"
    assert rows[hit]["state"] == "query"
    assert rows[hit]["expected_next_state"] == "localize"


def test_prediction_validation(brain_home):
    with pytest.raises(BrainError, match="state"):
        plasticity.record_prediction(brain_home, "s1", "  ", "b", "b", "k")
    with pytest.raises(BrainError, match="kind"):
        plasticity.record_prediction(brain_home, "s1", "a", "b", "b", "")


# ---------------------------------------------------------------------------
# Outcome vector
# ---------------------------------------------------------------------------


def test_outcome_partial_vector_ok(brain_home):
    oid = plasticity.record_outcome(
        brain_home, "s1", {"verified_success": True, "tool_calls": 12}, task_id="t1"
    )
    rows = _rows(brain_home, "outcomes")
    assert rows[0]["outcome_id"] == oid
    vector = json.loads(rows[0]["vector_json"])
    assert vector == {"verified_success": True, "tool_calls": 12}
    assert rows[0]["task_id"] == "t1"


def test_outcome_unknown_key_rejected(brain_home):
    with pytest.raises(BrainError, match="Unknown outcome vector field"):
        plasticity.record_outcome(brain_home, "s1", {"verified_success": True, "magic": 1})
    with pytest.raises(BrainError, match="vector"):
        plasticity.record_outcome(brain_home, "s1", "not-a-dict")  # type: ignore[arg-type]


def test_outcome_vector_fields_constant():
    assert set(plasticity.OUTCOME_VECTOR_FIELDS) == {
        "verified_success",
        "first_pass_success",
        "intent_alignment",
        "regression",
        "user_correction",
        "revert",
        "token_cost",
        "latency",
        "tool_calls",
        "context_peak",
        "code_complexity",
        "dependency_delta",
        "environment_damage",
    }


# ---------------------------------------------------------------------------
# Prediction errors / credit
# ---------------------------------------------------------------------------


def test_prediction_error_record(brain_home):
    pid = plasticity.record_prediction(brain_home, "s1", "a", "b", "c", "k")
    eid = plasticity.record_prediction_error(
        brain_home, pid, "confident-wrong", salience=0.9, detail="was sure, failed"
    )
    rows = _rows(brain_home, "prediction_errors")
    assert rows[0]["error_id"] == eid
    assert rows[0]["prediction_id"] == pid
    assert rows[0]["salience"] == 0.9
    with pytest.raises(BrainError, match="Unknown prediction id"):
        plasticity.record_prediction_error(brain_home, 99999, "k")
    with pytest.raises(BrainError, match="salience"):
        plasticity.record_prediction_error(brain_home, pid, "k", salience="high")  # type: ignore[arg-type]


def test_credit_requires_explicit_level(brain_home):
    # No default exists: calling without credit_level is a TypeError.
    with pytest.raises(TypeError):
        plasticity.record_credit(brain_home, "s1", "skill-x", "skill")  # type: ignore[arg-type]
    cid = plasticity.record_credit(brain_home, "s1", "skill-x", "skill", "direct")
    rows = _rows(brain_home, "credit_events")
    assert rows[0]["credit_id"] == cid
    assert rows[0]["credit_level"] == "direct"
    with pytest.raises(BrainError, match="subject_kind"):
        plasticity.record_credit(brain_home, "s1", "x", "bogus-kind", "direct")
    with pytest.raises(BrainError, match="credit_level"):
        plasticity.record_credit(brain_home, "s1", "x", "skill", "automatic")


def test_hindsight_relabel(brain_home):
    mismatch = plasticity.hindsight_relabel(brain_home, "s1", "localization", "environment drift")
    assert mismatch["error"] == 1
    assert mismatch["prediction_error_id"] is not None
    rows = _rows(brain_home, "predictions")
    # Formula: expected=actual=actual_bottleneck, so the column is 0; the
    # mismatch is captured by the prediction_error ROW (plan §45 example).
    assert rows[0]["prediction_error"] == 0
    assert rows[0]["state"] == "localization"
    assert rows[0]["expected_next_state"] == "environment drift"
    assert rows[0]["kind"] == "bottleneck"
    errors = _rows(brain_home, "prediction_errors")
    assert errors[0]["kind"] == "bottleneck-mismatch"

    match = plasticity.hindsight_relabel(brain_home, "s1", "localization", "localization")
    assert match["error"] == 0
    assert match["prediction_error_id"] is None
    assert len(_rows(brain_home, "prediction_errors")) == 1  # no new error row


# ---------------------------------------------------------------------------
# Utility log
# ---------------------------------------------------------------------------


def test_utility_append_only(brain_home):
    first = plasticity.utility_update(brain_home, "skill-x", "skill", 0.5, "verified result")
    second = plasticity.utility_update(brain_home, "skill-x", "skill", -0.1, "misleading")
    log = plasticity.read_utility_log(brain_home)
    assert len(log) == 2
    assert log[0]["subject_id"] == "skill-x"
    assert log[0]["delta"] == 0.5
    assert log[1]["delta"] == -0.1
    assert log[0]["ts"] == first["ts"]
    assert log[1]["ts"] == second["ts"]
    # Append-only: the file has exactly two lines and the first line is intact.
    lines = (brain_home / "plasticity" / "utility.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == first


def test_utility_validation(brain_home):
    with pytest.raises(BrainError, match="delta"):
        plasticity.utility_update(brain_home, "x", "skill", "big", "e")  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="evidence"):
        plasticity.utility_update(brain_home, "x", "skill", 0.1, "  ")
    with pytest.raises(BrainError, match="subject_kind"):
        plasticity.utility_update(brain_home, "x", "nope", 0.1, "e")


def test_corrupt_utility_log_raises_on_read(brain_home):
    path = brain_home / "plasticity" / "utility.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ok": 1}\nnot json\n', encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        plasticity.read_utility_log(brain_home)
    assert str(path) in str(exc.value)
    assert ":2" in str(exc.value)


# ---------------------------------------------------------------------------
# Lazy migration
# ---------------------------------------------------------------------------


def test_lazy_migration_0004(brain_home):
    dbfile = db.db_path(brain_home)
    conn = db.connect(dbfile)
    try:
        for table in (
            "model_skill_outcomes",
            "model_profiles",
            "memory_activations",
            "memory_retrievals",
            "credit_events",
            "prediction_errors",
            "outcomes",
            "predictions",
            "memory_versions",
            "memory_sources",
            "memories",
            "episodes",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DELETE FROM schema_version WHERE version >= 2")
        conn.commit()
    finally:
        conn.close()
    assert db.pending_migrations(dbfile) == [2, 3, 4, 5, 6]
    pid = plasticity.record_prediction(brain_home, "s1", "a", "b", "b", "k")
    assert db.pending_migrations(dbfile) == []
    assert pid >= 1


# ---------------------------------------------------------------------------
# Replay determinism (acceptance)
# ---------------------------------------------------------------------------

_EVENTS = [
    {
        "op": "prediction",
        "session_id": "s1",
        "state": "query",
        "expected_next_state": "localize",
        "actual_next_state": "search",
        "kind": "repo",
    },
    {
        "op": "outcome",
        "session_id": "s1",
        "task_id": "t1",
        "vector": {"verified_success": True, "tool_calls": 9, "token_cost": 42000},
    },
    {
        "op": "prediction_error",
        "prediction_id": 1,
        "kind": "confident-wrong",
        "salience": 0.8,
        "detail": "expected localization, searched",
    },
    {
        "op": "credit",
        "session_id": "s1",
        "subject_id": "scout",
        "subject_kind": "scout",
        "credit_level": "contributory",
    },
    {
        "op": "hindsight",
        "session_id": "s1",
        "predicted_bottleneck": "localization",
        "actual_bottleneck": "environment drift",
    },
    {
        "op": "utility",
        "subject_id": "scout",
        "subject_kind": "scout",
        "delta": 0.25,
        "evidence": "scout localized in 3 tool calls",
    },
]


def _strip_ids_and_ts(rows, id_columns):
    out = []
    for row in rows:
        clean = {k: v for k, v in row.items() if k not in (*id_columns, "created_at")}
        out.append(clean)
    return out


def test_replay_determinism_two_fresh_brains(brain_home):
    home_a = _fresh_home(brain_home)
    home_b = _fresh_home(brain_home)
    result_a = plasticity.replay(home_a, _EVENTS)
    result_b = plasticity.replay(home_b, _EVENTS)
    # Id sequences are identical for two fresh brains (both start empty);
    # utility records differ only in their ts field.
    assert {k: v for k, v in result_a.items() if k != "utilities"} == {
        k: v for k, v in result_b.items() if k != "utilities"
    }
    assert [dict(r, ts=None) for r in result_a["utilities"]] == [
        dict(r, ts=None) for r in result_b["utilities"]
    ]
    for table, id_col in (
        ("predictions", "prediction_id"),
        ("outcomes", "outcome_id"),
        ("prediction_errors", "error_id"),
        ("credit_events", "credit_id"),
    ):
        rows_a = _strip_ids_and_ts(_rows(home_a, table), (id_col,))
        rows_b = _strip_ids_and_ts(_rows(home_b, table), (id_col,))
        assert rows_a == rows_b, table
    # Utility logs are byte-identical except the ts field.
    log_a = plasticity.read_utility_log(home_a)
    log_b = plasticity.read_utility_log(home_b)
    assert [dict(r, ts=None) for r in log_a] == [dict(r, ts=None) for r in log_b]
    assert len(log_a) == 1


def test_replay_unknown_op_raises(brain_home):
    with pytest.raises(BrainError, match="Unknown replay op"):
        plasticity.replay(brain_home, [{"op": "nope"}])


def test_replay_missing_args_raises(brain_home):
    with pytest.raises(BrainError):
        plasticity.replay(brain_home, [{"op": "prediction", "state": "x"}])
    with pytest.raises(BrainError, match="events"):
        plasticity.replay(brain_home, "not-a-list")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Hypothesis: random op sequences replay deterministically
# ---------------------------------------------------------------------------

_OP_STRATEGY = st.sampled_from(("prediction", "outcome", "credit", "hindsight", "utility"))


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(_OP_STRATEGY, min_size=1, max_size=15))
def test_random_replay_deterministic(brain_home, ops):
    home_a = _fresh_home(brain_home)
    home_b = _fresh_home(brain_home)
    events = []
    for index, op in enumerate(ops):
        if op == "prediction":
            events.append(
                {
                    "op": op,
                    "session_id": "s",
                    "state": f"s{index}",
                    "expected_next_state": f"e{index}",
                    "actual_next_state": f"a{index}",
                    "kind": "k",
                }
            )
        elif op == "outcome":
            events.append({"op": op, "session_id": "s", "vector": {"tool_calls": index}})
        elif op == "credit":
            events.append(
                {
                    "op": op,
                    "session_id": "s",
                    "subject_id": f"sub{index}",
                    "subject_kind": "tool",
                    "credit_level": "unknown",
                }
            )
        elif op == "hindsight":
            events.append(
                {
                    "op": op,
                    "session_id": "s",
                    "predicted_bottleneck": f"p{index}",
                    "actual_bottleneck": f"a{index}",
                }
            )
        else:
            events.append(
                {
                    "op": op,
                    "subject_id": f"sub{index}",
                    "subject_kind": "tool",
                    "delta": float(index % 3),
                    "evidence": f"e{index}",
                }
            )
    result_a = plasticity.replay(home_a, events)
    result_b = plasticity.replay(home_b, events)
    assert {k: v for k, v in result_a.items() if k != "utilities"} == {
        k: v for k, v in result_b.items() if k != "utilities"
    }
    assert [dict(r, ts=None) for r in result_a["utilities"]] == [
        dict(r, ts=None) for r in result_b["utilities"]
    ]
    for table, id_col in (
        ("predictions", "prediction_id"),
        ("outcomes", "outcome_id"),
        ("prediction_errors", "error_id"),
        ("credit_events", "credit_id"),
    ):
        assert _strip_ids_and_ts(_rows(home_a, table), (id_col,)) == _strip_ids_and_ts(
            _rows(home_b, table), (id_col,)
        )
    log_a = plasticity.read_utility_log(home_a)
    log_b = plasticity.read_utility_log(home_b)
    assert [dict(r, ts=None) for r in log_a] == [dict(r, ts=None) for r in log_b]
