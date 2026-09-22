from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from second_brain import backup, contracts, db, omp_adapter, registry, worker_protocol
from second_brain.errors import MigrationError


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


def _payload(
    repo: Path,
    task_id: str,
    *,
    access_intent: str = "mutating",
    project_id: str = "writer-project",
) -> dict[str, object]:
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
        "project_id": project_id,
        "cwd": str(repo),
        "role": "driver",
        "provider": "test",
        "model": "test",
        "worker_role": "worker",
        "access_intent": access_intent,
    }


def _packet(
    repo: Path, task_id: str, *, project_id: str = "writer-project"
) -> contracts.WorkerTaskPacket:
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
        project_id=project_id,
        repo_root=str(repo),
        access_intent="mutating",
    ).validate()


def _bind_payload(
    context: dict[str, object], *, generation: int = 1, job: str | None = "job-1"
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


def _register(brain_home: Path, repo: Path, *, project_id: str = "writer-project") -> None:
    registry.add_project(brain_home, repo, project_id=project_id)


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


def test_same_physical_worktree_across_project_labels_has_one_owner(
    brain_home: Path, tmp_path: Path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root, project_id="alpha")
    _register(brain_home, root, project_id="beta")

    alpha_identity = registry.resolve_registered_worktree(brain_home, "alpha", root)
    beta_identity = registry.resolve_registered_worktree(brain_home, "beta", root)
    assert alpha_identity.worktree_id == beta_identity.worktree_id
    assert alpha_identity.project_id == "alpha"
    assert beta_identity.project_id == "beta"

    first = omp_adapter.handle_request(
        brain_home, _payload(root, "alpha-writer", project_id="alpha")
    )
    blocked = omp_adapter.handle_request(
        brain_home, _payload(root, "beta-writer", project_id="beta")
    )
    assert first.get("status") == "prepared"
    assert blocked.get("status") == "failed"
    assert blocked.get("failure_code") == "WORKTREE_WRITER_BUSY"
    assert "callback_token" not in blocked
    with sqlite3.connect(db.db_path(brain_home)) as conn:
        owners = conn.execute(
            "SELECT task_id,project_id,worktree_id FROM worker_tasks "
            "WHERE access_intent='mutating' "
            "AND writer_ownership IN ('held','quarantined')"
        ).fetchall()
    assert owners == [
        ("alpha-writer", "alpha", alpha_identity.worktree_id),
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows path alias contract")
def test_windows_case_and_junction_aliases_share_worktree_identity(
    brain_home: Path, tmp_path: Path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root, project_id="alias-project")
    direct = registry.resolve_registered_worktree(brain_home, "alias-project", root)
    case_alias = Path(str(root).swapcase())
    junction = tmp_path / "registered-junction"
    linked = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(root)],
        capture_output=True,
        text=True,
    )
    if linked.returncode != 0:
        pytest.skip(f"junction creation unavailable: {linked.stderr.strip()}")
    try:
        case_identity = registry.resolve_registered_worktree(
            brain_home, "alias-project", case_alias
        )
        junction_identity = registry.resolve_registered_worktree(
            brain_home, "alias-project", junction
        )
    finally:
        os.rmdir(junction)

    assert case_identity.worktree_id == direct.worktree_id
    assert junction_identity.worktree_id == direct.worktree_id


def test_moved_worktree_and_path_replacement_fail_closed_while_owner_is_held(
    brain_home: Path, tmp_path: Path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root, project_id="alpha")
    first = omp_adapter.handle_request(
        brain_home, _payload(root, "alpha-before-move", project_id="alpha")
    )
    assert first.get("status") == "prepared"

    moved = tmp_path / "registered-moved"
    root.rename(moved)
    _register(brain_home, moved, project_id="beta")
    root.mkdir()
    _git(root, "init", "-q")
    _register(brain_home, root, project_id="replacement")

    replacement = omp_adapter.handle_request(
        brain_home,
        _payload(root, "replacement-writer", project_id="replacement"),
    )
    moved_request = omp_adapter.handle_request(
        brain_home, _payload(moved, "moved-writer", project_id="beta")
    )

    assert replacement.get("status") == "failed"
    assert replacement.get("failure_code") in {
        "WORKTREE_IDENTITY_AMBIGUOUS",
        "WORKTREE_WRITER_BUSY",
    }
    assert "callback_token" not in replacement
    assert moved_request.get("status") == "failed"
    assert moved_request.get("failure_code") in {
        "WORKTREE_IDENTITY_AMBIGUOUS",
        "WORKTREE_WRITER_BUSY",
    }
    assert "callback_token" not in moved_request


