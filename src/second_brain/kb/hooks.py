"""Host hook adapter for the V3 core: ``brain hook claude-code`` (one JSON object in, one out).

Push happens only at two moments here:

* ``SessionStart`` (startup, resume, clear, compact, fork) → the project brief as
  ``additionalContext``, or nothing when the project has no current records. When Claude Code's
  own auto memory (``<transcript dir>/memory/MEMORY.md``) exists, facts it already holds are left
  out of the brief so the same fact is never paid for twice.
* ``PostToolUseFailure`` → at most one tested correction whose error pattern matches, or nothing.

Every other event returns ``{}``. The adapter never blocks, vetoes or continues host work, and it
fails open: any error prints ``{}`` and exits 0. One telemetry line per call records the event,
project, delivered tokens and latency.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import projects, records, views

_SOURCES = frozenset({"startup", "resume", "clear", "compact", "fork"})


def _native_memory(payload: dict) -> str | None:
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        return None
    path = Path(transcript).parent / "memory" / "MEMORY.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _project(home: Path, payload: dict) -> projects.Project | None:
    cwd = payload.get("cwd")
    return projects.resolve(home, Path(cwd) if isinstance(cwd, str) and cwd else None)


def _view_dir(home: Path, project: projects.Project | None) -> Path:
    return Path(home) / "views" / (project.id if project is not None else "_none")


def session_brief(home: Path, payload: dict) -> str:
    project = _project(home, payload)
    native = _native_memory(payload)
    if native is None:
        compiled = _view_dir(home, project) / "brief.md"
        if compiled.is_file():
            return compiled.read_text(encoding="utf-8")
    recs, _ = records.load_all(home)
    return views.render_brief(recs, project, native_text=native)


def correction(home: Path, payload: dict) -> str:
    if payload.get("is_interrupt") is True:
        return ""
    error = payload.get("error")
    if not isinstance(error, str) or not error.strip():
        return ""
    project = _project(home, payload)
    compiled = _view_dir(home, project) / "corrections.json"
    if compiled.is_file():
        table = json.loads(compiled.read_text(encoding="utf-8"))
    else:
        recs, _ = records.load_all(home)
        table = views.correction_table(recs)
    entry = views.match_error(table, error, project)
    if entry is None:
        return ""
    return f"Brain correction (advisory): {entry['text']} [{entry['id']}]"


def handle(home: Path, payload: dict) -> dict:
    event = payload.get("hook_event_name")
    context = ""
    if event == "SessionStart" and payload.get("source", "startup") in _SOURCES:
        context = session_brief(home, payload)
    elif event == "PostToolUseFailure":
        context = correction(home, payload)
    if not context.strip():
        return {}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}


def _telemetry(home: Path, event: object, output: dict, started: float) -> None:
    context = output.get("hookSpecificOutput", {}).get("additionalContext", "")
    line = {
        "at": records.now_iso(),
        "event": event,
        "tokens": views.estimate_tokens(context) if context else 0,
        "ms": round((time.perf_counter() - started) * 1000, 2),
    }
    try:
        path = Path(home) / "telemetry" / "kb-hooks.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError:
        pass


def run_claude_code(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    output: dict = {}
    event: object = None
    home: Path | None = None
    try:
        from .cli import home_from

        home = home_from(args)
        payload = json.loads(sys.stdin.read() or "{}")
        if isinstance(payload, dict):
            event = payload.get("hook_event_name")
            output = handle(home, payload)
    except (Exception, SystemExit):  # fail open: never break the host session
        output = {}
    print(json.dumps(output))
    if home is not None:
        _telemetry(home, event, output, started)
    return 0


def register(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    hook = sub.add_parser("hook", parents=[common], help="host hook adapters (JSON on stdin)")
    hosts = hook.add_subparsers(dest="host", required=True)
    claude = hosts.add_parser("claude-code", parents=[common], help="Claude Code hook events")
    claude.set_defaults(func=run_claude_code)
