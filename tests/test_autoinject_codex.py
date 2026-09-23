"""Codex hook adapter tests (Phase 0C part 2; plan §6.10, §17.3 hook tier).

`brainctl autoinject codex-shadow`: ONE JSON object on stdin -> ONE JSON
object on stdout. Task text NEVER crosses argv (STOP §23 #6); malformed or
missing stdin fails open to NO_INJECTION(BRAIN_UNAVAILABLE) with exit 0.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from second_brain import registry, semantic

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(home: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        input=stdin,
        timeout=120,
    )


def _init_and_seed(
    home: Path, title: str = "Migration ordering", body: str = "apply migrations in numeric order"
) -> None:
    home.mkdir(parents=True, exist_ok=True)
    r = _run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    mid = semantic.add_memory(
        home, title, body, scope="project", project_id="proj-a", grade="TESTED"
    )
    semantic.curate(home, mid, status="current")


def test_native_session_end_records_finalization_without_inferred_failure(
    tmp_path, monkeypatch
) -> None:
    from second_brain import db, telemetry

    monkeypatch.setenv("SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE", "CANARY")
    home = tmp_path / "brain"
    _init_and_seed(home, title="Alpha rules", body="alpha body content")
    session_id = "native-codex-end"
    _run_cli(
        home,
        "autoinject",
        "codex-shadow",
        stdin=json.dumps(
            {
                "session_id": session_id,
                "project": "proj-a",
                "hook_event_name": "UserPromptSubmit",
                "prompt": "implement alpha rules",
            }
        ),
    )
    result = _run_cli(
        home,
        "autoinject",
        "codex-shadow",
        stdin=json.dumps(
            {
                "session_id": session_id,
                "project": "proj-a",
                "hook_event_name": "SessionEnd",
            }
        ),
    )
    assert result.returncode == 0, result.stderr
    assert any(
        record.get("kind") == "session_finalized" and record.get("session") == session_id
        for _, _, record in telemetry.iter_records(home)
    )
    conn = db.connect(db.db_path(home), readonly=True)
    try:
        row = conn.execute(
            (
                "SELECT outcome_json, reward FROM decisions "
                "WHERE session_id = ? AND kind = 'retrieval'"
            ),
            (session_id,),
        ).fetchone()
        assert row is not None
        assert row["outcome_json"] is None
        assert row["reward"] is None
    finally:
        conn.close()


def test_windows_hook_preserves_unicode_project_scope_and_unknown_counts(tmp_path) -> None:
    if os.name != "nt":
        import pytest

        pytest.skip("Windows PowerShell transport")
    home = tmp_path / "brain"
    _init_and_seed(home)
    cwd_dir = tmp_path / "repo-\u03bb"
    cwd_dir.mkdir()
    registry.add_project(home, cwd_dir, project_id="proj-a")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"}
    }
    env.update({
        "SECOND_BRAIN_HOME": str(home),
        "SECOND_BRAIN_PYTHON": sys.executable,
        "SECOND_BRAIN_AUTOINJECT_MODE": "advisory",
        "PYTHONIOENCODING": "cp1252",
    })
    payload = {
        "session_id": "unicode-hook",
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(cwd_dir),
        "prompt": "migration ordering",
    }
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "brainstem" / "codex-hooks" / "run.ps1"),
        ],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout.decode("utf-8"))
    assert "apply migrations in numeric order" in response["additionalContext"]
    log_path = home / "telemetry" / "agent-performance" / "codex-hooks.jsonl"
    observation = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert observation["candidate_count"] is None
    assert observation["selected_count"] is None


def _payload(**kw: str) -> str:
    base = {
        "session_id": "codex-s1",
        "project": "proj-a",
        "task": "migration ordering",
        "agent_id": "a1",
        "branch": "main",
        "role": "worker",
        "source": "UserPromptSubmit",
    }
    base.update(kw)
    return json.dumps(base)


def test_valid_stdin_deterministic_output(tmp_path) -> None:
    home = tmp_path / "brain"
    _init_and_seed(home)
    r = _run_cli(home, "autoinject", "codex-shadow", stdin=_payload())
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["decision"] == "INJECT"
    assert out["reason"] is None
    assert out["packet"].startswith("[BRAIN_CONTEXT_DELTA v1]")
    assert out["delivery_id"]

    # Dedupe on the same lineage -> ALREADY_DELIVERED, still exit 0.
    r2 = _run_cli(home, "autoinject", "codex-shadow", stdin=_payload())
    out2 = json.loads(r2.stdout)
    assert out2["decision"] == "NO_INJECTION"
    assert out2["reason"] == "ALREADY_DELIVERED"
    assert out2["packet"] is None

    # Fresh lineage -> byte-identical packet (determinism).
    payload = _payload(session_id="codex-s2", branch="b2")
    r3 = _run_cli(home, "autoinject", "codex-shadow", stdin=payload)
    out3 = json.loads(r3.stdout)
    assert out3["decision"] == "INJECT"
    assert out3["packet"] == out["packet"]
    assert out3["candidate_ids"] == out["candidate_ids"]


def test_prompt_key_accepted_as_task(tmp_path) -> None:
    home = tmp_path / "brain"
    _init_and_seed(home)
    payload = json.dumps({"session_id": "s1", "project": "proj-a", "prompt": "migration ordering"})
    r = _run_cli(home, "autoinject", "codex-shadow", stdin=payload)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["decision"] == "INJECT"


def test_malformed_stdin_fails_open(tmp_path) -> None:
    home = tmp_path / "brain"
    _init_and_seed(home)
    for bad in ("not json", "{", "", '{"task": 42}', '{"task": ""}'):
        r = _run_cli(home, "autoinject", "codex-shadow", stdin=bad)
        assert r.returncode == 0, (bad, r.stderr)
        out = json.loads(r.stdout)
        assert out["decision"] == "NO_INJECTION"
        assert out["reason"] == "BRAIN_UNAVAILABLE"
        assert out["packet"] is None
        assert out["delivery_id"] is None


def test_no_argv_task_path_exists(tmp_path) -> None:
    """The task can never reach argv: --task on codex-shadow is a usage error."""
    home = tmp_path / "brain"
    _init_and_seed(home)
    r = _run_cli(
        home, "autoinject", "codex-shadow", "--task", "migration ordering", stdin=_payload()
    )
    assert r.returncode == 2  # argparse usage error
    assert "unrecognized arguments" in r.stderr


def test_wrong_project_stdin_no_injection(tmp_path) -> None:
    home = tmp_path / "brain"
    _init_and_seed(home)
    r = _run_cli(home, "autoinject", "codex-shadow", stdin=_payload(project="proj-zzz"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["decision"] == "NO_INJECTION"
    assert out["reason"] in ("WRONG_PROJECT", "NO_RELEVANT_MEMORY")


def test_codex_project_from_cwd_ladder(tmp_path) -> None:
    """No explicit `project` field: codex-shadow must resolve project_id via
    `autoinject._resolve_project_id`'s cwd ladder (registry repo_path match),
    not silently fall through to "default" for harnesses that only ever send
    `cwd`. An explicit `project` field still wins over the ladder (rung 1)."""
    home = tmp_path / "brain"
    _init_and_seed(home)
    cwd_dir = tmp_path / "workdir"
    cwd_dir.mkdir()
    registry.add_project(home, cwd_dir, project_id="proj-a")

    # No `project` field at all -> must resolve "proj-a" via the cwd ladder,
    # not fall through to "default" (where the seeded memory is invisible).
    payload = json.dumps(
        {
            "session_id": "codex-cwd-ladder-1",
            "task": "migration ordering",
            "agent_id": "a1",
            "branch": "main",
            "role": "worker",
            "source": "UserPromptSubmit",
            "cwd": str(cwd_dir),
        }
    )
    r = _run_cli(home, "autoinject", "codex-shadow", stdin=payload)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["decision"] == "INJECT"

    # An explicit `project` field still wins over the cwd ladder.
    payload2 = json.dumps(
        {
            "session_id": "codex-cwd-ladder-2",
            "project": "proj-zzz",
            "task": "migration ordering",
            "agent_id": "a1",
            "branch": "main",
            "role": "worker",
            "source": "UserPromptSubmit",
            "cwd": str(cwd_dir),
        }
    )
    r2 = _run_cli(home, "autoinject", "codex-shadow", stdin=payload2)
    assert r2.returncode == 0, r2.stderr
    out2 = json.loads(r2.stdout)
    assert out2["decision"] == "NO_INJECTION"
    assert out2["reason"] in ("WRONG_PROJECT", "NO_RELEVANT_MEMORY")
