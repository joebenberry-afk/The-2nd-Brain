"""
Long-Running Goals & State Machine (Plan §3 P4.1).

Provides local Brain-owned multi-day and multi-session goal tracking.
Supports:
- Goal lifecycle: PENDING -> ACTIVE -> BLOCKED / COMPLETED / ABANDONED.
- Structured milestones with verification evidence.
- Cross-session objective persistence and resume.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import db, paths
from .errors import BrainError, MigrationError
_MAX_TEXT_CHARS = 512
_MAX_REFERENCE_CHARS = 256


def _bounded_text(value: object, field: str, limit: int = _MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise BrainError(f"{field} must be a string")
    return value.strip()[:limit]


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BrainError("malformed JSON value") from exc


def _legacy_sidecar_has_rows(path: Path) -> bool:
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            return any(
                conn.execute(
                    f'SELECT 1 FROM "{str(table[0]).replace(chr(34), chr(34) * 2)}" LIMIT 1'
                ).fetchone()
                is not None
                for table in tables
            )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise MigrationError(f"Cannot inspect legacy goals sidecar {path}: {exc}") from exc


def _retire_legacy_sidecars(home: Path) -> None:
    directory = home / "state" / "goals"
    sidecars = sorted(directory.glob("*.sqlite")) if directory.is_dir() else []
    if any(_legacy_sidecar_has_rows(path) for path in sidecars):
        raise MigrationError(
            "Refusing to discard non-empty legacy goals sidecar; migrate it explicitly"
        )
    for path in sidecars:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass



class GoalStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


@dataclass
class Milestone:
    """A milestone within a long-running goal."""
    milestone_id: str
    title: str
    completed: bool = False
    evidence_ref: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "title": self.title,
            "completed": self.completed,
            "evidence_ref": self.evidence_ref,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Milestone:
        return cls(
            milestone_id=data["milestone_id"],
            title=data["title"],
            completed=data.get("completed", False),
            evidence_ref=data.get("evidence_ref", ""),
            completed_at=data.get("completed_at", ""),
        )


@dataclass
class LongRunningGoal:
    """A multi-day or multi-session goal (§3 P4.1)."""
    goal_id: str
    title: str
    description: str
    status: GoalStatus
    milestones: list[Milestone] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    target_date: str | None = None
    completed_at: str | None = None
    blocker_note: str | None = None

    def progress_pct(self) -> float:
        if not self.milestones:
            return 100.0 if self.status == GoalStatus.COMPLETED else 0.0
        done = sum(1 for m in self.milestones if m.completed)
        return round((done / len(self.milestones)) * 100.0, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "progress_pct": round(self.progress_pct(), 1),
            "milestones": [m.to_dict() for m in self.milestones],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "target_date": self.target_date,
            "completed_at": self.completed_at,
            "blocker_note": self.blocker_note,
        }


class GoalStore:
    """SQLite-backed persistent store for long-running goals (§3 P4.1)."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        _retire_legacy_sidecars(self.home)
        db.migrate(paths.db_path(self.home))

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> LongRunningGoal:
        milestones_raw = json.loads(row["milestones_json"])
        milestones = [Milestone.from_dict(m) for m in milestones_raw]
        return LongRunningGoal(
            goal_id=row["goal_id"],
            title=row["title"],
            description=row["description"],
            status=GoalStatus(row["status"]),
            milestones=milestones,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            target_date=row["target_date"],
            completed_at=row["completed_at"],
            blocker_note=row["blocker_note"] or None,
        )

    def create_goal(
        self,
        title: str,
        description: str,
        milestone_titles: list[str] | None = None,
        target_date: str | None = None,
    ) -> LongRunningGoal:
        """Create a new long-running goal."""
        import hashlib

        title = _bounded_text(title, "title")
        description = _bounded_text(description, "description")
        if milestone_titles is not None and not isinstance(milestone_titles, list):
            raise BrainError("milestone_titles must be a list")
        milestones = [
            Milestone(
                milestone_id=f"m-{i + 1}",
                title=_bounded_text(value, "milestone title"),
            )
            for i, value in enumerate(milestone_titles or [])
        ]
        if target_date is not None and not isinstance(target_date, str):
            raise BrainError("target_date must be a string or None")
        now = datetime.now(UTC).isoformat()
        digest = hashlib.sha256(f"{title}:{now}".encode()).hexdigest()[:12]
        goal = LongRunningGoal(
            goal_id=f"goal-{digest}",
            title=title,
            description=description,
            status=GoalStatus.ACTIVE,
            milestones=milestones,
            created_at=now,
            updated_at=now,
            target_date=target_date,
        )
        conn = db.connect(paths.db_path(self.home))
        try:
            conn.execute(
                "INSERT INTO goals "
                "(goal_id, title, description, status, milestones_json, created_at, "
                "updated_at, target_date, blocker_note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    goal.goal_id,
                    goal.title,
                    goal.description,
                    goal.status.value,
                    _canonical_json([m.to_dict() for m in goal.milestones]),
                    goal.created_at,
                    goal.updated_at,
                    goal.target_date,
                    "",
                ),
            )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not create goal: {exc}") from exc
        finally:
            conn.close()
        return goal

    def get_goal(self, goal_id: str) -> LongRunningGoal | None:
        """Retrieve goal by ID."""
        conn = db.connect(paths.db_path(self.home))
        try:
            row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
            return self._row_to_goal(row) if row else None
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not retrieve goal: {exc}") from exc
        finally:
            conn.close()

    def complete_milestone(
        self, goal_id: str, milestone_id: str, evidence_ref: str = ""
    ) -> LongRunningGoal:
        """Mark a milestone as completed with evidence ref."""
        goal = self.get_goal(goal_id)
        if goal is None:
            raise BrainError(f"Goal {goal_id} not found")
        evidence_ref = _bounded_text(evidence_ref, "evidence_ref", _MAX_REFERENCE_CHARS)
        now = datetime.now(UTC).isoformat()
        for milestone in goal.milestones:
            if milestone.milestone_id == milestone_id:
                milestone.completed = True
                milestone.evidence_ref = evidence_ref
                milestone.completed_at = now
                break
        else:
            raise BrainError(f"Milestone {milestone_id} not found on goal {goal_id}")
        if all(m.completed for m in goal.milestones):
            goal.status = GoalStatus.COMPLETED
            goal.completed_at = now
        goal.updated_at = now
        conn = db.connect(paths.db_path(self.home))
        try:
            conn.execute(
                "UPDATE goals SET status = ?, milestones_json = ?, "
                "updated_at = ?, completed_at = ? WHERE goal_id = ?",
                (
                    goal.status.value,
                    _canonical_json([m.to_dict() for m in goal.milestones]),
                    goal.updated_at,
                    goal.completed_at,
                    goal.goal_id,
                ),
            )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not update goal: {exc}") from exc
        finally:
            conn.close()
        return goal

    def list_active_goals(self) -> list[LongRunningGoal]:
        """List all goals with status ACTIVE or BLOCKED."""
        conn = db.connect(paths.db_path(self.home))
        try:
            rows = conn.execute(
                "SELECT * FROM goals WHERE status IN ('ACTIVE', 'BLOCKED') "
                "ORDER BY updated_at DESC"
            ).fetchall()
            return [self._row_to_goal(row) for row in rows]
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not list goals: {exc}") from exc
        finally:
            conn.close()
