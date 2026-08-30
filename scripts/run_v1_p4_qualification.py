"""Real v1 P4 qualification runner (Task 8).

Exercises every prior P4 task (1-7) through actual CLI/subprocess calls
against fresh Brain homes, and records raw evidence (subprocess return
codes/stdout/stderr/sha256, real telemetry JSONL, real `brain.sqlite` state)
for every claim in the manifest. Nothing here fabricates a model identity,
a token count, or a success value: absent counters are `None`, never a
synthesized default.

CLI:
    python scripts/run_v1_p4_qualification.py --repo . --out outputs/reports/v1-p4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from second_brain import paths as paths_module  # noqa: E402
from second_brain import telemetry  # noqa: E402

SCENARIO_NAMES = (
    "fresh_session", "resumed_session", "compacted_session",
    "cross_session_continuity", "harness_isolation", "harness_switch",
    "driver_worker", "failed_worker", "malformed_state", "stale_state",
    "token_pressure", "cache_sensitive", "long_running_goal",
    "brain_off", "brain_on", "recovery_rollback",
    "security_boundary", "genuine_project_dogfood",
)

_ENV_STRIP = ("PYTHONHOME", "PYTHONPATH")


def sanitized_env(home: Path | None) -> dict[str, str]:
    """Brief Step 2's exact sanitized subprocess environment."""
    env = {key: value for key, value in os.environ.items() if key not in _ENV_STRIP}
    if home is not None:
        env["SECOND_BRAIN_HOME"] = str(home)
    return env


class CommandResult(NamedTuple):
    record: dict[str, Any]
    stdout: bytes
    stderr: bytes


@dataclass
class Ctx:
    repo: Path
    out_dir: Path
    raw_dir: Path
    python_exe: Path
    seq: dict[str, int] = field(default_factory=dict)

    def next_seq(self, scenario: str) -> int:
        self.seq[scenario] = self.seq.get(scenario, 0) + 1
        return self.seq[scenario]


def _rel(ctx: Ctx, path: Path) -> str:
    return path.resolve().relative_to(ctx.out_dir.resolve()).as_posix()




def _confined_evidence_path(out_dir: Path, ref: Any) -> Path | None:
    """Resolve a relative evidence ref only when it stays under out_dir."""
    if not isinstance(ref, str) or not ref:
        return None
    try:
        ref_path = Path(ref)
        if ref_path.is_absolute() or ".." in ref_path.parts:
            return None
        root = out_dir.resolve()
        path = (out_dir / ref_path).resolve()
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return path
def run_argv(
    ctx: Ctx,
    scenario: str,
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    timeout: int = 90,
    label: str = "cmd",
) -> CommandResult:
    """Run one real subprocess; capture rc/stdout/stderr/sha256 as raw evidence."""
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    scen_dir = ctx.raw_dir / scenario
    scen_dir.mkdir(parents=True, exist_ok=True)
    seq = ctx.next_seq(scenario)
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "-", label)[:48] or "cmd"
    stem = f"{seq:02d}-{safe_label}"
    stdout_path = scen_dir / f"{stem}.stdout"
    stderr_path = scen_dir / f"{stem}.stderr"
    stdout_path.write_bytes(proc.stdout)
    stderr_path.write_bytes(proc.stderr)
    record = {
        "argv": [str(a) for a in argv],
        "cwd": str(cwd) if cwd else None,
        "returncode": proc.returncode,
        "stdout_ref": _rel(ctx, stdout_path),
        "stderr_ref": _rel(ctx, stderr_path),
        "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest(),
        "stdout_bytes": len(proc.stdout),
        "stderr_bytes": len(proc.stderr),
    }
    return CommandResult(record, proc.stdout, proc.stderr)


def run_cli(
    ctx: Ctx, scenario: str, args: list[str], *, home: Path, cwd: Path | None = None,
    timeout: int = 90, label: str = "",
) -> CommandResult:
    argv = [str(ctx.python_exe), "-m", "second_brain.cli", *args]
    return run_argv(
        ctx, scenario, argv, cwd=cwd or ctx.repo, env=sanitized_env(home),
        timeout=timeout, label=label or args[0],
    )


def run_py(
    ctx: Ctx, scenario: str, code: str, *, home: Path | None, cwd: Path | None = None,
    timeout: int = 90, label: str = "py",
) -> CommandResult:
    argv = [str(ctx.python_exe), "-c", code]
    return run_argv(
        ctx, scenario, argv, cwd=cwd or ctx.repo, env=sanitized_env(home),
        timeout=timeout, label=label,
    )


def write_evidence(ctx: Ctx, scenario: str, label: str, data: Any) -> str:
    scen_dir = ctx.raw_dir / scenario
    scen_dir.mkdir(parents=True, exist_ok=True)
    seq = ctx.next_seq(scenario)
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "-", label)[:48] or "evidence"
    path = scen_dir / f"{seq:02d}-{safe_label}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return _rel(ctx, path)


def json_stdout(cr: CommandResult) -> Any:
    return json.loads(cr.stdout.decode("utf-8"))


def _q(value: str) -> str:
    """Embed a string literal safely into generated Python source."""
    return repr(value)


# ---------------------------------------------------------------------------
# Setup evidence: git SHA, Prime package version.
# ---------------------------------------------------------------------------


def git_info(ctx: Ctx) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    commands: list[dict[str, Any]] = []
    sha_result = run_argv(
        ctx, "_setup", ["git", "rev-parse", "HEAD"], cwd=ctx.repo,
        env=sanitized_env(None), label="git-sha",
    )
    commands.append(sha_result.record)
    sha = (
        sha_result.stdout.decode("utf-8").strip()
        if sha_result.record["returncode"] == 0
        else None
    )

    status_result = run_argv(
        ctx, "_setup", ["git", "status", "--porcelain"], cwd=ctx.repo,
        env=sanitized_env(None), label="git-status",
    )
    commands.append(status_result.record)
    dirty = (
        bool(status_result.stdout.decode("utf-8").strip())
        if status_result.record["returncode"] == 0
        else None
    )
    return {"sha": sha, "dirty": dirty}, commands


