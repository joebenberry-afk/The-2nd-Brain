"""Reservation lifecycle: only proven-unused capacity is returned; uncertainty stays a liability.

The rule under test: a refund must be conditional on authoritative evidence that dispatch never
became billable. An unconditional refund in a ``finally`` block is exactly the failure mode this
suite exists to reject -- a missing response does not establish that nothing happened.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from second_brain import contracts, db, governor, ledger  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "omp_replay_state.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("omp_fixture", FIXTURE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _home(tmp_path: Path, *, worker_tokens: int, soft_ratio: float = 0.8) -> Path:
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "config" / "governor.toml").write_text(
        f"[budgets]\nworker_tokens = {worker_tokens}\nsoft_ratio = {soft_ratio}\n", encoding="utf-8"
    )
    return home


def _open_reservation(home: Path, session_id: str, task_id: str) -> dict:
    with db.connect(home / "db" / "brain.sqlite") as conn:
        conn.row_factory = __import__("sqlite3").Row
        row = conn.execute(
            "SELECT * FROM budget_reservations WHERE session_id=? AND task_id=?",
            (session_id, task_id),
        ).fetchone()
        return dict(row) if row is not None else {}


def _child_session(home: Path, root: str, child: str) -> None:
    """A later session in the same root episode: its ledger declares this root parent."""
    with ledger.LedgerStore(home, child, host="omp").open(create=True) as store:
        store.create_session(
            contracts.BrainSessionIdentity(
                internal_session_id=ledger.internal_session_id(child),
                host="omp",
                host_session_id=child,
                project_id="reservation-project",
                created_at="2026-01-01T00:00:00.000Z",
                status="active",
                pinned=False,
                schema_version=ledger.LEDGER_SCHEMA_VERSION,
                root_parent_session_id=ledger.internal_session_id(root),
            )
        )


def test_cancellation_requires_proven_unused_evidence(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    assert governor.reserve_budget(home, "s1", "t1", tokens=60)["reserved"] is True

    unevidenced = governor.cancel_budget_reservation(home, "s1", "t1", "cleanup")
    assert unevidenced["cancelled"] is False
    assert unevidenced["refused"] == "EVIDENCE_REQUIRED"

    evidenced = governor.cancel_budget_reservation(
        home, "s1", "t1", "PREPARATION_FAILED_BEFORE_DISPATCH", evidence="proven_unused"
    )
    assert evidenced["cancelled"] is True
    assert governor.list_budget_reservations(home, "s1") == []


def test_cancellation_is_idempotent_and_does_not_refund_twice(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "t1", tokens=60)
    first = governor.cancel_budget_reservation(home, "s1", "t1", "unused", evidence="proven_unused")
    second = governor.cancel_budget_reservation(
        home, "s1", "t1", "unused", evidence="proven_unused"
    )
    assert (first["cancelled"], first["already_cancelled"]) == (True, False)
    assert (second["cancelled"], second["already_cancelled"]) == (True, True)

    # One refund, not two: the whole cap is available again, but not more than the cap.
    assert governor.reserve_budget(home, "s1", "t2", tokens=100)["reserved"] is True
    assert governor.reserve_budget(home, "s1", "t3", tokens=1)["reserved"] is False


def test_uncertain_dispatch_keeps_the_liability(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "t1", tokens=60)
    marked = governor.mark_budget_reservation_unresolved(home, "s1", "t1", "DISPATCH_UNCERTAIN")
    assert marked["unresolved"] is True

    # Uncertainty is not a refund: the capacity is still spoken for.
    assert len(governor.list_budget_reservations(home, "s1")) == 1
    refused = governor.reserve_budget(home, "s1", "t2", tokens=60)
    assert refused["reserved"] is False
    assert refused["outstanding"] == 60


def test_a_cancelled_reservation_cannot_be_consumed_later(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "t1", tokens=60)
    governor.cancel_budget_reservation(home, "s1", "t1", "unused", evidence="proven_unused")

    # A dispatch arriving after the cancellation must not spend returned capacity.
    late = governor.consume_budget_reservation(home, "s1", "t1", "late-dispatch")
    assert late["consumed"] is False
    assert late["refused"] == "RESERVATION_CANCELLED"
    assert _open_reservation(home, "s1", "t1")["cancelled_at"] is not None


def test_recovering_one_reservation_leaves_the_newer_one_alone(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "older", tokens=40)
    governor.reserve_budget(home, "s1", "newer", tokens=40)

    governor.cancel_budget_reservation(home, "s1", "older", "unused", evidence="proven_unused")

    newer = _open_reservation(home, "s1", "newer")
    assert newer["cancelled_at"] is None
    assert newer["consumed_at"] is None
    assert governor.list_budget_reservations(home, "s1") == [newer]


def test_consume_reconciles_actual_usage_once(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "t1", tokens=80)

    first = governor.consume_budget_reservation(home, "s1", "t1", "usage", actual_tokens=25)
    duplicate = governor.consume_budget_reservation(home, "s1", "t1", "usage", actual_tokens=25)
    assert first == {"consumed": True, "already_consumed": False}
    assert duplicate == {"consumed": False, "already_consumed": True}
    row = _open_reservation(home, "s1", "t1")
    assert row["actual_tokens"] == 25
    assert row["resolution"] == "consumed"


def test_zero_cap_always_refuses_without_a_default_fallback(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=0)
    result = governor.reserve_budget(home, "s1", "t1", tokens=1)
    assert result["reserved"] is False
    assert result["cap"] == 0
    assert result["reason"] == "BUDGET_EXHAUSTED"
    # Nothing was written for a refused zero-cap reservation.
    assert governor.list_budget_reservations(home, "s1") == []


def test_new_session_in_the_episode_does_not_reset_liability(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    assert governor.reserve_budget(home, "root-session", "root-task", tokens=80)["reserved"]

    _child_session(home, "root-session", "child-session")
    episode = governor._episode_host_sessions(home, "root-session")
    assert "child-session" in episode
    assert governor.reserve_budget(home, "child-session", "child-task", tokens=80)["reserved"]

    # The root episode now carries both liabilities: a third request cannot overbook it.
    third = governor.reserve_budget(
        home, "root-session", "root-task-2", tokens=30
    )
    assert third["reserved"] is False
    assert third["outstanding"] == 160
    fourth = governor.reserve_budget(home, "child-session", "child-task-2", tokens=30)
    assert fourth["reserved"] is False


def test_reconcile_cancels_only_when_no_attempt_exists(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "never-admitted", tokens=50)
    outcome = governor.reconcile_budget_reservations(home, session_id="s1")
    assert outcome["cancelled"] == ["never-admitted"], outcome
    row = _open_reservation(home, "s1", "never-admitted")
    assert row["cancel_reason"] == "NO_ATTEMPT_RECORDED"
    assert row["resolution"] == "cancelled_unused"


@pytest.mark.parametrize("bound", [True, False])
def test_reconcile_distinguishes_observed_dispatch_from_uncertainty(tmp_path: Path, bound: bool) -> None:
    fixture = _load_fixture()
    home = _home(tmp_path, worker_tokens=100)
    fixture.make_brain(home)  # the registry tables must exist before a project is registered
    (tmp_path / "base").mkdir(parents=True, exist_ok=True)
    repo = fixture.make_repo(tmp_path / "base")
    fixture.registry.add_project(home, repo, project_id=fixture.PROJECT_ID)
    task_id = "bound" if bound else "unbound"
    context = fixture.admit(home, repo, task_id, "mutating", "omp-session")
    if bound:
        fixture.bind(home, task_id, context, "omp-session")

    assert governor.reserve_budget(home, "omp-session", task_id, tokens=50)["reserved"] is True
    outcome = governor.reconcile_budget_reservations(home, session_id="omp-session")
    if bound:
        assert outcome["consumed"] == [task_id], outcome
        assert _open_reservation(home, "omp-session", task_id)["resolution"] == "consumed"
    else:
        assert outcome["unresolved"] == [task_id], outcome
        assert governor.list_budget_reservations(home, "omp-session") != []
