"""Labeled retrieval benchmark harness (plan Phase 6; v4.3 §14 Phase 3).

Builds synthetic-but-realistic labeled corpora of semantic memories, runs the
current engine (FTS5 path or linear fallback) over per-query JSON labels, and
measures Recall@1/3/5, Precision@5, MRR, duplicate rate, stale activation
rate, contradiction surfacing rate, retrieved tokens, and latency p50/p95 at
corpus sizes 100/1k/10k (50k optional).

Label format (JSONL, one per query):
  {"query": str, "must_retrieve": [id], "may_retrieve": [id],
   "must_not_retrieve": [id], "critical_ground_truth": str}

Quality gates are ENFORCED from Phase 7+; this harness only measures. The
Phase 6 engine has no filter/dedupe/contradiction channels, so duplicate /
stale / contradiction rates are computed from the labels against whatever the
engine returns (expected to be raw until Phases 7-11 land).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from second_brain import db, paths, semantic

# Realistic vocabulary pools (seeded, deterministic).
TOPICS = [
    ("wal", "WAL mode", "durability", "journal"),
    ("fts5", "FTS5", "tokenizer", "prefix"),
    ("telemetry", "telemetry", "session id", "jsonl"),
    ("rtd", "RTD", "distillation", "threshold"),
    ("router", "skill router", "trigger", "margin"),
    ("sleep", "sleep replay", "consolidation", "queue"),
    ("immune", "immune scan", "fingerprint", "quarantine"),
    ("backup", "backup restore", "snapshot", "manifest"),
    ("migration", "schema migration", "idempotent", "version"),
    ("ranking", "retrieval ranking", "bm25", "score"),
    ("dedupe", "duplicate suppression", "anchor", "current version"),
    ("budget", "token budget", "ceiling", "trim"),
]
TOPIC_WORDS = [w for t in TOPICS for w in t]
VERBS = ["ensures", "avoids", "tracks", "rebuilds", "verifies", "bounds", "surfaces", "preserves"]
QUALIFIERS = ["under load", "at 10k memories", "after migration", "in shadow mode", "per session"]
TOPIC_INDEX = {t[0]: t for t in TOPICS}


def batch_theme(batch_index: int) -> str:
    """Unique-per-batch theme token: phrase queries match ONE fact cluster
    (~8 docs) instead of every same-topic doc, so metadata ranking can
    distinguish the cluster's canonical fact."""
    return f"concept{batch_index:04d}"


def make_memory_body(rng: random.Random, topic_key: str) -> str:
    topic = TOPIC_INDEX[topic_key]
    # Deterministic coverage of the anchor terms (realistic doc for the topic)
    # plus one randomized sentence so docs in a family differ.
    sentences = [
        f"{topic[1]} {rng.choice(VERBS)} {rng.choice(QUALIFIERS)}.",
        f"{topic[2]} {rng.choice(VERBS)} {topic[3]}.",
        f"{rng.choice(topic)} {rng.choice(VERBS)} {rng.choice(QUALIFIERS)}.",
    ]
    return " ".join(sentences)


def unique_token(index: int) -> str:
    """Fixed-width unique token (case00042) so prefix matching stays unique
    at every corpus size (case00100 never matches case001000)."""
    return f"case{index:05d}"


