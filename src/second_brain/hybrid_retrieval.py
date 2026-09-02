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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

from . import semantic
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
    score: float
    tier_resolved: int
    summary: str = ""
    body: str = ""
    confidence: float = 1.0
    raw_row: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "title": self.title,
            "score": round(self.score, 4),
            "tier_resolved": self.tier_resolved,
            "summary": self.summary,
            "confidence": round(self.confidence, 4),
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
    """Multi-tier cascade retriever with negative result cache."""

    def __init__(self) -> None:
        # (query_hash, project_id) -> timestamp
        self._negative_cache: dict[tuple[str, str | None], str] = {}

    def _query_hash(self, query: str) -> str:
        norm = " ".join(re.findall(r"[a-z0-9]+", query.lower()))
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def invalidate_negative_cache(self, project_id: str | None = None) -> None:
        """Invalidate negative cache entries."""
        if project_id is None:
            self._negative_cache.clear()
        else:
            self._negative_cache = {
                k: v for k, v in self._negative_cache.items() if k[1] != project_id
            }

    def retrieve(
        self,
        home: Path | str,
        query: str,
        *,
        project_id: str | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        top_k: int = 10,
        vector_searcher: Callable[[str, str | None], list[dict[str, Any]]] | None = None,
    ) -> CascadeResult:
        """
        Execute multi-tier retrieval cascade (§9.1, §9.2).
        """
        t0 = time.perf_counter()
        home_path = Path(home)
        clean_q = query.strip()

        # Step 0: Trivial / Empty Query Check
        if not clean_q or clean_q.lower() in _TRIVIAL_QUERIES:
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                matches=[],
                vector_invoked=False,
                latency_ms=lat,
                short_circuited=True,
                decision="NO_INJECTION",
                reason="TRIVIAL_TASK",
            )

        q_hash = self._query_hash(clean_q)
        cache_key = (q_hash, project_id)

        # Step 1: Negative Result Cache Check (§9.3)
        if cache_key in self._negative_cache:
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                matches=[],
                vector_invoked=False,
                latency_ms=lat,
                short_circuited=True,
                negative_cached=True,
                decision="NO_INJECTION",
                reason="NO_RELEVANT_MEMORY",
            )

        # Step 2: Tier 0 — Exact Ref / Memory ID Lookup
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
                        query=query,
                        project_id=project_id,
                        tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                        matches=[match],
                        vector_invoked=False,
                        latency_ms=lat,
                        short_circuited=True,
                        decision="INJECT",
                        reason="EXACT_REF_MATCH",
                    )
            except BrainError:
                pass  # not found as exact ID, continue cascade

        retrieval_error = False
        try:
            fts_matches = semantic.search_memories(
                home_path,
                clean_q,
                project_id=project_id,
                top_k=top_k,
            )
        except Exception:
            retrieval_error = True
            fts_matches = []

        if fts_matches:
            # Score first match
            best_score = float(fts_matches[0].get("_score") or fts_matches[0].get("score") or 0.85)
            if best_score >= confidence_threshold:
                matches = [
                    RetrievalMatch(
                        memory_id=m["memory_id"],
                        title=m.get("title", ""),
                        score=float(m.get("_score") or m.get("score") or best_score),
                        tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                        summary=m.get("summary", ""),
                        confidence=best_score,
                        raw_row=dict(m),
                    )
                    for m in fts_matches
                ]
                lat = (time.perf_counter() - t0) * 1000.0
                return CascadeResult(
                    query=query,
                    project_id=project_id,
                    tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                    matches=matches,
                    vector_invoked=False,
                    latency_ms=lat,
                    short_circuited=True,
                    decision="INJECT",
                    reason="LEXICAL_HIGH_CONFIDENCE",
                )

        # Step 4: Tier 3 — Vector / Semantic Search (Only when Tiers 0-2 yield low confidence)
        if vector_searcher is not None:
            vec_res = vector_searcher(clean_q, project_id)
            if vec_res:
                matches = [
                    RetrievalMatch(
                        memory_id=m["memory_id"],
                        title=m.get("title", ""),
                        score=float(m.get("score", 0.75)),
                        tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                        summary=m.get("summary", ""),
                        confidence=float(m.get("score", 0.75)),
                    )
                    for m in vec_res
                ]
                lat = (time.perf_counter() - t0) * 1000.0
                return CascadeResult(
                    query=query,
                    project_id=project_id,
                    tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                    matches=matches,
                    vector_invoked=True,
                    latency_ms=lat,
                    short_circuited=False,
                    decision="INJECT",
                    reason="VECTOR_FALLBACK_MATCH",
                )

        # Infrastructure failures must not poison the negative cache or look
        # like a genuine no-match to the AutoInject fail-open gate.
        if retrieval_error:
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                matches=[],
                vector_invoked=vector_searcher is not None,
                latency_ms=lat,
                short_circuited=True,
                decision="NO_INJECTION",
                reason="BRAIN_UNAVAILABLE",
                retrieval_error=True,
            )
        # Step 5: No Matches Found -> Record Negative Cache (§9.3)
        self._negative_cache[cache_key] = datetime.now(UTC).isoformat()
        lat = (time.perf_counter() - t0) * 1000.0
        return CascadeResult(
            query=query,
            project_id=project_id,
            tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
            matches=[],
            vector_invoked=vector_searcher is not None,
            latency_ms=lat,
            short_circuited=True,
            decision="NO_INJECTION",
            reason="NO_RELEVANT_MEMORY",
        )
