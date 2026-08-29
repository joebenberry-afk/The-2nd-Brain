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
_MAX_METADATA_CHARS = 4096
_EVIDENCE_FIELDS = frozenset({"record_hash", "telemetry_ref", "ts", "input_bytes", "output_bytes"})


def _bounded_text(value: object, field_name: str, limit: int = _MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise BrainError(f"{field_name} must be a string")
    return value.strip()[:limit]


def _bounded_refs(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BrainError("evidence_refs must be a list")
    refs: list[dict[str, Any]] = []
    for raw_ref in value:
        if isinstance(raw_ref, str):
            raw_ref = {"record_hash": raw_ref}
        if not isinstance(raw_ref, dict):
            raise BrainError("evidence reference must be a JSON object")
        if set(raw_ref) - _EVIDENCE_FIELDS:
            raise BrainError("evidence reference contains unsupported fields")
        record_hash = _bounded_text(raw_ref.get("record_hash"), "record_hash", 128)
        if not record_hash:
            raise BrainError("record_hash must be non-empty")
        ref: dict[str, Any] = {"record_hash": record_hash}
        for field in ("telemetry_ref", "ts"):
            if field in raw_ref:
                ref[field] = _bounded_text(raw_ref[field], field, _MAX_REFERENCE_CHARS)
        for field in ("input_bytes", "output_bytes"):
            if field in raw_ref:
                number = raw_ref[field]
                if isinstance(number, bool) or not isinstance(number, int) or number < 0 or number > 1_000_000_000:
                    raise BrainError(f"{field} must be a bounded non-negative integer")
                ref[field] = number
        refs.append(ref)
    by_hash: dict[str, dict[str, Any]] = {}
    for ref in refs:
        by_hash.pop(ref["record_hash"], None)
        by_hash[ref["record_hash"]] = ref
    return list(by_hash.values())[-_MAX_EVIDENCE_REFS:]


def _merge_refs(previous: list[dict[str, Any]], latest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for ref in [*previous, *latest]:
        merged.pop(ref["record_hash"], None)
        merged[ref["record_hash"]] = ref
    return list(merged.values())[-_MAX_EVIDENCE_REFS:]


def _canonical_json(value: object, field_name: str) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BrainError(f"malformed {field_name}") from exc
    if field_name == "metadata" and len(encoded) > _MAX_METADATA_CHARS:
        raise BrainError("metadata exceeds bound")
    return encoded


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
    scope_id: str = ""
    signal_key: str = ""
    evidence_refs: list[dict[str, Any]] | None = None

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
            "scope_id": self.scope_id,
            "signal_key": self.signal_key,
            "evidence_refs": list(self.evidence_refs or []),
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
        evidence_refs: list[dict[str, Any]] | list[str] | None = None,
    ) -> BottleneckFingerprint:
        """Record or increment a bottleneck fingerprint."""
        try:
            cat = (
                category
                if isinstance(category, BottleneckCategory)
                else BottleneckCategory(str(category).strip().upper())
            )
        except (TypeError, ValueError) as exc:
            raise BrainError("category must be non-empty and recognized") from exc
        if isinstance(impact_score, bool) or not isinstance(impact_score, (int, float)):
            raise BrainError("impact_score must be a real number")
        import math

        score = float(impact_score)
        if not math.isfinite(score):
            raise BrainError("impact_score must be finite")
        if not 0.0 <= score <= 10.0:
            raise BrainError("impact_score must be within 0..10")
        description = _bounded_text(description, "description")
        mitigation = _bounded_text(mitigation, "mitigation")
        scope_id = _bounded_text(scope_id, "scope_id", _MAX_REFERENCE_CHARS)
        normalized_description = " ".join(description.lower().split())
        if not normalized_description:
            raise BrainError("description must be non-empty")
        supplied_signal = signal_key if signal_key is not None else normalized_description
        normalized_signal = " ".join(str(supplied_signal).lower().split())
        signal = _bounded_text(f"{cat.value}:{normalized_signal}", "signal_key")
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
                "SELECT * FROM bottleneck_fingerprints "
                "WHERE category = ? AND signal_key = ? AND scope_id = ?",
                (cat.value, signal, scope_id),
            ).fetchone()
            if row:
                previous_count = row["occurrence_count"]
                if isinstance(previous_count, bool) or not isinstance(previous_count, int) or previous_count < 0:
                    raise BrainError("stored occurrence_count is invalid")
                count = previous_count + 1
                previous_refs = _bounded_refs(json.loads(row["evidence_refs_json"]))
                merged_refs = _merge_refs(previous_refs, refs)
                new_impact = max(float(row["impact_score"]), score)
                conn.execute(
                    "UPDATE bottleneck_fingerprints "
                    "SET occurrence_count = ?, impact_score = ?, last_seen = ?, "
                    "evidence_refs_json = ? WHERE fingerprint_id = ?",
                    (count, new_impact, now, _canonical_json(merged_refs, "evidence_refs"), row["fingerprint_id"]),
                )
                stored = {
                    "fingerprint_id": row["fingerprint_id"],
                    "category": BottleneckCategory(row["category"]),
                    "impact_score": new_impact,
                    "occurrence_count": count,
                    "description": row["description"],
                    "mitigation": row["mitigation"],
                    "first_seen": row["first_seen"],
                    "last_seen": now,
                    "metadata": json.loads(row["metadata_json"]),
                    "scope_id": row["scope_id"],
                    "signal_key": row["signal_key"],
                    "evidence_refs": merged_refs,
                }
            else:
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
                        score,
                        1,
                        description,
                        mitigation,
                        now,
                        now,
                        refs_json,
                        metadata_json,
                    ),
                )
                stored = {
                    "fingerprint_id": fp_id,
                    "category": cat,
                    "impact_score": score,
                    "occurrence_count": 1,
                    "description": description,
                    "mitigation": mitigation,
                    "first_seen": now,
                    "last_seen": now,
                    "metadata": metadata,
                    "scope_id": scope_id,
                    "signal_key": signal,
                    "evidence_refs": refs,
                }
            conn.commit()
        except BrainError:
            conn.rollback()
            raise
        except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
            conn.rollback()
            raise BrainError(f"Could not record bottleneck: {exc}") from exc
        finally:
            conn.close()

        return BottleneckFingerprint(**stored)

    def record_alert(
        self,
        alert: Any,
        *,
        scope_id: str,
        evidence_refs: list[dict[str, Any]] | list[str] | None,
    ) -> BottleneckFingerprint:
        """Project an existing Radar alert into a fixed, privacy-safe fingerprint."""
        pattern = getattr(getattr(alert, "pattern", None), "value", getattr(alert, "pattern", ""))
        mapping = {
            "REPEATED_READ": BottleneckCategory.TOOL_CHAIN_THRASH,
            "TOOL_ERROR_LOOP": BottleneckCategory.TOOL_CHAIN_THRASH,
            "SEARCH_THRASH": BottleneckCategory.RETRIEVAL_OVERLOAD,
            "REDUNDANT_TEST_RUN": BottleneckCategory.TOOL_CHAIN_THRASH,
            "CONTEXT_CHURN": BottleneckCategory.PROMPT_BLOAT,
        }
        descriptions = {
            "REPEATED_READ": "Repeated reads of identical content",
            "TOOL_ERROR_LOOP": "Repeated failures from the same tool",
            "SEARCH_THRASH": "Repeated searches with no candidates",
            "REDUNDANT_TEST_RUN": "Repeated test runs without changes",
            "CONTEXT_CHURN": "Repeated context replacement and rereading",
        }
        category = mapping.get(str(pattern))
        description = descriptions.get(str(pattern))
        if category is None or description is None:
            raise BrainError("unsupported Radar alert pattern")
        severity_scores = {"INFO": 2.0, "WARNING": 5.0, "CRITICAL": 8.0}
        score = severity_scores.get(str(getattr(alert, "severity", "")).upper(), 1.0)
        return self.record_bottleneck(
            category,
            description,
            "Review the existing Radar recommendation before repeating the pattern",
            impact_score=score,
            metadata={"alert_count": 1},
            scope_id=scope_id,
            evidence_refs=evidence_refs,
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
                    scope_id=row["scope_id"],
                    signal_key=row["signal_key"],
                    evidence_refs=_bounded_refs(json.loads(row["evidence_refs_json"])),
                )
                for row in rows
            ]
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not list bottlenecks: {exc}") from exc
        finally:
            conn.close()
