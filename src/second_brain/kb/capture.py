"""V3 core: capture tool events, git trailers, and evidence staleness.

Capture proposes records to a local inbox; nothing goes straight to records/ or to a model.
All writes are async and local; events never leave the machine.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import projects, records
from .records import Record, RecordError, now_iso

EVENT_RETENTION_DAYS = 14


def inbox_dir(home: Path) -> Path:
    """Local inbox for proposed records."""
    return Path(home) / "state" / "kb-inbox"


def events_dir(home: Path) -> Path:
    """Directory containing tool event logs."""
    return Path(home) / "state" / "kb-events"


def scrub(text: str) -> tuple[str, bool]:
    r"""Replace secret-looking values with ***, return (clean, changed).

    Cover: ghp_…/gho_…/github_pat_…, sk-+≥20 chars, xox[baprs]-…,
    AKIA[0-9A-Z]{16}, AIza[0-9A-Za-z_-]{35}, Bearer <token>,
    (password|passwd|secret|token|api[_-]?key)\s*[=:]\s*<value>,
    and any run of ≥40 base64/hex characters.
    """
    original = text

    # GitHub tokens
    text = re.sub(r"ghp_[A-Za-z0-9_]+", "***", text)
    text = re.sub(r"gho_[A-Za-z0-9_]+", "***", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]+", "***", text)

    # OpenAI/Slack tokens
    text = re.sub(r"sk-[A-Za-z0-9_\-\.]{20,}", "***", text)
    text = re.sub(r"xox[baprs]-[A-Za-z0-9_]+", "***", text)

    # AWS and Google tokens
    text = re.sub(r"AKIA[0-9A-Z]{16}", "***", text)
    text = re.sub(r"AIza[0-9A-Za-z_-]{35}", "***", text)

    # Bearer tokens
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text)

    # Password/secret/token patterns (key kept, value masked)
    text = re.sub(
        r"(?i)(password|passwd|secret|token|api[_-]?key)(\s*[=:])\s*([^\s]+)",
        r"\1\2 ***",
        text,
    )

    # Long base64/hex runs (≥40 chars)
    text = re.sub(r"[A-Fa-f0-9]{40,}", "***", text)

    def replace_b64(match: re.Match) -> str:
        return "***" if "=" in match.group() or len(match.group()) >= 40 else match.group()

    text = re.sub(r"[A-Za-z0-9+/]{40,}={0,2}", replace_b64, text)

    return text, text != original


def program(command: str) -> str:
    """Extract the first real word of a shell command.

    Skip leading VAR=value assignments and sudo/env/time; take the basename;
    strip a Windows .exe.
    """
    if not command:
        return ""

    parts = command.split()
    for part in parts:
        # Skip VAR=value assignments
        if "=" in part and not part.startswith("-"):
            continue
        # Skip sudo, env, time
        if part in ("sudo", "env", "time"):
            continue
        # Found the program
        # Handle both Unix (/) and Windows (\) path separators
        prog = part.replace("\\", "/").split("/")[-1]  # basename
        if prog.lower().endswith(".exe"):
            prog = prog[:-4]
        return prog

    return ""


def error_signature(error: str) -> str:
    """Extract error signature: first line with error keywords, else first non-empty line.

    Strip ANSI escapes, collapse whitespace, cut to 120 characters.
    """
    if not error:
        return ""

    # Strip ANSI escapes
    clean = re.sub(r"\x1b\[[0-9;]*m", "", error)

    # Split into lines
    lines = clean.split("\n")

    # Find first line with error keywords (case-insensitive)
    keywords = (
        r"(?i)(error|exception|failed|failure|not found|denied|mismatch|no such|"
        r"cannot|unable)"
    )
    for line in lines:
        if line.strip() and re.search(keywords, line):
            sig = " ".join(line.split())  # collapse whitespace
            return sig[:120]

    # Fall back to first non-empty line
    for line in lines:
        if line.strip():
            sig = " ".join(line.split())  # collapse whitespace
            return sig[:120]

    return ""


def prune_events(home: Path, *, now: float | None = None) -> list[str]:
    """Delete event files and cursor entries when mtime is older than EVENT_RETENTION_DAYS.

    Returns list of deleted file names (stems).
    """
    if now is None:
        now = time.time()

    deleted: list[str] = []
    events_dir_path = events_dir(home)
    cursor_file = events_dir_path / ".cursor.json"

    if not events_dir_path.is_dir():
        return deleted

    # Load cursor
    cursor: dict[str, int] = {}
    if cursor_file.is_file():
        try:
            cursor = json.loads(cursor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cursor = {}

    # Calculate cutoff time
    cutoff = now - (EVENT_RETENTION_DAYS * 24 * 60 * 60)

    # Check each event file
    for event_file in events_dir_path.glob("*.jsonl"):
        file_stem = event_file.stem

        # Only delete files whose every byte has been processed
        try:
            stat = event_file.stat()
        except OSError:
            continue
        if cursor.get(file_stem, -1) < stat.st_size:
            continue
        mtime = stat.st_mtime

        # Delete if old enough
        if mtime < cutoff:
            try:
                event_file.unlink()
                deleted.append(file_stem)
                # Remove from cursor
                del cursor[file_stem]
            except OSError:
                pass

    # Write updated cursor if anything was deleted
    if deleted:
        try:
            cursor_file.parent.mkdir(parents=True, exist_ok=True)
            cursor_file.write_text(json.dumps(cursor, indent=2), encoding="utf-8")
        except OSError:
            pass

    return deleted


@dataclass
class CaptureReport:
    """Result of a capture operation."""

    proposals: list[str]  # list of new record ids
    sessions: int  # number of event files processed
    skipped: int  # number of events skipped (duplicates, etc)


def capture_events(home: Path, *, dry_run: bool = False) -> CaptureReport:
    """Process tool event logs into gotcha proposals.

    Failure→fix rule: pair each failure event with the first later event within 6
    events where tool matches, ok is true, and program(cmd) is equal.
    """
    events_dir_path = events_dir(home)
    cursor_file = events_dir_path / ".cursor.json"
    inbox_dir_path = inbox_dir(home)

    # Load cursor
    cursor: dict[str, int] = {}
    if cursor_file.is_file():
        try:
            cursor = json.loads(cursor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cursor = {}

    # Load existing records to check for duplicates
    all_records, _ = records.load_all(home)
    existing_titles = {r.title.casefold() for r in all_records}
    existing_sigs = {s.casefold() for r in all_records for s in r.trigger_errors}

    # Load rejected records
    rejected_titles = set()
    rejected_sigs = set()
    rejected_file = inbox_dir_path / "rejected.jsonl"
    if rejected_file.is_file():
        try:
            for line in rejected_file.read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    item = json.loads(line)
                    rejected_titles.add(item.get("title", "").casefold())
                    if item.get("signature"):
                        rejected_sigs.add(item["signature"].casefold())
        except (OSError, json.JSONDecodeError):
            pass

    # Load inbox
    inbox_titles = set()
    inbox_sigs = set()
    if inbox_dir_path.is_dir():
        for inbox_file in inbox_dir_path.glob("*.md"):
            if inbox_file.name == "rejected.jsonl":
                continue
            try:
                rec = records.read(inbox_file)
                inbox_titles.add(rec.title.casefold())
                for sig in rec.trigger_errors:
                    inbox_sigs.add(sig.casefold())
            except (OSError, RecordError):
                pass

    proposals: list[str] = []
    skipped = 0
    sessions = 0

    # Process each event file
    if not events_dir_path.is_dir():
        return CaptureReport(proposals, sessions, skipped)

    for event_file in sorted(events_dir_path.glob("*.jsonl")):
        sessions += 1
        file_stem = event_file.stem
        offset = cursor.get(file_stem, 0)

        # Read events from cursor offset
        try:
            content = event_file.read_bytes()
            if offset >= len(content):
                continue
            lines_text = content[offset:].decode("utf-8", errors="replace")
        except OSError:
            continue

        events = []
        for line in lines_text.split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError:
                continue

        if not events:
            if not dry_run:
                cursor[file_stem] = len(content)
                cursor_file.parent.mkdir(parents=True, exist_ok=True)
                cursor_file.write_text(json.dumps(cursor, indent=2), encoding="utf-8")
            continue

        # Find failure→fix pairs
        i = 0
        while i < len(events):
            event_i = events[i]

            # Check if this is a failure event
            if event_i.get("ok") is False and event_i.get("command") and event_i.get("error"):
                prog_i = program(event_i.get("command", ""))
                tool_i = event_i.get("tool", "")
                cmd_i = event_i.get("command", "")
                error_i = event_i.get("error", "")

                # Look for fix within next 6 events
                for j in range(i + 1, min(i + 7, len(events))):
                    event_j = events[j]
                    if (
                        event_j.get("tool") == tool_i
                        and event_j.get("ok") is True
                        and event_j.get("command")
                        and program(event_j.get("command", "")) == prog_i
                        and event_j.get("command") != cmd_i
                    ):
                        # Found a pair
                        cmd_j = event_j.get("command", "")

                        # Scrub
                        cmd_i_clean, cmd_i_scrubbed = scrub(cmd_i)
                        cmd_j_clean, cmd_j_scrubbed = scrub(cmd_j)
                        error_clean, error_scrubbed = scrub(error_i)

                        # Build title
                        cmd_i_short = " ".join(cmd_i_clean.split())[:60]
                        cmd_j_short = " ".join(cmd_j_clean.split())[:60]
                        sig = error_signature(error_clean)[:60]
                        title = f"{prog_i}: {cmd_i_short} fails ({sig}); {cmd_j_short} works"
                        title = title[:200]

                        # Check for duplicates
                        if (
                            title.casefold() in existing_titles
                            or title.casefold() in inbox_titles
                            or title.casefold() in rejected_titles
                            or (
                                bool(sig)
                                and (
                                    sig.casefold() in existing_sigs
                                    or sig.casefold() in inbox_sigs
                                    or sig.casefold() in rejected_sigs
                                )
                            )
                        ):
                            skipped += 1
                            i = j
                            break

                        # Resolve project
                        cwd = event_i.get("cwd")
                        proj = None
                        scope = "global"
                        if cwd:
                            try:
                                proj = projects.resolve(home, Path(cwd))
                                if proj:
                                    scope = "project"
                            except Exception:
                                pass

                        # Build body
                        body = f"{cmd_i_clean}\n\n{cmd_j_clean}\n\nError: {error_clean}"[:800]

                        # Build record
                        rec = Record(
                            id=records.new_id("got"),
                            title=title,
                            type="gotcha",
                            scope=scope,
                            project=proj.id if proj else None,
                            status="candidate",
                            grade="OBSERVED",
                            recorded_at=now_iso(),
                            evidence=(f"kb-events:{file_stem}#{i}-{j}",),
                            trigger_errors=(sig,) if sig else (),
                            body=body,
                        )

                        if cmd_i_scrubbed or cmd_j_scrubbed or error_scrubbed:
                            rec.extra["scrubbed"] = "true"
                        rec.extra["captured_from"] = "failure-fix"

                        # Validate
                        errors = records.validate(rec)
                        if errors:
                            skipped += 1
                            i = j
                            break

                        # Write
                        if not dry_run:
                            try:
                                inbox_dir_path.mkdir(parents=True, exist_ok=True)
                                records.write_atomic(
                                    inbox_dir_path / f"{rec.id}.md",
                                    records.dumps(rec),
                                )
                                proposals.append(rec.id)
                                existing_titles.add(title.casefold())
                                if sig:
                                    existing_sigs.add(sig.casefold())
                            except OSError:
                                skipped += 1
                        else:
                            # Still collect proposals in dry_run for reporting
                            proposals.append(rec.id)

                        i = j
                        break

            i += 1

        # Update cursor
        if not dry_run:
            cursor[file_stem] = len(content)
            cursor_file.parent.mkdir(parents=True, exist_ok=True)
            cursor_file.write_text(json.dumps(cursor, indent=2), encoding="utf-8")

    # Prune old event files (only when not in dry run)
    if not dry_run:
        prune_events(home)

    return CaptureReport(proposals, sessions, skipped)


def capture_git(home: Path, repo: Path, *, dry_run: bool = False) -> list[str]:
    """Process git commit trailers into decision/gotcha proposals.

    Look for Brain-Decision and Brain-Gotcha trailers (case-insensitive).
    """
    git_cursor_file = events_dir(home) / ".git-cursor.json"

    # Load cursor
    cursor: dict[str, str] = {}
    if git_cursor_file.is_file():
        try:
            cursor = json.loads(git_cursor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cursor = {}

    # Run git log
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%H%x1f%cI%x1f%B%x1e"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return []

    # Load existing records to check for duplicates
    all_records, _ = records.load_all(home)
    existing_titles = {r.title.casefold() for r in all_records}

    # Load inbox
    inbox_titles = set()
    inbox_dir_path = inbox_dir(home)
    if inbox_dir_path.is_dir():
        for inbox_file in inbox_dir_path.glob("*.md"):
            if inbox_file.name == "rejected.jsonl":
                continue
            try:
                rec = records.read(inbox_file)
                inbox_titles.add(rec.title.casefold())
            except (OSError, RecordError):
                pass

    # Load rejected
    rejected_titles = set()
    rejected_file = inbox_dir_path / "rejected.jsonl"
    if rejected_file.is_file():
        try:
            for line in rejected_file.read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    item = json.loads(line)
                    rejected_titles.add(item.get("title", "").casefold())
        except (OSError, json.JSONDecodeError):
            pass

    proposals: list[str] = []
    repo_str = str(repo)
    last_sha = cursor.get(repo_str)

    # Parse commits
    commits = []
    for commit_text in result.stdout.split("\x1e"):
        if not commit_text.strip():
            continue
        parts = commit_text.split("\x1f", 2)
        if len(parts) < 3:
            continue
        sha, date_str, body = parts
        commits.append((sha, date_str, body))

    # `git log` lists newest first: the unprocessed commits are the ones before the cursor.
    newer = commits
    if last_sha:
        for i, (sha, _, _) in enumerate(commits):
            if sha == last_sha:
                newer = commits[:i]
                break

    # Process commits from oldest to newest
    for sha, date_str, body in reversed(newer):
        # Extract trailers (case-insensitive)
        for trailer_type in ["Brain-Decision", "Brain-Gotcha"]:
            pattern = rf"(?i)^{re.escape(trailer_type)}:\s*(.+)$"
            for match in re.finditer(pattern, body, re.MULTILINE):
                text = match.group(1).strip()

                # Scrub
                text_clean, scrubbed = scrub(text)
                title = text_clean[:200]

                # Check for duplicates
                if (
                    title.casefold() in existing_titles
                    or title.casefold() in inbox_titles
                    or title.casefold() in rejected_titles
                ):
                    continue

                # Determine type
                rec_type = "decision" if trailer_type.lower() == "brain-decision" else "gotcha"

                # Resolve project
                proj = None
                scope = "global"
                try:
                    proj = projects.resolve(home, repo)
                    if proj:
                        scope = "project"
                except Exception:
                    pass

                # Build record
                rec = Record(
                    id=records.new_id("git"),
                    title=title,
                    type=rec_type,
                    scope=scope,
                    project=proj.id if proj else None,
                    status="candidate",
                    grade="OBSERVED",
                    recorded_at=now_iso(),
                    valid_from=date_str,
                    evidence=(f"commit:{sha[:12]}",),
                    body="",
                )

                if scrubbed:
                    rec.extra["scrubbed"] = "true"

                # Validate
                errors = records.validate(rec)
                if errors:
                    continue

                # Write (a dry run only reports)
                if dry_run:
                    proposals.append(rec.id)
                    existing_titles.add(title.casefold())
                    continue
                try:
                    inbox_dir_path.mkdir(parents=True, exist_ok=True)
                    records.write_atomic(
                        inbox_dir_path / f"{rec.id}.md",
                        records.dumps(rec),
                    )
                    proposals.append(rec.id)
                    existing_titles.add(title.casefold())
                except OSError:
                    pass

    # Update cursor
    if not dry_run and commits:
        cursor[repo_str] = commits[0][0]  # most recent commit
        git_cursor_file.parent.mkdir(parents=True, exist_ok=True)
        git_cursor_file.write_text(json.dumps(cursor, indent=2), encoding="utf-8")

    return proposals


def inbox(home: Path) -> list[Record]:
    """List all proposals in inbox, sorted by id."""
    inbox_dir_path = inbox_dir(home)
    results = []

    if not inbox_dir_path.is_dir():
        return results

    for inbox_file in sorted(inbox_dir_path.glob("*.md")):
        try:
            rec = records.read(inbox_file)
            results.append(rec)
        except (OSError, RecordError):
            pass

    return results


def accept(home: Path, record_id: str) -> Record:
    """Move a proposal from inbox to records, update index and views."""
    inbox_dir_path = inbox_dir(home)
    inbox_file = inbox_dir_path / f"{record_id}.md"

    if not inbox_file.is_file():
        raise RecordError(f"record {record_id!r} not in inbox")

    # Load and validate
    rec = records.read(inbox_file)
    errors = records.validate(rec)
    if errors:
        raise RecordError(f"{record_id}: " + "; ".join(errors))

    # Save to records
    records.save(home, rec)

    # Remove from inbox
    inbox_file.unlink()

    # Update index and views
    from . import index, views

    index.refresh(home)
    views.compile_views(home)

    return rec


def reject(home: Path, record_id: str, *, reason: str) -> None:
    """Move a proposal from inbox to rejected.jsonl."""
    if not reason or not reason.strip():
        raise RecordError("rejection reason is required and non-empty")

    inbox_dir_path = inbox_dir(home)
    inbox_file = inbox_dir_path / f"{record_id}.md"
    rejected_file = inbox_dir_path / "rejected.jsonl"

    if not inbox_file.is_file():
        raise RecordError(f"record {record_id!r} not in inbox")

    # Load record
    rec = records.read(inbox_file)

    # Append to rejected.jsonl
    rejection = {
        "id": record_id,
        "title": rec.title,
        "signature": rec.trigger_errors[0] if rec.trigger_errors else "",
        "reason": reason.strip(),
        "at": now_iso(),
    }

    inbox_dir_path.mkdir(parents=True, exist_ok=True)
    with open(rejected_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(rejection) + "\n")

    # Remove from inbox
    inbox_file.unlink()


def stale_evidence(home: Path) -> list[tuple[str, str, str]]:
    """Check evidence staleness for active records.

    Returns list of (record_id, evidence_item, "missing" | "changed").
    Evidence items matching ^(?P<path>[^@\\s]+)@(?P<blob>[0-9a-f]{7,40})
    are checked; CRLF is normalized to LF for blob computation.
    """
    all_records, _ = records.load_all(home)
    results: list[tuple[str, str, str]] = []

    # Load projects for project-scoped records
    proj_dict = {}
    for proj in projects.load_projects(home):
        proj_dict[proj.id] = proj

    for rec in all_records:
        if not rec.active:
            continue

        for evidence_item in rec.evidence:
            # Parse evidence
            match = re.match(
                r"^(?P<path>[^@\s]+)@(?P<blob>[0-9a-f]{7,40})(?: \(repo (?P<repo>.+)\))?$",
                evidence_item,
            )
            if not match:
                continue

            path_str = match.group("path")
            blob_prefix = match.group("blob")

            # Resolve root directory: the recorded repo when it exists here, else the project's
            # first existing path, else the Brain home.
            root = None
            repo_str = match.group("repo")
            if repo_str and Path(repo_str).is_dir():
                root = Path(repo_str)
            if root is None and rec.scope == "project" and rec.project and rec.project in proj_dict:
                proj = proj_dict[rec.project]
                for p in proj.paths:
                    if Path(p).is_dir():
                        root = Path(p)
                        break

            if root is None:
                root = home

            # Check file
            file_path = root / path_str
            if not file_path.is_file():
                results.append((rec.id, evidence_item, "missing"))
                continue

            # Compute blob id
            try:
                data = file_path.read_bytes()
                # Normalize CRLF to LF
                data = data.replace(b"\r\n", b"\n")
                blob_hash = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

                if not blob_hash.startswith(blob_prefix):
                    results.append((rec.id, evidence_item, "changed"))
            except (OSError, Exception):
                results.append((rec.id, evidence_item, "missing"))

    return results
