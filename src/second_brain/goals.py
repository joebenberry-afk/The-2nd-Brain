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

from .errors import BrainError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    milestones_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    target_date TEXT,
    completed_at TEXT,
    blocker_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_goal_status ON goals (status);
"""


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
        self._db_dir = self.home / "state" / "goals"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._dbfile = self._db_dir / "goals.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def create_goal(
        self,
        title: str,
        description: str,
        milestone_titles: list[str] | None = None,
        target_date: str | None = None,
    ) -> LongRunningGoal:
        """Create a new long-running goal."""
        import hashlib
        now = datetime.now(UTC).isoformat()
        digest = hashlib.sha256(f"{title}:{now}".encode()).hexdigest()[:12]
        goal_id = f"goal-{digest}"

        milestones = [
            Milestone(milestone_id=f"m-{i+1}", title=t)
            for i, t in enumerate(milestone_titles or [])
        ]

        goal = LongRunningGoal(
            goal_id=goal_id,
            title=title,
            description=description,
            status=GoalStatus.ACTIVE,
            milestones=milestones,
            created_at=now,
            updated_at=now,
            target_date=target_date,
        )

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                "INSERT INTO goals "
                "(goal_id, title, description, status, milestones_json, created_at, "
                " updated_at, target_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    goal.goal_id,
                    goal.title,
                    goal.description,
                    goal.status.value,
                    json.dumps([m.to_dict() for m in goal.milestones]),
                    goal.created_at,
                    goal.updated_at,
                    goal.target_date,
                ),
            )
            conn.commit()

        return goal

    def get_goal(self, goal_id: str) -> LongRunningGoal | None:
        """Retrieve goal by ID."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
            if not row:
                return None
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
                blocker_note=row["blocker_note"],
            )

    def complete_milestone(
        self, goal_id: str, milestone_id: str, evidence_ref: str = ""
    ) -> LongRunningGoal:
        """Mark a milestone as completed with evidence ref."""
        goal = self.get_goal(goal_id)
        if goal is None:
            raise BrainError(f"Goal {goal_id} not found")

        found = False
        now = datetime.now(UTC).isoformat()
        for m in goal.milestones:
            if m.milestone_id == milestone_id:
                m.completed = True
                m.evidence_ref = evidence_ref
                m.completed_at = now
                found = True
                break

        if not found:
            raise BrainError(f"Milestone {milestone_id} not found on goal {goal_id}")

        # Check if all milestones completed
        if all(m.completed for m in goal.milestones):
            goal.status = GoalStatus.COMPLETED
            goal.completed_at = now

        goal.updated_at = now
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                "UPDATE goals SET status = ?, milestones_json = ?, "
                "updated_at = ?, completed_at = ? WHERE goal_id = ?",
                (
                    goal.status.value,
                    json.dumps([m.to_dict() for m in goal.milestones]),
                    goal.updated_at,
                    goal.completed_at,
                    goal.goal_id,
                ),
            )
            conn.commit()

        return goal

    def list_active_goals(self) -> list[LongRunningGoal]:
        """List all goals with status ACTIVE or BLOCKED."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT goal_id FROM goals WHERE status IN ('ACTIVE', 'BLOCKED') "
                "ORDER BY updated_at DESC"
            ).fetchall()
            return [g for r in rows if (g := self.get_goal(r["goal_id"])) is not None]
