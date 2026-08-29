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
from dataclasses import dataclass
import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import db, paths
from .errors import BrainError, MigrationError

_MAX_TEXT_CHARS = 512
_MAX_REFERENCE_CHARS = 256
_MAX_EVIDENCE_REFS = 64


def _bounded_text(value: object, field_name: str, limit: int = _MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise BrainError(f"{field_name} must be a string")
    return value.strip()[:limit]


def _bounded_refs(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BrainError("evidence_refs must be a list")
    refs: list[str] = []
    for ref in value[:_MAX_EVIDENCE_REFS]:
        refs.append(_bounded_text(ref, "evidence reference", _MAX_REFERENCE_CHARS))
    return refs


def _canonical_json(value: object, field_name: str) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BrainError(f"malformed {field_name}") from exc


def _legacy_sidecar_has_rows(path: Path) -> bool:
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            return any(
                conn.execute(f"SELECT 1 FROM [{table[0]}] LIMIT 1").fetchone() is not None
                for table in tables
            )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise MigrationError(
            f"Cannot inspect legacy fingerprints sidecar {path}: {exc}"
        ) from exc


def _retire_legacy_sidecars(home: Path) -> None:
    directory = home / "state" / "fingerprints"
    sidecars = sorted(directory.glob("*.sqlite")) if directory.is_dir() else []
    if any(_legacy_sidecar_has_rows(path) for path in sidecars):
        raise MigrationError(
            "Refusing to discard non-empty legacy fingerprints sidecar; migrate it explicitly"
        )
    for path in sidecars:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


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
        _retire_legacy_sidecars(self.home)
        db.migrate(paths.db_path(self.home))

    def record_bottleneck(
        self,
        category: BottleneckCategory | str,
        description: str,
        mitigation: str,
        impact_score: float = 1.0,
        metadata: dict[str, Any] | None = None,
        *,
        signal_key: str | None = None,
        scope_id: str = "",
        evidence_refs: list[str] | None = None,
    ) -> BottleneckFingerprint:
        """Record or increment a bottleneck fingerprint."""
        cat = (
            category
            if isinstance(category, BottleneckCategory)
            else BottleneckCategory(str(category).upper())
        )
        if isinstance(impact_score, bool) or not isinstance(impact_score, (int, float)):
            raise BrainError("impact_score must be a real number")
        import math

        if not math.isfinite(float(impact_score)):
            raise BrainError("impact_score must be finite")
        if not 0.0 <= float(impact_score) <= 10.0:
            raise BrainError("impact_score must be within 0..10")
        description = _bounded_text(description, "description")
        mitigation = _bounded_text(mitigation, "mitigation")
        scope_id = _bounded_text(scope_id, "scope_id", _MAX_REFERENCE_CHARS)
        signal = _bounded_text(signal_key or " ".join(description.lower().split()), "signal_key")
        refs = _bounded_refs(evidence_refs)
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise BrainError("metadata must be a JSON object")
        metadata_json = _canonical_json(metadata, "metadata")
        refs_json = _canonical_json(refs, "evidence_refs")
        fp_id = f"fp-{hashlib.sha256(f'{cat.value}:{signal}:{scope_id}'.encode()).hexdigest()[:12]}"
        now = datetime.now(UTC).isoformat()

        conn = db.connect(paths.db_path(self.home))
        try:
            row = conn.execute(
                "SELECT * FROM bottleneck_fingerprints WHERE fingerprint_id = ?",
                (fp_id,),
            ).fetchone()
            if row:
                count = row["occurrence_count"] + 1
                new_impact = max(row["impact_score"], float(impact_score))
                previous_refs = json.loads(row["evidence_refs_json"])
                merged_refs = _bounded_refs(previous_refs + refs)
                conn.execute(
                    "UPDATE bottleneck_fingerprints "
                    "SET occurrence_count = ?, impact_score = ?, last_seen = ?, "
                    "metadata_json = ?, evidence_refs_json = ? WHERE fingerprint_id = ?",
                    (count, new_impact, now, metadata_json, _canonical_json(merged_refs, "evidence_refs"), fp_id),
                )
                first_seen = row["first_seen"]
            else:
                count = 1
                first_seen = now
                new_impact = float(impact_score)
                conn.execute(
                    "INSERT INTO bottleneck_fingerprints "
                    "(fingerprint_id, category, signal_key, scope_id, impact_score, "
                    "occurrence_count, description, mitigation, first_seen, last_seen, "
                    "evidence_refs_json, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        fp_id,
                        cat.value,
                        signal,
                        scope_id,
                        new_impact,
                        1,
                        description,
                        mitigation,
                        now,
                        now,
                        refs_json,
                        metadata_json,
                    ),
                )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not record bottleneck: {exc}") from exc
        finally:
            conn.close()

        return BottleneckFingerprint(
            fingerprint_id=fp_id,
            category=cat,
            impact_score=new_impact,
            occurrence_count=count,
            description=description,
            mitigation=mitigation,
            first_seen=first_seen,
            last_seen=now,
            metadata=metadata,
        )

    def list_top_bottlenecks(self, limit: int = 10) -> list[BottleneckFingerprint]:
        """List top bottleneck fingerprints sorted by impact score and frequency."""
        conn = db.connect(paths.db_path(self.home))
        try:
            rows = conn.execute(
                "SELECT * FROM bottleneck_fingerprints "
                "ORDER BY (impact_score * occurrence_count) DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                BottleneckFingerprint(
                    fingerprint_id=row["fingerprint_id"],
                    category=BottleneckCategory(row["category"]),
                    impact_score=row["impact_score"],
                    occurrence_count=row["occurrence_count"],
                    description=row["description"],
                    mitigation=row["mitigation"],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    metadata=json.loads(row["metadata_json"]),
                )
                for row in rows
            ]
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not list bottlenecks: {exc}") from exc
        finally:
            conn.close()
