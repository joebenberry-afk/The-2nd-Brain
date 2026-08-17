# Claude Code Lifecycle Hooks (P3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Claude Code's native `SessionStart`, `PreCompact`, and `Stop` lifecycle hooks into the existing Second Brain via one new thin CLI verb (`autoinject claude-code-hook`) and a PowerShell launcher, mirroring the already-shipped Antigravity/Codex adapters — zero new subsystems.

**Architecture:** One new handler function `_cmd_claude_code_hook(home)` in `src/second_brain/cli.py`, dispatched from a new `autoinject claude-code-hook` subcommand. It reads Claude Code's native hook JSON from stdin, branches on `hook_event_name`, and calls only existing primitives: `autoinject._resolve_project_id`, `autoinject.BrainLifecycle` (telemetry-based session lifecycle), `ledger.LedgerStore`/`checkpoint_ledger` (durability/resume snapshot), `antigravity_transcript.extract_latest_user_task` (bounded transcript parsing, already harness-neutral), and `autoinject.BrainLifecycle.writeback_candidate` (candidate-only memory writes). A PowerShell launcher (`brainstem/adapters/claude-code/scripts/run-hook.ps1`) is pure transport, following the exact fail-open shape of `brainstem/adapters/antigravity/scripts/run-hook.ps1`. Hooks register in the user's global `~/.claude/settings.json` via a reversible install script mirroring `scripts/install-codex-hooks.ps1`, so the integration works in any repo the user opens with Claude Code, not just this one.

**Tech Stack:** Python 3.11 (`src/second_brain`), PowerShell 5.1 launcher, Claude Code native hooks (`.claude/settings.json`), pytest.

## Global Constraints

- Reuse only existing Brain primitives — no Claude-specific DB, ledger, telemetry backend, retrieval engine, or evidence system (per user's P3a spec).
- Implement exactly three hook events: `SessionStart`, `PreCompact`, `Stop`. Do not add `PreToolUse`, `PostToolUse`, `SubagentStop`, `UserPromptSubmit`, or `SessionEnd` in this pass.
- Fail-open everywhere: any exception in the handler → print `{}` (or nothing), exit 0. Never block Claude Code startup, compaction, or turn completion.
- No circuit breaker exists in the codebase (confirmed by survey) — copy the existing single-shot try/except convention used by `_cmd_antigravity_hook` / `_cmd_codex_shadow`. Do not build one.
- `Claude Code's Stop hook fires once per assistant turn, not once per session` (confirmed against Claude Code hooks reference). `SessionEnd` is the real once-per-session close event and is explicitly out of scope. Do not call `finalize_session()` from Stop — that would mark the session finalized after the first turn.
- PreCompact must never block compaction: never emit `{"decision": "deny"}` and never exit 2.
- Candidate memory writes go only through `autoinject.BrainLifecycle.writeback_candidate` (wraps `semantic.add_memory`, which hardcodes `status='candidate'`). Never call `semantic.curate` from any hook code — that is the only promotion path and must stay human/CLI-driven.
- No fabrication: mechanical hook code must never invent "decisions," "blockers," or "evidence" text. Only reuse what is literally present in the payload (`last_assistant_message`, `custom_instructions`), the transcript file (via the existing bounded parser), or git (`branch`/`commit`/changed files). Where the user's original P3a spec asks for fields a shell hook cannot semantically derive (validated decisions, blockers, tests run), the resume packet carries them as `null`/`[]` rather than guessed text — this gap is intentional and reported, not silently papered over.
- Timeouts: 30s per hook command (matches existing Antigravity/Codex convention — plenty for a `doctor`-class operation measured at ~0.4s).
- Windows/PowerShell environment gotcha: every launcher must clear `$env:PYTHONHOME` / `$env:PYTHONPATH` before invoking the venv Python (AGENTS.md).

---

## File Structure

- Modify `src/second_brain/cli.py`:
  - New subparser `claude-code-hook` under the existing `autoinject` subcommand group (~line 213, next to `antigravity-hook`).
  - New handler `_cmd_claude_code_hook(home: Path) -> int` (~after `_cmd_antigravity_hook`, before `_cmd_writeback`).
  - New dispatch line in `cmd_autoinject` (~line 2657).
- Create `brainstem/adapters/claude-code/scripts/run-hook.ps1` — thin transport launcher (mirrors `brainstem/adapters/antigravity/scripts/run-hook.ps1`).
- Create `brainstem/adapters/claude-code/hooks.json` — reference/template of the `"hooks"` block merged into `~/.claude/settings.json`.
- Create `brainstem/adapters/claude-code/rules/second-brain-core.md` — Claude-facing operating principles (mirrors `brainstem/adapters/antigravity/rules/second-brain-core.md`), documents the opt-in candidate-marker convention used by the Stop hook.
- Create `brainstem/adapters/claude-code/README.md` — mirrors `brainstem/codex-hooks/README.md`: what happens on each event, install/uninstall/rollback, known limits (honest about the resume-packet gap).
- Create `scripts/install-claude-code-hooks.ps1` and `scripts/uninstall-claude-code-hooks.ps1` — idempotent JSON merge/unmerge of the `"hooks"` key into `~/.claude/settings.json`, with a timestamped backup and `-RestoreBackup` (mirrors `scripts/install-codex-hooks.ps1`).
- Modify `brainstem/telemetry/SCHEMA.md` — add the new record kinds (`claude_code_session_start`, `claude_code_precompact`, `claude_code_stop_turn`, `claude_code_stop_candidate_written`) as additive rows.
- Create `tests/test_claude_code_adapter.py` — acceptance tests for all three events, mirroring `tests/test_antigravity_adapter.py`'s subprocess-CLI style.

---

## Task 1: `claude-code-hook` CLI verb — SessionStart

**Files:**
- Modify: `src/second_brain/cli.py:213` (subparser), `src/second_brain/cli.py` after `_cmd_antigravity_hook` (~line 2277, new function), `src/second_brain/cli.py:2657` (dispatch)
- Test: `tests/test_claude_code_adapter.py`

**Interfaces:**
- Consumes: `autoinject._resolve_project_id(home, cwd, explicit)`, `contracts.BrainSessionIdentity`, `autoinject.BrainLifecycle(home, session).start_session(session)`, `contracts.canonical_json`
- Produces: `_cmd_claude_code_hook(home: Path) -> int` — reads one JSON object from stdin, writes one JSON object (or `{}`) to stdout, always returns 0. Later tasks (PreCompact, Stop) extend this same function with more `if event == "...":` branches.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_claude_code_adapter.py
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
def home(tmp_path: Path) -> Path:
    h = tmp_path / "brain"
    h.mkdir(parents=True)
    return h


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
    # SessionStart must never carry retrieved memory/context — empty object only.
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
        {"session_id": "x", "cwd": str(tmp_path), "hook_event_name": "SessionStart", "source": "startup"}
    )
    result = _run_cli(missing_home, "autoinject", "claude-code-hook", stdin=payload, cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}


