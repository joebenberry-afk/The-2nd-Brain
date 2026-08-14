"""Plasticity: shadow learning (plan §40-45, Phase 13 §109).

Records prediction events, raw outcome vectors, prediction errors, explicit
credit events and utility updates. No automatic policy enforcement and no
automatic credit: credit levels are always supplied by the caller (plan §43 —
task success must never auto-reward every active skill).

The acceptance criterion is deterministic replay: applying the same event
sequence to a fresh Brain always yields the same DB rows (modulo ids and
timestamps) and the same utility log lines.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .errors import BrainError

CREDIT_KINDS: tuple[str, ...] = ("skill", "memory", "policy", "tool", "scout", "verification")
CREDIT_LEVELS: tuple[str, ...] = ("direct", "contributory", "correlated", "unknown")
OUTCOME_VECTOR_FIELDS: tuple[str, ...] = (
    "verified_success",
    "first_pass_success",
    "intent_alignment",
    "regression",
    "user_correction",
    "revert",
    "token_cost",
    "latency",
    "tool_calls",
    "context_peak",
    "code_complexity",
    "dependency_delta",
    "environment_damage",
)

UTILITY_LOG = "utility.jsonl"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _insert_id(cursor: sqlite3.Cursor) -> int:
    lastrowid = cursor.lastrowid
    if lastrowid is None:
        raise BrainError("Insert did not return a row id")
    return int(lastrowid)


def _dbfile(home: Path) -> Path:
    return db.db_path(home)


def _ensure_migrated(home: Path) -> None:
    if db.pending_migrations(_dbfile(home)):
        db.migrate(_dbfile(home))


def _utility_path(home: Path) -> Path:
    return Path(home) / "plasticity" / UTILITY_LOG


def _check_real(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrainError(f"{name} must be a real number")
    return float(value)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def record_prediction(
    home: Path,
    session_id: str | None,
    state: str,
    expected_next_state: str,
    actual_next_state: str,
    kind: str,
) -> int:
    """Record one prediction event; prediction_error = 0 iff expected == actual."""
    for name, value in (
        ("state", state),
        ("expected_next_state", expected_next_state),
        ("actual_next_state", actual_next_state),
        ("kind", kind),
    ):
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"{name} must be a non-empty string")
    if session_id is not None and not isinstance(session_id, str):
        raise BrainError("session_id must be a string or None")
    _ensure_migrated(home)
    error = 0 if expected_next_state == actual_next_state else 1
    conn = db.connect(_dbfile(home))
    try:
        cursor = conn.execute(
            """INSERT INTO predictions
               (session_id, state, expected_next_state, actual_next_state,
                prediction_error, kind, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, state, expected_next_state, actual_next_state, error, kind, _utcnow()),
        )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record prediction: {exc}") from exc
    finally:
        conn.close()


def record_outcome(
    home: Path,
    session_id: str | None,
    vector: dict,
    task_id: str | None = None,
) -> int:
    """Record a raw outcome vector (plan §42). Partial vectors allowed;
    unknown keys rejected."""
    if not isinstance(vector, dict):
        raise BrainError("vector must be a dict")
    unknown = sorted(set(vector) - set(OUTCOME_VECTOR_FIELDS))
    if unknown:
        raise BrainError(f"Unknown outcome vector field(s): {', '.join(unknown)}")
    if session_id is not None and not isinstance(session_id, str):
        raise BrainError("session_id must be a string or None")
    if task_id is not None and not isinstance(task_id, str):
        raise BrainError("task_id must be a string or None")
    _ensure_migrated(home)
    vector_json = json.dumps(vector, sort_keys=True)
    conn = db.connect(_dbfile(home))
    try:
        cursor = conn.execute(
            "INSERT INTO outcomes (session_id, task_id, vector_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, task_id, vector_json, _utcnow()),
        )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record outcome: {exc}") from exc
    finally:
        conn.close()


def record_prediction_error(
    home: Path,
    prediction_id: int,
    kind: str,
    salience: float = 0.5,
    detail: str | None = None,
) -> int:
    """Attach a prediction-error training example to a prediction."""
    if not isinstance(prediction_id, int) or isinstance(prediction_id, bool) or prediction_id <= 0:
        raise BrainError("prediction_id must be a positive integer")
    if not isinstance(kind, str) or not kind.strip():
        raise BrainError("kind must be a non-empty string")
    salience_value = _check_real(salience, "salience")
    if detail is not None and not isinstance(detail, str):
        raise BrainError("detail must be a string or None")
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        exists = conn.execute(
            "SELECT 1 FROM predictions WHERE prediction_id = ?", (prediction_id,)
        ).fetchone()
        if exists is None:
            raise BrainError(f"Unknown prediction id {prediction_id}")
        cursor = conn.execute(
            "INSERT INTO prediction_errors (prediction_id, kind, salience, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (prediction_id, kind, salience_value, detail, _utcnow()),
        )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record prediction error: {exc}") from exc
    finally:
        conn.close()


