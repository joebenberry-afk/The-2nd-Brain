"""Reservation lifecycle: only proven-unused capacity is returned; uncertainty stays a liability.

The rule under test: a refund must be conditional on authoritative evidence that dispatch never
became billable. An unconditional refund in a ``finally`` block is exactly the failure mode this
suite exists to reject -- a missing response does not establish that nothing happened.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from second_brain import contracts, db, governor, ledger  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "omp_replay_state.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("omp_fixture", FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _home(tmp_path: Path, *, worker_tokens: int, soft_ratio: float = 0.8) -> Path:
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "config" / "governor.toml").write_text(
        f"[budgets]\nworker_tokens = {worker_tokens}\nsoft_ratio = {soft_ratio}\n", encoding="utf-8"
    )
    return home


def _seed_usage(
    home: Path,
    session_id: str,
    total_tokens: int,
    *,
    response_id: str = "seed-response-1",
    append: bool = False,
) -> None:
    """The session has authoritative usage; without it the governor refuses as unaccountable.

    ``response_id`` is the billable-response identity, so two seeds with the same id are two
    observations of one request rather than two requests.
    """
    telemetry = home / "telemetry" / "agent-performance"
    telemetry.mkdir(parents=True, exist_ok=True)
    record = {
        "v": 3,
        "kind": "assistant_usage",
        "session": session_id,
        "timestamp": "2026-01-01T00:00:00.000Z",
        "provider": "test-provider",
        "model": "test-model",
        "response_id": response_id,
        "total_tokens": total_tokens,
    }
    path = telemetry / f"{session_id}.jsonl"
    existing = path.read_text(encoding="utf-8") if append and path.is_file() else ""
    path.write_text(existing + json.dumps(record) + "\n", encoding="utf-8")


def _cli(home: Path, *args: str) -> dict:
    """Run the real governor CLI in its own process against ``home``."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["SECOND_BRAIN_HOME"] = str(home)
    done = subprocess.run(
        [sys.executable, "-m", "second_brain", "governor", *args, "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(done.stdout)


def _open_reservation(home: Path, session_id: str, task_id: str) -> dict:
    with db.connect(home / "db" / "brain.sqlite") as conn:
        conn.row_factory = __import__("sqlite3").Row
        row = conn.execute(
            "SELECT * FROM budget_reservations WHERE session_id=? AND task_id=?",
            (session_id, task_id),
        ).fetchone()
        return dict(row) if row is not None else {}


def _episode_session(home: Path, host: str, *, root: str | None = None) -> None:
    """A ledger row for ``host``; with ``root`` it declares that session as its root parent."""
    with ledger.LedgerStore(home, host, host="omp").open(create=True) as store:
        store.create_session(
            contracts.BrainSessionIdentity(
                internal_session_id=ledger.internal_session_id(host),
                host="omp",
                host_session_id=host,
                project_id="reservation-project",
                created_at="2026-01-01T00:00:00.000Z",
                status="active",
                pinned=False,
                schema_version=ledger.LEDGER_SCHEMA_VERSION,
                root_parent_session_id=(
                    ledger.internal_session_id(root) if root is not None else None
                ),
            )
        )


def _child_session(home: Path, root: str, child: str) -> None:
    """A later session in the same root episode: its ledger declares this root parent."""
    _episode_session(home, child, root=root)


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


def test_a_resolved_reservation_cannot_be_reopened(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "cancelled", tokens=40)
    governor.cancel_budget_reservation(
        home, "s1", "cancelled", "PREPARATION_FAILED", evidence="proven_unused"
    )

    # Capacity that was returned cannot be re-created by re-asking for the same attempt.
    late = governor.reserve_budget(home, "s1", "cancelled", tokens=40)
    assert late["reserved"] is False
    assert late["reason"] == "RESERVATION_CANCELLED"
    assert _open_reservation(home, "s1", "cancelled")["cancelled_at"] is not None

    # The refusal wrote nothing, so the returned capacity is intact for other attempts.
    assert governor.reserve_budget(home, "s1", "other", tokens=100)["reserved"] is True
    governor.consume_budget_reservation(home, "s1", "other")

    governor.reserve_budget(home, "s1", "spent", tokens=40)
    governor.consume_budget_reservation(home, "s1", "spent")
    replay = governor.reserve_budget(home, "s1", "spent", tokens=40)
    assert replay["reserved"] is False
    assert replay["reason"] == "RESERVATION_CONSUMED"


def test_default_reservation_claims_the_remaining_allowance_not_a_fresh_cap(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    _seed_usage(home, "s1", 30)

    # The cap covers the whole root episode, so an untargeted claim takes what is left of it.
    first = governor.reserve_budget(home, "s1", "t1")
    assert first["reserved"] is True, first
    assert first["requested"] == 70
    assert first["outstanding"] == 70

    # Nothing is left to book while that claim is outstanding.
    second = governor.reserve_budget(home, "s1", "t2")
    assert second["reserved"] is False
    assert second["reason"] == "BUDGET_EXHAUSTED"

    # Once the episode has spent the whole cap there is no remainder to claim.
    governor.consume_budget_reservation(home, "s1", "t1")
    _seed_usage(home, "s1", 100)
    third = governor.reserve_budget(home, "s1", "t3")
    assert third["reserved"] is False
    assert third["reason"] == "BUDGET_EXHAUSTED"
    assert third["requested"] == 0


def test_zero_cap_always_refuses_without_a_default_fallback(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=0)
    result = governor.reserve_budget(home, "s1", "t1", tokens=1)
    assert result["reserved"] is False
    assert result["cap"] == 0
    assert result["reason"] == "BUDGET_EXHAUSTED"
    # Nothing was written for a refused zero-cap reservation.
    assert governor.list_budget_reservations(home, "s1") == []


def test_a_new_session_in_the_episode_charges_the_root_book(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    assert governor.reserve_budget(home, "root-session", "root-task", tokens=80)["reserved"]

    _episode_session(home, "root-session")
    _child_session(home, "root-session", "child-session")

    # The child resolves the same root episode, so the root's 80 is already spoken for.
    assert governor._episode_host_sessions(home, "child-session") == {
        "root-session",
        "child-session",
    }
    over = governor.reserve_budget(home, "child-session", "child-task", tokens=80)
    assert over["reserved"] is False
    assert over["outstanding"] == 80

    # What the episode has left is claimable from either side of it, exactly once.
    assert governor.reserve_budget(home, "child-session", "child-task", tokens=20)["reserved"]
    over_cap = governor.reserve_budget(home, "root-session", "root-task-2", tokens=1)
    assert over_cap["reserved"] is False
    assert [
        row["task_id"] for row in governor.list_budget_reservations(home, "child-session")
    ] == ["root-task", "child-task"]


def test_a_declared_root_that_cannot_be_resolved_fails_closed(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    _child_session(home, "vanished-root", "child-session")
    _seed_usage(home, "child-session", 5)

    # The child claims a root whose own ledger and telemetry are gone. Its spend cannot be
    # bounded, so a dispatch from below is refused instead of booking a fresh cap.
    refused = governor.reserve_budget(home, "child-session", "child-task", tokens=10)
    assert refused["reserved"] is False
    assert refused["reason"] == "ACCOUNTING_UNAVAILABLE"
    assert governor.check_budget(home, "child-session", "worker")["used"] is None


def test_reconcile_cancels_only_when_no_attempt_exists(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    governor.reserve_budget(home, "s1", "never-admitted", tokens=50)
    outcome = governor.reconcile_budget_reservations(home, session_id="s1")
    assert outcome["cancelled"] == ["never-admitted"], outcome
    row = _open_reservation(home, "s1", "never-admitted")
    assert row["cancel_reason"] == "NO_ATTEMPT_RECORDED"
    assert row["resolution"] == "cancelled_unused"


@pytest.mark.parametrize("bound", [True, False])
def test_reconcile_distinguishes_observed_dispatch_from_uncertainty(
    tmp_path: Path, bound: bool
) -> None:
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


# ---------------------------------------------------------------------------
# One book for admission and every reader
#
# The reader question must be the admission question: episode-scoped spend plus episode-scoped
# open reservation liability, with unknown usage reported as unknown instead of as zero. A reader
# that answered for one session, or for the whole home's history, would tell a different story
# than the reservation that just refused a dispatch.
# ---------------------------------------------------------------------------


def test_readers_resolve_one_episode_book_for_root_and_descendants(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    _episode_session(home, "root")
    _child_session(home, "root", "child")
    _seed_usage(home, "root", 30)
    _seed_usage(home, "child", 20)

    # The child's claim is charged to the root episode, which has 50 spent.
    granted = governor.reserve_budget(home, "child", "child-task", tokens=50)
    assert granted["reserved"] is True
    assert granted["used"] == 50

    # Both sessions of the episode resolve the same numbers, from either side.
    for session in ("root", "child"):
        view = governor.check_budget(home, session, "worker")
        assert view == {
            "state": "OK",
            "used": 50,
            "cap": 100,
            "outstanding": 50,
            "available": 0,
        }, (session, view)

    # What the reader calls available is exactly what admission refuses: nothing is left.
    refused = governor.reserve_budget(home, "root", "one-over", tokens=1)
    assert refused["reserved"] is False
    assert refused["outstanding"] == 50

    # Returning the unused claim restores the episode's capacity once, for both readers.
    governor.cancel_budget_reservation(
        home, "child", "child-task", "unused", evidence="proven_unused"
    )
    restored = governor.check_budget(home, "root", "worker")
    assert restored["outstanding"] == 0
    assert restored["available"] == 50


def test_a_fresh_unrelated_episode_does_not_inherit_another_episodes_consumption(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path, worker_tokens=100)
    _seed_usage(home, "episode-e", 60)
    assert governor.reserve_budget(home, "episode-e", "e-task", tokens=40)["reserved"] is True

    _seed_usage(home, "episode-f", 5)
    assert governor.check_budget(home, "episode-f", "worker") == {
        "state": "OK",
        "used": 5,
        "cap": 100,
        "outstanding": 0,
        "available": 95,
    }
    # E is unaffected by F's view, and F by E's.
    assert governor.check_budget(home, "episode-e", "worker")["outstanding"] == 40
    assert governor.list_budget_reservations(home, "episode-f") == []


def test_the_liability_excludes_cancelled_and_includes_unresolved(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    _seed_usage(home, "s1", 10)
    governor.reserve_budget(home, "s1", "cancelled", tokens=20)
    governor.reserve_budget(home, "s1", "unresolved", tokens=30)
    governor.cancel_budget_reservation(
        home, "s1", "cancelled", "PREPARATION_FAILED", evidence="proven_unused"
    )
    governor.mark_budget_reservation_unresolved(home, "s1", "unresolved", "DISPATCH_UNCERTAIN")

    view = governor.check_budget(home, "s1", "worker")
    assert view["outstanding"] == 30
    assert view["available"] == 60
    assert [row["task_id"] for row in governor.list_budget_reservations(home, "s1")] == [
        "unresolved"
    ]

    # The cancelled capacity really is free again, and the unresolved one really is not.
    assert governor.reserve_budget(home, "s1", "reuses-cancelled", tokens=60)["reserved"] is True
    assert governor.reserve_budget(home, "s1", "over-unresolved", tokens=1)["reserved"] is False


def test_a_consumed_reservation_is_not_charged_beside_the_usage_it_reconciled(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path, worker_tokens=100)
    assert governor.reserve_budget(home, "s1", "t1", tokens=40)["reserved"] is True
    assert governor.check_budget(home, "s1", "worker")["outstanding"] == 40

    # The attempt spends 25: consumption reconciles the actual usage once and releases the rest.
    governor.consume_budget_reservation(home, "s1", "t1", "usage", actual_tokens=25)
    _seed_usage(home, "s1", 25)

    assert governor.check_budget(home, "s1", "worker") == {
        "state": "OK",
        "used": 25,
        "cap": 100,
        "outstanding": 0,
        "available": 75,
    }


def test_a_duplicate_usage_observation_is_charged_once_in_the_view(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    # One billable response, observed twice. Charged twice, this reads HARD at 130 of 100.
    _seed_usage(home, "s1", 65, response_id="resp-duplicate")
    _seed_usage(home, "s1", 65, response_id="resp-duplicate", append=True)

    view = governor.check_budget(home, "s1", "worker")
    assert view["used"] == 65, "the same billable response must not be charged twice"
    assert view == {
        "state": "OK",
        "used": 65,
        "cap": 100,
        "outstanding": 0,
        "available": 35,
    }


def test_a_restart_resolves_the_same_totals(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    _seed_usage(home, "s1", 30)
    assert governor.reserve_budget(home, "s1", "t1", tokens=40)["reserved"] is True
    in_process = governor.check_budget(home, "s1", "worker")

    # A separate process, the real CLI, over the same durable state.
    assert _cli(home, "check-budget", "--session", "s1", "--role", "worker") == in_process
    listed = _cli(home, "budget-reservations", "--session", "s1")
    assert [row["task_id"] for row in listed["reservations"]] == ["t1"]


def test_a_session_without_telemetry_is_unknown_to_the_reader_and_zero_to_admission(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path, worker_tokens=100)

    # The reader reports what it can prove: no recorded usage is unknown, not a factual zero.
    view = governor.check_budget(home, "fresh", "worker")
    assert view["used"] is None
    assert view["available"] is None
    assert view["error"] == "ACCOUNTING_UNAVAILABLE"

    # Admission still has to decide, and a session with no recorded history is a resolved zero:
    # reading absence as unknown here would refuse the first worker of every fresh session.
    granted = governor.reserve_budget(home, "fresh", "first-task", tokens=100)
    assert granted["reserved"] is True
    assert granted["used"] == 0


def test_the_status_reader_does_not_create_the_reservation_ledger(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    dbfile = home / "db" / "brain.sqlite"
    assert not dbfile.exists()

    view = governor.check_budget(home, "s1", "worker")
    assert view["outstanding"] == 0
    assert not dbfile.exists(), "a status read must not create the reservation ledger"
