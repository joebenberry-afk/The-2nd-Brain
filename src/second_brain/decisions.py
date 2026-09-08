"""Deterministic policy decisions and durable outcomes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts, db
from .errors import BrainError

_ROLLOUT_STAGES = frozenset({"OFF", "SHADOW", "ADVISORY", "CANARY", "ACTIVE"})
_DECISION_KINDS = frozenset(
    {
        "retrieval",
        "routing",
        "eviction",
        "budget",
        "verification",
        "admission",
        "reread",
        "reconsolidation",
        "brainstem",
        "learning",
        "frontier",
    }
)
_FORBIDDEN_METADATA_FIELDS = frozenset(
    {
        "prompt",
        "payload",
        "secret",
        "content",
        "text",
        "query",
        "input",
        "output",
        "body",
        "message",
        "token",
        "thought",
        "reasoning",
    }
)
MAX_METADATA_TEXT_CHARS = 512
_MAX_METADATA_DEPTH = 4
_MAX_METADATA_KEYS = 32
_MAX_METADATA_ITEMS = 16
_MAX_METADATA_BYTES = 4096


def _dbfile(home: Path | str) -> Path:
    return db.db_path(Path(home))


def _ensure_migrated(home: Path | str) -> None:
    dbfile = _dbfile(home)
    if db.pending_migrations(dbfile):
        db.migrate(dbfile)


def _canonical(value: Any, name: str) -> str:
    try:
        return contracts.canonical_json(value)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BrainError(f"{name} must be JSON-serializable") from exc


def _validate_metadata(value: Any, name: str, depth: int = 0) -> None:
    if depth > _MAX_METADATA_DEPTH:
        raise BrainError(f"{name} exceeds metadata nesting bound")
    if isinstance(value, dict):
        if len(value) > _MAX_METADATA_KEYS:
            raise BrainError(f"{name} exceeds metadata key bound")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise BrainError(f"{name} has an invalid metadata key")
            if key.casefold() in _FORBIDDEN_METADATA_FIELDS:
                raise BrainError(f"{name} contains forbidden metadata field {key!r}")
            _validate_metadata(item, name, depth + 1)
    elif isinstance(value, (list, tuple)):
        if len(value) > _MAX_METADATA_ITEMS:
            raise BrainError(f"{name} exceeds metadata item bound")
        for item in value:
            _validate_metadata(item, name, depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_METADATA_TEXT_CHARS:
            raise BrainError(f"{name} exceeds metadata text bound")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise BrainError(f"{name} contains a non-finite number")
    elif not isinstance(value, (int, bool, type(None))):
        raise BrainError(f"{name} must contain metadata-safe JSON values")


def _metadata_json(value: Any, name: str) -> str:
    _validate_metadata(value, name)
    serialized = _canonical(value, name)
    if len(serialized.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise BrainError(f"{name} exceeds metadata byte bound")
    return serialized


def _text(value: Any, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise BrainError(f"{name} must be a string")
    return value


def _propensity(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrainError("propensity must be a number between 0 and 1")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise BrainError("propensity must be a number between 0 and 1")
    return result


def _reward(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrainError("reward must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise BrainError("reward must be a finite number")
    return result


def record(
    home: Path | str,
    *,
    kind: str,
    session_id: str | None,
    task_id: str | None,
    chosen: Any,
    alternatives: Any,
    propensity: float,
    randomized: bool,
    policy_version: str,
    stage: str,
    inputs: Any,
) -> str:
    """Record a policy choice, returning its deterministic identity.

    Re-recording the same decision is a no-op: the first stored decision and
    its eventual caller-supplied outcome remain intact.
    """
    kind = _text(kind, "kind") or ""
    if kind not in _DECISION_KINDS:
        raise BrainError(f"kind must be one of {sorted(_DECISION_KINDS)}")
    session_id = _text(session_id, "session_id")
    if not session_id:
        raise BrainError("session_id must be non-empty")
    task_id = _text(task_id, "task_id", nullable=True)
    if task_id == "":
        raise BrainError("task_id must be non-empty when provided")
    policy_version = _text(policy_version, "policy_version") or ""
    if not policy_version:
        raise BrainError("policy_version must be non-empty")
    stage = _text(stage, "stage") or ""
    if stage not in _ROLLOUT_STAGES:
        raise BrainError(f"stage must be one of {sorted(_ROLLOUT_STAGES)}")
    if not isinstance(randomized, bool):
        raise BrainError("randomized must be a boolean")
    propensity = _propensity(propensity)
    chosen_json = _metadata_json(chosen, "chosen")
    alternatives_json = _metadata_json(alternatives, "alternatives")
    inputs_json = _canonical(inputs, "inputs")
    if len(inputs_json.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise BrainError("inputs exceeds metadata byte bound")
    inputs_hash = contracts.stable_content_hash(inputs)
    decision_id = hashlib.sha256((inputs_json + session_id + kind).encode("utf-8")).hexdigest()[:24]

    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            """INSERT OR IGNORE INTO decisions(
                decision_id, session_id, task_id, kind, chosen_json,
                alternatives_json, propensity, randomized, policy_version,
                rollout_stage, inputs_hash, inputs_json, outcome_json, reward, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
            (
                decision_id,
                session_id,
                task_id,
                kind,
                chosen_json,
                alternatives_json,
                propensity,
                1 if randomized else 0,
                policy_version,
                stage,
                inputs_hash,
                inputs_json,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if isinstance(exc, BrainError):
            raise
        raise BrainError(f"Could not record decision: {exc}") from exc
    finally:
        conn.close()
    return decision_id


def set_outcome(
    home: Path | str,
    decision_id: str,
    outcome: dict[str, Any],
    reward: float | None,
) -> None:
    """Persist the caller-supplied outcome and optional reward for a decision."""
    decision_id = _text(decision_id, "decision_id") or ""
    if not decision_id:
        raise BrainError("decision_id must be non-empty")
    if not isinstance(outcome, dict):
        raise BrainError("outcome must be a dict")
    outcome_json = _metadata_json(outcome, "outcome")
    if reward is not None:
        reward = _reward(reward)

    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        cursor = conn.execute(
            "UPDATE decisions SET outcome_json = ?, reward = ? WHERE decision_id = ?",
            (outcome_json, reward, decision_id),
        )
        if cursor.rowcount != 1:
            raise BrainError(f"Unknown decision_id {decision_id!r}")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if isinstance(exc, BrainError):
            raise
        raise BrainError(f"Could not set decision outcome: {exc}") from exc
    finally:
        conn.close()


record_outcome = set_outcome


def randomize(
    policy_choice: Any,
    alternatives: Sequence[Any],
    epsilon: float,
    rng_seed: Any = None,
) -> tuple[Any, float, bool]:
    """Epsilon-randomize a policy choice with its exact action propensity."""
    if (
        isinstance(policy_choice, Path)
        or (
            isinstance(policy_choice, str)
            and (
                os.path.sep in policy_choice
                or "/" in policy_choice
                or policy_choice.endswith(".sqlite")
            )
        )
    ) and (
        isinstance(alternatives, Sequence) and alternatives and policy_choice not in alternatives
    ):
        policy_choice = alternatives[0]
    if isinstance(alternatives, (str, bytes)) or not isinstance(alternatives, Sequence):
        raise BrainError("alternatives must be a non-empty sequence")
    if not alternatives:
        raise BrainError("alternatives must be a non-empty sequence")
    for index, candidate in enumerate(alternatives):
        if any(candidate == prior for prior in alternatives[:index]):
            raise BrainError("alternatives must not contain duplicate choices")
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise BrainError("epsilon must be a number between 0 and 1")
    epsilon = float(epsilon)
    if not math.isfinite(epsilon) or not 0.0 <= epsilon <= 1.0:
        raise BrainError("epsilon must be a number between 0 and 1")

    n = len(alternatives)
    rng = random.Random(rng_seed)
    randomized = rng.random() < epsilon
    choice = rng.choice(alternatives) if randomized else policy_choice
    alternative_propensity = epsilon / n
    propensity = (
        1.0 - epsilon + alternative_propensity
        if choice == policy_choice and policy_choice in alternatives
        else alternative_propensity
        if randomized
        else 1.0 - epsilon
    )
    return choice, propensity, randomized


def list_decisions(
    home: Path | str,
    *,
    kind: str | None = None,
    session_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Query decisions table, parsing JSON fields into Python objects."""
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home), readonly=True)
    try:
        sql = "SELECT * FROM decisions WHERE 1=1"
        params: list[Any] = []
        if kind is not None:
            kind_str = _text(kind, "kind") or ""
            if kind_str not in _DECISION_KINDS:
                raise BrainError(f"kind must be one of {sorted(_DECISION_KINDS)}")
            sql += " AND kind = ?"
            params.append(kind_str)
        if session_id is not None:
            sess_str = _text(session_id, "session_id")
            sql += " AND session_id = ?"
            params.append(sess_str)
        sql += " ORDER BY created_at ASC, rowid ASC"
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise BrainError("limit must be a positive integer")
            sql += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            row_dict = dict(row)
            for key, json_key in (
                ("chosen", "chosen_json"),
                ("alternatives", "alternatives_json"),
                ("inputs", "inputs_json"),
                ("outcome", "outcome_json"),
            ):
                raw = row_dict.get(json_key)
                if raw is not None:
                    try:
                        row_dict[key] = json.loads(raw)
                    except Exception:
                        row_dict[key] = raw
                else:
                    row_dict[key] = [] if key == "alternatives" else None

            if "randomized" in row_dict:
                row_dict["randomized"] = bool(row_dict["randomized"])
            if "propensity" in row_dict and row_dict["propensity"] is not None:
                row_dict["propensity"] = float(row_dict["propensity"])
            if "reward" in row_dict and row_dict["reward"] is not None:
                row_dict["reward"] = float(row_dict["reward"])

            results.append(row_dict)
        return results
    finally:
        conn.close()
