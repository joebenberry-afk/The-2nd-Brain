"""E01 turn bridge: batched/reused-interpreter memory preparation.

The contract these tests protect:

* a batched `prepare_turn` returns EXACTLY what the three separate CLI
  commands return (capsule ensure, vmem hot-context, autoinject shadow), so
  the adapter's batched path cannot change a decision or a packet;
* the JSON-lines helper answers one bounded request at a time, rejects a
  different brain home or an empty task, reports identity drift instead of
  answering from stale loaded state, and stops on EOF, `shutdown` or a
  bounded lifetime;
* every failure is fail-open data (`*_error`), never an exception.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from second_brain import turn_bridge

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK = "In what order should database migrations be applied?"
SESSION = "e01-session"


def _env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["SECOND_BRAIN_HOME"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_cli(home: Path, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(home),
        cwd=home,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def prepare(home: Path, **overrides) -> dict:
    kwargs: dict[str, Any] = {
        "session_id": SESSION,
        "task": TASK,
        "agent_id": SESSION,
    }
    kwargs.update(overrides)
    return turn_bridge.prepare_turn(home, **kwargs)


def test_prepare_turn_matches_the_separate_cli_commands(brain_home: Path) -> None:
    """Batched == per-phase, field by field, on every phase output.

    The batched call creates the capsule first; the CLI calls then see the
    SAME unchanged capsule, so their bytes (sha256/bytes/payload) must match
    the batched values exactly — the strongest available parity check.
    """
    first = prepare(brain_home, budget_tokens=256)
    assert first["capsule"]["changed"] is True

    capsule = run_cli(
        brain_home, "capsule", "ensure", SESSION, TASK, "--next-action", TASK, "--json"
    )
    render = run_cli(brain_home, "vmem", "hot-context", SESSION, "--budget", "256", "--json")
    autoinject = run_cli(
        brain_home,
        "autoinject",
        "shadow",
        "--task",
        TASK,
        "--session",
        SESSION,
        "--agent",
        SESSION,
        "--branch",
        "main",
        "--role",
        "worker",
        "--json",
    )

    batched = prepare(brain_home, budget_tokens=256)

    assert batched["ok"] is True
    assert batched["errors"] == []
    assert capsule["changed"] is False
    assert batched["capsule"]["changed"] is False
    assert batched["capsule"]["capsule_sha256"] == capsule["capsule_sha256"]
    assert batched["capsule"]["capsule_bytes"] == capsule["capsule_bytes"]
    assert batched["capsule"]["capsule"] == capsule["capsule"]
    assert json.loads(batched["capsule_stdout"]) == capsule
    assert batched["active_state"]["rendered_text"] == render["rendered_text"]
    assert batched["active_state"]["session_id"] == render["session_id"]
    assert json.loads(batched["autoinject_stdout"]) == autoinject


def test_prepare_turn_stdout_fields_match_the_cli_stdout_bytes(brain_home: Path) -> None:
    """The `*_stdout` fields are the CLI's own output, so the adapter can reuse
    its existing parsers instead of growing a second one."""
    batched = prepare(brain_home)
    capsule = run_cli(
        brain_home, "capsule", "ensure", SESSION, TASK, "--next-action", TASK, "--json"
    )
    # Both encoded with the same json.dumps(indent=2) + trailing newline the
    # CLI prints; capsule bytes are timestamp-independent only within one run,
    # so compare the parsed values plus the exact key order of the payload.
    reparsed = json.loads(batched["capsule_stdout"])
    assert list(reparsed) == list(capsule)
    assert batched["capsule_stdout"].endswith("\n")
    assert batched["autoinject_stdout"].endswith("\n")


def test_prepare_turn_keeps_phase_order_and_reports_timings(brain_home: Path) -> None:
    batched = prepare(brain_home)
    assert batched["phases"] == ["capsule", "render", "autoinject"]
    for phase in ("capsule", "render", "autoinject", "total"):
        assert batched["timings_ms"][phase] >= 0
    assert batched["timings_ms"]["total"] >= batched["timings_ms"]["capsule"]


def test_prepare_turn_reports_per_phase_success(brain_home: Path, monkeypatch) -> None:
    """A client must be able to consume the phases that succeeded: a later
    phase can commit its delivery while an earlier one failed."""
    batched = prepare(brain_home)
    assert batched["phases_ok"] == {"capsule": True, "render": True, "autoinject": True}

    reduced = prepare(brain_home, want=["capsule", "render"])
    assert reduced["phases_ok"] == {"capsule": True, "render": True, "autoinject": None}

    def boom(*_args, **_kwargs):
        raise ValueError("phase exploded")

    monkeypatch.setattr(turn_bridge, "_render_phase", boom)
    partial = prepare(brain_home)
    assert partial["ok"] is False
    assert partial["phases_ok"] == {"capsule": True, "render": False, "autoinject": True}
    assert partial["capsule_stdout"] is not None
    assert partial["autoinject_stdout"] is not None
    assert partial["render_stdout"] is None


def test_phase_selection_is_validated() -> None:
    assert turn_bridge.phase_selection(None) == (None, None)
    assert turn_bridge.phase_selection(["render", "capsule"]) == (("capsule", "render"), None)
    assert turn_bridge.phase_selection(["capsule", "nonsense"]) == (None, "invalid_want")
    assert turn_bridge.phase_selection([]) == (None, "invalid_want")
    assert turn_bridge.phase_selection("capsule") == (None, "invalid_want")


def test_serve_honours_and_rejects_want(brain_home: Path) -> None:
    """The helper dispatcher must forward `want` (an emit-cache hit must not
    rerun the AutoInject decision) and refuse an unknown phase."""
    responses = _serve(
        brain_home,
        [
            {
                "id": 1,
                "op": "prepare_turn",
                "session_id": SESSION,
                "task": TASK,
                "want": ["capsule", "render"],
            },
            {
                "id": 2,
                "op": "prepare_turn",
                "session_id": SESSION,
                "task": TASK,
                "want": ["capsule", "bogus"],
            },
            {"op": "shutdown"},
        ],
    )
    reduced = responses[1]["result"]
    assert reduced["phases"] == ["capsule", "render"]
    assert reduced["autoinject"] is None
    assert reduced["phases_ok"]["autoinject"] is None
    assert responses[2]["error"] == "invalid_want"


def test_prepare_turn_honours_a_reduced_phase_set(brain_home: Path) -> None:
    """A cached AutoInject emit must not pay for (or duplicate) the decision."""
    batched = prepare(brain_home, want=["capsule", "render"])
    assert batched["autoinject"] is None
    assert batched["autoinject_stdout"] is None
    assert batched["ok"] is True


def test_prepare_turn_is_fail_open_per_phase(brain_home: Path, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise ValueError("phase exploded")

    monkeypatch.setattr(turn_bridge, "_render_phase", boom)
    batched = prepare(brain_home)
    assert batched["ok"] is False
    assert "render_error" in batched
    assert batched["active_state"]["ok"] is False
    # The other phases still produced their results.
    assert batched["capsule"] is not None
    assert batched["autoinject"] is not None
    assert batched["errors"] == ["render_error"]


def test_prepare_turn_bounds_a_huge_task_like_the_cli(brain_home: Path) -> None:
    huge = "x" * (turn_bridge.MAX_TASK_CHARS + 500)
    batched = prepare(brain_home, task=huge)
    cli = run_cli(brain_home, "capsule", "ensure", "cli-session", huge, "--json")
    objective = batched["capsule"]["capsule"]["objective"]
    assert objective == cli["capsule"]["objective"]
    assert 0 < len(objective) <= turn_bridge.MAX_TASK_CHARS


def _serve(
    home: Path, requests: list[dict], *, raw_lines: list[str] | None = None, **kwargs
) -> list[dict]:
    payload = "".join(f"{json.dumps(request)}\n" for request in requests)
    payload += "".join(f"{line}\n" for line in raw_lines or [])
    out = io.StringIO()
    code = turn_bridge.serve(
        home,
        stream_in=io.StringIO(payload),
        stream_out=out,
        max_rss_bytes=0,
        **kwargs,
    )
    assert code == 0
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_serve_handshake_request_and_shutdown(brain_home: Path) -> None:
    responses = _serve(
        brain_home,
        [
            {"id": 1, "op": "prepare_turn", "session_id": SESSION, "task": TASK},
            {"id": 2, "op": "ping"},
            {"id": 3, "op": "shutdown"},
        ],
    )
    assert responses[0]["op"] == "ready"
    assert responses[0]["identity"]["home"] == str(brain_home)
    assert responses[0]["limits"]["max_requests"] == turn_bridge.DEFAULT_MAX_REQUESTS

    prepared = responses[1]
    assert prepared["id"] == 1
    assert prepared["result"]["ok"] is True
    assert prepared["result"]["session_id"] == SESSION
    assert prepared["result"]["capsule"]["capsule"]["objective"] == TASK

    assert responses[2]["op"] == "ping"
    assert responses[2]["requests"] == 2
    assert responses[3]["op"] == "shutdown"


def test_serve_is_request_isolated(brain_home: Path) -> None:
    """Two sessions in one helper keep their own capsule/session identity."""
    responses = _serve(
        brain_home,
        [
            {"id": 1, "op": "prepare_turn", "session_id": "session-a", "task": TASK},
            {"id": 2, "op": "prepare_turn", "session_id": "session-b", "task": TASK},
            {"op": "shutdown"},
        ],
    )
    assert responses[1]["result"]["session_id"] == "session-a"
    assert responses[2]["result"]["session_id"] == "session-b"
    capsules = {
        responses[1]["result"]["capsule"]["capsule_path"],
        responses[2]["result"]["capsule"]["capsule_path"],
    }
    assert len(capsules) == 2


def test_serve_rejects_a_different_home_empty_task_and_bad_requests(
    brain_home: Path, tmp_path: Path
) -> None:
    responses = _serve(
        brain_home,
        [
            {
                "id": 1,
                "op": "prepare_turn",
                "home": str(tmp_path),
                "session_id": SESSION,
                "task": TASK,
            },
            {"id": 2, "op": "prepare_turn", "session_id": SESSION, "task": "   "},
            {"id": 3, "op": "prepare_turn", "task": TASK},
            {"id": 4, "op": "retrieve_everything", "session_id": SESSION, "task": TASK},
            {"op": "shutdown"},
        ],
    )
    assert [r["error"] for r in responses[1:5]] == [
        "home_mismatch",
        "empty_task",
        "missing_session_id",
        "unsupported_op",
    ]
    assert responses[1]["expected_home"] == str(brain_home)


def test_serve_reports_identity_drift_instead_of_stale_state(brain_home: Path, monkeypatch) -> None:
    base = turn_bridge.identity(brain_home)
    monkeypatch.setattr(turn_bridge, "_source_mtime_ns", lambda: (base["source_mtime_ns"] or 0) + 1)
    session = turn_bridge.TurnSession(brain_home)
    monkeypatch.setattr(session, "base_identity", base)
    response = session.handle(
        {"op": "prepare_turn", "home": str(brain_home), "session_id": SESSION, "task": TASK}
    )
    assert response == {
        "ok": False,
        "op": "prepare_turn",
        "error": "identity_changed",
        "drift": "code_changed",
    }


def test_serve_detects_an_external_db_change_but_not_its_own_writes(brain_home: Path) -> None:
    """A reused interpreter must not answer from state loaded before an
    in-place database replacement, and must NOT treat its own writes as drift
    (otherwise every answered turn would force a restart)."""
    session = turn_bridge.TurnSession(brain_home)
    request = {"op": "prepare_turn", "session_id": SESSION, "task": TASK}
    assert session.handle(dict(request))["ok"] is True
    assert session.handle(dict(request))["ok"] is True  # own writes are absorbed

    db_file = brain_home / "db" / "brain.sqlite"
    stat = db_file.stat()
    os.utime(db_file, ns=(stat.st_atime_ns + 5_000_000_000, stat.st_mtime_ns + 5_000_000_000))

    drifted = session.handle(dict(request))
    assert drifted == {
        "ok": False,
        "op": "prepare_turn",
        "error": "identity_changed",
        "drift": "db_changed",
    }


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("db", "db_changed"),
        ("config", "config_changed"),
    ],
)
def test_identity_drift_detects_db_and_config_changes(
    brain_home: Path, monkeypatch, field: str, expected: str
) -> None:
    base = turn_bridge.identity(brain_home)
    drifted = dict(base)
    drifted[field] = "different"
    assert turn_bridge.identity_drift(drifted, brain_home) == expected
    assert turn_bridge.identity_drift(base, brain_home) is None


def test_serve_stops_after_the_bounded_request_count(brain_home: Path) -> None:
    responses = _serve(
        brain_home,
        [
            {"id": 1, "op": "prepare_turn", "session_id": SESSION, "task": TASK},
            {"id": 2, "op": "prepare_turn", "session_id": SESSION, "task": TASK},
        ],
        max_requests=1,
    )
    assert responses[-1]["op"] == "exit"
    assert responses[-1]["reason"] == "max_requests"
    # The second request is never answered: the helper stops after the bound.
    assert [r.get("id") for r in responses].count(2) == 0


def test_serve_stops_after_the_error_budget(brain_home: Path) -> None:
    responses = _serve(brain_home, [], raw_lines=["not json", "not json", "not json"], max_errors=2)
    assert [r["error"] for r in responses[1:3]] == ["malformed_json", "malformed_json"]
    assert responses[-1]["op"] == "exit"
    assert responses[-1]["reason"] == "error_budget"


def test_serve_exits_on_eof_and_rejects_oversized_requests(brain_home: Path) -> None:
    responses = _serve(brain_home, [])
    assert [r["op"] for r in responses] == ["ready", "exit"]
    assert responses[-1]["reason"] == "eof"

    oversized = "x" * (turn_bridge.MAX_REQUEST_BYTES + 10)
    out = io.StringIO()
    turn_bridge.serve(
        brain_home,
        stream_in=io.StringIO(f"{oversized}\n"),
        stream_out=out,
        max_rss_bytes=0,
    )
    lines = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert lines[1]["error"] == "request_too_large"


def test_identity_binds_home_code_config_and_db(brain_home: Path) -> None:
    identity = turn_bridge.identity(brain_home)
    assert identity["home"] == str(brain_home)
    assert identity["python"] == sys.executable
    assert identity["code"]
    assert identity["config"]
    assert identity["db"]["exists"] is True
    assert identity["schema_version"] >= 1
    assert identity["source_mtime_ns"] > 0


def test_cli_turn_prepare_phases_flag(brain_home: Path) -> None:
    reduced = run_cli(
        brain_home,
        "turn",
        "prepare",
        "--session",
        SESSION,
        "--task",
        TASK,
        "--phases",
        "capsule,render",
        "--json",
    )
    assert reduced["phases"] == ["capsule", "render"]
    assert reduced["autoinject"] is None

    invalid = subprocess.run(
        [
            sys.executable,
            "-m",
            "second_brain",
            "--home",
            str(brain_home),
            "turn",
            "prepare",
            "--session",
            SESSION,
            "--task",
            TASK,
            "--phases",
            "capsule,bogus",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(brain_home),
        cwd=brain_home,
        timeout=120,
    )
    assert invalid.returncode == 2
    assert "invalid --phases" in invalid.stderr


def test_cli_turn_prepare_exit_1_still_prints_complete_json(
    brain_home: Path, monkeypatch, capsys
) -> None:
    """Exit 1 means "a phase failed, the JSON is complete": the transport must
    not be mistaken for a crash, or the successful phases are discarded and a
    committed AutoInject delivery is lost (reviewer finding 2)."""
    from second_brain import cli as cli_mod
    from second_brain import turn_bridge as bridge

    partial = {
        "ok": False,
        "session_id": SESSION,
        "phases": ["capsule", "render", "autoinject"],
        "capsule": {"session_id": SESSION},
        "capsule_stdout": '{"session_id": "x"}\n',
        "active_state": {"ok": False, "error": "render exploded"},
        "render_stdout": None,
        "autoinject": {"decision": "INJECT"},
        "autoinject_stdout": '{"decision": "INJECT"}\n',
        "phases_ok": {"capsule": True, "render": False, "autoinject": True},
        "timings_ms": {},
        "errors": ["render_error"],
    }
    monkeypatch.setattr(bridge, "prepare_turn", lambda *_args, **_kwargs: partial)

    code = cli_mod.main(
        [
            "--home",
            str(brain_home),
            "turn",
            "prepare",
            "--session",
            SESSION,
            "--task",
            TASK,
            "--json",
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    assert code == 1
    assert printed["phases_ok"] == {"capsule": True, "render": False, "autoinject": True}
    assert printed["autoinject_stdout"] is not None


def test_cli_turn_prepare_and_serve_round_trip(brain_home: Path) -> None:
    prepared = run_cli(
        brain_home,
        "turn",
        "prepare",
        "--session",
        SESSION,
        "--task",
        TASK,
        "--json",
    )
    assert prepared["ok"] is True
    assert prepared["capsule"]["capsule"]["objective"] == TASK

    request = json.dumps({"id": 1, "op": "prepare_turn", "session_id": SESSION, "task": TASK})
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "second_brain",
            "--home",
            str(brain_home),
            "turn",
            "serve",
            "--max-requests",
            "1",
        ],
        input=f"{request}\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(brain_home),
        cwd=brain_home,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert lines[0]["op"] == "ready"
    assert lines[1]["result"]["session_id"] == SESSION
    assert lines[-1]["reason"] == "max_requests"


def test_trace_env_records_python_phases(tmp_path: Path, brain_home: Path, monkeypatch) -> None:
    trace = tmp_path / "e01-trace.jsonl"
    monkeypatch.setenv(turn_bridge.TRACE_ENV, str(trace))
    prepare(brain_home)
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    names = [event.get("name") for event in events if event["t"] == "phase"]
    assert names == ["capsule", "render", "autoinject"]
    assert all(event["end_ms"] >= event["start_ms"] for event in events if event["t"] == "phase")
