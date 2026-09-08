from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from second_brain import cli, contracts, hermes_adapter, ledger, worker_protocol

HASH = "a" * 64
START = datetime(2026, 1, 1, tzinfo=UTC)


def test_invalid_transition_raises() -> None:
    with pytest.raises(contracts.WorkerPacketError, match="INVALID_TRANSITION"):
        contracts.WorkerLifecycle.transition("COMPLETED", "WORKING")


def test_worker_canceled_alias_reaches_canceled_state(brain_home) -> None:
    worker_protocol.register_task(brain_home, "canceled-alias", HASH, now=START)
    result = worker_protocol.record_worker_event(
        brain_home, "canceled-alias", HASH, "worker_canceled", now=START
    )
    assert result["state"] == contracts.WorkerLifecycle.CANCELED
    worker_protocol.register_task(brain_home, "task-completed-alias", HASH, now=START)
    worker_protocol.record_worker_event(
        brain_home, "task-completed-alias", HASH, "accepted", now=START
    )
    assert (
        worker_protocol.record_worker_event(
            brain_home, "task-completed-alias", HASH, "task_completed", now=START
        )["state"]
        == contracts.WorkerLifecycle.COMPLETED
    )
    worker_protocol.register_task(brain_home, "task-failed-alias", HASH, now=START)
    worker_protocol.record_worker_event(
        brain_home, "task-failed-alias", HASH, "worker_started", now=START
    )
    assert (
        worker_protocol.record_worker_event(
            brain_home, "task-failed-alias", HASH, "task_failed", now=START
        )["state"]
        == contracts.WorkerLifecycle.FAILED
    )


@pytest.mark.parametrize(
    "event_name",
    ["task_completed", "task_failed", "worker_cancelled", "worker_canceled"],
)
def test_worker_event_terminal_aliases_emit_result_telemetry(
    brain_home, monkeypatch: pytest.MonkeyPatch, event_name: str
) -> None:
    binding = hermes_adapter.resolve_binding(
        brain_home,
        {
            "bot_name": "Brain-Worker",
            "bot_role": "worker",
            "hermes_session_id": f"telemetry-{event_name}",
            "project_id": "second-brain",
            "repo_root": ".",
        },
    )
    task_id = f"telemetry-{event_name}"
    worker_protocol.register_task(
        brain_home, task_id, HASH, session_id=binding.host_session_id, now=START
    )
    if event_name in {"task_completed", "task_failed"}:
        worker_protocol.record_worker_event(
            brain_home,
            task_id,
            HASH,
            "accepted",
            session_id=binding.host_session_id,
            now=START,
        )
    seen: list[str] = []
    monkeypatch.setattr(
        hermes_adapter.autoinject,
        "_append_telemetry",
        lambda _home, _session, kind, _payload: seen.append(kind),
    )
    response = hermes_adapter.handle_worker_event(
        brain_home,
        binding,
        {
            "event": event_name,
            "task_id": task_id,
            "packet_sha256": HASH,
            "session_id": binding.host_session_id,
        },
    )
    assert response["status"] == "ok"
    assert seen == ["handoff_result"]


def test_lease_expiry_fails_task_and_unblocks_driver(brain_home) -> None:
    worker_protocol.register_task(brain_home, "lease-task", HASH, session_id="driver", now=START)
    worker_protocol.record_worker_event(
        brain_home, "lease-task", HASH, "worker_started", session_id="driver", now=START
    )
    result = worker_protocol.reap(brain_home, now=START + timedelta(seconds=301))
    assert result == [
        {
            "task_id": "lease-task",
            "action": "failed",
            "state": "FAILED",
            "failure_reason": "lease_expired",
        }
    ]
    with sqlite3.connect(brain_home / "db" / "brain.sqlite") as conn:
        assert (
            conn.execute("SELECT state FROM worker_tasks WHERE task_id='lease-task'").fetchone()[0]
            == "FAILED"
        )
    with sqlite3.connect(
        brain_home / "state" / "sessions" / ledger.internal_session_id("driver") / "ledger.sqlite"
    ) as conn:
        {row[0] for row in conn.execute("SELECT event_type FROM events")}


def test_reap_normalizes_offset_timestamps(brain_home) -> None:
    worker_protocol.register_task(
        brain_home,
        "offset-task",
        HASH,
        lease_seconds=10,
        now="2026-01-01T00:00:00+02:00",
    )
    worker_protocol.record_worker_event(
        brain_home,
        "offset-task",
        HASH,
        "worker_started",
        lease_seconds=10,
        now="2026-01-01T00:00:00+02:00",
    )
    outcome = worker_protocol.reap(brain_home, lease_seconds=10, now="2025-12-31T22:00:11Z")
    assert outcome[0]["failure_reason"] == "lease_expired"


