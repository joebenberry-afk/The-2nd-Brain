"""
Structural Bottleneck Fingerprinting (Plan §3 P4.4).

Detects, fingerprints, and tracks structural token and latency bottlenecks across sessions.
Categories:
- PROMPT_BLOAT: Excessive system or context prefix overhead.
- TOOL_CHAIN_THRASH: Long repetitive tool calls.
- UNCOMPRESSED_PAYLOAD: Bulky raw outputs bypassing the Observation Firewall.
- CACHE_UNDERUTILIZATION: Pure actions running repeatedly without Action Cache reuse.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bottleneck_fingerprints (
    fingerprint_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    impact_score REAL NOT NULL,
    occurrence_count INTEGER NOT NULL,
    description TEXT NOT NULL,
    mitigation TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bottleneck_cat ON bottleneck_fingerprints (category);
CREATE INDEX IF NOT EXISTS idx_bottleneck_impact ON bottleneck_fingerprints (impact_score DESC);
"""


class BottleneckCategory(StrEnum):
    PROMPT_BLOAT = "PROMPT_BLOAT"
    TOOL_CHAIN_THRASH = "TOOL_CHAIN_THRASH"
    UNCOMPRESSED_PAYLOAD = "UNCOMPRESSED_PAYLOAD"
    CACHE_UNDERUTILIZATION = "CACHE_UNDERUTILIZATION"
    RETRIEVAL_OVERLOAD = "RETRIEVAL_OVERLOAD"


@dataclass
class BottleneckFingerprint:
    """A structural bottleneck pattern fingerprint (§3 P4.4)."""
    fingerprint_id: str
    category: BottleneckCategory
    impact_score: float  # 0.0 - 10.0 scale of token/latency severity
    occurrence_count: int
    description: str
    mitigation: str
    first_seen: str
    last_seen: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint_id": self.fingerprint_id,
            "category": self.category.value,
            "impact_score": round(self.impact_score, 2),
            "occurrence_count": self.occurrence_count,
            "description": self.description,
            "mitigation": self.mitigation,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "metadata": self.metadata,
        }


class BottleneckFingerprintStore:
    """Persistent database for structural bottleneck fingerprints."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self._db_dir = self.home / "state" / "fingerprints"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._dbfile = self._db_dir / "fingerprints.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def record_bottleneck(
        self,
        category: BottleneckCategory | str,
        description: str,
        mitigation: str,
        impact_score: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> BottleneckFingerprint:
        """Record or increment a bottleneck fingerprint."""
        cat = (
            category
            if isinstance(category, BottleneckCategory)
            else BottleneckCategory(str(category).upper())
        )
        norm_desc = " ".join(description.strip().lower().split())
        fp_id = f"fp-{hashlib.sha256(f'{cat.value}:{norm_desc}'.encode()).hexdigest()[:12]}"
        now = datetime.now(UTC).isoformat()

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM bottleneck_fingerprints WHERE fingerprint_id = ?",
                (fp_id,),
            ).fetchone()

            if row:
                count = row["occurrence_count"] + 1
                new_impact = max(row["impact_score"], impact_score)
                conn.execute(
                    "UPDATE bottleneck_fingerprints "
                    "SET occurrence_count = ?, impact_score = ?, last_seen = ? "
                    "WHERE fingerprint_id = ?",
                    (count, new_impact, now, fp_id),
                )
                first_seen = row["first_seen"]
            else:
                count = 1
                first_seen = now
                conn.execute(
                    "INSERT INTO bottleneck_fingerprints "
                    "(fingerprint_id, category, impact_score, occurrence_count, description, "
                    " mitigation, first_seen, last_seen, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        fp_id,
                        cat.value,
                        impact_score,
                        1,
                        description,
                        mitigation,
                        now,
                        now,
                        json.dumps(metadata or {}),
                    ),
                )
            conn.commit()

        return BottleneckFingerprint(
            fingerprint_id=fp_id,
            category=cat,
            impact_score=impact_score,
            occurrence_count=count,
            description=description,
            mitigation=mitigation,
            first_seen=first_seen,
            last_seen=now,
            metadata=metadata or {},
        )

    def list_top_bottlenecks(self, limit: int = 10) -> list[BottleneckFingerprint]:
        """List top bottleneck fingerprints sorted by impact score and frequency."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM bottleneck_fingerprints "
                "ORDER BY (impact_score * occurrence_count) DESC LIMIT ?",
                (limit,),
            ).fetchall()

            return [
                BottleneckFingerprint(
                    fingerprint_id=r["fingerprint_id"],
                    category=BottleneckCategory(r["category"]),
                    impact_score=r["impact_score"],
                    occurrence_count=r["occurrence_count"],
                    description=r["description"],
                    mitigation=r["mitigation"],
                    first_seen=r["first_seen"],
                    last_seen=r["last_seen"],
                    metadata=json.loads(r["metadata_json"]),
                )
                for r in rows
            ]
