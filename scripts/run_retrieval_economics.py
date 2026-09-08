"""Measure local retrieval overhead against the current Brain corpus.

Context token estimates and measured retrieval latency are not provider usage,
task acceptance, turns, or dollar savings. Those remain unmeasured here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from typing import Any

from second_brain import build_identity, contracts, db, hybrid_retrieval, semantic

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "reports" / "v2" / "retrieval"


def run_retrieval_economics(
    home: Path | None = None, *, repeats: int = 5, output_path: Path | None = None
) -> dict[str, Any]:
    """Profile at most sixteen real title queries without inventing downstream outcomes."""
    if repeats < 1:
        raise ValueError("repeats must be positive")
    home = Path(home or os.environ.get("SECOND_BRAIN_HOME") or ROOT).resolve()
    database = db.db_path(home)
    conn = db.connect(database, readonly=True)
    try:
        counts = conn.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(CASE WHEN status = 'current' THEN 1 END) AS current FROM memories"
        ).fetchone()
        queries = conn.execute(
            "SELECT memory_id, title, project_id FROM memories "
            "WHERE status = 'current' ORDER BY memory_id LIMIT 16"
        ).fetchall()
    finally:
        conn.close()
    if not queries:
        raise ValueError("the Brain has no current memories to profile")

    now = datetime.now(UTC)
    target = output_path or OUTPUT_DIR / f"retrieval-{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite retained evidence: {target}")
    retriever = hybrid_retrieval.HybridCascadeRetriever()
    runs = []
    for row in queries:
        timings: dict[str, list[float]] = {"baseline": [], "candidate": []}
        contexts = {"baseline": "", "candidate": ""}
        selected: dict[str, list[str]] = {"baseline": [], "candidate": []}
        for repetition in range(repeats):
            # Alternate order; each measurement includes its real retrieval call.
            order = ("baseline", "candidate") if repetition % 2 == 0 else ("candidate", "baseline")
            for arm in order:
                started = perf_counter_ns()
                if arm == "baseline":
                    matches = semantic.search_memories(
                        home,
                        row["title"],
                        project_id=row["project_id"],
                        top_k=4,
                        include_duplicates=True,
                    )
                    timings[arm].append((perf_counter_ns() - started) / 1_000_000)
                    contexts[arm] = "\n\n".join(
                        f"[{match['title']}]\n{match.get('_body', '')}" for match in matches
                    )
                    selected[arm] = [match["memory_id"] for match in matches]
                else:
                    result = retriever.retrieve(
                        home,
                        row["title"],
                        project_id=row["project_id"],
                        top_k=4,
                        lambda_param=0.7,
                    )
                    timings[arm].append((perf_counter_ns() - started) / 1_000_000)
                    contexts[arm] = "\n\n".join(
                        f"[{match.title}]\n{match.body}" for match in result.matches
                    )
                    selected[arm] = [match.memory_id for match in result.matches]
        runs.append(
            {
                "query_memory_id": row["memory_id"],
                "query_sha256": hashlib.sha256(row["title"].encode("utf-8")).hexdigest(),
                "project_id": row["project_id"],
                **{
                    arm: {
                        "retrieval_ms": timings[arm],
                        "median_ms": median(timings[arm]),
                        "context_chars": len(contexts[arm]),
                        "context_tokens_estimated": contracts.estimate_tokens(contexts[arm]),
                        "selected_memory_ids": selected[arm],
                    }
                    for arm in timings
                },
            }
        )
    report = {
        "schema_version": 1,
        "classification": "observed",
        "scope": "local_retrieval_scale_and_performance",
        "generated_at": now.isoformat(),
        "home": str(home),
        "source_tree_sha256": build_identity.source_tree_fingerprint(ROOT),
        "config_sha256": build_identity.configuration_fingerprint(home),
        "corpus": {"total": counts["total"], "current": counts["current"]},
        "database_bytes": database.stat().st_size,
        "query_selection": "up to sixteen current titles in memory-id order",
        "repeats": repeats,
        "runs": runs,
        "provider_usage": {"tokens": None, "dollars": None, "turns": None, "task_success": None},
        "live_economics_eligible": False,
        "economics_verdict": "INSUFFICIENT",
        "conclusion": "Measured local retrieval only; no downstream success or savings claim.",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    print(
        json.dumps(
            run_retrieval_economics(
                args.home,
                repeats=args.repeats,
                output_path=args.out,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
