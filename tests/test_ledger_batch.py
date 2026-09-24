"""LedgerBatch: `ledger append --batch` / `--init` + resilient batch append.

The batched mirror path exists so a host turn costs ONE Python spawn instead of
one spawn per mirrored event. Everything below exists to prove that the cheaper
path did not buy its speed by weakening the ledger:

- one transaction per batch, seq auto-assigned contiguously inside it;
- the envelope hash chain advances exactly as `append_events` defines it
  (`integrity()` recomputes every digest from the ledger's origin);
- ordering follows stdin order, not insertion luck;
- a rejected event is REPORTED and its siblings are still appended — including
  through the per-event fallback that a whole-batch rejection triggers — and a
  child whose parent was rejected is rejected too instead of landing as an
  orphan.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import contracts, ledger

HOST = "host-batch-session"
_STRIPPED_ENV = ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP")


def _event(index: int, *, event_type: str = "turn_end", **overrides) -> dict:
    event = {
        "event_id": f"e-{index}",
        "event_type": event_type,
        "timestamp": "2026-09-24T01:00:00Z",
        "surface_visibility": "raw_only",
        "ignorable": False,
        "payload": {"turn_index": index},
    }
    event.update(overrides)
    return event


class _Cli:
    """`python -m second_brain --home <tmp>` runner (one process per call)."""

    def __init__(self, home: Path) -> None:
        self.home = home
        env = dict(os.environ)
        for key in _STRIPPED_ENV:
            env.pop(key, None)
        # Bind the child to THIS candidate's source, exactly like
        # tests/conftest.py::clean_python_env: a shared venv can carry an
        # editable install pointing at another worktree, and then the CLI under
        # test would silently be different code than this repo.
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        self.env = env

    def run(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "second_brain", "--home", str(self.home), *args],
            capture_output=True,
            text=True,
            env=self.env,
            cwd=self.home,
            input=stdin,
            timeout=180,
        )

    def batch(self, lines: list[str], *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
        result = self.run(
            "ledger", "append", "--session", HOST, "--batch", *extra, stdin="\n".join(lines)
        )
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
        return result, payload

    def integrity(self) -> dict:
        result = self.run("ledger", "verify", HOST)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


def _init(cli: _Cli) -> None:
    result = cli.run("ledger", "init", "--session", HOST)
    assert result.returncode == 0, result.stderr


def _conn(store: ledger.LedgerStore) -> sqlite3.Connection:
    conn = store._conn
    assert conn is not None, "ledger store is not open"
    return conn


def _chain_is_sound(verify: dict, *, events: int) -> None:
    integrity = verify["integrity"]
    assert integrity["seq_contiguous"] is True
    assert integrity["hash_chain_ok"] is True
    assert integrity["hash_chain_break_seq"] is None
    assert integrity["orphan_parents"] == 0
    assert integrity["event_count"] == events
    assert integrity["hash_chain_verified_through_seq"] == events
    assert verify["replay_ok"] is True


def test_append_batch_one_process_appends_contiguous_chain(tmp_path) -> None:
    """20 events, ONE spawn (--init included), one transaction, sound chain."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0

    lines = [json.dumps(_event(i)) for i in range(1, 21)]
    # `--batch --init`: the ledger does not exist yet, so this single process
    # must create the session AND append the batch (no separate init spawn).
    result, payload = cli.batch(lines, "--init")

    assert result.returncode == 0, result.stderr
    assert payload["appended"] == list(range(1, 21))
    assert payload["errors"] == []
    assert (
        home / "state" / "sessions" / ledger.internal_session_id(HOST) / "ledger.sqlite"
    ).is_file()
    _chain_is_sound(cli.integrity(), events=20)

    # A second batch continues the same contiguous seq run (no reset, no gap).
    result, payload = cli.batch([json.dumps(_event(21)), json.dumps(_event(22))])
    assert result.returncode == 0, result.stderr
    assert payload["appended"] == [21, 22]
    _chain_is_sound(cli.integrity(), events=22)


