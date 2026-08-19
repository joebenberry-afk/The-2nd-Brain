"""
Skill ROI Tracking & Skill Gardener (Plan §3 P3.14, P3.15).

Capabilities:
1. P3.14 Skill ROI Layer:
   - Measures token investment vs tokens saved per skill invocation.
   - Computes net tokens, ROI multiplier, and execution success rate.
2. P3.15 Skill Gardener:
   - Evaluates portfolio health across all skills.
   - Flags degraded/negative-ROI skills for review or automated deprecation.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_roi_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tokens_invested INTEGER NOT NULL,
    tokens_saved INTEGER NOT NULL,
    success INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_name ON skill_roi_ledger (skill_name);
"""


class SkillHealth(StrEnum):
    HEALTHY = "HEALTHY"            # ROI > 0, Success rate ≥ 80%
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Low usage or marginal ROI
    DEGRADED = "DEGRADED"          # Negative net tokens or Success rate < 70%
    DEPRECATED = "DEPRECATED"      # Flagged for archival


@dataclass
class SkillROISummary:
    """ROI summary for a skill."""
    skill_name: str
    invocations: int
    total_tokens_invested: int
    total_tokens_saved: int
    net_tokens_saved: int
    roi_ratio: float
    success_rate: float
    health: SkillHealth
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "invocations": self.invocations,
            "total_tokens_invested": self.total_tokens_invested,
            "total_tokens_saved": self.total_tokens_saved,
            "net_tokens_saved": self.net_tokens_saved,
            "roi_ratio": round(self.roi_ratio, 2),
            "success_rate": round(self.success_rate, 2),
            "health": self.health.value,
            "recommendation": self.recommendation,
        }


class SkillROILedger:
    """Tracks token investments and savings per skill invocation (§3 P3.14)."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self._db_dir = self.home / "state" / "skills"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._dbfile = self._db_dir / "skill_roi.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def record_usage(
        self,
        skill_name: str,
        session_id: str,
        tokens_invested: int,
        tokens_saved: int,
        success: bool = True,
    ) -> None:
        """Record one skill execution in the ROI ledger."""
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                "INSERT INTO skill_roi_ledger "
                "(skill_name, session_id, tokens_invested, tokens_saved, success, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (skill_name, session_id, tokens_invested, tokens_saved, 1 if success else 0, now),
            )
            conn.commit()

    def get_summary(self, skill_name: str) -> SkillROISummary:
        """Compute aggregate ROI and health for a skill."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(tokens_invested), SUM(tokens_saved), SUM(success) "
                "FROM skill_roi_ledger WHERE skill_name = ?",
                (skill_name,),
            ).fetchone()

            if not row or row[0] == 0:
                return SkillROISummary(
                    skill_name=skill_name,
                    invocations=0,
                    total_tokens_invested=0,
                    total_tokens_saved=0,
                    net_tokens_saved=0,
                    roi_ratio=0.0,
                    success_rate=0.0,
                    health=SkillHealth.NEEDS_REVIEW,
                    recommendation="No invocation data yet.",
                )

            invocations = int(row[0])
            invested = int(row[1] or 0)
            saved = int(row[2] or 0)
            success_count = int(row[3] or 0)
            net_saved = saved - invested
            roi_ratio = saved / max(invested, 1)
            success_rate = success_count / max(invocations, 1)

            # Health classification
            if net_saved < 0 or success_rate < 0.60:
                health = SkillHealth.DEGRADED
                recommendation = "Negative ROI or high failure rate: review or deprecate."
            elif roi_ratio >= 1.5 and success_rate >= 0.80:
                health = SkillHealth.HEALTHY
                recommendation = "High value skill: promote to core resident catalog."
            else:
                health = SkillHealth.NEEDS_REVIEW
                recommendation = "Acceptable performance: monitor ongoing ROI."

            return SkillROISummary(
                skill_name=skill_name,
                invocations=invocations,
                total_tokens_invested=invested,
                total_tokens_saved=saved,
                net_tokens_saved=net_saved,
                roi_ratio=roi_ratio,
                success_rate=success_rate,
                health=health,
                recommendation=recommendation,
            )

    def list_all(self) -> list[SkillROISummary]:
        """List summaries for all recorded skills."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            rows = conn.execute(
                "SELECT DISTINCT skill_name FROM skill_roi_ledger ORDER BY skill_name"
            ).fetchall()
            return [self.get_summary(r[0]) for r in rows]


class SkillGardener:
    """Autonomous skill maintenance and portfolio pruning (§3 P3.15)."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self.ledger = SkillROILedger(self.home)

    def audit_portfolio(self) -> dict[str, Any]:
        """
        Scan all skills and produce maintenance recommendations.
        """
        summaries = self.ledger.list_all()
        healthy = [s for s in summaries if s.health == SkillHealth.HEALTHY]
        degraded = [s for s in summaries if s.health == SkillHealth.DEGRADED]
        review = [s for s in summaries if s.health == SkillHealth.NEEDS_REVIEW]

        return {
            "total_skills_tracked": len(summaries),
            "healthy_count": len(healthy),
            "degraded_count": len(degraded),
            "review_count": len(review),
            "degraded_skills": [d.to_dict() for d in degraded],
            "healthy_skills": [h.to_dict() for h in healthy],
        }