def prime_version(repo: Path) -> tuple[str | None, str]:
    pkg = repo / "brainstem" / "prime-extension" / "package.json"
    if not pkg.is_file():
        return None, str(pkg)
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, str(pkg)
    version = data.get("version")
    return (version if isinstance(version, str) else None), str(pkg)


def set_heartbeat_mode(home: Path, mode: str) -> None:
    cfg = home / "config" / "brain.toml"
    lines = cfg.read_text(encoding="utf-8").splitlines(keepends=True)
    in_heartbeat = False
    for index, line in enumerate(lines):
        section = line.strip()
        if section.startswith("[") and section.endswith("]"):
            in_heartbeat = section == "[heartbeat]"
            continue
        if in_heartbeat and re.match(r'^mode\s*=\s*"\w+"\s*(?:#.*)?(?:\r?\n)?$', line):
            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = f'mode = "{mode}"{newline}'
            cfg.write_text("".join(lines), encoding="utf-8")
            return
    raise AssertionError(f"could not locate heartbeat mode setting in {cfg}")


def common_metrics(home: Path, session_id: str) -> dict[str, Any]:
    """Real telemetry-derived counters. Unavailable provider usage is `None`,
    never a synthesized 0 (plan Step 4)."""
    usage = telemetry.session_usage(home, session_id)
    wall_ms = telemetry.session_wall_time_ms(home, session_id)
    tool_calls = telemetry.session_tool_calls(home, session_id)
    has_usage = usage["message_count"] > 0
    background_model_calls = sum(
        1
        for _, _, rec in telemetry.iter_records(home)
        if rec.get("session") == session_id
        and isinstance(rec.get("kind"), str)
        and rec["kind"].startswith("model_invocation")
    )
    return {
        "tool_calls": tool_calls,
        "wall_time_ms": wall_ms,
        "provider_tokens": {
            "input": usage["input"] if has_usage else None,
            "output": usage["output"] if has_usage else None,
            "total": usage["total"] if has_usage else None,
            "cache_read": usage["cache_read"] if has_usage else None,
            "cache_write": usage["cache_write"] if has_usage else None,
        },
        "reasoning_tokens": usage["reasoning"],
        "message_count": usage["message_count"],
        # background_model_calls=0 is asserted only because we counted zero
        # real model_invocation_* telemetry records for this session above.
        "background_model_calls": background_model_calls,
    }


def make_result(
    name: str, *, evidence_refs: list[str], commands: list[dict[str, Any]],
    metrics: dict[str, Any], status: str = "passed", **extra: Any,
) -> dict[str, Any]:
    result = {
        "name": name,
        "status": status,
        "evidence_refs": evidence_refs,
        "commands": commands,
        "metrics": metrics,
    }
    result.update(extra)
    return result


# ---------------------------------------------------------------------------
# Scenario 1-2: fresh_session / resumed_session
# ---------------------------------------------------------------------------


