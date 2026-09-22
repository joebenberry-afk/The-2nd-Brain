"""Reserve-before-dispatch: capacity is checked and reserved atomically.

The policy under test: a budget-consuming worker admission reserves budget *with* the
capacity check in one transaction; the reservation keeps its accounting until the worker
completes and cleans up; a refusal writes nothing, so it cannot release writer ownership.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import governor

REPO_ROOT = Path(__file__).resolve().parents[1]


def _home(tmp_path: Path, *, worker_tokens: int, soft_ratio: float = 0.8) -> Path:
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    (home / "config" / "governor.toml").write_text(
        f"[budgets]\nworker_tokens = {worker_tokens}\nsoft_ratio = {soft_ratio}\n",
        encoding="utf-8",
    )
    return home


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return env


def _cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "governor", *args, "--json"],
        capture_output=True,
        text=True,
        env={**_env(), "SECOND_BRAIN_HOME": str(home)},
        check=False,
    )


def test_zero_remaining_refuses_without_writing(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=10)

    first = governor.reserve_budget(home, "s1", "t1", tokens=10)
    assert first["reserved"] is True
    assert first["used"] == 0  # a fresh session is a resolved zero, not unaccountable

    # Nothing left: the second admission is refused and writes no reservation.
    second = governor.reserve_budget(home, "s1", "t2", tokens=10)
    assert second["reserved"] is False
    assert second["reason"] == "BUDGET_EXHAUSTED"
    assert second["outstanding"] == 10
    assert [row["task_id"] for row in governor.list_budget_reservations(home, "s1")] == ["t1"]


def test_concurrent_reservations_cannot_both_pass(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)

    def reserve(task: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [
                sys.executable, "-m", "second_brain", "governor", "reserve-budget",
                "--session", "s1", "--task-id", task, "--tokens", "80", "--json",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**_env(), "SECOND_BRAIN_HOME": str(home)},
        )

    left, right = reserve("a"), reserve("b")
    out_left, _ = left.communicate(timeout=60)
    out_right, _ = right.communicate(timeout=60)
    results = [json.loads(out_left), json.loads(out_right)]

    assert sum(1 for r in results if r["reserved"]) == 1, results
    assert sum(1 for r in results if not r["reserved"]) == 1, results
    assert len(governor.list_budget_reservations(home, "s1")) == 1


def test_reservation_survives_a_process_and_is_consumed_once(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)

    first = _cli(home, "reserve-budget", "--session", "s1", "--task-id", "t1", "--tokens", "60")
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout)["reserved"] is True

    # New process: the reservation is still accounted, exactly once.
    listed = _cli(home, "budget-reservations", "--session", "s1")
    rows = json.loads(listed.stdout)["reservations"]
    assert [row["task_id"] for row in rows] == ["t1"]

    again = _cli(home, "reserve-budget", "--session", "s1", "--task-id", "t1", "--tokens", "60")
    assert json.loads(again.stdout)["idempotent"] is True
    assert len(_rows(home)) == 1  # re-reserving the same task does not consume twice

    consumed = _cli(home, "consume-budget-reservation", "--session", "s1", "--task-id", "t1")
    assert json.loads(consumed.stdout) == {"consumed": True, "already_consumed": False}
    repeat = _cli(home, "consume-budget-reservation", "--session", "s1", "--task-id", "t1")
    assert json.loads(repeat.stdout) == {"consumed": False, "already_consumed": True}
    assert governor.list_budget_reservations(home, "s1") == []


def test_consumption_is_not_double_counted(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)

    assert governor.reserve_budget(home, "s1", "t1", tokens=60)["reserved"] is True
    assert governor.consume_budget_reservation(home, "s1", "t1")["consumed"] is True
    assert governor.consume_budget_reservation(home, "s1", "t1")["consumed"] is False

    # Freed capacity is real: another reservation of the same size still fits.
    second = governor.reserve_budget(home, "s1", "t2", tokens=60)
    assert second["reserved"] is True
    assert second["outstanding"] == 60


def test_refusal_exit_code_is_distinct(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=10)
    ok = _cli(home, "reserve-budget", "--session", "s1", "--task-id", "t1", "--tokens", "10")
    assert ok.returncode == 0, ok.stdout
    refused = _cli(home, "reserve-budget", "--session", "s1", "--task-id", "t2", "--tokens", "10")
    assert refused.returncode == 3, refused.stdout
    assert json.loads(refused.stdout)["reserved"] is False


def test_check_budget_behavior_is_unchanged(tmp_path: Path) -> None:
    home = _home(tmp_path, worker_tokens=100)
    result = governor.check_budget(home, "s1", "worker")
    assert set(result) >= {"state", "used", "cap"}
    assert result["cap"] == 100

    reservation = governor.reserve_budget(home, "s1", "t1", tokens=40)
    assert reservation["reserved"] is True
    # check-budget keeps its own contract: it reports spend, not reservations.
    after = governor.check_budget(home, "s1", "worker")
    assert after["state"] == "OK"
    assert after["cap"] == 100


def _rows(home: Path) -> list[dict[str, object]]:
    """All reservations including consumed ones, for idempotency accounting checks."""
    import sqlite3

    from second_brain import paths

    with sqlite3.connect(paths.db_path(home)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM budget_reservations")]


if __name__ == "__main__":  # pragma: no cover - manual smoke
    raise SystemExit(pytest.main([__file__, "-q"]))
