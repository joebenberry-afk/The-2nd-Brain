"""Deterministic local evidence freshness checks for semantic memories."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
from pathlib import Path

from . import db

VERIFIED_CURRENT = "VERIFIED_CURRENT"
CURRENT_BUT_WEAK = "CURRENT_BUT_WEAK"
STALE = "STALE"
SOURCE_MISSING = "SOURCE_MISSING"
SOURCE_MOVED = "SOURCE_MOVED"
CONTRADICTED = "CONTRADICTED"
UNKNOWN = "UNKNOWN"

_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS freshness_cache (
    memory_id TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (memory_id, head_sha)
)
"""
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _run_git(repo_root: Path, *args: str) -> str | None:
    """Run a fixed-argv git command; evidence paths never enter a shell."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _repo_path(repo_root: Path, raw_path: object) -> tuple[Path, str] | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    root = repo_root.resolve()
    candidate = Path(raw_path)
    try:
        absolute = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        relative = absolute.relative_to(root)
    except (OSError, ValueError):
        return None
    # Git accepts platform separators, while stored evidence is portable.
    rel_text = relative.as_posix()
    if not rel_text or rel_text == ".":
        return None
    return absolute, rel_text


def _range_hash(path: Path, start: object, end: object) -> str | None:
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError):
        return None
    if end > len(lines):
        return None
    return hashlib.sha256("".join(lines[start - 1 : end]).encode("utf-8")).hexdigest()


def _cache_get(home: Path, memory_id: str, head_sha: str) -> dict | None:
    try:
        path = home / "state" / "cache" / "freshness.sqlite"
        conn = sqlite3.connect(path)
        try:
            conn.execute(_CACHE_DDL)
            row = conn.execute(
                "SELECT state, reason FROM freshness_cache WHERE memory_id = ? AND head_sha = ?",
                (memory_id, head_sha),
            ).fetchone()
            conn.commit()
            return {"state": row[0], "reason": row[1]} if row else None
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return None


def _cache_put(home: Path, memory_id: str, head_sha: str, result: dict) -> None:
    try:
        path = home / "state" / "cache" / "freshness.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            conn.execute(_CACHE_DDL)
            conn.execute(
                "INSERT OR REPLACE INTO freshness_cache(memory_id, head_sha, state, reason) "
                "VALUES (?, ?, ?, ?)",
                (memory_id, head_sha, result["state"], result["reason"]),
            )
            conn.commit()
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return



def _cache_is_valid(
    cached: dict, rows: list[sqlite3.Row], repo_root: Path
) -> bool:
    """Validate cached states against tracked source blobs.

    HEAD is the durable cache key, but uncommitted edits do not change HEAD.
    Only VERIFIED_CURRENT is reusable after a blob check; all weaker/stale or
    missing states are recomputed so edits, restores, and range changes recover.
    """
    state = cached.get("state")
    if state == UNKNOWN:
        return not rows
    if state != VERIFIED_CURRENT:
        return False
    for row in rows:
        resolved = _repo_path(repo_root, row["path"])
        if resolved is None:
            continue
        path, rel = resolved
        if not path.is_file():
            return False
        blob = _run_git(repo_root, "hash-object", "--", rel)
        if not blob or not row["blob_sha"] or blob != row["blob_sha"]:
            return False
    return True

def _result(state: str, reason: str) -> dict[str, str]:
    return {"state": state, "reason": reason}


def resolve(home: Path | str, memory_id: str, repo_root: Path | str) -> dict[str, str]:
    """Resolve evidence freshness using only the local DB, git, and file hashes.

    All operational failures fail open to ``UNKNOWN``.  The cache is keyed by
    memory and current repository HEAD; a new HEAD naturally invalidates old
    results without mutating canonical memory rows.
    """
    home = Path(home)
    repo_root = Path(repo_root)
    try:
        db.migrate(db.db_path(home))
        head_sha = _run_git(repo_root, "rev-parse", "HEAD") or "<no-head>"
        conn = db.connect(db.db_path(home), readonly=True)
        try:
            memory = conn.execute(
                "SELECT contradiction_count FROM memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
            if memory is not None and int(memory["contradiction_count"] or 0) > 0:
                result = _result(CONTRADICTED, "contradiction override")
                _cache_put(home, str(memory_id), head_sha, result)
                return result
            rows = conn.execute(
                "SELECT repo_id, path, symbol, commit_sha, blob_sha, range_start, range_end, "
                "range_sha, verified_at, source_ref FROM memory_sources "
                "WHERE memory_id = ? ORDER BY id",
                (memory_id,),
            ).fetchall()
        finally:
            conn.close()
        cached = _cache_get(home, str(memory_id), head_sha)
        if cached is not None and _cache_is_valid(cached, rows, repo_root):
            return cached
        if not rows:
            result = _result(UNKNOWN, "no source evidence")
            _cache_put(home, str(memory_id), head_sha, result)
            return result
        saw_stale = False
        for row in rows:
            resolved = _repo_path(repo_root, row["path"])
            if resolved is None:
                continue
            path, rel = resolved
            if not path.is_file():
                moved = _run_git(
                    repo_root, "log", "--follow", "--diff-filter=R", "-1", "--", rel
                )
                if not moved:
                    history = _run_git(
                        repo_root, "log", "HEAD", "--name-status", "--diff-filter=R", "-1"
                    )
                    moved = (
                        history
                        if history
                        and any(
                            part == rel
                            for line in history.splitlines()
                            if line.startswith("R")
                            for part in line.split("\t")[1:]
                        )
                        else None
                    )
                if moved:
                    result = _result(SOURCE_MOVED, "source path was renamed")
                else:
                    result = _result(SOURCE_MISSING, "source path is missing")
                _cache_put(home, str(memory_id), head_sha, result)
                return result
            blob = _run_git(repo_root, "hash-object", "--", rel)
            if blob and row["blob_sha"] and blob == row["blob_sha"]:
                result = _result(VERIFIED_CURRENT, "blob unchanged")
                _cache_put(home, str(memory_id), head_sha, result)
                return result
            range_sha = _range_hash(path, row["range_start"], row["range_end"])
            if range_sha and row["range_sha"] and range_sha == row["range_sha"]:
                result = _result(CURRENT_BUT_WEAK, "blob changed but range unchanged")
                _cache_put(home, str(memory_id), head_sha, result)
                return result
            saw_stale = True
        result = (
            _result(STALE, "source content changed")
            if saw_stale
            else _result(UNKNOWN, "source path unavailable")
        )
        _cache_put(home, str(memory_id), head_sha, result)
        return result
    except Exception:
        return _result(UNKNOWN, "freshness unavailable")


def current_source(home: Path | str, memory_id: str, repo_root: Path | str) -> dict | None:
    """Return the first source whose complete blob still matches."""
    home = Path(home)
    repo_root = Path(repo_root)
    try:
        db.migrate(db.db_path(home))
        conn = db.connect(db.db_path(home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT repo_id, path, symbol, commit_sha, blob_sha, range_start, range_end, "
                "range_sha, verified_at, source_ref FROM memory_sources "
                "WHERE memory_id = ? ORDER BY id",
                (memory_id,),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            resolved = _repo_path(repo_root, row["path"])
            if resolved is None or not resolved[0].is_file():
                continue
            blob = _run_git(repo_root, "hash-object", "--", resolved[1])
            if blob and row["blob_sha"] and blob == row["blob_sha"]:
                return dict(row)
    except Exception:
        return None
    return None
