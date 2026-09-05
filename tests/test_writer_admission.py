from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from second_brain import backup, contracts, db, omp_adapter, registry, worker_protocol


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "registered"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(
        root,
        "-c",
        "user.name=Writer Lease Test",
        "-c",
        "user.email=writer@example.invalid",
        "commit",
        "-qm",
        "initial",
    )
    _git(root, "branch", "side-worktree")
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "side-worktree")
    return root, side


def _payload(repo: Path, task_id: str, *, access_intent: str = "mutating") -> dict[str, object]:
    return {
        "operation": "worker_context",
        "host_session_id": f"session-{task_id}",
        "task_id": task_id,
        "task": "write a disposable marker",
        "scope": "repository",
        "constraints": [],
        "evidence_requirements": [],
        "completion_condition": "marker written",
        "context_refs": [],
        "project_id": "writer-project",
        "cwd": str(repo),
        "role": "driver",
        "provider": "test",
        "model": "test",
        "worker_role": "worker",
        "access_intent": access_intent,
    }


def _packet(repo: Path, task_id: str) -> contracts.WorkerTaskPacket:
    return contracts.WorkerTaskPacket(
        task_id=task_id,
        parent_session_id=f"session-{task_id}",
        driver_identity=contracts.AgentIdentity(
            agent_id=f"driver-{task_id}",
            internal_session_id=f"internal-{task_id}",
            host_agent_id="omp",
            parent_agent_id=None,
            role_profile="driver",
            model="test",
            provider="test",
            created_at="2026-09-05T00:00:00+00:00",
        ),
        requested_role="worker",
        objective="write a disposable marker",
        scope="repository",
        completion_condition="marker written",
        project_id="writer-project",
        repo_root=str(repo),
        access_intent="mutating",
    ).validate()


def _bind_payload(
    context: dict[str, object], *, generation: int = 1, job: str = "job-1"
) -> dict[str, object]:
    return {
        "operation": "worker_bind",
        "task_id": context["task_id"],
        "packet_sha256": context["packet_sha256"],
        "host_session_id": f"session-{context['task_id']}",
        "attempt_id": context["attempt_id"],
        "project_id": context["project_id"],
        "worktree_id": context["worktree_id"],
        "callback_token": context["callback_token"],
        "host_generation": generation,
        "native_attempt_id": f"native-{context['attempt_id']}",
        "native_job_id": job,
        "agent_id": f"agent-{context['task_id']}",
    }


def _lifecycle_payload(
    binding: dict[str, object],
    *,
    sequence: int,
    outcome: str | None,
    executor_settled: bool,
    cleanup_complete: bool,
) -> dict[str, object]:
    return {
        **binding,
        "operation": "worker_lifecycle",
        "sequence": sequence,
        "outcome": outcome,
        "executor_settled": executor_settled,
        "cleanup_complete": cleanup_complete,
    }


def _prepare(brain_home: Path, repo: Path, task_id: str) -> dict[str, object]:
    result = omp_adapter.handle_request(brain_home, _payload(repo, task_id))
    assert result["status"] == "prepared"
    return result


def _response_text(response: dict[str, object], field: str) -> str:
    value = response.get(field)
    assert isinstance(value, str)
    return value


def _bind(
    brain_home: Path,
    context: dict[str, object],
    *,
    generation: int = 1,
    job: str = "job-1",
) -> dict[str, object]:
    payload = _bind_payload(context, generation=generation, job=job)
    result = omp_adapter.handle_request(brain_home, payload)
    assert result["status"] == "accepted"
    return payload


def _register(brain_home: Path, repo: Path) -> None:
    registry.add_project(brain_home, repo, project_id="writer-project")