def test_settled_requires_postcondition_evidence(brain_home) -> None:
    worker_protocol.register_task(brain_home, "settle-task", HASH, now=START)
    worker_protocol.record_worker_event(
        brain_home, "settle-task", HASH, "worker_started", now=START
    )
    worker_protocol.record_worker_event(brain_home, "settle-task", HASH, "completed", now=START)
    with pytest.raises(contracts.WorkerPacketError, match="SETTLEMENT_REJECTED"):
        worker_protocol.settle_task(brain_home, "settle-task", approved=True, evidence={})
    with pytest.raises(contracts.WorkerPacketError, match="SETTLEMENT_REJECTED"):
        worker_protocol.settle_task(
            brain_home,
            "settle-task",
            approved=True,
            evidence={"tests": [{"command": "pytest", "exit_code": 0}]},
            now=START + timedelta(seconds=1),
        )


def test_postcondition_evidence_requires_bounded_test_identity(brain_home) -> None:
    del brain_home
    assert not worker_protocol._has_postcondition_evidence(
        {"tests": [{"exit_code": True, "command": "pytest"}]}
    )
    assert not worker_protocol._has_postcondition_evidence({"tests": [{"exit_code": 0}]})
    assert not worker_protocol._has_postcondition_evidence(
        {"tests": [{"command": "x" * 513, "exit_code": 0}]}
    )
    assert worker_protocol._has_postcondition_evidence(
        {"tests": [{"command": "pytest -q", "exit_code": 0}]}
    )

    assert not worker_protocol._has_postcondition_evidence(
        {"tests": [{"command": "pytest", "exit_code": 0}], "diff_sha256": HASH}
    )
    assert not worker_protocol._has_postcondition_evidence(
        {"tests": [{"command": "pytest", "exit_code": 0, "extra": "nope"}]}
    )
    assert not worker_protocol._has_postcondition_evidence([{"command": "pytest", "exit_code": 0}])
    assert not worker_protocol._has_postcondition_evidence(
        {"tests": [{"name": 123, "exit_code": 0}]}
    )
    assert not worker_protocol._has_postcondition_evidence(
        {"tests": [{"command": ["pytest"], "exit_code": 0}]}
    )
    assert not worker_protocol._has_postcondition_evidence(
        {"tests": [{"name": 7, "command": "pytest", "exit_code": 0}]}
    )
    assert not worker_protocol._has_postcondition_evidence(
        {"diff_sha256": "invalid", "diff_hash": HASH}
    )
    assert not worker_protocol._has_postcondition_evidence({"diff_sha256": None, "diff_hash": HASH})
    assert not worker_protocol._has_postcondition_evidence({"diff_sha256": HASH, "diff_hash": None})
    assert worker_protocol._has_postcondition_evidence({"diff_hash": HASH})
    assert worker_protocol._has_postcondition_evidence({"diff_sha256": HASH, "diff_hash": HASH})
    assert not worker_protocol._is_sha256("+" + "a" * 63)
    assert not worker_protocol._is_sha256("a" * 63)


