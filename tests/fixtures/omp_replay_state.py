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


def command_probe(args: argparse.Namespace) -> int:
    home = Path(args.base).resolve() / "home"
    with sqlite3.connect(db.db_path(home)) as conn:
        row = conn.execute(
            "SELECT state, writer_ownership, attempt_id, callback_token_sha256"
            " FROM worker_tasks WHERE task_id=?",
            (args.task_id,),
        ).fetchone()
        if row is None:
            return _emit({"ok": False, "error": "TASK_NOT_FOUND"}, 1)
        results = conn.execute(
            "SELECT COUNT(*) FROM worker_attempt_results WHERE task_id=?", (args.task_id,)
        ).fetchone()[0]
    digest = row[3]
    return _emit(
        {
            "ok": True,
            "state": row[0],
            "writer_ownership": row[1],
            "attempt_id": row[2],
            "attempt_results": int(results),
            "callback_digest_present": isinstance(digest, str) and len(digest) > 0,
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
    probe = subparsers.add_parser("probe")
    probe.add_argument("--base", required=True)
    probe.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            return command_setup(args)
        return command_probe(args)
    except FixtureError as error:
        return _emit({"ok": False, "error": error.code, "response": error.response}, 1)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