def test_malformed_stdin_fails_open(home: Path, tmp_path: Path) -> None:
    result = _run_cli(home, "autoinject", "claude-code-hook", stdin="not json", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout.strip() or "{}") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\test_claude_code_adapter.py -v`
Expected: FAIL — `claude-code-hook` is not a recognized `autoinject` subcommand (argparse error / exit code 2).

- [ ] **Step 3: Add the subparser**

In `src/second_brain/cli.py`, immediately after the existing `antigravity-hook` subparser block (~line 213):

```python
    ais.add_parser(
        "claude-code-hook",
        parents=[home_parent],
        help="Claude Code hook adapter: SessionStart/PreCompact/Stop JSON on stdin -> JSON on stdout",
    )
```

- [ ] **Step 4: Implement the SessionStart branch**

Add this function in `src/second_brain/cli.py`, directly after `_cmd_antigravity_hook` (before `_cmd_writeback`):

```python
def _cmd_claude_code_hook(home: Path) -> int:
    """Claude Code native lifecycle hook adapter (P3a).

    Reads ONE JSON object from stdin — Claude Code's own hook payload
    shape: {session_id, cwd, hook_event_name, transcript_path,
    last_assistant_message (Stop only), source (SessionStart only, one of
    startup/resume/clear/compact/fork), trigger (PreCompact only, manual/
    auto), custom_instructions (PreCompact only)}.

    SessionStart: register the harness (host="claude-code") via the same
    telemetry-based BrainLifecycle used by Antigravity/Codex — no ledger
    write, no memory retrieval, no context injection. Always prints "{}".

    Fail-open: any error or malformed input -> "{}", exit 0. Claude Code
    must never fail to start, compact, or finish a turn because the Brain
    is unavailable.
    """
    import json

    from . import autoinject, contracts

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except Exception:
        payload = None
    payload_dict = payload if isinstance(payload, dict) else {}

    event = str(payload_dict.get("hook_event_name") or "SessionStart")
    session_id = str(payload_dict.get("session_id") or "claude-anon")
    cwd = payload_dict.get("cwd")

    try:
        resolved_project = autoinject._resolve_project_id(
            home, str(cwd) if cwd else None, None
        )
    except Exception:
        resolved_project = "default"

    session = contracts.BrainSessionIdentity(
        internal_session_id="is-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12],
        host="claude-code",
        host_session_id=session_id,
        project_id=resolved_project,
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=1,
    )

    if event == "SessionStart":
        try:
            autoinject.BrainLifecycle(home, session).start_session(session)
        except Exception:
            pass  # fail-open: telemetry is best-effort, never blocks startup
        print("{}")
        return 0

    print("{}")
    return 0
