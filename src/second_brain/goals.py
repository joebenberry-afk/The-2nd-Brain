"""
Long-Running Goals & State Machine (Plan §3 P4.1).

Provides local Brain-owned multi-day and multi-session goal tracking.
Supports:
- Goal lifecycle: PENDING -> ACTIVE -> BLOCKED / COMPLETED / ABANDONED.
- Structured milestones with verification evidence.
- Cross-session objective persistence and resume.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import json
import sqlite3
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
            with contextlib.suppress(FileNotFoundError):
                candidate.unlink()



class GoalStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


_ALLOWED = {
    GoalStatus.PENDING: {GoalStatus.ACTIVE, GoalStatus.ABANDONED},
    GoalStatus.ACTIVE: {GoalStatus.BLOCKED, GoalStatus.COMPLETED, GoalStatus.ABANDONED},
    GoalStatus.BLOCKED: {GoalStatus.ACTIVE, GoalStatus.ABANDONED},
    GoalStatus.COMPLETED: set(),
    GoalStatus.ABANDONED: set(),
}



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
    def _coerce_status(value: GoalStatus | str, field: str = "status") -> GoalStatus:
        try:
            return value if isinstance(value, GoalStatus) else GoalStatus(value)
        except (TypeError, ValueError) as exc:
            raise BrainError(f"Unknown {field} {value!r}") from exc

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> LongRunningGoal:
        goal_id = row["goal_id"]
        try:
            milestones_raw = json.loads(row["milestones_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise BrainError(
                f"Goal {goal_id} has malformed database field milestones_json"
            ) from exc
        if not isinstance(milestones_raw, list):
            raise BrainError(f"Goal {goal_id} database field milestones_json must be a list")
        milestones: list[Milestone] = []
        for index, data in enumerate(milestones_raw):
            if not isinstance(data, dict):
                raise BrainError(
                    f"Goal {goal_id} milestone {index} in database field milestones_json "
                    "must be an object"
                )
            for column in ("milestone_id", "title"):
                if column not in data:
                    raise BrainError(
                        f"Goal {goal_id} milestone {index} missing database field {column}"
                    )
            try:
                milestones.append(Milestone.from_dict(data))
            except (KeyError, TypeError, ValueError) as exc:
                raise BrainError(
                    f"Goal {goal_id} has malformed milestone in database field milestones_json"
                ) from exc
        try:
            status = GoalStatus(row["status"])
        except (TypeError, ValueError) as exc:
            raise BrainError(f"Goal {goal_id} has unknown database field status") from exc
        return LongRunningGoal(
            goal_id=goal_id,
            title=row["title"],
            description=row["description"],
            status=status,
            milestones=milestones,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            target_date=row["target_date"],
            completed_at=row["completed_at"],
            blocker_note=row["blocker_note"] or None,
        )

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        *,
        goal_id: str,
        event_type: str,
        from_status: GoalStatus | None,
        to_status: GoalStatus,
        milestone_id: str | None = None,
        evidence_ref: str | None = None,
        details: dict[str, Any] | None = None,
        created_at: str,
    ) -> None:
        import uuid

        conn.execute(
            "INSERT INTO goal_events "
            "(event_id, goal_id, event_type, from_status, to_status, milestone_id, "
            "evidence_ref, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"event-{uuid.uuid4().hex}",
                goal_id,
                event_type,
                from_status.value if from_status is not None else None,
                to_status.value,
                milestone_id,
                evidence_ref,
                _canonical_json(details or {}),
                created_at,
            ),
        )

    @staticmethod
    def _validate_transition(current: GoalStatus, requested: GoalStatus) -> None:
        if requested not in _ALLOWED[current]:
            raise BrainError(f"Illegal transition {current.value} -> {requested.value}")

    @staticmethod
    def _load_row(conn: sqlite3.Connection, goal_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        if row is None:
            raise BrainError(f"Goal {goal_id} not found")
        return row

    def create_goal(
        self,
        title: str,
        description: str,
        milestone_titles: list[str] | None = None,
        target_date: str | None = None,
        initial_status: GoalStatus = GoalStatus.ACTIVE,
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
        initial_status = self._coerce_status(initial_status, "initial_status")
        now = datetime.now(UTC).isoformat()
        digest = hashlib.sha256(f"{title}:{now}".encode()).hexdigest()[:12]
        goal = LongRunningGoal(
            goal_id=f"goal-{digest}",
            title=title,
            description=description,
            status=initial_status,
            milestones=milestones,
            created_at=now,
            updated_at=now,
            target_date=target_date,
            completed_at=now if initial_status is GoalStatus.COMPLETED else None,
        )
        conn = db.connect(paths.db_path(self.home))
        try:
            conn.execute(
                "INSERT INTO goals "
                "(goal_id, title, description, status, milestones_json, created_at, "
                "updated_at, target_date, completed_at, blocker_note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    goal.goal_id,
                    goal.title,
                    goal.description,
                    goal.status.value,
                    _canonical_json([m.to_dict() for m in goal.milestones]),
                    goal.created_at,
                    goal.updated_at,
                    goal.target_date,
                    goal.completed_at,
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

    def transition(
        self,
        goal_id: str,
        status: GoalStatus,
        *,
        evidence_ref: str | None = None,
        blocker_note: str = "",
    ) -> LongRunningGoal:
        """Atomically transition a goal and append its audit event."""
        requested = self._coerce_status(status)
        evidence = (
            _bounded_text(evidence_ref, "evidence_ref", _MAX_REFERENCE_CHARS)
            if evidence_ref is not None
            else None
        )
        blocker = _bounded_text(blocker_note, "blocker_note")
        if requested is GoalStatus.COMPLETED and not evidence:
            raise BrainError("Completion requires non-empty evidence_ref")
        if requested is GoalStatus.BLOCKED and not blocker:
            raise BrainError("Entering BLOCKED requires non-empty blocker_note")

        conn = db.connect(paths.db_path(self.home))
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = self._row_to_goal(self._load_row(conn, goal_id))
            from_status = current.status
            self._validate_transition(from_status, requested)
            now = datetime.now(UTC).isoformat()
            completed_at = current.completed_at
            if requested is GoalStatus.COMPLETED:
                if completed_at is None:
                    completed_at = now
            elif requested not in (GoalStatus.COMPLETED, GoalStatus.ABANDONED):
                completed_at = None
            current.status = requested
            current.updated_at = now
            current.completed_at = completed_at
            current.blocker_note = blocker or None
            conn.execute(
                "UPDATE goals SET status = ?, updated_at = ?, completed_at = ?, "
                "blocker_note = ? WHERE goal_id = ?",
                (
                    current.status.value,
                    current.updated_at,
                    current.completed_at,
                    blocker,
                    goal_id,
                ),
            )
            self._insert_event(
                conn,
                goal_id=goal_id,
                event_type="STATUS_CHANGED",
                from_status=from_status,
                to_status=requested,
                evidence_ref=evidence,
                details={"blocker_note": blocker},
                created_at=now,
            )
            conn.commit()
            return current
        except BrainError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not transition goal {goal_id}: {exc}") from exc
        finally:
            conn.close()

    def complete_milestone(
        self, goal_id: str, milestone_id: str, evidence_ref: str = ""
    ) -> LongRunningGoal:
        """Atomically complete a milestone with evidence and audit it."""
        evidence = _bounded_text(evidence_ref, "evidence_ref", _MAX_REFERENCE_CHARS)
        if not evidence:
            raise BrainError("Milestone completion requires non-empty evidence_ref")
        conn = db.connect(paths.db_path(self.home))
        try:
            conn.execute("BEGIN IMMEDIATE")
            goal = self._row_to_goal(self._load_row(conn, goal_id))
            from_status = goal.status
            milestone = next(
                (item for item in goal.milestones if item.milestone_id == milestone_id),
                None,
            )
            if milestone is None:
                raise BrainError(f"Milestone {milestone_id} not found on goal {goal_id}")
            if milestone.completed:
                if milestone.evidence_ref == evidence:
                    conn.rollback()
                    return goal
                raise BrainError(
                    f"Milestone {milestone_id} on goal {goal_id} already completed "
                    "with different evidence"
                )
            if goal.status in (GoalStatus.COMPLETED, GoalStatus.ABANDONED):
                raise BrainError(f"Illegal milestone completion on terminal goal {goal_id}")
            now = datetime.now(UTC).isoformat()
            milestone.completed = True
            milestone.evidence_ref = evidence
            milestone.completed_at = now
            new_status = from_status
            completed_at = goal.completed_at
            if goal.milestones and all(item.completed for item in goal.milestones):
                self._validate_transition(from_status, GoalStatus.COMPLETED)
                new_status = GoalStatus.COMPLETED
                if completed_at is None:
                    completed_at = now
            goal.status = new_status
            goal.updated_at = now
            goal.completed_at = completed_at
            conn.execute(
                "UPDATE goals SET status = ?, milestones_json = ?, updated_at = ?, "
                "completed_at = ? WHERE goal_id = ?",
                (
                    goal.status.value,
                    _canonical_json([item.to_dict() for item in goal.milestones]),
                    goal.updated_at,
                    goal.completed_at,
                    goal_id,
                ),
            )
            self._insert_event(
                conn,
                goal_id=goal_id,
                event_type="MILESTONE_COMPLETED",
                from_status=from_status,
                to_status=new_status,
                milestone_id=milestone_id,
                evidence_ref=evidence,
                details={},
                created_at=now,
            )
            conn.commit()
            return goal
        except BrainError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not complete milestone on goal {goal_id}: {exc}") from exc
        finally:
            conn.close()

    def list_goals(
        self,
        statuses: (
            GoalStatus
            | str
            | list[GoalStatus | str]
            | tuple[GoalStatus | str, ...]
            | None
        ) = None,
    ) -> list[LongRunningGoal]:
        """List goals in deterministic newest-updated order, optionally by status."""
        conn = db.connect(paths.db_path(self.home))
        try:
            if statuses is None:
                rows = conn.execute("SELECT * FROM goals ORDER BY updated_at DESC").fetchall()
            else:
                values = [statuses] if isinstance(statuses, (GoalStatus, str)) else statuses
                normalized = [self._coerce_status(value) for value in values]
                if not normalized:
                    return []
                placeholders = ", ".join("?" for _ in normalized)
                rows = conn.execute(
                    f"SELECT * FROM goals WHERE status IN ({placeholders}) "
                    "ORDER BY updated_at DESC",
                    tuple(status.value for status in normalized),
                ).fetchall()
            return [self._row_to_goal(row) for row in rows]
        except BrainError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not list goals: {exc}") from exc
        finally:
            conn.close()

    def list_goal_events(self, goal_id: str) -> list[dict[str, Any]]:
        """Return append-only audit history for one goal, oldest first."""
        conn = db.connect(paths.db_path(self.home))
        try:
            self._load_row(conn, goal_id)
            rows = conn.execute(
                "SELECT * FROM goal_events WHERE goal_id = ? ORDER BY created_at ASC, event_id ASC",
                (goal_id,),
            ).fetchall()
            events: list[dict[str, Any]] = []
            for row in rows:
                try:
                    details = json.loads(row["details_json"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise BrainError(
                        f"Goal {goal_id} has malformed database field goal_events.details_json"
                    ) from exc
                events.append({**dict(row), "details": details})
            return events
        except BrainError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not list history for goal {goal_id}: {exc}") from exc
        finally:
            conn.close()

    def get_goal_history(self, goal_id: str) -> list[dict[str, Any]]:
        """Compatibility accessor for goal audit history."""
        return self.list_goal_events(goal_id)

    def list_active_goals(self) -> list[LongRunningGoal]:
        """List all goals with status ACTIVE or BLOCKED."""
        return self.list_goals([GoalStatus.ACTIVE, GoalStatus.BLOCKED])