def test_access_intent_is_explicit_and_mutation_identity_fails_closed(brain_home, tmp_path) -> None:
    repo, _ = _repo(tmp_path)
    missing = _payload(repo, "missing-intent")
    missing.pop("access_intent")
    assert omp_adapter.handle_request(brain_home, missing) == {
        "status": "failed",
        "failure_code": "ACCESS_INTENT_REQUIRED",
    }

    read_only = omp_adapter.handle_request(
        brain_home, _payload(repo, "reader", access_intent="read_only")
    )
    assert read_only["status"] == "prepared"
    assert read_only["worktree_id"] is None
    assert "callback_token" not in read_only

    unknown_project = omp_adapter.handle_request(brain_home, _payload(repo, "unknown-project"))
    assert unknown_project["failure_code"] == "WORKTREE_IDENTITY_INVALID"
    _register(brain_home, repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    _git(outside, "init", "-q")
    stale = omp_adapter.handle_request(brain_home, _payload(outside, "outside-worktree"))
    assert stale["failure_code"] == "WORKTREE_IDENTITY_INVALID"


def test_real_git_worktrees_are_distinct_writer_resources(brain_home, tmp_path) -> None:
    root, side = _repo(tmp_path)
    _register(brain_home, root)

    first = _prepare(brain_home, root, "root-writer")
    blocked = omp_adapter.handle_request(brain_home, _payload(root, "root-writer-2"))
    side_writer = _prepare(brain_home, side, "side-writer")
    reader = omp_adapter.handle_request(
        brain_home, _payload(root, "root-reader", access_intent="read_only")
    )
    reader_two = omp_adapter.handle_request(
        brain_home, _payload(root, "root-reader-2", access_intent="read_only")
    )

    assert blocked["status"] == "failed"
    assert blocked["failure_code"] == "WORKTREE_WRITER_BUSY"
    assert first["worktree_id"] != side_writer["worktree_id"]
    assert reader["status"] == reader_two["status"] == "prepared"


def test_parallel_same_worktree_admission_has_one_winner(brain_home, tmp_path) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)

    def admit(task_id: str) -> str:
        try:
            return worker_protocol.admit_worker_attempt(
                brain_home, _packet(root, task_id)
            )["attempt_id"]
        except contracts.WorkerPacketError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(admit, ("parallel-a", "parallel-b")))
    assert sum(value.startswith("attempt-") for value in outcomes) == 1
    assert outcomes.count("WORKTREE_WRITER_BUSY") == 1


def test_exact_binding_and_monotonic_receipts_are_durable_and_idempotent(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "receipt-writer")
    binding = _bind(brain_home, context)

    duplicate_bind = omp_adapter.handle_request(brain_home, binding)
    assert duplicate_bind["status"] == "accepted"
    assert duplicate_bind["duplicate"] is True

    with sqlite3.connect(db.db_path(brain_home)) as conn:
        stored_token = conn.execute(
            "SELECT callback_token_sha256 FROM worker_tasks WHERE task_id=?",
            (context["task_id"],),
        ).fetchone()[0]
    assert stored_token != context["callback_token"]
    assert len(stored_token) == 64
    for field, value, code in (
        ("packet_sha256", "f" * 64, "BINDING_MISMATCH"),
        ("host_session_id", "wrong-session", "BINDING_MISMATCH"),
        ("worktree_id", "wrong-worktree", "BINDING_MISMATCH"),
        ("agent_id", "wrong-agent", "BINDING_MISMATCH"),
        ("native_job_id", "wrong-job", "BINDING_MISMATCH"),
        ("host_generation", 2, "BINDING_MISMATCH"),
        ("callback_token", "not-the-token", "UNAUTHORIZED_CALLBACK"),
    ):
        rejected = omp_adapter.handle_request(
            brain_home,
            _lifecycle_payload(
                {**binding, field: value},
                sequence=0,
                outcome=None,
                executor_settled=False,
                cleanup_complete=False,
            ),
        )
        assert rejected == {"status": "rejected", "failure_code": code}

    receipt = _lifecycle_payload(
        binding,
        sequence=0,
        outcome="cancelled",
        executor_settled=False,
        cleanup_complete=False,
    )
    accepted = omp_adapter.handle_request(brain_home, receipt)
    duplicate = omp_adapter.handle_request(brain_home, receipt)
    conflict = omp_adapter.handle_request(
        brain_home, {**receipt, "outcome": "failed"}
    )
    assert accepted["writer_ownership"] == "held"
    assert duplicate["duplicate"] is True
    assert conflict == {"status": "rejected", "failure_code": "RECEIPT_CONFLICT"}
    advanced = omp_adapter.handle_request(brain_home, {**receipt, "sequence": 2})
    stale = omp_adapter.handle_request(brain_home, {**receipt, "sequence": 1})
    assert advanced["status"] == "accepted"
    assert stale == {"status": "rejected", "failure_code": "STALE_RECEIPT"}

    with sqlite3.connect(db.db_path(brain_home)) as conn:
        row = conn.execute(
            "SELECT receipt_sha256 FROM worker_lifecycle_receipts "
            "WHERE attempt_id=? AND sequence=0",
            (context["attempt_id"],),
        ).fetchone()
    assert row is not None


