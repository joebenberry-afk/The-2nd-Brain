"""Policy promotion — shadow -> candidate -> active with ALL guards (plan §119, Phase 23).

Upward adjacent promotion requires: G1 evidence (>= 1 credit_event for the
skill OR >= 1 model_skill_outcome), G2 a frontier approve review for
``skill-<name>-promotion``, and G3 no immune rollback record for
``skill-<name>``. Skip-level moves, same-level no-ops, level mismatches, and
destination conflicts are refused. Demotion (active -> anything, or via
:func:`demote`) needs no guards but ALWAYS writes a promotion record under
``state/promotions/``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import frontier, immune
from .errors import BrainError

LEVELS: tuple[str, ...] = ("shadow", "candidate", "active")
LEVEL_RANK = {"shadow": 0, "candidate": 1, "active": 2}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _skills_dir(home: Path) -> Path:
    return Path(home) / "skills"


def _promotions_dir(home: Path) -> Path:
    return Path(home) / "state" / "promotions"


def _level_of(home: Path, skill_name: str) -> str | None:
    for level in LEVELS:
        if (_skills_dir(home) / level / skill_name).is_dir():
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


def _evidence_counts(home: Path, skill_name: str) -> dict:
    return {
        "credit_events": _count(home, "credit_events", "subject_id", skill_name),
        "model_skill_outcomes": _count(home, "model_skill_outcomes", "skill_name", skill_name),
    }


def _frontier_verdict(home: Path, skill_name: str) -> str | None:
    return frontier.frontier_status(home, f"skill-{skill_name}-promotion").get("latest_verdict")


def _guard_checks(home: Path, skill_name: str) -> tuple[dict, dict]:
    evidence = _evidence_counts(home, skill_name)
    has_evidence = evidence["credit_events"] >= 1 or evidence["model_skill_outcomes"] >= 1
    verdict = _frontier_verdict(home, skill_name)
    frontier_ok = verdict == "approve"
    rolled_back = any(
        record.get("policy_id") == f"skill-{skill_name}" for record in immune.rollback_log(home)
    )
    guards = {
        "evidence": has_evidence,
        "frontier_approved": frontier_ok,
        "immune_clear": not rolled_back,
    }
    details = {
        "evidence_counts": evidence,
        "frontier_verdict": verdict,
        "rolled_back": rolled_back,
    }
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
    source = _skills_dir(home) / from_level / skill_name
    target = _skills_dir(home) / to_level / skill_name
    if not source.is_dir():
        raise BrainError(f"No skill {skill_name!r} under skills/{from_level}/")
    if target.exists():
        raise BrainError(f"Destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)  # atomic within the Brain home
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
    if not isinstance(skill_name, str) or not skill_name.strip():
        raise BrainError("skill_name must be a non-empty string")
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
        "evidence_counts": {"credit_events": 0, "model_skill_outcomes": 0},
        "frontier_verdict": None,
        "rolled_back": False,
    }
    if not demotion:
        guards, details = _guard_checks(home, skill_name)
        if not guards["evidence"]:
            return {"promoted": False, "reason": "no_evidence", **details}
        if not guards["frontier_approved"]:
            return {"promoted": False, "reason": "frontier_not_approved", **details}
        if guards["immune_clear"] is False:
            return {"promoted": False, "reason": "rolled_back", **details}

    try:
        target = _move_skill(home, skill_name, from_level, to_level)
    except BrainError as exc:
        return (
            {"promoted": False, "reason": "destination_exists", "detail": str(exc)}
            if "already exists" in str(exc)
            else {"promoted": False, "reason": "move_failed", "detail": str(exc)}
        )

    record = {
        "skill_name": skill_name,
        "from_level": from_level,
        "to_level": to_level,
        "ts": _utcnow(),
        "session_id": session_id,
        "guards": guards,
        "frontier_verdict": details["frontier_verdict"],
        "evidence_counts": details["evidence_counts"],
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
        "evidence_counts": {"credit_events": 0, "model_skill_outcomes": 0},
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
        directory = _skills_dir(home) / level
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
    return (_skills_dir(home) / "active" / skill_name).is_dir()
