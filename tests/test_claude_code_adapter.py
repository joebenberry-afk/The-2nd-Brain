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
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
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


def _telemetry_kinds(home: Path, session_id: str) -> list[str]:
    telem = home / "telemetry" / "agent-performance" / f"{session_id}.jsonl"
    if not telem.exists():
        return []
    return [
        json.loads(line)["kind"] for line in telem.read_text(encoding="utf-8").splitlines() if line
    ]


def _telemetry_sessions(home: Path, session_id: str) -> set[str]:
    telem = home / "telemetry" / "agent-performance" / f"{session_id}.jsonl"
    return {
        json.loads(line)["session"]
        for line in telem.read_text(encoding="utf-8").splitlines()
        if line
    }


def _session_start_payload(session_id: str, cwd: Path, source: str = "startup") -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "cwd": str(cwd),
            "hook_event_name": "SessionStart",
            "source": source,
        }
    )


def _stop_payload(session_id: str, cwd: Path, message: str = "did some work") -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "cwd": str(cwd),
            "hook_event_name": "Stop",
            "last_assistant_message": message,
        }
    )


def _precompact_payload(session_id: str, cwd: Path) -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "cwd": str(cwd),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }
    )


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


def test_stop_records_claude_code_stop_turn_without_writing_memory(
    home: Path, git_project: Path
) -> None:
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
        json.loads(line)["kind"] for line in telem.read_text(encoding="utf-8").splitlines() if line
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


# --- P3a.1: SessionStart lifecycle dedup -----------------------------------
# Claude Code fires SessionStart again on resume/clear/compact/fork, not just
# real startup (source in {startup,resume,clear,compact,fork}), and Stop/
# PreCompact each also call BrainLifecycle.start_session() as a side effect.
# One logical Claude Code session must produce exactly one session_started
# telemetry record, no matter how many hook invocations touch it.


def test_startup_records_exactly_one_session_started(home: Path, git_project: Path) -> None:
    sid = "claude-sess-dedup1"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project),
        cwd=git_project,
    )
    kinds = _telemetry_kinds(home, sid)
    assert kinds.count("session_started") == 1


def test_repeated_startup_same_session_still_one(home: Path, git_project: Path) -> None:
    sid = "claude-sess-dedup2"
    for _ in range(3):
        _run_cli(
            home,
            "autoinject",
            "claude-code-hook",
            stdin=_session_start_payload(sid, git_project),
            cwd=git_project,
        )
    kinds = _telemetry_kinds(home, sid)
    assert kinds.count("session_started") == 1


def test_startup_stop_resume_same_brain_session(home: Path, git_project: Path) -> None:
    sid = "claude-sess-dedup3"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project, "startup"),
        cwd=git_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_stop_payload(sid, git_project),
        cwd=git_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project, "resume"),
        cwd=git_project,
    )
    kinds = _telemetry_kinds(home, sid)
    assert kinds.count("session_started") == 1  # not re-created by Stop or resume
    assert kinds.count("claude_code_stop_turn") == 1
    assert _telemetry_sessions(home, sid) == {sid}  # every record belongs to the same session


def test_startup_precompact_records_exactly_one_session_started(
    home: Path, git_project: Path
) -> None:
    sid = "claude-sess-dedup4"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project),
        cwd=git_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload(sid, git_project),
        cwd=git_project,
    )
    kinds = _telemetry_kinds(home, sid)
    assert kinds.count("session_started") == 1

    from second_brain import ledger

    with ledger.LedgerStore(home, sid).open() as store:
        rows = store.search("compaction_started", event_type="compaction_started", limit=10)
    assert len(rows) == 1  # PreCompact still attaches to/checkpoints the ledger normally


def test_startup_precompact_resume_still_one_session_started(home: Path, git_project: Path) -> None:
    sid = "claude-sess-dedup5"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project, "startup"),
        cwd=git_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload(sid, git_project),
        cwd=git_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project, "resume"),
        cwd=git_project,
    )
    kinds = _telemetry_kinds(home, sid)
    assert kinds.count("session_started") == 1


def test_multiple_stop_turns_stay_in_same_active_session(home: Path, git_project: Path) -> None:
    sid = "claude-sess-dedup6"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project),
        cwd=git_project,
    )
    for _ in range(3):
        _run_cli(
            home,
            "autoinject",
            "claude-code-hook",
            stdin=_stop_payload(sid, git_project),
            cwd=git_project,
        )
    kinds = _telemetry_kinds(home, sid)
    assert kinds.count("session_started") == 1
    assert kinds.count("claude_code_stop_turn") == 3
    assert _telemetry_sessions(home, sid) == {sid}


