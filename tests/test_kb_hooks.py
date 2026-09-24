"""V3 core: the Claude Code hook adapter (`brain hook claude-code`)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from second_brain.kb import cli, hooks, records, views
from second_brain.kb.records import Record


def _home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "brain"
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = home / "projects" / "p1" / "project.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        f'id = "p1"\nname = "Project One"\npaths = ["{repo.as_posix()}"]\n', encoding="utf-8"
    )
    return home, repo


def _save(home: Path, **kw: object) -> Record:
    base: dict[str, object] = {
        "id": records.new_id(),
        "title": "Run migrations in numeric order",
        "type": "gotcha",
        "project": "p1",
        "status": "current",
        "grade": "TESTED",
        "recorded_at": "2026-09-01T00:00:00+00:00",
    }
    base.update(kw)
    rec = Record(**base)  # type: ignore[arg-type]
    records.save(home, rec)
    return rec


def _run(home: Path, payload: object, monkeypatch: pytest.MonkeyPatch, capsys) -> dict:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook", "claude-code", "--home", str(home)]) == 0
    return json.loads(capsys.readouterr().out)


def test_session_start_injects_the_project_brief(tmp_path, monkeypatch, capsys) -> None:
    home, repo = _home(tmp_path)
    rec = _save(home)
    out = _run(
        home,
        {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(repo)},
        monkeypatch,
        capsys,
    )
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert f"[{rec.id}]" in context and "Project One" in context
    assert views.estimate_tokens(context) <= views.BRIEF_TOKEN_BUDGET


def test_session_start_uses_the_compiled_view(tmp_path, monkeypatch, capsys) -> None:
    home, repo = _home(tmp_path)
    _save(home)
    views.compile_views(home)
    (home / "views" / "p1" / "brief.md").write_text("compiled marker\n", encoding="utf-8")
    out = _run(home, {"hook_event_name": "SessionStart", "cwd": str(repo)}, monkeypatch, capsys)
    assert out["hookSpecificOutput"]["additionalContext"] == "compiled marker\n"


def test_nothing_current_means_nothing_injected(tmp_path, monkeypatch, capsys) -> None:
    home, repo = _home(tmp_path)
    _save(home, status="candidate")
    _save(home, project="p2")
    payload = {"hook_event_name": "SessionStart", "source": "resume", "cwd": str(repo)}
    assert _run(home, payload, monkeypatch, capsys) == {}


def test_native_auto_memory_is_not_paid_twice(tmp_path, monkeypatch, capsys) -> None:
    home, repo = _home(tmp_path)
    dup = _save(home, title="Run migrations in numeric order")
    kept = _save(home, title="Seed the cloud corpus before evals", type="procedure")
    transcript = tmp_path / "claude" / "session.jsonl"
    (transcript.parent / "memory").mkdir(parents=True)
    (transcript.parent / "memory" / "MEMORY.md").write_text(
        "- Run migrations in numeric order.\n", encoding="utf-8"
    )
    payload = {
        "hook_event_name": "SessionStart",
        "cwd": str(repo),
        "transcript_path": str(transcript),
    }
    context = _run(home, payload, monkeypatch, capsys)["hookSpecificOutput"]["additionalContext"]
    assert dup.id not in context and kept.id in context


def test_tool_failure_gets_one_tested_correction(tmp_path, monkeypatch, capsys) -> None:
    home, repo = _home(tmp_path)
    fix = _save(
        home,
        title="Unset PYTHONHOME before running the venv",
        type="correction",
        trigger_errors=("SRE module mismatch",),
    )
    _save(
        home,
        title="Observed only",
        type="correction",
        grade="OBSERVED",
        trigger_errors=("SRE module mismatch: long",),
    )
    payload = {
        "hook_event_name": "PostToolUseFailure",
        "cwd": str(repo),
        "tool_name": "Bash",
        "error": "AssertionError: SRE module mismatch: long trace",
    }
    out = _run(home, payload, monkeypatch, capsys)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"
    assert context.startswith("Brain correction (advisory):") and f"[{fix.id}]" in context
    assert views.estimate_tokens(context) <= views.CORRECTION_TOKEN_BUDGET + 20


@pytest.mark.parametrize(
    "payload",
    [
        {"hook_event_name": "PostToolUseFailure", "error": "no known pattern here"},
        {
            "hook_event_name": "PostToolUseFailure",
            "error": "SRE module mismatch",
            "is_interrupt": True,
        },
        {"hook_event_name": "UserPromptSubmit", "prompt": "Unset PYTHONHOME"},
        {"hook_event_name": "Stop"},
    ],
)
def test_other_events_add_nothing(tmp_path, monkeypatch, capsys, payload: dict) -> None:
    home, repo = _home(tmp_path)
    _save(home, type="correction", trigger_errors=("SRE module mismatch",))
    assert _run(home, {**payload, "cwd": str(repo)}, monkeypatch, capsys) == {}


def test_fails_open(tmp_path, monkeypatch, capsys) -> None:
    home, _ = _home(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
    assert cli.main(["hook", "claude-code", "--home", str(home)]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    monkeypatch.delenv("SECOND_BRAIN_HOME", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"hook_event_name": "SessionStart"}'))
    assert cli.main(["hook", "claude-code"]) == 0  # no home at all
    assert json.loads(capsys.readouterr().out) == {}


def test_telemetry_records_event_tokens_and_latency(tmp_path, monkeypatch, capsys) -> None:
    home, repo = _home(tmp_path)
    _save(home)
    _run(home, {"hook_event_name": "SessionStart", "cwd": str(repo)}, monkeypatch, capsys)
    line = json.loads((home / "telemetry" / "kb-hooks.jsonl").read_text().splitlines()[-1])
    assert line["event"] == "SessionStart" and line["tokens"] > 0 and line["ms"] >= 0


def test_real_process_latency(tmp_path) -> None:
    """End to end as the host runs it: a fresh interpreter per hook call."""
    home, repo = _home(tmp_path)
    for i in range(50):
        _save(home, title=f"Gotcha number {i} about builds", id=f"mem-{i:012x}")
    views.compile_views(home)
    payload = json.dumps({"hook_event_name": "SessionStart", "cwd": str(repo)})
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        done = subprocess.run(
            [sys.executable, "-m", "second_brain.kb", "hook", "claude-code", "--home", str(home)],
            input=payload,
            capture_output=True,
            text=True,
            check=True,
        )
        timings.append((time.perf_counter() - started) * 1000)
        assert "additionalContext" in done.stdout
    print(f"hook process ms: {[round(t) for t in timings]}")
    assert min(timings) < 1000
    assert hooks.handle(home, {"hook_event_name": "Unknown"}) == {}