def test_branch_change_does_not_partition_writer_identity(brain_home, tmp_path) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    first = _prepare(brain_home, root, "branch-holder")
    before = registry.resolve_registered_worktree(brain_home, "writer-project", root)

    _git(root, "switch", "-c", "branch-identity-challenge")

    after = registry.resolve_registered_worktree(brain_home, "writer-project", root)
    contender = omp_adapter.handle_request(brain_home, _payload(root, "branch-contender"))

    assert before.worktree_id == after.worktree_id == first["worktree_id"]
    assert contender == {
        "status": "failed",
        "failure_code": "WORKTREE_WRITER_BUSY",
    }


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
            return worker_protocol.admit_worker_attempt(brain_home, _packet(root, task_id))[
                "attempt_id"
            ]
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
    conflict = omp_adapter.handle_request(brain_home, {**receipt, "outcome": "failed"})
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


def test_blocking_native_identity_with_null_job_id_binds_exactly_and_releases(
    brain_home: Path, tmp_path: Path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "blocking-writer")
    binding = _bind_payload(context, generation=7, job=None)

    missing_identity = omp_adapter.handle_request(
        brain_home, {**binding, "native_attempt_id": None}
    )
    assert missing_identity.get("status") == "rejected"
    assert missing_identity.get("failure_code") == "PROTOCOL_ERROR"

    accepted = omp_adapter.handle_request(brain_home, binding)
    duplicate = omp_adapter.handle_request(brain_home, binding)
    assert accepted.get("status") == "accepted"
    assert duplicate.get("status") == "accepted"
    assert duplicate.get("duplicate") is True

    dispatch_failure = omp_adapter.handle_request(
        brain_home,
        {**binding, "operation": "worker_dispatch_failed", "failure_code": "not-started"},
    )
    assert dispatch_failure.get("failure_code") == "INVALID_TRANSITION"
    for field, value, code in (
        ("packet_sha256", "f" * 64, "BINDING_MISMATCH"),
        ("host_session_id", "wrong-session", "BINDING_MISMATCH"),
        ("project_id", "wrong-project", "BINDING_MISMATCH"),
        ("worktree_id", "wrong-worktree", "BINDING_MISMATCH"),
        ("callback_token", "wrong-token", "UNAUTHORIZED_CALLBACK"),
        ("host_generation", 8, "BINDING_MISMATCH"),
        ("native_attempt_id", "second-native-launch", "BINDING_MISMATCH"),
        ("native_job_id", "fabricated-async-job", "BINDING_MISMATCH"),
        ("agent_id", "other-agent", "BINDING_MISMATCH"),
    ):
        rejected = omp_adapter.handle_request(brain_home, {**binding, field: value})
        assert rejected.get("status") == "rejected"
        assert rejected.get("failure_code") == code

    terminal = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=17,
            outcome="completed",
            executor_settled=True,
            cleanup_complete=True,
        ),
    )
    assert terminal.get("status") == "accepted"
    assert terminal.get("writer_ownership") == "released"
    assert terminal.get("lifecycle_sequence") == 17
    with sqlite3.connect(db.db_path(brain_home)) as conn:
        persisted_binding = conn.execute(
            "SELECT host_generation,native_attempt_id,native_job_id,agent_id "
            "FROM worker_tasks WHERE task_id='blocking-writer'"
        ).fetchone()
        receipt_json = conn.execute(
            "SELECT payload_json FROM worker_lifecycle_receipts WHERE attempt_id=? AND sequence=17",
            (context["attempt_id"],),
        ).fetchone()[0]
    assert persisted_binding == (
        7,
        f"native-{context['attempt_id']}",
        None,
        "agent-blocking-writer",
    )
    assert '"native_job_id":null' in receipt_json
    assert _prepare(brain_home, root, "writer-after-blocking")["status"] == "prepared"


