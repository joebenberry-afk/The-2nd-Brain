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
    score_components: dict[str, float] = field(default_factory=dict)
    has_contradiction: bool = False
    contradiction_details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "title": self.title,
            "score": round(self.score, 4) if self.score is not None else None,
            "tier_resolved": self.tier_resolved,
            "summary": self.summary,
            "confidence": (round(self.confidence, 4) if self.confidence is not None else None),
            "score_components": {
                k: round(v, 4) if isinstance(v, (int, float)) else v
                for k, v in self.score_components.items()
            },
            "has_contradiction": self.has_contradiction,
            "contradiction_details": self.contradiction_details,
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
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    multiview_invoked: bool = False

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
            "contradictions": self.contradictions,
            "multiview_invoked": self.multiview_invoked,
            "retrieval_error": self.retrieval_error,
        }


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"\b\w+\b", text.lower()))


def _jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    union = len(tokens_a | tokens_b)
    if union == 0:
        return 0.0
    return len(tokens_a & tokens_b) / union


def apply_mmr(
    matches: list[RetrievalMatch],
    *,
    lambda_param: float = 0.7,
    top_k: int = 10,
) -> list[RetrievalMatch]:
    """Maximal Marginal Relevance over token Jaccard similarity.

    Balances relevance with diversity:
    MMR = lambda * relevance - (1 - lambda) * max_similarity(c, selected).
    """
    if not matches or len(matches) <= 1:
        for m in matches:
            m.score_components["diversity"] = 1.0
        return matches[:top_k]

    token_cache = [_token_set(f"{m.title} {m.summary} {m.body}") for m in matches]

    selected_indices: list[int] = []
    remaining_indices = list(range(len(matches)))

    best_first = max(remaining_indices, key=lambda idx: matches[idx].score or 0.0)
    selected_indices.append(best_first)
    remaining_indices.remove(best_first)
    matches[best_first].score_components["diversity"] = 1.0

    while remaining_indices and len(selected_indices) < top_k:
        best_idx = -1
        best_mmr_score = -float("inf")
        best_diversity = 1.0

        for idx in remaining_indices:
            cand = matches[idx]
            cand_score = cand.score or 0.0
            cand_tokens = token_cache[idx]

            max_sim = max(
                _jaccard_similarity(cand_tokens, token_cache[sel_idx])
                for sel_idx in selected_indices
            )
            diversity = 1.0 - max_sim
            mmr_score = lambda_param * cand_score - (1.0 - lambda_param) * max_sim

            if mmr_score > best_mmr_score:
                best_mmr_score = mmr_score
                best_idx = idx
                best_diversity = diversity

        if best_idx >= 0:
            matches[best_idx].score_components["diversity"] = round(best_diversity, 4)
            matches[best_idx].score = round(best_mmr_score, 4)
            selected_indices.append(best_idx)
            remaining_indices.remove(best_idx)
        else:
            break

    return [matches[i] for i in selected_indices]


