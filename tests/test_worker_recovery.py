"""Focused regressions for operator recovery of worker attempts.

Recovery must reach the same authoritative ownership state admission writes, and
must refuse whenever the release rule is not satisfied: no accepted outcome, no
established executor settlement, no established cleanup completion, a mismatched
host generation, or nothing but a lease that expired.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from second_brain import worker_recovery


@pytest.fixture(autouse=True)
def _temp_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recovery must operate on the disposable store, never the canonical Brain DB."""
    store = tmp_path / "disposable" / "db" / "brain.sqlite"
    store.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(worker_recovery, "_db", lambda home=None: store)


def _make_home(tmp_path: Path) -> Path:
    home = tmp_path / "brain"
    home.mkdir()
    db = worker_recovery._db(home)
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE worker_tasks("
            "task_id TEXT, state TEXT, lease_expires_at TEXT, packet_sha256 TEXT, accepted_at TEXT,"
            "settled_at TEXT, updated_at TEXT, attempt_id TEXT, access_intent TEXT, project_id TE"
                "XT,"
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
            "worktree_id TEXT, worktree_root TEXT, writer_ownership TEXT, logical_outcome TEXT,"
            "executor_settled INTEGER, cleanup_complete INTEGER, host_session_id TEXT,"
            "callback_token_sha256 TEXT, host_generation TEXT, native_attempt_id TEXT,"
                " native_job_id TEXT,"
            "agent_id TEXT, lifecycle_sequence INTEGER, bound_at TEXT, ownership_updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE worker_lifecycle_receipts("
            "attempt_id TEXT, sequence INTEGER, receipt_sha256 TEXT, payload_json TEXT,"
                " recorded_at TEXT)"
        )
    return home


def _attempt(
    home: Path,
    *,
    attempt_id: str = "attempt-1",
    outcome: str | None = "completed",
    executor_settled: int = 1,
    cleanup_complete: int = 0,
    ownership: str = "held",
    generation: str = "gen-1",
    lease: str = "2026-09-19T00:00:00+00:00",
    task_id: str = "task-1",
) -> None:
    with sqlite3.connect(worker_recovery._db(home)) as conn:
        conn.execute(
            "INSERT INTO worker_tasks(task_id,attempt_id,project_id,worktree_id,state,writer_owne"
                "rship,"
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
            "logical_outcome,executor_settled,cleanup_complete,host_session_id,host_generation,"
            "native_attempt_id,native_job_id,agent_id,lifecycle_sequence,lease_expires_at,updated"
                "_at,"
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
                ""
            "ownership_updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                attempt_id,
                "proj",
                "wt",
                "SUBMITTED",
                ownership,
                outcome,
                executor_settled,
                cleanup_complete,
                "session-1",
                generation,
                "native-1",
                None,
                "AgentA",
                1,
                lease,
                "2026-09-19T00:00:00+00:00",
                "2026-09-19T00:00:00+00:00",
            ),
        )


def test_inspect_is_read_only_and_reports_the_unresolved_conditions(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home)

    report = worker_recovery.inspect_attempt(home, attempt_id="attempt-1")

    attempt = report["attempts"][0]
    assert attempt["writer_ownership"] == "held"
    assert attempt["unresolved_conditions"] == [
        "cleanup completion is not established for: the attempt's owned resources"
    ]
    with sqlite3.connect(worker_recovery._db(home)) as conn:
        assert conn.execute("SELECT writer_ownership FROM worker_tasks").fetchone()[0] == "held"


def test_bare_operator_request_is_refused(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home)

    result = worker_recovery.recover_attempt(home, attempt_id="attempt-1", actor="operator")

    assert result["action"] == "protection-retained"
    assert result["changed"] is False
    assert any("cleanup completion" in c for c in result["unresolved_conditions"])


def test_expired_lease_alone_never_releases(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home, executor_settled=0, lease="2020-01-01T00:00:00+00:00")

    result = worker_recovery.recover_attempt(home, attempt_id="attempt-1", actor="operator")

    assert result["changed"] is False
    assert any("executor settlement" in c for c in result["unresolved_conditions"])


def test_generation_mismatch_is_refused(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home)

    with pytest.raises(worker_recovery.RecoveryError) as excinfo:
        worker_recovery.recover_attempt(
            home, attempt_id="attempt-1", actor="operator", host_generation="gen-other"
        )

    assert excinfo.value.code == "GENERATION_MISMATCH"


def test_valid_recovery_releases_and_preserves_the_outcome(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home)
    worker_recovery.record_quiescence(
        home,
        attempt_id="attempt-1",
        resource="isolation-handle",
        method="operator inspected the isolation worktree and the capture path",
        observation="no capture, commit or disposable process remained for the attempt",
        actor="operator",
        host_generation="gen-1",
    )

    dry = worker_recovery.recover_attempt(home, attempt_id="attempt-1", actor="operator")
    assert dry["action"] == "release-permitted"
    assert dry["changed"] is False

    applied = worker_recovery.recover_attempt(
        home, attempt_id="attempt-1", actor="operator", dry_run=False
    )
    assert applied["action"] == "released-by-operator-recovery"
    assert applied["logical_outcome_preserved"] == "completed"

    report = worker_recovery.inspect_attempt(home, attempt_id="attempt-1")["attempts"][0]
    assert report["writer_ownership"] == "released"
    assert report["cleanup_complete"] is True
    assert report["logical_outcome"] == "completed"
    assert report["receipts"][0]["sequence"] == 2


def test_repeated_recovery_is_idempotent_and_spares_newer_attempts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home)
    _attempt(home, attempt_id="attempt-2", task_id="task-2", ownership="held")
    worker_recovery.record_quiescence(
        home,
        attempt_id="attempt-1",
        resource="isolation-handle",
        method="operator inspection",
        observation="idle",
        actor="operator",
    )

    first = worker_recovery.recover_attempt(
        home, attempt_id="attempt-1", actor="operator", dry_run=False
    )
    second = worker_recovery.recover_attempt(
        home, attempt_id="attempt-1", actor="operator", dry_run=False
    )

    assert first["changed"] is True
    assert second["action"] == "already-released"
    assert second["changed"] is False
    newer = worker_recovery.inspect_attempt(home, attempt_id="attempt-2")["attempts"][0]
    assert newer["writer_ownership"] == "held"