```

- [ ] **Step 5: Wire the dispatch**

In `cmd_autoinject` (~line 2657), add:

```python
    if args.autoinject_command == "claude-code-hook":
        return _cmd_claude_code_hook(home)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_claude_code_adapter.py -v`
Expected: PASS (4/4)

- [ ] **Step 7: Commit**

```bash
git add src/second_brain/cli.py tests/test_claude_code_adapter.py
git commit -m "feat(claude): add SessionStart lifecycle adapter"
```

---

## Task 2: PreCompact — bounded resume snapshot via the ledger

**Files:**
- Modify: `src/second_brain/cli.py` (`_cmd_claude_code_hook`, add PreCompact branch)
- Test: `tests/test_claude_code_adapter.py`

**Interfaces:**
- Consumes: `session` (`contracts.BrainSessionIdentity`, from Task 1), `antigravity_transcript.extract_latest_user_task(transcript_path)`, `ledger.LedgerStore(home, host_session_id)`, `ledger.internal_session_id(host_session_id)`, `ledger.checkpoint_ledger(store)`, `contracts.stable_content_hash(obj)`, `contracts.LifecycleEventType.COMPACTION_STARTED`, `contracts.SurfaceVisibility.RAW_ONLY`, `contracts.BrainLifecycleEvent`
- Produces: PreCompact branch inside `_cmd_claude_code_hook` writes one `COMPACTION_STARTED` ledger event per distinct resume-packet content and always prints `{}` (never `{"decision": "deny"}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_code_adapter.py`:

```python
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


def test_precompact_writes_bounded_resume_snapshot(home: Path, git_project: Path, tmp_path: Path) -> None:
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
        rows = store.search("", event_type="compaction_started", limit=10)
    assert len(rows) == 1
    body = json.loads(rows[0]["payload_json"]) if "payload_json" in rows[0] else rows[0]
    # payload may be nested under "payload" depending on row shape; normalize
    payload_out = body.get("payload", body)
    assert payload_out["goal"] == "Add retry logic to the fetch client"
    assert payload_out["branch"]
    assert payload_out["commit"]
    assert payload_out["trigger"] == "manual"


def test_precompact_does_not_store_full_transcript(home: Path, git_project: Path, tmp_path: Path) -> None:
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
        rows = store.search("", event_type="compaction_started", limit=10)
    raw = json.dumps(rows[0])
    assert "x" * 1000 not in raw  # the 50KB assistant blob must never be persisted
    assert len(raw.encode("utf-8")) < 8000  # bounded (well under ~2000 tokens)


def test_precompact_duplicate_invocation_is_deduplicated(home: Path, git_project: Path, tmp_path: Path) -> None:
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
        rows = store.search("", event_type="compaction_started", limit=10)
    assert len(rows) == 1  # not 2: idempotent on identical content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\test_claude_code_adapter.py -k precompact -v`
Expected: FAIL — PreCompact branch not implemented yet (no `compaction_started` events, ledger session never created).

- [ ] **Step 3: Implement the PreCompact branch**

In `_cmd_claude_code_hook`, replace the trailing `print("{}"); return 0` fallback with:

```python
    if event == "PreCompact":
        from . import antigravity_transcript, ledger

        try:
            autoinject.BrainLifecycle(home, session).start_session(session)
        except Exception:
            pass

        transcript_path = payload_dict.get("transcript_path")
        goal = None
        if transcript_path:
            try:
                goal = antigravity_transcript.extract_latest_user_task(str(transcript_path))
            except Exception:
                goal = None
        custom_instructions = payload_dict.get("custom_instructions")
        if isinstance(custom_instructions, str) and custom_instructions.strip():
            custom_instructions = custom_instructions.strip()[:500]
        else:
            custom_instructions = None

        branch = commit = None
        changed_files: list[str] = []
        if cwd:
            branch = _git_capture(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
            commit = _git_capture(cwd, ["rev-parse", "HEAD"])
            diff_stat = _git_capture(cwd, ["diff", "--name-only", "HEAD"])
            if diff_stat:
                changed_files = diff_stat.splitlines()[:20]

        resume_packet = {
            "goal": goal,
            "custom_instructions": custom_instructions,
            "project_id": resolved_project,
            "cwd": str(cwd) if cwd else None,
            "branch": branch,
            "commit": commit,
            "files_changed": changed_files,
            "trigger": str(payload_dict.get("trigger") or "auto"),
            # Fields the P3a spec asks for that a mechanical hook cannot
            # honestly derive without model participation (no PreToolUse/
            # PostToolUse in this pass, so nothing populates a Requirement
            # Ledger during the turn). Left explicit and empty rather than
            # fabricated -- see brainstem/adapters/claude-code/README.md.
            "decisions": [],
            "blockers": [],
            "open_questions": [],
            "evidence_refs": [],
            "tests_run": [],
        }
        content_hash = contracts.stable_content_hash(resume_packet)

        try:
            store = ledger.LedgerStore(home, session_id)
            with store.open(create=True):
                try:
                    store.create_session(session)
                except Exception:
                    pass  # INSERT OR REPLACE is idempotent; ignore best-effort
                existing = store.search(content_hash[:16], event_type="compaction_started", limit=1)
                if not existing:
                    internal = ledger.internal_session_id(session_id)
                    event_obj = contracts.BrainLifecycleEvent(
                        seq=0,
                        event_id=f"precompact-{content_hash[:16]}",
                        internal_session_id=internal,
                        agent_id="claude-code",
                        event_type=contracts.LifecycleEventType.COMPACTION_STARTED,
                        timestamp=datetime.now(UTC).isoformat(),
                        surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
                        ignorable=False,
                        payload={**resume_packet, "content_sha256": content_hash},
                    )
                    store.append_events([event_obj])
                ledger.checkpoint_ledger(store)
        except Exception:
            pass  # fail-open: never block compaction

        print("{}")
        return 0
```

Add a small private helper above `_cmd_claude_code_hook` (shared by SessionStart/PreCompact/Stop, avoids duplicating the subprocess boilerplate):

```python
def _git_capture(cwd: object, args: list[str]) -> str | None:
    """Best-effort `git <args>` in cwd. Never raises; empty/error -> None."""
    import subprocess as _sp

    try:
        result = _sp.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = result.stdout.strip()
        return out or None
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_claude_code_adapter.py -v`
Expected: PASS (all tests from Task 1 + Task 2)

- [ ] **Step 5: Commit**

```bash
git add src/second_brain/cli.py tests/test_claude_code_adapter.py
git commit -m "feat(claude): preserve state at PreCompact"
```

---

## Task 3: Stop — per-turn telemetry + opt-in candidate writeback

**Files:**
- Modify: `src/second_brain/cli.py` (`_cmd_claude_code_hook`, add Stop branch)
- Test: `tests/test_claude_code_adapter.py`

**Interfaces:**
- Consumes: `autoinject.BrainLifecycle.record_event` is not used directly (it needs a full `BrainLifecycleEvent`); instead reuse `autoinject._append_telemetry`-equivalent via `BrainLifecycle` is private, so Stop uses the same lightweight pattern as SessionStart (`start_session`-style telemetry) plus `autoinject.BrainLifecycle.writeback_candidate(session_id, project_id, title, observation, guidance, evidence)`.
- Produces: Stop branch appends a `turn_end`-kind telemetry record every call (cheap, matches existing `LifecycleEventType.TURN_END` naming convention used by Prime), and — only when `last_assistant_message` contains the opt-in marker block below — calls `writeback_candidate` exactly once.

**The opt-in candidate marker.** A hook has no semantic judgment; it cannot reliably decide "is this reusable" from free text without either fabricating or spamming on routine turns (explicitly prohibited). So the *only* trigger for a candidate write is a literal, deterministic marker that Claude itself chooses to emit at the end of a turn when it has an evidence-backed, reusable finding — documented in `brainstem/adapters/claude-code/rules/second-brain-core.md` (Task 4):

```
<!--second-brain-candidate
title: <one line>
observation: <what was learned>
evidence: <reproducible command, file+line, or test name>
-->
```