def test_append_batch_reports_per_event_failures_without_dropping_the_rest(tmp_path) -> None:
    """A bad line, an unknown required type and an in-batch duplicate are reported;
    every other event still lands, in order, with an intact chain."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0
    _init(cli)
    result, payload = cli.batch([json.dumps(_event(1))])
    assert result.returncode == 0 and payload["appended"] == [1]

    lines = [
        json.dumps(_event(2)),  # ok
        "{not json",  # malformed line
        json.dumps(_event(2)),  # duplicate event_id (same batch)
        json.dumps(_event(3, event_type="mystery")),  # unknown + required -> rejected
        json.dumps(
            _event(4, event_type="mystery", ignorable=True)
        ),  # unknown + ignorable -> skipped
        json.dumps(_event(5)),  # ok
        json.dumps(_event(6)),  # ok
    ]
    result, payload = cli.batch(lines)

    assert result.returncode == 0, result.stderr
    assert payload["appended"] == [2, 3, 4]
    assert payload["skipped"] == 1
    # Every failure is attributed; none of them aborts the batch.
    assert [(e["line"], e["event_id"]) for e in payload["errors"]] == [
        (2, ""),
        (3, "e-2"),
        (4, "e-3"),
    ]
    assert "invalid JSON" in payload["errors"][0]["error"]
    assert "duplicate event_id" in payload["errors"][1]["error"]
    assert "unknown required event type" in payload["errors"][2]["error"]

    # Ordering followed stdin order (e-2 before e-5 before e-6).
    verify = cli.integrity()
    _chain_is_sound(verify, events=4)


def test_append_batch_path_that_hits_the_whole_batch_rejection_keeps_siblings(tmp_path) -> None:
    """A duplicate of an ALREADY PERSISTED event aborts the atomic attempt, so the
    per-event fallback must still append the siblings — and still in order."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0
    _init(cli)
    result, payload = cli.batch([json.dumps(_event(1)), json.dumps(_event(2))])
    assert result.returncode == 0 and payload["appended"] == [1, 2]

    lines = [
        json.dumps(_event(3)),
        json.dumps(_event(2)),  # already durable -> whole batch rejected
        json.dumps(_event(4, parent_event_id="e-3")),  # parent committed by the fallback
        json.dumps(_event(5)),
    ]
    result, payload = cli.batch(lines)

    assert result.returncode == 0, result.stderr
    assert payload["appended"] == [3, 4, 5]
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["event_id"] == "e-2"
    assert "duplicate event_id" in payload["errors"][0]["error"]
    _chain_is_sound(cli.integrity(), events=5)


def test_append_batch_child_of_a_rejected_event_is_rejected_not_orphaned(tmp_path) -> None:
    """A rejected parent must not leave a dangling child: the child is reported."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0
    _init(cli)

    lines = [
        json.dumps(_event(10, event_type="mystery")),  # rejected: unknown required type
        json.dumps(_event(11, parent_event_id="e-10")),  # parent never exists
        json.dumps(_event(12)),  # sibling still lands
    ]
    result, payload = cli.batch(lines)

    assert result.returncode == 0, result.stderr
    assert payload["appended"] == [1]
    errors = {e["event_id"]: e["error"] for e in payload["errors"]}
    assert set(errors) == {"e-10", "e-11"}
    assert "unknown required event type" in errors["e-10"]
    assert "invalid parent_event_id" in errors["e-11"]
    verify = cli.integrity()
    _chain_is_sound(verify, events=1)


def test_append_batch_explicit_seq_contiguity_violation_is_isolated(tmp_path) -> None:
    """Explicit seqs must stay contiguous with the ledger; a violating event is
    reported while the rest of the batch is appended in order."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0
    _init(cli)
    result, payload = cli.batch([json.dumps(_event(1))])
    assert payload["appended"] == [1]

    lines = [
        json.dumps(_event(2)),
        json.dumps(_event(3, seq=99)),  # contiguity violation
        json.dumps(_event(4)),
    ]
    result, payload = cli.batch(lines)

    assert result.returncode == 0, result.stderr
    assert payload["appended"] == [2, 3]
    assert [e["event_id"] for e in payload["errors"]] == ["e-3"]
    assert "contiguity" in payload["errors"][0]["error"]
    _chain_is_sound(cli.integrity(), events=3)


