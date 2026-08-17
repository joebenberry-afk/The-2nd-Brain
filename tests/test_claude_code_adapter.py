"""Claude Code lifecycle hook adapter acceptance tests (P3a).

Claude Code's native hook payload (per the hooks reference) is a single
JSON object on stdin with at least: session_id, cwd, hook_event_name, and
(for SessionStart) source in {startup, resume, clear, compact, fork}.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(
    home: Path,
    *args: str,
    stdin: str = "",
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or home),
        input=stdin,
        timeout=120,
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from conftest import make_brain

    return make_brain(tmp_path / "brain", monkeypatch)


def test_session_start_returns_empty_no_active_retrieval(home: Path, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    payload = json.dumps(
        {
            "session_id": "claude-sess-1",
            "cwd": str(project),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
    )
    result = _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=project)
    assert result.returncode == 0
    out = json.loads(result.stdout.strip() or "{}")
    # SessionStart must never carry retrieved memory/context - empty object only.
    assert out == {}


def test_session_start_records_lightweight_telemetry(home: Path, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    payload = json.dumps(
        {
            "session_id": "claude-sess-2",
            "cwd": str(project),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
    )
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=project)
    telem = home / "telemetry" / "agent-performance" / "claude-sess-2.jsonl"
    assert telem.exists()
    lines = [json.loads(line) for line in telem.read_text(encoding="utf-8").splitlines() if line]
    kinds = {rec["kind"] for rec in lines}
    assert "session_started" in kinds


def test_session_start_brain_unavailable_fails_open(tmp_path: Path) -> None:
    # home does not exist / is not initialized -> handler must still exit 0
    # with {} rather than raising or crashing Claude Code startup.
    missing_home = tmp_path / "does-not-exist"
    payload = json.dumps(
        {
            "session_id": "x",
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
    )
    result = _run_cli(missing_home, "autoinject", "claude-code-hook", stdin=payload, cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}


def test_malformed_stdin_fails_open(home: Path, tmp_path: Path) -> None:
    result = _run_cli(home, "autoinject", "claude-code-hook", stdin="not json", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "t@example.com")
    _git(project, "config", "user.name", "t")
    (project / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(project, "add", "a.txt")
    _git(project, "commit", "-q", "-m", "init")
    return project


def _write_transcript(path: Path, user_text: str) -> None:
    path.write_text(
        json.dumps({"role": "user", "content": user_text}) + "\n",
        encoding="utf-8",
    )


def test_precompact_writes_bounded_resume_snapshot(
    home: Path, git_project: Path, tmp_path: Path
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, "Add retry logic to the fetch client")
    payload = json.dumps(
        {
            "session_id": "claude-sess-pc",
            "cwd": str(git_project),
            "hook_event_name": "PreCompact",
            "trigger": "manual",
            "transcript_path": str(transcript),
        }
    )
    result = _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}  # never blocks compaction

    from second_brain import ledger

    with ledger.LedgerStore(home, "claude-sess-pc").open() as store:
        rows = store.search("compaction_started", event_type="compaction_started", limit=10)
    assert len(rows) == 1
    payload_json = rows[0].get("payload_json")
    payload_out = (
        json.loads(payload_json)
        if isinstance(payload_json, str)
        else rows[0].get("payload", rows[0])
    )
    assert payload_out["goal"] == "Add retry logic to the fetch client"
    assert payload_out["branch"]
    assert payload_out["commit"]
    assert payload_out["trigger"] == "manual"


def test_precompact_does_not_store_full_transcript(
    home: Path, git_project: Path, tmp_path: Path
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    huge_line = json.dumps({"role": "assistant", "content": "x" * 50_000})
    _write_transcript(transcript, "short goal")
    with transcript.open("a", encoding="utf-8") as f:
        f.write(huge_line + "\n")
    payload = json.dumps(
        {
            "session_id": "claude-sess-pc2",
            "cwd": str(git_project),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
            "transcript_path": str(transcript),
        }
    )
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)

    from second_brain import ledger

    with ledger.LedgerStore(home, "claude-sess-pc2").open() as store:
        rows = store.search("compaction_started", event_type="compaction_started", limit=10)
    raw = json.dumps(rows[0])
    assert "x" * 1000 not in raw  # the 50KB assistant blob must never be persisted
    assert len(raw.encode("utf-8")) < 8000  # bounded (well under ~2000 tokens)


def test_precompact_duplicate_invocation_is_deduplicated(
    home: Path, git_project: Path, tmp_path: Path
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, "same goal twice")
    payload = json.dumps(
        {
            "session_id": "claude-sess-pc3",
            "cwd": str(git_project),
            "hook_event_name": "PreCompact",
            "trigger": "manual",
            "transcript_path": str(transcript),
        }
    )
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)  # duplicate

    from second_brain import ledger

    with ledger.LedgerStore(home, "claude-sess-pc3").open() as store:
        rows = store.search("compaction_started", event_type="compaction_started", limit=10)
    assert len(rows) == 1  # not 2: idempotent on identical content


def test_stop_records_turn_end_without_writing_memory(home: Path, git_project: Path) -> None:
    payload = json.dumps(
        {
            "session_id": "claude-sess-stop1",
            "cwd": str(git_project),
            "hook_event_name": "Stop",
            "last_assistant_message": "Ran `rg TODO` across the repo, found 3 hits.",
        }
    )
    result = _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}

    telem = home / "telemetry" / "agent-performance" / "claude-sess-stop1.jsonl"
    kinds = {
        json.loads(line)["kind"]
        for line in telem.read_text(encoding="utf-8").splitlines()
        if line
    }
    assert "claude_code_stop_turn" in kinds

    from second_brain import semantic

    memories = semantic.list_memories(home, scope="project")
    assert memories == []  # routine turn -> no candidate memory


def test_stop_with_marker_writes_one_candidate(home: Path, git_project: Path) -> None:
    marker = (
        "Fixed the flaky retry test.\n\n"
        "<!--second-brain-candidate\n"
        "title: Retry test flake root cause\n"
        "observation: test asserted wall-clock timing under 50ms; CI runners jitter above that\n"
        "evidence: tests/test_retry.py::test_backoff_timing failing log at CI run 4821\n"
        "-->"
    )
    payload = json.dumps(
        {
            "session_id": "claude-sess-stop2",
            "cwd": str(git_project),
            "hook_event_name": "Stop",
            "last_assistant_message": marker,
        }
    )
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)

    from second_brain import semantic

    memories = semantic.list_memories(home, scope="project")
    assert len(memories) == 1
    mem = memories[0]
    assert mem["status"] == "candidate"  # never canonical
    assert "Retry test flake root cause" in mem["title"]


def test_stop_marker_without_evidence_is_not_written(home: Path, git_project: Path) -> None:
    marker = (
        "<!--second-brain-candidate\n"
        "title: Unsupported claim\n"
        "observation: probably works this way\n"
        "evidence: \n"
        "-->"
    )
    payload = json.dumps(
        {
            "session_id": "claude-sess-stop3",
            "cwd": str(git_project),
            "hook_event_name": "Stop",
            "last_assistant_message": marker,
        }
    )
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)

    from second_brain import semantic

    memories = semantic.list_memories(home, scope="project")
    assert memories == []  # empirical claim without evidence is dropped, not written


def test_stop_duplicate_turn_does_not_duplicate_candidate(home: Path, git_project: Path) -> None:
    marker = (
        "<!--second-brain-candidate\n"
        "title: Same finding twice\n"
        "observation: same text\n"
        "evidence: tests/test_x.py::test_y\n"
        "-->"
    )
    payload = json.dumps(
        {
            "session_id": "claude-sess-stop4",
            "cwd": str(git_project),
            "hook_event_name": "Stop",
            "last_assistant_message": marker,
        }
    )
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)

    from second_brain import semantic

    memories = semantic.list_memories(home, scope="project")
    assert len(memories) == 1
