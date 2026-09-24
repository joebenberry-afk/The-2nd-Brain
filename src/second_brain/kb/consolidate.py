"""Consolidation and duplicate detection (LRN-01)."""

from __future__ import annotations

from . import index
from .records import Record


def near_duplicates(recs: list[Record], *, threshold: float = 0.8) -> list[tuple[str, str, float]]:
    """Find near-duplicate records by title token similarity.

    Args:
        recs: List of records to analyze
        threshold: Minimum Jaccard similarity (0-1) to consider as duplicates

    Returns:
        List of (id_a, id_b, score) tuples sorted by score descending, then by ids.
        Only pairs of active records in the same visibility bucket (scope, project,
        domains) are returned. Records with <2 title tokens are skipped.
    """
    # Build inverted index: token -> record ids
    token_to_recs: dict[str, list[str]] = {}

    for record in recs:
        # Only active records
        if not record.active:
            continue

        # Extract tokens from title
        tokens = index.tokens(record.title)

        # Skip records with <2 title tokens
        if len(tokens) < 2:
            continue

        # Add to inverted index
        for token in tokens:
            if token not in token_to_recs:
                token_to_recs[token] = []
            token_to_recs[token].append(record.id)

    # Build a map of records by id for easy access
    record_map = {r.id: r for r in recs}

    # Find candidates using inverted index
    candidates: set[tuple[str, str]] = set()
    for _token, rec_ids in token_to_recs.items():
        # Compare records sharing this token
        for i, id_a in enumerate(rec_ids):
            for id_b in rec_ids[i + 1 :]:
                # Normalize pair (smaller id first)
                pair = tuple(sorted([id_a, id_b]))  # type: ignore[assignment]
                candidates.add(pair)  # type: ignore[arg-type]

    # Compute Jaccard similarity for candidates
    results: list[tuple[str, str, float]] = []
    for id_a, id_b in candidates:
        rec_a = record_map[id_a]
        rec_b = record_map[id_b]

        # Check if they're in the same visibility bucket
        if not _same_bucket(rec_a, rec_b):
            continue

        # Compute Jaccard similarity
        tokens_a = set(index.tokens(rec_a.title))
        tokens_b = set(index.tokens(rec_b.title))
        score = _jaccard_similarity(tokens_a, tokens_b)

        if score >= threshold:
            results.append((id_a, id_b, score))

    # Sort by score descending, then by ids
    results.sort(key=lambda x: (-x[2], x[0], x[1]))

    return results


def _same_bucket(rec_a: Record, rec_b: Record) -> bool:
    """Check if two records are in the same visibility bucket."""
    return (
        rec_a.scope == rec_b.scope
        and rec_a.project == rec_b.project
        and rec_a.domains == rec_b.domains
    )


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return intersection / union
