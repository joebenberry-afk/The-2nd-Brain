"""Reconsolidation / strategic forgetting (plan §49-52/§15, Phase 15 §111).

Advisory-only forgetting. Tracks retrievals and activation outcomes per memory
(meta-memory counters), applies the HOT/WARM/COLD/ARCHIVED heat states, and
runs a decay pass that only moves stale memories OUT of the hot set — it never
destroys canonical evidence and never auto-archives (plan §52).

Protected memories (current+VERIFIED, or constitution/security-titled) never
decay. Heat/status changes are pure metadata: memory files and memory_versions
are never touched, so history stays recoverable.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from . import db, semantic
from .errors import BrainError

HEAT_STATES: tuple[str, ...] = ("HOT", "WARM", "COLD", "ARCHIVED")
ACTIVATION_OUTCOMES: tuple[str, ...] = ("correct", "irrelevant", "contradicted")
HOT_TTL_DAYS = 7
WARM_TTL_DAYS = 30
PROTECTED_TITLE_WORDS = ("constitution", "security")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _dbfile(home: Path) -> Path:
    return db.db_path(home)


def _ensure_migrated(home: Path) -> None:
    if db.pending_migrations(_dbfile(home)):
        db.migrate(_dbfile(home))


def _insert_id(cursor: sqlite3.Cursor) -> int:
    lastrowid = cursor.lastrowid
    if lastrowid is None:
        raise BrainError("Insert did not return a row id")
    return int(lastrowid)


def _memory_row(home: Path, memory_id: str) -> dict:
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    return dict(row)


def _validate_session(session_id: str | None) -> None:
    if session_id is not None and not isinstance(session_id, str):
        raise BrainError("session_id must be a string or None")


def record_retrieval(
    home: Path, memory_id: str, session_id: str | None = None, *, idempotent: bool = False
) -> int:
    """Record a retrieval, optionally deduplicated per memory/session.

    ``idempotent`` is reserved for repeated host-hook feedback. The default
    remains append-only for callers that intentionally record each retrieval.
    """
    if not isinstance(memory_id, str) or not memory_id.strip():
        raise BrainError("memory_id must be a non-empty string")
    _validate_session(session_id)
    _memory_row(home, memory_id)  # existence check + lazy migration
    now = _utcnow()
    conn = db.connect(_dbfile(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        if idempotent and session_id is not None:
            existing = conn.execute(
                "SELECT retrieval_id FROM memory_retrievals "
                "WHERE memory_id = ? AND session_id = ? ORDER BY retrieval_id LIMIT 1",
                (memory_id, session_id),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return int(existing["retrieval_id"])
        cursor = conn.execute(
            "INSERT INTO memory_retrievals (memory_id, session_id, created_at) VALUES (?, ?, ?)",
            (memory_id, session_id, now),
        )
        conn.execute(
            "UPDATE memories SET retrieval_count = retrieval_count + 1, "
            "last_retrieved_at = ? WHERE memory_id = ?",
            (now, memory_id),
        )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record retrieval: {exc}") from exc
    finally:
        conn.close()


def record_activation(
    home: Path,
    memory_id: str,
    outcome: str,
    session_id: str | None = None,
    *,
    idempotent: bool = False,
) -> int:
    """Record an activation outcome; optionally deduplicate host-hook repeats."""
    if not isinstance(memory_id, str) or not memory_id.strip():
        raise BrainError("memory_id must be a non-empty string")
    if outcome not in ACTIVATION_OUTCOMES:
        raise BrainError(f"outcome must be one of {', '.join(ACTIVATION_OUTCOMES)}")
    _validate_session(session_id)
    _memory_row(home, memory_id)  # existence check + lazy migration
    conn = db.connect(_dbfile(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        if idempotent and session_id is not None:
            existing = conn.execute(
                "SELECT activation_id FROM memory_activations "
                "WHERE memory_id = ? AND session_id = ? AND outcome = ? "
                "ORDER BY activation_id LIMIT 1",
                (memory_id, session_id, outcome),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return int(existing["activation_id"])
        cursor = conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at) "
            "VALUES (?, ?, ?, ?)",
            (memory_id, session_id, outcome, _utcnow()),
        )
        if outcome == "correct":
            conn.execute(
                "UPDATE memories SET successful_retrieval_count = successful_retrieval_count + 1 "
                "WHERE memory_id = ?",
                (memory_id,),
            )
        elif outcome == "contradicted":
            conn.execute(
                "UPDATE memories SET contradiction_count = contradiction_count + 1, "
                "heat = 'COLD', status = 'labile' WHERE memory_id = ?",
                (memory_id,),
            )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record activation: {exc}") from exc
    finally:
        conn.close()

def apply_heat(home: Path, memory_id: str, heat: str) -> dict:
    """Set a memory's heat state with plan §52 guardrails:

    - HOT only for status 'current' with grade VERIFIED/TESTED;
    - ARCHIVED never for status 'current';
    - heat is meta-state: no version bump, no file changes.
    """
    if heat not in HEAT_STATES:
        raise BrainError(f"heat must be one of {', '.join(HEAT_STATES)}")
    row = _memory_row(home, memory_id)
    if heat == "HOT" and not (
        row["status"] == "current" and row["evidence_grade"] in ("VERIFIED", "TESTED")
    ):
        raise BrainError("HOT requires status 'current' and grade VERIFIED or TESTED")
    if heat == "ARCHIVED" and row["status"] == "current":
        raise BrainError("ARCHIVED cannot be applied to a memory with status 'current'")
    conn = db.connect(_dbfile(home))
    try:
        conn.execute("UPDATE memories SET heat = ? WHERE memory_id = ?", (heat, memory_id))
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not set heat: {exc}") from exc
    finally:
        conn.close()
    return _memory_row(home, memory_id)


def _protected(row: dict) -> bool:
    if row["status"] == "current" and row["evidence_grade"] == "VERIFIED":
        return True
    title = (row.get("title") or "").lower()
    return any(word in title for word in PROTECTED_TITLE_WORDS)


def _reference_dt(row: dict) -> datetime | None:
    raw = row.get("last_retrieved_at") or row.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def decay_pass(
    home: Path,
    dry_run: bool = True,
    now: str | None = None,
    hot_ttl_days: int = HOT_TTL_DAYS,
    warm_ttl_days: int = WARM_TTL_DAYS,
) -> list[dict]:
    """Advisory decay: HOT -> WARM when stale; WARM -> COLD when never
    retrieved and old. Protected memories never decay; nothing is ever
    auto-ARCHIVED and no evidence is destroyed. Deterministic for a fixed
    `now`."""
    now_iso = now or _utcnow()
    now_dt = datetime.fromisoformat(now_iso)
    changes: list[dict] = []
    for row in semantic.list_memories(home):
        if _protected(row):
            continue
        heat = row.get("heat") or "WARM"
        reference = _reference_dt(row)
        age_days = float("inf") if reference is None else (now_dt - reference).days
        new_heat = heat
        reason = None
        if heat == "HOT" and age_days > hot_ttl_days:
            new_heat = "WARM"
            reason = f"not retrieved in {age_days:.0f} day(s) (TTL {hot_ttl_days})"
        elif heat == "WARM" and (row.get("retrieval_count") or 0) == 0 and age_days > warm_ttl_days:
            new_heat = "COLD"
            reason = f"never retrieved and older than {warm_ttl_days} day(s)"
        if new_heat == heat:
            continue
        changes.append(
            {
                "memory_id": row["memory_id"],
                "title": row["title"],
                "heat_before": heat,
                "heat_after": new_heat,
                "reason": reason,
            }
        )
        if dry_run:
            continue
        conn = db.connect(_dbfile(home))
        try:
            conn.execute(
                "UPDATE memories SET heat = ? WHERE memory_id = ?", (new_heat, row["memory_id"])
            )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not decay memory {row['memory_id']}: {exc}") from exc
        finally:
            conn.close()
    return changes
