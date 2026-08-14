"""Retrieval benchmark against the current semantic.search_memories engine."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from second_brain import db, paths, semantic


@dataclass(frozen=True)
class RetrievalSummary:
    corpus_size: int
    queries: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    precision_at_5: float
    duplicate_injection_rate: float
    stale_activation_rate: float
    contradiction_surface_rate: float
    latency_p50_ms: float
    latency_p95_ms: float

    def as_dict(self) -> dict[str, int | float]:
        return {
            "corpus_size": self.corpus_size,
            "queries": self.queries,
            "recall_at_1": self.recall_at_1,
            "recall_at_3": self.recall_at_3,
            "recall_at_5": self.recall_at_5,
            "precision_at_5": self.precision_at_5,
            "duplicate_injection_rate": self.duplicate_injection_rate,
            "stale_activation_rate": self.stale_activation_rate,
            "contradiction_surface_rate": self.contradiction_surface_rate,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
        }


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(probability * (len(ordered) - 1)))
    return ordered[index]


def _new_home(root: Path) -> Path:
    home = root / "brain"
    paths.ensure_layout(home)
    db.migrate(db.db_path(home))
    return home


def benchmark_retrieval(corpus_size: int, *, root: Path, seed: int = 20260814) -> RetrievalSummary:
    """Build a temporary labeled corpus and measure top-k substring retrieval."""
    if corpus_size < 25:
        raise ValueError("corpus_size must be at least 25")
    home = _new_home(root)
    rng = random.Random(seed + corpus_size)
    query_count = min(25, max(5, corpus_size // 10))
    expected: dict[str, set[str]] = {}
    duplicates: set[str] = set()
    stale: set[str] = set()

    for index in range(corpus_size):
        query_index = index % query_count
        anchor = f"proof-anchor-{query_index:02d}"
        if index < query_count:
            title = f"Verified lesson {query_index}"
            body = f"The required fact for {anchor} is exact-{query_index}."
        elif index < query_count * 2:
            title = f"Duplicate historical note {query_index}"
            body = f"Duplicate of {anchor}; same fact, older wording."
        elif index < query_count * 3:
            title = f"Stale note {query_index}"
            body = f"Superseded guidance for {anchor}; do not use this old fact."
        else:
            noise = rng.choice(("build", "migration", "testing", "deployment", "logging"))
            title = f"Unrelated {noise} memory {index}"
            body = f"General note {index}; no target-specific anchor."
        memory_id = semantic.add_memory(
            home,
            title,
            body,
            scope="global",
            grade="VERIFIED" if index < query_count else "OBSERVED",
            summary=body[:80],
        )
        if index < query_count:
            expected.setdefault(anchor, set()).add(memory_id)
        elif index < query_count * 2:
            duplicates.add(memory_id)
        elif index < query_count * 3:
            stale.add(memory_id)

    recalls = {1: [], 3: [], 5: []}
    precisions: list[float] = []
    duplicate_hits = 0
    stale_hits = 0
    contradiction_hits = 0
    retrieved_count = 0
    latencies: list[float] = []
    for anchor, relevant_ids in expected.items():
        started = time.perf_counter()
        rows = semantic.search_memories(home, anchor)
        latencies.append((time.perf_counter() - started) * 1000)
        ranked = [row["memory_id"] for row in rows]
        for limit in recalls:
            recalls[limit].append(float(bool(set(ranked[:limit]) & relevant_ids)))
        top = ranked[:5]
        retrieved_count += len(top)
        precisions.append(sum(item in relevant_ids for item in top) / len(top) if top else 0.0)
        duplicate_hits += sum(item in duplicates for item in top)
        stale_hits += sum(item in stale for item in top)
        # The current engine has no contradiction-surfacing channel; keep the
        # zero visible rather than treating a missing signal as success.
        contradiction_hits += 0

    denominator = max(1, retrieved_count)
    return RetrievalSummary(
        corpus_size=corpus_size,
        queries=len(expected),
        recall_at_1=round(sum(recalls[1]) / len(expected), 4),
        recall_at_3=round(sum(recalls[3]) / len(expected), 4),
        recall_at_5=round(sum(recalls[5]) / len(expected), 4),
        precision_at_5=round(sum(precisions) / len(precisions), 4),
        duplicate_injection_rate=round(duplicate_hits / denominator, 4),
        stale_activation_rate=round(stale_hits / denominator, 4),
        contradiction_surface_rate=round(contradiction_hits / len(expected), 4),
        latency_p50_ms=round(median(latencies), 4),
        latency_p95_ms=round(_percentile(latencies, 0.95), 4),
    )
