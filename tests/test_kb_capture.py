"""V3 core: capture tool events, git trailers, and evidence staleness."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from second_brain.kb import capture, cli, records
from second_brain.kb.records import Record


# Scrub tests
def test_scrub_github_tokens() -> None:
    """Scrub GitHub tokens: ghp_, gho_, github_pat_."""
    text = "ghp_abc123def456"
    clean, changed = capture.scrub(text)
    assert clean == "***"
    assert changed is True


def test_scrub_openai_tokens() -> None:
    """Scrub OpenAI tokens: sk-+≥20 chars."""
    text = "sk-proj-abc123def456abc123def456"
    clean, changed = capture.scrub(text)
    assert clean == "***"
    assert changed is True


def test_scrub_slack_tokens() -> None:
    """Scrub Slack tokens: xox[baprs]-…."""
    text = "xoxb-abc123def456"
    clean, changed = capture.scrub(text)
    assert clean == "***"
    assert changed is True


def test_scrub_aws_tokens() -> None:
    """Scrub AWS tokens: AKIA[0-9A-Z]{16}."""
    text = "AKIAIOSFODNN7EXAMPLE"
    clean, changed = capture.scrub(text)
    assert clean == "***"
    assert changed is True


def test_scrub_google_tokens() -> None:
    """Scrub Google tokens: AIza[0-9A-Za-z_-]{35}."""
    text = "AIzaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # AIza + 35 A's
    clean, changed = capture.scrub(text)
    assert "***" in clean
    assert changed is True


def test_scrub_bearer_tokens() -> None:
    """Scrub Bearer tokens."""
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    clean, changed = capture.scrub(text)
    assert "Bearer ***" in clean
    assert changed is True


def test_scrub_password_pattern() -> None:
    """Scrub password/secret patterns: key kept, value masked."""
    text = "password=mysecretpass123"
    clean, changed = capture.scrub(text)
    assert "password=" in clean.lower()
    assert "***" in clean
    assert "mysecretpass" not in clean
    assert changed is True


def test_scrub_api_key_pattern() -> None:
    """Scrub API key patterns."""
    text = "api_key: sk_prod_abc123def456"
    clean, changed = capture.scrub(text)
    assert "api_key" in clean.lower()
    assert "***" in clean
    assert changed is True


def test_scrub_base64_long_run() -> None:
    """Scrub long base64/hex runs (≥40 chars)."""
    text = "debug: " + "A" * 40
    clean, changed = capture.scrub(text)
    assert "***" in clean
    assert changed is True


def test_scrub_unchanged() -> None:
    """Unchanged text returns False."""
    text = "hello world"
    clean, changed = capture.scrub(text)
    assert clean == text
    assert changed is False


# Program tests
def test_program_simple() -> None:
    """Extract program name from simple command."""
    cmd = "python -m pytest"
    prog = capture.program(cmd)
    assert prog == "python"


def test_program_with_env_assignment() -> None:
    """Skip leading VAR=value assignments."""
    cmd = "VAR=value python -m pytest"
    prog = capture.program(cmd)
    assert prog == "python"


def test_program_with_sudo() -> None:
    """Skip sudo."""
    cmd = "sudo apt-get install"
    prog = capture.program(cmd)
    assert prog == "apt-get"


def test_program_with_env_command() -> None:
    """Skip env command."""
    cmd = "env PATH=/usr/bin python -m pytest"
    prog = capture.program(cmd)
    assert prog == "python"


def test_program_with_time() -> None:
    """Skip time command."""
    cmd = "time python -m pytest"
    prog = capture.program(cmd)
    assert prog == "python"


def test_program_with_path() -> None:
    """Take basename, ignore path."""
    cmd = "/usr/bin/python -m pytest"
    prog = capture.program(cmd)
    assert prog == "python"


def test_program_windows_exe() -> None:
    """Strip .exe extension."""
    cmd = "C:\\Python\\python.exe -m pytest"
    prog = capture.program(cmd)
    assert prog == "python"


def test_program_empty() -> None:
    """Empty command returns empty string."""
    prog = capture.program("")
    assert prog == ""


# Error signature tests
def test_error_signature_with_error_keyword() -> None:
    """First line with error keyword."""
    error = "some preamble\nerror: file not found\nmore details"
    sig = capture.error_signature(error)
    assert "error" in sig.lower()
    assert "file not found" in sig


def test_error_signature_strips_ansi() -> None:
    """Strip ANSI escape codes."""
    error = "\x1b[31merror: something failed\x1b[0m"
    sig = capture.error_signature(error)
    assert "\x1b" not in sig
    assert "error" in sig.lower()


def test_error_signature_collapses_whitespace() -> None:
    """Collapse whitespace."""
    error = "error:   file    not   found"
    sig = capture.error_signature(error)
    assert "  " not in sig


def test_error_signature_caps_at_120() -> None:
    """Cut to 120 characters."""
    error = "error: " + "x" * 150
    sig = capture.error_signature(error)
    assert len(sig) <= 120


def test_error_signature_empty() -> None:
    """Empty error returns empty signature."""
    sig = capture.error_signature("")
    assert sig == ""


def test_error_signature_first_nonzero_line() -> None:
    """Fall back to first non-empty line when no keyword."""
    error = "some preamble\nfailed to do something\nmore"
    sig = capture.error_signature(error)
    # Should match because "failed" is a keyword
    assert "failed" in sig.lower()


# Failure→fix pairing tests
def test_failure_fix_pairing_basic(tmp_path: Path) -> None:
    """Pair failure and fix events within 6 events."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "connection timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "echo hello",
            "ok": True,
            "error": None,
        },
        {
            "v": 1,
            "at": "2026-01-01T10:02:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = events_dir / "session1.jsonl"
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 1
    rec_id = report.proposals[0]
    inbox_file = capture.inbox_dir(home) / f"{rec_id}.md"
    assert inbox_file.is_file()
    rec = records.read(inbox_file)
    assert "pip" in rec.title.lower()
    assert "fails" in rec.title.lower()
    assert "works" in rec.title.lower()


def test_failure_fix_no_pair_beyond_6_events(tmp_path: Path) -> None:
    """No pair when fix is beyond 6 events."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
    ]
    # Add 7 events between failure and fix
    for i in range(7):
        events.append(
            {
                "v": 1,
                "at": f"2026-01-01T10:0{i}:00Z",
                "tool": "bash",
                "command": f"echo {i}",
                "ok": True,
                "error": None,
            }
        )
    # This fix is beyond 6 events
    events.append(
        {
            "v": 1,
            "at": "2026-01-01T10:08:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        }
    )

    event_file = capture.events_dir(home) / "session1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 0


def test_failure_fix_no_pair_different_tool(tmp_path: Path) -> None:
    """No pair when tool differs."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "python",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = capture.events_dir(home) / "session1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 0


def test_failure_fix_no_pair_identical_command(tmp_path: Path) -> None:
    """No pair when commands are identical."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": True,
            "error": None,
        },
    ]

    event_file = capture.events_dir(home) / "session1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 0


def test_cursor_advances_on_capture(tmp_path: Path) -> None:
    """Cursor advances after processing, so second run proposes nothing new."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = capture.events_dir(home) / "session1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    # First run
    report1 = capture.capture_events(home)
    assert len(report1.proposals) == 1

    # Second run
    report2 = capture.capture_events(home)
    assert len(report2.proposals) == 0


def test_appending_events_proposes_only_new(tmp_path: Path) -> None:
    """Appending new events proposes only those new events."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    event_file = capture.events_dir(home) / "session1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text("")

    # First batch
    events1 = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]
    for event in events1:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report1 = capture.capture_events(home)
    assert len(report1.proposals) == 1

    # Append second batch
    events2 = [
        {
            "v": 1,
            "at": "2026-01-01T10:02:00Z",
            "tool": "bash",
            "command": "npm install bar",
            "ok": False,
            "error": "network error",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:03:00Z",
            "tool": "bash",
            "command": "npm install bar --legacy",
            "ok": True,
            "error": None,
        },
    ]
    for event in events2:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report2 = capture.capture_events(home)
    assert len(report2.proposals) == 1  # Only the new pair


def test_dry_run_doesnt_advance_cursor(tmp_path: Path) -> None:
    """Dry run writes nothing and doesn't advance cursor."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = capture.events_dir(home) / "session1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    # Dry run
    report1 = capture.capture_events(home, dry_run=True)
    assert len(report1.proposals) == 1

    # But inbox file should not be written
    inbox_dir = capture.inbox_dir(home)
    assert not inbox_dir.is_dir() or len(list(inbox_dir.glob("*.md"))) == 0

    # Second run without dry_run should see same events
    report2 = capture.capture_events(home, dry_run=False)
    assert len(report2.proposals) == 1


def test_secrets_scrubbed_with_extra_flag(tmp_path: Path) -> None:
    """Secrets scrubbed in title/body with extra['scrubbed']."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "curl -H 'Authorization: Bearer sk-abc123def456abc123def456'",
            "ok": False,
            "error": "unauthorized",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "curl -u user:pass",
            "ok": True,
            "error": None,
        },
    ]

    event_file = capture.events_dir(home) / "session1.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 1
    rec_id = report.proposals[0]
    inbox_file = capture.inbox_dir(home) / f"{rec_id}.md"
    rec = records.read(inbox_file)
    assert rec.extra.get("scrubbed") == "true"
    assert "***" in rec.body or "***" in rec.title


def test_dedupe_against_existing_record_trigger(tmp_path: Path) -> None:
    """Dedupe against existing record trigger (signature)."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create existing record with trigger_errors
    existing_rec = Record(
        id="mem-abc123def456",
        title="Some gotcha",
        type="gotcha",
        project="p1",
        status="current",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
        trigger_errors=("connection timeout",),
    )
    records.save(home, existing_rec)

    # Try to capture event with same signature
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "connection timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = events_dir / "session1.jsonl"
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 0
    assert report.skipped == 1


def test_dedupe_against_inbox(tmp_path: Path) -> None:
    """Dedupe against inbox."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create inbox record with a title that will match the generated one (case-folded)
    inbox_rec = Record(
        id="got-abc123def457",
        title="pip: pip install foo fails (timeout); pip install foo --no-cache works",
        type="gotcha",
        project="p1",
        status="candidate",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
    )
    inbox_dir = capture.inbox_dir(home)
    inbox_dir.mkdir(parents=True)
    records.write_atomic(inbox_dir / "got-abc123def457.md", records.dumps(inbox_rec))

    # Try to capture similar event
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = events_dir / "session1.jsonl"
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 0
    assert report.skipped == 1


def test_dedupe_against_rejected(tmp_path: Path) -> None:
    """Dedupe against rejected.jsonl."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create rejected record
    inbox_dir = capture.inbox_dir(home)
    inbox_dir.mkdir(parents=True)
    rejected_file = inbox_dir / "rejected.jsonl"
    rejected = {
        "id": "got-abc123def458",
        "title": "pip install fails",
        "signature": "connection timeout",
        "reason": "not relevant",
        "at": "2026-01-01T00:00:00Z",
    }
    rejected_file.write_text(json.dumps(rejected) + "\n", encoding="utf-8")

    # Try to capture similar event
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "connection timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = events_dir / "session1.jsonl"
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 0
    assert report.skipped == 1


def test_malformed_lines_skipped(tmp_path: Path) -> None:
    """Malformed lines skipped, never fatal."""
    home = tmp_path / "brain"
    home.mkdir()
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    event_file = events_dir / "session1.jsonl"
    event_file.write_text("not json at all\n")
    event_file.write_text(
        event_file.read_text(encoding="utf-8")
        + json.dumps(
            {
                "v": 1,
                "at": "2026-01-01T10:00:00Z",
                "tool": "bash",
                "command": "pip install",
                "ok": False,
                "error": "timeout",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    event_file.write_text(
        event_file.read_text(encoding="utf-8") + "another bad line\n", encoding="utf-8"
    )
    event_file.write_text(
        event_file.read_text(encoding="utf-8")
        + json.dumps(
            {
                "v": 1,
                "at": "2026-01-01T10:01:00Z",
                "tool": "bash",
                "command": "pip install --no-cache",
                "ok": True,
                "error": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = capture.capture_events(home)
    assert len(report.proposals) == 1  # Still parses the valid events


def test_git_trailers_captured(tmp_path: Path) -> None:
    """Git trailers (Brain-Decision, Brain-Gotcha) captured as proposals."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create temp git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True
    )

    # Create a commit with Brain-Decision trailer
    (repo / "file.txt").write_text("content")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Commit\n\nBrain-Decision: Always check return codes"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Capture
    proposals = capture.capture_git(home, repo)
    assert len(proposals) == 1
    rec_id = proposals[0]
    inbox_file = capture.inbox_dir(home) / f"{rec_id}.md"
    rec = records.read(inbox_file)
    assert rec.type == "decision"
    assert "check return codes" in rec.title


def test_git_cursor_honored(tmp_path: Path) -> None:
    """Git cursor honored: second run doesn't re-propose."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create temp git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True
    )

    # First commit with trailer
    (repo / "file.txt").write_text("content1")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Commit1\n\nBrain-Gotcha: Check error handling"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # First capture
    proposals1 = capture.capture_git(home, repo)
    assert len(proposals1) == 1

    # Second capture
    proposals2 = capture.capture_git(home, repo)
    assert len(proposals2) == 0


def test_git_non_repo_returns_empty(tmp_path: Path) -> None:
    """Non-repo path returns []."""
    home = tmp_path / "brain"
    home.mkdir()

    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()

    proposals = capture.capture_git(home, non_repo)
    assert proposals == []


def test_project_scope_from_cwd(tmp_path: Path) -> None:
    """Project scope resolved from cwd via projects/p1/project.toml."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create project
    proj_dir = home / "projects" / "p1"
    proj_dir.mkdir(parents=True)
    (proj_dir / "project.toml").write_text(
        f'id = "p1"\npaths = ["{tmp_path}/repo"]',
        encoding="utf-8",
    )

    # Create event with cwd in project
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "cwd": str(repo_dir),
            "tool": "bash",
            "command": "pip install",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "cwd": str(repo_dir),
            "tool": "bash",
            "command": "pip install --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = events_dir / "session1.jsonl"
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 1
    rec_id = report.proposals[0]
    rec = records.read(capture.inbox_dir(home) / f"{rec_id}.md")
    assert rec.scope == "project"
    assert rec.project == "p1"


def test_accept_moves_to_records_and_is_searchable(tmp_path: Path) -> None:
    """Accept moves proposal into records/ and makes it searchable."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create a proposal
    inbox_rec = Record(
        id="got-abc123def456",
        title="pip fails with timeout",
        type="gotcha",
        project="p1",
        status="candidate",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
    )
    inbox_dir = capture.inbox_dir(home)
    inbox_dir.mkdir(parents=True)
    records.write_atomic(inbox_dir / "got-abc123def456.md", records.dumps(inbox_rec))

    # Accept it
    result = capture.accept(home, "got-abc123def456")
    assert result.id == "got-abc123def456"

    # Check it's in records
    assert records.record_path(home, "got-abc123def456").is_file()

    # Check inbox file is gone
    assert not (inbox_dir / "got-abc123def456.md").is_file()

    # Check it's searchable
    all_records, _ = records.load_all(home)
    assert any(r.id == "got-abc123def456" for r in all_records)


def test_reject_records_reason_and_prevents_rerun(tmp_path: Path) -> None:
    """Reject records reason and prevents re-proposal."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create a proposal
    inbox_rec = Record(
        id="got-abc123def456",
        title="pip: pip install foo fails (timeout); pip install foo --no-cache works",
        type="gotcha",
        project="p1",
        status="candidate",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
    )
    inbox_dir = capture.inbox_dir(home)
    inbox_dir.mkdir(parents=True)
    records.write_atomic(inbox_dir / "got-abc123def456.md", records.dumps(inbox_rec))

    # Reject it
    capture.reject(home, "got-abc123def456", reason="Not a real issue")

    # Check inbox file is gone
    assert not (inbox_dir / "got-abc123def456.md").is_file()

    # Check rejected.jsonl has the entry
    rejected_file = inbox_dir / "rejected.jsonl"
    assert rejected_file.is_file()
    rejected = json.loads(rejected_file.read_text(encoding="utf-8").split("\n")[0])
    assert rejected["id"] == "got-abc123def456"
    assert rejected["reason"] == "Not a real issue"

    # Try to re-propose the same thing (should be deduped)
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)
    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install foo",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install foo --no-cache",
            "ok": True,
            "error": None,
        },
    ]
    event_file = events_dir / "session1.jsonl"
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    report = capture.capture_events(home)
    assert len(report.proposals) == 0
    assert report.skipped == 1


def test_stale_evidence_missing(tmp_path: Path) -> None:
    """stale_evidence reports 'missing' when file not found."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create a record with evidence pointing to missing file
    rec = Record(
        id="mem-abc123def456",
        title="Test",
        type="gotcha",
        project="p1",
        status="current",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
        evidence=("nonexistent/file.txt@1a2b3c4d5e6f",),
    )
    records.save(home, rec)

    stale = capture.stale_evidence(home)
    assert len(stale) == 1
    assert stale[0][0] == "mem-abc123def456"
    assert "nonexistent/file.txt" in stale[0][1]
    assert stale[0][2] == "missing"


def test_stale_evidence_changed(tmp_path: Path) -> None:
    """stale_evidence reports 'changed' when blob doesn't match."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create a file and compute its blob
    proj_dir = tmp_path / "repo"
    proj_dir.mkdir()
    test_file = proj_dir / "file.txt"
    test_file.write_text("original content")

    import hashlib

    data = b"original content"
    blob_hash = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

    # Create project
    projects_dir = home / "projects" / "p1"
    projects_dir.mkdir(parents=True)
    (projects_dir / "project.toml").write_text(
        f'id = "p1"\npaths = ["{proj_dir}"]',
        encoding="utf-8",
    )

    # Create record with correct blob
    rec = Record(
        id="mem-abc123def456",
        title="Test",
        type="gotcha",
        scope="project",
        project="p1",
        status="current",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
        evidence=(f"file.txt@{blob_hash[:7]}",),
    )
    records.save(home, rec)

    # File is unchanged, so no stale
    stale = capture.stale_evidence(home)
    assert len(stale) == 0

    # Change file
    test_file.write_text("different content")

    # Now it's stale
    stale = capture.stale_evidence(home)
    assert len(stale) == 1
    assert stale[0][0] == "mem-abc123def456"
    assert stale[0][2] == "changed"


def test_cli_capture_command(tmp_path: Path, capsys) -> None:
    """CLI capture command."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create events
    events_dir = capture.events_dir(home)
    events_dir.mkdir(parents=True)

    events = [
        {
            "v": 1,
            "at": "2026-01-01T10:00:00Z",
            "tool": "bash",
            "command": "pip install",
            "ok": False,
            "error": "timeout",
        },
        {
            "v": 1,
            "at": "2026-01-01T10:01:00Z",
            "tool": "bash",
            "command": "pip install --no-cache",
            "ok": True,
            "error": None,
        },
    ]

    event_file = events_dir / "session1.jsonl"
    event_file.write_text("")
    for event in events:
        event_file.write_text(
            event_file.read_text(encoding="utf-8") + json.dumps(event) + "\n", encoding="utf-8"
        )

    # Run capture command
    exit_code = cli.main(["capture", "--home", str(home)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "proposed 1" in captured.out
    assert "pip" in captured.out


def test_cli_review_command(tmp_path: Path, capsys) -> None:
    """CLI review command."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create an inbox record
    inbox_rec = Record(
        id="got-abc123def456",
        title="pip fails",
        type="gotcha",
        project="p1",
        status="candidate",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
    )
    inbox_dir = capture.inbox_dir(home)
    inbox_dir.mkdir(parents=True)
    records.write_atomic(inbox_dir / "got-abc123def456.md", records.dumps(inbox_rec))

    # Run review command
    exit_code = cli.main(["review", "--home", str(home), "--no-capture"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "inbox (1)" in captured.out
    assert "got-abc123def456" in captured.out


def test_cli_accept_command(tmp_path: Path, capsys) -> None:
    """CLI accept command."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create an inbox record
    inbox_rec = Record(
        id="got-abc123def456",
        title="pip fails",
        type="gotcha",
        project="p1",
        status="candidate",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
    )
    inbox_dir = capture.inbox_dir(home)
    inbox_dir.mkdir(parents=True)
    records.write_atomic(inbox_dir / "got-abc123def456.md", records.dumps(inbox_rec))

    # Run accept command
    exit_code = cli.main(["accept", "--home", str(home), "got-abc123def456"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "accepted" in captured.out

    # Check it's in records
    assert records.record_path(home, "got-abc123def456").is_file()


def test_cli_reject_command(tmp_path: Path, capsys) -> None:
    """CLI reject command."""
    home = tmp_path / "brain"
    home.mkdir()

    # Create an inbox record
    inbox_rec = Record(
        id="got-abc123def456",
        title="pip fails",
        type="gotcha",
        project="p1",
        status="candidate",
        grade="OBSERVED",
        recorded_at="2026-01-01T00:00:00Z",
    )
    inbox_dir = capture.inbox_dir(home)
    inbox_dir.mkdir(parents=True)
    records.write_atomic(inbox_dir / "got-abc123def456.md", records.dumps(inbox_rec))

    # Run reject command
    exit_code = cli.main(
        ["reject", "--home", str(home), "got-abc123def456", "--reason", "Not relevant"]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "rejected" in captured.out

    # Check it's in rejected.jsonl
    rejected_file = inbox_dir / "rejected.jsonl"
    assert rejected_file.is_file()


def _repo_with_commits(path: Path, *messages: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    for message in messages:
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", message], cwd=path, check=True
        )
    return path


def test_git_cursor_processes_only_newer_commits(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = _repo_with_commits(tmp_path / "repo", "one\n\nBrain-Decision: first decision")
    first = capture.capture_git(home, repo)
    assert len(first) == 1
    _repo_with_commits(repo, "two\n\nBrain-Decision: second decision")
    second = capture.capture_git(home, repo)
    titles = [r.title for r in capture.inbox(home) if r.id in second]
    assert titles == ["second decision"]
    assert capture.capture_git(home, repo) == []


def test_git_dry_run_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = _repo_with_commits(tmp_path / "repo", "one\n\nBrain-Gotcha: a gotcha")
    assert len(capture.capture_git(home, repo, dry_run=True)) == 1
    assert capture.inbox(home) == []
    assert len(capture.capture_git(home, repo)) == 1


def test_empty_rejected_signature_does_not_block_proposals(tmp_path: Path) -> None:
    home = tmp_path / "home"
    inbox = capture.inbox_dir(home)
    inbox.mkdir(parents=True)
    (inbox / "rejected.jsonl").write_text(
        json.dumps({"id": "x", "title": "t", "signature": "", "reason": "r"}) + "\n"
    )
    events = capture.events_dir(home)
    events.mkdir(parents=True)
    lines = [
        {"v": 1, "tool": "bash", "command": "pytest", "ok": False, "error": "E  ImportError: x"},
        {
            "v": 1,
            "tool": "bash",
            "command": "pytest -p no:cacheprovider",
            "ok": True,
            "error": None,
        },
    ]
    (events / "s.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    report = capture.capture_events(home)
    assert len(report.proposals) == 1


def test_stale_evidence_uses_the_recorded_repo(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "elsewhere"
    repo.mkdir()
    (repo / "doc.md").write_bytes(b"v1\n")
    blob = hashlib.sha1(b"blob 3\0v1\n").hexdigest()
    rec = records.Record(
        id="mem-aaaaaaaaaaaa",
        title="Doc fact",
        scope="global",
        status="current",
        grade="TESTED",
        recorded_at="2026-09-01T00:00:00+00:00",
        evidence=(f"doc.md@{blob[:12]} (repo {repo})",),
    )
    records.save(home, rec)
    assert capture.stale_evidence(home) == []
    (repo / "doc.md").write_bytes(b"v2\n")
    assert capture.stale_evidence(home) == [(rec.id, rec.evidence[0], "changed")]
