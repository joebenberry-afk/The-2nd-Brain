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
import math
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
_MAX_EXPLANATION_CANDIDATES = 256
_MAX_EXPLANATION_OMISSIONS = 256
_MAX_VECTOR_CALLBACK_ROWS = 4096


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
    # Bounded, consumer-reconstructable evidence from the production selection.
    explanation: dict[str, Any] = field(default_factory=dict)
    omitted: list[dict[str, Any]] = field(default_factory=list)

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
            "explanation": self.explanation,
            "omitted": self.omitted,
            "multiview_invoked": self.multiview_invoked,
            "retrieval_error": self.retrieval_error,
        }


def _authority_rank(row: dict[str, Any]) -> int:
    """Ordering preference by *effective* authority.

    A stored ceiling is a caller claim, so it cannot buy selection priority:
    only authority an independent issuer granted ranks, and nothing in this
    build can grant one, so every row ranks advisory.
    """
    return {"advisory": 0, "project_rule": 1, "policy": 2}[
        semantic.effective_authority_ceiling(row)
    ]


def _match_order_key(match: RetrievalMatch) -> tuple[float, int, str]:
    score = match.score
    return (
        -(score if score is not None else float("-inf")),
        -_authority_rank(match.raw_row),
        match.memory_id,
    )


def _validate_mmr_params(lambda_param: object, top_k: object) -> tuple[float, int]:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise BrainError("top_k must be an integer")
    if isinstance(lambda_param, bool) or not isinstance(lambda_param, (int, float)):
        raise BrainError("lambda_param must be a finite number between 0 and 1")
    value = float(lambda_param)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise BrainError("lambda_param must be a finite number between 0 and 1")
    return value, top_k


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
    selection_steps: list[dict[str, Any]] | None = None,
) -> list[RetrievalMatch]:
    """Apply bounded MMR and retain full-precision selection evidence."""
    lambda_value, limit = _validate_mmr_params(lambda_param, top_k)
    if limit <= 0:
        return []
    for match in matches:
        if match.score is not None:
            try:
                if isinstance(match.score, bool) or not math.isfinite(float(match.score)):
                    match.score = None
            except (TypeError, ValueError):
                match.score = None
        if match.score is not None:
            match.score_components["rank_score"] = match.score
    if not matches or len(matches) <= 1:
        for order, match in enumerate(matches[:limit], 1):
            match.score_components["diversity"] = 1.0
            match.score_components["selection_order"] = float(order)
            if match.score is not None:
                match.score_components["selection_score"] = match.score
        return matches[:limit]

    token_cache = [_token_set(f"{m.title} {m.summary} {m.body}") for m in matches]
    selected_indices: list[int] = []
    remaining_indices = list(range(len(matches)))
    best_first = min(remaining_indices, key=lambda idx: _match_order_key(matches[idx]))
    selected_indices.append(best_first)
    remaining_indices.remove(best_first)
    first = matches[best_first]
    first.score_components["diversity"] = 1.0
    first.score_components["selection_order"] = 1.0
    if first.score is not None:
        first.score_components["selection_score"] = first.score

    while remaining_indices and len(selected_indices) < limit:
        best_idx = -1
        best_mmr_score = -float("inf")
        best_diversity = 1.0
        evaluated: list[dict[str, Any]] | None = (
            []
            if selection_steps is not None and len(selection_steps) < _MAX_EXPLANATION_CANDIDATES
            else None
        )
        for idx in remaining_indices:
            cand = matches[idx]
            cand_score = cand.score or 0.0
            max_sim = max(
                _jaccard_similarity(token_cache[idx], token_cache[sel_idx])
                for sel_idx in selected_indices
            )
            diversity = 1.0 - max_sim
            mmr_score = lambda_value * cand_score - (1.0 - lambda_value) * max_sim
            if evaluated is not None and len(evaluated) < _MAX_EXPLANATION_CANDIDATES:
                evaluated.append(
                    {
                        "memory_id": cand.memory_id,
                        "max_token_jaccard": max_sim,
                        "mmr_score": mmr_score,
                    }
                )
            better = mmr_score > best_mmr_score
            if best_idx >= 0 and mmr_score == best_mmr_score:
                better = _match_order_key(cand) < _match_order_key(matches[best_idx])
            if better:
                best_mmr_score = mmr_score
                best_idx = idx
                best_diversity = diversity
        if best_idx < 0:
            break
        if evaluated is not None and selection_steps is not None:
            selection_steps.append(
                {
                    "candidates": evaluated,
                    "selected_id": matches[best_idx].memory_id,
                    "candidates_truncated_count": len(remaining_indices) - len(evaluated),
                }
            )
        chosen = matches[best_idx]
        chosen.score_components["diversity"] = best_diversity
        chosen.score_components["max_token_jaccard"] = 1.0 - best_diversity
        chosen.score_components["mmr_score"] = best_mmr_score
        chosen.score_components["selection_order"] = float(len(selected_indices) + 1)
        chosen.score_components["selection_score"] = best_mmr_score
        chosen.score = round(best_mmr_score, 4)
        selected_indices.append(best_idx)
        remaining_indices.remove(best_idx)
    return [matches[i] for i in selected_indices]