def test_different_host_sessions_stay_distinct(home: Path, git_project: Path) -> None:
    sid_a, sid_b = "claude-sess-dedupA", "claude-sess-dedupB"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid_a, git_project),
        cwd=git_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid_b, git_project),
        cwd=git_project,
    )
    assert _telemetry_kinds(home, sid_a).count("session_started") == 1
    assert _telemetry_kinds(home, sid_b).count("session_started") == 1


def test_session_dedup_check_fails_open_on_corrupt_telemetry_file(
    home: Path, git_project: Path
) -> None:
    sid = "claude-sess-dedup7"
    telem_dir = home / "telemetry" / "agent-performance"
    telem_dir.mkdir(parents=True, exist_ok=True)
    (telem_dir / f"{sid}.jsonl").write_text("not json\n{also not json\n", encoding="utf-8")
    result = _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, git_project),
        cwd=git_project,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}


# --- P3a.2: PreCompact -> Ledger session identity boundary ------------------
# `LedgerStore.create_session()` and every other ledger primitive (events,
# _ensure_session_row, session_dir) key sessions rows by
# `ledger.internal_session_id()` (full sha256 hex). The Claude Code hook's
# own `session` identity uses a different scheme ("is-"+sha256[:12], the
# AutoInject/telemetry convention). Passing that mismatched identity into
# `create_session()` silently created a second, orphaned `sessions` row via
# `_ensure_session_row`'s host="prime" fallback. These tests prove the fix:
# exactly one canonical ledger sessions row per Claude Code session, no
# phantom prime row, and the compaction_started event FK-references it.


@pytest.fixture
def named_project(git_project: Path) -> Path:
    brain_dir = git_project / ".brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    (brain_dir / "project.toml").write_text('id = "second-brain"\n', encoding="utf-8")
    return git_project


def _sessions_rows(home: Path, session_id: str) -> list[dict]:
    import sqlite3

    from second_brain import ledger

    dbfile = ledger.session_dir(home, session_id) / "ledger.sqlite"
    conn = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()]
    finally:
        conn.close()


def _events_rows(home: Path, session_id: str, event_type: str) -> list[dict]:
    import sqlite3

    from second_brain import ledger

    dbfile = ledger.session_dir(home, session_id) / "ledger.sqlite"
    conn = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM events WHERE event_type = ?", (event_type,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def test_precompact_creates_exactly_one_canonical_ledger_session_row(
    home: Path, named_project: Path
) -> None:
    from second_brain import ledger

    sid = "claude-sess-p3a2-1"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload(sid, named_project),
        cwd=named_project,
    )
    rows = _sessions_rows(home, sid)
    assert len(rows) == 1  # no phantom second row
    row = rows[0]
    assert row["internal_session_id"] == ledger.internal_session_id(sid)
    assert row["host"] == "claude-code"
    assert row["project_id"] == "second-brain"
    assert row["status"] == "active"
    assert row["host"] != "prime"  # the phantom-row regression this fixes


def test_precompact_creates_no_phantom_prime_row(home: Path, named_project: Path) -> None:
    sid = "claude-sess-p3a2-2"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload(sid, named_project),
        cwd=named_project,
    )
    rows = _sessions_rows(home, sid)
    assert not any(r["host"] == "prime" for r in rows)


def test_precompact_event_references_canonical_session_row(home: Path, named_project: Path) -> None:
    from second_brain import ledger

    sid = "claude-sess-p3a2-3"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload(sid, named_project),
        cwd=named_project,
    )
    session_rows = _sessions_rows(home, sid)
    assert len(session_rows) == 1
    event_rows = _events_rows(home, sid, "compaction_started")
    assert len(event_rows) == 1
    assert event_rows[0]["internal_session_id"] == session_rows[0]["internal_session_id"]
    assert event_rows[0]["internal_session_id"] == ledger.internal_session_id(sid)


def test_precompact_repeated_invocation_stays_one_session_row(
    home: Path, named_project: Path
) -> None:
    sid = "claude-sess-p3a2-4"
    payload = _precompact_payload(sid, named_project)
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=named_project)
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=named_project)
    _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=named_project)
    rows = _sessions_rows(home, sid)
    assert len(rows) == 1  # INSERT OR REPLACE on the same canonical PK, not 3 rows
    assert _events_rows(home, sid, "compaction_started") == _events_rows(
        home, sid, "compaction_started"
    )
    assert len(_events_rows(home, sid, "compaction_started")) == 1  # content-hash dedup intact


def test_precompact_fix_does_not_change_telemetry_identity_semantics(
    home: Path, named_project: Path
) -> None:
    # SessionStart -> Stop -> PreCompact -> Stop: session_started stays
    # singular and stop_turn count is unaffected by the ledger-identity fix.
    sid = "claude-sess-p3a2-5"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_session_start_payload(sid, named_project),
        cwd=named_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_stop_payload(sid, named_project),
        cwd=named_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload(sid, named_project),
        cwd=named_project,
    )
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_stop_payload(sid, named_project),
        cwd=named_project,
    )
    kinds = _telemetry_kinds(home, sid)
    assert kinds.count("session_started") == 1
    assert kinds.count("claude_code_stop_turn") == 2
    assert _telemetry_sessions(home, sid) == {sid}