No marker present → no candidate write, ever. This makes "routine `rg` searches / directory listings / ordinary successful commands never become memories" true by construction, and keeps promotion entirely candidate-only (the hook only ever calls `writeback_candidate`, never `curate`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_code_adapter.py`:

```python
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
    assert "turn_end" in kinds

    from second_brain import semantic

    memories = semantic.list_memories(home, scope="project", project_id=None)
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

    memories = semantic.list_memories(home, scope="project", project_id=None)
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

    memories = semantic.list_memories(home, scope="project", project_id=None)
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

    memories = semantic.list_memories(home, scope="project", project_id=None)
    assert len(memories) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\test_claude_code_adapter.py -k stop -v`
Expected: FAIL — Stop branch not implemented, `semantic.list_memories` signature must be confirmed (adjust the test to match the real signature found in `src/second_brain/semantic.py` if it differs — check `list_memories`/`search_memories` before writing the assertions above).

- [ ] **Step 3: Implement the Stop branch**

In `_cmd_claude_code_hook`, add before the final fallback `print("{}"); return 0`:

```python
    if event == "Stop":
        try:
            autoinject.BrainLifecycle(home, session).start_session(session)
        except Exception:
            pass
        try:
            autoinject._append_telemetry(
                home, session_id, "turn_end", {"host": "claude-code", "project_id": resolved_project}
            )
        except Exception:
            pass

        last_message = payload_dict.get("last_assistant_message")
        if isinstance(last_message, str) and last_message.strip():
            candidate = _extract_candidate_marker(last_message)
            if candidate is not None:
                title, observation, evidence = candidate
                if evidence.strip():  # empirical claims require evidence (never fabricate)
                    try:
                        lifecycle = autoinject.BrainLifecycle(home, session)
                        content_key = hashlib.sha256(
                            (title + observation + evidence).encode("utf-8")
                        ).hexdigest()[:16]
                        marker_path = home / "telemetry" / "agent-performance" / "claude-code-candidates-seen.jsonl"
                        seen = set()
                        if marker_path.exists():
                            seen = {
                                line.strip() for line in marker_path.read_text(encoding="utf-8").splitlines()
                            }
                        if content_key not in seen:
                            lifecycle.writeback_candidate(
                                session_id=session_id,
                                project_id=resolved_project,
                                title=title,
                                observation=observation,
                                evidence=[{"ref": evidence, "kind": "session_reported"}],
                            )
                            marker_path.parent.mkdir(parents=True, exist_ok=True)
                            with marker_path.open("a", encoding="utf-8") as f:
                                f.write(content_key + "\n")
                    except Exception:
                        pass  # fail-open: candidate writeback never blocks Stop

        print("{}")
        return 0
```

Add the marker parser above `_cmd_claude_code_hook`:

```python
def _extract_candidate_marker(text: str) -> tuple[str, str, str] | None:
    """Parse an opt-in `<!--second-brain-candidate ... -->` block.

    Deterministic, no NLP: only fires when Claude itself explicitly emitted
    the marker (see brainstem/adapters/claude-code/rules/second-brain-core.md).
    Returns (title, observation, evidence) or None if absent/malformed.
    """
    import re

    m = re.search(r"<!--second-brain-candidate\s*(.*?)-->", text, re.S)
    if not m:
        return None
    body = m.group(1)
    fields: dict[str, str] = {}
    for line in body.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in ("title", "observation", "evidence"):
            fields[key.strip()] = value.strip()
    title = fields.get("title", "")
    observation = fields.get("observation", "")
    evidence = fields.get("evidence", "")
    if not title or not observation:
        return None
    return title, observation, evidence
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_claude_code_adapter.py -v`
Expected: PASS (all tests from Tasks 1-3). If `semantic.list_memories` has a different signature than assumed, read `src/second_brain/semantic.py` for the real one and fix the test calls (do not change adapter code to fit a wrong test).

- [ ] **Step 5: Commit**

```bash
git add src/second_brain/cli.py tests/test_claude_code_adapter.py
git commit -m "feat(claude): add candidate-only Stop lifecycle"
```

---

## Task 4: Launcher, rules file, telemetry schema, install/uninstall scripts

**Files:**
- Create: `brainstem/adapters/claude-code/scripts/run-hook.ps1`
- Create: `brainstem/adapters/claude-code/hooks.json`
- Create: `brainstem/adapters/claude-code/rules/second-brain-core.md`
- Create: `brainstem/adapters/claude-code/README.md`
- Create: `scripts/install-claude-code-hooks.ps1`
- Create: `scripts/uninstall-claude-code-hooks.ps1`
- Modify: `brainstem/telemetry/SCHEMA.md`

**Interfaces:**
- Consumes: `autoinject claude-code-hook` (Tasks 1-3)
- Produces: a working, reversible hook registration in `~/.claude/settings.json`

This task is transport/config wiring, not new Python logic — no unit tests beyond a syntax/dry-run check, since its correctness is verified in Task 5's dogfood pass.

- [ ] **Step 1: Write the launcher**

Create `brainstem/adapters/claude-code/scripts/run-hook.ps1`:

```powershell
# The Second Brain — Claude Code Lifecycle Hook Launcher (THIN TRANSPORT)
#
# stdin  : Claude Code's own hook JSON payload (already carries
#          hook_event_name — unlike Antigravity's official payload, no
#          -Event param is needed here).
# flow   : payload -> `brainctl autoinject claude-code-hook` (Python owns
#          ALL policy). This script is transport only: invoke, return
#          stdout verbatim, fail open to `{}` on any error.
# events : SessionStart, PreCompact, Stop (P3a scope only).

$ErrorActionPreference = "Stop"

$repoHome = $env:SECOND_BRAIN_HOME
if (-not $repoHome) { $repoHome = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$python = Join-Path $repoHome ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Output "{}"
    exit 0
}

$payload = ""
try {
    if ([Console]::IsInputRedirected) {
        $payload = [Console]::In.ReadToEnd()
    }
} catch {
    $payload = ""
}
if (-not $payload -or -not $payload.Trim()) {
    $payload = "{}"
}

# Clear corrupted environment variables (repo gotcha: PYTHONHOME pollution)
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null

try {
    $response = $payload | & $python -m second_brain --home $repoHome autoinject claude-code-hook 2>$null
} catch {
    $response = "{}"
}

if (-not $response -or -not $response.Trim()) {
    $response = "{}"
}

Write-Output $response
exit 0
```

- [ ] **Step 2: Write the hooks.json reference/template**

Create `brainstem/adapters/claude-code/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "powershell -ExecutionPolicy Bypass -File \"<RUN_PS1>\"",
            "timeout": 30
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "powershell -ExecutionPolicy Bypass -File \"<RUN_PS1>\"",
            "timeout": 30
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "powershell -ExecutionPolicy Bypass -File \"<RUN_PS1>\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Write the rules file**

Create `brainstem/adapters/claude-code/rules/second-brain-core.md`:

```markdown
# Second Brain Core Rule for Claude Code

This workspace is integrated with The Second Brain via native SessionStart/
PreCompact/Stop hooks (P3a).

## Operating Principles

1. **Source Authority**: Current repository source, verified tests, and live tool evidence strictly outrank Second Brain memory.
2. **No Automatic Retrieval**: SessionStart and PreCompact never inject memory or project history into context. Nothing here changes that.
3. **Single Source of Truth**: Do not create parallel memory databases or session ledgers. Reuse the existing Second Brain store.
4. **Candidate-Only Writeback**: You may record a durable, evidence-backed finding by ending a turn with this exact block:

   ```
   <!--second-brain-candidate
   title: <one line>
   observation: <what was learned>
   evidence: <reproducible command, file+line, or test name>
   -->
   ```

   The Stop hook writes this as a `candidate` memory only — never canonical. Omit `evidence` (or leave it blank) and nothing is written: empirical claims without evidence are dropped, not recorded. Do not emit this marker for routine activity (searches, listings, ordinary passing tests) — only for something plausibly reusable in a future session.
5. **Never Self-Promote**: You cannot and must not promote a candidate to canonical. Promotion is a human/`memory curate` action only.
```

- [ ] **Step 4: Write the README**

Create `brainstem/adapters/claude-code/README.md` (mirrors `brainstem/codex-hooks/README.md`'s structure — event table, install/uninstall, known limits):

```markdown
# Second Brain P3a Claude Code hooks

Native Claude Code lifecycle wiring for SessionStart, PreCompact, and Stop
only (P3a scope). Every call runs `brainctl autoinject claude-code-hook`:
one JSON object on stdin, one on stdout, fail-open (`{}`, exit 0) on any
error — the hook never breaks a Claude Code session.

## What happens on each event

| Event       | Brain behavior |
|-------------|----------------|
| SessionStart | Registers host=`claude-code` in the existing telemetry-based session lifecycle (`autoinject.BrainLifecycle.start_session`). No memory retrieval, no context injection — always returns `{}`. |
| PreCompact   | Extracts a bounded resume packet (goal from the transcript's last user message, `custom_instructions` if the user ran `/compact <text>`, git branch/commit/changed-files) and writes it as one `compaction_started` ledger event, then runs `ledger.checkpoint_ledger` (the existing pre-compaction durability barrier). Deduplicated by content hash. Never blocks compaction. |
| Stop         | Fires once per assistant turn (not once per session — `SessionEnd` is Claude Code's real session-close event and is out of scope here). Records a lightweight `turn_end` telemetry record every time. Writes a `candidate` memory only when the assistant's last message contains the opt-in `<!--second-brain-candidate ...-->` marker (see `rules/second-brain-core.md`) with non-empty evidence. |

## Known limits (honest)

- A hook is a shell script with no model access. It cannot semantically judge "is this a validated decision" or "is this a blocker" from free text. The PreCompact resume packet therefore leaves `decisions`/`blockers`/`open_questions`/`evidence_refs`/`tests_run` as empty — populating them with guessed text would violate the Brain's no-fabrication rule. The only semantically rich field (`goal`) comes from a literal, bounded read of the transcript's last user message plus, when present, the user's own `/compact` instructions — not from summarization.
- `Stop` firing once per turn (not once per session) means "session completion" in the literal P3a spec sense doesn't have a clean hook in this three-event slice; `SessionEnd` would be the correct hook for that and is explicitly deferred.
- No circuit breaker: repeated Brain failures do not back off; each hook call is an independent single-shot try/except that fails open, matching every other adapter in this repo.

## Install / uninstall / rollback

```powershell
.\scripts\install-claude-code-hooks.ps1     # merge into ~/.claude/settings.json
.\scripts\uninstall-claude-code-hooks.ps1   # remove the hooks block
.\scripts\uninstall-claude-code-hooks.ps1 -RestoreBackup   # exact prior state
```

Test safely without touching the real config:

```powershell
$env:CLAUDE_CONFIG_DIR = "$env:TEMP\claude-test"; .\scripts\install-claude-code-hooks.ps1
```
```

- [ ] **Step 5: Write the install/uninstall scripts**

Create `scripts/install-claude-code-hooks.ps1` (idempotent JSON merge, timestamped backup):

```powershell
# Idempotently merge brainstem/adapters/claude-code/hooks.json's "hooks"
# key into ~/.claude/settings.json (or $env:CLAUDE_CONFIG_DIR\settings.json).
# Never touches any other top-level key. Keeps a timestamped backup.
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$templatePath = Join-Path $repoRoot "brainstem\adapters\claude-code\hooks.json"
$runPs1 = Join-Path $repoRoot "brainstem\adapters\claude-code\scripts\run-hook.ps1"

$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = Join-Path $env:USERPROFILE ".claude" }
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$settingsPath = Join-Path $configDir "settings.json"

$template = Get-Content $templatePath -Raw | ConvertFrom-Json
$templateJson = ($template | ConvertTo-Json -Depth 10) -replace [regex]::Escape("<RUN_PS1>"), ($runPs1 -replace '\\', '\\\\')
$template = $templateJson | ConvertFrom-Json

$existing = if (Test-Path $settingsPath) {
    Get-Content $settingsPath -Raw | ConvertFrom-Json -AsHashtable
} else {
    @{}
}

if (Test-Path $settingsPath) {
    $backup = "$settingsPath.sb-hooks-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $settingsPath $backup
    Write-Output "Backup written: $backup"
}

$existing["hooks"] = $template.hooks
($existing | ConvertTo-Json -Depth 10) | Set-Content -Path $settingsPath -Encoding utf8
Write-Output "Installed Claude Code hooks -> $settingsPath"
```

Create `scripts/uninstall-claude-code-hooks.ps1`:

```powershell
param(
    [switch]$RestoreBackup
)
$ErrorActionPreference = "Stop"

$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = Join-Path $env:USERPROFILE ".claude" }
$settingsPath = Join-Path $configDir "settings.json"

if ($RestoreBackup) {
    $backup = Get-ChildItem "$settingsPath.sb-hooks-backup-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $backup) { Write-Output "No backup found."; exit 1 }
    Copy-Item $backup.FullName $settingsPath -Force
    Write-Output "Restored $settingsPath from $($backup.Name)"
    exit 0
}

if (-not (Test-Path $settingsPath)) { Write-Output "No settings.json found."; exit 0 }
$existing = Get-Content $settingsPath -Raw | ConvertFrom-Json -AsHashtable
if ($existing.ContainsKey("hooks")) {
    $existing.Remove("hooks")
    ($existing | ConvertTo-Json -Depth 10) | Set-Content -Path $settingsPath -Encoding utf8
    Write-Output "Removed hooks block from $settingsPath"
} else {
    Write-Output "No hooks block present."
}
```

- [ ] **Step 6: Add telemetry schema rows**

In `brainstem/telemetry/SCHEMA.md`, add a row (matching the existing table's format) for each new kind: `claude_code_session_start`, `claude_code_precompact`, `claude_code_stop_turn`, `claude_code_stop_candidate_written` — read the existing table's columns first and match them exactly (do not invent a new column).

- [ ] **Step 7: Dry-run the install script against a throwaway config dir**

Run:
```bash
CLAUDE_CONFIG_DIR="$TEMP/claude-test-install" powershell -File scripts/install-claude-code-hooks.ps1
```
(PowerShell: `$env:CLAUDE_CONFIG_DIR = "$env:TEMP\claude-test-install"; .\scripts\install-claude-code-hooks.ps1`)

Expected: prints `Installed Claude Code hooks -> ...\claude-test-install\settings.json`; the file contains valid JSON with a `hooks` key holding the three events, `<RUN_PS1>` replaced with the real absolute path.

- [ ] **Step 8: Commit**

```bash
git add brainstem/adapters/claude-code scripts/install-claude-code-hooks.ps1 scripts/uninstall-claude-code-hooks.ps1 brainstem/telemetry/SCHEMA.md
git commit -m "feat(claude): add hook launcher, rules, and install script"
```

---

## Task 5: Dogfood verification (manual — not automated)

**Files:** none (verification only)

- [ ] **Step 1: Stop and ask the user for explicit confirmation before running the real install** — `~/.claude/settings.json` is the user's global Claude Code config; the install script makes Claude Code execute shell commands on every session going forward. Do not run `scripts/install-claude-code-hooks.ps1` against the real (non-`CLAUDE_CONFIG_DIR`-overridden) path without a clear yes.

- [ ] **Step 2:** Run `scripts\install-claude-code-hooks.ps1` for real (after confirmation). Confirm `~/.claude/settings.json` now has the `hooks` block and a timestamped backup exists if a prior settings.json existed.

- [ ] **Step 3:** Open a fresh native Claude Code session in this repo. Confirm:
  - `%SECOND_BRAIN_HOME%\telemetry\agent-performance\<session-id>.jsonl` gets exactly one `session_started` record for this session (SessionStart fired once for the real `startup` trigger).
  - No visible context injection appeared (compare session start to before the hooks existed) — the CLAUDE.md bootstrap output is unchanged.

- [ ] **Step 4:** Work normally for a few turns (read a file, run a command) to exercise meaningful state.

- [ ] **Step 5:** Trigger compaction manually with `/compact` (or let it auto-trigger). Confirm:
  - The command exits normally (compaction not blocked).
  - A new `compaction_started` event exists: `.venv\Scripts\python.exe -m second_brain --home %SECOND_BRAIN_HOME% ledger rehydrate <session-id> 2` (or `ledger search <session-id> "" --event-type compaction_started`) shows the resume packet with the real goal/branch/commit populated.

- [ ] **Step 6:** After compaction, ask Claude (in-session) to state the goal/branch/next-action — confirm it can still answer correctly from the ongoing conversation (this hook does not re-inject the packet automatically — retrieval automation is out of scope — so this step is really confirming the packet is *available* via `ledger rehydrate`/`session recover` for a human or a later phase, not that Claude auto-recovers it).

- [ ] **Step 7:** End the turn with a deliberate `<!--second-brain-candidate ...-->` marker (as documented in `rules/second-brain-core.md`) referencing real evidence from this session (e.g., a test that was actually run). Confirm exactly one `candidate` memory was written: `.venv\Scripts\python.exe -m second_brain --home %SECOND_BRAIN_HOME% memory list --scope project --project <id>`.

- [ ] **Step 8:** Confirm several ordinary turns (file reads, `rg` searches) in between did **not** create any memories.

- [ ] **Step 9:** Run `.venv\Scripts\python.exe -m second_brain --home %SECOND_BRAIN_HOME% doctor`. Confirm PASS/no new FAIL introduced by this change.

- [ ] **Step 10:** Run the full test suite: `.venv\Scripts\python.exe -m pytest`. Confirm no regressions.

- [ ] **Step 11: Report to the user** using the exact structure requested in the original P3a task (SessionStart/PreCompact/Stop status, reused primitives, new files, hook configuration, failure behavior, verification evidence, noise/token assessment, scope confirmation). Then stop — do not proceed into P3b, MCP, retrieval automation, or additional hooks.

---

## Self-Review Notes

- **Spec coverage:** SessionStart (Task 1), PreCompact (Task 2), Stop (Task 3), hook registration + rules (Task 4), dogfood (Task 5) all map to explicit P3a requirements. The one deliberate, disclosed deviation: Stop cannot "finalize the session" (it fires per-turn; `finalize_session()` is never called from Stop) and PreCompact's decisions/blockers/tests fields are left empty rather than fabricated — both called out in `README.md` and the final report rather than silently claimed as done.
- **No placeholders:** every step has runnable code, not descriptions.
- **Type/name consistency:** `_cmd_claude_code_hook`, `_git_capture`, `_extract_candidate_marker` are the only three new functions; each is defined once (Tasks 1/2/3) and referenced identically thereafter. `resolved_project`, `session`, `session_id`, `cwd`, `payload_dict`, `event` are established in Task 1's function body and reused verbatim by the branches added in Tasks 2-3 (all three tasks edit the same function, so there is no cross-file signature drift to check).