def test_structured_task_outcome_never_releases_writer_without_cleanup(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "logical-result")
    _bind(brain_home, context)
    result = omp_adapter.handle_request(
        brain_home,
        {
            "operation": "worker_result",
            "host_session_id": "session-logical-result",
            "task_id": "logical-result",
            "attempt_id": context["attempt_id"],
            "packet_sha256": context["packet_sha256"],
            "status": "completed",
            "worker_agent": "agent-logical-result",
            "worker_model": "test",
            "worker_role": "worker",
            "summary": "logical work completed",
        },
    )
    assert result["status"] == "completed"
    persisted = worker_protocol.lookup_task(
        brain_home, "logical-result", _response_text(context, "packet_sha256")
    )
    assert persisted is not None
    assert persisted["logical_outcome"] == "completed"
    assert persisted["writer_ownership"] == "held"


def test_cancellation_does_not_release_until_exact_executor_cleanup(brain_home, tmp_path) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    first = _prepare(brain_home, root, "cancelled-writer")
    binding = _bind(brain_home, first, job="reused-job")

    cancelled = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=0,
            outcome="cancelled",
            executor_settled=False,
            cleanup_complete=False,
        ),
    )
    assert cancelled["logical_outcome"] == "cancelled"
    assert cancelled["writer_ownership"] == "held"
    assert omp_adapter.handle_request(
        brain_home, _payload(root, "blocked-after-cancel")
    )["failure_code"] == "WORKTREE_WRITER_BUSY"
    assert omp_adapter.handle_request(
        brain_home,
        _payload(root, "reader-during-cancel", access_intent="read_only"),
    )["status"] == "prepared"

    quarantined = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=1,
            outcome="cancelled",
            executor_settled=True,
            cleanup_complete=False,
        ),
    )
    assert omp_adapter.handle_request(
        brain_home,
        _payload(root, "reader-during-quarantine", access_intent="read_only"),
    )["status"] == "prepared"
    assert quarantined["writer_ownership"] == "quarantined"
    released = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=2,
            outcome="cancelled",
            executor_settled=True,
            cleanup_complete=True,
        ),
    )
    assert released["writer_ownership"] == "released"
    assert _prepare(brain_home, root, "writer-after-cleanup")["status"] == "prepared"


