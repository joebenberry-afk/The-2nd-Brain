"""Policy promotion — shadow -> candidate -> active with ALL guards (plan §119, Phase 23).

Upward adjacent promotion requires: G1 evidence (>= 1 DIRECT or CONTRIBUTORY
credit_event for the skill), G2 a frontier approve review for
``skill-<name>-promotion``, and G3 no immune rollback record for
``skill-<name>``. Skip-level moves, same-level no-ops, level mismatches, and
destination conflicts are refused. Demotion (active -> anything, or via
:func:`demote`) needs no guards but ALWAYS writes a promotion record under
``state/promotions/``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import contracts, db, decisions, frontier, immune, paths, skillforge
from .errors import BrainError
from .security.identifiers import validate_skill_name

LEVELS: tuple[str, ...] = ("shadow", "candidate", "active")
LEVEL_RANK = {"shadow": 0, "candidate": 1, "active": 2}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _skills_dir(home: Path) -> Path:
    return Path(home) / "skills"


def _skill_dir(home: Path, level: str) -> Path:
    return Path(home) / paths.SKILL_LEVEL_DIRS[level]


def _promotions_dir(home: Path) -> Path:
    return Path(home) / "state" / "promotions"


def _level_of(home: Path, skill_name: str) -> str | None:
    for level in LEVELS:
        if (_skill_dir(home, level) / skill_name).is_dir():
            return level
    return None


def _count(home: Path, table: str, column: str, value: str) -> int:
    """Row count for one column equality; a missing table counts as zero."""
    import sqlite3 as _sqlite3

    from . import db

    conn = db.connect(db.db_path(home))
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()
        return int(row["n"])
    except _sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return 0
        raise
    finally:
        conn.close()

def _causal_credit_count(home: Path, skill_name: str) -> int:
    conn = db.connect(db.db_path(home))
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM credit_events "
            "WHERE subject_id = ? AND LOWER(credit_level) IN ('direct', 'contributory')",
            (skill_name,),
        ).fetchone()
        return int(row["n"]) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()



def _evidence_counts(home: Path, skill_name: str) -> dict:
    return {
        "credit_events": _count(home, "credit_events", "subject_id", skill_name),
        "causal_credit_events": _causal_credit_count(home, skill_name),
        "model_skill_outcomes": _count(home, "model_skill_outcomes", "skill_name", skill_name),
    }


def _frontier_verdict(home: Path, skill_name: str) -> str | None:
    return frontier.frontier_status(home, f"skill-{skill_name}-promotion").get("latest_verdict")


def _frontier_binding_current(home: Path, skill_name: str) -> bool:
    review = frontier.latest_review(home, f"skill-{skill_name}-promotion")
    if review is None or review.get("verdict") != "approve":
        return False
    binding = skillforge.artifact_binding(home, skill_name)
    return all(review.get(key) == value for key, value in binding.items())


def _last_active_version(home: Path, skill_name: str) -> int | None:
    """The version most recently promoted to active for this skill, or
    None if it has never been active. Only active-bound versions constrain
    future promotions; lifecycle moves toward active for a brand-new
    candidate need not bump a version that has no prior release."""
    records = [
        r
        for r in _read_records(home, skill_name)
        if r.get("to_level") == "active" and isinstance(r.get("resulting_version"), int)
    ]
    if not records:
        return None
    records.sort(key=lambda r: r.get("ts", ""))
    return records[-1]["resulting_version"]


def _version_check(home: Path, skill_name: str) -> tuple[bool, str | None, int | None]:
    """§119 version gate: the artifact must carry a valid positive integer
    version, and it must strictly exceed any version this skill previously
    reached active with."""
    binding_artifact = skillforge.artifact_binding(home, skill_name)
    raw = binding_artifact.get("artifact_version", "unversioned")
    if raw == "unversioned":
        return False, "version_missing", None
    try:
        candidate_version = int(raw)
    except (TypeError, ValueError):
        return False, "version_invalid", None
    if candidate_version < 1:
        return False, "version_invalid", None
    previous = _last_active_version(home, skill_name)
    if previous is not None and candidate_version <= previous:
        return False, "version_not_incremented", candidate_version
    return True, None, candidate_version


def _guard_checks(home: Path, skill_name: str) -> tuple[dict, dict]:
    evidence = _evidence_counts(home, skill_name)
    has_evidence = _causal_credit_count(home, skill_name) >= 1
    verdict = _frontier_verdict(home, skill_name)
    rolled_back = any(
        record.get("policy_id") == f"skill-{skill_name}" for record in immune.rollback_log(home)
    )
    guards = {
        "evidence": has_evidence,
        "frontier_approved": verdict == "approve",
        "immune_clear": not rolled_back,
        "frontier_binding_current": _frontier_binding_current(home, skill_name),
    }
    details = {
        "evidence_counts": evidence,
        "frontier_verdict": verdict,
        "rolled_back": rolled_back,
        "frontier_binding_current": guards["frontier_binding_current"],
    }
    binding = skillforge.candidate_binding(home, skill_name)
    guards["bound"] = binding is not None
    if binding is not None:
        # §119 baseline-vs-candidate comparison: universal for every bound
        # candidate source (Radar, frontier-evidence, or otherwise), not
        # only Skill-Forge-originated ones.
        candidate_path = skillforge.skill_path(home, skill_name)
        if candidate_path is None:
            raise BrainError(f"No skill {skill_name!r} found under lifecycle directories")
        current_hash = skillforge.lifecycle_content_hash(candidate_path)
        evaluation_path = candidate_path.parent / "evaluation.json"
        try:
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            evaluation = {}
        evaluation_current = (
            binding.get("evaluation_state") == "passed"
            and binding.get("candidate_content_sha256") == current_hash
            and evaluation.get("status") == "passed"
            and evaluation.get("candidate_content_sha256") == current_hash
        )
        guards["evaluation"] = evaluation_current
        details["evaluation_state"] = binding.get("evaluation_state")
        details["evaluation_stale"] = (
            binding.get("evaluation_state") == "passed" and not evaluation_current
        )
        # §119 owner: explicit, bounded, persisted with the binding.
        owner = str(binding.get("owner") or "").strip()
        guards["owner"] = bool(owner)
        details["owner"] = owner or None
        details["candidate_id"] = binding.get("candidate_id")
    version_ok, version_issue, candidate_version = _version_check(home, skill_name)
    guards["version"] = version_ok
    details["version"] = candidate_version
    details["version_issue"] = version_issue
    return guards, details


def _write_record(home: Path, record: dict) -> Path:
    directory = _promotions_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    counter = 1
    while True:
        target = directory / f"{record['skill_name']}-{counter}.json"
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            counter += 1
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise BrainError(f"Could not write promotion record {target}: {exc}") from exc
    return target


def _move_skill(home: Path, skill_name: str, from_level: str, to_level: str) -> Path:
    # SEC-03: skill names reach filesystem moves; only validated identifiers.
    skill_name = validate_skill_name(skill_name)
    source = _skill_dir(home, from_level) / skill_name
    target = _skill_dir(home, to_level) / skill_name
    if not source.is_dir():
        raise BrainError(f"No skill {skill_name!r} under skills/{from_level}/")
    if target.exists():
        raise BrainError(f"Destination already exists: {target}")
    skill_file = source / "SKILL.md"
    old_status = skillforge.read_metadata(skill_file).get("status") if skill_file.exists() else None
    if skill_file.exists():
        skillforge.set_status(skill_file, to_level)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.rename(target)  # atomic within the Brain home
    except OSError as exc:
        if skill_file.exists() and old_status:
            skillforge.set_status(skill_file, old_status)
        raise BrainError(f"Could not move skill {skill_name!r}: {exc}") from exc
    return target


def _validate_levels(from_level: str, to_level: str) -> None:
    for name, value in (("from_level", from_level), ("to_level", to_level)):
        if value not in LEVELS:
            raise BrainError(f"{name} must be one of {', '.join(LEVELS)}")


def promote(
    home: Path,
    skill_name: str,
    from_level: str,
    to_level: str,
    session_id: str = "",
) -> dict:
    """Promote (or demote) a skill with all guards. Refusals return
    {promoted: False, reason}; never mutates on refusal."""
    skill_name = validate_skill_name(skill_name)
    if not isinstance(session_id, str):
        raise BrainError("session_id must be a string")
    _validate_levels(from_level, to_level)
    actual = _level_of(home, skill_name)
    if actual is None:
        raise BrainError(f"No skill {skill_name!r} found under skills/")
    if actual != from_level:
        return {"promoted": False, "reason": "level_mismatch", "actual_level": actual}
    if to_level == from_level:
        return {"promoted": False, "reason": "already_at_level", "level": from_level}
    if LEVEL_RANK[to_level] > LEVEL_RANK[from_level] + 1:
        return {"promoted": False, "reason": "skip_level"}

    demotion = LEVEL_RANK[to_level] < LEVEL_RANK[from_level]
    guards = None
    details = {
        "evidence_counts": {"credit_events": 0, "causal_credit_events": 0, "model_skill_outcomes": 0},
        "frontier_verdict": None,
        "rolled_back": False,
    }
    if not demotion:
        guards, details = _guard_checks(home, skill_name)
        if guards.get("evaluation") is False:
            reason = (
                "evaluation_stale" if details.get("evaluation_stale") else "evaluation_not_proven"
            )
            return {"promoted": False, "reason": reason, **details}
        if not guards["evidence"]:
            return {"promoted": False, "reason": "no_evidence", **details}
        if not guards["frontier_approved"]:
            return {"promoted": False, "reason": "frontier_not_approved", **details}
        if not guards["frontier_binding_current"]:
            return {"promoted": False, "reason": "frontier_stale", **details}
        if guards["immune_clear"] is False:
            return {"promoted": False, "reason": "rolled_back", **details}
        if not guards["bound"]:
            return {"promoted": False, "reason": "no_promotion_binding", **details}
        if not guards.get("owner", False):
            return {"promoted": False, "reason": "no_owner", **details}
        if not guards["version"]:
            return {
                "promoted": False,
                "reason": details.get("version_issue") or "version_invalid",
                **details,
            }

        if to_level == "active":
            ready = skillforge.validate_execution_ready(
                _skill_dir(home, from_level) / skill_name / "SKILL.md"
            )
            if not ready["ok"]:
                return {
                    "promoted": False,
                    "reason": "execution_not_ready",
                    "validation": ready,
                    **details,
                }

    try:
        target = _move_skill(home, skill_name, from_level, to_level)
    except BrainError as exc:
        return (
            {"promoted": False, "reason": "destination_exists", "detail": str(exc)}
            if "already exists" in str(exc)
            else {"promoted": False, "reason": "move_failed", "detail": str(exc)}
        )

    ts = _utcnow()
    promotion_id = (
        "promotion-" + hashlib.sha256(f"{skill_name}|{ts}|{session_id}".encode()).hexdigest()[:16]
    )
    record = {
        "promotion_id": promotion_id,
        "skill_name": skill_name,
        "from_level": from_level,
        "to_level": to_level,
        "ts": ts,
        "session_id": session_id,
        "guards": guards,
        "frontier_verdict": details["frontier_verdict"],
        "evidence_counts": details["evidence_counts"],
        "owner": details.get("owner"),
        "candidate_id": details.get("candidate_id"),
        "baseline_comparison": details.get("evaluation_state"),
        "rollback_clear": not details.get("rolled_back", False),
        "resulting_version": details.get("version") if not demotion else None,
        "reason": "demoted-via-promote" if demotion else None,
    }
    record_path = _write_record(home, record)
    return {
        "promoted": True,
        "from_level": from_level,
        "to_level": to_level,
        "record": record,
        "record_path": str(record_path),
        "target": str(target),
    }


def demote(home: Path, skill_name: str, to_level: str, reason: str) -> dict:
    """Demote a skill to a lower level. No guards, but always records."""
    skill_name = validate_skill_name(skill_name)
    if not isinstance(reason, str) or not reason.strip():
        raise BrainError("reason must be a non-empty string")
    if to_level not in LEVELS:
        raise BrainError(f"to_level must be one of {', '.join(LEVELS)}")
    actual = _level_of(home, skill_name)
    if actual is None:
        raise BrainError(f"No skill {skill_name!r} found under skills/")
    if LEVEL_RANK[to_level] >= LEVEL_RANK[actual]:
        return {"demoted": False, "reason": "not_a_demote", "actual_level": actual}
    try:
        target = _move_skill(home, skill_name, actual, to_level)
    except BrainError as exc:
        return {"demoted": False, "reason": "destination_exists", "detail": str(exc)}
    record = {
        "skill_name": skill_name,
        "from_level": actual,
        "to_level": to_level,
        "ts": _utcnow(),
        "session_id": "",
        "guards": None,
        "frontier_verdict": None,
        "evidence_counts": {"credit_events": 0, "causal_credit_events": 0, "model_skill_outcomes": 0},
        "reason": reason,
    }
    record_path = _write_record(home, record)
    return {
        "demoted": True,
        "from_level": actual,
        "to_level": to_level,
        "record": record,
        "record_path": str(record_path),
        "target": str(target),
    }


def _read_records(home: Path, skill_name: str | None = None) -> list[dict]:
    directory = _promotions_dir(home)
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrainError(f"Corrupt promotion record {path}: {exc}") from exc
        if not isinstance(record, dict):
            raise BrainError(f"Corrupt promotion record {path}: not a JSON object")
        if skill_name is None or record.get("skill_name") == skill_name:
            records.append(record)
    records.sort(key=lambda r: (r.get("ts", ""), r.get("skill_name", "")))
    return records


def promotion_status(home: Path, skill_name: str | None = None) -> dict:
    """Current level per skill + promotion history records."""
    levels: dict[str, str] = {}
    for level in LEVELS:
        directory = _skill_dir(home, level)
        if directory.is_dir():
            for entry in sorted(directory.iterdir()):
                if entry.is_dir():
                    levels[entry.name] = level
    if skill_name is not None:
        return {
            "skill_name": skill_name,
            "level": levels.get(skill_name),
            "records": [r for r in _read_records(home, skill_name)],
        }
    return {"skills": levels, "records": _read_records(home)}


def is_active(home: Path, skill_name: str) -> bool:
    skill_name = validate_skill_name(skill_name)
    return (_skills_dir(home) / "active" / skill_name).is_dir()


ROLLOUT_STAGES: tuple[str, ...] = ("OFF", "SHADOW", "ADVISORY", "CANARY", "ACTIVE")
STAGE_RANKS: dict[str, int] = {
    "OFF": 0,
    "SHADOW": 1,
    "ADVISORY": 2,
    "CANARY": 3,
    "ACTIVE": 4,
}


def _ensure_v2_migrated(home: Path) -> None:
    dbfile = db.db_path(home)
    if db.pending_migrations(dbfile):
        db.migrate(dbfile)


def get_feature_stage(home: Path | str, feature: str) -> str:
    home_p = Path(home)
    _ensure_v2_migrated(home_p)
    conn = db.connect(db.db_path(home_p), readonly=True)
    try:
        row = conn.execute(
            "SELECT to_stage FROM v2_rollout_events WHERE feature = ? "
            "ORDER BY created_at DESC, event_id DESC LIMIT 1",
            (feature,),
        ).fetchone()
        if row is not None:
            return str(row["to_stage"])
    finally:
        conn.close()
    return "OFF"


def transition_rollout_stage(
    home: Path | str,
    feature: str,
    to_stage: str,
    *,
    reason: str,
    evidence_refs: list[str] | None = None,
    actor: str = "system",
    credit_class: str | None = None,
    verifier_passed: bool | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Transition a feature's rollout stage with strict invariant enforcement.

    Rule 1: Stages must progress adjacent: OFF -> SHADOW -> ADVISORY -> CANARY -> ACTIVE.
            Skipping stages (e.g. SHADOW -> ACTIVE) is strictly forbidden.
    Rule 2: Promotion to ACTIVE requires verified causal credit (DIRECT or CONTRIBUTORY)
            AND an independent verifier pass.
    Rule 3: Negative or regressed evidence refuses promotion and holds or demotes the candidate.
    Rule 4: Demotion and rollback write full audit records and preserve all history.
    """
    home_p = Path(home)
    _ensure_v2_migrated(home_p)

    target_stage = str(to_stage).strip().upper()
    if target_stage not in STAGE_RANKS:
        raise BrainError(f"Invalid rollout stage {to_stage!r}")

    current_stage = get_feature_stage(home_p, feature)
    current_rank = STAGE_RANKS[current_stage]
    target_rank = STAGE_RANKS[target_stage]

    # Check for negative / unsafe evidence refusing promotion
    if credit_class == "UNRELATED_NEGATIVE" and target_rank >= current_rank:
        demote_target = "SHADOW" if current_stage in ("CANARY", "ADVISORY") else "OFF"
        event_id = "event-" + hashlib.sha256(
            f"{feature}:{current_stage}:{demote_target}:{_utcnow()}".encode("utf-8")
        ).hexdigest()[:24]
        evidence_list = list(evidence_refs or []) + ["credit:UNRELATED_NEGATIVE"]
        now = _utcnow()

        conn = db.connect(db.db_path(home_p))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO v2_rollout_events(
                    event_id, feature, from_stage, to_stage, reason, evidence_refs_json, actor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    feature,
                    current_stage,
                    demote_target,
                    f"PROMOTION_REFUSED_NEGATIVE_EFFECT: {reason}",
                    contracts.canonical_json(evidence_list),
                    actor,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        decisions.record(
            home_p,
            kind="learning",
            session_id=session_id or f"rollout-{event_id}",
            task_id=task_id or f"task-{event_id}",
            chosen={
                "action": "demote_feature",
                "feature": feature,
                "from_stage": current_stage,
                "to_stage": demote_target,
            },
            alternatives=[{"action": "promote"}],
            propensity=1.0,
            randomized=False,
            policy_version="v7.9",
            stage=demote_target,
            inputs={
                "feature": feature,
                "credit_class": credit_class,
                "reason": reason,
            },
        )

        return {
            "event_id": event_id,
            "feature": feature,
            "from_stage": current_stage,
            "to_stage": demote_target,
            "status": "HELD",
            "promotion_refused": True,
            "reason": f"Promotion refused due to negative effect; candidate demoted to {demote_target}",
            "evidence_refs": evidence_list,
            "created_at": now,
        }

    # Check for skip-stage attempts when advancing
    if target_rank > current_rank:
        if target_rank > current_rank + 1:
            raise BrainError(
                f"Cannot skip rollout stages: attempted {current_stage} -> {target_stage}. "
                "Must advance sequentially (OFF -> SHADOW -> ADVISORY -> CANARY -> ACTIVE)."
            )

        # Rule 2: Promotion to ACTIVE requires credit and verifier pass
        if target_stage == "ACTIVE":
            if credit_class not in ("DIRECT", "CONTRIBUTORY"):
                raise BrainError(
                    f"Promotion to ACTIVE requires causal credit DIRECT or CONTRIBUTORY (got {credit_class!r})"
                )
            if verifier_passed is not True:
                raise BrainError(
                    "Promotion to ACTIVE requires an independent verifier pass (verifier_passed must be True)"
                )

    now = _utcnow()
    event_id = "event-" + hashlib.sha256(
        f"{feature}:{current_stage}:{target_stage}:{now}".encode("utf-8")
    ).hexdigest()[:24]
    evidence_list = list(evidence_refs or [])

    conn = db.connect(db.db_path(home_p))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO v2_rollout_events(
                event_id, feature, from_stage, to_stage, reason, evidence_refs_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                feature,
                current_stage,
                target_stage,
                reason,
                contracts.canonical_json(evidence_list),
                actor,
                now,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record rollout event: {exc}") from exc
    finally:
        conn.close()

    decisions.record(
        home_p,
        kind="learning",
        session_id=session_id or f"rollout-{event_id}",
        task_id=task_id or f"task-{event_id}",
        chosen={
            "action": "transition_stage",
            "feature": feature,
            "from_stage": current_stage,
            "to_stage": target_stage,
        },
        alternatives=[],
        propensity=1.0,
        randomized=False,
        policy_version="v7.9",
        stage=target_stage,
        inputs={
            "feature": feature,
            "credit_class": credit_class,
            "verifier_passed": verifier_passed,
            "reason": reason,
        },
    )

    return {
        "event_id": event_id,
        "feature": feature,
        "from_stage": current_stage,
        "to_stage": target_stage,
        "status": "PROMOTED"
        if target_rank > current_rank
        else ("DEMOTED" if target_rank < current_rank else "MAINTAINED"),
        "promotion_refused": False,
        "reason": reason,
        "evidence_refs": evidence_list,
        "created_at": now,
    }


def list_rollout_events(
    home: Path | str, feature: str | None = None
) -> list[dict[str, Any]]:
    home_p = Path(home)
    _ensure_v2_migrated(home_p)
    conn = db.connect(db.db_path(home_p), readonly=True)
    try:
        sql = "SELECT * FROM v2_rollout_events WHERE 1=1"
        params: list[Any] = []
        if feature is not None:
            sql += " AND feature = ?"
            params.append(feature)
        sql += " ORDER BY created_at ASC, event_id ASC"
        rows = conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["evidence_refs"] = json.loads(d["evidence_refs_json"])
            results.append(d)
        return results
    finally:
        conn.close()