def record_credit(
    home: Path,
    session_id: str | None,
    subject_id: str,
    subject_kind: str,
    credit_level: str,
) -> int:
    """Record an explicit credit event. The level is ALWAYS caller-supplied:
    there is no default and no auto-reward path (plan §43)."""
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise BrainError("subject_id must be a non-empty string")
    if subject_kind not in CREDIT_KINDS:
        raise BrainError(f"subject_kind must be one of {', '.join(CREDIT_KINDS)}")
    if credit_level not in CREDIT_LEVELS:
        raise BrainError(f"credit_level must be one of {', '.join(CREDIT_LEVELS)}")
    if session_id is not None and not isinstance(session_id, str):
        raise BrainError("session_id must be a string or None")
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        cursor = conn.execute(
            "INSERT INTO credit_events "
            "(session_id, subject_id, subject_kind, credit_level, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, subject_id, subject_kind, credit_level, _utcnow()),
        )
        conn.commit()
        return _insert_id(cursor)
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record credit event: {exc}") from exc
    finally:
        conn.close()


def hindsight_relabel(
    home: Path,
    session_id: str | None,
    predicted_bottleneck: str,
    actual_bottleneck: str,
) -> dict:
    """Plan §45: compare predicted vs actual bottleneck. Records a
    'bottleneck' prediction (error=1 when they differ) plus a prediction_error
    training example in the mismatch case."""
    for name, value in (
        ("predicted_bottleneck", predicted_bottleneck),
        ("actual_bottleneck", actual_bottleneck),
    ):
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"{name} must be a non-empty string")
    prediction_id = record_prediction(
        home,
        session_id,
        state=predicted_bottleneck,
        expected_next_state=actual_bottleneck,
        actual_next_state=actual_bottleneck,
        kind="bottleneck",
    )
    error = 0 if predicted_bottleneck == actual_bottleneck else 1
    error_id = None
    if error:
        error_id = record_prediction_error(
            home,
            prediction_id,
            kind="bottleneck-mismatch",
            salience=0.5,
            detail=f"predicted {predicted_bottleneck!r}, actual {actual_bottleneck!r}",
        )
    return {"prediction_id": prediction_id, "prediction_error_id": error_id, "error": error}


def utility_update(
    home: Path,
    subject_id: str,
    subject_kind: str,
    delta: float,
    evidence: str,
) -> dict:
    """Append one deterministic utility-update line (append-only JSONL; no
    aggregation in this phase — aggregation is Phase 14)."""
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise BrainError("subject_id must be a non-empty string")
    if subject_kind not in CREDIT_KINDS:
        raise BrainError(f"subject_kind must be one of {', '.join(CREDIT_KINDS)}")
    delta_value = _check_real(delta, "delta")
    if not isinstance(evidence, str) or not evidence.strip():
        raise BrainError("evidence must be a non-empty string")
    record = {
        "ts": _utcnow(),
        "subject_id": subject_id,
        "subject_kind": subject_kind,
        "delta": delta_value,
        "evidence": evidence,
    }
    path = _utility_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    try:
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
    except OSError as exc:
        raise BrainError(f"Could not append utility log {path}: {exc}") from exc
    return record


def read_utility_log(home: Path) -> list[dict]:
    """All utility lines in append order; a corrupt line raises BrainError
    naming the file and line."""
    path = _utility_path(home)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BrainError(f"Could not read utility log {path}: {exc}") from exc
    records = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BrainError(f"Corrupt utility log {path}:{lineno}: {exc}") from exc
        if not isinstance(record, dict):
            raise BrainError(f"Corrupt utility log {path}:{lineno}: not a JSON object")
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Replay (deterministic acceptance)
# ---------------------------------------------------------------------------


def _apply_event(home: Path, event: dict) -> object:
    op = event.get("op")
    args = {key: value for key, value in event.items() if key != "op"}
    try:
        if op == "prediction":
            return record_prediction(home, **args)
        if op == "outcome":
            return record_outcome(home, **args)
        if op == "prediction_error":
            return record_prediction_error(home, **args)
        if op == "credit":
            return record_credit(home, **args)
        if op == "hindsight":
            return hindsight_relabel(home, **args)
        if op == "utility":
            return utility_update(home, **args)
    except TypeError as exc:
        raise BrainError(f"Invalid arguments for replay op {op!r}: {exc}") from exc
    raise BrainError(f"Unknown replay op {op!r}")


def replay(home: Path, events: list[dict]) -> dict:
    """Apply an ordered list of {op, ...} events to `home` and return the ids
    each op produced. Deterministic: the same event list applied to two fresh
    Brains produces identical DB row contents and utility log lines."""
    if not isinstance(events, list):
        raise BrainError("events must be a list of {op, ...} dicts")
    produced: dict[str, list[object]] = {
        "predictions": [],
        "outcomes": [],
        "prediction_errors": [],
        "credits": [],
        "hindsight": [],
        "utilities": [],
    }
    for event in events:
        if not isinstance(event, dict):
            raise BrainError(f"Replay event must be a dict, got {type(event).__name__}")
        op = event.get("op")
        if not isinstance(op, str):
            raise BrainError(f"Replay event must have a string 'op', got {op!r}")
        result = _apply_event(home, event)  # raises BrainError for unknown ops
        bucket = {
            "prediction": "predictions",
            "outcome": "outcomes",
            "prediction_error": "prediction_errors",
            "credit": "credits",
            "hindsight": "hindsight",
            "utility": "utilities",
        }.get(op)
        if bucket is None:  # unreachable: _apply_event raises first
            raise BrainError(f"Unknown replay op {op!r}")
        produced[bucket].append(result)
    return produced
