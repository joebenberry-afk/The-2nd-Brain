"""Reconsolidation / strategic forgetting (plan §49-52/§15, Phase 15 §111).

Advisory-only forgetting. Tracks retrievals and activation outcomes per memory
(meta-memory counters), applies the HOT/WARM/COLD/ARCHIVED heat states, and
runs a decay pass that only moves stale memories OUT of the hot set — it never
destroys canonical evidence and never auto-archives (plan §52).

Protected memories (current+VERIFIED, or constitution/security-titled) never
decay. Heat/status changes are pure metadata: memory files and memory_versions
are never touched, so history stays recoverable.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts, db, decisions, semantic
from .errors import BrainError

HEAT_STATES: tuple[str, ...] = ("HOT", "WARM", "COLD", "ARCHIVED")
ACTIVATION_OUTCOMES: tuple[str, ...] = ("correct", "irrelevant", "contradicted")
RECONSOLIDATION_ACTIONS: tuple[str, ...] = (
    "strengthen",
    "narrow",
    "update",
    "split",
    "merge",
    "supersede",
    "demote",
    "archive",
)
HOT_TTL_DAYS = 7
WARM_TTL_DAYS = 30
PROTECTED_TITLE_WORDS = ("constitution", "security")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(val: datetime | str | None) -> datetime:
    if val is None:
        return datetime.now(UTC)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)

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


def _memory_row(home: Path, memory_id: str) -> dict:
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    return dict(row)


def _validate_session(session_id: str | None) -> None:
    if session_id is not None and not isinstance(session_id, str):
        raise BrainError("session_id must be a string or None")


def record_retrieval(
    home: Path, memory_id: str, session_id: str | None = None, *, idempotent: bool = False
) -> int:
    """Record a retrieval, optionally deduplicated per memory/session.

    ``idempotent`` is reserved for repeated host-hook feedback. The default
    remains append-only for callers that intentionally record each retrieval.
    """
    if not isinstance(memory_id, str) or not memory_id.strip():
        raise BrainError("memory_id must be a non-empty string")
    _validate_session(session_id)
    _memory_row(home, memory_id)  # existence check + lazy migration
    now = _utcnow()
    conn = db.connect(_dbfile(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        if idempotent and session_id is not None:
            existing = conn.execute(
                "SELECT retrieval_id FROM memory_retrievals "
                "WHERE memory_id = ? AND session_id = ? ORDER BY retrieval_id LIMIT 1",
                (memory_id, session_id),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return int(existing["retrieval_id"])
        cursor = conn.execute(
            "INSERT INTO memory_retrievals (memory_id, session_id, created_at) VALUES (?, ?, ?)",
            (memory_id, session_id, now),
        )
        conn.execute(
            "UPDATE memories SET retrieval_count = retrieval_count + 1, "
            "last_retrieved_at = ? WHERE memory_id = ?",
            (now, memory_id),
        )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record retrieval: {exc}") from exc
    finally:
        conn.close()


def record_activation(
    home: Path | str,
    memory_id: str,
    outcome: str,
    session_id: str | None = None,
    *,
    idempotent: bool = False,
    kind: str | None = None,
) -> int:
    """Record an activation outcome; optionally deduplicate host-hook repeats."""
    home_p = Path(home)
    if not isinstance(memory_id, str) or not memory_id.strip():
        raise BrainError("memory_id must be a non-empty string")
    if outcome not in ACTIVATION_OUTCOMES:
        raise BrainError(f"outcome must be one of {', '.join(ACTIVATION_OUTCOMES)}")
    _validate_session(session_id)
    _memory_row(home_p, memory_id)  # existence check + lazy migration
    if kind is None:
        kind = "used" if outcome == "correct" else outcome
    conn = db.connect(_dbfile(home_p))
    try:
        conn.execute("BEGIN IMMEDIATE")
        if idempotent and session_id is not None:
            existing = conn.execute(
                "SELECT activation_id FROM memory_activations "
                "WHERE memory_id = ? AND session_id = ? AND outcome = ? "
                "ORDER BY activation_id LIMIT 1",
                (memory_id, session_id, outcome),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return int(existing["activation_id"])
        cursor = conn.execute(
            "INSERT INTO memory_activations (memory_id, session_id, outcome, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (memory_id, session_id, outcome, _utcnow(), kind),
        )
        if outcome == "correct":
            conn.execute(
                "UPDATE memories SET successful_retrieval_count = successful_retrieval_count + 1 "
                "WHERE memory_id = ?",
                (memory_id,),
            )
        elif outcome == "contradicted":
            conn.execute(
                "UPDATE memories SET contradiction_count = contradiction_count + 1, "
                "heat = 'COLD', status = 'labile' WHERE memory_id = ?",
                (memory_id,),
            )
        if kind in ("used", "success", "verified"):
            conn.execute(
                "UPDATE memories SET storage_strength = storage_strength + 0.1 "
                "WHERE memory_id = ?",
                (memory_id,),
            )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record activation: {exc}") from exc
    finally:
        conn.close()


def compute_base_level_activation(
    home: Path | str,
    memory_id: str,
    now: datetime | str | None = None,
    d: float = 0.5,
) -> float:
    """Compute ACT-R base-level activation: B = ln(sum(t_j ** -d)).

    Retrieval-only events never contribute. When no matching events exist or
    sum <= 0, returns -10.0.
    """
    home_p = Path(home)
    _ensure_migrated(home_p)
    now_dt = _parse_dt(now)
    conn = db.connect(_dbfile(home_p))
    try:
        rows = conn.execute(
            "SELECT created_at FROM memory_activations "
            "WHERE memory_id = ? AND ("
            "  kind IN ('used', 'success', 'verified') OR "
            "  (kind IS NULL AND outcome = 'correct')"
            ")",
            (memory_id,),
        ).fetchall()
    except sqlite3.Error:
        return -10.0
    finally:
        conn.close()

    if not rows:
        return -10.0

    total_sum = 0.0
    for r in rows:
        created_dt = _parse_dt(r["created_at"])
        delta_sec = (now_dt - created_dt).total_seconds()
        t_j = max(delta_sec / 3600.0, 0.001)
        total_sum += t_j ** (-d)

    if total_sum <= 0.0:
        return -10.0
    return math.log(total_sum)


def compute_p_need(
    home: Path | str,
    memory_id: str,
    now: datetime | str | None = None,
    tau: float = 0.0,
    s: float = 1.0,
    d: float = 0.5,
) -> float:
    """Compute need probability P_need = sigmoid((B - tau) / s).

    Bounds the sigmoid argument to [-40, 40] to prevent overflow.
    """
    b = compute_base_level_activation(home, memory_id, now=now, d=d)
    s_val = float(s) if s and s > 0 else 1.0
    z = (b - float(tau)) / s_val
    z_clamped = max(-40.0, min(40.0, z))
    return 1.0 / (1.0 + math.exp(-z_clamped))

def apply_heat(home: Path, memory_id: str, heat: str) -> dict:
    """Set a memory's heat state with plan §52 guardrails:

    - HOT only for status 'current' with grade VERIFIED/TESTED;
    - ARCHIVED never for status 'current';
    - heat is meta-state: no version bump, no file changes.
    """
    if heat not in HEAT_STATES:
        raise BrainError(f"heat must be one of {', '.join(HEAT_STATES)}")
    row = _memory_row(home, memory_id)
    if heat == "HOT" and not (
        row["status"] == "current" and row["evidence_grade"] in ("VERIFIED", "TESTED")
    ):
        raise BrainError("HOT requires status 'current' and grade VERIFIED or TESTED")
    if heat == "ARCHIVED" and row["status"] == "current":
        raise BrainError("ARCHIVED cannot be applied to a memory with status 'current'")
    conn = db.connect(_dbfile(home))
    try:
        conn.execute("UPDATE memories SET heat = ? WHERE memory_id = ?", (heat, memory_id))
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not set heat: {exc}") from exc
    finally:
        conn.close()
    return _memory_row(home, memory_id)


def _protected(row: dict) -> bool:
    if row["status"] == "current" and row["evidence_grade"] == "VERIFIED":
        return True
    title = (row.get("title") or "").lower()
    return any(word in title for word in PROTECTED_TITLE_WORDS)


def _reference_dt(row: dict) -> datetime | None:
    raw = row.get("last_retrieved_at") or row.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def decay_pass(
    home: Path | str,
    arg1: bool | datetime | str | None = None,
    arg2: bool | datetime | str | None = None,
    *,
    dry_run: bool | None = None,
    now: datetime | str | None = None,
    hot_ttl_days: int = HOT_TTL_DAYS,
    warm_ttl_days: int = WARM_TTL_DAYS,
) -> list[dict]:
    """Advisory decay: updates heat based on ACT-R activation B (or legacy TTL
    when no activation events exist). Protected memories never decay;
    nothing is ever auto-ARCHIVED and no evidence is destroyed."""
    if dry_run is None:
        if isinstance(arg1, bool):
            dry_run = arg1
        elif isinstance(arg2, bool):
            dry_run = arg2
        else:
            dry_run = False
    if now is None:
        if isinstance(arg1, (str, datetime)):
            now = arg1
        elif isinstance(arg2, (str, datetime)):
            now = arg2

    home_p = Path(home)
    _ensure_migrated(home_p)
    now_dt = _parse_dt(now)
    changes: list[dict] = []

    conn = db.connect(_dbfile(home_p))
    try:
        act_rows = conn.execute(
            "SELECT DISTINCT memory_id FROM memory_activations"
        ).fetchall()
        memories_with_activations = {str(r["memory_id"]) for r in act_rows}
    except sqlite3.Error:
        memories_with_activations = set()
    finally:
        conn.close()

    for row in semantic.list_memories(home_p):
        if _protected(row):
            continue
        heat = row.get("heat") or "WARM"
        if heat == "ARCHIVED":
            continue

        mid = str(row["memory_id"])
        new_heat = heat
        reason = None

        contradiction_count = int(row.get("contradiction_count") or 0)
        if mid in memories_with_activations:
            b = compute_base_level_activation(home_p, mid, now=now_dt)
            if b > 0:
                if (
                    contradiction_count == 0
                    and row.get("status") == "current"
                    and row.get("evidence_grade") in ("VERIFIED", "TESTED")
                ):
                    candidate_heat = "HOT"
                elif contradiction_count > 0:
                    candidate_heat = "COLD"
                else:
                    candidate_heat = "WARM"
            elif b > -3:
                candidate_heat = "COLD" if contradiction_count > 0 else "WARM"
            else:
                candidate_heat = "COLD"
            if candidate_heat != heat:
                new_heat = candidate_heat
                if contradiction_count > 0:
                    reason = f"Contradiction count={contradiction_count} prevents HOT; ACT-R B={b:.2f}"
                else:
                    reason = f"ACT-R base activation B={b:.2f}"
        else:
            reference = _reference_dt(row)
            age_days = float("inf") if reference is None else (now_dt - reference).days
            if heat == "HOT" and age_days > hot_ttl_days:
                new_heat = "WARM"
                reason = f"not retrieved in {age_days:.0f} day(s) (TTL {hot_ttl_days})"
            elif heat == "WARM" and (row.get("retrieval_count") or 0) == 0 and age_days > warm_ttl_days:
                new_heat = "COLD"
                reason = f"never retrieved and older than {warm_ttl_days} day(s)"

        if new_heat == heat:
            continue

        changes.append(
            {
                "memory_id": row["memory_id"],
                "title": row["title"],
                "heat_before": heat,
                "heat_after": new_heat,
                "reason": reason,
            }
        )
        if dry_run:
            continue

        conn = db.connect(_dbfile(home_p))
        try:
            conn.execute(
                "UPDATE memories SET heat = ? WHERE memory_id = ?",
                (new_heat, row["memory_id"]),
            )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise BrainError(f"Could not decay memory {row['memory_id']}: {exc}") from exc
        finally:
            conn.close()

        decisions.record(
            home_p,
            kind="reconsolidation",
            session_id=f"decay-{row['memory_id']}",
            task_id=f"task-decay-{row['memory_id']}",
            chosen={
                "action": "demote" if new_heat in ("WARM", "COLD") else "strengthen",
                "memory_id": row["memory_id"],
                "heat_before": heat,
                "heat_after": new_heat,
            },
            alternatives=[{"heat": h} for h in HEAT_STATES if h != new_heat],
            propensity=1.0,
            randomized=False,
            policy_version="v7.2",
            stage="SHADOW",
            inputs={
                "memory_id": row["memory_id"],
                "heat_before": heat,
                "reason": reason,
                "contradiction_count": contradiction_count,
            },
        )

    return changes

def evaluate_memory(
    home: Path | str,
    memory_id: str,
    *,
    now: datetime | str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate ACT-R activation, need probability, and contradictions for reconsolidation.

    Contradictions strictly prevent silent strengthening. Every evaluation
    records an admission/reconsolidation decision in decisions.
    """
    home_p = Path(home)
    _ensure_migrated(home_p)
    row = _memory_row(home_p, memory_id)
    now_dt = _parse_dt(now)

    b = compute_base_level_activation(home_p, memory_id, now=now_dt)
    p_need = compute_p_need(home_p, memory_id, now=now_dt)

    conn = db.connect(_dbfile(home_p))
    try:
        act_row = conn.execute(
            "SELECT count(*) as c FROM memory_activations "
            "WHERE memory_id = ? AND outcome = 'contradicted'",
            (memory_id,),
        ).fetchone()
        act_contradictions = int(act_row["c"]) if act_row else 0
    finally:
        conn.close()

    stored_contradictions = int(row.get("contradiction_count") or 0)
    total_contradictions = max(stored_contradictions, act_contradictions)

    if total_contradictions > 0:
        action = "narrow" if row.get("status") in ("current", "labile") else "demote"
        reason = f"Contradictions detected ({total_contradictions}); silent strengthening blocked"
    elif row.get("status") == "current":
        if b > 0.0 and p_need >= 0.5:
            action = "strengthen"
            reason = f"High activation B={b:.2f} and P_need={p_need:.2f}"
        elif b <= -3.0:
            action = "demote"
            reason = f"Low activation B={b:.2f}"
        else:
            action = "update"
            reason = f"Stable activation B={b:.2f}"
    elif row.get("status") == "labile":
        action = "narrow"
        reason = "Labile memory requires narrowing or curation"
    elif row.get("status") in ("archived", "superseded"):
        action = "archive"
        reason = f"Status is {row.get('status')}"
    else:
        action = "update"
        reason = "Default update"

    dec_id = decisions.record(
        home_p,
        kind="reconsolidation",
        session_id=session_id or f"recon-{memory_id}",
        task_id=task_id or f"task-recon-{memory_id}",
        chosen={"action": action, "memory_id": memory_id, "heat": row.get("heat")},
        alternatives=[{"action": a} for a in RECONSOLIDATION_ACTIONS if a != action],
        propensity=1.0,
        randomized=False,
        policy_version="v7.2",
        stage="SHADOW",
        inputs={
            "memory_id": memory_id,
            "b": b,
            "p_need": p_need,
            "contradiction_count": total_contradictions,
            "status": row.get("status"),
            "heat": row.get("heat"),
        },
    )
    return {
        "memory_id": memory_id,
        "action": action,
        "b": b,
        "p_need": p_need,
        "contradiction_count": total_contradictions,
        "reason": reason,
        "decision_ref": dec_id,
        "heat": row.get("heat"),
        "status": row.get("status"),
    }


