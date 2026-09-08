"""Tests for reconsolidation / strategic forgetting (Phase 15)."""

import uuid
from datetime import datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import db, reconsolidation, semantic
from second_brain.errors import BrainError

NOW = "2026-08-14T12:00:00+00:00"


def _memory(home, title="restore hygiene rule", grade="TESTED", status="current"):
    mid = semantic.add_memory(home, title, f"body for {title}", grade=grade)
    if status != "candidate":
        semantic.curate(home, mid, status=status)
    return mid


def _row(home, mid):
    conn = db.connect(db.db_path(home))
    try:
        return dict(conn.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,)).fetchone())
    finally:
        conn.close()


def _set(home, mid, **fields):
    conn = db.connect(db.db_path(home))
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE memories SET {sets} WHERE memory_id = ?", (*fields.values(), mid))
        conn.commit()
    finally:
        conn.close()


def _days_ago(days):
    return (datetime.fromisoformat(NOW) - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Retrieval / activation bookkeeping
# ---------------------------------------------------------------------------


def test_record_retrieval_bumps_count(brain_home):
    mid = _memory(brain_home)
    rid1 = reconsolidation.record_retrieval(brain_home, mid, session_id="s1")
    rid2 = reconsolidation.record_retrieval(brain_home, mid, session_id="s1")
    row = _row(brain_home, mid)
    assert row["retrieval_count"] == 2
    assert row["last_retrieved_at"]
    conn = db.connect(db.db_path(brain_home))
    try:
        retrievals = conn.execute("SELECT * FROM memory_retrievals").fetchall()
    finally:
        conn.close()
    assert {r["retrieval_id"] for r in retrievals} == {rid1, rid2}
    with pytest.raises(BrainError, match="Unknown memory"):
        reconsolidation.record_retrieval(brain_home, "mem-000000000000")


def test_record_activation_outcomes(brain_home):
    mid = _memory(brain_home)
    reconsolidation.record_activation(brain_home, mid, "correct")
    reconsolidation.record_activation(brain_home, mid, "irrelevant")
    row = _row(brain_home, mid)
    assert row["successful_retrieval_count"] == 1
    assert row["contradiction_count"] == 0
    assert row["status"] == "current"  # untouched by correct/irrelevant

    reconsolidation.record_activation(brain_home, mid, "contradicted")
    row = _row(brain_home, mid)
    assert row["contradiction_count"] == 1
    assert row["heat"] == "COLD"
    assert row["status"] == "labile"  # reconsolidation event (plan §49)

    with pytest.raises(BrainError, match="outcome"):
        reconsolidation.record_activation(brain_home, mid, "bogus")


def test_feedback_idempotency_is_opt_in_and_atomic(brain_home):
    mid = _memory(brain_home)
    first = reconsolidation.record_retrieval(brain_home, mid, session_id="hook-s1", idempotent=True)
    second = reconsolidation.record_retrieval(
        brain_home, mid, session_id="hook-s1", idempotent=True
    )
    assert first == second
    assert _row(brain_home, mid)["retrieval_count"] == 1

    activation_first = reconsolidation.record_activation(
        brain_home, mid, "correct", session_id="hook-s1", idempotent=True
    )
    activation_second = reconsolidation.record_activation(
        brain_home, mid, "correct", session_id="hook-s1", idempotent=True
    )
    assert activation_first == activation_second
    assert _row(brain_home, mid)["successful_retrieval_count"] == 1


# ---------------------------------------------------------------------------
# apply_heat guardrails
# ---------------------------------------------------------------------------


def test_apply_heat_rules(brain_home):
    verified = _memory(brain_home, grade="VERIFIED", status="current")
    unverified = _memory(brain_home, title="scout promotion", grade="INFERRED", status="current")
    candidate = _memory(brain_home, title="draft idea", grade="VERIFIED", status="candidate")
    labile = _memory(brain_home, title="contested rule", grade="OBSERVED", status="current")
    semantic.curate(brain_home, labile, status="labile")

    assert reconsolidation.apply_heat(brain_home, verified, "HOT")["heat"] == "HOT"
    with pytest.raises(BrainError, match="HOT"):
        reconsolidation.apply_heat(brain_home, unverified, "HOT")
    with pytest.raises(BrainError, match="HOT"):
        reconsolidation.apply_heat(brain_home, candidate, "HOT")

    # ARCHIVED is refused for current memories, allowed otherwise.
    with pytest.raises(BrainError, match="ARCHIVED"):
        reconsolidation.apply_heat(brain_home, verified, "ARCHIVED")
    assert reconsolidation.apply_heat(brain_home, candidate, "ARCHIVED")["heat"] == "ARCHIVED"
    assert reconsolidation.apply_heat(brain_home, labile, "ARCHIVED")["heat"] == "ARCHIVED"

    assert reconsolidation.apply_heat(brain_home, verified, "WARM")["heat"] == "WARM"
    with pytest.raises(BrainError, match="heat"):
        reconsolidation.apply_heat(brain_home, verified, "BOILING")
    with pytest.raises(BrainError, match="Unknown memory"):
        reconsolidation.apply_heat(brain_home, "mem-000000000000", "COLD")


# ---------------------------------------------------------------------------
# decay_pass
# ---------------------------------------------------------------------------


def test_decay_hot_to_warm(brain_home):
    mid = _memory(brain_home)
    _set(brain_home, mid, heat="HOT", last_retrieved_at=_days_ago(10))
    changes = reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW)
    assert [c["memory_id"] for c in changes] == [mid]
    assert changes[0]["heat_before"] == "HOT"
    assert changes[0]["heat_after"] == "WARM"
    assert _row(brain_home, mid)["heat"] == "HOT"  # dry run wrote nothing
    # Fresh HOT memory does not decay.
    _set(brain_home, mid, heat="HOT", last_retrieved_at=_days_ago(1))
    assert reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW) == []