def test_structured_task_outcome_never_releases_writer_without_cleanup(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "logical-result")
    binding = _bind(brain_home, context)
    result = omp_adapter.handle_request(
        brain_home,
        {
            "operation": "worker_result",
            "host_session_id": "session-logical-result",
            "task_id": "logical-result",
            "attempt_id": context["attempt_id"],
            "packet_sha256": context["packet_sha256"],
            "callback_token": context["callback_token"],
            "child_omp_agent_id": binding["agent_id"],
            "host_generation": binding["host_generation"],
            "native_attempt_id": binding["native_attempt_id"],
            "native_job_id": binding["native_job_id"],
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


def test_mutating_result_rejects_wrong_native_identity_without_poisoning_attempt(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "bound-result")
    binding = _bind(brain_home, context)
    payload = {
        "operation": "worker_result",
        "host_session_id": binding["host_session_id"],
        "task_id": context["task_id"],
        "attempt_id": context["attempt_id"],
        "packet_sha256": context["packet_sha256"],
        "callback_token": context["callback_token"],
        "child_omp_agent_id": binding["agent_id"],
        "host_generation": binding["host_generation"],
        "native_attempt_id": binding["native_attempt_id"],
        "native_job_id": binding["native_job_id"],
        "status": "completed",
        "worker_agent": "task",
        "worker_role": "worker",
        "summary": "Accepted work from the bound native child",
    }
    for field, wrong in {
        "child_omp_agent_id": "unrelated-child",
        "native_job_id": "unrelated-job",
        "native_attempt_id": "unrelated-attempt",
        "host_generation": 2,
    }.items():
        refused = omp_adapter.handle_request(brain_home, {**payload, field: wrong})
        assert refused["failure_code"] == "BINDING_MISMATCH", field
        assert "result_sha256" not in refused
    with db.connect(db.db_path(brain_home)) as conn:
        assert conn.execute(
            "SELECT state FROM worker_tasks WHERE task_id='bound-result'"
        ).fetchone()[0] == "WORKING"
        assert conn.execute("SELECT COUNT(*) FROM worker_attempt_results").fetchone()[0] == 0
    accepted = omp_adapter.handle_request(brain_home, payload)
    assert accepted["status"] == "completed"
    with db.connect(db.db_path(brain_home)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM worker_attempt_results").fetchone()[0] == 1


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
    assert (
        omp_adapter.handle_request(brain_home, _payload(root, "blocked-after-cancel"))[
            "failure_code"
        ]
        == "WORKTREE_WRITER_BUSY"
    )
    assert (
        omp_adapter.handle_request(
            brain_home,
            _payload(root, "reader-during-cancel", access_intent="read_only"),
        )["status"]
        == "prepared"
    )

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
    assert (
        omp_adapter.handle_request(
            brain_home,
            _payload(root, "reader-during-quarantine", access_intent="read_only"),
        )["status"]
        == "prepared"
    )
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


def test_accepted_terminal_outcome_cannot_be_rewritten_by_cleanup(brain_home, tmp_path) -> None:
    """Audit F-06: an accepted terminal outcome is immutable, so the host must
    never report a different one during cleanup.

    The core refuses a changed terminal outcome (OUTCOME_CONFLICT) and keeps the
    writer quarantined; the paired host-module regression proving that the host
    no longer produces that change lives in
    docs/integrations/omp-host-patch-2026-09-19/tests/attempt-settlement-outcome.test.ts.
    """
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "terminal-outcome")
    binding = _bind(brain_home, context)

    accepted = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=1,
            outcome="failed",
            executor_settled=True,
            cleanup_complete=False,
        ),
    )
    assert accepted["logical_outcome"] == "failed"
    assert accepted["writer_ownership"] == "quarantined"

    conflict = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=2,
            outcome="cancelled",
            executor_settled=True,
            cleanup_complete=True,
        ),
    )
    assert conflict["failure_code"] == "OUTCOME_CONFLICT"
    assert (
        omp_adapter.handle_request(brain_home, _payload(root, "blocked-after-conflict"))[
            "failure_code"
        ]
        == "WORKTREE_WRITER_BUSY"
    )

    # Settling with the accepted outcome still releases, which is the path the
    # repaired host produces.
    resolved = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            binding,
            sequence=2,
            outcome="failed",
            executor_settled=True,
            cleanup_complete=True,
        ),
    )
    assert resolved["writer_ownership"] == "released"
    assert _prepare(brain_home, root, "writer-after-terminal-cleanup")["status"] == "prepared"


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
            "callback_token": first["callback_token"],
            "child_omp_agent_id": old_binding["agent_id"],
            "host_generation": old_binding["host_generation"],
            "native_attempt_id": old_binding["native_attempt_id"],
            "native_job_id": old_binding["native_job_id"],
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


