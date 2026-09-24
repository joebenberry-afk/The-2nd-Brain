"""Tests for ACT-R base-level activation and need probability (T5.1)."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from second_brain import autoinject, contracts, db, reconsolidation, semantic


def test_activation_ignores_retrieval_only_events(brain_home) -> None:
    """record_retrieval does not increase B or storage_strength, while
    record_activation(..., kind='used') does."""
    mid = semantic.add_memory(brain_home, "Retrieval vs Activation", "Content test")
    semantic.curate(brain_home, mid, status="current")

    conn = db.connect(db.db_path(brain_home))
    try:
        row = dict(conn.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,)).fetchone())
    finally:
        conn.close()

    assert row["storage_strength"] == 1.0
    assert row["retrieval_strength"] == 1.0

    b_initial = reconsolidation.compute_base_level_activation(brain_home, mid)
    assert b_initial == -10.0

    # Recording retrievals must NOT increment storage_strength or B
    for _ in range(3):
        reconsolidation.record_retrieval(brain_home, mid)

    conn = db.connect(db.db_path(brain_home))
    try:
        row = dict(conn.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,)).fetchone())
    finally:
        conn.close()

    assert row["retrieval_count"] == 3
    assert row["storage_strength"] == 1.0
    b_after_retrievals = reconsolidation.compute_base_level_activation(brain_home, mid)
    assert b_after_retrievals == -10.0

    # Now record activation with kind='used'
    aid = reconsolidation.record_activation(brain_home, mid, "correct", kind="used")
    assert aid >= 1

    conn = db.connect(db.db_path(brain_home))
    try:
        row = dict(conn.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,)).fetchone())
    finally:
        conn.close()

    assert pytest.approx(row["storage_strength"], 0.001) == 1.1
    b_active = reconsolidation.compute_base_level_activation(brain_home, mid)
    assert b_active > 0.0
    assert b_active > b_initial

    # Second activation increases storage_strength further
    reconsolidation.record_activation(brain_home, mid, "correct", kind="used")
    conn = db.connect(db.db_path(brain_home))
    try:
        row = dict(conn.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,)).fetchone())
    finally:
        conn.close()
    assert pytest.approx(row["storage_strength"], 0.001) == 1.2


def test_recent_used_memory_outranks_old(brain_home) -> None:
    """A recently used memory gets higher B and outranks an older memory with
    identical text and baseline relevance."""
    m_old = semantic.add_memory(
        brain_home,
        "Database timeout connection setting",
        "Set database connection timeout to 30s",
        grade="TESTED",
    )
    m_new = semantic.add_memory(
        brain_home,
        "Database timeout connection config",
        "Set database connection timeout to 30s",
        grade="TESTED",
    )
    semantic.curate(brain_home, m_old, status="current")
    semantic.curate(brain_home, m_new, status="current")

    conn = db.connect(db.db_path(brain_home))
    try:
        old_time = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
        new_time = (datetime.now(UTC) - timedelta(hours=0.1)).isoformat()
        conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (m_old, "s_old", "correct", old_time, "used"),
        )
        conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (m_new, "s_new", "correct", new_time, "used"),
        )
        conn.commit()
    finally:
        conn.close()

    b_old = reconsolidation.compute_base_level_activation(brain_home, m_old)
    b_new = reconsolidation.compute_base_level_activation(brain_home, m_new)
    assert b_new > b_old

    p_old = reconsolidation.compute_p_need(brain_home, m_old)
    p_new = reconsolidation.compute_p_need(brain_home, m_new)
    assert p_new > p_old

    results = semantic.search_memories(brain_home, "Database timeout connection")
    ids = [r["memory_id"] for r in results]
    assert m_new in ids
    assert m_old in ids
    assert ids.index(m_new) < ids.index(m_old)


def test_low_need_high_cost_item_ranked_not_vetoed(brain_home) -> None:
    """Need-cost ROI ranks the budget stage; it never vetoes a deliverable item.

    S2 residual R01-R03: a never-activated memory floors P_need at 0.5, and a long
    body makes it expensive in target-token units, so the old
    ``p_need * value < token_cost_ratio`` veto dropped the *only* relevant
    candidate and answered CONTEXT_PRESSURE instead of the memory. The same
    factors still order the budget stage, but a candidate that fits the packet is
    delivered (see also test_budget_hard_cap_never_exceeded).
    """
    mid = semantic.add_memory(
        brain_home,
        "Expensive deployment runbook",
        "step procedure verification " * 15,
        grade="OBSERVED",
        project_id="proj-a",
    )
    semantic.curate(brain_home, mid, status="current")

    # Record ancient activation (500 hours ago) so B is low and P_need is near zero
    conn = db.connect(db.db_path(brain_home))
    try:
        ancient_time = (datetime.now(UTC) - timedelta(hours=500)).isoformat()
        conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (mid, "s_ancient", "correct", ancient_time, "used"),
        )
        conn.commit()
    finally:
        conn.close()

    p_need = reconsolidation.compute_p_need(brain_home, mid)
    assert p_need < 0.1

    config = autoinject.AutoInjectConfig(target_tokens=400, hard_cap_tokens=1000)
    intent = autoinject.RetrievalIntent(
        task_text="Expensive deployment runbook",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="s_test",
    )

    decision = autoinject.prepare_injection(brain_home, intent, config=config)
    assert decision.decision is contracts.InjectionDecision.INJECT
    assert decision.selected_ids == [mid]
    assert decision.packet_token_size is not None
    assert decision.packet_token_size <= config.hard_cap_tokens


def test_boundary_and_overflow(brain_home) -> None:
    """Boundary conditions: no events -> -10, t_j=0 clamp, sigmoid overflow protection."""
    b_none = reconsolidation.compute_base_level_activation(brain_home, "mem-nonexistent")
    assert b_none == -10.0

    p_none = reconsolidation.compute_p_need(brain_home, "mem-nonexistent")
    assert 0.0 < p_none < 0.001

    mid = semantic.add_memory(brain_home, "Instant test", "body")
    reconsolidation.record_activation(brain_home, mid, "correct", kind="used")

    # t_j=0 or negative event age (clock drift) is clamped to 0.001 without error
    past_ts = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    b_drift = reconsolidation.compute_base_level_activation(brain_home, mid, now=past_ts)
    assert isinstance(b_drift, float)
    assert not math.isnan(b_drift)
    assert not math.isinf(b_drift)

    # Sigmoid extreme positive bound [-40, 40]
    p_high = reconsolidation.compute_p_need(brain_home, mid, tau=-1000.0, s=1.0)
    assert 0.9999 < p_high <= 1.0

    # Sigmoid extreme negative bound
    p_low = reconsolidation.compute_p_need(brain_home, mid, tau=1000.0, s=1.0)
    assert 0.0 <= p_low < 0.0001

    # Zero scale s defaults to 1.0 safely
    p_zero_s = reconsolidation.compute_p_need(brain_home, mid, s=0.0)
    assert 0.0 <= p_zero_s <= 1.0


def test_decay_pass_actr_heat_transitions(brain_home) -> None:
    """decay_pass updates heat according to ACT-R base activation thresholds:
    HOT when B > 0, WARM when -3 < B <= 0, COLD when B <= -3."""
    m_hot = semantic.add_memory(brain_home, "Hot Rule", "body", grade="TESTED")
    m_warm = semantic.add_memory(brain_home, "Warm Rule", "body", grade="TESTED")
    m_cold = semantic.add_memory(brain_home, "Cold Rule", "body", grade="TESTED")
    for m in (m_hot, m_warm, m_cold):
        semantic.curate(brain_home, m, status="current")

    reconsolidation.apply_heat(brain_home, m_hot, "HOT")
    reconsolidation.apply_heat(brain_home, m_warm, "HOT")
    reconsolidation.apply_heat(brain_home, m_cold, "HOT")

    conn = db.connect(db.db_path(brain_home))
    try:
        # m_hot: 0.1 hours ago -> B > 0
        t_hot = (datetime.now(UTC) - timedelta(hours=0.1)).isoformat()
        conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (m_hot, "s", "correct", t_hot, "used"),
        )
        # m_warm: 5 hours ago -> B ~ ln(5**-0.5) ~ -0.80 -> between -3 and 0
        t_warm = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (m_warm, "s", "correct", t_warm, "used"),
        )
        # m_cold: 300 hours ago -> B ~ ln(300**-0.5) ~ -2.85 ... 1000 hours -> -3.45 -> B <= -3
        t_cold = (datetime.now(UTC) - timedelta(hours=1000)).isoformat()
        conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (m_cold, "s", "correct", t_cold, "used"),
        )
        conn.commit()
    finally:
        conn.close()

    assert reconsolidation.compute_base_level_activation(brain_home, m_hot) > 0
    b_warm = reconsolidation.compute_base_level_activation(brain_home, m_warm)
    assert -3 < b_warm <= 0
    assert reconsolidation.compute_base_level_activation(brain_home, m_cold) <= -3

    changes = reconsolidation.decay_pass(brain_home, dry_run=False)
    change_map = {c["memory_id"]: c["heat_after"] for c in changes}
    assert m_hot not in change_map  # HOT stays HOT
    assert change_map[m_warm] == "WARM"
    assert change_map[m_cold] == "COLD"
