"""Brain sync: sharing records across projects and git synchronization (V3 core).

This module provides two key operations:
- share: Makes a project-scoped record visible to other projects via domain tags
- sync: Commits local records to git and pulls/pushes changes (the only way records leave home)
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import index, records, views
from .records import Record, RecordError


@dataclass
class SyncReport:
    """Result of a sync operation."""

    committed: int  # Number of files committed
    pulled: bool  # Whether pull succeeded
    pushed: bool  # Whether push succeeded
    conflict: str | None  # First 300 chars of conflict error, if any
    notes: list[str]  # Additional notes about the sync


def share(home: Path, record_id: str, *, domains: tuple[str, ...], reason: str) -> Record:
    """Share a project-scoped record with one or more domains (rule 3).

    This is the only way a project record widens its scope. The record changes from
    scope=project to scope=domain, and gains domain tags. The old project is kept as
    provenance in extra["shared_from"], and the share metadata is recorded.

    Args:
        home: Brain home directory
        record_id: The record to share
        domains: Domain tags (each must match ^[a-z0-9][a-z0-9-]{0,39}$)
        reason: Why the record is being shared

    Returns:
        The updated Record with scope=domain

    Raises:
        RecordError: If any precondition fails (no reason, bad tag, record not found,
            not project-scoped, not active, or is global)
    """
    # Validate inputs
    if not reason.strip():
        raise RecordError("share requires a non-empty reason")

    if not domains:
        raise RecordError("share requires at least one domain")

    # Validate each domain tag
    domain_pattern = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
    for domain in domains:
        if not domain_pattern.match(domain):
            raise RecordError(f"domain {domain!r} must match ^[a-z0-9][a-z0-9-]{{0,39}}$")

    # Load the record
    try:
        record = records.load(home, record_id)
    except RecordError as err:
        raise RecordError(f"unknown record {record_id!r}") from err

    # Validate preconditions: project records widen to domain; domain records gain tags.
    if record.scope == "global":
        raise RecordError("cannot share: global records are already visible everywhere")

    if not record.active:
        raise RecordError(f"cannot share: record status is {record.status!r} (not active)")

    # Update record: change scope, merge domains, add metadata
    old_project = record.project
    new_domains = tuple(sorted(set(record.domains) | set(domains)))

    updated = records.replace(
        record,
        scope="domain",
        domains=new_domains,
        extra={
            **record.extra,
            "shared_at": records.now_iso(),
            "shared_from": record.extra.get("shared_from") or old_project or "",
            "share_reason": reason,
        },
    )

    # Save and refresh
    records.save(home, updated)
    index.refresh(home)
    views.compile_views(home)

    return updated


_SYNC_PATHS = ("records", "projects", ":(exclude)records/private")


def sync(
    home: Path,
    *,
    message: str | None = None,
    push: bool = True,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> SyncReport:
    """Commit records and projects to git, then pull and push changes.

    This is the only way Brain records leave the machine through the network.
    Records in records/private/ are gitignored and never committed.

    Steps:
    1. Check that home is in a git work tree
    2. Refuse if any files in records/private/ are tracked by git
    3. Stage records/ and projects/ (private/ is gitignored)
    4. Commit staged files (if any)
    5. Pull with rebase and autostash
    6. Push (if push=True and there's an upstream)
    7. Refresh index and views from pulled records

    Args:
        home: Brain home directory
        message: Commit message (default: auto-generated)
        push: Whether to push after pull (default: True)
        run: Callable for subprocess commands (default: subprocess.run)

    Returns:
        SyncReport with commit, pull, push, and conflict information

    Raises:
        RecordError: If home is not a git work tree or if private records are tracked
    """
    if run is None:
        run = subprocess.run  # type: ignore[assignment]

    home = Path(home)
    notes: list[str] = []
    conflict: str | None = None

    # Step 1: Verify home is in a git work tree
    result = run(
        ["git", "-C", str(home), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise RecordError("brain sync needs the Brain home to be a git checkout")

    # Step 2: Check for tracked files in records/private/
    result = run(
        ["git", "-C", str(home), "ls-files", "records/private"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        tracked_files = result.stdout.strip().split("\n")
        raise RecordError(
            "private records are tracked by git (must remove): " + ", ".join(tracked_files[:3])
        )

    # Step 3: Stage only records/ and projects/ (use git add -A -- to limit scope)
    # Create directories if missing to avoid git add failure
    (Path(home) / "records").mkdir(exist_ok=True)
    (Path(home) / "projects").mkdir(exist_ok=True)

    result = run(
        # Private records are excluded explicitly, not only through .gitignore: a home
        # without the ignore rule must still never publish them.
        ["git", "-C", str(home), "add", "-A", "--", *_SYNC_PATHS],
        capture_output=True,
        text=True,
        check=False,
    )

    # Step 4: Count staged files and commit if any
    committed = 0
    result = run(
        ["git", "-C", str(home), "diff", "--cached", "--name-only", "--", *_SYNC_PATHS],
        capture_output=True,
        text=True,
        check=False,
    )
    staged_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
    committed = len(staged_files)

    if committed > 0:
        if message is None:
            message = f"brain(memory): sync {committed} record files"

        # Commit exactly the staged Brain files: anything else the user staged stays staged.
        result = run(
            ["git", "-C", str(home), "commit", "-m", message, "--pathspec-from-file=-"],
            input="\n".join(staged_files) + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            notes.append(f"commit failed: {result.stderr[:300]}")

    # Step 5: pull and push only against an upstream; without one there is nothing to sync
    # with, which is a note, not a conflict.
    pulled = False
    pushed = False
    upstream = run(
        ["git", "-C", str(home), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if upstream.returncode != 0:
        notes.append("no upstream; not pulled or pushed")
    else:
        result = run(
            ["git", "-C", str(home), "pull", "--rebase", "--autostash"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            pulled = True
        else:
            # Leave the checkout as it was: the local commit stays, nothing is lost.
            run(
                ["git", "-C", str(home), "rebase", "--abort"],
                capture_output=True,
                text=True,
                check=False,
            )
            conflict = (result.stderr or result.stdout)[:300]

        # Step 6: push after a clean pull
        if push and pulled:
            # Push to the tracked branch by name: a local branch named differently from its
            # upstream is refused by a bare `git push` under push.default=simple.
            remote, _, branch = upstream.stdout.strip().partition("/")
            result = run(
                ["git", "-C", str(home), "push", remote, f"HEAD:{branch}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                pushed = True
            else:
                notes.append(f"push failed: {result.stderr[:300]}")

    # Step 7: Refresh index and views after pull
    if pulled:
        index.refresh(home)
        views.compile_views(home)

    return SyncReport(
        committed=committed,
        pulled=pulled,
        pushed=pushed,
        conflict=conflict,
        notes=notes,
    )