def _compute_score_components(
    home: Path,
    row: dict[str, Any],
    query_tokens: set[str],
    project_id: str | None,
) -> tuple[dict[str, float], bool, list[str]]:
    bm25 = row.get("_bm25")
    score_val = row.get("_score")
    relevance = float(row.get("_relevance", score_val if score_val is not None else 0.8))

    grade = semantic.effective_evidence_grade(row) or "OBSERVED"
    authority_ceiling = semantic.effective_authority_ceiling(row)
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

    p_need = row.get("_p_need")
    if p_need is None:
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
    if bm25 is not None:
        components["bm25_raw"] = float(bm25)
    return components, has_contradiction, contradiction_details


def _selection_explanation(
    *,
    query: str,
    lane: str,
    candidate_rows: list[dict[str, Any]],
    matches: list[RetrievalMatch],
    top_k: int,
    lambda_param: float,
    omitted: list[dict[str, Any]],
    selection_steps: list[dict[str, Any]] | None = None,
    algorithm: str = "mmr",
) -> dict[str, Any]:
    selected_ids = {match.memory_id for match in matches}
    candidate_total = len(candidate_rows)
    visible_rows = candidate_rows[:_MAX_EXPLANATION_CANDIDATES]
    candidates = []
    for order, row in enumerate(visible_rows, 1):
        score = row.get("_score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            score = None
        authority = _authority_rank(row)
        memory_id = str(row.get("memory_id") or "")
        candidates.append(
            {
                "memory_id": memory_id,
                "current_version": row.get("current_version"),
                "file_hash": row.get("file_hash"),
                "candidate_score": score,
                "authority_rank": authority,
                "candidate_order": order,
                "rank_key": [
                    -float(score) if score is not None else None,
                    -authority,
                    memory_id,
                ],
            }
        )
    seen = {str(item.get("memory_id")) for item in omitted}
    for row in visible_rows:
        memory_id = str(row.get("memory_id") or "")
        if memory_id and memory_id not in selected_ids and memory_id not in seen:
            omitted.append(
                {
                    "memory_id": memory_id,
                    "reason": "MMR_LIMIT" if algorithm == "mmr" else "VECTOR_TOP_K",
                }
            )
            seen.add(memory_id)
    if candidate_total > len(visible_rows):
        omitted.append(
            {
                "memory_id": None,
                "reason": "EXPLANATION_CANDIDATE_LIMIT",
                "truncated_count": candidate_total - len(visible_rows),
            }
        )
    step_total = max(0, len(matches) - 1) if algorithm == "mmr" else 0
    visible_steps = (selection_steps or [])[:_MAX_EXPLANATION_CANDIDATES]
    selected = [
        {
            "memory_id": match.memory_id,
            "rank_score": match.score_components.get("rank_score"),
            "selection_score": match.score_components.get("selection_score"),
            "authority_rank": _authority_rank(match.raw_row),
            "selection_order": match.score_components.get("selection_order"),
        }
        for match in matches[:_MAX_EXPLANATION_CANDIDATES]
    ]
    omitted_total = sum(item.get("truncated_count", 1) for item in omitted)
    if len(omitted) > _MAX_EXPLANATION_OMISSIONS:
        first_omitted = _MAX_EXPLANATION_OMISSIONS - 1
        truncated = sum(item.get("truncated_count", 1) for item in omitted[first_omitted:])
        omitted[first_omitted:] = [
            {
                "memory_id": None,
                "reason": "OMISSIONS_TRUNCATED",
                "truncated_count": truncated,
            }
        ]
    return {
        "algorithm": algorithm,
        "query": query,
        "lane": lane,
        "parameters": {
            "top_k": top_k,
            "lambda_param": lambda_param,
            "candidate_limit": _MAX_EXPLANATION_CANDIDATES,
        },
        "candidate_count": candidate_total,
        "candidates": candidates,
        "selected": selected,
        "selected_truncated_count": len(matches) - len(selected),
        "selection_steps": visible_steps,
        "selection_steps_truncated_count": max(0, step_total - len(visible_steps)),
        "replay_complete": (
            candidate_total <= _MAX_EXPLANATION_CANDIDATES
            and len(matches) <= _MAX_EXPLANATION_CANDIDATES
            and step_total == len(visible_steps)
            and all(step["candidates_truncated_count"] == 0 for step in visible_steps)
        ),
        "seed_rule": "candidate_score desc, authority_rank desc, memory_id asc",
        "tie_break": "candidate_score desc, authority_rank desc, memory_id asc",
        "omitted": omitted,
        "omitted_count": omitted_total,
        "formula": (
            "lambda * candidate_score - (1 - lambda) * max_token_jaccard"
            if algorithm == "mmr"
            else "candidate_score desc, authority_rank desc, memory_id asc"
        ),
    }


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
        result = float(value)
        return result if math.isfinite(result) else None

    @classmethod
    def _canonical_vector_row(
        cls, home: Path, candidate: object, *, project_id: str | None
    ) -> dict[str, Any] | None:
        if not isinstance(candidate, dict):
            return None
        memory_id = candidate.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            return None
        row = semantic._row(home, memory_id)
        if row is None:
            return None
        if not semantic._row_passes_filters(row, project_id=project_id, include_history=False):
            return None
        version = candidate.get("current_version")
        file_hash = candidate.get("file_hash")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != row.get("current_version")
            or not isinstance(file_hash, str)
            or not file_hash
            or file_hash != semantic._file_hash(home, row)
        ):
            return None
        score = cls._number(candidate.get("score"))
        if score is None:
            return None
        row["_score"] = score
        row["_body"] = semantic._body_text(home, row)
        return row

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
        lambda_value, top_k = _validate_mmr_params(lambda_param, top_k)
        if top_k <= 0 or not clean_q or clean_q.lower() in _TRIVIAL_QUERIES:
            lat = (time.perf_counter() - t0) * 1000.0
            reason = "NO_RELEVANT_MEMORY" if top_k <= 0 else "TRIVIAL_TASK"
            return CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                vector_invoked=False,
                latency_ms=lat,
                short_circuited=True,
                decision="NO_INJECTION",
                reason=reason,
                explanation={
                    "algorithm": "mmr",
                    "query": query,
                    "lane": lane,
                    "parameters": {"top_k": top_k, "lambda_param": lambda_value},
                    "candidate_count": 0,
                    "candidates": [],
                    "selected": [],
                    "selection_steps": [],
                    "omitted": [],
                },
            )
        epoch = self._epoch(home_path)
        config = self._config(home_path)
        gate = config.gate
        q_hash = self._query_hash(clean_q)
        project_key = project_id or ""
        # Callback projections have no stable generation in the lexical cache key.
        cached = None
        try:
            if vector_searcher is None:
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
                    authority_ceiling = semantic.effective_authority_ceiling(row)
                    if not semantic._lane_authorized(row, lane):
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
                            omitted=[{"memory_id": cand_id, "reason": "AUTHORITY_VIOLATION"}],
                        )
                    if not semantic._project_matches(row, project_id):
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
                            reason="PROJECT_MISMATCH",
                            omitted=[{"memory_id": cand_id, "reason": "PROJECT_MISMATCH"}],
                        )
                    if row.get("evidence_grade") == "REJECTED" or row.get("status") in (
                        "archived",
                        "superseded",
                    ):
                        lat = (time.perf_counter() - t0) * 1000.0
                        omitted = (
                            [semantic._history_omission(row)]
                            if row.get("status") in {"archived", "superseded"}
                            else [{"memory_id": cand_id, "reason": "EXCLUDED_STATUS"}]
                        )
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
                            omitted=omitted,
                            explanation={
                                "algorithm": "exact_ref",
                                "query": query,
                                "lane": lane,
                                "candidate_count": 0,
                                "candidates": [],
                                "selected": [],
                                "selection_steps": [],
                                "omitted": omitted,
                            },
                        )

                    contradiction_count = int(row.get("contradiction_count") or 0)
                    has_contradiction = contradiction_count > 0
                    contradictions_list = (
                        [
                            {
                                "memory_id": cand_id,
                                "title": row.get("title", ""),
                                "contradiction_count": contradiction_count,
                                "details": [f"Contradiction count: {contradiction_count}"],
                            }
                        ]
                        if has_contradiction
                        else []
                    )
                    components = {
                        "relevance": 1.0,
                        "authority": 1.0
                        if authority_ceiling in ("project_rule", "policy")
                        else 0.8,
                        "scope": 1.0,
                        "freshness": 1.0,
                        "contradiction": 0.5 if has_contradiction else 1.0,
                        "activation_need": 1.0,
                        "diversity": 1.0,
                        "rank_score": 1.0,
                        "selection_score": 1.0,
                        "selection_order": 1.0,
                        "final_score": 1.0,
                    }
                    match = RetrievalMatch(
                        memory_id=row.get("memory_id") or cand_id,
                        title=row.get("title", ""),
                        score=1.0,
                        tier_resolved=RetrievalTier.TIER_0_EXACT_REF,
                        summary=row.get("summary", ""),
                        body=semantic._body_text(home_path, row),
                        confidence=1.0,
                        raw_row=dict(row),
                        score_components=components,
                        has_contradiction=has_contradiction,
                        contradiction_details=(
                            [f"Contradiction count: {contradiction_count}"]
                            if has_contradiction
                            else []
                        ),
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
                        explanation={
                            "algorithm": "exact_ref",
                            "query": query,
                            "lane": lane,
                            "parameters": {"top_k": top_k, "lambda_param": lambda_value},
                            "candidate_count": 1,
                            "candidates": [
                                {
                                    "memory_id": match.memory_id,
                                    "candidate_score": 1.0,
                                    "current_version": row.get("current_version"),
                                    "file_hash": semantic._file_hash(home_path, row),
                                    "authority_rank": _authority_rank(row),
                                    "candidate_order": 1,
                                }
                            ],
                            "selected": [
                                {
                                    "memory_id": match.memory_id,
                                    "rank_score": 1.0,
                                    "selection_order": 1.0,
                                }
                            ],
                            "selection_steps": [],
                            "omitted": [],
                        },
                    )
            except BrainError:
                pass

        retrieval_error = False
        omitted: list[dict[str, Any]] = []
        try:
            fts_rows = semantic.search_memories(
                home_path,
                clean_q,
                project_id=project_id,
                top_k=min(max(top_k * 2, 20), _MAX_EXPLANATION_CANDIDATES),
                include_history=False,
                include_duplicates=True,
                history_omissions=omitted,
            )
        except Exception:
            retrieval_error = True
            fts_rows = []

        matches: list[RetrievalMatch] = []
        contradictions_list: list[dict[str, Any]] = []
        canonical_rows: list[dict[str, Any]] = []
        selection_steps: list[dict[str, Any]] = []

        for candidate in fts_rows:
            if not semantic._lane_authorized(candidate, lane):
                omitted.append(
                    {"memory_id": candidate.get("memory_id"), "reason": "AUTHORITY_VIOLATION"}
                )
                continue
            canonical_rows.append(candidate)
        query_tokens = set(re.findall(r"\b\w+\b", clean_q.lower()))
        for row in canonical_rows:
            components, has_c, c_details = _compute_score_components(
                home_path, row, query_tokens, project_id
            )
            match = RetrievalMatch(
                memory_id=row["memory_id"],
                title=row.get("title", ""),
                score=self._number(row.get("_score")),
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                summary=row.get("summary", ""),
                body=row.get("_body", ""),
                confidence=self._number(row.get("_score")),
                raw_row=dict(row),
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
                        "contradiction_count": row.get("contradiction_count", 0),
                        "details": c_details,
                    }
                )
        matches = apply_mmr(
            matches,
            lambda_param=lambda_value,
            top_k=top_k,
            selection_steps=selection_steps,
        )
        explanation = _selection_explanation(
            query=query,
            lane=lane,
            candidate_rows=canonical_rows,
            matches=matches,
            top_k=top_k,
            lambda_param=lambda_value,
            omitted=omitted,
            selection_steps=selection_steps,
        )
        scores = [m.score for m in matches]
        if canonical_rows and self._gate_passes(scores, gate, lane, confidence_threshold):
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
                explanation=explanation,
                omitted=omitted,
                multiview_invoked=multiview or self.multiview_enabled,
            )

        if vector_searcher is not None:
            try:
                vec_res = vector_searcher(clean_q, project_id)
                if not isinstance(vec_res, list):
                    retrieval_error = True
                    vec_res = []
            except Exception:
                retrieval_error = True
                vec_res = []
            vector_by_id: dict[str, dict[str, Any]] = {}
            callback_limit = _MAX_VECTOR_CALLBACK_ROWS
            callback_count = len(vec_res) if isinstance(vec_res, list) else None
            for callback_index, raw_candidate in enumerate(vec_res):
                if callback_index >= callback_limit:
                    omitted.append(
                        {
                            "memory_id": None,
                            "reason": "VECTOR_CALLBACK_LIMIT",
                            "truncated_count": (
                                max(0, callback_count - callback_limit)
                                if callback_count is not None
                                else None
                            ),
                        }
                    )
                    break
                if not isinstance(raw_candidate, dict):
                    omitted.append({"memory_id": None, "reason": "STALE_OR_UNSAFE_CANDIDATE"})
                    continue
                candidate = dict(raw_candidate)
                candidate["_score"] = candidate.get("score")
                canonical = self._canonical_vector_row(home_path, candidate, project_id=project_id)
                if canonical is None:
                    omitted.append(
                        {
                            "memory_id": candidate.get("memory_id"),
                            "reason": "STALE_OR_UNSAFE_CANDIDATE",
                        }
                    )
                    continue
                if not semantic._lane_authorized(canonical, lane):
                    omitted.append(
                        {"memory_id": canonical["memory_id"], "reason": "AUTHORITY_VIOLATION"}
                    )
                    continue
                mid = canonical["memory_id"]
                previous = vector_by_id.get(mid)
                if previous is not None:
                    omitted.append({"memory_id": mid, "reason": "VECTOR_DUPLICATE"})
                    if canonical["_score"] <= previous["_score"]:
                        continue
                vector_by_id[mid] = canonical
            vector_canonical_rows = list(vector_by_id.values())
            semantic._attach_contradictions(
                vector_canonical_rows, semantic._contradiction_map(vector_canonical_rows)
            )
            vector_candidates = sorted(
                vector_canonical_rows,
                key=lambda row: (
                    -float(row["_score"]),
                    -_authority_rank(row),
                    str(row["memory_id"]),
                ),
            )
            # Bound the admitted pool, not just the evidence needed to replay it.
            for row in vector_candidates[_MAX_EXPLANATION_CANDIDATES:]:
                omitted.append({"memory_id": row["memory_id"], "reason": "CANDIDATE_POOL_LIMIT"})
            vector_candidates = vector_candidates[:_MAX_EXPLANATION_CANDIDATES]
            vector_rows = vector_candidates[:top_k]
            for row in vector_candidates[top_k:]:
                omitted.append({"memory_id": row["memory_id"], "reason": "VECTOR_TOP_K"})
            if vector_rows:
                vector_matches = []
                vector_contradictions = []
                for order, row in enumerate(vector_rows, 1):
                    components, has_c, details = _compute_score_components(
                        home_path, row, set(), project_id
                    )
                    components.update(
                        {
                            "rank_score": row["_score"],
                            "selection_score": row["_score"],
                            "selection_order": float(order),
                        }
                    )
                    vector_matches.append(
                        RetrievalMatch(
                            memory_id=row["memory_id"],
                            title=row.get("title", ""),
                            score=row["_score"],
                            tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                            summary=row.get("summary", ""),
                            body=row.get("_body", ""),
                            confidence=row["_score"],
                            raw_row=row,
                            score_components=components,
                            has_contradiction=has_c,
                            contradiction_details=details,
                        )
                    )
                    if has_c:
                        vector_contradictions.append(
                            {
                                "memory_id": row["memory_id"],
                                "title": row.get("title", ""),
                                "details": details,
                            }
                        )
                explanation = _selection_explanation(
                    query=query,
                    lane=lane,
                    candidate_rows=vector_candidates,
                    matches=vector_matches,
                    top_k=top_k,
                    lambda_param=lambda_value,
                    omitted=omitted,
                    algorithm="ranked",
                )
                inject = self._gate_passes(
                    [m.score for m in vector_matches], gate, lane, confidence_threshold
                ) or gate.rollout in {"SHADOW", "ADVISORY", "OFF"}
                return CascadeResult(
                    query=query,
                    project_id=project_id,
                    tier_resolved=RetrievalTier.TIER_3_VECTOR_SEMANTIC,
                    matches=vector_matches,
                    vector_invoked=True,
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    short_circuited=False,
                    decision="INJECT" if inject else "NO_INJECTION",
                    reason="VECTOR_FALLBACK_MATCH" if inject else "LOW_CONFIDENCE",
                    contradictions=vector_contradictions,
                    explanation=explanation,
                    omitted=omitted,
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
        if canonical_rows:
            lat = (time.perf_counter() - t0) * 1000.0
            return CascadeResult(
                query=query,
                project_id=project_id,
                tier_resolved=RetrievalTier.TIER_2_LEXICAL_FTS5,
                matches=matches,
                vector_invoked=vector_searcher is not None,
                latency_ms=lat,
                short_circuited=True,
                decision=(
                    "INJECT" if gate.rollout in {"SHADOW", "ADVISORY", "OFF"} else "NO_INJECTION"
                ),
                reason=(
                    "LEXICAL_HIGH_CONFIDENCE"
                    if gate.rollout in {"SHADOW", "ADVISORY", "OFF"}
                    else "LOW_CONFIDENCE"
                ),
                contradictions=contradictions_list,
                explanation=explanation,
                omitted=omitted,
                multiview_invoked=multiview or self.multiview_enabled,
            )
        try:
            if vector_searcher is None and not omitted:
                cache_conn = self._cache_conn(home_path)
                cache_conn.execute(
                    "INSERT OR IGNORE INTO negative_cache("
                    "query_hash, project_id, lane, retrieval_config_version, "
                    "memory_epoch, created_at)"
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
            explanation=explanation,
            omitted=omitted,
        )