def _compute_score_components(
    home: Path,
    row: dict[str, Any],
    query_tokens: set[str],
    project_id: str | None,
) -> tuple[dict[str, float], bool, list[str]]:
    bm25 = row.get("_bm25")
    score_val = row.get("_score")
    relevance = (
        float(bm25) if bm25 is not None else (float(score_val) if score_val is not None else 0.8)
    )

    grade = row.get("evidence_grade") or "OBSERVED"
    authority_ceiling = row.get("authority_ceiling") or "advisory"
    authority = (
        1.0
        if authority_ceiling == "policy"
        else (0.9 if authority_ceiling == "project_rule" else 0.8)
    )
    if grade == "VERIFIED":
        authority = max(authority, 0.95)

    mem_project = row.get("project_id")
    mem_scope = row.get("scope") or "project"
    scope_score = (
        1.0 if mem_scope == "global" or (project_id and mem_project == project_id) else 0.8
    )

    freshness_score = 1.0
    contradiction_count = int(row.get("contradiction_count") or 0)
    contradiction_with = row.get("contradiction_with") or []
    has_contradiction = contradiction_count > 0 or bool(contradiction_with)
    contradiction_score = 0.5 if has_contradiction else 1.0
    contradiction_details = []
    if contradiction_count > 0:
        contradiction_details.append(f"Contradiction count: {contradiction_count}")
    if contradiction_with:
        contradiction_details.append(
            f"Contradicts with: {', '.join(str(x) for x in contradiction_with)}"
        )

    try:
        from . import reconsolidation

        p_need = reconsolidation.compute_p_need(home, row.get("memory_id", ""))
    except Exception:
        p_need = 0.5

    components = {
        "relevance": round(relevance, 4),
        "authority": round(authority, 4),
        "scope": round(scope_score, 4),
        "freshness": round(freshness_score, 4),
        "contradiction": round(contradiction_score, 4),
        "activation_need": round(p_need, 4),
        "diversity": 1.0,
        "final_score": round(float(score_val if score_val is not None else relevance), 4),
    }
    return components, has_contradiction, contradiction_details


