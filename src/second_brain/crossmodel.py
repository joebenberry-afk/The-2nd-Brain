"""Cross-model memory (plan §116, Phase 20).

Model-specific skill outcomes are CALLER-RECORDED (no automatic capture).
Profiles are upserted; outcomes reference existing profiles and carry a
16-hex task hash (sha256 prefix) so the same task can be compared across
models. Global policy aggregates exclude models whose success rate is below a
threshold — model-specific failures must not contaminate global policy.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .errors import BrainError


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _dbfile(home: Path) -> Path:
    return db.db_path(home)


def _ensure_migrated(home: Path) -> None:
    if db.pending_migrations(_dbfile(home)):
        db.migrate(_dbfile(home))


def _insert_id(cursor: sqlite3.Cursor) -> int:
    lastrowid = cursor.lastrowid
    if lastrowid is None:
        raise BrainError("Insert did not return a row id")
    return int(lastrowid)


def task_hash(task: str) -> str:
    """16-hex deterministic task fingerprint."""
    return hashlib.sha256(task.encode("utf-8")).hexdigest()[:16]


def record_model(
    home: Path,
    model_id: str,
    family: str = "",
    capabilities: str = "",
) -> dict:
    """Upsert a model profile (first_seen_at preserved on update)."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise BrainError("model_id must be a non-empty string")
    for name, value in (("family", family), ("capabilities", capabilities)):
        if not isinstance(value, str):
            raise BrainError(f"{name} must be a string")
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            """INSERT INTO model_profiles (model_id, family, capabilities, first_seen_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(model_id) DO UPDATE SET family = excluded.family,
                   capabilities = excluded.capabilities""",
            (model_id, family, capabilities, _utcnow()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT model_id, family, capabilities, first_seen_at FROM model_profiles "
            "WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        return dict(row)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record model profile: {exc}") from exc
    finally:
        conn.close()


def record_skill_outcome(
    home: Path,
    model_id: str,
    skill_name: str,
    task: str,
    success: bool,
    noise: int = 0,
    f1: float = 0.0,
    session_id: str = "",
) -> int:
    """Record one model/skill/task outcome. The model profile must exist."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise BrainError("model_id must be a non-empty string")
    if not isinstance(skill_name, str) or not skill_name.strip():
        raise BrainError("skill_name must be a non-empty string")
    if not isinstance(task, str) or not task.strip():
        raise BrainError("task must be a non-empty string")
    if not isinstance(success, bool):
        raise BrainError("success must be a boolean")
    if not isinstance(noise, int) or isinstance(noise, bool) or noise < 0:
        raise BrainError("noise must be a non-negative integer")
    if isinstance(f1, bool) or not isinstance(f1, (int, float)) or not 0.0 <= float(f1) <= 1.0:
        raise BrainError("f1 must be a real number within 0..1")
    if not isinstance(session_id, str):
        raise BrainError("session_id must be a string")
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        profile = conn.execute(
            "SELECT 1 FROM model_profiles WHERE model_id = ?", (model_id,)
        ).fetchone()
        if profile is None:
            raise BrainError(f"Unknown model profile {model_id!r}; record_model first")
        cursor = conn.execute(
            """INSERT INTO model_skill_outcomes
               (model_id, skill_name, task_hash, success, noise, f1, session_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_id,
                skill_name,
                task_hash(task),
                1 if success else 0,
                noise,
                float(f1),
                session_id,
                _utcnow(),
            ),
        )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record skill outcome: {exc}") from exc
    finally:
        conn.close()


