"""Credit assignment (plan §43-44/§114, Phase 18).

NO_AUTO_REWARD invariant: nothing in this module — and no combination of
outcome recording + routing — creates credit_events automatically. The ONLY
writer is :func:`assign_credit`, which requires the caller to state levels
explicitly (plan §43: task success must never reward every active skill).

Counterfactual evaluation (plan §44) routes each task WITH and WITHOUT one
shadow skill via the router's ``skills`` override (no filesystem mutation) and
reports routing deltas; :func:`eval_skill_credit` turns those deltas into
INERT recommendations — nothing is written.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import db, plasticity, router
from .errors import BrainError

CREDIT_LEVELS: tuple[str, ...] = plasticity.CREDIT_LEVELS

# Deterministic subject-kind inference contract (assign_credit).
_SKILL_DIRS = ("skills/shadow", "skills/candidates")
_MEMORY_PREFIX = "mem-"
_KIND_PREFIXES = {
    "tool:": "tool",
    "scout:": "scout",
    "verification:": "verification",
    "policy:": "policy",
}
_BARE_IDS = {"scout": "scout"}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _infer_kind(home: Path, subject_id: str) -> str:
    """Map a subject id to a subject_kind, or raise BrainError for unknowns."""
    for directory in _SKILL_DIRS:
        if (Path(home) / directory / subject_id).is_dir():
            return "skill"
    if subject_id.startswith(_MEMORY_PREFIX):
        return "memory"
    for prefix, kind in _KIND_PREFIXES.items():
        if subject_id.startswith(prefix):
            return kind
    if subject_id in _BARE_IDS:
        return _BARE_IDS[subject_id]
    raise BrainError(
        f"Unknown credit subject {subject_id!r}: not a skill, memory, or "
        "prefixed (tool:/scout:/verification:/policy:) id"
    )


def assign_credit(
    home: Path,
    session_id: str | None,
    *,
    direct: list[str],
    contributory: list[str],
    correlated: list[str],
) -> dict:
    """Insert one credit_event per (subject, level). The ONLY credit writer;
    levels are always explicit. Returns per-level counts."""
    counts = {"direct": 0, "contributory": 0, "correlated": 0, "total": 0}
    for level, subject_ids in (
        ("direct", direct),
        ("contributory", contributory),
        ("correlated", correlated),
    ):
        if not isinstance(subject_ids, list):
            raise BrainError(f"{level} must be a list of subject ids")
        for subject_id in subject_ids:
            if not isinstance(subject_id, str) or not subject_id.strip():
                raise BrainError(f"{level} contains an invalid subject id {subject_id!r}")
            kind = _infer_kind(home, subject_id)
            plasticity.record_credit(home, session_id, subject_id, kind, level)
            counts[level] += 1
            counts["total"] += 1
    return counts


def credit_report(home: Path, session_id: str | None = None) -> dict:
    """Per (subject_id, subject_kind) counts by level; deterministic."""
    conn = db.connect(db.db_path(home))
    try:
        try:
            if session_id is not None:
                rows = conn.execute(
                    "SELECT subject_id, subject_kind, credit_level FROM credit_events "
                    "WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT subject_id, subject_kind, credit_level FROM credit_events"
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return {"total_events": 0, "subjects": []}  # nothing assigned yet
            raise
    finally:
        conn.close()
    subjects: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        key = (row["subject_id"], row["subject_kind"])
        entry = subjects.setdefault(key, {level: 0 for level in CREDIT_LEVELS})
        entry[row["credit_level"]] += 1
    entries = [
        {
            "subject_id": key[0],
            "subject_kind": key[1],
            **{level: data[level] for level in CREDIT_LEVELS},
            "total": sum(data.values()),
        }
        for key, data in sorted(subjects.items())
    ]
    return {"total_events": len(rows), "subjects": entries}


def _shadow_names(home: Path) -> list[str]:
    directory = Path(home) / "skills" / "shadow"
    return sorted(p.name for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []


def counterfactual_eval(home: Path, skill_name: str, tasks: list[dict]) -> dict:
    """Local counterfactual (plan §44): route each task with and without one
    shadow skill (router `skills` override — no filesystem mutation).
    delta_tools is unobservable here and reported honestly as 0."""
    if not isinstance(skill_name, str) or not skill_name.strip():
        raise BrainError("skill_name must be a non-empty string")
    all_names = _shadow_names(home)
    if skill_name not in all_names:
        raise BrainError(f"No shadow skill {skill_name!r}")
    without = [name for name in all_names if name != skill_name]
    per_task = []
    affected = 0
    for task in tasks:
        text = str(task.get("text", ""))
        with_skill = router.route(home, text, skills=all_names)["selected"]
        without_skill = router.route(home, text, skills=without)["selected"]
        changed = with_skill != without_skill
        affected += 1 if changed else 0
        per_task.append(
            {
                "text": text,
                "selected_with": with_skill,
                "selected_without": without_skill,
                "delta_tools": 0,  # unobservable from the Python side
                "routed_change": changed,
            }
        )
    report = {
        "skill": skill_name,
        "tasks": per_task,
        "tasks_affected": affected,
        "tasks_unaffected": len(tasks) - affected,
    }
    _write_report(home, skill_name, report)
    return report


def _write_report(home: Path, skill_name: str, report: dict) -> Path:
    out_dir = Path(home) / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"counterfactual-{skill_name}.md"
    lines = [
        "# Counterfactual Eval",
        "",
        f"skill: {skill_name}",
        f"generated_at: {_utcnow()}",
        f"tasks: {len(report['tasks'])} (affected {report['tasks_affected']}, "
        f"unaffected {report['tasks_unaffected']})",
        "",
        "| task | with | without | changed |",
        "|---|---|---|---|",
    ]
    for task in report["tasks"]:
        lines.append(
            f"| {task['text'][:60]} | {', '.join(task['selected_with']) or '-'} | "
            f"{', '.join(task['selected_without']) or '-'} | {task['routed_change']} |"
        )
    content = "\n".join(lines) + "\n"
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write counterfactual report {target}: {exc}") from exc
    return target


def eval_skill_credit(home: Path, skill_name: str, tasks: list[dict]) -> dict:
    """Counterfactual + INERT credit recommendations (direct/contributory/
    correlated). Nothing is written — recommendations are text only."""
    eval_result = counterfactual_eval(home, skill_name, tasks)
    expect_by_text = {str(task.get("text", "")): set(task.get("expect") or []) for task in tasks}
    recommendations: dict[str, int] = {"direct": 0, "contributory": 0, "correlated": 0}
    per_task: list[dict] = []
    for task in eval_result["tasks"]:
        if not task["routed_change"]:
            per_task.append({**task, "recommendation": None})
            continue
        expected = expect_by_text.get(task["text"], set())
        if skill_name in expected:
            level = "direct"
        elif skill_name in task["selected_with"] and len(task["selected_with"]) > 1:
            level = "contributory"
        else:
            level = "correlated"
        recommendations[level] += 1
        per_task.append({**task, "recommendation": level})
    return {
        "skill": skill_name,
        "tasks": per_task,
        "recommendations": recommendations,
        "note": "recommendations only; nothing was written (NO_AUTO_REWARD)",
    }
