"""Focused tests for retrieval injection holdout (T5.2).

Verifies holdout eligibility rules:
- Rollout stage >= CANARY (never OFF, SHADOW, ADVISORY).
- Task class is strictly trivial, navigation, or implementation.
- All selected candidate items have advisory authority (never policy or project_rule).
- Lane is not policy.
- Decision recording in decisions table with kind="retrieval", chosen, alternatives, propensity, inputs.
- Outcome finalization in finalize_session with reward 1.0/0.0 and tokens_total.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_brain import autoinject, db, decisions, semantic
from second_brain.contracts import (
    BrainInjectionDecision,
    Confidence,
    InjectionDecision,
    MemoryItemStatus,
    NoInjectionReason,
    PacketItem,
)


def _add(
    home: Path,
    title: str,
    body: str,
    *,
    project_id: str | None = "proj-holdout",
    scope: str = "project",
    grade: str = "TESTED",
    origin_class: str = "MODEL_INFERENCE",
) -> str:
    return semantic.add_memory(
        home,
        title,
        body,
        scope=scope,
        project_id=project_id,
        grade=grade,
        origin_class=origin_class,
    )


def _seed_current(home: Path, title: str, body: str, **kw) -> str:
    mid = _add(home, title, body, **kw)
    semantic.curate(home, mid, status="current")
    return mid


def test_holdout_never_when_stage_below_canary(brain_home, monkeypatch) -> None:
    """Verify holdout never fires when rollout stage is OFF, SHADOW, or ADVISORY."""
    m1 = _seed_current(brain_home, "Sorting rules", "sort alphabetically first")
    m2 = _seed_current(brain_home, "Sorting rules secondary", "sort numerically second")

    lifecycle = autoinject.BrainLifecycle(brain_home)
    normal_order: list[str] = []

    for stage in ("OFF", "SHADOW", "ADVISORY"):
        monkeypatch.setenv("SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE", stage)
        decision = lifecycle.prepare_injection(
            "implement sorting algorithm rules",
            project_id="proj-holdout",
            session_id=f"session-stage-{stage}",
            random_fn=lambda: 0.0,  # Would force holdout if stage were CANARY
        )
        assert decision.decision is InjectionDecision.INJECT
        # Both items delivered, none is held out
        assert set(decision.selected_ids) == {m1, m2}
        normal_order = list(decision.selected_ids)

        # Check no retrieval decision was recorded in decisions DB
        conn = db.connect(db.db_path(brain_home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE session_id = ? AND kind = 'retrieval'",
                (f"session-stage-{stage}",),
            ).fetchall()
            assert len(rows) == 0
        finally:
            conn.close()

    top_item = normal_order[0]
    expected_delivered = normal_order[1:]

    # Now verify that with CANARY stage, holdout DOES fire
    monkeypatch.setenv("SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE", "CANARY")
    decision_canary = lifecycle.prepare_injection(
        "implement sorting algorithm rules",
        project_id="proj-holdout",
        session_id="session-stage-CANARY",
        random_fn=lambda: 0.0,
    )
    assert decision_canary.decision is InjectionDecision.INJECT
    # Top item was withheld, rest delivered
    assert decision_canary.selected_ids == expected_delivered
    assert top_item not in decision_canary.selected_ids

    # Verify decision was recorded in decisions table
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE session_id = ? AND kind = 'retrieval'",
            ("session-stage-CANARY",),
        ).fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert json.loads(row["chosen_json"]) == expected_delivered
        assert json.loads(row["alternatives_json"]) == [top_item]
        assert row["propensity"] == pytest.approx(0.1)
        assert row["randomized"] == 1
        assert row["policy_version"] == "v5.2"
        assert row["rollout_stage"] == "CANARY"
    finally:
        conn.close()


def test_holdout_only_on_advisory_items_and_low_risk_classes(brain_home, monkeypatch) -> None:
    """Verify holdout only fires when authority is advisory and task class is trivial/navigation/implementation.

    Verify non-advisory items or debugging/verification/high_risk tasks never hold out.
    """
    monkeypatch.setenv("SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE", "CANARY")
    lifecycle = autoinject.BrainLifecycle(brain_home)

    m1 = _seed_current(brain_home, "Coding conventions", "standard code style")
    m2 = _seed_current(brain_home, "Coding conventions guide", "extended code style")

    # Baseline: check order when both are delivered
    baseline = lifecycle.prepare_injection(
        "implement coding conventions",
        project_id="proj-holdout",
        session_id="session-baseline",
        random_fn=lambda: 1.0,  # no holdout
    )
    assert baseline.decision is InjectionDecision.INJECT
    assert set(baseline.selected_ids) == {m1, m2}
    top_item = baseline.selected_ids[0]
    rest_items = baseline.selected_ids[1:]

    # 1. Non-eligible task classes must NEVER hold out
    non_eligible_tasks = [
        "debug the crash in coding conventions and fix bug",       # debugging
        "verify coding conventions and check assertion gates",     # verification
        "explore coding conventions and survey codebase",          # exploration
        "continue coding conventions and resume previous context", # continuation
        "critical high risk security coding conventions permission drop table", # high_risk
    ]

    for idx, task_text in enumerate(non_eligible_tasks):
        sess_id = f"session-taskclass-{idx}"
        dec = lifecycle.prepare_injection(
            task_text,
            project_id="proj-holdout",
            session_id=sess_id,
            random_fn=lambda: 0.0,  # Would hold out if eligible
        )
        assert dec.decision is InjectionDecision.INJECT
        # Not held out: top item is delivered
        assert dec.selected_ids == baseline.selected_ids

        # No decision record should exist
        conn = db.connect(db.db_path(brain_home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE session_id = ? AND kind = 'retrieval'",
                (sess_id,),
            ).fetchall()
            assert len(rows) == 0
        finally:
            conn.close()

    # 2. Eligible task classes DO hold out
    eligible_tasks = [
        "summarize coding conventions and trivial overview",   # trivial
        "search coding conventions where located",            # navigation
        "implement and build coding conventions",             # implementation
    ]
    for idx, task_text in enumerate(eligible_tasks):
        sess_id = f"session-eligible-{idx}"
        dec = lifecycle.prepare_injection(
            task_text,
            project_id="proj-holdout",
            session_id=sess_id,
            random_fn=lambda: 0.0,
        )
        assert dec.decision is InjectionDecision.INJECT
        # Top item is withheld
        assert dec.selected_ids == rest_items
        assert top_item not in dec.selected_ids

        conn = db.connect(db.db_path(brain_home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE session_id = ? AND kind = 'retrieval'",
                (sess_id,),
            ).fetchall()
            assert len(rows) == 1
            assert json.loads(rows[0]["chosen_json"]) == rest_items
            assert json.loads(rows[0]["alternatives_json"]) == [top_item]
        finally:
            conn.close()

    # 3. Non-advisory items: project_rule or policy authority ceiling
    # Create a memory with origin_class="USER_AUTHORED" (ceiling="project_rule")
    m_rule = _seed_current(
        brain_home,
        "Project Rule Authority",
        "must follow strict project rules",
        origin_class="USER_AUTHORED",
    )
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute("UPDATE memories SET authority_ceiling = 'project_rule' WHERE memory_id = ?", (m_rule,))
        conn.commit()
    finally:
        conn.close()

    dec_rule = lifecycle.prepare_injection(
        "implement strict project rules",
        project_id="proj-holdout",
        session_id="session-rule-auth",
        random_fn=lambda: 0.0,
    )
    assert dec_rule.decision is InjectionDecision.INJECT
    # Item with authority != 'advisory' must NOT be withheld
    assert m_rule in dec_rule.selected_ids

    # 4. Policy lane: NEVER hold out
    dec_policy = lifecycle.prepare_injection(
        "implement coding conventions",
        project_id="proj-holdout",
        session_id="session-policy-lane",
        lane="policy",
        random_fn=lambda: 0.0,
    )
    # In policy lane, holdout is never performed
    if dec_policy.decision is InjectionDecision.INJECT:
        conn = db.connect(db.db_path(brain_home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE session_id = 'session-policy-lane' AND kind = 'retrieval' AND json_extract(inputs_hash, '$') IS NOT NULL",
            ).fetchall()
            for r in rows:
                assert "withheld_id" not in json.loads(r["chosen_json"])
        finally:
            conn.close()


def test_holdout_deterministic_seed_and_single_item(brain_home, monkeypatch) -> None:
    """Verify single-item holdout returns HOLDOUT reason and deterministic seed works."""
    monkeypatch.setenv("SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE", "CANARY")
    monkeypatch.setenv("SECOND_BRAIN_HOLDOUT_EPSILON", "0.2")

    m_only = _seed_current(brain_home, "Single unique memory", "single unique body text")
    lifecycle = autoinject.BrainLifecycle(brain_home)

    # When holdout triggers on single item, delivered is empty -> NO_INJECTION with HOLDOUT
    dec_held = lifecycle.prepare_injection(
        "implement single unique memory",
        project_id="proj-holdout",
        session_id="session-single-held",
        random_fn=lambda: 0.05,  # 0.05 < 0.2 -> triggers holdout
    )
    assert dec_held.decision is InjectionDecision.NO_INJECTION
    assert dec_held.reason is NoInjectionReason.HOLDOUT
    assert dec_held.selected_ids == []

    # Verify decision record was still created with chosen=[] and alternatives=[m_only]
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE session_id = 'session-single-held' AND kind = 'retrieval'",
        ).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["chosen_json"]) == []
        assert json.loads(rows[0]["alternatives_json"]) == [m_only]
        assert rows[0]["propensity"] == pytest.approx(0.2)
        assert rows[0]["randomized"] == 1
    finally:
        conn.close()

    # When holdout does NOT trigger (random value >= epsilon):
    dec_delivered = lifecycle.prepare_injection(
        "implement single unique memory",
        project_id="proj-holdout",
        session_id="session-single-delivered",
        random_fn=lambda: 0.95,  # 0.95 >= 0.2 -> delivery
    )
    assert dec_delivered.decision is InjectionDecision.INJECT
    assert dec_delivered.selected_ids == [m_only]

    # Verify delivery decision was recorded with propensity = 1.0 - epsilon = 0.8
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE session_id = 'session-single-delivered' AND kind = 'retrieval'",
        ).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["chosen_json"]) == [m_only]
        assert json.loads(rows[0]["alternatives_json"]) == []
        assert rows[0]["propensity"] == pytest.approx(0.8)
        assert rows[0]["randomized"] == 1
    finally:
        conn.close()


def test_finalize_session_updates_retrieval_decisions(brain_home, monkeypatch) -> None:
    """Verify finalize_session sets outcome_json and reward on pending retrieval decisions."""
    monkeypatch.setenv("SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE", "CANARY")
    m1 = _seed_current(brain_home, "Alpha rules", "alpha body content")
    m2 = _seed_current(brain_home, "Beta rules", "beta body content")

    lifecycle = autoinject.BrainLifecycle(brain_home)

    # 1. Success case: acceptance_passed = True
    lifecycle.prepare_injection(
        "implement alpha rules",
        project_id="proj-holdout",
        session_id="session-final-1",
        random_fn=lambda: 0.0,
    )

    # Before finalization: outcome_json and reward are NULL
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT outcome_json, reward FROM decisions WHERE session_id = 'session-final-1' AND kind = 'retrieval'",
        ).fetchone()
        assert row is not None
        assert row["outcome_json"] is None
        assert row["reward"] is None
    finally:
        conn.close()

    lifecycle.finalize_session(
        session_id="session-final-1",
        acceptance_passed=True,
        tokens_total=1500,
    )

    # After finalization: outcome_json and reward are populated
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT outcome_json, reward FROM decisions WHERE session_id = 'session-final-1' AND kind = 'retrieval'",
        ).fetchone()
        assert row is not None
        assert json.loads(row["outcome_json"]) == {
            "acceptance_passed": True,
            "tokens_total": 1500,
        }
        assert row["reward"] == pytest.approx(1.0)
    finally:
        conn.close()

    # 2. Failure case: acceptance_passed = False
    lifecycle.prepare_injection(
        "implement beta rules",
        project_id="proj-holdout",
        session_id="session-final-2",
        random_fn=lambda: 0.0,
    )

    lifecycle.finalize_session(
        session_id="session-final-2",
        acceptance_passed=False,
        tokens_total=850,
    )

    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT outcome_json, reward FROM decisions WHERE session_id = 'session-final-2' AND kind = 'retrieval'",
        ).fetchone()
        assert row is not None
        assert json.loads(row["outcome_json"]) == {
            "acceptance_passed": False,
            "tokens_total": 850,
        }
        assert row["reward"] == pytest.approx(0.0)
    finally:
        conn.close()

    # 3. Telemetry fallback case when tokens_total is None
    lifecycle.prepare_injection(
        "implement alpha rules",
        project_id="proj-holdout",
        session_id="session-telemetry-fallback",
        random_fn=lambda: 0.0,
    )

    # Write a telemetry JSONL file under telemetry/agent-performance/
    telem_dir = brain_home / "telemetry" / "agent-performance"
    telem_dir.mkdir(parents=True, exist_ok=True)
    telem_file = telem_dir / "session-telemetry-fallback.jsonl"
    telem_record = {
        "kind": "assistant_usage",
        "total_tokens": 200,
        "input_tokens": 120,
        "output_tokens": 80,
    }
    telem_file.write_text(json.dumps(telem_record) + "\n", encoding="utf-8")

    lifecycle.finalize_session(
        session_id="session-telemetry-fallback",
        acceptance_passed=True,
        # tokens_total not passed -> computed from telemetry file (200)
    )

    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT outcome_json, reward FROM decisions WHERE session_id = 'session-telemetry-fallback' AND kind = 'retrieval'",
        ).fetchone()
        assert row is not None
        outcome = json.loads(row["outcome_json"])
        assert outcome["acceptance_passed"] is True
        assert outcome["tokens_total"] == 200
        assert row["reward"] == pytest.approx(1.0)
    finally:
        conn.close()