def test_retry_mints_new_attempt_and_old_or_reused_native_identity_cannot_release_it(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    first = _prepare(brain_home, root, "retry-task")
    old_binding = _bind(brain_home, first, generation=1, job="reused-job")
    completed = omp_adapter.handle_request(
        brain_home,
        {
            "operation": "worker_result",
            "host_session_id": "session-retry-task",
            "task_id": "retry-task",
            "attempt_id": first["attempt_id"],
            "packet_sha256": first["packet_sha256"],
            "status": "completed",
            "worker_agent": "agent-retry-task",
            "worker_model": "test",
            "worker_role": "worker",
            "summary": "first attempt completed",
        },
    )
    assert completed["status"] == "completed"
    finish = _lifecycle_payload(
        old_binding,
        sequence=0,
        outcome="completed",
        executor_settled=True,
        cleanup_complete=True,
    )
    assert omp_adapter.handle_request(brain_home, finish)["writer_ownership"] == "released"

    retry = _prepare(brain_home, root, "retry-task")
    assert retry["attempt_id"] != first["attempt_id"]
    with sqlite3.connect(db.db_path(brain_home)) as conn:
        receipt = conn.execute(
            "SELECT task_id FROM worker_attempt_results WHERE attempt_id=?",
            (first["attempt_id"],),
        ).fetchone()
    assert receipt == ("retry-task",)
    current_binding = _bind(brain_home, retry, generation=2, job="reused-job")
    late = omp_adapter.handle_request(brain_home, {**finish, "sequence": 1})
    assert late["status"] == "rejected"
    assert late["failure_code"] in {"BINDING_MISMATCH", "UNAUTHORIZED_CALLBACK"}
    current = worker_protocol.lookup_task(
        brain_home, "retry-task", _response_text(retry, "packet_sha256")
    )
    assert current is not None
    assert current["attempt_id"] == retry["attempt_id"]
    assert current["writer_ownership"] == "held"

    wrong_agent = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            {**current_binding, "agent_id": "old-agent"},
            sequence=0,
            outcome="completed",
            executor_settled=True,
            cleanup_complete=True,
        ),
    )
    assert wrong_agent["failure_code"] == "BINDING_MISMATCH"


def test_definitive_predispatch_failure_releases_only_with_durable_receipt(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "predispatch-failure")
    failure = {
        "operation": "worker_dispatch_failed",
        "task_id": context["task_id"],
        "packet_sha256": context["packet_sha256"],
        "host_session_id": "session-predispatch-failure",
        "attempt_id": context["attempt_id"],
        "project_id": context["project_id"],
        "worktree_id": context["worktree_id"],
        "callback_token": context["callback_token"],
        "failure_code": "HOST_PREFLIGHT_FAILED",
    }
    released = omp_adapter.handle_request(brain_home, failure)
    duplicate = omp_adapter.handle_request(brain_home, failure)
    assert released["status"] == "accepted"
    assert released["logical_outcome"] == "failed"
    assert released["writer_ownership"] == "released"
    assert duplicate["duplicate"] is True
    with sqlite3.connect(db.db_path(brain_home)) as conn:
        receipt = conn.execute(
            "SELECT failure_code FROM worker_dispatch_failures WHERE attempt_id=?",
            (context["attempt_id"],),
        ).fetchone()
    assert receipt is not None
    assert receipt[0] == "HOST_PREFLIGHT_FAILED"
    next_context = _prepare(brain_home, root, "after-predispatch-failure")
    next_attempt = worker_protocol.lookup_task(
        brain_home,
        _response_text(next_context, "task_id"),
        _response_text(next_context, "packet_sha256"),
    )
    assert next_attempt is not None
    assert next_attempt["writer_ownership"] == "held"


def test_reaper_quarantines_lost_authority_without_failure_or_redelivery(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "expired-writer")
    _bind(brain_home, context)

    reaped = worker_protocol.reap(
        brain_home, now=datetime.now(UTC) + timedelta(seconds=301)
    )
    assert reaped == [
        {
            "task_id": "expired-writer",
            "attempt_id": context["attempt_id"],
            "action": "quarantined",
            "state": "UNRESOLVED",
            "logical_outcome": "unresolved",
            "writer_ownership": "quarantined",
            "failure_reason": "authority_expired",
        }
    ]
    recovered = worker_protocol.lookup_task(
        brain_home, "expired-writer", _response_text(context, "packet_sha256")
    )
    assert recovered is not None
    assert recovered["logical_outcome"] == "unresolved"
    assert recovered["writer_ownership"] == "quarantined"
    assert omp_adapter.handle_request(
        brain_home, _payload(root, "blocked-by-quarantine")
    )["failure_code"] == "WORKTREE_WRITER_BUSY"