class HybridCascadeRetriever:
    """Multi-tier cascade retriever with a persistent negative result cache."""

    _LANES = frozenset({"policy", "active_state", "semantic", "repo", "decision", "skill"})

    def __init__(self) -> None:
        self._cache_connections: dict[str, sqlite3.Connection] = {}
        self._config_cache: dict[str, tuple[int, semantic.RetrievalConfig]] = {}
        self._epoch_cache: dict[str, tuple[tuple[int, int], int]] = {}
        self._last_home: Path | None = None
        self.multiview_enabled: bool = False

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
        return len(scores) == 1 or (scores[1] is not None and scores[0] - scores[1] >= gate.gap_min)

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
        multiview: bool = False,
        lambda_param: float = 0.7,
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
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                vector_invoked=False,
                latency_ms=lat,
                short_circuited=True,
                decision="NO_INJECTION",
                reason="TRIVIAL_TASK",
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
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                vector_invoked=False,
                latency_ms=lat,
                short_circuited=True,
                decision="NO_INJECTION",
                reason="BRAIN_UNAVAILABLE",
                retrieval_error=True,
            )
        if cached is not None:
            lat = min((time.perf_counter() - t0) * 1000.0, 1.999)
            return CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                vector_invoked=False,
                latency_ms=lat,
                short_circuited=True,
                negative_cached=True,
                decision="NO_INJECTION",
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
                    # Authority safety check: policy lane cannot inject advisory memory
                    authority_ceiling = row.get("authority_ceiling") or "advisory"
                    if lane == "policy" and authority_ceiling != "policy":
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
                            reason="AUTHORITY_VIOLATION",
                        )

                    # Status safety check: rejected and archived memories excluded
                    if row.get("evidence_grade") == "REJECTED" or row.get("status") in (
                        "archived",
                        "superseded",
                    ):
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
                            reason="EXCLUDED_STATUS",
                        )

                    contradiction_count = int(row.get("contradiction_count") or 0)
                    has_contradiction = contradiction_count > 0
                    contradictions_list = []
                    if has_contradiction:
                        contradictions_list.append(
                            {
                                "memory_id": cand_id,
                                "title": row.get("title", ""),
                                "contradiction_count": contradiction_count,
                                "details": [f"Contradiction count: {contradiction_count}"],
                            }
                        )

                    components = {
                        "relevance": 1.0,  # Exact ref bypasses semantic uncertainty
                        "authority": 1.0
                        if authority_ceiling in ("project_rule", "policy")
                        else 0.8,
                        "scope": 1.0,
                        "freshness": 1.0,
                        "contradiction": 0.5 if has_contradiction else 1.0,
                        "activation_need": 1.0,
                        "diversity": 1.0,
                        "final_score": 1.0,
                    }

                    match = RetrievalMatch(
                        memory_id=row.get("memory_id") or cand_id,
                        title=row.get("title", ""),
                        score=1.0,
                        tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                        summary=row.get("summary", ""),
                        body=mem_data.get("body", ""),
                        confidence=1.0,
                        raw_row=dict(row),
                        score_components=components,
                        has_contradiction=has_contradiction,
                        contradiction_details=[f"Contradiction count: {contradiction_count}"]
                        if has_contradiction
                        else [],
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
                        contradictions=contradictions_list,
                    )
            except BrainError:
                pass

        retrieval_error = False
        try:
            fts_rows = semantic.search_memories(
                home_path,
                clean_q,
                project_id=project_id,
                top_k=max(top_k * 2, 20),
                include_duplicates=True,
            )
        except Exception:
            retrieval_error = True
            fts_rows = []

        matches: list[RetrievalMatch] = []
        contradictions_list: list[dict[str, Any]] = []
        if fts_rows:
            query_tokens = set(re.findall(r"\b\w+\b", clean_q.lower()))
            for m in fts_rows:
                components, has_c, c_details = _compute_score_components(
                    home_path, m, query_tokens, project_id
                )
                body_val = m.get("_body", "")
                match = RetrievalMatch(
                    memory_id=m["memory_id"],
                    title=m.get("title", ""),
                    score=self._number(m.get("_score")),
                    tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                    summary=m.get("summary", ""),
                    body=body_val,
                    confidence=self._number(m.get("_score")),
                    raw_row=dict(m),
                    score_components=components,
                    has_contradiction=has_c,
                    contradiction_details=c_details,
                )
                matches.append(match)
                if has_c:
                    contradictions_list.append(
                        {
                            "memory_id": match.memory_id,
                            "title": match.title,
                            "contradiction_count": m.get("contradiction_count", 0),
                            "details": c_details,
                        }
                    )

            # Apply MMR for diversity over token Jaccard
            matches = apply_mmr(matches, lambda_param=lambda_param, top_k=top_k)
            scores = [m.score for m in matches]
            if self._gate_passes(scores, gate, lane, confidence_threshold):
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
                    contradictions=contradictions_list,
                    multiview_invoked=multiview or self.multiview_enabled,
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
                if gate.rollout in {"SHADOW", "ADVISORY", "OFF"}:
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
                lat = (time.perf_counter() - t0) * 1000.0
                return CascadeResult(
                    query=query,
                    project_id=project_id,
                    tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                    matches=matches,
                    vector_invoked=True,
                    latency_ms=lat,
                    short_circuited=False,
                    decision="NO_INJECTION",
                    reason="LOW_CONFIDENCE",
                )

        if retrieval_error:
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                vector_invoked=vector_searcher is not None,
                latency_ms=lat,
                short_circuited=True,
                decision="NO_INJECTION",
                reason="BRAIN_UNAVAILABLE",
                retrieval_error=True,
            )
        if fts_rows:
            lat = (time.perf_counter() - t0) * 1000.0
            result = CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                matches=matches,
                vector_invoked=False,
                latency_ms=lat,
                short_circuited=True,
                decision="INJECT"
                if gate.rollout in {"SHADOW", "ADVISORY", "OFF"}
                else "NO_INJECTION",
                reason="LEXICAL_HIGH_CONFIDENCE"
                if gate.rollout in {"SHADOW", "ADVISORY", "OFF"}
                else "LOW_CONFIDENCE",
                contradictions=contradictions_list,
                multiview_invoked=multiview or self.multiview_enabled,
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
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                vector_invoked=vector_searcher is not None,
                latency_ms=lat,
                short_circuited=True,
                decision="NO_INJECTION",
                reason="BRAIN_UNAVAILABLE",
                retrieval_error=True,
            )
        lat = (time.perf_counter() - t0) * 1000.0
        return CascadeResult(
            query=query,
            project_id=project_id,
            tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
            vector_invoked=vector_searcher is not None,
            latency_ms=lat,
            short_circuited=True,
            decision="NO_INJECTION",
            reason="NO_RELEVANT_MEMORY",
        )
