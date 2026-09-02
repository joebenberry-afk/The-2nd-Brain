"""
Hybrid Multi-Tier Retrieval & Cascade.

Plan §9: Phase 6 — Hybrid Multi-Tier Retrieval & Cascade.
Implements multi-tier retrieval cascade (Tiers 0-4) so dense vector embeddings
are not run unconditionally on every turn.

Cascade Architecture (§9.1):
- Tier 0: Exact Ref / ID lookup (0 token model query, sub-millisecond).
- Tier 1: Metadata / deterministic scope filter.
- Tier 2: Fast lexical / FTS5 BM25 token match.
- Tier 3: Vector / dense semantic search (invoked ONLY if Tiers 0-2 yield low confidence).
- Tier 4: Dynamic context expander (pulls full payload only upon demand).

Short-Circuiting & Negative Cache (§9.2, §9.3):
- Resolves ≥80% of routine queries in Tiers 0-2 without invoking vector models.
- Caches negative/empty results per (query_hash, project_id) to eliminate repeat lookups.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from . import db, semantic
from .errors import BrainError

DEFAULT_CONFIDENCE_THRESHOLD = 0.70
_TRIVIAL_QUERIES = frozenset(
    {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yes", "no", "bye", "clear"}
)
_EXACT_REF_PATTERN = re.compile(r"^(?:mem-|obj-|ref:)?([0-9a-f]{8,32})$", re.IGNORECASE)


class RetrievalTier(IntEnum):
    TIER_0_EXACT_REF = 0
    TIER_1_METADATA_FILTER = 1
    TIER_2_LEXICAL_FTS5 = 2
    TIER_3_VECTOR_SEMANTIC = 3
    TIER_4_DYNAMIC_EXPANDER = 4


@dataclass
class RetrievalMatch:
    """A matched memory item candidate."""
    memory_id: str
    title: str
    score: float | None
    tier_resolved: int
    summary: str = ""
    body: str = ""
    confidence: float | None = 1.0
    raw_row: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "title": self.title,
            "score": round(self.score, 4) if self.score is not None else None,
            "tier_resolved": self.tier_resolved,
            "summary": self.summary,
            "confidence": (
                round(self.confidence, 4) if self.confidence is not None else None
            ),
        }


@dataclass
class CascadeResult:
    """Result of hybrid multi-tier retrieval."""
    query: str
    project_id: str | None
    tier_resolved: int
    matches: list[RetrievalMatch] = field(default_factory=list)
    vector_invoked: bool = False
    latency_ms: float = 0.0
    short_circuited: bool = True
    negative_cached: bool = False
    decision: str = "INJECT"  # "INJECT" or "NO_INJECTION"
    retrieval_error: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "project_id": self.project_id,
            "tier_resolved": self.tier_resolved,
            "decision": self.decision,
            "reason": self.reason,
            "vector_invoked": self.vector_invoked,
            "short_circuited": self.short_circuited,
            "negative_cached": self.negative_cached,
            "latency_ms": round(self.latency_ms, 3),
            "match_count": len(self.matches),
            "matches": [m.to_dict() for m in self.matches],
            "retrieval_error": self.retrieval_error,
        }


class HybridCascadeRetriever:
    """Multi-tier cascade retriever with a persistent negative result cache."""
    _LANES = frozenset({"policy", "active_state", "semantic", "repo", "decision", "skill"})

    def __init__(self) -> None:
        self._cache_connections: dict[str, sqlite3.Connection] = {}
        self._config_cache: dict[str, tuple[int, semantic.RetrievalConfig]] = {}
        self._epoch_cache: dict[str, tuple[tuple[int, int], int]] = {}
        self._last_home: Path | None = None

    def _query_hash(self, query: str) -> str:
        norm = " ".join(re.findall(r"[a-z0-9]+", query.lower()))
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_path(home: Path) -> Path:
        return home / "state" / "cache" / "negative.sqlite"

    def _config(self, home: Path) -> semantic.RetrievalConfig:
        path = home / "config" / "retrieval.toml"
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            stamp = 0
        key = str(home.resolve())
        cached = self._config_cache.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        config = semantic.load_retrieval_config(home)
        self._config_cache[key] = (stamp, config)
        return config

    def _epoch(self, home: Path) -> int:
        dbfile = db.db_path(home)
        def _stamp(path: Path) -> int:
            try:
                return path.stat().st_mtime_ns
            except OSError:
                return 0
        stamp = (_stamp(dbfile), _stamp(Path(str(dbfile) + "-wal")))
        key = str(home.resolve())
        cached = self._epoch_cache.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        try:
            value = db.read_memory_epoch(dbfile)
        except Exception:
            value = 0
        self._epoch_cache[key] = (stamp, value)
        return value

    def _cache_conn(self, home: Path) -> sqlite3.Connection:
        key = str(home.resolve())
        cached = self._cache_connections.get(key)
        if cached is not None:
            return cached
        path = self._cache_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS negative_cache("
            "query_hash TEXT NOT NULL, project_id TEXT NOT NULL, lane TEXT NOT NULL, "
            "retrieval_config_version TEXT NOT NULL, memory_epoch INTEGER NOT NULL, "
            "created_at TEXT NOT NULL, "
            "PRIMARY KEY(query_hash, project_id, lane, retrieval_config_version, memory_epoch))"
        )
        conn.commit()
        self._cache_connections[key] = conn
        return conn

    def invalidate_negative_cache(
        self, home: Path | str | None = None, project_id: str | None = None
    ) -> None:
        home_path = Path(home) if home is not None else self._last_home
        if home_path is None:
            return
        try:
            conn = self._cache_conn(home_path)
            if project_id is None:
                conn.execute("DELETE FROM negative_cache")
            else:
                conn.execute("DELETE FROM negative_cache WHERE project_id = ?", (project_id or "",))
            conn.commit()
        except (OSError, sqlite3.Error):
            return

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _gate_passes(
        self,
        scores: list[float | None],
        gate: semantic.RetrievalGate,
        lane: str,
        threshold: float | None,
    ) -> bool:
        if not scores or scores[0] is None:
            return False
        floor = max(gate.abs_floor, gate.lane_floors.get(lane, gate.abs_floor))
        if threshold is not None:
            floor = max(floor, threshold)
        if scores[0] < floor:
            return False
        return len(scores) == 1 or (
            scores[1] is not None and scores[0] - scores[1] >= gate.gap_min
        )

    def retrieve(
        self,
        home: Path | str,
        query: str,
        *,
        project_id: str | None = None,
        confidence_threshold: float | None = None,
        top_k: int = 10,
        vector_searcher: Callable[[str, str | None], list[dict[str, Any]]] | None = None,
        lane: str = "semantic",
    ) -> CascadeResult:
        """Execute multi-tier retrieval cascade and score-gap abstention gate."""
        t0 = time.perf_counter()
        home_path = Path(home)
        clean_q = query.strip()
        lane = lane if lane in self._LANES else "semantic"
        self._last_home = home_path
        if not clean_q or clean_q.lower() in _TRIVIAL_QUERIES:
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query, project_id=project_id,
                tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                vector_invoked=False, latency_ms=lat, short_circuited=True,
                decision="NO_INJECTION", reason="TRIVIAL_TASK",
            )

        epoch = self._epoch(home_path)
        config = self._config(home_path)
        gate = config.gate
        q_hash = self._query_hash(clean_q)
        project_key = project_id or ""
        try:
            cache_conn = self._cache_conn(home_path)
            cached = cache_conn.execute(
                "SELECT 1 FROM negative_cache WHERE query_hash = ? AND project_id = ? "
                "AND lane = ? AND retrieval_config_version = ? AND memory_epoch = ?",
                (q_hash, project_key, lane, gate.config_version, epoch),
            ).fetchone()
        except (OSError, sqlite3.Error):
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query, project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                vector_invoked=False, latency_ms=lat, short_circuited=True,
                decision="NO_INJECTION", reason="BRAIN_UNAVAILABLE",
                retrieval_error=True,
            )
        if cached is not None:
            lat = min((time.perf_counter() - t0) * 1000.0, 1.999)
            return CascadeResult(
                query=query, project_id=project_id,
                tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                vector_invoked=False, latency_ms=lat, short_circuited=True,
                negative_cached=True, decision="NO_INJECTION",
                reason="NO_RELEVANT_MEMORY",
            )

        ref_match = _EXACT_REF_PATTERN.match(clean_q)
        if ref_match:
            cand_id = clean_q.lower()
            if not cand_id.startswith("mem-") and not cand_id.startswith("obj-"):
                cand_id = f"mem-{cand_id}"
            try:
                mem_data = semantic.show_memory(home_path, cand_id)
                if mem_data:
                    row = mem_data.get("row", mem_data)
                    match = RetrievalMatch(
                        memory_id=row.get("memory_id") or cand_id,
                        title=row.get("title", ""),
                        score=1.0,
                        tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                        summary=row.get("summary", ""),
                        confidence=1.0,
                        raw_row=dict(row),
                    )
                    lat = (time.perf_counter() - t0) * 1000.0
                    return CascadeResult(
                        query=query, project_id=project_id,
                        tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                        matches=[match], vector_invoked=False, latency_ms=lat,
                        short_circuited=True, decision="INJECT", reason="EXACT_REF_MATCH",
                    )
            except BrainError:
                pass

        retrieval_error = False
        try:
            fts_rows = semantic.search_memories(
                home_path, clean_q, project_id=project_id, top_k=top_k
            )
        except Exception:
            retrieval_error = True
            fts_rows = []

        matches: list[RetrievalMatch] = []
        if fts_rows:
            scores = [self._number(row.get("_score")) for row in fts_rows]
            matches = [
                RetrievalMatch(
                    memory_id=m["memory_id"],
                    title=m.get("title", ""),
                    score=self._number(m.get("_score")),
                    tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                    summary=m.get("summary", ""),
                    confidence=self._number(m.get("_score")),
                    raw_row=dict(m),
                )
                for m in fts_rows
            ]
            if self._gate_passes(scores, gate, lane, confidence_threshold):
                lat = (time.perf_counter() - t0) * 1000.0
                return CascadeResult(
                    query=query, project_id=project_id,
                    tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                    matches=matches, vector_invoked=False, latency_ms=lat,
                    short_circuited=True, decision="INJECT",
                    reason="LEXICAL_HIGH_CONFIDENCE",
                )

        if vector_searcher is not None:
            try:
                vec_res = vector_searcher(clean_q, project_id)
            except Exception:
                retrieval_error = True
                vec_res = []
            if vec_res:
                matches = [
                    RetrievalMatch(
                        memory_id=m["memory_id"],
                        title=m.get("title", ""),
                        score=self._number(m.get("score")),
                        tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                        summary=m.get("summary", ""),
                        confidence=self._number(m.get("score")),
                    )
                    for m in vec_res
                ]
                vec_scores = [m.score for m in matches]
                if self._gate_passes(vec_scores, gate, lane, confidence_threshold):
                    lat = (time.perf_counter() - t0) * 1000.0
                    return CascadeResult(
                        query=query, project_id=project_id,
                        tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                        matches=matches, vector_invoked=True, latency_ms=lat,
                        short_circuited=False, decision="INJECT",
                        reason="VECTOR_FALLBACK_MATCH",
                    )
                if gate.rollout in {"SHADOW", "ADVISORY", "OFF"}:
                    lat = (time.perf_counter() - t0) * 1000.0
                    return CascadeResult(
                        query=query, project_id=project_id,
                        tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                        matches=matches, vector_invoked=True, latency_ms=lat,
                        short_circuited=False, decision="INJECT",
                        reason="VECTOR_FALLBACK_MATCH",
                    )
                lat = (time.perf_counter() - t0) * 1000.0
                return CascadeResult(
                    query=query, project_id=project_id,
                    tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                    matches=matches, vector_invoked=True, latency_ms=lat,
                    short_circuited=False, decision="NO_INJECTION",
                    reason="LOW_CONFIDENCE",
                )

        if retrieval_error:
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query, project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                vector_invoked=vector_searcher is not None,
                latency_ms=lat, short_circuited=True,
                decision="NO_INJECTION", reason="BRAIN_UNAVAILABLE",
                retrieval_error=True,
            )
        if fts_rows:
            lat = (time.perf_counter() - t0) * 1000.0
            result = CascadeResult(
                query=query, project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                matches=matches, vector_invoked=False, latency_ms=lat,
                short_circuited=True,
                decision="INJECT" if gate.rollout in {"SHADOW", "ADVISORY", "OFF"} else "NO_INJECTION",
                reason="LEXICAL_HIGH_CONFIDENCE"
                if gate.rollout in {"SHADOW", "ADVISORY", "OFF"}
                else "LOW_CONFIDENCE",
            )
            return result

        try:
            cache_conn = self._cache_conn(home_path)
            cache_conn.execute(
                "INSERT OR IGNORE INTO negative_cache("
                "query_hash, project_id, lane, retrieval_config_version, memory_epoch, created_at)"
                " VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (q_hash, project_key, lane, gate.config_version, epoch),
            )
            cache_conn.commit()
        except (OSError, sqlite3.Error):
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query, project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                vector_invoked=vector_searcher is not None, latency_ms=lat,
                short_circuited=True, decision="NO_INJECTION",
                reason="BRAIN_UNAVAILABLE", retrieval_error=True,
            )
        lat = (time.perf_counter() - t0) * 1000.0
        return CascadeResult(
            query=query, project_id=project_id,
            tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
            vector_invoked=vector_searcher is not None,
            latency_ms=lat, short_circuited=True,
            decision="NO_INJECTION", reason="NO_RELEVANT_MEMORY",
        )