def test_lifecycle_persistence_failure_and_missing_settlement_fail_closed(
    brain_home, tmp_path, monkeypatch
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "disk-failure")
    binding = _bind(brain_home, context)
    lifecycle = _lifecycle_payload(
        binding,
        sequence=0,
        outcome="completed",
        executor_settled=True,
        cleanup_complete=True,
    )

    with sqlite3.connect(db.db_path(brain_home)) as conn:
        conn.execute(
            "CREATE TRIGGER reject_lifecycle BEFORE INSERT ON worker_lifecycle_receipts "
            "BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END"
        )
    rejected = omp_adapter.handle_request(brain_home, lifecycle)
    assert rejected == {
        "status": "rejected",
        "failure_code": "PERSISTENCE_UNAVAILABLE",
    }
    current = worker_protocol.lookup_task(
        brain_home, "disk-failure", _response_text(context, "packet_sha256")
    )
    assert current is not None
    assert current["writer_ownership"] == "held"

    missing = dict(lifecycle)
    missing.pop("executor_settled")
    assert omp_adapter.handle_request(brain_home, missing)["status"] == "rejected"

    monkeypatch.setattr(
        worker_protocol,
        "ingest_worker_lifecycle",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("adapter crash")),
    )
    assert omp_adapter.handle_request(brain_home, lifecycle)["status"] == "rejected"
    after_crash = worker_protocol.lookup_task(
        brain_home, "disk-failure", _response_text(context, "packet_sha256")
    )
    assert after_crash is not None
    assert after_crash["writer_ownership"] == "held"


def test_quarantine_survives_reopen_backup_and_restore(brain_home, tmp_path) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "durable-quarantine")
    binding = _bind(brain_home, context)
    active_snapshot = backup.create_backup(brain_home, note="active writer")
    active_home = tmp_path / "active-restored-brain"
    backup.restore_backup(active_home, active_snapshot)
    active = worker_protocol.lookup_task(
        active_home,
        "durable-quarantine",
        _response_text(context, "packet_sha256"),
    )
    assert active is not None
    assert active["writer_ownership"] == "held"
    interrupted = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=0,
            outcome="interrupted",
            executor_settled=False,
            cleanup_complete=False,
        ),
    )
    assert interrupted["writer_ownership"] == "quarantined"

    reopened = worker_protocol.lookup_task(
        brain_home,
        "durable-quarantine",
        _response_text(context, "packet_sha256"),
    )
    assert reopened is not None
    assert reopened["writer_ownership"] == "quarantined"

    snapshot = backup.create_backup(brain_home, note="writer quarantine")
    restored_home = tmp_path / "restored-brain"
    backup.restore_backup(restored_home, snapshot)
    restored = worker_protocol.lookup_task(
        restored_home,
        "durable-quarantine",
        _response_text(context, "packet_sha256"),
    )
    assert restored is not None
    assert restored["attempt_id"] == context["attempt_id"]
    assert restored["writer_ownership"] == "quarantined"


def test_migration_preserves_legacy_worker_rows_and_is_repeatable(tmp_path) -> None:
    dbfile = tmp_path / "legacy.sqlite"
    conn = db.connect(dbfile)
    try:
        conn.execute(
            "CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE worker_tasks(task_id TEXT PRIMARY KEY,state TEXT NOT NULL,"
            "lease_expires_at TEXT NOT NULL,packet_sha256 TEXT NOT NULL,accepted_at TEXT,"
            "settled_at TEXT,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE worker_task_meta(task_id TEXT PRIMARY KEY,redeliveries INTEGER "
            "NOT NULL DEFAULT 0,failure_reason TEXT,session_id TEXT,delivered_at TEXT,"
            "dispatch_payload TEXT,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE worker_task_results(task_id TEXT PRIMARY KEY REFERENCES "
            "worker_tasks(task_id),packet_sha256 TEXT NOT NULL,result_sha256 TEXT NOT NULL,"
            "payload_json TEXT NOT NULL,recorded_at TEXT NOT NULL)"
        )
        conn.execute("CREATE TABLE memories(id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE memory_sources(id TEXT PRIMARY KEY)")
        conn.execute(
            "INSERT INTO schema_version VALUES(22,'2026-09-05T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO worker_tasks VALUES('legacy','WORKING','2026-09-06',?,NULL,NULL,"
            "'2026-09-05')",
            ("a" * 64,),
        )
        conn.commit()
    finally:
        conn.close()

    assert db.migrate(dbfile) == [23]
    assert db.migrate(dbfile) == []
    with db.connect(dbfile) as migrated:
        row = migrated.execute(
            "SELECT task_id,attempt_id,writer_ownership FROM worker_tasks"
        ).fetchone()
        assert tuple(row) == ("legacy", None, None)