def test_readonly_predispatch_failure_is_owner_bound_and_durable(brain_home, tmp_path):
    payload = _payload(tmp_path, "readonly-preflight", access_intent="read_only")
    payload["task"] = "inspect a source file"
    context = omp_adapter.handle_request(brain_home, payload)
    failure = {
        "operation": "worker_dispatch_failed",
        "task_id": context["task_id"],
        "packet_sha256": context["packet_sha256"],
        "host_session_id": "session-readonly-preflight",
        "attempt_id": context["attempt_id"],
        "project_id": context["project_id"],
        "failure_code": "HOST_PREFLIGHT_REJECTED",
    }
    rejected = omp_adapter.handle_request(
        brain_home,
        {**failure, "host_session_id": "different-owner"},
    )
    assert rejected["status"] == "rejected"
    accepted = omp_adapter.handle_request(brain_home, failure)
    duplicate = omp_adapter.handle_request(brain_home, failure)
    assert accepted["status"] == "accepted"
    assert accepted["state"] == "FAILED"
    assert accepted["writer_ownership"] == "released"
    assert duplicate["duplicate"] is True
    with sqlite3.connect(db.db_path(brain_home)) as connection:
        row = connection.execute(
            "SELECT state,native_attempt_id,cleanup_complete FROM worker_tasks WHERE task_id=?",
            (context["task_id"],),
        ).fetchone()
        receipts = connection.execute(
            "SELECT COUNT(*) FROM worker_dispatch_failures WHERE attempt_id=?",
            (context["attempt_id"],),
        ).fetchone()[0]
    assert row == ("FAILED", None, 1)
    assert receipts == 1


def test_reaper_quarantines_lost_authority_without_failure_or_redelivery(
    brain_home, tmp_path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "expired-writer")
    _bind(brain_home, context)

    reaped = worker_protocol.reap(brain_home, now=datetime.now(UTC) + timedelta(seconds=301))
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
    assert (
        omp_adapter.handle_request(brain_home, _payload(root, "blocked-by-quarantine"))[
            "failure_code"
        ]
        == "WORKTREE_WRITER_BUSY"
    )


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
        conn.execute("INSERT INTO schema_version VALUES(22,'2026-09-05T00:00:00+00:00')")
        conn.execute(
            "INSERT INTO worker_tasks VALUES('legacy','COMPLETED','2026-09-06',?,NULL,NULL,"
            "'2026-09-05')",
            ("a" * 64,),
        )
        conn.commit()
    finally:
        conn.close()

    assert db.migrate(dbfile) == [23, 24]
    assert db.migrate(dbfile) == []
    with db.connect(dbfile) as migrated:
        row = migrated.execute(
            "SELECT task_id,attempt_id,writer_ownership FROM worker_tasks"
        ).fetchone()
        assert tuple(row) == ("legacy", None, None)


def _migrate_through_23(dbfile: Path, migrations_dir: Path) -> None:
    migrations_dir.mkdir()
    for path in db.migration_files():
        if int(path.name[:4]) <= 23:
            shutil.copy2(path, migrations_dir / path.name)
    applied = db.migrate(dbfile, migrations_dir=migrations_dir)
    assert applied and applied[-1] == 23


def _insert_protecting_attempt(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    project_id: str,
    worktree_id: str | None,
    worktree_root: str,
) -> None:
    conn.execute(
        "INSERT INTO worker_tasks("
        "task_id,state,lease_expires_at,packet_sha256,updated_at,attempt_id,"
        "access_intent,project_id,worktree_id,worktree_root,writer_ownership,"
        "host_session_id,callback_token_sha256,ownership_updated_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            task_id,
            contracts.WorkerLifecycle.SUBMITTED,
            "2026-09-06T00:00:00+00:00",
            "a" * 64,
            "2026-09-05T00:00:00+00:00",
            f"attempt-{task_id}",
            "mutating",
            project_id,
            worktree_id,
            worktree_root,
            "held",
            f"session-{task_id}",
            "b" * 64,
            "2026-09-05T00:00:00+00:00",
        ),
    )


def _physical_writer_index_columns(conn: sqlite3.Connection) -> list[str]:
    return [
        str(row[2])
        for row in conn.execute("PRAGMA index_info(idx_worker_tasks_writer_physical)").fetchall()
    ]