def test_append_batch_without_init_refuses_an_unknown_session(tmp_path) -> None:
    """Without --init the batched append keeps the historical contract: an
    uninitialized session is a hard error, never a silent partial ledger."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0

    result, _ = cli.batch([json.dumps(_event(1))])
    assert result.returncode == 2
    assert "ledger not initialized" in result.stderr
    assert not (home / "state" / "sessions" / ledger.internal_session_id(HOST)).exists()


def test_append_batch_file_is_the_same_path_as_stdin_and_is_consumed(tmp_path) -> None:
    """`--batch-file PATH` (the host's detached shutdown handoff: no stdin survives
    the parent) is a SOURCE for the identical batch path — same validation, same
    one-transaction append, same reporting — and a consumed handoff is removed so
    `state/tmp` does not accumulate one file per shutdown."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)

    handoff = home / "state" / "tmp" / "ledger-terminal-test.jsonl"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "\n".join(json.dumps(_event(i)) for i in range(1, 4)) + "\n", encoding="utf-8"
    )

    # `--batch-file` implies `--batch` (and `--init`, so this one process both
    # creates the session and appends its batch, exactly like a stdin flush).
    result = cli.run(
        "ledger", "append", "--session", HOST, "--init", "--host", "prime",
        "--batch-file", str(handoff),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"appended": [1, 2, 3], "errors": [], "skipped": 0}
    assert not handoff.exists(), "a consumed handoff file must be removed"
    _chain_is_sound(cli.integrity(), events=3)

    # The same stream continues through stdin: one batch path, not two.
    result, payload = cli.batch([json.dumps(_event(4))])
    assert result.returncode == 0, result.stderr
    assert payload["appended"] == [4]
    _chain_is_sound(cli.integrity(), events=4)


