"""Offline Windows acceptance evidence; every child is owned and pipe-barrier driven."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.append(str(ROOT / ".venv" / "Lib" / "site-packages"))
from second_brain import db, omp_adapter, registry  # noqa: E402
from second_brain.errors import MigrationError  # noqa: E402
from test_writer_admission import (  # noqa: E402
    _bind_payload,
    _insert_protecting_attempt,
    _lifecycle_payload,
    _migrate_through_23,
    _payload,
    _repo,
)


def emit(value):
    print(json.dumps({"process_pid": os.getpid(), "value": value}), flush=True)


def snapshot(home):
    conn = db.connect(db.db_path(home))
    try:
        return {
            "version": db.current_version(conn),
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "owners": [
                dict(r) for r in conn.execute("SELECT * FROM worker_tasks ORDER BY task_id")
            ],
            "receipts": [
                {**dict(r), "payload": json.loads(r["payload_json"])}
                for r in conn.execute(
                    "SELECT attempt_id,sequence,receipt_sha256,payload_json "
                    "FROM worker_lifecycle_receipts ORDER BY attempt_id,sequence"
                )
            ],
            "indexes": [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND name LIKE 'idx_worker_tasks_writer_%'"
                )
            ],
            "schema": [
                dict(r)
                for r in conn.execute(
                    "SELECT type,name,sql FROM sqlite_master "
                    "WHERE tbl_name IN ('worker_tasks','worker_lifecycle_receipts') "
                    "ORDER BY type,name"
                )
            ],
        }
    finally:
        conn.close()


def child(mode, home):
    if mode == "writer":
        with (home / "owned-writer.txt").open("a", encoding="utf-8") as stream:
            stream.write("start\n")
            stream.flush()
            emit({"ready": True, "pid": os.getpid(), "cwd": str(home)})
            assert sys.stdin.readline().strip() == "release"
            stream.write("end\n")
            stream.flush()
        return
    if mode == "snapshot":
        emit(snapshot(home))
        return
    if mode == "migrate":
        emit({"applied": db.migrate(db.db_path(home)), "state": snapshot(home)})
        return
    if mode == "migration-refusal":
        original = db._execute_migration_statement
        statements = []

        def observe(conn, stmt, *, version):
            if version == 24:
                statements.append(stmt)
            return original(conn, stmt, version=version)

        db._execute_migration_statement = observe
        try:
            applied = db.migrate(db.db_path(home))
        except MigrationError as error:
            emit(
                {
                    "status": "refused",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "migration_24_statements": statements,
                }
            )
        else:
            emit({"status": "applied", "applied": applied, "migration_24_statements": statements})
        return
    if mode == "migration-crash":
        original = db._execute_migration_statement

        def execute(conn, stmt, *, version):
            original(conn, stmt, version=version)
            if version == 24:
                emit(
                    {
                        "barrier": "after-real-DDL-before-commit",
                        "in_transaction": conn.in_transaction,
                        "old_index_exists": conn.execute(
                            "SELECT count(*) FROM sqlite_master "
                            "WHERE name='idx_worker_tasks_writer_worktree'"
                        ).fetchone()[0],
                        "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
                        "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
                    }
                )
                sys.stdin.readline()

        db._execute_migration_statement = execute
        db.migrate(db.db_path(home))
        return
    request = json.loads(sys.stdin.readline())
    if mode == "receipt-crash":
        original_connect = db.connect

        class BarrierConnection:
            def __init__(self, conn):
                self.conn = conn

            def __getattr__(self, name):
                return getattr(self.conn, name)

            def execute(self, sql, *args):
                result = self.conn.execute(sql, *args)
                if sql.startswith("INSERT INTO worker_lifecycle_receipts"):
                    emit(
                        {
                            "barrier": "receipt-inserted-before-commit",
                            "in_transaction": self.conn.in_transaction,
                            "receipt_count_in_transaction": self.conn.execute(
                                "SELECT count(*) FROM worker_lifecycle_receipts"
                            ).fetchone()[0],
                        }
                    )
                    sys.stdin.readline()
                return result

        db.connect = lambda *args, **kwargs: BarrierConnection(original_connect(*args, **kwargs))
    response = omp_adapter.handle_request(home, request)
    # Never persist ephemeral callback capabilities in public evidence.
    emit(response)
    if mode == "after-commit-crash":
        sys.stdin.readline()


def run(output):
    assert os.name == "nt", "Windows gate requires Windows"
    output.mkdir(parents=True, exist_ok=False)
    fixture = Path(tempfile.mkdtemp(prefix="brain-eight-gates-"))
    events = []
    env = os.environ.copy()
    for key in list(env):
        if key in ("PYTHONHOME", "PYTHONPATH") or key.startswith("SECOND_BRAIN_"):
            env.pop(key)
    env["PYTHONPATH"] = str(ROOT / "src")
    executor = concurrent.futures.ThreadPoolExecutor()
    live = []

    def log(name, **data):
        events.append({"event": name, **data})
        (output / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    def command(mode, home):
        return [
            sys._base_executable,
            str(Path(__file__).resolve()),
            "--child",
            mode,
            "--home",
            str(home),
        ]

    def start(mode, home, request=None):
        p = subprocess.Popen(
            command(mode, home),
            cwd=home,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        live.append(p)
        log("spawn", command=command(mode, home), pid=p.pid, cwd=str(home))
        if request is not None:
            p.stdin.write(json.dumps(request) + "\n")
            p.stdin.flush()
        return p

    def line(p):
        text = executor.submit(p.stdout.readline).result(timeout=20)
        assert text, p.stderr.read()
        message = json.loads(text)
        assert message["process_pid"] == p.pid, message
        log("exact-process-barrier", pid=p.pid)
        return message["value"]

    def finish(p, kill=False):
        if kill:
            p.kill()
        code = p.wait(timeout=20)
        stderr = p.stderr.read()
        for stream in (p.stdin, p.stdout, p.stderr):
            stream.close()
        live.remove(p)
        log("exit", pid=p.pid, exit_code=code, killed=kill, stderr=stderr)
        if not kill:
            assert code == 0, stderr
        return code

    def fresh(mode, home, request=None):
        p = start(mode, home, request)
        value = line(p)
        finish(p)
        return value

    def adapter(home, request):
        return fresh("adapter", home, request)

    def preserve(name, home):
        dest = output / name
        dest.mkdir()
        for path in db.db_path(home).parent.glob("brain.sqlite*"):
            shutil.copy2(path, dest / path.name)
        log("recovery-files-preserved", path=str(dest), files=[p.name for p in dest.iterdir()])

    try:
        repo, side = _repo(fixture)
        home = fixture / "home"
        home.mkdir()
        db.migrate(db.db_path(home))
        registry.add_project(home, repo, project_id="writer-project")
        first = adapter(home, _payload(repo, "a03-holder"))
        binding = _bind_payload(first)
        assert adapter(home, binding)["status"] == "accepted"
        writer = start("writer", repo)
        writer_ready = line(writer)
        junction = fixture / "alias"
        linked = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(repo)],
            capture_output=True,
            text=True,
            check=True,
        )
        log("junction", exit_code=linked.returncode, stdout=linked.stdout)
        for label, cwd in (("case", Path(str(repo).swapcase())), ("junction", junction)):
            result = adapter(home, _payload(cwd, "a03-" + label))
            assert result.get("failure_code") == "WORKTREE_WRITER_BUSY", result
            log(
                "A03-alias-refused",
                alias=label,
                response=result,
                writer_pid=writer.pid,
                writer_alive=writer.poll() is None,
            )
        branch_cmd = ["git", "-C", str(repo), "switch", "-c", "acceptance-branch"]
        switched = subprocess.run(branch_cmd, capture_output=True, text=True, check=True)
        result = adapter(home, _payload(repo, "a03-branch"))
        assert result.get("failure_code") == "WORKTREE_WRITER_BUSY"
        identity = registry.resolve_registered_worktree(home, "writer-project", repo)
        assert identity.worktree_id == first["worktree_id"]
        log(
            "A03-branch-refused",
            command=branch_cmd,
            exit_code=switched.returncode,
            response=result,
            identity=identity.worktree_id,
        )
        outside = fixture / "unresolved"
        outside.mkdir()
        result = adapter(home, _payload(outside, "a03-unresolved"))
        assert result.get("failure_code") == "WORKTREE_IDENTITY_INVALID"
        log("A03-unresolved-refused", response=result)
        side_admission = adapter(home, _payload(side, "a03-distinct"))
        assert (
            side_admission["status"] == "prepared"
            and side_admission["worktree_id"] != first["worktree_id"]
        )
        second_writer = start("writer", side)
        second_ready = line(second_writer)
        assert writer.poll() is None and second_writer.poll() is None
        log(
            "A03-distinct-concurrent",
            first=writer_ready,
            second=second_ready,
            state=fresh("snapshot", home),
        )
        second_writer.stdin.write("release\n")
        second_writer.stdin.flush()
        finish(second_writer)
        os.rmdir(junction)
        # C06: durable cancellation survives adapter crash, writer remains alive.
        cancellation = _lifecycle_payload(
            binding, sequence=0, outcome="cancelled", executor_settled=False, cleanup_complete=False
        )
        crash = start("after-commit-crash", home, cancellation)
        accepted = line(crash)
        assert accepted["writer_ownership"] == "held"
        finish(crash, kill=True)
        preserve("C06-after-commit-crash", home)
        after = fresh("snapshot", home)
        assert after["receipts"][0]["payload"]["outcome"] == "cancelled"
        assert writer.poll() is None
        denied = adapter(home, _payload(repo, "c06-live-contender"))
        assert denied.get("failure_code") == "WORKTREE_WRITER_BUSY"
        log(
            "C06-fresh-restart-live-writer-protected",
            state=after,
            denial=denied,
            writer_pid=writer.pid,
        )
        writer.stdin.write("release\n")
        writer.stdin.flush()
        finish(writer)
        release = _lifecycle_payload(
            binding, sequence=1, outcome="cancelled", executor_settled=True, cleanup_complete=True
        )
        crash = start("receipt-crash", home, release)
        mutation = line(crash)
        assert mutation["in_transaction"]
        finish(crash, kill=True)
        preserve("C06-uncommitted-receipt-crash", home)
        rolled_back = fresh("snapshot", home)
        assert len(rolled_back["receipts"]) == 1
        assert (
            next(r for r in rolled_back["owners"] if r["task_id"] == "a03-holder")[
                "writer_ownership"
            ]
            == "held"
        )
        recovered = adapter(home, release)
        assert recovered["writer_ownership"] == "released"
        replay = adapter(home, release)
        assert replay["duplicate"]
        restarted = fresh("snapshot", home)
        assert len(restarted["receipts"]) == 2
        assert adapter(home, _payload(repo, "c06-after-release"))["status"] == "prepared"
        log(
            "C06-transaction-rollback-and-durable-release",
            barrier=mutation,
            rolled_back=rolled_back,
            recovered=restarted,
        )
        # A09: execute actual migration 24 DROP INDEX, crash before commit.
        migration_home = fixture / "migration"
        migration_home.mkdir()
        _migrate_through_23(db.db_path(migration_home), fixture / "migrations23")
        crash = start("migration-crash", migration_home)
        mutation = line(crash)
        assert mutation["in_transaction"] and mutation["old_index_exists"] == 0
        finish(crash, kill=True)
        preserve("A09-post-DDL-crash", migration_home)
        rolled_back = fresh("snapshot", migration_home)
        assert (
            rolled_back["version"] == 23
            and "idx_worker_tasks_writer_worktree" in rolled_back["indexes"]
        )
        upgraded = fresh("migrate", migration_home)
        repeated = fresh("migrate", migration_home)
        assert upgraded["applied"] == [24] and repeated["applied"] == []
        log(
            "A09-post-DDL-recovered",
            barrier=mutation,
            rollback=rolled_back,
            upgraded=upgraded,
            repeated=repeated,
        )
        # v23 fixtures retain historical attempt records, but use a registered
        # real physical resource. Admission cannot seed v23: it migrates first.
        protecting_cases = []
        for ownership in ("held", "quarantined"):
            protected_home = fixture / ownership
            protected_home.mkdir()
            _migrate_through_23(db.db_path(protected_home), fixture / (ownership + "-migrations23"))
            registry.add_project(protected_home, repo, project_id="writer-project")
            physical = registry.resolve_registered_worktree(protected_home, "writer-project", repo)
            with db.connect(db.db_path(protected_home)) as conn:
                _insert_protecting_attempt(
                    conn,
                    task_id=ownership,
                    project_id=physical.project_id,
                    worktree_id=physical.worktree_id,
                    worktree_root=physical.root,
                )
                conn.execute(
                    "UPDATE worker_tasks SET writer_ownership=?,state=? WHERE task_id=?",
                    (
                        ownership,
                        "UNRESOLVED" if ownership == "quarantined" else "SUBMITTED",
                        ownership,
                    ),
                )
            before = fresh("snapshot", protected_home)
            refusal = fresh("migration-refusal", protected_home)
            after = fresh("snapshot", protected_home)
            assert refusal["status"] == "refused", refusal
            assert "unresolved historical holders" in refusal["error"], refusal
            assert refusal["migration_24_statements"] == [], refusal
            assert before == after and after["version"] == 23
            denied = adapter(protected_home, _payload(repo, "a09-contender-" + ownership))
            assert denied.get("failure_code") == "WORKTREE_SAFETY_MIGRATION_REQUIRED", denied
            after_dispatch = fresh("snapshot", protected_home)
            assert after_dispatch == before
            preserve("A09-refused-" + ownership, protected_home)
            protecting_cases.append(
                {
                    "ownership": ownership,
                    "fixture_origin": "v23 historical row; registry-resolved physical identity",
                    "physical_resource": {
                        "worktree_id": physical.worktree_id,
                        "root": physical.root,
                    },
                    "migration": refusal,
                    "before": before,
                    "after": after,
                    "dispatch_denial": denied,
                    "after_dispatch": after_dispatch,
                    "status": "PASS_SUPPORTED_PRE_DDL_REFUSAL",
                    "populated_post_DDL_crash": "NOT_REACHED_BY_POLICY",
                }
            )
            log("A09-protecting-upgrade-refused", **protecting_cases[-1])
        # Current-schema startup is separately exercised with real production
        # admission, binding, and lifecycle transitions, not inserted test rows.
        startup_cases = []
        for ownership in ("held", "quarantined"):
            startup_home = fixture / ("startup-" + ownership)
            startup_home.mkdir()
            db.migrate(db.db_path(startup_home))
            registry.add_project(startup_home, repo, project_id="writer-project")
            admitted = adapter(startup_home, _payload(repo, "a09-production-" + ownership))
            assert admitted["status"] == "prepared", admitted
            native_binding = _bind_payload(admitted)
            assert adapter(startup_home, native_binding)["status"] == "accepted"
            if ownership == "quarantined":
                settled = adapter(
                    startup_home,
                    _lifecycle_payload(
                        native_binding,
                        sequence=0,
                        outcome="cancelled",
                        executor_settled=True,
                        cleanup_complete=False,
                    ),
                )
                assert settled["writer_ownership"] == "quarantined", settled
            before = fresh("snapshot", startup_home)
            assert before["owners"][0]["writer_ownership"] == ownership
            assert before["owners"][0]["attempt_id"] == admitted["attempt_id"]
            reopened = fresh("migrate", startup_home)
            assert reopened["applied"] == [] and reopened["state"] == before
            denied = adapter(startup_home, _payload(repo, "a09-restart-contender-" + ownership))
            assert denied.get("failure_code") == "WORKTREE_WRITER_BUSY", denied
            after = fresh("snapshot", startup_home)
            assert after == before
            startup_cases.append(
                {
                    "ownership": ownership,
                    "fixture_origin": "worker_context -> worker_bind -> worker_lifecycle "
                    + "(quarantine only)",
                    "before": before,
                    "reopened": reopened,
                    "dispatch_denial": denied,
                    "after": after,
                    "status": "PASS_CURRENT_SCHEMA_STARTUP_EXCLUSION",
                }
            )
            log("A09-production-protection-survives-startup", **startup_cases[-1])
        # E01: isolated Windows fixture, exact child identity and exit, immediate deletion.
        teardown = fixture / "owned-delete"
        teardown.mkdir()
        owned = start("writer", teardown)
        ready = line(owned)
        owned.stdin.write("release\n")
        owned.stdin.flush()
        exit_code = finish(owned)
        assert (teardown / "owned-writer.txt").read_text() == "start\nend\n"
        shutil.rmtree(teardown)
        assert not teardown.exists() and repo.exists() and side.exists()
        log(
            "E01-owned-windows-exit-deletion",
            ready=ready,
            exit_code=exit_code,
            directory=str(teardown),
            deleted=True,
            sibling_directories_retained=True,
        )
        log(
            "complete",
            fixture=str(fixture),
            production_source_changed=False,
            providers_used=0,
            A03="PASS_BRAIN_API",
            A09={
                "status": "PARTIAL_CONTRACT_CONFLICT",
                "clean_post_DDL_crash_recovery": "PASS",
                "protecting_upgrade": [
                    {"ownership": case["ownership"], "status": case["status"]}
                    for case in protecting_cases
                ],
                "production_startup": [
                    {"ownership": case["ownership"], "status": case["status"]}
                    for case in startup_cases
                ],
                "unexercised": "populated post-DDL crash: migration 24 refuses holders before DDL",
            },
            R04={
                "status": "NOT_EXERCISED_IN_BRAIN",
                "required_boundary": "host AgentSession -> TaskTool capability-provider/selection",
            },
            C06="PASS_BRAIN_ADAPTER",
            E01="PASS_PYTHON_FIXTURE_ONLY; exact native selection requires host evidence",
        )
    except BaseException as error:
        log(
            "failure", type=type(error).__name__, message=str(error), fixture_preserved=str(fixture)
        )
        raise
    finally:
        for p in live[:]:
            finish(p, kill=True)
        executor.shutdown(wait=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.home)
    else:
        run(args.output)