def test_decay_warm_to_cold(brain_home):
    mid = _memory(brain_home)
    _set(brain_home, mid, heat="WARM", retrieval_count=0, last_retrieved_at=_days_ago(40))
    changes = reconsolidation.decay_pass(brain_home, dry_run=False, now=NOW)
    assert changes[0]["heat_after"] == "COLD"
    assert _row(brain_home, mid)["heat"] == "COLD"
    # Retrieved memories never cold-decay.
    _set(brain_home, mid, heat="WARM", retrieval_count=1, last_retrieved_at=_days_ago(40))
    assert reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW) == []
    # Young WARM memory does not decay.
    _set(brain_home, mid, heat="WARM", retrieval_count=0, last_retrieved_at=_days_ago(1))
    assert reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW) == []


def test_decay_never_auto_archives(brain_home):
    mid = _memory(brain_home)
    _set(brain_home, mid, heat="COLD", last_retrieved_at=_days_ago(400))
    changes = reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW)
    assert changes == []  # COLD stays COLD; nothing is auto-ARCHIVED (plan §52)
    assert _row(brain_home, mid)["heat"] == "COLD"


def test_protected_never_decays(brain_home):
    verified = _memory(brain_home, grade="VERIFIED")
    constitution = _memory(brain_home, title="constitution change control", grade="TESTED")
    security = _memory(brain_home, title="security boundaries", grade="INFERRED")
    for mid in (verified, constitution, security):
        _set(brain_home, mid, heat="HOT", retrieval_count=0, last_retrieved_at=_days_ago(90))
    changes = reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW)
    assert changes == []
    # An unprotected memory in the same pass still decays.
    mid = _memory(brain_home, title="scout promotion criteria")
    _set(brain_home, mid, heat="HOT", last_retrieved_at=_days_ago(90))
    changes = reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW)
    assert [c["memory_id"] for c in changes] == [mid]


def test_decay_determinism(brain_home):
    _memory(brain_home)
    mid2 = _memory(brain_home, title="scout promotion criteria")
    _set(brain_home, mid2, heat="HOT", last_retrieved_at=_days_ago(20))
    assert reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW) == (
        reconsolidation.decay_pass(brain_home, dry_run=True, now=NOW)
    )