def demote_memory(
    home: Path | str,
    memory_id: str,
    *,
    target_heat: str | None = None,
    reason: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    home_p = Path(home)
    row = _memory_row(home_p, memory_id)
    if _protected(row):
        raise BrainError(f"Memory {memory_id} is protected and cannot be demoted")
    current_heat = row.get("heat") or "WARM"

    if target_heat is None:
        if current_heat == "HOT":
            target_heat = "WARM"
        else:
            target_heat = "COLD"

    updated = apply_heat(home_p, memory_id, target_heat)
    dec_id = decisions.record(
        home_p,
        kind="reconsolidation",
        session_id=session_id or f"demote-{memory_id}",
        task_id=task_id or f"task-demote-{memory_id}",
        chosen={
            "action": "demote",
            "memory_id": memory_id,
            "heat_before": current_heat,
            "heat_after": target_heat,
        },
        alternatives=[{"heat": h} for h in HEAT_STATES if h != target_heat],
        propensity=1.0,
        randomized=False,
        policy_version="v7.2",
        stage="SHADOW",
        inputs={
            "memory_id": memory_id,
            "heat_before": current_heat,
            "reason": reason or "explicit demotion",
        },
    )
    return updated


def propose_plan(
    home: Path | str,
    action: str,
    memory_id: str,
    *,
    new_title: str | None = None,
    new_body: str | None = None,
    change_note: str | None = None,
    new_sources: list[dict] | None = None,
    target_heat: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    home_p = Path(home)
    _ensure_migrated(home_p)
    if action not in RECONSOLIDATION_ACTIONS:
        raise BrainError(f"action must be one of {', '.join(RECONSOLIDATION_ACTIONS)}")
    row = _memory_row(home_p, memory_id)
    if action == "supersede" and (not isinstance(new_body, str) or not new_body.strip()):
        raise BrainError("new_body must be a non-empty string for supersede plan")

    show = semantic.show_memory(home_p, memory_id)
    current_body = show["body"]

    before_state = {
        "memory_id": memory_id,
        "current_version": row["current_version"],
        "title": row["title"],
        "body_path": row["body_path"],
        "status": row["status"],
        "evidence_grade": row["evidence_grade"],
        "heat": row.get("heat") or "WARM",
        "body": current_body,
    }

    identity_str = f"{memory_id}:{action}:{row['current_version']}:{new_title}:{new_body}:{target_heat}"
    plan_id = "plan-" + hashlib.sha256(identity_str.encode("utf-8")).hexdigest()[:24]

    parameters = {
        "new_title": new_title,
        "new_body": new_body,
        "change_note": change_note or f"Automatic {action} proposal",
        "new_sources": new_sources,
        "target_heat": target_heat,
    }

    plan = {
        "plan_id": plan_id,
        "action": action,
        "memory_id": memory_id,
        "rollout_stage": "SHADOW",
        "status": "planned",
        "parameters": parameters,
        "before_state": before_state,
        "created_at": _utcnow(),
    }

    dec_id = decisions.record(
        home_p,
        kind="reconsolidation",
        session_id=session_id or f"plan-{plan_id}",
        task_id=task_id or f"task-plan-{plan_id}",
        chosen={"plan_id": plan_id, "action": action, "memory_id": memory_id},
        alternatives=[{"action": "no_op"}],
        propensity=1.0,
        randomized=False,
        policy_version="v7.2",
        stage="SHADOW",
        inputs={
            "plan_id": plan_id,
            "action": action,
            "target_memory_id": memory_id,
            "before_version": row["current_version"],
        },
    )
    plan["decision_ref"] = dec_id
    return plan


def apply_plan(
    home: Path | str,
    plan: dict[str, Any],
    *,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    home_p = Path(home)
    if plan.get("status") != "planned":
        raise BrainError(f"Cannot apply plan with status {plan.get('status')!r}")
    action = plan["action"]
    memory_id = plan["memory_id"]
    params = plan["parameters"]

    if action == "supersede":
        new_version = semantic.supersede(
            home_p,
            memory_id,
            new_title=params.get("new_title"),
            new_body=params["new_body"],
            change_note=params.get("change_note") or "Applied reconsolidation plan",
            new_sources=params.get("new_sources"),
        )
        applied_result = {"new_version": new_version}
    elif action == "demote":
        res = demote_memory(home_p, memory_id, target_heat=params.get("target_heat"), session_id=session_id)
        applied_result = {"heat": res.get("heat")}
    elif action == "strengthen":
        conn = db.connect(_dbfile(home_p))
        try:
            conn.execute(
                "UPDATE memories SET storage_strength = storage_strength + 0.1 WHERE memory_id = ?",
                (memory_id,),
            )
            conn.commit()
        finally:
            conn.close()
        applied_result = {"storage_strength_incremented": True}
    else:
        applied_result = {"action": action, "applied": True}

    updated = dict(plan)
    updated["status"] = "applied"
    updated["applied_at"] = _utcnow()
    updated["applied_result"] = applied_result

    decisions.record(
        home_p,
        kind="reconsolidation",
        session_id=session_id or f"apply-{plan['plan_id']}",
        task_id=task_id or f"task-apply-{plan['plan_id']}",
        chosen={"plan_id": plan["plan_id"], "action": action, "status": "applied"},
        alternatives=[],
        propensity=1.0,
        randomized=False,
        policy_version="v7.2",
        stage="SHADOW",
        inputs={"plan_id": plan["plan_id"], "applied_result": applied_result},
    )
    return updated

def revert_plan(
    home: Path | str,
    plan: dict[str, Any],
    *,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    home_p = Path(home)
    if plan.get("status") != "applied":
        raise BrainError(f"Cannot revert plan with status {plan.get('status')!r}")
    action = plan["action"]
    memory_id = plan["memory_id"]
    before = plan["before_state"]

    if action == "supersede":
        revert_supersede(
            home_p,
            memory_id,
            target_version=before["current_version"],
            session_id=session_id,
        )
    elif action == "demote":
        apply_heat(home_p, memory_id, before.get("heat") or "WARM")

    updated = dict(plan)
    updated["status"] = "reverted"
    updated["reverted_at"] = _utcnow()

    decisions.record(
        home_p,
        kind="reconsolidation",
        session_id=session_id or f"revert-{plan['plan_id']}",
        task_id=task_id or f"task-revert-{plan['plan_id']}",
        chosen={"plan_id": plan["plan_id"], "action": action, "status": "reverted"},
        alternatives=[],
        propensity=1.0,
        randomized=False,
        policy_version="v7.2",
        stage="SHADOW",
        inputs={
            "plan_id": plan["plan_id"],
            "reverted_to_version": before.get("current_version"),
        },
    )
    return updated

def revert_supersede(
    home: Path | str,
    memory_id: str,
    *,
    target_version: int | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> int:
    home_p = Path(home)
    _ensure_migrated(home_p)
    row = _memory_row(home_p, memory_id)
    current_v = int(row["current_version"])
    if current_v <= 1:
        raise BrainError(f"Cannot revert memory {memory_id}: already at version {current_v}")
    target_v = target_version if target_version is not None else current_v - 1

    conn = db.connect(_dbfile(home_p))
    try:
        conn.execute("BEGIN IMMEDIATE")
        target_row = conn.execute(
            "SELECT * FROM memory_versions WHERE memory_id = ? AND version = ?",
            (memory_id, target_v),
        ).fetchone()
        if target_row is None:
            raise BrainError(
                f"Target version {target_v} not found in memory_versions for {memory_id}"
            )

        now = _utcnow()
        # Save current version record in memory_versions before switching
        conn.execute(
            "INSERT OR REPLACE INTO memory_versions "
            "(memory_id, version, created_at, title, body_path, change_note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                current_v,
                row.get("updated_at") or now,
                row["title"],
                row["body_path"],
                f"Reverted to version {target_v}",
            ),
        )

        # Remove target_v from memory_versions as it becomes active in memories
        conn.execute(
            "DELETE FROM memory_versions WHERE memory_id = ? AND version = ?",
            (memory_id, target_v),
        )

        # Update memories table to point back to target_version
        conn.execute(
            "UPDATE memories SET current_version = ?, title = ?, body_path = ?, updated_at = ? "
            "WHERE memory_id = ?",
            (
                target_v,
                target_row["title"],
                target_row["body_path"],
                now,
                memory_id,
            ),
        )
        db.bump_memory_epoch(conn)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not revert supersede for {memory_id}: {exc}") from exc
    finally:
        conn.close()

    target_path = home_p / target_row["body_path"]
    semantic._sync_file_metadata(
        home_p,
        target_path,
        grade=row.get("evidence_grade"),
        status=row.get("status"),
    )
    semantic._safe_index(home_p, memory_id)

    decisions.record(
        home_p,
        kind="reconsolidation",
        session_id=session_id or f"revert-{memory_id}-v{target_v}",
        task_id=task_id or f"task-revert-{memory_id}-v{target_v}",
        chosen={
            "action": "revert_supersede",
            "memory_id": memory_id,
            "reverted_to_version": target_v,
        },
        alternatives=[],
        propensity=1.0,
        randomized=False,
        policy_version="v7.2",
        stage="SHADOW",
        inputs={
            "memory_id": memory_id,
            "from_version": current_v,
            "to_version": target_v,
        },
    )
    return target_v