def build_corpus(home: Path, size: int, seed: int) -> dict:
    """Create `size` realistic memories (+ duplicates/contradictions/superseded)
    and return a manifest {memory_id: {anchor, status, family}} plus label info.
    """
    rng = random.Random(seed)
    paths.ensure_layout(home)
    db.migrate(db.db_path(home))
    manifest: dict[str, dict] = {}
    families: dict[str, list[str]] = {}
    contradictions: list[tuple[str, str]] = []

    n_topics = len(TOPICS)
    topic_counts: dict[str, int] = {}
    for i in range(size):
        topic_key = TOPICS[i % n_topics][0]
        # topic-major theme batches: 8 consecutive SAME-topic docs share one
        # theme token so a phrase query matches one fact cluster
        tb = topic_counts.setdefault(topic_key, 0) // 8
        anchor = f"{topic_key}-{tb}"
        title = f"{TOPIC_INDEX[topic_key][1]} lesson {i}"
        body = make_memory_body(rng, topic_key) + f" Unique {unique_token(i)} marker."
        # the first memory of each 8-memory batch is the canonical target of
        # the batch's queries: created OBSERVED then curated to VERIFIED and
        # given decision value (successful retrievals) — realistic: the fact
        # a task looks for is the one that was verified and reused
        theme = batch_theme(tb)
        slot = topic_counts[topic_key] % 8
        canonical = slot == 5  # NOT the first row: bm25/rowid ties must not favor it
        grade = "OBSERVED" if canonical else rng.choice(["OBSERVED", "TESTED", "VERIFIED"])
        topic_counts[topic_key] += 1
        body = body + f" {theme}."
        mid = semantic.add_memory(
            home,
            title,
            body,
            scope="project",
            project_id="bench",
            grade=grade,
            summary=f"{TOPIC_INDEX[topic_key][1]} note {i}",
        )
        if canonical:
            semantic.curate(home, mid, grade="TESTED")  # one-step chain
            semantic.curate(home, mid, grade="VERIFIED")
            semantic.curate(home, mid, status="current")
            conn = db.connect(db.db_path(home))
            try:
                conn.execute(
                    "UPDATE memories SET successful_retrieval_count = 5 WHERE memory_id = ?", (mid,)
                )
                conn.commit()
            finally:
                conn.close()
        families.setdefault(topic_key, []).append(mid)
        manifest[mid] = {
            "anchor": anchor,
            "status": "current",
            "family": f"fact-{mid}",
            "uid": unique_token(i),
            "canonical": canonical,
        }
        # ~10% superseded duplicates (same anchor, older copy)
        if rng.random() < 0.10 and families[topic_key][-1] != mid:
            dup_body = f"Superseded copy. {make_memory_body(rng, topic_key)} {theme}."
            dup_id = semantic.add_memory(
                home,
                f"{TOPIC_INDEX[topic_key][1]} copy {i}",
                dup_body,
                scope="project",
                project_id="bench",
                grade="OBSERVED",
            )
            semantic.curate(home, dup_id, status="superseded")
            families.setdefault(f"dup:{topic_key}", []).append(dup_id)
            manifest[dup_id] = {"anchor": anchor, "status": "superseded", "family": f"fact-{mid}"}
        # ~8% archived
        if rng.random() < 0.08:
            semantic.curate(home, mid, status="archived")
            manifest[mid] = {"anchor": anchor, "status": "archived", "family": topic_key}
        # ~8% contradiction pair (two memories, conflicting bodies, same topic)
        if rng.random() < 0.08:
            other_body = f"Conflicting evidence. {make_memory_body(rng, topic_key)}"
            other_id = semantic.add_memory(
                home,
                f"{TOPIC_INDEX[topic_key][1]} conflict {i}",
                other_body,
                scope="project",
                project_id="bench",
                grade="VERIFIED",
            )
            contradictions.append((mid, other_id))
            # pair-specific family: contradictions are NOT duplicates
            manifest[other_id] = {
                "anchor": anchor,
                "status": "current",
                "family": f"contr-{mid}",
            }
        # ~12% near-duplicate CURRENT copy: identical title, same body template,
        # different unique token, labile status (canonical original stays the
        # representative). Same family -> dedupe must merge it.
        if rng.random() < 0.12:
            dup_title = title
            dup_body = (
                make_memory_body(rng, topic_key)
                + f" Unique {unique_token(i + size)} marker. {theme}."
            )
            dup_id = semantic.add_memory(
                home,
                dup_title,
                dup_body,
                scope="project",
                project_id="bench",
                grade="OBSERVED",
            )
            semantic.curate(home, dup_id, status="labile")
            manifest[dup_id] = {
                "anchor": anchor,
                "status": "labile",
                "family": f"fact-{mid}",
            }
    return {"manifest": manifest, "families": families, "contradictions": contradictions}


