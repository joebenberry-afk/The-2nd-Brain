"""The post-commit notification window: committed recording, recoverable delivery.

The defect this pins down: the terminal fact and the result row commit, the *later* ledger
notification fails, and the caller was told the whole operation failed. The repair commits an
outbox intent with the terminal write, reports recording and delivery separately, and delivers
the pending event from durable evidence -- with a content-addressed event id, so a repeated
delivery is a detected duplicate rather than a second logical event.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from second_brain import db, ledger, worker_protocol  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "omp_replay_state.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("omp_fixture", FIXTURE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def attempt(tmp_path: Path):
    fixture = _load_fixture()
    base = tmp_path / "base"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    setup = json.loads(
        subprocess.run(
            [sys.executable, str(FIXTURE), "setup", "--base", str(base), "--task-id", "notify",
             "--intent", "mutating", "--host-session", "omp-session"],
            capture_output=True, text=True, env=env, check=True,
        ).stdout
    )
    home = Path(setup["home"])
    return fixture, home, "notify", fixture._stored_context(home, "notify")


def _rows(home: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with sqlite3.connect(db.db_path(home)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


def _pending(home: Path, task_id: str) -> int:
    return int(
        _rows(
            home, "SELECT notification_pending FROM worker_task_meta WHERE task_id=?", (task_id,)
        )[0][0]
    )


def _ledger_events(home: Path) -> int:
    path = ledger.LedgerStore(home, "omp-session").dbfile
    if not path.exists():
        return 0
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='worker_completed'"
        ).fetchone()[0]


def _completed_response(home: Path, task_id: str, context: dict, token: str | None) -> dict:
    """Complete through the real adapter path, which is where the false label appeared."""
    import second_brain.omp_adapter as adapter

    payload = {
        "operation": "worker_result",
        "host_session_id": "omp-session",
        "task_id": task_id,
        "packet_sha256": context["packet_sha256"],
        "attempt_id": context["attempt_id"],
        "status": "completed",
        "result_sha256": "a" * 64,
        "callback_token": token,
    }
    return adapter.handle_request(home, payload)


def test_committed_recording_is_not_reported_as_a_failure(attempt, monkeypatch) -> None:
    fixture, home, task_id, context = attempt
    attempts: list[int] = []
    original_append = ledger.LedgerStore.append_events

    def failing_append(self, events):
        attempts.append(1)
        raise RuntimeError("LEDGER_UNAVAILABLE")

    # The real interruption point: the terminal write committed, the *ledger append* fails.
    monkeypatch.setattr(ledger.LedgerStore, "append_events", failing_append)
    response = fixture.complete(home, task_id, context, token=context["callback_token"])

    assert attempts, "the ledger append was attempted"
    assert response.get("recording") == "committed", response
    assert response.get("notification") == "pending", response
    assert response.get("status") == "completed", response
    monkeypatch.setattr(ledger.LedgerStore, "append_events", original_append)

    # The accepted fact is durable; only the notification is outstanding.
    state = _rows(home, "SELECT state FROM worker_tasks WHERE task_id=?", (task_id,))[0][0]
    assert state == "COMPLETED"
    assert _pending(home, task_id) == 1
    assert _ledger_events(home) == 0


def test_reconciliation_delivers_the_pending_notification_once(attempt, monkeypatch) -> None:
    fixture, home, task_id, context = attempt
    monkeypatch.setattr(
        ledger.LedgerStore, "append_events",
        lambda self, events: (_ for _ in ()).throw(RuntimeError("LEDGER_UNAVAILABLE")),
    )
    fixture.complete(home, task_id, context, token=context["callback_token"])
    monkeypatch.undo()

    # New process semantics: reconciliation reads only durable state.
    outcome = worker_protocol.reconcile_worker_notifications(home, task_id=task_id)
    assert outcome["delivered"] == [task_id], outcome
    assert _ledger_events(home) == 1
    assert _pending(home, task_id) == 0


def test_repeated_delivery_is_duplicate_safe(attempt, monkeypatch) -> None:
    fixture, home, task_id, context = attempt
    monkeypatch.setattr(
        ledger.LedgerStore, "append_events",
        lambda self, events: (_ for _ in ()).throw(RuntimeError("LEDGER_UNAVAILABLE")),
    )
    fixture.complete(home, task_id, context, token=context["callback_token"])
    monkeypatch.undo()
    worker_protocol.reconcile_worker_notifications(home, task_id=task_id)
    assert _ledger_events(home) == 1

    # The acknowledgement was "lost": the intent is pending again, so reconciliation runs twice
    # over an event that is already recorded. It must detect the duplicate, not record it twice.
    with sqlite3.connect(db.db_path(home)) as conn:
        conn.execute("UPDATE worker_task_meta SET notification_pending=1 WHERE task_id=?", (task_id,))
        conn.commit()
    again = worker_protocol.reconcile_worker_notifications(home, task_id=task_id)
    assert again["already_delivered"] == [task_id], again
    assert _ledger_events(home) == 1, "no second logical event"
    assert _pending(home, task_id) == 0


def test_uninterrupted_completion_reports_delivered(attempt) -> None:
    fixture, home, task_id, context = attempt
    response = fixture.complete(home, task_id, context, token=context["callback_token"])
    assert response.get("notification") == "delivered", response
    assert _ledger_events(home) == 1
    assert _pending(home, task_id) == 0