def test_history_still_recoverable(brain_home):
    mid = _memory(brain_home)
    path = brain_home / "memory" / "semantic" / f"{mid}.md"
    body_before = path.read_text(encoding="utf-8")
    reconsolidation.record_retrieval(brain_home, mid)
    reconsolidation.record_activation(brain_home, mid, "contradicted")
    reconsolidation.apply_heat(brain_home, mid, "COLD")
    reconsolidation.decay_pass(brain_home, dry_run=False, now=NOW)
    # Files and version history are never touched by heat/status changes.
    assert path.read_text(encoding="utf-8") == body_before
    conn = db.connect(db.db_path(brain_home))
    try:
        versions = conn.execute("SELECT COUNT(*) AS n FROM memory_versions").fetchone()["n"]
    finally:
        conn.close()
    assert versions == 0


# ---------------------------------------------------------------------------
# Lazy migration 0005
# ---------------------------------------------------------------------------


def test_lazy_migration_0005(brain_home):
    dbfile = db.db_path(brain_home)
    conn = db.connect(dbfile)
    try:
        conn.execute("DROP TABLE IF EXISTS model_skill_outcomes")
        conn.execute("DROP TABLE IF EXISTS model_profiles")
        conn.execute("DROP TABLE IF EXISTS memory_activations")
        conn.execute("DROP TABLE IF EXISTS memory_retrievals")
        conn.execute("DROP TABLE IF EXISTS memory_fts")
        conn.execute("DROP TABLE IF EXISTS memory_index")
        # Rebuild memories without the 0005 columns (v4 shape). memory_sources /
        # memory_versions stay (empty in this fresh brain) so FK drops are safe.
        conn.execute(
            "CREATE TABLE memories_v1 AS SELECT memory_id, title, scope, project_id, status, "
            "evidence_grade, current_version, created_at, updated_at, last_verified_at, "
            "strength, stability, summary, body_path FROM memories"
        )
        conn.execute("DROP TABLE memories")
        conn.execute("ALTER TABLE memories_v1 RENAME TO memories")
        conn.execute("DELETE FROM schema_version WHERE version >= 5")
        conn.commit()
    finally:
        conn.close()
    assert db.pending_migrations(dbfile) == [
        v for v in [int(p.name[:4]) for p in db.migration_files()] if v >= 5
    ]
    mid = semantic.add_memory(brain_home, "new memory", "body")
    assert db.pending_migrations(dbfile) == []
    assert _row(brain_home, mid)["heat"] == "WARM"
    rid = reconsolidation.record_retrieval(brain_home, mid)
    assert rid >= 1


# ---------------------------------------------------------------------------
# Hypothesis: counters stay consistent
# ---------------------------------------------------------------------------


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(
        st.sampled_from(("retrieve", "correct", "irrelevant", "contradict")),
        min_size=1,
        max_size=20,
    )
)
def test_random_sequences_consistent(brain_home, ops):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    mid = semantic.add_memory(home, "restore hygiene rule", "body")
    semantic.curate(home, mid, status="current")
    retrievals = 0
    activations = 0
    correct = 0
    contradicted = 0
    for op in ops:
        if op == "retrieve":
            reconsolidation.record_retrieval(home, mid)
            retrievals += 1
        elif activations < retrievals:  # one activation per retrieval
            outcome = "contradicted" if op == "contradict" else op
            reconsolidation.record_activation(home, mid, outcome)
            activations += 1
            if op == "correct":
                correct += 1
            elif op == "contradict":
                contradicted += 1
        row = _row(home, mid)
        assert row["retrieval_count"] == retrievals
        assert row["successful_retrieval_count"] == correct
        assert row["contradiction_count"] == contradicted
        assert row["heat"] in reconsolidation.HEAT_STATES
        # Invariants from the spec.
        assert row["successful_retrieval_count"] <= row["retrieval_count"]
        assert row["contradiction_count"] <= retrievals