def test_append_batch_file_unreadable_fails_operationally_without_side_effects(
    tmp_path,
) -> None:
    """A handoff the child cannot read is an operational failure (non-zero), never
    an empty batch (exit 0 would settle the session's last events as handled) — and
    it must not create the session it could never fill."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    missing = home / "state" / "tmp" / "gone.jsonl"

    result = cli.run(
        "ledger", "append", "--session", HOST, "--batch", "--init",
        "--batch-file", str(missing),
    )

    assert result.returncode != 0
    assert "batch-file unreadable" in result.stderr
    assert not (home / "state" / "sessions" / ledger.internal_session_id(HOST)).exists()


def test_append_batch_init_is_idempotent_and_keeps_attribution(tmp_path) -> None:
    """--init on a live session preserves identity/parent and resolves the same
    project attribution the separate `ledger init` would (the two callers share
    _ledger_init_session)."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0
    parent = "host-parent"
    assert cli.run("ledger", "init", "--session", parent).returncode == 0

    result = cli.run(
        "ledger",
        "append",
        "--session",
        HOST,
        "--batch",
        "--init",
        "--parent-session",
        parent,
        stdin=json.dumps(_event(1)),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["appended"] == [1]

    # Same session, re-init with the same parent: identity preserved, no new row,
    # and the second batch still appends contiguously.
    result = cli.run(
        "ledger",
        "append",
        "--session",
        HOST,
        "--batch",
        "--init",
        "--parent-session",
        parent,
        stdin=json.dumps(_event(2)),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["appended"] == [2]

    with ledger.LedgerStore(home, HOST).open() as store:
        row = (
            _conn(store)
            .execute(
                "SELECT host_session_id, root_parent_session_id, internal_session_id FROM sessions"
            )
            .fetchone()
        )
        assert row["host_session_id"] == HOST
        assert row["root_parent_session_id"] == ledger.internal_session_id(parent)
    _chain_is_sound(cli.integrity(), events=2)


def test_append_batch_init_with_unowned_parent_writes_nothing(tmp_path) -> None:
    """`append --batch --init` resolves the parent BEFORE creating the ledger, so a
    rejected init leaves no half-created session behind (same rule as `ledger init`)."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0

    result, _ = cli.batch([json.dumps(_event(1))], "--init", "--parent-session", "missing-parent")
    assert result.returncode == 2
    assert "parent ledger not initialized" in result.stderr
    assert not (home / "state" / "sessions" / ledger.internal_session_id(HOST)).exists()


def test_append_batch_accepts_the_adapter_wire_format(tmp_path) -> None:
    """The EXACT argv + stdin the TypeScript mirror produces (ledger-mirror.ts
    `batchAppendArgs` / `spawnBatch`) must be accepted as-is: one JSON Lines
    batch, one JSON document on stdout, `--init` only on the first flush."""
    home = tmp_path / "brain"
    home.mkdir()
    cli = _Cli(home)
    assert cli.run("init").returncode == 0

    parent = "wire-parent"
    assert cli.run("ledger", "init", "--session", parent).returncode == 0

    def adapter_event(
        event_id: str, event_type: str = "turn_end", ignorable: bool = False, **payload
    ) -> str:
        # Field-for-field what buildMirrorEventJson() serializes. A kind the
        # ledger does not know travels as ignorable host bookkeeping (the
        # adapter's vocabulary bridge), so the caller sets that flag.
        return json.dumps(
            {
                "event_id": event_id,
                "agent_id": None,
                "parent_event_id": None,
                "event_type": event_type,
                "timestamp": "2026-09-24T03:00:00.000Z",
                "surface_visibility": "raw_only",
                "ignorable": ignorable,
                "payload": payload or {"turn_index": 0},
            }
        )

    first = cli.run(
        "ledger",
        "append",
        "--session",
        HOST,
        "--batch",
        "--init",
        "--host",
        "prime",
        "--parent-session",
        parent,
        "--cwd",
        str(home),
        stdin="\n".join(
            [
                adapter_event("wire-1", "session_started"),
                adapter_event("wire-2", "host_artifact_ref", ignorable=True, kind="telemetry"),
                adapter_event("wire-3", "turn_end", turn_index=0, tool_result_count=2),
            ]
        )
        + "\n",
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout.count("\n") == 1  # exactly one JSON document for JSON.parse
    assert json.loads(first.stdout) == {"appended": [1, 2], "errors": [], "skipped": 1}

    # A later flush of the same session omits --init (the adapter's cache says
    # initialized) and still appends contiguously.
    second = cli.run(
        "ledger",
        "append",
        "--session",
        HOST,
        "--batch",
        stdin=adapter_event("wire-4", "agent_ended", message_count=0) + "\n",
    )
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == {"appended": [3], "errors": [], "skipped": 0}
    with ledger.LedgerStore(home, HOST).open() as store:
        row = _conn(store).execute("SELECT root_parent_session_id FROM sessions").fetchone()
        assert row["root_parent_session_id"] == ledger.internal_session_id(parent)
    _chain_is_sound(cli.integrity(), events=3)


def test_append_events_resilient_batch_equals_single_appends(tmp_path) -> None:
    """Clean batch == N single appends in every observable way that matters:
    same seq run, same payloads, same chain verification."""
    home = tmp_path / "brain"
    home.mkdir()
    batched_session = "host-resilient-batch"
    single_session = "host-resilient-single"
    events = [
        contracts.BrainLifecycleEvent(
            seq=0,
            event_id=f"r-{i}",
            internal_session_id=ledger.internal_session_id(batched_session),
            agent_id="unknown",
            event_type=contracts.LifecycleEventType.TURN_END,
            timestamp="2026-09-24T01:00:00Z",
            surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
            ignorable=False,
            payload={"turn_index": i},
        )
        for i in range(1, 6)
    ]
    single_events = [
        contracts.BrainLifecycleEvent(
            seq=0,
            event_id=f"r-{i}",
            internal_session_id=ledger.internal_session_id(single_session),
            agent_id="unknown",
            event_type=contracts.LifecycleEventType.TURN_END,
            timestamp="2026-09-24T01:00:00Z",
            surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
            ignorable=False,
            payload={"turn_index": i},
        )
        for i in range(1, 6)
    ]

    with ledger.LedgerStore(home, batched_session, host="prime").open(create=True) as store:
        seqs, errors = ledger.append_events_resilient(store, events)
        assert seqs == [1, 2, 3, 4, 5]
        assert errors == []
        integrity = store.integrity()

    with ledger.LedgerStore(home, single_session, host="prime").open(create=True) as store:
        for event in single_events:
            store.append_events([event])
        single_integrity = store.integrity()

    assert integrity["seq_contiguous"] is True and single_integrity["seq_contiguous"] is True
    assert integrity["hash_chain_ok"] is True and single_integrity["hash_chain_ok"] is True
    assert integrity["event_count"] == single_integrity["event_count"] == 5
    assert integrity["hash_chain_verified_through_seq"] == 5


def test_append_events_resilient_reports_intra_batch_duplicate_from_sqlite(tmp_path) -> None:
    """Store-level: the CLI pre-dedupes, but a direct caller cannot lose the batch
    to UNIQUE(event_id) — the fallback isolates it and the chain stays sound."""
    home = tmp_path / "brain"
    home.mkdir()
    session = "host-resilient-dup"

    def event(event_id: str, index: int) -> contracts.BrainLifecycleEvent:
        return contracts.BrainLifecycleEvent(
            seq=0,
            event_id=event_id,
            internal_session_id=ledger.internal_session_id(session),
            agent_id="unknown",
            event_type=contracts.LifecycleEventType.TURN_END,
            timestamp="2026-09-24T01:00:00Z",
            surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
            ignorable=False,
            payload={"turn_index": index},
        )

    with ledger.LedgerStore(home, session, host="prime").open(create=True) as store:
        seqs, errors = ledger.append_events_resilient(
            store, [event("d-1", 1), event("d-2", 2), event("d-1", 3), event("d-3", 4)]
        )
        assert seqs == [1, 2, 3]
        assert [e["event_id"] for e in errors] == ["d-1"]
        assert "d-1" in errors[0]["error"]
        integrity = store.integrity()
        assert integrity["seq_contiguous"] is True
        assert integrity["hash_chain_ok"] is True
        rows = _conn(store).execute("SELECT event_id FROM events ORDER BY seq").fetchall()
        assert [r["event_id"] for r in rows] == ["d-1", "d-2", "d-3"]


def test_append_events_resilient_empty_batch_is_a_noop(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    with ledger.LedgerStore(home, "host-resilient-empty", host="prime").open(create=True) as store:
        assert ledger.append_events_resilient(store, []) == ([], [])
        assert store.integrity()["event_count"] == 0


def test_append_events_resilient_propagates_non_rejection_failures(tmp_path) -> None:
    """Internal defects must NOT be re-attributed to individual events."""
    home = tmp_path / "brain"
    home.mkdir()
    with ledger.LedgerStore(home, "host-resilient-defect", host="prime").open(create=True) as store:
        try:
            ledger.append_events_resilient(store, [object()])  # type: ignore[list-item]
        except AttributeError:
            pass
        else:  # pragma: no cover - the defect must surface
            raise AssertionError("a non-ledger failure must propagate")


def _resilient_event(session: str, event_id: str, index: int) -> contracts.BrainLifecycleEvent:
    return contracts.BrainLifecycleEvent(
        seq=0,
        event_id=event_id,
        internal_session_id=ledger.internal_session_id(session),
        agent_id="unknown",
        event_type=contracts.LifecycleEventType.TURN_END,
        timestamp="2026-09-24T01:00:00Z",
        surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
        ignorable=False,
        payload={"turn_index": index},
    )


def test_append_events_resilient_isolates_sqlite_integrity_rejections(
    tmp_path, monkeypatch
) -> None:
    """A constraint violation (UNIQUE/FK/CHECK) rejects ONE row deterministically,
    so it stays an event rejection: reported, siblings still appended."""
    home = tmp_path / "brain"
    home.mkdir()
    session = "host-resilient-integrity"
    events = [_resilient_event(session, f"i-{index}", index) for index in (1, 2, 3)]
    real = ledger.LedgerStore.append_events

    def reject_i2(self, batch):
        if any(event.event_id == "i-2" for event in batch):
            raise sqlite3.IntegrityError("UNIQUE constraint failed: events.event_id")
        return real(self, batch)

    monkeypatch.setattr(ledger.LedgerStore, "append_events", reject_i2)
    with ledger.LedgerStore(home, session, host="prime").open(create=True) as store:
        seqs, errors = ledger.append_events_resilient(store, events)
        assert seqs == [1, 2]
        assert [error["event_id"] for error in errors] == ["i-2"]
        assert "UNIQUE constraint failed" in errors[0]["error"]
        integrity = store.integrity()
        assert integrity["seq_contiguous"] is True
        assert integrity["hash_chain_ok"] is True


def test_append_events_resilient_propagates_operational_sqlite_failures(
    tmp_path, monkeypatch
) -> None:
    """busy/locked/disk I/O is a statement about the DATABASE, not about the
    events: it must fail the whole batch (no per-event rejections) so the host
    mirror's retry / deferred requeue path runs instead of settling."""
    home = tmp_path / "brain"
    home.mkdir()
    session = "host-resilient-operational"
    events = [_resilient_event(session, f"o-{index}", index) for index in (1, 2, 3)]

    def locked(self, batch):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger.LedgerStore, "append_events", locked)
    with (
        ledger.LedgerStore(home, session, host="prime").open(create=True) as store,
        pytest.raises(sqlite3.OperationalError, match="database is locked"),
    ):
        ledger.append_events_resilient(store, events)


def test_ledger_append_batch_operational_failure_exits_nonzero(
    tmp_path, monkeypatch, capsys
) -> None:
    """The mirror keys its retry/requeue off a non-zero exit (or a top-level CLI
    error), so an operational DB failure must NEVER be published as
    `{"errors": [...]}` with exit 0 — that would settle the events as handled."""
    from second_brain import cli

    home = tmp_path / "brain"
    home.mkdir()
    assert cli.main(["--home", str(home), "ledger", "init", "--session", HOST]) == 0
    capsys.readouterr()

    def locked(store, events):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger, "append_events_resilient", locked)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_event(1)) + "\n"))
    status = cli.main(["--home", str(home), "ledger", "append", "--session", HOST, "--batch"])
    captured = capsys.readouterr()
    assert status != 0
    assert "errors" not in captured.out
    assert "ledger append --batch failed: database is locked" in captured.err
