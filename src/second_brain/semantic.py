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
import logging
import math
import os
import re
import secrets
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .errors import BrainError

_LOG = logging.getLogger("second_brain.semantic")

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


def _version_created_at(home: Path, memory_id: str, version: int, fallback: str) -> str:
    """Original created_at of a version being retired (v1 = row's created_at)."""
    if version <= 1:
        return fallback
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute(
            "SELECT created_at FROM memory_versions WHERE memory_id = ? AND version = ?",
            (memory_id, version),
        ).fetchone()
        return row["created_at"] if row is not None else fallback
    finally:
        conn.close()


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


def _write_file_exclusive(path: Path, data: str) -> None:
    """Write with O_CREAT|O_EXCL: fails instead of overwriting (race-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


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


_FTS5_CREATE = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
    "memory_id UNINDEXED, title, summary, body, project_id, status, "
    "evidence_grade, tags, tokenize = 'unicode61')"
)
# Process-global FTS5 module availability. SQLite's FTS5 support is a
# property of the sqlite3 build, identical for every database, and cannot
# change mid-process. A single flag (not a per-path cache) avoids any hazard
# from temp-dir path reuse (review N4); the CREATE itself still runs per
# database (IF NOT EXISTS, cheap) so every new DB gets its memory_fts table.
_FTS_MODULE_CHECKED = False
_FTS_MODULE_OK = False


def _fts_available(conn: sqlite3.Connection) -> bool:
    """Whether the memory_fts virtual table is usable on this database.

    Review N-C: only "no such module: fts5" permanently degrades the process
    to linear; ANY OTHER OperationalError (transient disk/I-O, per-db issue)
    reports False for this call but is NOT cached, so the next call retries
    the CREATE instead of poisoning the whole process.
    """
    global _FTS_MODULE_CHECKED, _FTS_MODULE_OK
    if _FTS_MODULE_CHECKED and not _FTS_MODULE_OK:
        return False
    try:
        conn.execute(_FTS5_CREATE)
        _FTS_MODULE_CHECKED = True
        _FTS_MODULE_OK = True
        return True
    except sqlite3.OperationalError as exc:
        if "no such module" in str(exc).lower():
            _FTS_MODULE_CHECKED = True
            _FTS_MODULE_OK = False
        # other errors: transient, do not degrade the process permanently
        return False


def _fts_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0])


def _fts_query(term: str) -> str | None:
    """FTS5 MATCH expression: every ASCII alphanumeric token as a quoted
    prefix (`"wal"* "lesson"*`, AND), quoted so FTS5 special characters can
    never break the query.

    Returns None when FTS5 tokenization cannot faithfully represent the term
    (Phase 7 review F2): non-ASCII text (unicode61 would treat "deja" as one
    token, but the ASCII regex would split "déjà" into fragments "d" "j" —
    never emit a MATCH built from fragments) or a term with no tokens
    (punctuation-only). The caller falls back to the linear scan.
    """
    if re.search(r"[^\x00-\x7f]", term):
        return None
    tokens = re.findall(r"[a-z0-9]+", term.lower())
    if not tokens:
        return None
    return " ".join(f'"{token}"*' for token in tokens)


def _body_text(home: Path, row: dict) -> str:
    """Markdown body (after frontmatter) of a memory file; '' when missing."""
    path = (
        Path(home) / row["body_path"] if row.get("body_path") else _v1_path(home, row["memory_id"])
    )
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if content.startswith("---\n") and "\n---" in content:
        content = content.split("\n---", 1)[1]
    return content


def _file_hash(home: Path, row: dict) -> str:
    """sha256 of the canonical markdown file (whole file: any edit changes it)."""
    path = (
        Path(home) / row["body_path"] if row.get("body_path") else _v1_path(home, row["memory_id"])
    )
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _index_memory_row(conn: sqlite3.Connection, home: Path, row: dict, *, file_hash: str) -> None:
    """Upsert one memory into memory_index + memory_fts (derived state)."""
    body = _body_text(home, row)
    tags = ""
    # Optional canonical extension: a comma/space separated `tags:` frontmatter
    # line (not written by the canonical writer; read if a user adds it).
    try:
        path = (
            Path(home) / row["body_path"]
            if row.get("body_path")
            else _v1_path(home, row["memory_id"])
        )
        content = path.read_text(encoding="utf-8")
        if content.startswith("---\n") and "\n---" in content:
            fm = content[4 : content.index("\n---")]
            for line in fm.splitlines():
                if line.startswith("tags:"):
                    tags = ",".join(w for w in re.split(r"[,\s]+", line[5:].strip()) if w)
                    break
    except OSError:
        pass
    conn.execute(
        """INSERT INTO memory_index
           (memory_id, title, summary, project_id, scope, status, evidence_grade,
            current_version, created_at, updated_at, body_path, tags, file_hash, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(memory_id) DO UPDATE SET
             title=excluded.title, summary=excluded.summary, project_id=excluded.project_id,
             scope=excluded.scope, status=excluded.status, evidence_grade=excluded.evidence_grade,
             current_version=excluded.current_version, created_at=excluded.created_at,
             updated_at=excluded.updated_at, body_path=excluded.body_path, tags=excluded.tags,
             file_hash=excluded.file_hash, indexed_at=excluded.indexed_at""",
        (
            row["memory_id"],
            row["title"],
            row.get("summary") or "",
            row.get("project_id"),
            row.get("scope"),
            row.get("status"),
            row.get("evidence_grade"),
            row.get("current_version"),
            row.get("created_at"),
            row.get("updated_at"),
            row.get("body_path"),
            tags,
            file_hash,
            _utcnow(),
        ),
    )
    if _fts_available(conn):
        conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (row["memory_id"],))
        conn.execute(
            "INSERT INTO memory_fts (memory_id, title, summary, body, project_id, "
            "status, evidence_grade, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["memory_id"],
                row["title"],
                row.get("summary") or "",
                body,
                row.get("project_id") or "",
                row.get("status") or "",
                row.get("evidence_grade") or "",
                tags,
            ),
        )


def _index_memory(home: Path, memory_id: str) -> bool:
    """Index one memory (derived state). False when the memory is unknown."""
    row = _row(home, memory_id)
    if row is None:
        return False
    file_hash = _file_hash(home, row)
    conn = db.connect(_dbfile(home))
    try:
        _index_memory_row(conn, home, row, file_hash=file_hash)
        conn.commit()
        return True
    finally:
        conn.close()


def _safe_index(home: Path, memory_id: str) -> None:
    """Lifecycle hook: index failures must never break memory curation.

    The index is derived and rebuildable (`reindex_all`); fail open.
    """
    try:
        _index_memory(home, memory_id)
    except (sqlite3.Error, OSError, BrainError) as exc:
        # Derived index: fail open, but stay observable (F4).
        _LOG.warning("memory index update failed for %s: %s", memory_id, exc)


def index_memory(home: Path, memory_id: str) -> bool:
    """Public: (re)index one memory into the derived SQLite index."""
    _ensure_migrated(home)
    return _index_memory(home, memory_id)


def reindex_all(home: Path) -> dict:
    """Full rebuild of the derived memory index (idempotent, incremental).

    Skips memories whose canonical file hash is unchanged; purges index rows
    whose files no longer exist. Returns {"indexed", "skipped", "purged"}.
    """
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    counts = {"indexed": 0, "skipped": 0, "purged": 0}
    try:
        fts_ok = _fts_available(conn)  # F1: availability derived once
        db_rows = {r["memory_id"]: dict(r) for r in conn.execute("SELECT * FROM memories")}
        for memory_id, row in db_rows.items():
            hash_now = _file_hash(home, row)
            if not hash_now:
                # canonical file missing -> derived row is stale, purge it
                if fts_ok:
                    conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
                conn.execute("DELETE FROM memory_index WHERE memory_id = ?", (memory_id,))
                counts["purged"] += 1
                continue
            prev = conn.execute(
                "SELECT file_hash FROM memory_index WHERE memory_id = ?", (memory_id,)
            ).fetchone()
            if prev is not None and prev["file_hash"] == hash_now:
                counts["skipped"] += 1
                continue
            _index_memory_row(conn, home, row, file_hash=hash_now)
            counts["indexed"] += 1
        # safety net: index rows whose memory row disappeared entirely
        indexed_ids = {r["memory_id"] for r in conn.execute("SELECT memory_id FROM memory_index")}
        for memory_id in indexed_ids - set(db_rows):
            if fts_ok:
                conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            conn.execute("DELETE FROM memory_index WHERE memory_id = ?", (memory_id,))
            counts["purged"] += 1
        conn.commit()
        return counts
    finally:
        conn.close()


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
    path: Path | None = None
    # Exclusive create (O_CREAT|O_EXCL): a concurrent same-id writer can never
    # overwrite our file; DB-failure cleanup below only ever removes OUR file.
    for _ in range(ID_RETRIES):
        candidate = "mem-" + secrets.token_hex(6)
        cand_path = _v1_path(home, candidate)
        if cand_path.exists() or _row(home, candidate) is not None:
            continue
        content = _render_file(
            candidate, title, scope, project_id, "candidate", grade, 1, now, body
        )
        try:
            _write_file_exclusive(cand_path, content)
        except FileExistsError:
            continue
        memory_id = candidate
        path = cand_path
        break
    if memory_id is None or path is None:
        raise BrainError("Could not allocate a unique memory id after 5 attempts")

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
    _safe_index(home, memory_id)
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


def _sync_file_metadata(home: Path, path: str, *, grade: str, status: str) -> None:
    """Rewrite a memory file's frontmatter grade/status lines; body preserved."""
    p = Path(home) / path
    with p.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    if not text.startswith("---"):
        raise BrainError(f"Corrupt memory file (missing frontmatter): {p}")
    fm_end = text.find("\n---\n")
    if fm_end == -1:
        raise BrainError(f"Corrupt memory file (unterminated frontmatter): {p}")
    fm = text[:fm_end]  # "---\nid: ...\ncreated_at: ..."
    rest = text[fm_end + 1 :]  # "---\n<body>" (closing fence kept)
    fm_lines = []
    for line in fm.splitlines():
        if line.startswith("grade:"):
            fm_lines.append(f"grade: {grade}")
        elif line.startswith("status:"):
            fm_lines.append(f"status: {status}")
        else:
            fm_lines.append(line)
    new_text = "\n".join(fm_lines) + "\n" + rest
    _write_file_atomic(p, new_text)


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
    # Files are canonical (plan §7): keep the frontmatter in sync.
    if grade is not None or status is not None:
        _sync_file_metadata(home, row["body_path"], grade=new_grade, status=new_status)
    _safe_index(home, memory_id)  # derived index follows the canonical file
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
    retired_created_at = _version_created_at(home, memory_id, old_version, row["created_at"])
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
            (
                memory_id,
                old_version,
                retired_created_at,
                row["title"],
                row["body_path"],
                change_note,
            ),
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
    _safe_index(home, memory_id)  # derived index follows the new version file
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


_DEDUPE_STATUS_RANK = {"current": 4, "labile": 3, "candidate": 2, "archived": 1, "superseded": 0}
_DEDUPE_GRADE_RANK = {
    "VERIFIED": 4,
    "TESTED": 3,
    "OBSERVED": 2,
    "INFERRED": 1,
    "HISTORICAL": 0,
    "REJECTED": -1,
}
_BODY_SIMILARITY_THRESHOLD = 0.8
# Bodies shorter than this are too small for reliable similarity; title
# equality remains the primary family signal.
_BODY_MIN_TOKENS = 6


def _norm_title(title: str) -> str:
    """Deterministic family key: lowercase alphanumeric runs joined by spaces."""
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))


