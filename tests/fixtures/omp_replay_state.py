"""Disposable Brain state for the OMP worker-completion replay test.

Two commands, exactly one JSON object on stdout:

    setup --base DIR --task-id ID --intent mutating|read_only
    probe --base DIR --task-id ID

`setup` builds a throwaway Brain home plus a registered git worktree, admits one worker attempt and
(for mutating) binds it, so the attempt holds the completion authority admission minted for it.
`probe` reports the protected durable state a replayed completion must not change.

This fixture deliberately contains no replay logic: the extension-leg replay is driven by
`brainstem/prime-extension/tests/worker-result-replay.test.ts`, which reads the values printed here
and runs the real bridge against this state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from second_brain import db, omp_adapter, paths, registry, worker_protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "replay-project"


class FixtureError(Exception):
    """A setup step refused; carries the code the caller asserts on."""

    def __init__(self, code: str, response: object = None) -> None:
        super().__init__(code)
        self.code = code
        self.response = response


def _emit(payload: dict, code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload) + "\n")
    return code


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def make_brain(home: Path) -> Path:
    """Mirror `tests/conftest.make_brain` without pytest's monkeypatch."""
    home.mkdir(parents=True, exist_ok=True)
    os.environ["SECOND_BRAIN_HOME"] = str(home)
    paths.ensure_layout(home)
    (home / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    cfg = home / "config"
    for name in paths.REQUIRED_CONFIG_FILES:
        (cfg / name).write_text("schema_version = 1\n", encoding="utf-8")
    shutil.copytree(REPO_ROOT / "templates", home / "templates", dirs_exist_ok=True)
    db.migrate(db.db_path(home))
    subprocess.run(["git", "init", "-q"], cwd=home, check=True, capture_output=True)
    return home


def make_repo(base: Path) -> Path:
    """Mirror `tests/test_writer_admission.py:_repo`: a commit plus a linked worktree."""
    root = base / "registered"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(
        root,
        "-c",
        "user.name=Replay Fixture",
        "-c",
        "user.email=replay@example.invalid",
        "commit",
        "-qm",
        "initial",
    )
    _git(root, "branch", "side-worktree")
    _git(root, "worktree", "add", "-q", str(base / "side"), "side-worktree")
    return root


def admit(home: Path, repo: Path, task_id: str, intent: str, host_session: str) -> dict:
    payload = {
        "operation": "worker_context",
        "host_session_id": host_session,
        "task_id": task_id,
        "task": "write a disposable marker",
        "scope": "repository",
        "constraints": [],
        "evidence_requirements": [],
        "completion_condition": "marker written",
        "context_refs": [],
        "project_id": PROJECT_ID,
        "cwd": str(repo),
        "role": "driver",
        "provider": "test",
        "model": "test",
        "worker_role": "worker",
        "access_intent": intent,
    }
    result = omp_adapter.handle_request(home, payload)
    if result.get("status") != "prepared":
        raise FixtureError("ADMISSION_FAILED", result)
    return result


def bind(home: Path, task_id: str, context: dict, host_session: str) -> dict:
    payload = {
        "operation": "worker_bind",
        "task_id": task_id,
        "packet_sha256": context["packet_sha256"],
        "host_session_id": host_session,
        "attempt_id": context["attempt_id"],
        "project_id": context["project_id"],
        "worktree_id": context["worktree_id"],
        "callback_token": context["callback_token"],
        "host_generation": 1,
        "native_attempt_id": f"native-{context['attempt_id']}",
        "native_job_id": "job-1",
        "agent_id": f"agent-{task_id}",
    }
    result = omp_adapter.handle_request(home, payload)
    if result.get("status") != "accepted":
        raise FixtureError("BIND_FAILED", result)
    return payload


def command_setup(args: argparse.Namespace) -> int:
    base = Path(args.base).resolve()
    home = base / "home"
    if home.exists() or (base / "registered").exists():
        raise FixtureError("BASE_NOT_EMPTY")
    base.mkdir(parents=True, exist_ok=True)
    make_brain(home)
    repo = make_repo(base)
    registry.add_project(home, repo, project_id=PROJECT_ID)
    context = admit(home, repo, args.task_id, args.intent, args.host_session)
    if args.intent == "mutating":
        binding = bind(home, args.task_id, context, args.host_session)
        agent_id = binding["agent_id"]
        host_generation: object = binding["host_generation"]
        native_attempt_id: object = binding["native_attempt_id"]
        native_job_id: object = binding["native_job_id"]
    else:
        # Read-only attempts have no writer binding; a real dispatch only records non-terminal
        # telemetry, which is what moves the attempt to WORKING.
        started = worker_protocol.record_worker_event(
            home,
            args.task_id,
            context["packet_sha256"],
            "worker_started",
            attempt_id=context["attempt_id"],
            host="omp",
        )
        if started.get("state") != "WORKING":
            raise FixtureError("START_FAILED", started)
        agent_id = f"agent-{args.task_id}"
        host_generation = 1
        native_attempt_id = f"native-{context['attempt_id']}"
        native_job_id = "job-1"
    record = {
        "task_id": args.task_id,
        "attempt_id": context["attempt_id"],
        "packet_sha256": context["packet_sha256"],
        "project_id": context["project_id"],
        "worktree_id": context["worktree_id"],
        "host_session_id": args.host_session,
        "agent_id": agent_id,
        "host_generation": host_generation,
        "native_attempt_id": native_attempt_id,
        "native_job_id": native_job_id,
        "callback_token": context.get("callback_token"),
    }
    (home / "replay-context.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return _emit(
        {
            "ok": True,
            "home": str(home),
            "repo": str(repo),
            "host_session_id": args.host_session,
            "task_id": args.task_id,
            "attempt_id": context["attempt_id"],
            "packet_sha256": context["packet_sha256"],
            "project_id": context["project_id"],
            "worktree_id": context["worktree_id"],
            "agent_id": agent_id,
            "host_generation": host_generation,
            "native_attempt_id": native_attempt_id,
            "native_job_id": native_job_id,
            "callback_token": context.get("callback_token"),
            "python": sys.executable,
            "second_brain_file": __import__("second_brain").__file__,
        }
    )


def command_accept(args: argparse.Namespace) -> int:
    """Complete the attempt with its own credential, so the outcome already exists."""
    home = Path(args.base).resolve() / "home"
    context = _stored_context(home, args.task_id)
    outcome = complete(home, args.task_id, context, token=context["callback_token"])
    return _emit({"ok": True, "task_id": args.task_id, "response": outcome})


def complete(
    home: Path, task_id: str, context: dict, *, token: str | None
) -> dict:
    """Send one completion exactly as the extension's bridge does, with or without authority."""
    payload = {
        "operation": "worker_result",
        "harness": "omp",
        "host_session_id": context["host_session_id"],
        "session_id": context["host_session_id"],
        "task_id": task_id,
        "packet_sha256": context["packet_sha256"],
        "attempt_id": context["attempt_id"],
        "status": "completed",
        "worker_agent": "worker",
        "worker_model": "",
        "worker_role": "",
        "summary": "replay",
        "child_omp_agent_id": context["agent_id"],
        "host_generation": context["host_generation"],
        "native_attempt_id": context["native_attempt_id"],
        "native_job_id": context["native_job_id"],
    }
    if token is not None:
        payload["callback_token"] = token
    return omp_adapter.handle_request(home, payload)


def _stored_context(home: Path, task_id: str) -> dict:
    """Read back the identity a previous `setup` recorded, so commands stay independent."""
    record = home / "replay-context.json"
    if not record.exists():
        raise FixtureError("CONTEXT_NOT_FOUND")
    stored = json.loads(record.read_text(encoding="utf-8"))
    if stored.get("task_id") != task_id:
        raise FixtureError("CONTEXT_TASK_MISMATCH")
    return stored


def _lifecycle_payload(context: dict, *, sequence: int) -> dict:
    return {
        "operation": "worker_lifecycle",
        "task_id": context["task_id"],
        "packet_sha256": context["packet_sha256"],
        "host_session_id": context["host_session_id"],
        "attempt_id": context["attempt_id"],
        "project_id": context["project_id"],
        "worktree_id": context["worktree_id"],
        "callback_token": context["callback_token"],
        "host_generation": context["host_generation"],
        "native_attempt_id": context["native_attempt_id"],
        "native_job_id": context["native_job_id"],
        "agent_id": context["agent_id"],
        "sequence": sequence,
        "outcome": "completed",
        "executor_settled": True,
        "cleanup_complete": True,
    }


def command_sequence(args: argparse.Namespace) -> int:
    """Run `count` sequential mutating workers on one disposable worktree.

    Each iteration admits, binds, completes and releases; the next iteration's admission is what
    proves the release took effect, because a mutating admission is refused while another attempt
    holds the worktree and the loop never waits for a lease to expire.
    """
    base = Path(args.base).resolve()
    home = base / "home"
    if home.exists() or (base / "registered").exists():
        raise FixtureError("BASE_NOT_EMPTY")
    base.mkdir(parents=True, exist_ok=True)
    make_brain(home)
    repo = make_repo(base)
    registry.add_project(home, repo, project_id=PROJECT_ID)
    iterations: list[dict] = []
    for index in range(1, args.count + 1):
        task_id = f"{args.task_id}-{index}"
        context = admit(home, repo, task_id, "mutating", args.host_session)
        binding = bind(home, task_id, context, args.host_session)
        enriched = {
            **context,
            "task_id": task_id,
            "host_session_id": args.host_session,
            "agent_id": binding["agent_id"],
            "host_generation": binding["host_generation"],
            "native_attempt_id": binding["native_attempt_id"],
            "native_job_id": binding["native_job_id"],
        }
        completion = complete(home, task_id, enriched, token=context["callback_token"])
        lifecycle = omp_adapter.handle_request(home, _lifecycle_payload(enriched, sequence=0))
        with sqlite3.connect(db.db_path(home)) as conn:
            state, ownership, results = _task_state(conn, task_id)
        iterations.append(
            {
                "index": index,
                "task_id": task_id,
                "completion_status": completion.get("status"),
                "completion_failure": completion.get("failure_code"),
                "lifecycle_status": lifecycle.get("status"),
                "state": state,
                "writer_ownership": ownership,
                "attempt_results": results,
            }
        )
    return _emit({"ok": True, "home": str(home), "repo": str(repo), "iterations": iterations})


def _task_row(conn: sqlite3.Connection, task_id: str):
    columns = (
        "state, writer_ownership, attempt_id, callback_token_sha256, logical_outcome,"
        " executor_settled, cleanup_complete, lease_expires_at, host_generation,"
        " native_attempt_id, native_job_id, agent_id, lifecycle_sequence"
    )
    return conn.execute(
        f"SELECT {columns} FROM worker_tasks WHERE task_id=?", (task_id,)
    ).fetchone()


def _task_state(conn: sqlite3.Connection, task_id: str) -> tuple[object, object, int]:
    row = _task_row(conn, task_id)
    if row is None:
        raise FixtureError("TASK_NOT_FOUND")
    results = conn.execute(
        "SELECT COUNT(*) FROM worker_attempt_results WHERE task_id=?", (task_id,)
    ).fetchone()[0]
    return row[0], row[1], int(results)


def command_edges(args: argparse.Namespace) -> int:
    """The ownership and receipt edges a settlement path must not get wrong.

    One attempt completes, then reports settlement *without* cleanup: ownership must quarantine and
    the next admission must be refused. Cleanup then completes, the successor is admitted, and the
    receipt rules are exercised (duplicate, conflicting, regressing). Finally the released attempt's
    own completion is replayed, which must change nothing.
    """
    base = Path(args.base).resolve()
    home = base / "home"
    if home.exists() or (base / "registered").exists():
        raise FixtureError("BASE_NOT_EMPTY")
    base.mkdir(parents=True, exist_ok=True)
    make_brain(home)
    repo = make_repo(base)
    registry.add_project(home, repo, project_id=PROJECT_ID)
    observations: dict[str, object] = {}

    def worker(task_id: str) -> dict:
        context = admit(home, repo, task_id, "mutating", args.host_session)
        binding = bind(home, task_id, context, args.host_session)
        return {
            **context,
            "task_id": task_id,
            "host_session_id": args.host_session,
            "agent_id": binding["agent_id"],
            "host_generation": binding["host_generation"],
            "native_attempt_id": binding["native_attempt_id"],
            "native_job_id": binding["native_job_id"],
        }

    def lifecycle(context: dict, *, sequence: int, settled: bool, cleanup: bool) -> dict:
        payload = _lifecycle_payload(context, sequence=sequence)
        payload["executor_settled"] = settled
        payload["cleanup_complete"] = cleanup
        return omp_adapter.handle_request(home, payload)

    def ownership(task_id: str) -> dict:
        with sqlite3.connect(db.db_path(home)) as conn:
            state, owner, results = _task_state(conn, task_id)
        return {"state": state, "writer_ownership": owner, "attempt_results": results}

    def admission(task_id: str) -> dict:
        payload = {
            "operation": "worker_context",
            "host_session_id": args.host_session,
            "task_id": task_id,
            "task": "disposable marker",
            "scope": "repository",
            "constraints": [],
            "evidence_requirements": [],
            "completion_condition": "marker written",
            "context_refs": [],
            "project_id": PROJECT_ID,
            "cwd": str(repo),
            "role": "driver",
            "provider": "test",
            "model": "test",
            "worker_role": "worker",
            "access_intent": "mutating",
        }
        return omp_adapter.handle_request(home, payload)

    first = worker("edge-a")
    observations["completion"] = complete(home, "edge-a", first, token=first["callback_token"])
    observations["settled_without_cleanup"] = lifecycle(
        first, sequence=0, settled=True, cleanup=False
    )
    observations["after_incomplete_cleanup"] = ownership("edge-a")
    observations["successor_while_quarantined"] = admission("edge-b")
    observations["cleanup_receipt"] = lifecycle(first, sequence=1, settled=True, cleanup=True)
    observations["after_cleanup"] = ownership("edge-a")
    successor = worker("edge-b")
    observations["successor_after_release"] = {"task_id": successor["task_id"]}
    observations["duplicate_receipt"] = lifecycle(first, sequence=1, settled=True, cleanup=True)
    observations["regressing_sequence"] = lifecycle(first, sequence=0, settled=True, cleanup=True)
    observations["replay_without_credential"] = complete(home, "edge-a", first, token=None)
    observations["replay_with_credential"] = complete(
        home, "edge-a", first, token=first["callback_token"]
    )
    observations["first_attempt_final"] = ownership("edge-a")
    observations["successor_final"] = ownership("edge-b")
    return _emit({"ok": True, "home": str(home), "repo": str(repo), **observations})


def command_probe(args: argparse.Namespace) -> int:
    home = Path(args.base).resolve() / "home"
    with sqlite3.connect(db.db_path(home)) as conn:
        row = _task_row(conn, args.task_id)
        if row is None:
            return _emit({"ok": False, "error": "TASK_NOT_FOUND"}, 1)
        receipt = conn.execute(
            "SELECT result_sha256 FROM worker_attempt_results WHERE task_id=?",
            (args.task_id,),
        ).fetchone()
        results = conn.execute(
            "SELECT COUNT(*) FROM worker_attempt_results WHERE task_id=?", (args.task_id,)
        ).fetchone()[0]
    (
        state, ownership, attempt_id, digest, logical_outcome, settled, cleanup, lease,
        host_generation, native_attempt_id, native_job_id, agent_id, sequence,
    ) = row
    return _emit(
        {
            "ok": True,
            "state": state,
            "writer_ownership": ownership,
            "attempt_id": attempt_id,
            "attempt_results": int(results),
            "result_sha256": receipt[0] if receipt is not None else None,
            "callback_digest_present": isinstance(digest, str) and len(digest) > 0,
            "callback_digest_sha256": hashlib.sha256(digest.encode("utf-8")).hexdigest()
            if isinstance(digest, str) and digest
            else None,
            "logical_outcome": logical_outcome,
            "executor_settled": int(settled or 0),
            "cleanup_complete": int(cleanup or 0),
            "lease_expires_at": lease,
            "host_generation": host_generation,
            "native_attempt_id": native_attempt_id,
            "native_job_id": native_job_id,
            "agent_id": agent_id,
            "lifecycle_sequence": int(sequence) if sequence is not None else None,
        }
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="omp_replay_state")
    subparsers = parser.add_subparsers(dest="command", required=True)
    setup = subparsers.add_parser("setup")
    setup.add_argument("--base", required=True)
    setup.add_argument("--task-id", required=True)
    setup.add_argument("--intent", required=True, choices=["mutating", "read_only"])
    # The host session that admitted the attempt; a completion only binds to the same one.
    setup.add_argument("--host-session", default="omp-session")
    edges = subparsers.add_parser("edges")
    edges.add_argument("--base", required=True)
    edges.add_argument("--task-id", required=True)
    edges.add_argument("--host-session", default="omp-session")
    sequence = subparsers.add_parser("sequence")
    sequence.add_argument("--base", required=True)
    sequence.add_argument("--task-id", required=True)
    sequence.add_argument("--count", type=int, default=10)
    sequence.add_argument("--host-session", default="omp-session")
    accept = subparsers.add_parser("accept")
    accept.add_argument("--base", required=True)
    accept.add_argument("--task-id", required=True)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--base", required=True)
    probe.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            return command_setup(args)
        if args.command == "accept":
            return command_accept(args)
        if args.command == "sequence":
            return command_sequence(args)
        if args.command == "edges":
            return command_edges(args)
        return command_probe(args)
    except FixtureError as error:
        return _emit({"ok": False, "error": error.code, "response": error.response}, 1)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