def test_ledger_rehydration_still_works_after_identity_fix(home: Path, named_project: Path) -> None:
    sid = "claude-sess-p3a2-6"
    _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload(sid, named_project),
        cwd=named_project,
    )
    result = _run_cli(home, "ledger", "rehydrate", sid, "--level", "1")
    assert result.returncode == 0
    out = json.loads(result.stdout.strip())
    assert out.get("level") == 1


def test_precompact_brain_unavailable_fails_open(tmp_path: Path, git_project: Path) -> None:
    missing_home = tmp_path / "does-not-exist"
    result = _run_cli(
        missing_home,
        "autoinject",
        "claude-code-hook",
        stdin=_precompact_payload("claude-sess-p3a2-7", git_project),
        cwd=git_project,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}


def test_claude_stop_hook_emits_assistant_usage_from_transcript(
    home: Path, git_project: Path, tmp_path: Path
) -> None:
    transcript = tmp_path / "claude-session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "assistant-1",
                        "message": {
                            "role": "assistant",
                            "usage": {
                                "input_tokens": 101,
                                "output_tokens": 17,
                                "cache_read_input_tokens": 80,
                                "cache_creation_input_tokens": 21,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "assistant-2",
                        "message": {
                            "role": "assistant",
                            "usage": {
                                "input_tokens": 202,
                                "output_tokens": 19,
                                "cache_read_input_tokens": 160,
                                "cache_creation_input_tokens": 42,
                            },
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload = json.dumps(
        {
            "session_id": "claude-sess-usage",
            "cwd": str(git_project),
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
        }
    )

    first = _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)
    second = _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)
    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout.strip() or "{}") == {}
    assert json.loads(second.stdout.strip() or "{}") == {}

    telem = home / "telemetry" / "agent-performance" / "claude-sess-usage.jsonl"
    rows = [
        record
        for line in telem.read_text(encoding="utf-8").splitlines()
        if line
        for record in [json.loads(line)]
        if record.get("kind") == "assistant_usage"
    ]
    assert all(row["v"] == 3 for row in rows)
    assert len(rows) == 2
    assert [row["uuid"] for row in rows] == ["assistant-1", "assistant-2"]
    assert all(row["harness"] == "claude-code" for row in rows)
    assert [row["cache_write_tokens"] for row in rows] == [21, 42]
    assert not any("cache_creation_input_tokens" in row for row in rows)
    assert all(row["cache_state"] is None for row in rows)

    from second_brain import ledger

    cursor = (
        home
        / "state"
        / "sessions"
        / ledger.internal_session_id("claude-sess-usage")
        / "claude-usage-cursor.json"
    )
    assert json.loads(cursor.read_text(encoding="utf-8")) == {"last_uuid": "assistant-2"}


