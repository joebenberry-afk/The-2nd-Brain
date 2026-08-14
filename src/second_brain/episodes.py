"""Episodic memory vault (plan §12/§46, Phase 9 §105).

Capture-only: an episode is written immediately as an immutable markdown file
under ``memory/episodic/<id>.md`` (frontmatter + the 14 §46 sections) plus a
row in the ``episodes`` table. The body is never edited after creation;
updates happen only via :func:`annotate_episode`, which appends a dated
addendum section.

IDs are ``<type>-<YYYYmmdd>-<8hex>`` (``secrets.token_hex(4)``), checked
against both the file store and the DB, retried up to 5 times — multi-agent
safe. The file is written atomically first, then the DB row; if the insert
fails the file is deleted so no orphans are left. The 0002 migration is
applied lazily when pending.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .errors import BrainError

EPISODE_TYPES: tuple[str, ...] = (
    "success",
    "failure",
    "incident",
    "experiment",
    "correction",
    "surprise",
    "tool-routing",
    "context-efficiency",
    "environment",
    "skill-observation",
)

EPISODE_SECTIONS: tuple[str, ...] = (
    "Situation",
    "Expected",
    "Actual",
    "Actions",
    "Evidence",
    "Root cause",
    "What worked",
    "What failed",
    "Reusable lesson",
    "Trigger signals",
    "Counter-signals",
    "Verification",
    "Related memories",
)

FRONTMATTER_FIELDS: tuple[str, ...] = (
    "id",
    "project",
    "session",
    "task",
    "type",
    "created_at",
    "prediction_error",
    "salience",
    "evidence_grade",
    "evidence_refs",
)
DEFAULT_EVIDENCE_GRADE = "OBSERVED"
ID_RETRIES = 5


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _episodic_dir(home: Path) -> Path:
    return Path(home) / "memory" / "episodic"


def _episode_path(home: Path, episode_id: str) -> Path:
    return _episodic_dir(home) / f"{episode_id}.md"


def _dbfile(home: Path) -> Path:
    return db.db_path(home)


def _ensure_migrated(home: Path) -> None:
    """Apply pending migrations lazily (0002 episodes on v1 brains)."""
    if db.pending_migrations(_dbfile(home)):
        db.migrate(_dbfile(home))


def _row_exists(home: Path, episode_id: str) -> bool:
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute("SELECT 1 FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def _row(home: Path, episode_id: str) -> dict | None:
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _validate_episode_args(
    episode_type: str,
    summary: str,
    prediction_error: float | None,
    salience: float | None,
    evidence_refs: list[str] | None,
    confidence: str | None,
    scope: str,
    sections: dict[str, str] | None,
) -> None:
    if episode_type not in EPISODE_TYPES:
        raise BrainError(f"episode_type must be one of {', '.join(EPISODE_TYPES)}")
    if not isinstance(summary, str) or not summary.strip():
        raise BrainError("summary must be a non-empty string")
    if prediction_error is not None:
        if isinstance(prediction_error, bool) or not isinstance(prediction_error, (int, float)):
            raise BrainError("prediction_error must be a real number")
        if not 0.0 <= float(prediction_error) <= 1.0:
            raise BrainError("prediction_error must be within 0..1")
    if salience is not None and (
        isinstance(salience, bool) or not isinstance(salience, (int, float))
    ):
        raise BrainError("salience must be a real number")
    if evidence_refs is not None and (
        not isinstance(evidence_refs, list)
        or any(not isinstance(ref, str) for ref in evidence_refs)
    ):
        raise BrainError("evidence_refs must be a list of strings or None")
    if confidence is not None and not isinstance(confidence, str):
        raise BrainError("confidence must be a string or None")
    if not isinstance(scope, str) or not scope.strip():
        raise BrainError("scope must be a non-empty string")
    if sections is not None:
        unknown = [name for name in sections if name not in EPISODE_SECTIONS]
        if unknown:
            raise BrainError(f"Unknown episode section(s): {', '.join(sorted(unknown))}")
        for name, value in sections.items():
            if not isinstance(value, str):
                raise BrainError(f"Section {name!r} must be a string")


def _render_frontmatter(
    episode_id: str,
    project_id: str | None,
    session_id: str | None,
    task_id: str | None,
    episode_type: str,
    created_at: str,
    prediction_error: float | None,
    salience: float | None,
    evidence_refs: list[str] | None,
) -> str:
    values = {
        "id": episode_id,
        "project": project_id or "",
        "session": session_id or "",
        "task": task_id or "",
        "type": episode_type,
        "created_at": created_at,
        "prediction_error": "" if prediction_error is None else str(prediction_error),
        "salience": "" if salience is None else str(salience),
        "evidence_grade": DEFAULT_EVIDENCE_GRADE,
        "evidence_refs": json.dumps(evidence_refs or []),
    }
    lines = ["---"]
    for field in FRONTMATTER_FIELDS:
        lines.append(f"{field}: {values[field]}")
    lines.append("---")
    return "\n".join(lines)


def _render_body(summary: str, sections: dict[str, str] | None) -> str:
    sections = sections or {}
    lines = ["", "# Summary", "", summary.strip(), ""]
    for name in EPISODE_SECTIONS:
        content = sections.get(name)
        lines.append(f"# {name}")
        lines.append("")
        lines.append(content if content else "(none)")
        lines.append("")
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


def create_episode(
    home: Path,
    episode_type: str,
    summary: str,
    *,
    project_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    evidence_refs: list[str] | None = None,
    prediction_error: float | None = None,
    salience: float | None = None,
    confidence: str | None = None,
    scope: str = "project",
    sections: dict[str, str] | None = None,
) -> str:
    """Create an episode (file first, then DB row; no orphans on failure)."""
    _validate_episode_args(
        episode_type,
        summary,
        prediction_error,
        salience,
        evidence_refs,
        confidence,
        scope,
        sections,
    )
    _ensure_migrated(home)
    created_at = _utcnow()
    date_part = created_at[:10].replace("-", "")
    episode_id: str | None = None
    path: Path | None = None
    for _ in range(ID_RETRIES):
        candidate = f"{episode_type}-{date_part}-{secrets.token_hex(4)}"
        if _episode_path(home, candidate).exists() or _row_exists(home, candidate):
            continue
        episode_id = candidate
        path = _episode_path(home, candidate)
        break
    if episode_id is None or path is None:
        raise BrainError("Could not allocate a unique episode id after 5 attempts")

    content = _render_frontmatter(
        episode_id,
        project_id,
        session_id,
        task_id,
        episode_type,
        created_at,
        prediction_error,
        salience,
        evidence_refs,
    ) + _render_body(summary, sections)
    _write_file_atomic(path, content)

    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            """INSERT INTO episodes
               (episode_id, project_id, session_id, task_id, episode_type,
                created_at, summary, evidence_refs, prediction_error, salience,
                status, confidence, scope)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'raw', ?, ?)""",
            (
                episode_id,
                project_id,
                session_id,
                task_id,
                episode_type,
                created_at,
                summary,
                json.dumps(evidence_refs) if evidence_refs is not None else None,
                float(prediction_error) if prediction_error is not None else None,
                float(salience) if salience is not None else None,
                confidence,
                scope,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        with contextlib.suppress(OSError):
            path.unlink()  # no orphans: remove the file we just wrote
        raise BrainError(f"Could not insert episode {episode_id}: {exc}") from exc
    finally:
        conn.close()
    return episode_id


def annotate_episode(home: Path, episode_id: str, note: str) -> Path:
    """Append a dated addendum section. The original body is never edited."""
    row = _row(home, episode_id)
    if row is None:
        raise BrainError(f"Unknown episode {episode_id!r}")
    if not isinstance(note, str) or not note.strip():
        raise BrainError("note must be a non-empty string")
    path = _episode_path(home, episode_id)
    if not path.exists():
        raise BrainError(f"Episode file missing for {episode_id!r}: {path}")
    body = path.read_text(encoding="utf-8")
    addendum = f"## Addendum ({_utcnow()})\n\n{note.strip()}\n"
    _write_file_atomic(path, body.rstrip("\n") + "\n\n" + addendum)
    return path


def list_episodes(
    home: Path,
    episode_type: str | None = None,
    project_id: str | None = None,
    since: str | None = None,
) -> list[dict]:
    """Episode DB rows, newest first."""
    query = "SELECT * FROM episodes WHERE 1=1"
    params: list[object] = []
    if episode_type is not None:
        query += " AND episode_type = ?"
        params.append(episode_type)
    if project_id is not None:
        query += " AND project_id = ?"
        params.append(project_id)
    if since is not None:
        query += " AND created_at >= ?"
        params.append(since)
    query += " ORDER BY created_at DESC, episode_id"
    conn = db.connect(_dbfile(home))
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def show_episode(home: Path, episode_id: str) -> dict:
    """The DB row, file path, and full body of one episode."""
    row = _row(home, episode_id)
    if row is None:
        raise BrainError(f"Unknown episode {episode_id!r}")
    path = _episode_path(home, episode_id)
    if not path.exists():
        raise BrainError(f"Episode file missing for {episode_id!r}: {path}")
    body = path.read_text(encoding="utf-8")
    if not body.startswith("---\n") or "\n---" not in body:
        raise BrainError(f"Corrupt episode file {path}: missing frontmatter")
    return {"row": row, "path": str(path), "body": body}


def search_episodes(home: Path, term: str, limit: int = 20) -> list[dict]:
    """Episodes whose summary or section body contains the term
    (case-insensitive substring)."""
    if not isinstance(term, str) or not term.strip():
        raise BrainError("term must be a non-empty string")
    needle = term.lower()
    out: list[dict] = []
    for row in list_episodes(home):
        body = ""
        path = _episode_path(home, row["episode_id"])
        if path.exists():
            try:
                body = path.read_text(encoding="utf-8")
            except OSError:
                body = ""
        if needle in row["summary"].lower() or (body and needle in body.lower()):
            out.append({**row, "body": body})
            if len(out) >= limit:
                break
    return out
