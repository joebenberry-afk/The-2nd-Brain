"""Regressions for worker recovery: settlement reconciliation and interrupted release.

The interrupted path rests on two authoritative objects - a persisted complete
resource census and a bound quiescence attestation for every resource it lists -
and on an exact generation binding. Unknown is never a wildcard, generation zero
is a real generation, and recovery never advances the host lifecycle sequence.
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
            "worktree_id TEXT, worktree_root TEXT, writer_ownership TEXT, logical_outcome TEXT,"
            "executor_settled INTEGER, cleanup_complete INTEGER, host_session_id TEXT,"
            "callback_token_sha256 TEXT, host_generation TEXT, native_attempt_id TEXT, native_job"
            "_id TEXT,"
            "agent_id TEXT, lifecycle_sequence INTEGER, bound_at TEXT, ownership_updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE worker_lifecycle_receipts("
            "attempt_id TEXT, sequence INTEGER, receipt_sha256 TEXT, payload_json TEXT, recorded_"
            "at TEXT)"
        )
    return home


def _attempt(
    home: Path,
    *,
    attempt_id: str = "attempt-1",
    task_id: str = "task-1",
    outcome: str | None = "completed",
    executor_settled: int = 1,
    cleanup_complete: int = 0,
    ownership: str = "held",
    generation: object = 0,
    sequence: int = 1,
    state: str = "SUBMITTED",
    access_intent: str = "mutating",
) -> None:
    with sqlite3.connect(worker_recovery._db(home)) as conn:
        conn.execute(
            "INSERT INTO worker_tasks(task_id,attempt_id,project_id,worktree_id,state,access_inte"
            "nt,"
            "writer_ownership,logical_outcome,executor_settled,cleanup_complete,host_session_id,"
            "host_generation,native_attempt_id,native_job_id,agent_id,lifecycle_sequence,lease_ex"
            "pires_at,"
            "updated_at,ownership_updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                attempt_id,
                "proj",
                "wt",
                state,
                access_intent,
                ownership,
                outcome,
                executor_settled,
                cleanup_complete,
                "session-1",
                generation,
                "native-1",
                None,
                "AgentA",
                sequence,
                "2026-09-19T00:00:00+00:00",
                "2026-09-19T00:00:00+00:00",
                "2026-09-19T00:00:00+00:00",
            ),
        )


def _interrupted(home: Path, **kwargs: object) -> None:
    base: dict[str, object] = dict(
        outcome=None, executor_settled=0, cleanup_complete=0, sequence=-1, state="SUBMITTED"
    )
    base.update(kwargs)
    _attempt(home, **base)  # type: ignore[arg-type]


def _census(home: Path, resources: list[str], generation: object = 0) -> str:
    return worker_recovery.record_census(
        home,
        attempt_id="attempt-1",
        host_generation=generation,  # type: ignore[arg-type]
        resources=resources,
        method="operator inspection of the host state for this attempt",
        observation="each listed resource was inspected and found idle",
        actor="operator",
        resources_complete=True,
    )["event_id"]


def _quiesce(home: Path, resource: str, generation: object = 0) -> None:
    worker_recovery.record_quiescence(
        home,
        attempt_id="attempt-1",
        resource=resource,
        method="operator inspection",
        observation="idle",
        actor="operator",
        host_generation=generation,  # type: ignore[arg-type]
    )


# --- generation parser edges -------------------------------------------------


@pytest.mark.parametrize("value,expected", [(0, 0), ("0", 0), (7, 7), ("12", 12)])
def test_generation_accepts_zero_and_numeric_strings(value: object, expected: int) -> None:
    assert worker_recovery._generation(value) == expected


@pytest.mark.parametrize("value", [None, "", "abc", "-1", 1.5, True])
def test_generation_rejects_unknown_or_non_canonical(value: object) -> None:
    with pytest.raises(worker_recovery.RecoveryError) as excinfo:
        worker_recovery._generation(value)
    assert excinfo.value.code == "GENERATION_MISMATCH"


# --- census qualification ----------------------------------------------------


def test_census_without_established_completeness_is_not_recorded(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _interrupted(home)
    with pytest.raises(worker_recovery.RecoveryError) as excinfo:
        worker_recovery.record_census(
            home,
            attempt_id="attempt-1",
            host_generation=0,
            resources=["R1"],
            method="operator inspection",
            observation="R1 idle",
            actor="operator",
            resources_complete=False,
        )
    assert excinfo.value.code == "INSUFFICIENT_EVIDENCE"


# --- T1..T4 hard gates -------------------------------------------------------


def test_T1_omitted_resource_is_not_inferred_from_history(tmp_path: Path) -> None:
    """A census naming R3 must fail when only historical attestations for R1,R2 exist."""
    home = _make_home(tmp_path)
    _interrupted(home)
    _quiesce(home, "R1")
    _quiesce(home, "R2")
    census = _census(home, ["R1", "R2", "R3"])

    result = worker_recovery.release_interrupted_attempt(
        home, attempt_id="attempt-1", host_generation=0, census_event_id=census, actor="operator"
    )

    assert result["action"] == "protection-retained"
    assert result["changed"] is False
    assert any("R3" in c for c in result["unresolved_conditions"])


def test_T2_missing_generation_is_refused(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _interrupted(home, generation=None)

    with pytest.raises(worker_recovery.RecoveryError) as excinfo:
        worker_recovery.release_interrupted_attempt(
            home,
            attempt_id="attempt-1",
            host_generation=0,
            census_event_id="r-anything",
            actor="operator",
        )

    assert excinfo.value.code == "GENERATION_MISMATCH"


def test_T3_generation_zero_is_a_real_generation(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _interrupted(home, generation=0)
    census = _census(home, ["R1"], generation=0)
    _quiesce(home, "R1", generation=0)

    dry = worker_recovery.release_interrupted_attempt(
        home, attempt_id="attempt-1", host_generation=0, census_event_id=census, actor="operator"
    )
    assert dry["action"] == "release-permitted"

    applied = worker_recovery.release_interrupted_attempt(
        home,
        attempt_id="attempt-1",
        host_generation=0,
        census_event_id=census,
        actor="operator",
        dry_run=False,
    )
    assert applied["changed"] is True
    report = worker_recovery.inspect_attempt(home, attempt_id="attempt-1")["attempts"][0]
    assert report["writer_ownership"] == "released"
    assert report["logical_outcome"] is None
    assert report["executor_settled"] is False
    assert report["cleanup_complete"] is False


def test_T4_recovery_does_not_advance_lifecycle_sequence(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _interrupted(home)
    census = _census(home, ["R1"])
    _quiesce(home, "R1")

    worker_recovery.release_interrupted_attempt(
        home,
        attempt_id="attempt-1",
        host_generation=0,
        census_event_id=census,
        actor="operator",
        dry_run=False,
    )

    report = worker_recovery.inspect_attempt(home, attempt_id="attempt-1")["attempts"][0]
    assert report["lifecycle_sequence"] == -1
    with sqlite3.connect(worker_recovery._db(home)) as conn:
        receipts = conn.execute("SELECT COUNT(*) FROM worker_lifecycle_receipts").fetchone()[0]
    assert receipts == 0


# --- settlement reconciliation (unchanged contract) --------------------------


def _results_table(home: Path) -> None:
    """The store always carries this table (migrations); the settled rule reads it."""
    with sqlite3.connect(worker_recovery._db(home)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS worker_attempt_results("
            "attempt_id TEXT, task_id TEXT, packet_sha256 TEXT, result_sha256 TEXT,"
            "payload_json TEXT, recorded_at TEXT)"
        )


def _settled_result(home: Path, attempt_id: str = "attempt-1") -> None:
    """Add the result row the settled rule binds to: evidence the execution finished."""
    _results_table(home)
    with sqlite3.connect(worker_recovery._db(home)) as conn:
        conn.execute(
            "INSERT INTO worker_attempt_results(attempt_id,result_sha256) VALUES(?,?)",
            (attempt_id, "b" * 64),
        )


def _ownership(home: Path, attempt_id: str = "attempt-1") -> str | None:
    with sqlite3.connect(worker_recovery._db(home)) as conn:
        row = conn.execute(
            "SELECT writer_ownership FROM worker_tasks WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
    return None if row is None else str(row[0])


def test_settled_release_requires_a_recorded_result_row(tmp_path: Path) -> None:
    """A terminal-looking row without a result is not evidence that execution ended."""
    home = _make_home(tmp_path)
    _attempt(home, ownership="quarantined", state="COMPLETED", outcome="completed")
    _results_table(home)  # the table is present; the row that proves the result is not

    with pytest.raises(worker_recovery.RecoveryError):
        worker_recovery.release_settled_quarantine(
            home, attempt_id="attempt-1", actor="operator", dry_run=False
        )

    assert _ownership(home) == "quarantined"


def test_settled_release_refuses_an_attempt_without_a_recorded_terminal(tmp_path: Path) -> None:
    """The class whose launch window may still be open must not use the settled rule."""
    home = _make_home(tmp_path)
    _attempt(home, ownership="quarantined", state="UNRESOLVED", outcome=None)
    _settled_result(home)

    with pytest.raises(worker_recovery.RecoveryError):
        worker_recovery.release_settled_quarantine(
            home, attempt_id="attempt-1", actor="operator", dry_run=False
        )

    assert _ownership(home) == "quarantined"


def test_settled_release_binds_to_the_recorded_terminal(tmp_path: Path) -> None:
    """Terminal state, outcome, result row and an expired lease release; dry run changes nothing."""
    home = _make_home(tmp_path)
    _attempt(home, ownership="quarantined", state="COMPLETED", outcome="completed")
    _settled_result(home)

    dry = worker_recovery.release_settled_quarantine(home, attempt_id="attempt-1", actor="operator")
    assert dry["action"] == "released-settled"
    assert dry["dry_run"] is True
    assert dry["changed"] is False
    assert _ownership(home) == "quarantined"

    applied = worker_recovery.release_settled_quarantine(
        home, attempt_id="attempt-1", actor="operator", dry_run=False
    )
    assert applied["changed"] is True
    assert _ownership(home) == "released"

    again = worker_recovery.release_settled_quarantine(
        home, attempt_id="attempt-1", actor="operator", dry_run=False
    )
    assert again["action"] == "already-released"


def test_settlement_reconciliation_still_requires_evidence(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home, executor_settled=1, cleanup_complete=0, outcome="completed")
    result = worker_recovery.recover_attempt(home, attempt_id="attempt-1", actor="operator")
    assert result["action"] == "protection-retained"
    assert any("cleanup completion" in c for c in result["unresolved_conditions"])


def test_settlement_reconciliation_releases_with_bound_attestation(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _attempt(home, executor_settled=1, cleanup_complete=0, outcome="completed")
    _quiesce(home, "isolation-handle")

    applied = worker_recovery.recover_attempt(
        home, attempt_id="attempt-1", actor="operator", dry_run=False
    )

    assert applied["action"] == "released-by-operator-recovery"
    report = worker_recovery.inspect_attempt(home, attempt_id="attempt-1")["attempts"][0]
    assert report["writer_ownership"] == "released"
    assert report["logical_outcome"] == "completed"


def test_interrupted_release_needs_a_census_and_spares_newer_attempts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _interrupted(home)
    _interrupted(home, attempt_id="attempt-2", task_id="task-2", generation=0)

    with pytest.raises(worker_recovery.RecoveryError) as excinfo:
        worker_recovery.release_interrupted_attempt(
            home,
            attempt_id="attempt-1",
            host_generation=0,
            census_event_id="r-missing",
            actor="operator",
        )
    assert excinfo.value.code == "CENSUS_NOT_FOUND"

    census = _census(home, ["R1"])
    _quiesce(home, "R1")
    worker_recovery.release_interrupted_attempt(
        home,
        attempt_id="attempt-1",
        host_generation=0,
        census_event_id=census,
        actor="operator",
        dry_run=False,
    )

    newer = worker_recovery.inspect_attempt(home, attempt_id="attempt-2")["attempts"][0]
    assert newer["writer_ownership"] == "held"