def test_extract_usage_tail_is_bounded_and_preserves_only_usage(
    tmp_path: Path,
) -> None:
    from second_brain.antigravity_transcript import extract_usage_tail

    transcript = tmp_path / "large.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "large",
                "message": {
                    "role": "assistant",
                    "content": "secret transcript " * 30_000,
                    "usage": {"input_tokens": 1},
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "uuid": "tail",
                "message": {"role": "assistant", "usage": {"output_tokens": 7}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    records = extract_usage_tail(transcript)
    assert records == [{"uuid": "tail", "output_tokens": 7}]


def test_claude_stop_maps_optional_cache_state(
    home: Path, git_project: Path, tmp_path: Path
) -> None:
    transcript = tmp_path / "cache.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "cached",
                "message": {"role": "assistant", "usage": {"input_tokens": 3}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    payload = json.dumps(
        {
            "session_id": "claude-sess-cache",
            "cwd": str(git_project),
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "cache_hit_ratio": 0.75,
            "re_cached_tokens": 12,
        }
    )
    result = _run_cli(home, "autoinject", "claude-code-hook", stdin=payload, cwd=git_project)
    assert result.returncode == 0
    rows = [
        json.loads(line)
        for line in (home / "telemetry" / "agent-performance" / "claude-sess-cache.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and json.loads(line).get("kind") == "assistant_usage"
    ]
    assert rows[0]["cache_state"] == {"cache_hit_ratio": 0.75, "re_cached_tokens": 12}


def test_windows_claude_launcher_captures_unicode_without_persisting_content(
    home: Path, git_project: Path
) -> None:
    import hashlib

    if os.name != "nt":
        pytest.skip("Windows PowerShell transport")
    prompt = "Private Unicode prompt \u2014 \u03bb"
    session_id = "claude-unicode-transport"
    payload = {
        "session_id": session_id,
        "cwd": str(git_project),
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
    }
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    env.update({
        "SECOND_BRAIN_HOME": str(home),
        "SECOND_BRAIN_PYTHON": sys.executable,
        "SECOND_BRAIN_AUTOINJECT_MODE": "advisory",
        "PYTHONIOENCODING": "cp1252",
    })
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "brainstem" / "adapters" / "claude-code" / "scripts" / "run-hook.ps1"),
        ],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    raw = (home / "telemetry" / "agent-performance" / f"{session_id}.jsonl").read_text(
        encoding="utf-8"
    )
    rows = [json.loads(line) for line in raw.splitlines() if line]
    record = next(row for row in rows if row["kind"] == "claude_code_user_prompt")
    assert record["prompt_bytes"] == len(prompt.encode("utf-8"))
    assert record["prompt_sha256"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert prompt not in raw


def test_claude_prompt_and_tool_hooks_persist_only_telemetry(home: Path, git_project: Path) -> None:
    prompt = "secret prompt that must not be persisted"
    output = "secret tool output that must not be persisted"
    prompt_result = _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=json.dumps(
            {
                "session_id": "claude-sess-events",
                "cwd": str(git_project),
                "hook_event_name": "UserPromptSubmit",
                "prompt": prompt,
            }
        ),
        cwd=git_project,
    )
    tool_result = _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=json.dumps(
            {
                "session_id": "claude-sess-events",
                "cwd": str(git_project),
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_response": output,
            }
        ),
        cwd=git_project,
    )
    assert prompt_result.returncode == tool_result.returncode == 0
    rows = [
        json.loads(line)
        for line in (home / "telemetry" / "agent-performance" / "claude-sess-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    prompt_row = next(row for row in rows if row["kind"] == "claude_code_user_prompt")
    tool_row = next(row for row in rows if row["kind"] == "claude_code_tool_result")
    assert prompt_row["prompt_bytes"] == len(prompt.encode())
    assert prompt_row["prompt_sha256"]
    assert tool_row["tool"] == "Bash"
    assert tool_row["output_bytes"] == len(output.encode())
    assert tool_row["output_sha256"]
    raw = json.dumps(rows)
    assert prompt not in raw
    assert output not in raw


def test_claude_hook_malformed_surrogate_payload_fails_open(home: Path, tmp_path: Path) -> None:
    result = _run_cli(
        home,
        "autoinject",
        "claude-code-hook",
        stdin=json.dumps(
            {
                "session_id": "\ud800",
                "cwd": str(tmp_path),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "\ud800",
            }
        ),
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}


def test_claude_aux_hook_surrogate_prompt_and_tool_fields_fail_open(
    home: Path, tmp_path: Path
) -> None:
    for event, extra in (
        ("UserPromptSubmit", {"prompt": "\ud800"}),
        ("PostToolUse", {"tool_name": "\ud800", "tool_response": "\ud800"}),
    ):
        result = _run_cli(
            home,
            "autoinject",
            "claude-code-hook",
            stdin=json.dumps(
                {
                    "session_id": "claude-sess-surrogate-fields",
                    "cwd": str(tmp_path),
                    "hook_event_name": event,
                    **extra,
                }
            ),
            cwd=tmp_path,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout.strip() or "{}") == {}


def test_claude_usage_cursor_waits_for_successful_writer(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from second_brain import autoinject, cli

    transcript = tmp_path / "cursor.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "retry-me",
                "message": {"role": "assistant", "usage": {"input_tokens": 1}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(autoinject, "_append_telemetry", lambda *args, **kwargs: False)
    cli._claude_usage_records(home, "claude-sess-writer-failure", str(transcript), None)
    from second_brain import ledger

    cursor = ledger.session_dir(home, "claude-sess-writer-failure") / "claude-usage-cursor.json"
    assert not cursor.exists()


def test_claude_tool_call_args_extracts_nested_assistant_tool_use(tmp_path: Path) -> None:
    from second_brain import cli

    memory_id = "mem-nested-tool"
    transcript = tmp_path / "nested-tool.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "bash",
                            "input": {"command": f"echo {memory_id}"},
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    args = cli._claude_tool_call_args(str(transcript))
    assert args == [{"command": f"echo {memory_id}"}]


def test_transcript_tool_calls_extracts_antigravity_model_record(tmp_path: Path) -> None:
    from second_brain import cli

    memory_id = "mem-model-tool"
    transcript = tmp_path / "model-tool.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "view_file", "args": {"memory_id": memory_id}}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert cli._claude_tool_call_args(str(transcript)) == [{"memory_id": memory_id}]
