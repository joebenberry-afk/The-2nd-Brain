"""Sleep engine — conservative consolidation pass only (plan §53-54, Phase 14 §110).

Manual, deterministic, conservative: replay high-priority episodes, cluster by
reusable-lesson similarity, strengthen provenance-linked current memories, and
report utility + contradictions. No dream pass yet (plan §53 — dream outputs
are candidate-only and come later), and no invented facts: strengthening only
bumps ``memories.strength`` and appends episode provenance sources — it never
creates memories, never edits bodies/titles/grades.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import db, episodes, plasticity, semantic
from .errors import BrainError

JACCARD_THRESHOLD = 0.3
STRENGTH_BUMP = 0.1
STRENGTH_CAP = 1.0
TOKEN_MIN_LEN = 4

REPORT_DIR = "sleep/reports"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _tokens(text: str) -> set[str]:
    return set(re.findall(rf"[a-z0-9]{{{TOKEN_MIN_LEN},}}", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ---------------------------------------------------------------------------
# Prioritized replay (plan §54)
# ---------------------------------------------------------------------------


def _parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        if line.startswith("# "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = line[2:].strip()
            buffer = []
        else:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def _priority(row: dict) -> float:
    return round(
        float(row.get("prediction_error") or 0) * 2
        + float(row.get("salience") or 0)
        + (1 if row.get("episode_type") == "correction" else 0),
        2,
    )


def replay_queue(home: Path, limit: int = 20) -> list[dict]:
    """Episodes ranked by priority DESC (prediction_error*2 + salience +
    correction bonus), then created_at. Each entry carries its parsed
    sections. Episodes with missing/corrupt files are skipped, never fatal."""
    ranked = []
    for row in episodes.list_episodes(home):
        try:
            shown = episodes.show_episode(home, row["episode_id"])
        except BrainError:
            continue
        ranked.append(
            {
                "episode_id": row["episode_id"],
                "episode_type": row["episode_type"],
                "created_at": row["created_at"],
                "priority": _priority(row),
                "sections": _parse_sections(shown["body"]),
            }
        )
    ranked.sort(key=lambda item: (-item["priority"], item["created_at"], item["episode_id"]))
    return ranked[:limit]


# ---------------------------------------------------------------------------
# Clustering (plan §53 conservative pass)
# ---------------------------------------------------------------------------


def cluster(queue: list[dict]) -> list[dict]:
    """Group queue episodes by Reusable-lesson token Jaccard >= 0.3.

    Deterministic: process in queue order; each episode joins the FIRST
    cluster it matches, else starts a new one. Empty lessons never join.
    """
    clusters: list[dict] = []
    for episode in queue:
        tokens = _tokens((episode.get("sections") or {}).get("Reusable lesson", ""))
        joined: dict | None = None
        for candidate in clusters:
            if _jaccard(tokens, candidate["tokens"]) >= JACCARD_THRESHOLD:
                joined = candidate
                break
        if joined is None:
            joined = {
                "tokens": tokens,
                "episode_ids": [],
                "lesson": (episode.get("sections") or {}).get("Reusable lesson", ""),
            }
            clusters.append(joined)
        joined["episode_ids"].append(episode["episode_id"])
    return clusters


# ---------------------------------------------------------------------------
# Conservative strengthening (no invented facts)
# ---------------------------------------------------------------------------


def strengthen_memories(home: Path, cluster: dict, dry_run: bool = True) -> list[dict]:
    """Bump strength + append episode provenance sources for current memories
    whose title shares >= 1 token (len >= 4) with the cluster's lesson words.

    Never creates memories and never touches body/title/grade. In dry-run mode
    nothing is written; the returned change records show what would happen.
    """
    lesson_words = cluster.get("tokens") or set()
    changes: list[dict] = []
    if not lesson_words or not cluster.get("episode_ids"):
        return changes
    for memory in semantic.list_memories(home, status="current"):
        title_words = _tokens(memory["title"])
        if not (title_words & lesson_words):
            continue
        before = float(memory["strength"] or 0.0)
        after = min(STRENGTH_CAP, round(before + STRENGTH_BUMP, 2))
        changes.append(
            {
                "memory_id": memory["memory_id"],
                "title": memory["title"],
                "strength_before": before,
                "strength_after": after,
                "sources_added": list(cluster["episode_ids"]),
            }
        )
        if dry_run:
            continue
        conn = db.connect(db.db_path(home))
        try:
            conn.execute(
                "UPDATE memories SET strength = ? WHERE memory_id = ?",
                (after, memory["memory_id"]),
            )
            for episode_id in cluster["episode_ids"]:
                conn.execute(
                    "INSERT INTO memory_sources (memory_id, source_ref, source_kind, added_at) "
                    "VALUES (?, ?, 'episode', ?)",
                    (memory["memory_id"], episode_id, _utcnow()),
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise BrainError(f"Could not strengthen memory {memory['memory_id']}: {exc}") from exc
        finally:
            conn.close()
    return changes


# ---------------------------------------------------------------------------
# Utility report (report only, no promotion)
# ---------------------------------------------------------------------------


def utility_report(home: Path) -> dict:
    """Aggregate plasticity/utility.jsonl per (subject_id, subject_kind):
    sums + counts, sorted by sum DESC."""
    aggregates: dict[tuple[str, str], dict] = {}
    for record in plasticity.read_utility_log(home):
        subject = (str(record.get("subject_id")), str(record.get("subject_kind")))
        entry = aggregates.setdefault(subject, {"sum": 0.0, "count": 0})
        entry["sum"] += float(record.get("delta") or 0)
        entry["count"] += 1
    entries = [
        {
            "subject_id": subject[0],
            "subject_kind": subject[1],
            "sum": round(data["sum"], 4),
            "count": data["count"],
        }
        for subject, data in sorted(aggregates.items())
    ]
    entries.sort(key=lambda entry: (-entry["sum"], entry["subject_id"], entry["subject_kind"]))
    return {"records": sum(data["count"] for data in aggregates.values()), "entries": entries}


# ---------------------------------------------------------------------------
# Consolidation (manual command; conservative pass only)
# ---------------------------------------------------------------------------


def _render_report(home: Path, result: dict, dry_run: bool) -> str:
    lines = [
        "# Consolidation Report",
        "",
        f"generated_at: {_utcnow()}",
        f"mode: {'dry-run' if dry_run else 'live'}",
        "",
        f"queue: {len(result['queue'])} episode(s)",
    ]
    for item in result["queue"][:10]:
        lines.append(
            f"- {item['episode_id']} priority={item['priority']} type={item['episode_type']}"
        )
    lines.append("")
    lines.append(f"clusters: {len(result['clusters'])}")
    for index, cluster in enumerate(result["clusters"]):
        lines.append(
            f"- cluster {index}: {', '.join(cluster['episode_ids'])} "
            f"lesson={cluster['lesson'][:80]!r}"
        )
    lines.append("")
    lines.append(f"strengthened: {len(result['strengthened'])} memory(ies)")
    for change in result["strengthened"]:
        lines.append(
            f"- {change['memory_id']} {change['title']!r} "
            f"strength {change['strength_before']} -> {change['strength_after']} "
            f"sources: {', '.join(change['sources_added'])}"
        )
    lines.append("")
    utility = result["utility"]
    lines.append(f"utility: {utility['records']} record(s)")
    for entry in utility["entries"][:10]:
        lines.append(
            f"- {entry['subject_id']} ({entry['subject_kind']}): "
            f"sum={entry['sum']} count={entry['count']}"
        )
    lines.append("")
    lines.append(f"contradictions: {len(result['contradictions'])} pair(s)")
    for pair in result["contradictions"][:10]:
        lines.append(f"- {pair['title']}: {pair['memory_id_a']} vs {pair['memory_id_b']}")
    return "\n".join(lines) + "\n"


def consolidate(home: Path, limit: int = 20, dry_run: bool = True) -> dict:
    """Run the conservative consolidation pass and write a report.

    Returns {queue, clusters, strengthened, utility, contradictions}; the
    report is written to ``sleep/reports/consolidation-<ts>.md`` (with the
    dry-run status). Deterministic except for timestamps. This is the ONLY
    sleep operation: no dream pass exists yet (plan §53).
    """
    queue = replay_queue(home, limit=limit)
    clusters = cluster(queue)
    strengthened: list[dict] = []
    for item in clusters:
        strengthened.extend(strengthen_memories(home, item, dry_run=dry_run))
    result = {
        "queue": queue,
        "clusters": clusters,
        "strengthened": strengthened,
        "utility": utility_report(home),
        "contradictions": semantic.contradictions(home, scope="project"),
    }
    report_dir = Path(home) / REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / f"consolidation-{_utcnow().replace(':', '-')}.md"
    result["report_path"] = str(target)
    fd, tmp = tempfile.mkstemp(dir=report_dir, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_render_report(home, result, dry_run))
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write consolidation report {target}: {exc}") from exc
    return result