def _spawn_writer(target: Path, gate: Path, label: str) -> subprocess.Popen[str]:
    script = (
        "import pathlib,sys,time\n"
        "target=pathlib.Path(sys.argv[1]); gate=pathlib.Path(sys.argv[2]); label=sys.argv[3]\n"
        "with target.open('a', encoding='utf-8') as f:\n"
        " f.write(label+'-start\\n'); f.flush()\n"
        " while not gate.exists(): time.sleep(0.01)\n"
        " f.write(label+'-end\\n'); f.flush()\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return subprocess.Popen(
        [sys.executable, "-c", script, str(target), str(gate), label],
        env=env,
        text=True,
    )


def _wait_for_line(path: Path, line: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists() and line in path.read_text(encoding="utf-8").splitlines():
            return
        time.sleep(0.01)
    raise AssertionError(f"writer did not produce {line}")


def test_real_writer_process_cannot_overlap_after_logical_cancellation(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    target = root / "writer-order.txt"
    gate_one = tmp_path / "gate-one"
    gate_two = tmp_path / "gate-two"
    first = _prepare(brain_home, root, "real-first")
    first_binding = _bind(brain_home, first)
    process_one = _spawn_writer(target, gate_one, "one")
    process_two: subprocess.Popen[str] | None = None
    try:
        _wait_for_line(target, "one-start")
        cancelled = omp_adapter.handle_request(
            brain_home,
            _lifecycle_payload(
                first_binding,
                sequence=0,
                outcome="cancelled",
                executor_settled=False,
                cleanup_complete=False,
            ),
        )
        assert cancelled["writer_ownership"] == "held"
        assert process_one.poll() is None
        blocked = omp_adapter.handle_request(
            brain_home, _payload(root, "real-second")
        )
        assert blocked["failure_code"] == "WORKTREE_WRITER_BUSY"

        gate_one.touch()
        assert process_one.wait(timeout=10) == 0
        released = omp_adapter.handle_request(
            brain_home,
            _lifecycle_payload(
                first_binding,
                sequence=1,
                outcome="cancelled",
                executor_settled=True,
                cleanup_complete=True,
            ),
        )
        assert released["writer_ownership"] == "released"

        second = _prepare(brain_home, root, "real-second")
        _bind(brain_home, second, job="job-2")
        process_two = _spawn_writer(target, gate_two, "two")
        _wait_for_line(target, "two-start")
        gate_two.touch()
        assert process_two.wait(timeout=10) == 0
        assert target.read_text(encoding="utf-8").splitlines() == [
            "one-start",
            "one-end",
            "two-start",
            "two-end",
        ]
    finally:
        for process in (process_one, process_two):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def test_real_writers_can_run_in_parallel_in_distinct_git_worktrees(
    brain_home, tmp_path
) -> None:
    root, side = _repo(tmp_path)
    _register(brain_home, root)
    root_context = _prepare(brain_home, root, "concurrent-root")
    side_context = _prepare(brain_home, side, "concurrent-side")
    _bind(brain_home, root_context, job="root-job")
    _bind(brain_home, side_context, job="side-job")

    root_target = root / "root-writer.txt"
    side_target = side / "side-writer.txt"
    root_gate = tmp_path / "root-gate"
    side_gate = tmp_path / "side-gate"
    root_process = _spawn_writer(root_target, root_gate, "root")
    side_process = _spawn_writer(side_target, side_gate, "side")
    try:
        _wait_for_line(root_target, "root-start")
        _wait_for_line(side_target, "side-start")
        assert root_process.poll() is None
        assert side_process.poll() is None
        root_gate.touch()
        side_gate.touch()
        assert root_process.wait(timeout=10) == 0
        assert side_process.wait(timeout=10) == 0
    finally:
        for process in (root_process, side_process):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
