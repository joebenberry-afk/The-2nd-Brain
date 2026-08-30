import json
import sqlite3

import pytest

from second_brain import db
from second_brain.errors import BrainError
from second_brain.goals import GoalStatus, GoalStore


def test_goal_transitions_and_audit_events(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1", ["P4", "qualification"])
    assert goal.status is GoalStatus.ACTIVE
    blocked = store.transition(goal.goal_id, GoalStatus.BLOCKED, blocker_note="awaiting verifier")
    assert blocked.status is GoalStatus.BLOCKED
    resumed = store.transition(goal.goal_id, GoalStatus.ACTIVE)
    assert resumed.status is GoalStatus.ACTIVE
    store.complete_milestone(goal.goal_id, "m-1", "test://p4")
    store.complete_milestone(goal.goal_id, "m-2", "report://qualification")
    persisted = store.get_goal(goal.goal_id)
    assert persisted is not None
    assert persisted.status is GoalStatus.COMPLETED

    conn = db.connect(db.db_path(brain_home))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM goal_events WHERE goal_id = ?", (goal.goal_id,)
        ).fetchone()[0] >= 4
    finally:
        conn.close()


def test_terminal_goals_reject_transitions(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1", ["P4"])
    store.complete_milestone(goal.goal_id, "m-1", "test://p4")
    with pytest.raises(BrainError, match="Illegal transition"):
        store.transition(goal.goal_id, GoalStatus.ACTIVE)

    abandoned = store.create_goal("abandon", "stop", initial_status=GoalStatus.PENDING)
    store.transition(abandoned.goal_id, GoalStatus.ABANDONED)
    with pytest.raises(BrainError, match="Illegal transition"):
        store.transition(abandoned.goal_id, GoalStatus.ACTIVE)


def test_transition_requires_evidence_and_blocker_note(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1")
    with pytest.raises(BrainError, match="evidence"):
        store.transition(goal.goal_id, GoalStatus.COMPLETED)
    with pytest.raises(BrainError, match="blocker"):
        store.transition(goal.goal_id, GoalStatus.BLOCKED)


def test_milestone_evidence_and_idempotency(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1", ["P4"])
    with pytest.raises(BrainError, match="evidence"):
        store.complete_milestone(goal.goal_id, "m-1", "")
    completed = store.complete_milestone(goal.goal_id, "m-1", "test://p4")
    events_before = len(store.list_goal_events(goal.goal_id))
    assert store.complete_milestone(goal.goal_id, "m-1", "test://p4") == completed
    assert len(store.list_goal_events(goal.goal_id)) == events_before
    with pytest.raises(BrainError, match="different evidence"):
        store.complete_milestone(goal.goal_id, "m-1", "test://other")


def test_unknown_milestone_and_empty_milestones(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1", ["P4"])
    with pytest.raises(BrainError, match="Milestone m-2 not found"):
        store.complete_milestone(goal.goal_id, "m-2", "test://p4")
    empty = store.create_goal("empty", "no steps")
    assert empty.status is GoalStatus.ACTIVE
    assert store.transition(empty.goal_id, GoalStatus.COMPLETED, evidence_ref="test://empty").status is GoalStatus.COMPLETED
    persisted = store.get_goal(empty.goal_id)
    assert persisted is not None
    assert persisted.completed_at is not None


def test_initial_status_and_status_filtering(brain_home):
    store = GoalStore(brain_home)
    pending = store.create_goal("pending", "wait", initial_status=GoalStatus.PENDING)
    active = store.create_goal("active", "run")
    blocked = store.transition(active.goal_id, GoalStatus.BLOCKED, blocker_note="wait")
    completed = store.create_goal("completed", "done", ["step"])
    store.complete_milestone(completed.goal_id, "m-1", "test://done")

    assert [g.goal_id for g in store.list_goals([GoalStatus.PENDING])] == [pending.goal_id]
    assert {g.goal_id for g in store.list_goals(["ACTIVE", "BLOCKED"])} == {
        active.goal_id,
        blocked.goal_id,
    }
    assert {g.goal_id for g in store.list_active_goals()} == {active.goal_id, blocked.goal_id}


def test_corrupt_persisted_goal_state_is_explicit(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1", ["P4"])
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute("UPDATE goals SET milestones_json = ? WHERE goal_id = ?", ("{", goal.goal_id))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(BrainError, match=f"Goal {goal.goal_id}.*milestones_json"):
        store.get_goal(goal.goal_id)


def test_missing_milestone_field_is_explicit(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1", ["P4"])
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "UPDATE goals SET milestones_json = ? WHERE goal_id = ?",
            (json.dumps([{"milestone_id": "m-1"}]), goal.goal_id),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(BrainError, match="milestone.*title"):
        store.get_goal(goal.goal_id)


def test_unknown_persisted_status_is_explicit(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1")
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE goals SET status = ? WHERE goal_id = ?", ("BROKEN", goal.goal_id))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(BrainError, match=f"Goal {goal.goal_id}.*status"):
        store.get_goal(goal.goal_id)


def test_missing_goal_is_explicit_for_mutations(brain_home):
    store = GoalStore(brain_home)
    with pytest.raises(BrainError, match="Goal missing not found"):
        store.transition("missing", GoalStatus.ACTIVE)
    with pytest.raises(BrainError, match="Goal missing not found"):
        store.complete_milestone("missing", "m-1", "test://missing")