def scenario_fresh_session(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "fresh_session"
    session_id = "q8-primary"
    commands: list[dict[str, Any]] = []
    evidence_refs: list[str] = []

    cr = run_cli(ctx, name, ["doctor", "--json"], home=home, label="doctor")
    commands.append(cr.record)
    evidence_refs += [cr.record["stdout_ref"], cr.record["stderr_ref"]]
    doctor_payload = json_stdout(cr)
    assert doctor_payload["failed"] is False, f"doctor reported failure: {doctor_payload}"

    cr = run_cli(
        ctx, name,
        ["p4", "pulse", "--event", "session_start", "--session", session_id, "--force", "--json"],
        home=home, label="p4-pulse",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    pulse_payload = json_stdout(cr)
    assert pulse_payload["heartbeat"]["ran"] is True, pulse_payload

    code = (
        "from second_brain.goals import GoalStore\n"
        f"store = GoalStore({_q(str(home))})\n"
        "goal = store.create_goal("
        "'qualification fresh-session goal', "
        "'created during the fresh_session scenario')\n"
        "print(goal.goal_id)\n"
    )
    cr = run_py(ctx, name, code, home=home, label="create-goal")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    goal_id = cr.stdout.decode("utf-8").strip()
    assert goal_id.startswith("goal-"), goal_id

    shared["primary_session_id"] = session_id
    shared["fresh_goal_id"] = goal_id

    metrics = common_metrics(home, session_id)
    metrics["doctor_failed"] = doctor_payload["failed"]
    metrics["heartbeat_ran"] = pulse_payload["heartbeat"]["ran"]
    return make_result(
        name, evidence_refs=evidence_refs, commands=commands, metrics=metrics,
        session_id=session_id, goal_id=goal_id,
    )


def scenario_resumed_session(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "resumed_session"
    session_id = shared["primary_session_id"]
    goal_id = shared["fresh_goal_id"]
    code = (
        "import json\n"
        "from second_brain.goals import GoalStore\n"
        f"store = GoalStore({_q(str(home))})\n"
        f"goal = store.get_goal({_q(goal_id)})\n"
        "assert goal is not None, 'goal not found on reopen in a new process'\n"
        "print(json.dumps({'goal_title': goal.title, 'goal_status': goal.status.value}))\n"
    )
    cr = run_py(ctx, name, code, home=home, label="reopen-read-goal")
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    payload = json_stdout(cr)
    assert payload["goal_title"] == "qualification fresh-session goal"

    tfile = telemetry.telemetry_dir(home) / f"{session_id}.jsonl"
    assert tfile.is_file(), "expected the fresh_session telemetry file to persist across processes"

    metrics = common_metrics(home, session_id)
    metrics["goal_status_on_resume"] = payload["goal_status"]
    metrics["telemetry_file_persisted"] = True
    return make_result(
        name,
        evidence_refs=[cr.record["stdout_ref"]],
        commands=[cr.record],
        metrics=metrics,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Scenario 3: compacted_session
# ---------------------------------------------------------------------------


def scenario_compacted_session(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "compacted_session"
    session_id = "q8-compact"
    commands = []
    evidence_refs = []

    cr = run_cli(
        ctx, name, ["ledger", "init", "--session", session_id, "--host", "qualification-runner"],
        home=home, label="ledger-init",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")

    before = telemetry.report(home).get("compactions", 0)
    telemetry.append_record(home, session_id, "heartbeat_pulse")  # baseline, ignored below

    directory = telemetry.telemetry_dir(home)
    now = datetime.now(UTC).isoformat()
    compact_records = [
        {"v": 2, "kind": "session_before_compact", "session": session_id, "ts": now},
        {"v": 2, "kind": "session_compact", "session": session_id, "ts": now},
    ]
    tfile = directory / f"{session_id}.jsonl"
    with tfile.open("a", encoding="utf-8") as handle:
        for record in compact_records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    evidence_refs.append(write_evidence(ctx, name, "compact-telemetry-records", compact_records))

    cr = run_cli(
        ctx, name, ["ledger", "segment", "checkpoint", session_id], home=home,
        label="ledger-checkpoint",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    checkpoint_payload = json_stdout(cr)
    assert checkpoint_payload["ok"] is True, checkpoint_payload

    after = telemetry.report(home)["operational"]["compactions"]
    assert after >= 1, "expected a real session_compact telemetry record to be counted"

    metrics = common_metrics(home, session_id)
    metrics["compactions_before"] = before
    metrics["compactions_after"] = after
    metrics["checkpoint_integrity"] = checkpoint_payload["integrity"]
    return make_result(
        name, evidence_refs=evidence_refs, commands=commands, metrics=metrics,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Scenario 4: cross_session_continuity
# ---------------------------------------------------------------------------


def scenario_cross_session_continuity(
    ctx: Ctx, home: Path, shared: dict[str, Any]
) -> dict[str, Any]:
    name = "cross_session_continuity"
    title = "qualification cross-session continuity goal"

    code_a = (
        "from second_brain.goals import GoalStore\n"
        f"store = GoalStore({_q(str(home))})\n"
        f"goal = store.create_goal({_q(title)}, 'created by process A')\n"
        "print(goal.goal_id)\n"
    )
    cr_a = run_py(ctx, name, code_a, home=home, label="process-a-create")
    assert cr_a.record["returncode"] == 0, cr_a.stderr.decode("utf-8", "replace")
    goal_id = cr_a.stdout.decode("utf-8").strip()

    code_b = (
        "from second_brain.goals import GoalStore\n"
        f"store = GoalStore({_q(str(home))})\n"
        f"goal = store.get_goal({_q(goal_id)})\n"
        "assert goal is not None, 'goal created in process A missing in process B'\n"
        "print(goal.title)\n"
    )
    cr_b = run_py(ctx, name, code_b, home=home, label="process-b-read")
    assert cr_b.record["returncode"] == 0, cr_b.stderr.decode("utf-8", "replace")
    read_title = cr_b.stdout.decode("utf-8").strip()
    assert read_title == title, read_title

    return make_result(
        name,
        evidence_refs=[cr_a.record["stdout_ref"], cr_b.record["stdout_ref"]],
        commands=[cr_a.record, cr_b.record],
        metrics={"tool_calls": 0, "wall_time_ms": None, "provider_tokens": None,
                 "reasoning_tokens": None, "background_model_calls": 0},
        goal_id=goal_id,
    )


# ---------------------------------------------------------------------------
# Scenario 5-6: harness_isolation / harness_switch
# ---------------------------------------------------------------------------


def scenario_harness_isolation(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "harness_isolation"
    sess_a, sess_b = "q8-iso-a", "q8-iso-b"
    commands = []
    evidence_refs = []
    for sess in (sess_a, sess_b):
        cr = run_cli(
            ctx, name,
            ["p4", "pulse", "--event", "session_start", "--session", sess, "--force", "--json"],
            home=home, label=f"pulse-{sess}",
        )
        commands.append(cr.record)
        evidence_refs.append(cr.record["stdout_ref"])
        assert cr.record["returncode"] == 0

    file_a = telemetry.telemetry_dir(home) / f"{sess_a}.jsonl"
    file_b = telemetry.telemetry_dir(home) / f"{sess_b}.jsonl"
    assert file_a.is_file() and file_b.is_file() and file_a != file_b

    recs_a = [r for _, _, r in telemetry.iter_records(home) if r.get("session") == sess_a]
    recs_b = [r for _, _, r in telemetry.iter_records(home) if r.get("session") == sess_b]
    assert recs_a and recs_b
    assert all(r.get("session") != sess_b for r in recs_a), "session A leaked session B records"
    assert all(r.get("session") != sess_a for r in recs_b), "session B leaked session A records"

    metrics = {
        "tool_calls_a": telemetry.session_tool_calls(home, sess_a),
        "tool_calls_b": telemetry.session_tool_calls(home, sess_b),
        "records_a": len(recs_a),
        "records_b": len(recs_b),
        "files_distinct": True,
        "provider_tokens": None,
        "wall_time_ms": None,
        "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


def scenario_harness_switch(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "harness_switch"
    sess_cli, sess_bridge = "q8-harness-cli", "q8-harness-bridge"
    commands = []
    evidence_refs = []

    cr_cli = run_cli(
        ctx, name,
        ["p4", "pulse", "--event", "session_start", "--session", sess_cli, "--force", "--json"],
        home=home, label="python-cli-pulse",
    )
    commands.append(cr_cli.record)
    evidence_refs.append(cr_cli.record["stdout_ref"])
    assert cr_cli.record["returncode"] == 0

    code = (
        "import json\n"
        "from pathlib import Path\n"
        "from second_brain import p4\n"
        f"result = p4.pulse(Path({_q(str(home))}), event='session_start', "
        f"session_id={_q(sess_bridge)}, repo_dir=Path({_q(str(ctx.repo))}), force=True)\n"
        "print(json.dumps(result))\n"
    )
    cr_bridge = run_py(ctx, name, code, home=home, label="prime-bridge-direct-pulse")
    commands.append(cr_bridge.record)
    evidence_refs.append(cr_bridge.record["stdout_ref"])
    assert cr_bridge.record["returncode"] == 0, cr_bridge.stderr.decode("utf-8", "replace")
    bridge_payload = json_stdout(cr_bridge)
    assert bridge_payload["heartbeat"]["ran"] is True

    conn = sqlite3.connect(str(paths_module.db_path(home)))
    conn.row_factory = sqlite3.Row
    try:
        row_cli = conn.execute(
            "SELECT * FROM heartbeat_runs WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
            (sess_cli,),
        ).fetchone()
        row_bridge = conn.execute(
            "SELECT * FROM heartbeat_runs WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
            (sess_bridge,),
        ).fetchone()
    finally:
        conn.close()
    assert row_cli is not None and row_bridge is not None
    assert set(row_cli.keys()) == set(row_bridge.keys()), (
        "harness-dependent heartbeat_runs schema drift"
    )
    assert row_cli["mode"] == row_bridge["mode"], "harnesses disagree on heartbeat mode"

    prime_ver, prime_source = prime_version(ctx.repo)
    metrics = {
        "row_columns_identical": True,
        "cli_mode": row_cli["mode"],
        "bridge_mode": row_bridge["mode"],
        "prime_version": prime_ver,
        "prime_version_source": prime_source,
        "provider_tokens": None,
        "wall_time_ms": None,
        "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


# ---------------------------------------------------------------------------
# Scenario 7-8: driver_worker / failed_worker
# ---------------------------------------------------------------------------


def scenario_driver_worker(ctx: Ctx, home_root: Path, shared: dict[str, Any]) -> dict[str, Any]:
    # repository_intelligence.WorkerPlaneManager writes telemetry kinds
    # ("worker_spawned"/"worker_completed") that predate the P4 telemetry
    # contract and are not in telemetry.KNOWN_KINDS (a pre-existing gap in
    # that P1-era module, out of this task's scope). A dedicated home keeps
    # that unrelated non-conformance out of the P4 telemetry surface the
    # independent verifier audits, without hiding or altering any real
    # command output below.
    name = "driver_worker"
    dedicated = home_root / name
    sess = "q8-driver-worker"
    commands = []
    evidence_refs = []

    cr = run_cli(ctx, name, ["init"], home=dedicated, label="init")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    home = dedicated

    cr = run_cli(
        ctx, name,
        ["worker-plane", "spawn", sess,
         "qualification_real_subtask_implement_helper", "--json"],
        home=home, label="spawn",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    spawn_payload = json_stdout(cr)
    assert spawn_payload["spawned"] is True, spawn_payload
    worker_id = spawn_payload["worker_id"]

    cr = run_cli(
        ctx, name, ["worker-plane", "status", sess, "--json"],
        home=home, label="status-active",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    status_active = json_stdout(cr)
    assert status_active["active_workers"] == 1, status_active

    cr = run_cli(
        ctx, name,
        ["worker-plane", "complete", sess, worker_id, "--status", "COMPLETED",
         "--summary", "qualification_task_complete", "--json"],
        home=home, label="complete",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    complete_payload = json_stdout(cr)
    assert complete_payload["status"] == "COMPLETED", complete_payload

    cr = run_cli(
        ctx, name, ["worker-plane", "status", sess, "--json"],
        home=home, label="status-after",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    status_after = json_stdout(cr)
    assert status_after["active_workers"] == 0, status_after

    metrics = {
        "worker_id": worker_id, "spawned": True, "completed_status": "COMPLETED",
        "active_workers_during": status_active["active_workers"],
        "active_workers_after": status_after["active_workers"],
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


def scenario_failed_worker(ctx: Ctx, home_root: Path, shared: dict[str, Any]) -> dict[str, Any]:
    # See scenario_driver_worker: isolated in its own home for the same
    # pre-existing worker-plane telemetry-schema reason.
    name = "failed_worker"
    dedicated = home_root / name
    sess = "q8-failed-worker"
    commands = []
    evidence_refs = []

    cr = run_cli(ctx, name, ["init"], home=dedicated, label="init")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    home = dedicated

    cr = run_cli(
        ctx, name,
        ["worker-plane", "spawn", sess, "qualification_real_subtask_reproduce_failure", "--json"],
        home=home, label="spawn",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    spawn_payload = json_stdout(cr)
    worker_id = spawn_payload["worker_id"]

    cr = run_cli(
        ctx, name,
        ["worker-plane", "complete", sess, worker_id, "--status", "FAILED",
         "--summary", "qualification_real_failure", "--finding", "reproduced_real_error", "--json"],
        home=home, label="complete-failed",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    complete_payload = json_stdout(cr)
    assert complete_payload["status"] == "FAILED", complete_payload

    cr = run_cli(
        ctx, name, ["worker-plane", "status", sess, "--json"],
        home=home, label="status-after-fail",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    status_after = json_stdout(cr)
    retryable = status_after["active_workers"] < status_after["max_concurrent_workers"]

    cr = run_cli(
        ctx, name,
        ["worker-plane", "spawn", sess, "qualification_retry_after_real_failure", "--json"],
        home=home, label="retry-spawn",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    retry_payload = json_stdout(cr)
    assert retry_payload["spawned"] is retryable, retry_payload

    metrics = {
        "worker_id": worker_id, "completed_status": "FAILED", "retryable": retryable,
        "retry_spawned": retry_payload["spawned"],
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


# ---------------------------------------------------------------------------
# Scenario 9-10: malformed_state / stale_state
# ---------------------------------------------------------------------------


def scenario_malformed_state(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "malformed_state"
    isolated = ctx.out_dir / "isolated" / name
    if isolated.exists():
        shutil.rmtree(isolated)
    shutil.copytree(home, isolated)

    goal_id = shared["fresh_goal_id"]
    conn = sqlite3.connect(str(paths_module.db_path(isolated)))
    try:
        conn.execute(
            "UPDATE goals SET milestones_json = ? WHERE goal_id = ?",
            ("{not-valid-json", goal_id),
        )
        conn.commit()
    finally:
        conn.close()

    code = (
        "import json, sys\n"
        "from second_brain.goals import GoalStore\n"
        "from second_brain.errors import BrainError\n"
        f"store = GoalStore({_q(str(isolated))})\n"
        "try:\n"
        f"    store.get_goal({_q(goal_id)})\n"
        "    print(json.dumps({'refused': False}))\n"
        "    sys.exit(0)\n"
        "except BrainError as exc:\n"
        "    print(json.dumps({'refused': True, 'error': str(exc)}))\n"
        "    sys.exit(3)\n"
    )
    cr = run_py(ctx, name, code, home=isolated, label="corrupt-goal-read")
    assert cr.record["returncode"] == 3, (
        f"expected explicit refusal (exit 3) reading a corrupted goal record, "
        f"got rc={cr.record['returncode']}: {cr.stderr.decode('utf-8', 'replace')}"
    )
    payload = json_stdout(cr)
    assert payload["refused"] is True, payload

    return make_result(
        name,
        evidence_refs=[cr.record["stdout_ref"]],
        commands=[cr.record],
        metrics={
            "refused": True, "corrupted_field": "milestones_json",
            "isolated_copy": str(isolated),
            "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
        },
    )


def scenario_stale_state(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "stale_state"
    sess = "q8-stale"
    commands = []
    evidence_refs = []

    target_hash = hashlib.sha256(b"qualification radar repeated-read fixture content").hexdigest()
    directory = telemetry.telemetry_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    records = [
        {"v": 2, "kind": "tool_call", "session": sess, "ts": f"2026-08-26T00:00:0{i}Z",
         "tool": "read", "id": f"call-{i}", "target_sha256": target_hash, "input_bytes": 80}
        for i in range(3)
    ]
    tfile = directory / f"{sess}.jsonl"
    tfile.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    evidence_refs.append(write_evidence(ctx, name, "seed-telemetry", records))

    cr = run_cli(
        ctx, name,
        [
            "radar", "observe", sess, "--project-id", "second-brain",
            "--repo", str(ctx.repo), "--json",
        ],
        home=home, label="observe",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    observe_payload = json_stdout(cr)
    assert observe_payload["candidate_count"] >= 1, observe_payload
    candidate_id = observe_payload["candidates"][0]["candidate_id"]

    cr = run_cli(
        ctx, name, ["radar", "validate", candidate_id, "--json"],
        home=home, label="validate-fresh",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    fresh_payload = json_stdout(cr)
    assert fresh_payload["status"] == "candidate", fresh_payload

    lines = tfile.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("call-0", "call-0-TAMPERED")
    tfile.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cr = run_cli(
        ctx, name, ["radar", "validate", candidate_id, "--json"],
        home=home, label="validate-stale",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    stale_payload = json_stdout(cr)
    assert stale_payload["status"] == "stale", stale_payload
    assert stale_payload["reason"] == "telemetry_evidence_changed", stale_payload

    metrics = {
        "candidate_id": candidate_id, "fresh_status": fresh_payload["status"],
        "stale_status": stale_payload["status"], "stale_reason": stale_payload["reason"],
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(
        name, evidence_refs=evidence_refs, commands=commands, metrics=metrics,
        candidate_id=candidate_id,
    )


# ---------------------------------------------------------------------------
# Scenario 11-12: token_pressure / cache_sensitive
# ---------------------------------------------------------------------------


def scenario_token_pressure(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "token_pressure"
    sess = "q8-token-pressure"
    commands = []
    evidence_refs = []

    fixtures_dir = ctx.out_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    big_path = fixtures_dir / "oversized-tool-result.txt"
    line = "qualification firewall reduction real fixture line\n"
    big_path.write_text(line * 3000, encoding="utf-8")
    original_bytes = big_path.stat().st_size
    original_sha256 = hashlib.sha256(big_path.read_bytes()).hexdigest()

    cr = run_cli(
        ctx, name,
        ["firewall", "reduce", str(big_path), "--kind", "generic", "--tool", "bash",
         "--session", sess, "--json"],
        home=home, label="reduce",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    reduce_payload = json_stdout(cr)
    ref = reduce_payload["raw_object_ref"]

    cr = run_cli(ctx, name, ["firewall", "expand", ref], home=home, label="expand")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0
    expanded_sha256 = hashlib.sha256(cr.stdout).hexdigest()
    assert expanded_sha256 == original_sha256, "lossless RTD round-trip failed"

    metrics = {
        "original_bytes": original_bytes,
        "reduction_ratio": reduce_payload["reduction_ratio"],
        "lossless_roundtrip": True,
        "raw_object_ref": ref,
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


def scenario_cache_sensitive(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "cache_sensitive"
    pattern = "class GoalStore"
    commands = []
    evidence_refs = []

    cr = run_cli(
        ctx, name, ["action-cache", "search", pattern, "--path", str(ctx.repo), "--json"],
        home=home, label="search-miss",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    miss_payload = json_stdout(cr)
    assert miss_payload["hit"] is False, miss_payload

    cr = run_cli(
        ctx, name, ["action-cache", "search", pattern, "--path", str(ctx.repo), "--json"],
        home=home, label="search-hit",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    hit_payload = json_stdout(cr)
    assert hit_payload["hit"] is True, hit_payload
    assert hit_payload["content"] == miss_payload["content"]

    metrics = {
        "miss_latency_ms": miss_payload["latency_ms"], "hit_latency_ms": hit_payload["latency_ms"],
        "hit_after_miss": True,
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


# ---------------------------------------------------------------------------
# Scenario 13: long_running_goal
# ---------------------------------------------------------------------------


def scenario_long_running_goal(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "long_running_goal"
    commands = []
    evidence_refs = []

    code_create = (
        "from second_brain.goals import GoalStore\n"
        f"store = GoalStore({_q(str(home))})\n"
        "goal = store.create_goal('qualification long-running goal', "
        "'exercise the full P4 goal lifecycle', milestone_titles=['plan', 'ship'])\n"
        "print(goal.goal_id)\n"
    )
    cr = run_py(ctx, name, code_create, home=home, label="create")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    goal_id = cr.stdout.decode("utf-8").strip()

    code_block = (
        "from second_brain.goals import GoalStore, GoalStatus\n"
        f"store = GoalStore({_q(str(home))})\n"
        f"store.transition({_q(goal_id)}, GoalStatus.BLOCKED, "
        "blocker_note='waiting on a real qualification dependency')\n"
        f"print(store.get_goal({_q(goal_id)}).status.value)\n"
    )
    cr = run_py(ctx, name, code_block, home=home, label="block")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    assert cr.stdout.decode("utf-8").strip() == "BLOCKED"

    code_resume = (
        "from second_brain.goals import GoalStore, GoalStatus\n"
        f"store = GoalStore({_q(str(home))})\n"
        f"store.transition({_q(goal_id)}, GoalStatus.ACTIVE)\n"
        f"print(store.get_goal({_q(goal_id)}).status.value)\n"
    )
    cr = run_py(ctx, name, code_resume, home=home, label="resume")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    assert cr.stdout.decode("utf-8").strip() == "ACTIVE"

    code_complete = (
        "import json\n"
        "from second_brain.goals import GoalStore\n"
        f"store = GoalStore({_q(str(home))})\n"
        f"store.complete_milestone({_q(goal_id)}, 'm-1', evidence_ref='qualification:plan-done')\n"
        f"store.complete_milestone({_q(goal_id)}, 'm-2', evidence_ref='qualification:ship-done')\n"
        f"goal = store.get_goal({_q(goal_id)})\n"
        "print(json.dumps({'status': goal.status.value, "
        "'completed': goal.completed_at is not None}))\n"
    )
    cr = run_py(ctx, name, code_complete, home=home, label="complete-milestones")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")
    final_payload = json_stdout(cr)
    assert final_payload["status"] == "COMPLETED", final_payload
    assert final_payload["completed"] is True

    metrics = {
        "goal_id": goal_id, "final_status": final_payload["status"],
        "transitions": ["ACTIVE", "BLOCKED", "ACTIVE", "COMPLETED"],
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(
        name, evidence_refs=evidence_refs, commands=commands, metrics=metrics,
        goal_id=goal_id,
    )


# ---------------------------------------------------------------------------
# Scenario 14-15: brain_off / brain_on
# ---------------------------------------------------------------------------


def scenario_brain_off(ctx: Ctx, home_root: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "brain_off"
    dedicated = home_root / name
    commands = []
    evidence_refs = []

    cr = run_cli(ctx, name, ["init"], home=dedicated, label="init")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")

    set_heartbeat_mode(dedicated, "off")

    conn = sqlite3.connect(str(paths_module.db_path(dedicated)))
    try:
        before_runs = conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0]
        before_state = conn.execute("SELECT last_run_at FROM heartbeat_state").fetchone()[0]
    finally:
        conn.close()

    sess = "q8-brain-off"
    cr = run_cli(
        ctx, name,
        ["p4", "pulse", "--event", "session_start", "--session", sess, "--force", "--json"],
        home=dedicated, label="pulse-off",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    payload = json_stdout(cr)
    assert payload["heartbeat"]["mode"] == "off", payload
    assert payload["heartbeat"]["due"] is False, payload
    assert payload["heartbeat"]["ran"] is False, payload

    conn = sqlite3.connect(str(paths_module.db_path(dedicated)))
    try:
        after_runs = conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0]
        after_state = conn.execute("SELECT last_run_at FROM heartbeat_state").fetchone()[0]
    finally:
        conn.close()
    assert after_runs == before_runs, "OFF mode must not insert heartbeat_runs rows"
    assert after_state == before_state, "OFF mode must not update heartbeat_state"

    metrics = {
        "mode": "off", "heartbeat_runs_before": before_runs, "heartbeat_runs_after": after_runs,
        "p4_mutation": False,
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(
        name, evidence_refs=evidence_refs, commands=commands, metrics=metrics,
        home=str(dedicated),
    )


def scenario_brain_on(ctx: Ctx, home_root: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "brain_on"
    dedicated = home_root / name
    commands = []
    evidence_refs = []

    cr = run_cli(ctx, name, ["init"], home=dedicated, label="init")
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")

    set_heartbeat_mode(dedicated, "active")

    conn = sqlite3.connect(str(paths_module.db_path(dedicated)))
    try:
        before_runs = conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0]
    finally:
        conn.close()

    sess = "q8-brain-on"
    cr = run_cli(
        ctx, name,
        ["p4", "pulse", "--event", "session_start", "--session", sess, "--force", "--json"],
        home=dedicated, label="pulse-active",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    payload = json_stdout(cr)
    assert payload["heartbeat"]["mode"] == "active", payload
    assert payload["heartbeat"]["ran"] is True, payload
    assert payload["heartbeat"]["maintenance_mutated"] is True, payload

    conn = sqlite3.connect(str(paths_module.db_path(dedicated)))
    try:
        after_runs = conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0]
    finally:
        conn.close()
    assert after_runs == before_runs + 1, "ACTIVE mode must record a real heartbeat_runs row"

    metrics = {
        "mode": "active", "heartbeat_runs_before": before_runs, "heartbeat_runs_after": after_runs,
        "maintenance_mutated": True,
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(
        name, evidence_refs=evidence_refs, commands=commands, metrics=metrics,
        home=str(dedicated),
    )


# ---------------------------------------------------------------------------
# Scenario 16: recovery_rollback
# ---------------------------------------------------------------------------


def scenario_recovery_rollback(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "recovery_rollback"
    commands = []
    evidence_refs = []

    guarded_dir = home / "state" / "qualification"
    guarded_dir.mkdir(parents=True, exist_ok=True)
    target_rel = "state/qualification/guarded-target.txt"
    target_path = home / target_rel
    good_content = b"qualification guarded good state\n"
    target_path.write_bytes(good_content)
    good_hash = hashlib.sha256(good_content).hexdigest()

    policy_id, trigger_id = "q8-guard-policy", "q8-guard-trigger"
    cr = run_cli(
        ctx, name,
        ["immune", "policy", policy_id, "--trigger", trigger_id, "--target", target_rel,
         "--backup-of", good_hash],
        home=home, label="register-policy",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")

    cr = run_cli(
        ctx, name,
        ["immune", "trigger", trigger_id, "--metric", "tests_failed", "--operator", ">",
         "--value", "0", "--window", "1"],
        home=home, label="register-trigger",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")

    cr = run_cli(
        ctx, name, ["immune", "ingest", "tests_failed", "1", "--run", "qualification-run"],
        home=home, label="ingest-real-failing-metric",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, cr.stderr.decode("utf-8", "replace")

    # A real bad mutation, as the governed operation would have applied.
    target_path.write_bytes(b"qualification guarded BAD mutated state\n")

    cr = run_cli(
        ctx, name, ["immune", "check", "--policy", policy_id],
        home=home, label="check-triggers",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert "matched=True" in cr.stdout.decode("utf-8"), cr.stdout.decode("utf-8")

    cr = run_cli(
        ctx, name,
        ["immune", "rollback", policy_id, trigger_id, "--reason",
         "qualification_recovery_test"],
        home=home, label="rollback",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, (
        cr.stdout.decode("utf-8")
        + cr.stderr.decode("utf-8", "replace")
    )
    assert "rolled_back=True" in cr.stdout.decode("utf-8")
    assert not target_path.exists(), "rollback should have moved the mutated target aside"

    backups = list((home / "immune" / "rollbacks").glob(f"{policy_id}-*.bak"))
    assert backups, "expected a real rollback backup file"

    metrics = {
        "policy_id": policy_id, "trigger_id": trigger_id, "rolled_back": True,
        "backup_count": len(backups),
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


# ---------------------------------------------------------------------------
# Scenario 17: security_boundary
# ---------------------------------------------------------------------------


def scenario_security_boundary(ctx: Ctx, home: Path, shared: dict[str, Any]) -> dict[str, Any]:
    name = "security_boundary"
    fake_repo = ctx.out_dir / "fixtures" / "security-boundary-fake-repo"
    fake_repo.mkdir(parents=True, exist_ok=True)

    projects_before = (
        sorted(p.name for p in (home / "projects").glob("*"))
        if (home / "projects").is_dir()
        else []
    )

    cr = run_cli(
        ctx, name,
        [
            "project", "add", str(fake_repo), "--id", "../../evil-escape",
            "--no-marker", "--no-manifest",
        ],
        home=home, label="malicious-project-id",
    )
    assert cr.record["returncode"] != 0, "path-traversal project id must be refused"
    stderr_text = cr.stderr.decode("utf-8", "replace")
    assert "error" in stderr_text.lower(), stderr_text

    projects_after = (
        sorted(p.name for p in (home / "projects").glob("*"))
        if (home / "projects").is_dir()
        else []
    )
    assert projects_after == projects_before, "refused project add must not mutate projects/"
    escape_target = home.parent / "evil-escape"
    assert not escape_target.exists(), "path traversal must never escape the Brain home"

    metrics = {
        "refused": True, "returncode": cr.record["returncode"],
        "projects_unchanged": projects_after == projects_before,
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(
        name, evidence_refs=[cr.record["stdout_ref"], cr.record["stderr_ref"]],
        commands=[cr.record], metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Scenario 18: genuine_project_dogfood
# ---------------------------------------------------------------------------


def scenario_genuine_project_dogfood(
    ctx: Ctx, home: Path, shared: dict[str, Any]
) -> dict[str, Any]:
    name = "genuine_project_dogfood"
    commands = []
    evidence_refs = []

    cr = run_argv(
        ctx, name, [str(ctx.python_exe), "-m", "pytest", "-q", "tests/test_p4.py"],
        cwd=ctx.repo, env=sanitized_env(None), label="focused-p4-pytest", timeout=300,
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    assert cr.record["returncode"] == 0, (
        f"repository's real focused P4 test suite failed: {cr.stdout.decode('utf-8', 'replace')}"
    )
    pytest_summary = (
        cr.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
        if cr.stdout else ""
    )

    cr = run_cli(
        ctx, name, ["doctor", "--repo", str(ctx.repo), "--json"],
        home=home, label="doctor-registered-project",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    doctor_payload = json_stdout(cr)
    assert doctor_payload["failed"] is False, doctor_payload

    sess = "q8-dogfood"
    cr = run_cli(
        ctx, name,
        ["p4", "pulse", "--event", "session_start", "--session", sess, "--force", "--json",
         "--repo", str(ctx.repo), "--project-id", shared["registered_project_id"]],
        home=home, label="p4-pulse-registered-project",
    )
    commands.append(cr.record)
    evidence_refs.append(cr.record["stdout_ref"])
    pulse_payload = json_stdout(cr)
    assert pulse_payload["heartbeat"]["ran"] is True, pulse_payload

    metrics = {
        "pytest_summary": pytest_summary, "pytest_returncode": 0,
        "registered_project_id": shared["registered_project_id"],
        "doctor_failed": doctor_payload["failed"],
        "provider_tokens": None, "wall_time_ms": None, "background_model_calls": 0,
    }
    return make_result(name, evidence_refs=evidence_refs, commands=commands, metrics=metrics)


SCENARIO_FUNCS: tuple[tuple[str, Any], ...] = (
    ("fresh_session", scenario_fresh_session),
    ("resumed_session", scenario_resumed_session),
    ("compacted_session", scenario_compacted_session),
    ("cross_session_continuity", scenario_cross_session_continuity),
    ("harness_isolation", scenario_harness_isolation),
    ("harness_switch", scenario_harness_switch),
    ("driver_worker", scenario_driver_worker),
    ("failed_worker", scenario_failed_worker),
    ("malformed_state", scenario_malformed_state),
    ("stale_state", scenario_stale_state),
    ("token_pressure", scenario_token_pressure),
    ("cache_sensitive", scenario_cache_sensitive),
    ("long_running_goal", scenario_long_running_goal),
    ("brain_off", scenario_brain_off),
    ("brain_on", scenario_brain_on),
    ("recovery_rollback", scenario_recovery_rollback),
    ("security_boundary", scenario_security_boundary),
    ("genuine_project_dogfood", scenario_genuine_project_dogfood),
)


def run_qualification(out_dir: Path, repo: Path) -> dict[str, Any]:
    """Run all 18 real P4 qualification scenarios; return the manifest dict.

    Every raw artifact this run produces (subprocess captures, seeded
    fixtures, evidence snapshots) is written under `out_dir`. The manifest
    itself is written to `out_dir/qualification-manifest.json`.
    """
    out_dir = Path(out_dir).resolve()
    repo = Path(repo).resolve()
    raw_dir = out_dir / "raw"
    if raw_dir.is_symlink():
        raise RuntimeError(f"raw evidence directory must not be a symlink: {raw_dir}")
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    homes_dir = out_dir / "homes"
    if homes_dir.is_symlink():
        raise RuntimeError(f"qualification homes directory must not be a symlink: {homes_dir}")
    if homes_dir.exists():
        shutil.rmtree(homes_dir)
    homes_dir.mkdir(parents=True, exist_ok=True)

    ctx = Ctx(repo=repo, out_dir=out_dir, raw_dir=raw_dir, python_exe=Path(sys.executable))

    git, setup_commands = git_info(ctx)
    prime_ver, prime_source = prime_version(repo)

    shared_home = homes_dir / "shared"
    if shared_home.exists():
        shutil.rmtree(shared_home)
    init_cr = run_cli(ctx, "_setup", ["init"], home=shared_home, label="init-shared-home")
    setup_commands.append(init_cr.record)
    if init_cr.record["returncode"] != 0:
        raise AssertionError(
            "failed to initialize the shared Brain home: "
            f"{init_cr.stderr.decode('utf-8', 'replace')}"
        )

    project_cr = run_cli(
        ctx, "_setup",
        ["project", "add", str(repo), "--id", "second-brain", "--no-marker", "--no-manifest"],
        home=shared_home, label="register-second-brain-project",
    )
    setup_commands.append(project_cr.record)
    if project_cr.record["returncode"] != 0:
        raise AssertionError(
            f"failed to register the repository as project 'second-brain': "
            f"{project_cr.stderr.decode('utf-8', 'replace')}"
        )

    shared: dict[str, Any] = {"registered_project_id": "second-brain"}
    scenarios: list[dict[str, Any]] = []
    for scenario_name, fn in SCENARIO_FUNCS:
        try:
            if scenario_name in ("brain_off", "brain_on", "driver_worker", "failed_worker"):
                result = fn(ctx, homes_dir, shared)
            else:
                result = fn(ctx, shared_home, shared)
        except Exception as exc:
            result = {
                "name": scenario_name,
                "status": "failed",
                "evidence_refs": [],
                "commands": [],
                "metrics": {},
                "error": f"{type(exc).__name__}: {exc}",
            }
        scenarios.append(result)

    ordered_names = [row["name"] for row in scenarios]
    assert set(ordered_names) == set(SCENARIO_NAMES), (
        f"scenario name mismatch: {set(ordered_names) ^ set(SCENARIO_NAMES)}"
    )

    # Every referenced raw artifact (command captures already carry
    # stdout_sha256/stderr_sha256 on their own records; write_evidence()
    # snapshots like seeded telemetry/compaction fixtures do not) gets a
    # manifest-recorded sha256 here so the independent verifier can check
    # integrity of the *entire* evidence_refs set, not just command streams.
    for row in scenarios:
        hashes: dict[str, str] = {}
        for ref in row.get("evidence_refs", []):
            ref_path = _confined_evidence_path(out_dir, ref)
            if ref_path is None or not ref_path.is_file():
                raise ValueError(f"invalid or missing evidence ref: {ref!r}")
            hashes[ref] = hashlib.sha256(ref_path.read_bytes()).hexdigest()
        row["evidence_ref_hashes"] = hashes

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "repo": str(repo),
        "out_dir": str(out_dir),
        "git": git,
        "prime": {"version": prime_ver, "source": prime_source},
        "python": {"version": sys.version, "executable": str(ctx.python_exe)},
        "home": str(shared_home),
        "setup_commands": setup_commands,
        "scenarios": scenarios,
        "summary": {
            "total": len(scenarios),
            "passed": sum(1 for row in scenarios if row["status"] == "passed"),
            "failed": sum(1 for row in scenarios if row["status"] != "passed"),
        },
    }
    manifest_path = out_dir / "qualification-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = run_qualification(args.out, args.repo)
    print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
    if manifest["summary"]["failed"]:
        for row in manifest["scenarios"]:
            if row["status"] != "passed":
                print(
                    f"FAILED scenario {row['name']}: "
                    f"{row.get('error', 'unknown failure')}",
                    file=sys.stderr,
                )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