def test_physical_writer_migration_reopens_clean_backup_and_enforces_identity(
    tmp_path: Path,
) -> None:
    home = tmp_path / "clean-home"
    source = db.db_path(home)
    restored = tmp_path / "restored-v23.sqlite"
    root, _ = _repo(tmp_path)
    _migrate_through_23(source, tmp_path / "migrations-v23-clean")
    legacy_worktree_id = "c" * 64
    with db.connect(source) as conn:
        conn.execute(
            "INSERT INTO projects(id,name,repo_path,created_at) VALUES(?,?,?,?)",
            (
                "alpha",
                "alpha",
                str(root.resolve()),
                "2026-09-05T00:00:00+00:00",
            ),
        )
        _insert_protecting_attempt(
            conn,
            task_id="alpha-historical",
            project_id="alpha",
            worktree_id=legacy_worktree_id,
            worktree_root=str(root.resolve()),
        )
        conn.execute(
            "UPDATE worker_tasks SET state=?,writer_ownership='released' "
            "WHERE task_id='alpha-historical'",
            (contracts.WorkerLifecycle.COMPLETED,),
        )
    with sqlite3.connect(source) as source_conn, sqlite3.connect(restored) as restored_conn:
        source_conn.backup(restored_conn)

    assert db.migrate(source) == [24]
    expected_worktree_id = registry.resolve_registered_worktree(home, "alpha", root).worktree_id
    assert expected_worktree_id != legacy_worktree_id
    assert db.migrate(restored) == [24]
    for database in (source, restored):
        assert db.migrate(database) == []
        with db.connect(database) as conn:
            row = conn.execute(
                "SELECT task_id,project_id,worktree_id,writer_ownership "
                "FROM worker_tasks WHERE task_id='alpha-historical'"
            ).fetchone()
            assert tuple(row) == (
                "alpha-historical",
                "alpha",
                legacy_worktree_id,
                "released",
            )
            _insert_protecting_attempt(
                conn,
                task_id="alpha-held",
                project_id="alpha",
                worktree_id=expected_worktree_id,
                worktree_root=str(root.resolve()),
            )
            assert _physical_writer_index_columns(conn) == ["worktree_id"]
            with pytest.raises(sqlite3.IntegrityError):
                _insert_protecting_attempt(
                    conn,
                    task_id="beta-held",
                    project_id="beta",
                    worktree_id=expected_worktree_id,
                    worktree_root=str(root.resolve()),
                )
            for suffix, invalid in (("null", None), ("malformed", "not-a-physical-key")):
                with pytest.raises(sqlite3.IntegrityError, match="physical worktree identity"):
                    _insert_protecting_attempt(
                        conn,
                        task_id=f"invalid-{suffix}",
                        project_id="other-project",
                        worktree_id=invalid,
                        worktree_root=str(root.resolve()),
                    )
            conn.execute(
                "INSERT INTO worker_tasks("
                "task_id,state,lease_expires_at,packet_sha256,updated_at,attempt_id,"
                "access_intent,project_id,worktree_id,worktree_root,writer_ownership"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "upgrade-invalid",
                    contracts.WorkerLifecycle.SUBMITTED,
                    "2026-09-06T00:00:00+00:00",
                    "d" * 64,
                    "2026-09-05T00:00:00+00:00",
                    "attempt-upgrade-invalid",
                    "read_only",
                    "other-project",
                    None,
                    None,
                    "released",
                ),
            )
            with pytest.raises(sqlite3.IntegrityError, match="physical worktree identity"):
                conn.execute(
                    "UPDATE worker_tasks SET access_intent='mutating',"
                    "writer_ownership='held' WHERE task_id='upgrade-invalid'"
                )


def test_physical_writer_migration_refuses_conflicts_atomically_and_disables_dispatch(
    tmp_path: Path,
) -> None:
    home = tmp_path / "unsafe-home"
    dbfile = db.db_path(home)
    _migrate_through_23(dbfile, tmp_path / "migrations-v23-conflict")
    root, _ = _repo(tmp_path)
    with db.connect(dbfile) as conn:
        for project_id in ("alpha", "beta", "gamma"):
            conn.execute(
                "INSERT INTO projects(id,name,repo_path,created_at) VALUES(?,?,?,?)",
                (
                    project_id,
                    project_id,
                    str(root.resolve()),
                    "2026-09-05T00:00:00+00:00",
                ),
            )
    identity = registry.resolve_registered_worktree(home, "alpha", root)
    with db.connect(dbfile) as conn:
        _insert_protecting_attempt(
            conn,
            task_id="alpha-held",
            project_id="alpha",
            worktree_id=identity.worktree_id,
            worktree_root=identity.root,
        )
        _insert_protecting_attempt(
            conn,
            task_id="beta-quarantined",
            project_id="beta",
            worktree_id=identity.worktree_id,
            worktree_root=identity.root,
        )
        conn.execute(
            "UPDATE worker_tasks SET state=?,writer_ownership='quarantined' "
            "WHERE task_id='beta-quarantined'",
            (contracts.WorkerLifecycle.UNRESOLVED,),
        )
        before_rows = conn.execute(
            "SELECT task_id,state,project_id,worktree_id,writer_ownership "
            "FROM worker_tasks ORDER BY task_id"
        ).fetchall()
        old_index_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='idx_worker_tasks_writer_worktree'"
        ).fetchone()[0]

    with pytest.raises((sqlite3.IntegrityError, MigrationError), match="physical worktree"):
        db.migrate(dbfile)

    with db.connect(dbfile) as conn:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 23
        after_rows = conn.execute(
            "SELECT task_id,state,project_id,worktree_id,writer_ownership "
            "FROM worker_tasks ORDER BY task_id"
        ).fetchall()
        assert [tuple(row) for row in after_rows] == [tuple(row) for row in before_rows]
        assert (
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='idx_worker_tasks_writer_worktree'"
            ).fetchone()[0]
            == old_index_sql
        )
        assert _physical_writer_index_columns(conn) == []
    assert db.pending_migrations(dbfile) == [24]

    with pytest.raises(contracts.WorkerPacketError) as blocked:
        worker_protocol.admit_worker_attempt(
            home, _packet(root, "gamma-writer", project_id="gamma")
        )
    assert blocked.value.code == "WORKTREE_SAFETY_MIGRATION_REQUIRED"