def _outcome_rows(
    home: Path, model_id: str | None = None, skill_name: str | None = None
) -> list[dict]:
    query = "SELECT * FROM model_skill_outcomes WHERE 1=1"
    params: list[object] = []
    if model_id is not None:
        query += " AND model_id = ?"
        params.append(model_id)
    if skill_name is not None:
        query += " AND skill_name = ?"
        params.append(skill_name)
    query += " ORDER BY outcome_id"
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def model_skill_report(
    home: Path,
    model_id: str | None = None,
    skill_name: str | None = None,
) -> dict:
    """Per-model aggregates (outcomes, successes, f1 mean, noise mean),
    filtered deterministically and sorted by model_id."""
    rows = _outcome_rows(home, model_id, skill_name)
    by_model: dict[str, dict] = {}
    for row in rows:
        entry = by_model.setdefault(
            row["model_id"], {"outcomes": 0, "successes": 0, "f1_sum": 0.0, "noise_sum": 0}
        )
        entry["outcomes"] += 1
        entry["successes"] += 1 if row["success"] else 0
        entry["f1_sum"] += float(row["f1"])
        entry["noise_sum"] += int(row["noise"])
    models = [
        {
            "model_id": mid,
            "outcomes": data["outcomes"],
            "successes": data["successes"],
            "f1_mean": round(data["f1_sum"] / data["outcomes"], 4),
            "noise_mean": round(data["noise_sum"] / data["outcomes"], 4),
        }
        for mid, data in sorted(by_model.items())
    ]
    return {"models": models}


def transfer_test(home: Path, skill_name: str, model_a: str, model_b: str) -> dict:
    """Plan §116 transfer check on overlapping task hashes for one skill.
    'transfers' when model_b success >= model_a success on the overlap (and
    model_b has >= 1 outcome); 'no_data' when there is no overlap."""
    a_rows = _outcome_rows(home, model_id=model_a, skill_name=skill_name)
    b_rows = _outcome_rows(home, model_id=model_b, skill_name=skill_name)
    a_by_hash: dict[str, list[dict]] = {}
    b_by_hash: dict[str, list[dict]] = {}
    for row in a_rows:
        a_by_hash.setdefault(row["task_hash"], []).append(row)
    for row in b_rows:
        b_by_hash.setdefault(row["task_hash"], []).append(row)
    overlap = sorted(set(a_by_hash) & set(b_by_hash))
    tasks = []
    a_success = 0
    b_success = 0
    for task_hash in overlap:
        a_ok = max(row["success"] for row in a_by_hash[task_hash])
        b_ok = max(row["success"] for row in b_by_hash[task_hash])
        a_success += a_ok
        b_success += b_ok
        tasks.append({"task_hash": task_hash, "success_a": a_ok, "success_b": b_ok})
    if not overlap:
        verdict = "no_data"
    elif b_success >= a_success and len(b_rows) >= 1:
        verdict = "transfers"
    else:
        verdict = "does_not_transfer"
    return {
        "skill_name": skill_name,
        "model_a": model_a,
        "model_b": model_b,
        "verdict": verdict,
        "overlap_count": len(overlap),
        "tasks": tasks,
    }


def global_policy_stats(home: Path, skill_name: str, min_success_per_model: float = 0.5) -> dict:
    """Aggregate over ONLY model profiles whose success rate for the skill is
    >= min_success_per_model. Models below the threshold are excluded
    (contamination guard: model-specific failures never leak into global
    policy)."""
    rows = _outcome_rows(home, skill_name=skill_name)
    by_model: dict[str, dict] = {}
    for row in rows:
        entry = by_model.setdefault(row["model_id"], {"outcomes": 0, "successes": 0})
        entry["outcomes"] += 1
        entry["successes"] += 1 if row["success"] else 0
    included: list[str] = []
    excluded: list[str] = []
    for mid, data in sorted(by_model.items()):
        rate = data["successes"] / data["outcomes"] if data["outcomes"] else 0.0
        if rate >= min_success_per_model:
            included.append(mid)
        else:
            excluded.append(mid)
    total_outcomes = sum(by_model[mid]["outcomes"] for mid in included)
    total_successes = sum(by_model[mid]["successes"] for mid in included)
    return {
        "skill_name": skill_name,
        "models_included": included,
        "models_excluded": excluded,
        "outcomes": total_outcomes,
        "successes": total_successes,
        "success_rate": round(total_successes / total_outcomes, 4) if total_outcomes else 0.0,
    }