def build_labels(corpus: dict, queries: int, seed: int) -> list[dict]:
    rng = random.Random(seed + 1)
    manifest = corpus["manifest"]
    by_anchor: dict[str, list[str]] = {}
    for mid, info in manifest.items():
        by_anchor.setdefault(info["anchor"], []).append(mid)

    # choose query anchors: prefer topics with a current memory
    anchors = [
        a for a, ids in by_anchor.items() if any(manifest[i]["status"] == "current" for i in ids)
    ]
    rng.shuffle(anchors)
    labels = []
    for a in anchors[:queries]:
        ids = by_anchor[a]
        current = [i for i in ids if manifest[i]["status"] == "current"]
        if not current:
            continue
        canonicals = [i for i in current if manifest[i].get("canonical")]
        target = canonicals[0] if canonicals else current[0]
        may = [i for i in ids if i != target and manifest[i]["status"] == "superseded"]
        must_not = []
        others = [i for i in manifest if i not in ids]
        rng.shuffle(others)
        for other in others[:3]:
            must_not.append(other)
        topic = TOPIC_INDEX[a.split("-")[0]]
        uid = manifest[target].get("uid", "")
        theme = batch_theme(int(a.split("-")[1]))
        # Two realistic query styles per anchor:
        #  - phrase + batch theme: matches the fact cluster (~8 docs) — the
        #    metadata terms decide which cluster member is canonical
        #  - phrase + unique case token -> exact target (recall/precision)
        phrase = f"{topic[1]} {topic[2]} {theme}"
        queries_for_anchor = [phrase] + ([f"{phrase} {uid}" if uid else phrase] if uid else [])
        for query in queries_for_anchor:
            labels.append(
                {
                    "query": query,
                    "must_retrieve": [target],
                    "may_retrieve": may,
                    "must_not_retrieve": must_not,
                    "critical_ground_truth": topic[2],
                }
            )
    return labels


@dataclass
class QueryResult:
    retrieved: list[str]  # ranked memory ids (top 5 for metrics)
    latency_ms: float


ABLATION_TERMS: dict[str, frozenset[str]] = {
    "full": frozenset(semantic._SCORE_TERMS),
    "bm25": frozenset(),  # Phase 8-equivalent: relevance rank only
    "notrust": frozenset(semantic._SCORE_TERMS - {"trust"}),
    "nodecision": frozenset(semantic._SCORE_TERMS - {"decision"}),
    "trustonly": frozenset({"trust"}),
    "decisiononly": frozenset({"decision"}),
    "noscope": frozenset(semantic._SCORE_TERMS - {"scope"}),
    "nofresh": frozenset(semantic._SCORE_TERMS - {"freshness"}),
}


def run_engine(
    home: Path,
    query: str,
    engine: str,
    history: bool = False,
    duplicates: bool = False,
    score_terms: frozenset[str] | None = None,
) -> QueryResult:
    """history=True disables Phase 7 filters; duplicates=True disables Phase 8
    dedupe; score_terms selects the Phase 9 scoring terms (ablation)."""
    t0 = time.perf_counter()
    if engine == "linear":
        rows = semantic._search_linear(
            home,
            query,
            include_history=history,
            include_duplicates=duplicates,
            score_terms=score_terms or semantic._SCORE_TERMS,
        )
    else:
        rows = semantic.search_memories(
            home,
            query,
            include_history=history,
            include_duplicates=duplicates,
            score_terms=score_terms,
        )
    elapsed = (time.perf_counter() - t0) * 1000.0
    return QueryResult(retrieved=[r["memory_id"] for r in rows[:5]], latency_ms=elapsed)


