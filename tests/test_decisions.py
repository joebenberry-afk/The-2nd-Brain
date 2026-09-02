"""Focused tests for deterministic policy decisions and outcomes."""

import hashlib

import pytest

from second_brain import contracts, db, decisions
from second_brain.errors import BrainError


def test_record_and_outcome_roundtrip(brain_home):
    inputs = {"query": "remember this", "limit": 3}
    chosen = {"memory_id": "m-1"}
    alternatives = [{"memory_id": "m-1"}, {"memory_id": "m-2"}]

    decision_id = decisions.record(
        brain_home,
        kind="retrieval",
        session_id="session-1",
        task_id="task-1",
        chosen=chosen,
        alternatives=alternatives,
        propensity=0.75,
        randomized=False,
        policy_version="v2",
        stage="SHADOW",
        inputs=inputs,
    )

    expected_id = hashlib.sha256(
        (contracts.canonical_json(inputs) + "session-1" + "retrieval").encode("utf-8")
    ).hexdigest()[:24]
    assert decision_id == expected_id

    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["chosen_json"] == contracts.canonical_json(chosen)
    assert row["alternatives_json"] == contracts.canonical_json(alternatives)
    assert row["inputs_hash"] == contracts.stable_content_hash(inputs)
    assert row["outcome_json"] is None
    assert row["reward"] is None

    decisions.set_outcome(brain_home, decision_id, {"success": True, "latency_ms": 12}, 0.9)
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute("SELECT outcome_json, reward FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
    finally:
        conn.close()
    assert row["outcome_json"] == contracts.canonical_json({"success": True, "latency_ms": 12})
    assert row["reward"] == pytest.approx(0.9)


def test_randomize_propensities_sum_to_one():
    policy_choice = "policy"
    alternatives = ["policy", "alternative-a", "alternative-b"]
    epsilon = 0.2
    expected = {
        "policy": 1 - epsilon + epsilon / len(alternatives),
        "alternative-a": epsilon / len(alternatives),
        "alternative-b": epsilon / len(alternatives),
    }
    assert sum(expected.values()) == pytest.approx(1.0)

    for seed in range(32):
        choice, propensity, randomized = decisions.randomize(
            policy_choice, alternatives, epsilon, seed
        )
        assert propensity == pytest.approx(expected[choice])
        assert isinstance(randomized, bool)

    assert decisions.randomize(policy_choice, alternatives, 0.0, 1) == (
        policy_choice,
        1.0,
        False,
    )


def test_migration_is_idempotent_and_non_destructive(brain_home):
    dbfile = db.db_path(brain_home)
    conn = db.connect(dbfile)
    try:
        conn.execute("CREATE TABLE preserved_decision_data (value TEXT NOT NULL)")
        conn.execute("INSERT INTO preserved_decision_data VALUES ('keep')")
        conn.commit()
    finally:
        conn.close()

    assert db.migrate(dbfile) == []
    conn = db.connect(dbfile, readonly=True)
    try:
        assert conn.execute("SELECT value FROM preserved_decision_data").fetchone()[0] == "keep"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'decisions'").fetchone()
    finally:
        conn.close()