def _body_tokens(body: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (body or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _same_fact(row_a: dict, row_b: dict) -> bool:
    """Phase 8 family link: same normalized title OR near-identical bodies.

    Deterministic and file-free (the FTS hot path must not read canonical
    files). Exact-body copies are covered by a Jaccard of 1.0.
    """
    title_a, title_b = _norm_title(row_a.get("title") or ""), _norm_title(row_b.get("title") or "")
    if title_a and title_a == title_b:
        return True
    body_a = _body_tokens(_body_text_for_dedupe(row_a))
    body_b = _body_tokens(_body_text_for_dedupe(row_b))
    if len(body_a) < _BODY_MIN_TOKENS or len(body_b) < _BODY_MIN_TOKENS:
        return False
    return _jaccard(body_a, body_b) >= _BODY_SIMILARITY_THRESHOLD


def _body_text_for_dedupe(row: dict) -> str:
    """Body text attached by the search paths (FTS: f.body AS _body, file-free;
    linear: the already-read file body). '' when unavailable."""
    return str(row.get("_body") or row.get("body") or "")


def _dedupe_representative_key(row: dict) -> tuple:
    """Canonical-first representative: highest current_version, then status
    (current > labile > candidate > archived > superseded), then newest
    updated_at, then highest evidence grade, then memory_id (deterministic).
    """
    status_key = str(row.get("status") or "")
    grade_key = str(row.get("evidence_grade") or "")
    return (
        row.get("current_version") or 1,
        _DEDUPE_STATUS_RANK.get(status_key, 0),
        row.get("updated_at") or "",
        _DEDUPE_GRADE_RANK.get(grade_key, 0),
        row.get("memory_id") or "",
    )


_DEDUPE_BODY_SCAN_LIMIT = 200


def _dedupe_family(members: list[dict]) -> list[dict]:
    """Union-find over `members`; one representative per same-fact component.

    Deterministic and bounded: family features (normalized title, body token
    set) are computed ONCE per row; title-equality families are formed in
    O(n); the pairwise body-Jaccard scan (O(n^2)) only runs when the result
    set is small (<= _DEDUPE_BODY_SCAN_LIMIT) so hot-path latency stays
    bounded for broad queries (documented work guard).
    """
    if len(members) <= 1:
        return list(members)
    n = len(members)
    parent = list(range(n))
    titles = [_norm_title(m.get("title") or "") for m in members]
    tokens = [_body_tokens(_body_text_for_dedupe(m)) for m in members]

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    by_title: dict[str, list[int]] = {}
    for i, title in enumerate(titles):
        if title:
            by_title.setdefault(title, []).append(i)
    for group in by_title.values():
        for i in group[1:]:
            union(group[0], i)

    if n <= _DEDUPE_BODY_SCAN_LIMIT:
        for i in range(n):
            for j in range(i + 1, n):
                ti, tj = tokens[i], tokens[j]
                if (
                    len(ti) >= _BODY_MIN_TOKENS
                    and len(tj) >= _BODY_MIN_TOKENS
                    and _jaccard(ti, tj) >= _BODY_SIMILARITY_THRESHOLD
                ):
                    union(i, j)

    components: dict[int, list[dict]] = {}
    for i, row in enumerate(members):
        components.setdefault(find(i), []).append(row)
    return [max(comp, key=_dedupe_representative_key) for comp in components.values()]


def _dedupe_rows(
    rows: list[dict], *, project_id: str | None, include_duplicates: bool
) -> list[dict]:
    """Phase 8: post-filter, pre-budget dedupe (shared by FTS + fallback).

    Families: supersede/near-duplicate groups via `_same_fact`. Scope rule:
    when a project context is supplied, global/domain-scope rows are treated
    as a DISTINCT bucket (comparison may be required); otherwise everything
    dedupes by family. `include_duplicates=True` returns all rows untouched
    (comparison-required exception). Representatives keep their original
    rank order.
    """
    if include_duplicates or len(rows) <= 1:
        return list(rows)

    def bucket(row: dict) -> str:
        if project_id is not None and row.get("scope") in ("global", "domain"):
            return "other"
        return "same"

    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(bucket(row), []).append(row)
    out: list[dict] = []
    for members in buckets.values():
        out.extend(_dedupe_family(members))
    rank = {id(row): i for i, row in enumerate(rows)}
    out.sort(key=lambda row: rank[id(row)])
    return out


# ---------------------------------------------------------------------------
# Phase 9 deterministic ranking (plan §PHASE 9)
#
#   score = relevance * trust * scope_match * freshness
#           * decision_value * negative_transfer_factor
#           - token_cost_penalty
#
# All terms are bounded so no single term can zero or explode the score.
# Weights are HARDCODED constants (TODO Phase 12: wire config/retrieval.toml;
# not wired yet by design). No model calls, no embeddings. The scorer is
# shared verbatim by the FTS path and the linear fallback.
# ---------------------------------------------------------------------------
_SCORE_TERMS = frozenset({"trust", "scope", "freshness", "decision", "negative", "token"})
_GRADE_SCORE = {
    "VERIFIED": 1.0,
    "TESTED": 0.9,
    "OBSERVED": 0.8,
    "INFERRED": 0.7,
    "HISTORICAL": 0.6,
    "REJECTED": 0.5,
}
_STATUS_SCORE = {
    "current": 1.0,
    "labile": 0.95,
    "candidate": 0.9,
    "archived": 0.8,
    "superseded": 0.8,
}
_TITLE_BOOST_EXACT = 0.15
_TITLE_BOOST_PARTIAL = 0.05
_RELEVANCE_CAP = 1.25
_FRESHNESS_HALFLIFE_DAYS = 180.0
_FRESHNESS_MAX_PENALTY = 0.2
_DECISION_BOOST_PER_HIT = 0.1
_DECISION_BOOST_CAP = 0.5
_NEGATIVE_PENALTY_PER_CONTRADICTION = 0.1
_NEGATIVE_PENALTY_CAP = 0.3
_TOKEN_FREE_LIMIT = 400
_TOKEN_PENALTY_CAP = 0.25
_TOKEN_PENALTY_SATURATION = 2000


def _score_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _token_count(text: str) -> int:
    """Total token count (repetitions included) — for the ROI penalty."""
    return len(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _query_tokens(term: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", term.lower()))


_BM25_RELEVANCE_SCALE = 10.0


def _relevance_score(row: dict, query_tokens: set[str], bm25_max: float | None) -> float:
    """FTS path: raw bm25 normalized exponentially against the best match in
    the result set — docs that score (nearly) equally on bm25 keep (nearly)
    equal relevance, so the deterministic metadata terms decide among them;
    genuinely less relevant docs decay fast (one bm25 unit -> ~0.37x).
    Linear path: token-overlap ratio. Title/body boosts are small and
    deterministic. Bounded [0, _RELEVANCE_CAP]."""
    title_tokens = _score_tokens(row.get("title") or "")
    body_tokens = _score_tokens(_body_text_for_dedupe(row))
    raw = row.get("_bm25")
    if bm25_max is not None and raw is not None:
        base = math.exp(-(bm25_max - float(raw)) / _BM25_RELEVANCE_SCALE)
    elif not query_tokens:
        base = 1.0
    else:
        hay = title_tokens | body_tokens | _score_tokens(row.get("summary") or "")
        base = len(query_tokens & hay) / len(query_tokens)
    in_title = query_tokens & title_tokens
    if query_tokens and in_title == query_tokens:
        base += _TITLE_BOOST_EXACT
    elif len(in_title) >= max(1, len(query_tokens) // 2):
        base += _TITLE_BOOST_PARTIAL
    return min(_RELEVANCE_CAP, base)


def _trust_score(row: dict) -> float:
    """Evidence grade * status, both bounded; REJECTED/superseded rows are
    normally filtered before ranking."""
    return _GRADE_SCORE.get(str(row.get("evidence_grade") or ""), 0.8) * _STATUS_SCORE.get(
        str(row.get("status") or ""), 0.9
    )


def _scope_match_score(row: dict, project_id: str | None) -> float:
    """Exact project match > global/domain when a project context is given;
    neutral otherwise."""
    if project_id is None:
        return 1.0
    return 0.9 if row.get("scope") in ("global", "domain") else 1.0


def _freshness_score(updated_at: object) -> float:
    """Gentle linear decay 1.0 -> 0.8 over 180 days; never below 0.8 so a
    stale-but-right memory stays findable (relevance dominates)."""
    try:
        dt = datetime.fromisoformat(str(updated_at))
        days = max(0.0, (datetime.now(UTC) - dt).total_seconds() / 86400.0)
    except (TypeError, ValueError):
        return 0.9
    return 1.0 - _FRESHNESS_MAX_PENALTY * min(1.0, days / _FRESHNESS_HALFLIFE_DAYS)


def _decision_value_score(row: dict) -> float:
    """Memories that resolved past decisions (successful retrievals) rank
    higher. Bounded 1.0..1.5."""
    hits = int(row.get("successful_retrieval_count") or 0)
    return 1.0 + _DECISION_BOOST_PER_HIT * min(hits, 5)


def _negative_transfer_score(row: dict) -> float:
    """Contradicted memories are a negative-transfer risk. Bounded 0.7..1.0."""
    contradictions = int(row.get("contradiction_count") or 0)
    return 1.0 - _NEGATIVE_PENALTY_PER_CONTRADICTION * min(contradictions, 3)


def _token_cost_penalty(row: dict) -> float:
    """Gentle log-shaped per-token ROI penalty on very long bodies; never
    zeroes the score (max 0.25 subtracted)."""
    n = _token_count(_body_text_for_dedupe(row))
    if n <= _TOKEN_FREE_LIMIT:
        return 0.0
    return _TOKEN_PENALTY_CAP * min(
        1.0,
        math.log2(n / _TOKEN_FREE_LIMIT)
        / math.log2(_TOKEN_PENALTY_SATURATION / _TOKEN_FREE_LIMIT),
    )


def _score_row(
    row: dict,
    query_tokens: set[str],
    bm25_max: float | None,
    project_id: str | None,
    score_terms: frozenset[str],
) -> float:
    score = _relevance_score(row, query_tokens, bm25_max)
    if "trust" in score_terms:
        score *= _trust_score(row)
    if "scope" in score_terms:
        score *= _scope_match_score(row, project_id)
    if "freshness" in score_terms:
        score *= _freshness_score(row.get("updated_at"))
    if "decision" in score_terms:
        score *= _decision_value_score(row)
    if "negative" in score_terms:
        score *= _negative_transfer_score(row)
    if "token" in score_terms:
        score -= _token_cost_penalty(row)
    return score


def _rank_rows(
    rows: list[dict],
    term: str,
    *,
    project_id: str | None,
    score_terms: frozenset[str],
) -> list[dict]:
    """Phase 9: score AFTER filters+dedupe, BEFORE budget; stable ordering:
    score desc, then original order (bm25 order on the FTS path, list order
    on the linear path), then memory_id."""
    query_tokens = _query_tokens(term)
    bm25_values = [r.get("_bm25") for r in rows]
    bm25_max = (
        max(float(v) for v in bm25_values if v is not None)
        if any(v is not None for v in bm25_values)
        else None
    )
    scored = [
        (row, index, _score_row(row, query_tokens, bm25_max, project_id, score_terms))
        for index, row in enumerate(rows)
    ]
    scored.sort(key=lambda item: (-item[2], item[1], item[0].get("memory_id") or ""))
    return [item[0] for item in scored]


def search_memories(
    home: Path,
    term: str,
    *,
    project_id: str | None = None,
    include_history: bool = False,
    include_duplicates: bool = False,
    score_terms: frozenset[str] | None = None,
) -> list[dict]:
    """Search semantic memories (plan Phase 6 + Phase 7 hard filters).

    Primary path: SQLite FTS5 (word/prefix tokens, bm25-ranked) over the
    derived memory_fts index. Falls back to the previous linear Markdown
    substring scan when FTS5 is unavailable or the index has not been built
    (missing/empty memory_fts) — fail open, never error. Both paths apply
    the SAME hard filters (Phase 7).

    Phase 7 hard filters (applied BEFORE ranking, as SQL WHERE on the FTS
    path / shared predicate on the fallback path):
      - evidence grade REJECTED: always excluded (rejected != historical).
      - status archived: excluded unless `include_history`.
      - status superseded: excluded unless `include_history` (review N1: ALL
        superseded rows are excluded by default; memory_versions already
        preserves version history, so no carve-out is needed).
      - project_id given: only memories of that project (global/None keeps
        everything).

    Phase 6 scope: minimal faithful ranking (bm25) only. Dedupe,
    contradiction surfacing, and token budgets are Phases 8-11 (TODO anchors
    below). Known divergence: FTS5 matches word prefixes, so a substring in
    the middle of a word (e.g. "arc" inside "sidecar") matches the linear
    scan but not FTS5.
    """
    if not isinstance(term, str) or not term.strip():
        raise BrainError("term must be a non-empty string")
    terms = score_terms if score_terms is not None else _SCORE_TERMS
    _ensure_migrated(home)
    match_expr = _fts_query(term)
    conn = db.connect(_dbfile(home))
    try:
        if match_expr is not None and _fts_available(conn):
            total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            indexed = _fts_count(conn)
            if indexed > 0 or total == 0:
                return _search_fts(
                    conn,
                    match_expr,
                    term,
                    project_id=project_id,
                    include_history=include_history,
                    include_duplicates=include_duplicates,
                    score_terms=terms,
                )
            # Index exists but is empty while memories exist: not built yet.
            # Fall through to the linear scan (fail open).
    except sqlite3.Error:
        pass  # FTS path broken for any reason -> linear fallback below
    finally:
        conn.close()
    return _search_linear(
        home,
        term,
        project_id=project_id,
        include_history=include_history,
        include_duplicates=include_duplicates,
        score_terms=terms,
    )


def _filter_sql(project_id: str | None, include_history: bool) -> tuple[str, list[object]]:
    """Phase 7 hard-filter WHERE clause (shared by the FTS query).

    Cheap SQL: no post-hoc python filtering of the result set.
    """
    clauses = ["m.evidence_grade != 'REJECTED'"]
    params: list[object] = []
    if not include_history:
        # archived + superseded excluded outright (review N1); memory_versions
        # preserves history, so no superseded row is kept by default
        clauses.append("m.status NOT IN ('archived', 'superseded')")
    if project_id is not None:
        clauses.append("m.project_id = ?")
        params.append(project_id)
    return " AND ".join(clauses), params


def _row_passes_filters(row: dict, *, project_id: str | None, include_history: bool) -> bool:
    """Same Phase 7 filter semantics for the linear fallback path."""
    if row.get("evidence_grade") == "REJECTED":
        return False
    status = row.get("status")
    if status in ("archived", "superseded") and not include_history:
        return False
    return project_id is None or row.get("project_id") == project_id


def _search_fts(
    conn: sqlite3.Connection,
    match_expr: str,
    term: str,
    *,
    project_id: str | None = None,
    include_history: bool = False,
    include_duplicates: bool = False,
    score_terms: frozenset[str] = _SCORE_TERMS,
) -> list[dict]:
    """FTS5 query: quoted prefix tokens per word, hard filters (Phase 7),
    dedupe (Phase 8), then deterministic ranking (Phase 9) — post-filter,
    pre-budget.

    TODO(Phase 11): top_k / token budget trimming.
    """
    where, params = _filter_sql(project_id, include_history)
    body_col = "f.body AS _body, " if not include_duplicates else ""
    rows = conn.execute(
        f"SELECT m.*, {body_col}bm25(memory_fts) AS _bm25 FROM memory_fts f "
        "JOIN memories m ON m.memory_id = f.memory_id "
        f"WHERE memory_fts MATCH ? AND {where} ORDER BY bm25(memory_fts), m.memory_id",
        [match_expr, *params],
    ).fetchall()
    rows = _dedupe_rows(
        [dict(row) for row in rows], project_id=project_id, include_duplicates=include_duplicates
    )
    # review N-D: only tokenize bodies for bounded result sets (the pairwise
    # body scan is already guarded; ranking falls back to title/summary
    # signals and zero token penalty for broad queries)
    if len(rows) > _DEDUPE_BODY_SCAN_LIMIT:
        for row in rows:
            row.pop("_body", None)
    return _rank_rows(rows, term, project_id=project_id, score_terms=score_terms)


def _search_linear(
    home: Path,
    term: str,
    *,
    project_id: str | None = None,
    include_history: bool = False,
    include_duplicates: bool = False,
    score_terms: frozenset[str] = _SCORE_TERMS,
) -> list[dict]:
    """Previous linear Markdown scan — FALLBACK when FTS5/index unavailable.

    Applies the same Phase 7 filters, Phase 8 dedupe, and Phase 9 scoring
    (shared scorer) so the fallback cannot regress any of them.

    Matching is FTS-consistent: tokenizable queries match when EVERY query
    token is present (plain substring per token — keeps the documented
    middle-of-word divergence from FTS prefix matching). Queries with no
    tokenizable characters (symbols, non-ASCII) keep the legacy verbatim
    whole-string substring rule so punctuation searches still work.
    """
    needle = term.lower()
    query_tokens = _query_tokens(term)
    out = []
    for row in list_memories(home):
        if not _row_passes_filters(row, project_id=project_id, include_history=include_history):
            continue
        title = (row.get("title") or "").lower()
        summary = (row.get("summary") or "").lower()
        # Clean body (frontmatter stripped) — identical input to the FTS
        # path's dedupe/scoring so the fallback cannot diverge (e.g. a
        # frontmatter-polluted Jaccard failing the family threshold).
        body = _body_text(home, row).lower()
        if query_tokens:
            hay = f"{title} {summary} {body}"
            if not all(token in hay for token in query_tokens):
                continue
        elif needle in title or needle in summary or needle in body:
            pass
        else:
            continue
        row = dict(row)
        row["_body"] = body
        out.append(row)
    rows = _dedupe_rows(out, project_id=project_id, include_duplicates=include_duplicates)
    return _rank_rows(rows, term, project_id=project_id, score_terms=score_terms)