def _estimate_tokens(home: Path, memory_id: str) -> int:
    try:
        row = semantic.show_memory(home, memory_id)
        return max(1, len(row["body"]) // 4)
    except Exception:
        return 1


def evaluate(labels: list[dict], results: list[QueryResult], corpus: dict, home: Path) -> dict:
    manifest = corpus["manifest"]
    contradiction_pairs = set(frozenset(p) for p in corpus["contradictions"])
    rec1 = rec3 = rec5 = prec5 = mrr_sum = 0.0
    dup_hits = stale_hits = retrieved_total = 0
    contradiction_queries = 0
    token_sum = 0
    latencies: list[float] = []
    n = len(labels)

    for label, res in zip(labels, results, strict=True):
        must = set(label["must_retrieve"])
        relevant = must | set(label["may_retrieve"])
        top1 = res.retrieved[:1]
        top3 = res.retrieved[:3]
        top5 = res.retrieved[:5]
        rec1 += len(must & set(top1)) / max(1, len(must))
        rec3 += len(must & set(top3)) / max(1, len(must))
        rec5 += len(must & set(top5)) / max(1, len(must))
        prec5 += len(relevant & set(top5)) / 5.0
        for rank, mid in enumerate(top5, start=1):
            if mid in must:
                mrr_sum += 1.0 / rank
                break
        retrieved_total += len(top5)
        for mid in top5:
            info = manifest.get(mid)
            if info and info["status"] in ("superseded", "archived"):
                stale_hits += 1
            token_sum += _estimate_tokens(home, mid)
        # duplicate: same family appearing twice in top5
        seen: set[str] = set()
        for mid in top5:
            fam = manifest.get(mid, {}).get("family", mid)
            if fam in seen:
                dup_hits += 1
            seen.add(fam)
        # contradiction surfaced: both members of a labeled pair retrieved
        retrieved_set = set(top5)
        if any(frozenset(p) <= retrieved_set for p in contradiction_pairs):
            contradiction_queries += 1
        latencies.append(res.latency_ms)

    def pct(x: float) -> float:
        return round(x / max(1, n), 4)

    return {
        "queries": n,
        "recall_at_1": pct(rec1),
        "recall_at_3": pct(rec3),
        "recall_at_5": pct(rec5),
        "precision_at_5": pct(prec5),
        "mrr": pct(mrr_sum),
        "duplicate_rate": round(dup_hits / max(1, retrieved_total), 4),
        "stale_activation_rate": round(stale_hits / max(1, retrieved_total), 4),
        "contradiction_surface_rate": round(contradiction_queries / max(1, n), 4),
        "avg_retrieved_tokens": round(token_sum / max(1, n), 1),
        "latency_p50_ms": round(statistics.median(latencies), 2),
        "latency_p95_ms": round(
            sorted(latencies)[min(len(latencies) - 1, int(0.95 * len(latencies)))]
            if latencies
            else 0.0,
            2,
        ),
    }


def bench(
    corpus_size: int,
    queries: int,
    engine: str,
    seed: int = 20260815,
    root: Path | None = None,
    history: bool = False,
    duplicates: bool = False,
    score_terms: frozenset[str] | None = None,
) -> dict:
    """history=True disables Phase 7 filters; duplicates=True disables Phase 8
    dedupe; score_terms selects the Phase 9 scoring terms (ablation)."""
    root = root or Path(tempfile.mkdtemp(prefix="sb-retrieval-bench-"))
    home = root / "brain"
    t0 = time.perf_counter()
    corpus = build_corpus(home, corpus_size, seed)
    build_s = round(time.perf_counter() - t0, 1)
    labels = build_labels(corpus, queries, seed)
    results = [
        run_engine(home, label["query"], engine, history, duplicates, score_terms)
        for label in labels
    ]
    metrics = evaluate(labels, results, corpus, home)
    mode = "raw" if history else ("filters" if duplicates else "filters+dedupe")
    metrics.update(
        {
            "corpus_size": corpus_size,
            "engine": engine,
            "filters": mode,
            "score_terms": "full" if score_terms is None else ("bm25" if not score_terms else "+".join(sorted(score_terms))),
            "build_seconds": build_s,
        }
    )
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=int, nargs="+", default=[100, 1000, 10000])
    ap.add_argument("--queries", type=int, default=25)
    ap.add_argument("--engine", choices=["fts", "linear"], default="fts")
    ap.add_argument("--seed", type=int, default=20260815)
    ap.add_argument("--root", type=Path, default=None, help="persist corpora under this dir")
    ap.add_argument(
        "--history", action="store_true", help="disable Phase 7 hard filters (raw baseline)"
    )
    ap.add_argument(
        "--duplicates", action="store_true", help="disable Phase 8 dedupe (filters-only baseline)"
    )
    ap.add_argument(
        "--ablation",
        choices=sorted(ABLATION_TERMS),
        default=None,
        help="Phase 9 scoring ablation mode (default: full formula)",
    )
    args = ap.parse_args()
    terms = ABLATION_TERMS[args.ablation] if args.ablation else None
    rows = [
        bench(c, args.queries, args.engine, args.seed, args.root, args.history, args.duplicates, terms)
        for c in args.corpus
    ]
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