def test_settle_rejects_review_without_persisted_worker_result(
    brain_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_protocol.register_task(
        brain_home, "unbound-settle", HASH, session_id="driver", now=START
    )
    worker_protocol.record_worker_event(
        brain_home, "unbound-settle", HASH, "accepted", session_id="driver", now=START
    )
    worker_protocol.record_worker_event(
        brain_home, "unbound-settle", HASH, "completed", session_id="driver", now=START
    )
    monkeypatch.setattr(worker_protocol, "_approved_review_matches", lambda *args: True)
    monkeypatch.setattr(worker_protocol, "_approved_review_result_sha", lambda *args: "f" * 64)
    with pytest.raises(contracts.WorkerPacketError, match="SETTLEMENT_REJECTED"):
        worker_protocol.settle_task(
            brain_home,
            "unbound-settle",
            approved=True,
            evidence={"tests": [{"command": "pytest", "exit_code": 0}]},
        )


def test_completed_without_accept_is_rejected(brain_home) -> None:
    worker_protocol.register_task(brain_home, "unaccepted-task", HASH, now=START)
    with pytest.raises(contracts.WorkerPacketError, match="PROTOCOL_ERROR"):
        worker_protocol.record_worker_event(
            brain_home, "unaccepted-task", HASH, "completed", now=START
        )


def test_duplicate_and_hash_conflict_are_guarded(brain_home) -> None:
    worker_protocol.register_task(brain_home, "identity-task", HASH, now=START)
    first = worker_protocol.record_worker_event(
        brain_home, "identity-task", HASH, "accepted", now=START
    )
    duplicate = worker_protocol.record_worker_event(
        brain_home, "identity-task", HASH, "accepted", now=START
    )
    assert first["state"] == duplicate["state"] == "WORKING"
    assert duplicate["duplicate"] is True
    with pytest.raises(contracts.WorkerPacketError, match="PROTOCOL_ERROR"):
        worker_protocol.record_worker_event(
            brain_home, "identity-task", "b" * 64, "accepted", now=START
        )


def test_duplicate_event_renews_live_lease(brain_home) -> None:
    worker_protocol.register_task(brain_home, "renew-task", HASH, lease_seconds=10, now=START)
    worker_protocol.record_worker_event(
        brain_home, "renew-task", HASH, "accepted", lease_seconds=10, now=START
    )
    renewed = worker_protocol.record_worker_event(
        brain_home,
        "renew-task",
        HASH,
        "accepted",
        lease_seconds=10,
        now=START + timedelta(seconds=9),
    )
    assert renewed["duplicate"] is True
    assert (
        worker_protocol.reap(brain_home, now=START + timedelta(seconds=11), lease_seconds=10) == []
    )


def test_out_of_order_duplicate_never_shortens_lease(brain_home) -> None:
    worker_protocol.register_task(brain_home, "monotonic-task", HASH, lease_seconds=10, now=START)
    newer = worker_protocol.record_worker_event(
        brain_home,
        "monotonic-task",
        HASH,
        "accepted",
        lease_seconds=10,
        now=START + timedelta(seconds=9),
    )
    older = worker_protocol.record_worker_event(
        brain_home,
        "monotonic-task",
        HASH,
        "accepted",
        lease_seconds=10,
        now=START + timedelta(seconds=1),
    )
    assert older["lease_expires_at"] == newer["lease_expires_at"]
    assert (
        worker_protocol.reap(brain_home, now=START + timedelta(seconds=15), lease_seconds=10) == []
    )


def test_duplicate_delivery_renews_live_lease(brain_home) -> None:
    worker_protocol.register_task(brain_home, "delivery-task", HASH, lease_seconds=10, now=START)
    worker_protocol.record_worker_event(
        brain_home, "delivery-task", HASH, "delivered", lease_seconds=10, now=START
    )
    duplicate = worker_protocol.record_worker_event(
        brain_home,
        "delivery-task",
        HASH,
        "delivered",
        lease_seconds=10,
        now=START + timedelta(seconds=9),
    )
    assert duplicate["duplicate"] is True
    assert (
        worker_protocol.reap(brain_home, now=START + timedelta(seconds=11), lease_seconds=10) == []
    )


def test_driver_session_owns_terminal_event_across_worker_sessions(brain_home) -> None:
    task_id = "cross-session-task"
    worker_protocol.register_task(brain_home, task_id, HASH, session_id="driver-session", now=START)
    worker_protocol.record_worker_event(
        brain_home, task_id, HASH, "accepted", session_id="worker-session", now=START
    )
    duplicate = worker_protocol.record_worker_event(
        brain_home,
        task_id,
        HASH,
        "accepted",
        session_id="other-worker-session",
        now=START + timedelta(seconds=1),
    )
    assert duplicate["duplicate"] is True
    worker_protocol.record_worker_event(
        brain_home,
        task_id,
        HASH,
        "completed",
        session_id="worker-session",
        now=START + timedelta(seconds=1),
    )
    driver_db = (
        brain_home
        / "state"
        / "sessions"
        / ledger.internal_session_id("driver-session")
        / "ledger.sqlite"
    )
    with sqlite3.connect(driver_db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='worker_completed'"
            ).fetchone()[0]
            == 1
        )
    with sqlite3.connect(brain_home / "db" / "brain.sqlite") as conn:
        assert (
            conn.execute(
                "SELECT session_id FROM worker_task_meta WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            == "driver-session"
        )


def test_rejected_worker_event_transitions_submitted_task(brain_home) -> None:
    worker_protocol.register_task(brain_home, "rejected-task", HASH, now=START)
    rejected = worker_protocol.record_worker_event(
        brain_home, "rejected-task", HASH, "worker_rejected", now=START
    )
    assert rejected["state"] == "REJECTED"
    duplicate = worker_protocol.record_worker_event(
        brain_home, "rejected-task", HASH, "rejected", now=START + timedelta(seconds=1)
    )
    assert duplicate["duplicate"] is True


def test_late_delivery_does_not_mutate_terminal_task(brain_home) -> None:
    worker_protocol.register_task(brain_home, "terminal-task", HASH, now=START)
    worker_protocol.record_worker_event(brain_home, "terminal-task", HASH, "accepted", now=START)
    worker_protocol.record_worker_event(brain_home, "terminal-task", HASH, "completed", now=START)
    late = worker_protocol.record_worker_event(
        brain_home, "terminal-task", HASH, "delivered", now=START + timedelta(seconds=1)
    )
    assert late["duplicate"] is True


def test_redelivery_payload_is_bounded(brain_home) -> None:
    with pytest.raises(contracts.WorkerPacketError, match="PROTOCOL_ERROR"):
        worker_protocol.register_task(
            brain_home, "large-task", HASH, dispatch_payload={"prompt": "x" * (16 * 1024)}
        )


def test_malformed_diff_hash_is_not_postcondition_evidence(brain_home) -> None:
    worker_protocol.register_task(brain_home, "evidence-task", HASH, now=START)
    worker_protocol.record_worker_event(brain_home, "evidence-task", HASH, "accepted", now=START)
    worker_protocol.record_worker_event(brain_home, "evidence-task", HASH, "completed", now=START)
    with pytest.raises(contracts.WorkerPacketError, match="SETTLEMENT_REJECTED"):
        worker_protocol.settle_task(
            brain_home, "evidence-task", approved=True, evidence={"diff_hash": "not-a-sha256"}
        )


def test_settlement_rejects_unrelated_reviewed_diff(brain_home) -> None:
    session_id = "review-session"
    task_id = "reviewed-task"
    worker_protocol.register_task(brain_home, task_id, HASH, session_id=session_id, now=START)
    worker_protocol.record_worker_event(
        brain_home, task_id, HASH, "accepted", session_id=session_id, now=START
    )
    worker_protocol.record_worker_event(
        brain_home, task_id, HASH, "completed", session_id=session_id, now=START
    )
    reviewed = contracts.BrainLifecycleEvent(
        seq=0,
        event_id="reviewed-event",
        internal_session_id=ledger.internal_session_id(session_id),
        agent_id="reviewer",
        event_type=contracts.LifecycleEventType.RESULT_REVIEWED,
        timestamp=START.isoformat(),
        surface_visibility=contracts.SurfaceVisibility.MODEL_VISIBLE_APPEND,
        ignorable=False,
        payload={
            "task_id": task_id,
            "approved": True,
            "result_sha256": HASH,
            "evidence": {"diff_sha256": HASH},
        },
    )
    with ledger.LedgerStore(brain_home, session_id, host="test").open(create=True) as store:
        store.append_events([reviewed])
    with pytest.raises(contracts.WorkerPacketError, match="SETTLEMENT_REJECTED"):
        worker_protocol.settle_task(
            brain_home,
            task_id,
            approved=True,
            evidence={"diff_sha256": "b" * 64},
        )


def test_worker_plane_reap_fails_open_on_unavailable_db(brain_home, monkeypatch, capsys) -> None:
    def unavailable(_home):
        raise sqlite3.DatabaseError("malformed database")

    monkeypatch.setattr(worker_protocol, "reap", unavailable)
    args = SimpleNamespace(home=brain_home, worker_plane_command="reap", json=True)
    assert cli.cmd_worker_plane(args) == 0
    assert json.loads(capsys.readouterr().out)["reaped"] == []


def test_missing_dispatch_payload_fails_without_redelivery(brain_home) -> None:
    worker_protocol.register_task(brain_home, "missing-packet", HASH, now=START)
    outcome = worker_protocol.reap(brain_home, now=START + timedelta(seconds=301))
    assert outcome == [
        {
            "task_id": "missing-packet",
            "action": "failed",
            "state": "FAILED",
            "failure_reason": "UNACKNOWLEDGED",
        }
    ]


def test_unacknowledged_task_redelivers_once_then_fails(brain_home) -> None:
    worker_protocol.register_task(
        brain_home,
        "orphan-task",
        HASH,
        dispatch_payload={"task_id": "orphan-task", "prompt": "queued"},
        now=START,
    )
    first = worker_protocol.reap(brain_home, now=START + timedelta(seconds=301))
    second = worker_protocol.reap(brain_home, now=START + timedelta(seconds=602))
    assert first[0]["action"] == "redelivered"
    assert first[0]["packet"]["prompt"] == "queued"
    assert second[0]["failure_reason"] == "UNACKNOWLEDGED"
