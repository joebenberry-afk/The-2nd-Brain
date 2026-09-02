"""Focused tests for deterministic policy decisions and outcomes."""

from collections import Counter
import hashlib

import pytest

from second_brain import contracts, db, decisions
from second_brain.errors import BrainError


def _record_kwargs():
    return {
        "kind": "retrieval",
        "session_id": "session-1",
        "task_id": "task-1",
        "chosen": {"memory_id": "m-1"},
        "alternatives": [{"memory_id": "m-1"}, {"memory_id": "m-2"}],
        "propensity": 0.75,
        "randomized": False,
        "policy_version": "v2",
        "stage": "SHADOW",
        "inputs": {"query": "remember this", "limit": 3},
    }


def test_record_and_outcome_roundtrip(brain_home):
    values = _record_kwargs()
    decision_id = decisions.record(brain_home, **values)

    expected_id = hashlib.sha256(
        (contracts.canonical_json(values["inputs"]) + "session-1" + "retrieval").encode("utf-8")
    ).hexdigest()[:24]
    assert decision_id == expected_id

    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["chosen_json"] == contracts.canonical_json(values["chosen"])
    assert row["alternatives_json"] == contracts.canonical_json(values["alternatives"])
    assert row["inputs_hash"] == contracts.stable_content_hash(values["inputs"])
    assert row["outcome_json"] is None
    assert row["reward"] is None

    decisions.set_outcome(brain_home, decision_id, {"success": True, "latency_ms": 12}, -0.5)
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute("SELECT outcome_json, reward FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
    finally:
        conn.close()
    assert row["outcome_json"] == contracts.canonical_json({"success": True, "latency_ms": 12})
    assert row["reward"] == pytest.approx(-0.5)


def test_randomize_propensities_sum_to_one_and_matches_observations():
    epsilon = 0.2
    alternatives = ["policy", "alternative-a", "alternative-b"]
    expected = {
        "policy": 1 - epsilon + epsilon / len(alternatives),
        "alternative-a": epsilon / len(alternatives),
        "alternative-b": epsilon / len(alternatives),
    }
    assert sum(expected.values()) == pytest.approx(1.0)
    counts = Counter()
    for seed in range(10_000):
        choice, propensity, randomized = decisions.randomize("policy", alternatives, epsilon, seed)
        counts[choice] += 1
        assert propensity == pytest.approx(expected[choice])
        assert isinstance(randomized, bool)
    for choice, probability in expected.items():
        assert counts[choice] / 10_000 == pytest.approx(probability, abs=0.02)

    outside = ["alternative-a", "alternative-b"]
    outside_expected = {choice: epsilon / len(outside) for choice in outside}
    outside_expected["policy"] = 1 - epsilon
    outside_counts = Counter(
        decisions.randomize("policy", outside, epsilon, seed)[0] for seed in range(10_000)
    )
    assert sum(outside_expected.values()) == pytest.approx(1.0)
    for choice, probability in outside_expected.items():
        assert outside_counts[choice] / 10_000 == pytest.approx(probability, abs=0.02)

    assert decisions.randomize("policy", alternatives, 0.0, 1) == ("policy", 1.0, False)
    assert decisions.randomize("policy", alternatives, 0.2, 7) == decisions.randomize(
        "policy", alternatives, 0.2, 7
    )


def test_randomize_rejects_duplicate_alternatives():
    with pytest.raises(BrainError, match="duplicate"):
        decisions.randomize("policy", ["a", "a"], 0.2, 1)


def test_record_rejects_invalid_identity_and_kind(brain_home):
    for field, value in (("kind", ""), ("policy_version", ""), ("session_id", None), ("session_id", "")):
        values = _record_kwargs()
        values[field] = value
        with pytest.raises(BrainError):
            decisions.record(brain_home, **values)
    values = _record_kwargs()
    values["kind"] = "unknown"
    with pytest.raises(BrainError, match="kind"):
        decisions.record(brain_home, **values)


def test_record_rejects_content_like_or_oversized_metadata(brain_home):
    values = _record_kwargs()
    values["chosen"] = {"content": "secret prompt"}
    with pytest.raises(BrainError, match="content"):
        decisions.record(brain_home, **values)
    values = _record_kwargs()
    values["chosen"] = {"memory_id": "x" * (decisions.MAX_METADATA_TEXT_CHARS + 1)}
    with pytest.raises(BrainError, match="bound"):
        decisions.record(brain_home, **values)
    values = _record_kwargs()
    values["chosen"] = {"memory_id": "m-1", "score": 0.9}
    decision_id = decisions.record(brain_home, **values)
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        assert conn.execute("SELECT chosen_json FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()[0] == contracts.canonical_json(values["chosen"])
    finally:
        conn.close()


def test_fresh_migration_is_idempotent_and_preserves_decision(tmp_path):
    home = tmp_path / "fresh-brain"
    dbfile = db.db_path(home)
    assert db.migrate(dbfile) == list(range(1, 12))
    decision_id = decisions.record(home, **_record_kwargs())
    conn = db.connect(dbfile, readonly=True)
    try:
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(decisions)")}
        assert {"idx_decisions_kind_created", "idx_decisions_session"} <= indexes
    finally:
        conn.close()
    assert db.migrate(dbfile) == []
    conn = db.connect(dbfile, readonly=True)
    try:
        row = conn.execute("SELECT decision_id FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
    finally:
        conn.close()
    assert row["decision_id"] == decision_id