@pytest.mark.parametrize("ownership", ["held", "quarantined", None])
def test_physical_writer_migration_refuses_single_unresolved_history(
    tmp_path: Path, ownership: str | None
) -> None:
    dbfile = tmp_path / "unresolved.sqlite"
    _migrate_through_23(dbfile, tmp_path / "migrations-v23-single")
    with db.connect(dbfile) as conn:
        _insert_protecting_attempt(
            conn,
            task_id="unresolved",
            project_id="missing-project",
            worktree_id=None,
            worktree_root=str(tmp_path / "missing-worktree"),
        )
        conn.execute(
            "UPDATE worker_tasks SET state='UNRESOLVED',writer_ownership=?,access_intent=?",
            (ownership, "mutating" if ownership else None),
        )
        before = tuple(conn.execute("SELECT * FROM worker_tasks").fetchone())
    for _ in range(2):
        with pytest.raises(MigrationError, match="physical worktree"):
            db.migrate(dbfile)
        with db.connect(dbfile) as conn:
            assert db.current_version(conn) == 23
            assert tuple(conn.execute("SELECT * FROM worker_tasks").fetchone()) == before
            assert _physical_writer_index_columns(conn) == []


def test_fresh_physical_writer_index_protects_quarantine_across_paths(
    brain_home: Path, tmp_path: Path
) -> None:
    with db.connect(db.db_path(brain_home)) as conn:
        _insert_protecting_attempt(
            conn,
            task_id="original",
            project_id="alpha",
            worktree_id="a" * 64,
            worktree_root=str(tmp_path / "original"),
        )
        conn.execute(
            "UPDATE worker_tasks SET state='UNRESOLVED',writer_ownership='quarantined' "
            "WHERE task_id='original'"
        )
    assert db.migrate(db.db_path(brain_home)) == []
    with db.connect(db.db_path(brain_home)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_protecting_attempt(
                conn,
                task_id="renamed",
                project_id="beta",
                worktree_id="a" * 64,
                worktree_root=str(tmp_path / "renamed"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_protecting_attempt(
                conn,
                task_id="replacement",
                project_id="gamma",
                worktree_id="b" * 64,
                worktree_root=str(tmp_path / "original"),
            )
        assert conn.execute("SELECT task_id FROM worker_tasks").fetchall()[0][0] == "original"


def test_concurrent_physical_writer_migration_applies_once(tmp_path: Path) -> None:
    dbfile = tmp_path / "concurrent.sqlite"
    _migrate_through_23(dbfile, tmp_path / "migrations-v23-concurrent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(db.migrate, (dbfile, dbfile)))
    assert sorted(results) == [[], [24]]
    with db.connect(dbfile) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_version WHERE version=24").fetchone()[0] == 1
        )
        assert _physical_writer_index_columns(conn) == ["worktree_id"]


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


def _spawn_admission(
    brain_home: Path,
    payload: dict[str, object],
    *,
    ready: Path,
    gate: Path,
    output: Path,
) -> subprocess.Popen[str]:
    script = (
        "import json,pathlib,sys,time\n"
        "from second_brain import omp_adapter\n"
        "home=pathlib.Path(sys.argv[1]); payload=json.loads(sys.argv[2])\n"
        "ready=pathlib.Path(sys.argv[3]); gate=pathlib.Path(sys.argv[4])\n"
        "output=pathlib.Path(sys.argv[5]); ready.write_text('ready\\n',encoding='utf-8')\n"
        "deadline=time.monotonic()+10\n"
        "while not gate.exists():\n"
        "  if time.monotonic()>=deadline: raise TimeoutError('admission gate')\n"
        "  time.sleep(0.005)\n"
        "result=omp_adapter.handle_request(home,payload)\n"
        "output.write_text(json.dumps(result),encoding='utf-8')\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(brain_home),
            json.dumps(payload),
            str(ready),
            str(gate),
            str(output),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_separate_process_project_alias_admission_is_atomic(
    brain_home: Path, tmp_path: Path
) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root, project_id="alpha")
    _register(brain_home, root, project_id="beta")
    gate = tmp_path / "admission-gate"
    processes: list[subprocess.Popen[str]] = []
    outputs: list[Path] = []
    try:
        for index, project_id in enumerate(("alpha", "beta")):
            ready = tmp_path / f"admission-{index}.ready"
            output = tmp_path / f"admission-{index}.json"
            outputs.append(output)
            processes.append(
                _spawn_admission(
                    brain_home,
                    _payload(
                        root,
                        f"process-{project_id}",
                        project_id=project_id,
                    ),
                    ready=ready,
                    gate=gate,
                    output=output,
                )
            )
            _wait_for_line(ready, "ready")
        gate.touch()
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, f"{stdout}\n{stderr}"
        results = [json.loads(path.read_text(encoding="utf-8")) for path in outputs]
        assert [result["status"] for result in results].count("prepared") == 1
        assert [result.get("failure_code") for result in results].count("WORKTREE_WRITER_BUSY") == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


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
        blocked = omp_adapter.handle_request(brain_home, _payload(root, "real-second"))
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


def test_real_writers_can_run_in_parallel_in_distinct_git_worktrees(brain_home, tmp_path) -> None:
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


# --- Completion authority (M00.3 #3) ---------------------------------------------------------
#
# Terminal lifecycle evidence is authority-bearing: it sets a task's terminal state and it writes
# the attempt result row that the strongest writer-release rule reads. These cases are the
# acceptance matrix for that guard. The negative cases assert protected state is unchanged, not
# merely that an error came back.


def _completion_payload(
    context: dict[str, object], binding: dict[str, object], *, token: object = ...
) -> dict[str, object]:
    payload = {
        "operation": "worker_result",
        "host_session_id": f"session-{context['task_id']}",
        "task_id": context["task_id"],
        "attempt_id": context["attempt_id"],
        "packet_sha256": context["packet_sha256"],
        "child_omp_agent_id": binding["agent_id"],
        "host_generation": binding["host_generation"],
        "native_attempt_id": binding["native_attempt_id"],
        "native_job_id": binding["native_job_id"],
        "status": "completed",
        "worker_agent": f"agent-{context['task_id']}",
        "worker_role": "worker",
        "summary": "authenticated completion",
    }
    if token is not ...:
        payload["callback_token"] = token
    return payload


def _terminal_evidence(brain_home: Path, task_id: str) -> tuple[object, int]:
    with sqlite3.connect(db.db_path(brain_home)) as conn:
        state = conn.execute(
            "SELECT state FROM worker_tasks WHERE task_id=?", (task_id,)
        ).fetchone()[0]
        receipts = conn.execute(
            "SELECT COUNT(*) FROM worker_attempt_results WHERE task_id=?", (task_id,)
        ).fetchone()[0]
    return state, int(receipts)


def _writer_ownership(brain_home: Path, task_id: str) -> object:
    with sqlite3.connect(db.db_path(brain_home)) as conn:
        return conn.execute(
            "SELECT writer_ownership FROM worker_tasks WHERE task_id=?", (task_id,)
        ).fetchone()[0]


def _terminal_evidence_for_attempt(brain_home: Path, attempt_id: object) -> int:
    with sqlite3.connect(db.db_path(brain_home)) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM worker_attempt_results WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()[0]
        )


def _working_task(brain_home: Path, tmp_path: Path, task_id: str) -> tuple[dict, dict]:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, task_id)
    binding = _bind(brain_home, context)
    return context, binding


def test_authenticated_terminal_event_is_accepted(brain_home, tmp_path) -> None:
    context, binding = _working_task(brain_home, tmp_path, "auth-ok")
    accepted = omp_adapter.handle_request(
        brain_home, _completion_payload(context, binding, token=context["callback_token"])
    )
    assert accepted["status"] == "completed"
    state, receipts = _terminal_evidence(brain_home, "auth-ok")
    assert state == "COMPLETED"
    assert receipts == 1


def test_terminal_event_without_token_is_refused_and_writes_no_evidence(
    brain_home, tmp_path
) -> None:
    context, binding = _working_task(brain_home, tmp_path, "auth-missing")
    before = _terminal_evidence(brain_home, "auth-missing")
    assert _writer_ownership(brain_home, "auth-missing") == "held"
    refused = omp_adapter.handle_request(brain_home, _completion_payload(context, binding))
    assert refused.get("failure_code") == "UNAUTHORIZED_CALLBACK"
    assert "result_sha256" not in refused
    assert _terminal_evidence(brain_home, "auth-missing") == before
    assert before == ("WORKING", 0)
    # A refused completion must not release the writer lease either: ownership is the effect the
    # strongest release rule protects, and an unauthenticated caller cannot give it up.
    assert _writer_ownership(brain_home, "auth-missing") == "held"


def test_terminal_event_with_wrong_token_is_refused_and_writes_no_evidence(
    brain_home, tmp_path
) -> None:
    context, binding = _working_task(brain_home, tmp_path, "auth-wrong")
    before = _terminal_evidence(brain_home, "auth-wrong")
    refused = omp_adapter.handle_request(
        brain_home, _completion_payload(context, binding, token="not-the-minted-token")
    )
    assert refused.get("failure_code") == "UNAUTHORIZED_CALLBACK"
    assert _terminal_evidence(brain_home, "auth-wrong") == before


def test_token_belonging_to_another_attempt_cannot_complete_the_current_one(
    brain_home, tmp_path
) -> None:
    """A genuinely valid token is still not authority for a different attempt."""
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    first = _prepare(brain_home, root, "auth-other-attempt")
    old_binding = _bind(brain_home, first)
    settled = omp_adapter.handle_request(
        brain_home, _completion_payload(first, old_binding, token=first["callback_token"])
    )
    assert settled["status"] == "completed"
    released = omp_adapter.handle_request(
        brain_home,
        _lifecycle_payload(
            old_binding,
            sequence=0,
            outcome="completed",
            executor_settled=True,
            cleanup_complete=True,
        ),
    )
    assert released["writer_ownership"] == "released"

    retry = _prepare(brain_home, root, "auth-other-attempt")
    assert retry["attempt_id"] != first["attempt_id"]
    foreign_token = first["callback_token"]
    assert isinstance(foreign_token, str) and foreign_token
    binding = _bind(brain_home, retry)
    before = _terminal_evidence_for_attempt(brain_home, retry["attempt_id"])
    refused = omp_adapter.handle_request(
        brain_home, _completion_payload(retry, binding, token=foreign_token)
    )
    assert refused.get("failure_code") in {"UNAUTHORIZED_CALLBACK", "STALE_ATTEMPT"}
    assert _terminal_evidence_for_attempt(brain_home, retry["attempt_id"]) == before
    assert before == 0


def test_duplicate_authenticated_terminal_event_is_idempotent(brain_home, tmp_path) -> None:
    context, binding = _working_task(brain_home, tmp_path, "auth-duplicate")
    payload = _completion_payload(context, binding, token=context["callback_token"])
    first = omp_adapter.handle_request(brain_home, payload)
    second = omp_adapter.handle_request(brain_home, payload)
    assert first["status"] == "completed"
    assert second["status"] == "completed"
    state, receipts = _terminal_evidence(brain_home, "auth-duplicate")
    assert (state, receipts) == ("COMPLETED", 1)


def test_non_terminal_transition_needs_no_completion_authority(brain_home, tmp_path) -> None:
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    context = _prepare(brain_home, root, "auth-telemetry")
    registration = worker_protocol.register_task(
        brain_home,
        "auth-telemetry-telemetry",
        _response_text(context, "packet_sha256"),
        session_id="s",
    )
    assert registration["state"] not in contracts.WorkerLifecycle.TERMINAL_STATES
    started = worker_protocol.record_worker_event(
        brain_home,
        "auth-telemetry-telemetry",
        _response_text(context, "packet_sha256"),
        "worker_started",
        host="omp",
    )
    assert started["state"] == "WORKING"


def test_protocol_invalid_terminal_transition_keeps_its_own_diagnostic(
    brain_home, tmp_path
) -> None:
    """The authority check guards the write, so it must not mask the state machine's
    more precise protocol error. A completion for a task with no ACCEPTED fact is a protocol
    fault whatever token accompanies it."""
    root, _ = _repo(tmp_path)
    _register(brain_home, root)
    # Prepared, never worked: no ACCEPTED fact exists, so completion is a protocol fault.
    context = _prepare(brain_home, root, "auth-protocol")
    assert _terminal_evidence(brain_home, "auth-protocol") == ("SUBMITTED", 0)
    # The canonical transition, reached with a wrong token AND an impossible completion.
    with pytest.raises(contracts.WorkerPacketError) as raised:
        worker_protocol.record_worker_event(
            brain_home,
            "auth-protocol",
            _response_text(context, "packet_sha256"),
            "completed",
            attempt_id=_response_text(context, "attempt_id"),
            callback_token="wrong",
        )
    assert raised.value.code == "PROTOCOL_ERROR"
    assert "ACCEPTED" in str(raised.value)
    # The refused transition left no protected mutation behind.
    assert _terminal_evidence(brain_home, "auth-protocol") == ("SUBMITTED", 0)
