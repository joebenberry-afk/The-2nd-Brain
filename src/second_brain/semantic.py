"""Semantic memory cortex (plan §13/§47-49, Phase 10 §106).

Manual curation first. A memory is an immutable-per-version markdown file under
``memory/semantic/`` (frontmatter + body) plus rows in the ``memories``,
``memory_sources`` and ``memory_versions`` tables.

Evidence grades are strictly ordered (INFERRED < OBSERVED < TESTED < VERIFIED)
and only move one step up per curation; REJECTED is reachable from anywhere and
HISTORICAL only as a downgrade. The grade is never changed silently — curate is
the only mutation path, and show_memory always surfaces the stored grade.
Superseding writes a new versioned file (``<id>__v<N>.md`` for N>=2) and keeps
every previous file, so history is preserved.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .errors import BrainError

GRADES: tuple[str, ...] = ("OBSERVED", "TESTED", "VERIFIED", "INFERRED", "HISTORICAL", "REJECTED")
STATUSES: tuple[str, ...] = ("candidate", "current", "labile", "superseded", "archived")
SCOPES: tuple[str, ...] = ("project", "domain", "global")
SOURCE_KINDS: tuple[str, ...] = ("evidence", "episode", "test", "decision", "import")

# Rank for upgrade/downgrade decisions; HISTORICAL/REJECTED sit below everything.
_GRADE_RANK = {
    "INFERRED": 0,
    "OBSERVED": 1,
    "TESTED": 2,
    "VERIFIED": 3,
    "HISTORICAL": -1,
    "REJECTED": -2,
}
_UPGRADE_CHAIN = ("INFERRED", "OBSERVED", "TESTED", "VERIFIED")

FRONTMATTER_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "scope",
    "project",
    "status",
    "grade",
    "version",
    "created_at",
)
DEFAULT_STRENGTH = 0.5
DEFAULT_STABILITY = 0.5
ID_RETRIES = 5


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _semantic_dir(home: Path) -> Path:
    return Path(home) / "memory" / "semantic"


def _v1_path(home: Path, memory_id: str) -> Path:
    return _semantic_dir(home) / f"{memory_id}.md"


def _version_path(home: Path, memory_id: str, version: int) -> Path:
    if version <= 1:
        return _v1_path(home, memory_id)
    return _semantic_dir(home) / f"{memory_id}__v{version}.md"


def _dbfile(home: Path) -> Path:
    return db.db_path(home)


def _ensure_migrated(home: Path) -> None:
    if db.pending_migrations(_dbfile(home)):
        db.migrate(_dbfile(home))


def _row(home: Path, memory_id: str) -> dict | None:
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _sources(home: Path, memory_id: str) -> list[dict]:
    conn = db.connect(_dbfile(home))
    try:
        rows = conn.execute(
            "SELECT source_ref, source_kind, added_at FROM memory_sources "
            "WHERE memory_id = ? ORDER BY id",
            (memory_id,),
        ).fetchall()
        return [
            {"ref": r["source_ref"], "kind": r["source_kind"], "added_at": r["added_at"]}
            for r in rows
        ]
    finally:
        conn.close()


def _insert_sources(
    conn: sqlite3.Connection, memory_id: str, sources: list[dict], now: str
) -> None:
    for source in sources:
        conn.execute(
            "INSERT INTO memory_sources (memory_id, source_ref, source_kind, added_at) "
            "VALUES (?, ?, ?, ?)",
            (memory_id, source["ref"], source["kind"], now),
        )


def _validate_sources(sources: list[dict] | None) -> list[dict]:
    if sources is None:
        return []
    if not isinstance(sources, list):
        raise BrainError("sources must be a list of {ref, kind} dicts or None")
    out = []
    for source in sources:
        if not isinstance(source, dict):
            raise BrainError("sources must be a list of {ref, kind} dicts or None")
        ref = source.get("ref")
        kind = source.get("kind", "evidence")
        if not isinstance(ref, str) or not ref.strip():
            raise BrainError(f"source ref must be a non-empty string: {source!r}")
        if kind not in SOURCE_KINDS:
            raise BrainError(f"source kind must be one of {', '.join(SOURCE_KINDS)}")
        out.append({"ref": ref, "kind": kind})
    return out


def _validate_new(title: str, body: str, scope: str, grade: str) -> None:
    if not isinstance(title, str) or not title.strip():
        raise BrainError("title must be a non-empty string")
    if not isinstance(body, str) or not body.strip():
        raise BrainError("body must be a non-empty string")
    if scope not in SCOPES:
        raise BrainError(f"scope must be one of {', '.join(SCOPES)}")
    if grade not in GRADES:
        raise BrainError(f"grade must be one of {', '.join(GRADES)}")


def _render_file(
    memory_id: str,
    title: str,
    scope: str,
    project_id: str | None,
    status: str,
    grade: str,
    version: int,
    created_at: str,
    body: str,
) -> str:
    lines = [
        "---",
        f"id: {memory_id}",
        f"title: {title}",
        f"scope: {scope}",
        f"project: {project_id or ''}",
        f"status: {status}",
        f"grade: {grade}",
        f"version: {version}",
        f"created_at: {created_at}",
        "---",
        "",
        body.rstrip(),
        "",
    ]
    return "\n".join(lines)


def _write_file_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write {path}: {exc}") from exc


def add_memory(
    home: Path,
    title: str,
    body: str,
    *,
    scope: str = "project",
    project_id: str | None = None,
    grade: str = "OBSERVED",
    sources: list[dict] | None = None,
    summary: str | None = None,
) -> str:
    """Create a semantic memory (v1 file first, then DB row + sources)."""
    _validate_new(title, body, scope, grade)
    clean_sources = _validate_sources(sources)
    if summary is not None and not isinstance(summary, str):
        raise BrainError("summary must be a string or None")
    _ensure_migrated(home)

    now = _utcnow()
    memory_id: str | None = None
    for _ in range(ID_RETRIES):
        candidate = "mem-" + secrets.token_hex(6)
        if _v1_path(home, candidate).exists() or _row(home, candidate) is not None:
            continue
        memory_id = candidate
        break
    if memory_id is None:
        raise BrainError("Could not allocate a unique memory id after 5 attempts")

    path = _v1_path(home, memory_id)
    content = _render_file(memory_id, title, scope, project_id, "candidate", grade, 1, now, body)
    _write_file_atomic(path, content)

    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            """INSERT INTO memories
               (memory_id, title, scope, project_id, status, evidence_grade,
                current_version, created_at, updated_at, last_verified_at,
                strength, stability, summary, body_path)
               VALUES (?, ?, ?, ?, 'candidate', ?, 1, ?, ?, NULL, ?, ?, ?, ?)""",
            (
                memory_id,
                title,
                scope,
                project_id,
                grade,
                now,
                now,
                DEFAULT_STRENGTH,
                DEFAULT_STABILITY,
                summary,
                str(path.relative_to(home)),
            ),
        )
        _insert_sources(conn, memory_id, clean_sources, now)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        with contextlib.suppress(OSError):
            path.unlink()  # no orphans
        raise BrainError(f"Could not insert memory {memory_id}: {exc}") from exc
    finally:
        conn.close()
    return memory_id


def _check_grade_transition(current: str, new: str) -> None:
    """One-step upgrade, same grade, REJECTED anywhere, HISTORICAL downgrade only."""
    if new == current or new == "REJECTED":
        return
    if new == "HISTORICAL" and _GRADE_RANK[new] < _GRADE_RANK[current]:
        return
    if (
        current in _UPGRADE_CHAIN
        and new in _UPGRADE_CHAIN
        and _GRADE_RANK[new] == _GRADE_RANK[current] + 1
    ):
        return
    raise BrainError(
        f"Grade transition {current} -> {new} not allowed "
        "(one-step upgrades only; downgrades only to REJECTED/HISTORICAL)"
    )


def curate(
    home: Path,
    memory_id: str,
    *,
    grade: str | None = None,
    status: str | None = None,
    sources: list[dict] | None = None,
    verify: bool = True,
) -> dict:
    """Curate one memory: grade/status transitions, sources, verification."""
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    if grade is not None:
        if grade not in GRADES:
            raise BrainError(f"grade must be one of {', '.join(GRADES)}")
        _check_grade_transition(row["evidence_grade"], grade)
    if status is not None and status not in STATUSES:
        raise BrainError(f"status must be one of {', '.join(STATUSES)}")
    clean_sources = _validate_sources(sources)

    now = _utcnow()
    new_grade = grade if grade is not None else row["evidence_grade"]
    new_status = status if status is not None else row["status"]
    last_verified = row["last_verified_at"]
    if new_grade == "VERIFIED" and verify:
        last_verified = now

    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            "UPDATE memories SET evidence_grade = ?, status = ?, updated_at = ?, "
            "last_verified_at = ? WHERE memory_id = ?",
            (new_grade, new_status, now, last_verified, memory_id),
        )
        _insert_sources(conn, memory_id, clean_sources, now)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not curate memory {memory_id}: {exc}") from exc
    finally:
        conn.close()
    return _row(home, memory_id) or {}


def list_memories(
    home: Path,
    scope: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    grade: str | None = None,
) -> list[dict]:
    """Memory rows, most recently updated first."""
    query = "SELECT * FROM memories WHERE 1=1"
    params: list[object] = []
    for field, value in (
        ("scope", scope),
        ("project_id", project_id),
        ("status", status),
        ("evidence_grade", grade),
    ):
        if value is not None:
            query += f" AND {field} = ?"
            params.append(value)
    query += " ORDER BY updated_at DESC, memory_id"
    conn = db.connect(_dbfile(home))
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def show_memory(home: Path, memory_id: str) -> dict:
    """The DB row (incl. stored evidence_grade), file path, and body."""
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    path = Path(home) / row["body_path"] if row["body_path"] else _v1_path(home, memory_id)
    if not path.exists():
        raise BrainError(f"Memory file missing for {memory_id!r}: {path}")
    body = path.read_text(encoding="utf-8")
    if not body.startswith("---\n") or "\n---" not in body:
        raise BrainError(f"Corrupt memory file {path}: missing frontmatter")
    return {"row": row, "path": str(path), "body": body}


def supersede(
    home: Path,
    memory_id: str,
    *,
    new_title: str | None = None,
    new_body: str,
    change_note: str,
    new_sources: list[dict] | None = None,
) -> int:
    """Create the next version; every previous version file is preserved."""
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    if not isinstance(new_body, str) or not new_body.strip():
        raise BrainError("new_body must be a non-empty string")
    if not isinstance(change_note, str) or not change_note.strip():
        raise BrainError("change_note must be a non-empty string")
    if new_title is not None and (not isinstance(new_title, str) or not new_title.strip()):
        raise BrainError("new_title must be a non-empty string or None")
    clean_sources = _validate_sources(new_sources)

    old_version = row["current_version"]
    new_version = old_version + 1
    now = _utcnow()
    new_path = _version_path(home, memory_id, new_version)
    title = new_title if new_title is not None else row["title"]
    content = _render_file(
        memory_id,
        title,
        row["scope"],
        row["project_id"],
        row["status"],
        row["evidence_grade"],
        new_version,
        row["created_at"],
        new_body,
    )
    _write_file_atomic(new_path, content)

    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            "INSERT INTO memory_versions "
            "(memory_id, version, created_at, title, body_path, change_note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (memory_id, old_version, now, row["title"], row["body_path"], change_note),
        )
        conn.execute(
            "UPDATE memories SET title = ?, current_version = ?, updated_at = ?, "
            "body_path = ? WHERE memory_id = ?",
            (title, new_version, now, str(new_path.relative_to(home)), memory_id),
        )
        _insert_sources(conn, memory_id, clean_sources, now)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        with contextlib.suppress(OSError):
            new_path.unlink()  # no orphans
        raise BrainError(f"Could not supersede memory {memory_id}: {exc}") from exc
    finally:
        conn.close()
    return new_version


def history(home: Path, memory_id: str) -> list[dict]:
    """All versions (oldest first) with paths and change notes."""
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    conn = db.connect(_dbfile(home))
    try:
        versions = [
            dict(r)
            for r in conn.execute(
                "SELECT memory_id, version, created_at, title, body_path, change_note "
                "FROM memory_versions WHERE memory_id = ? ORDER BY version",
                (memory_id,),
            ).fetchall()
        ]
    finally:
        conn.close()
    current = {
        "memory_id": memory_id,
        "version": row["current_version"],
        "created_at": row["updated_at"],
        "title": row["title"],
        "body_path": row["body_path"],
        "change_note": None,  # the current version has no change note
    }
    versions.append(current)
    return versions


def contradictions(home: Path, scope: str = "project") -> list[dict]:
    """Same-title (case-insensitive) memories with different body hashes where
    neither side is REJECTED/ARCHIVED. Deterministic pair order."""
    by_title: dict[str, list[dict]] = {}
    for row in list_memories(home, scope=scope):
        key = row["title"].strip().lower()
        if row["evidence_grade"] == "REJECTED" or row["status"] == "archived":
            continue
        by_title.setdefault(key, []).append(row)
    pairs: list[dict] = []
    for title, entries in sorted(by_title.items()):
        entries.sort(key=lambda r: r["memory_id"])
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                hash_a = _body_hash(home, a)
                hash_b = _body_hash(home, b)
                if hash_a is None or hash_b is None:
                    continue
                if hash_a != hash_b:
                    pairs.append(
                        {
                            "title": title,
                            "memory_id_a": a["memory_id"],
                            "memory_id_b": b["memory_id"],
                        }
                    )
    return pairs


def _body_hash(home: Path, row: dict) -> str | None:
    """Hash only the body (frontmatter carries per-file timestamps, so the
    whole-file hash would differ even for identical bodies)."""
    path = Path(home) / row["body_path"] if row["body_path"] else _v1_path(home, row["memory_id"])
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if content.startswith("---\n") and "\n---" in content:
        content = content.split("\n---", 1)[1]
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def search_memories(home: Path, term: str) -> list[dict]:
    """Memories whose title, summary, or body contains the term (case-insensitive)."""
    if not isinstance(term, str) or not term.strip():
        raise BrainError("term must be a non-empty string")
    needle = term.lower()
    out = []
    for row in list_memories(home):
        title = (row.get("title") or "").lower()
        summary = (row.get("summary") or "").lower()
        body = ""
        path = (
            Path(home) / row["body_path"] if row["body_path"] else _v1_path(home, row["memory_id"])
        )
        if path.exists():
            try:
                body = path.read_text(encoding="utf-8").lower()
            except OSError:
                body = ""
        if needle in title or needle in summary or needle in body:
            out.append(row)
    return out
