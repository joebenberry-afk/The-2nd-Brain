"""Bounded lifecycle helpers for the existing Active State Capsule.

This module owns no new state. It only binds lifecycle inputs to the canonical
``working_set.py`` JSON capsule and returns integrity metadata for host bridges.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import working_set
from .errors import BrainError

MAX_TEXT_CHARS = 512
MAX_ITEM_CHARS = 256
MAX_ITEMS = 8


def _bounded_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise BrainError(f"{field} must be a string")
    return value.strip()[:MAX_TEXT_CHARS]


def _bounded_items(values: list[str], existing: list[str] | None = None) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise BrainError("capsule list fields must be lists of strings")
    merged = list(existing or [])
    merged.extend(item.strip()[:MAX_ITEM_CHARS] for item in values if item.strip())
    deduped: list[str] = []
    for item in merged:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[-MAX_ITEMS:]


def _bounded_verification(values: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise BrainError("verification must be an object")
    result = dict(existing)
    for key, value in values.items():
        if not isinstance(key, str):
            raise BrainError("verification keys must be strings")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise BrainError("verification values must be JSON scalars")
        result[key] = (
            _bounded_text(value, field=f"verification[{key!r}]")
            if isinstance(value, str)
            else value
        )
    return result


def _metadata(
    home: Path, session_id: str, capsule: dict[str, Any], changed: bool
) -> dict[str, Any]:
    path = working_set.session_dir(home, session_id) / "active-state.json"
    raw = path.read_bytes()
    return {
        "session_id": session_id,
        "capsule_path": str(path),
        "capsule_sha256": hashlib.sha256(raw).hexdigest(),
        "capsule_bytes": len(raw),
        "changed": changed,
        "capsule": capsule,
    }


def ensure_capsule(
    home: Path,
    session_id: str,
    *,
    objective: str,
    next_action: str | None = None,
    task_mode: str = "STANDARD",
    risk: str = "MEDIUM",
) -> dict[str, Any]:
    """Create or bind one capsule, changing it only when bounded state differs."""
    objective = _bounded_text(objective, field="objective")
    if not objective:
        raise BrainError("objective must be a non-empty string")
    bounded_next = None if next_action is None else _bounded_text(next_action, field="next_action")
    path = working_set.session_dir(home, session_id) / "active-state.json"

    if not path.exists():
        working_set.init_capsule(home, session_id, objective, task_mode=task_mode, risk=risk)
        if bounded_next:
            working_set.update_capsule(home, session_id, next_action=bounded_next)
        return _metadata(home, session_id, working_set.show_capsule(home, session_id), True)

    capsule = working_set.show_capsule(home, session_id)
    fields: dict[str, object] = {}
    if capsule["objective"] != objective:
        fields["objective"] = objective
    if bounded_next is not None and capsule["next_action"] != bounded_next:
        fields["next_action"] = bounded_next
    if not fields:
        return _metadata(home, session_id, capsule, False)
    working_set.update_capsule(home, session_id, **fields)
    return _metadata(home, session_id, working_set.show_capsule(home, session_id), True)


def update_capsule(
    home: Path,
    session_id: str,
    *,
    objective: str | None = None,
    next_action: str | None = None,
    task_mode: str | None = None,
    risk: str | None = None,
    constraints: list[str] | None = None,
    decisions: list[str] | None = None,
    open_questions: list[str] | None = None,
    facts: list[str] | None = None,
    hypotheses: list[str] | None = None,
    files_touched: list[str] | None = None,
    brain_refs: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge bounded meaningful state into the existing canonical capsule."""
    capsule = working_set.show_capsule(home, session_id)
    fields: dict[str, object] = {}
    if objective is not None:
        bounded = _bounded_text(objective, field="objective")
        if not bounded:
            raise BrainError("objective must be a non-empty string")
        if bounded != capsule["objective"]:
            fields["objective"] = bounded
    if next_action is not None:
        bounded = _bounded_text(next_action, field="next_action")
        if bounded != capsule["next_action"]:
            fields["next_action"] = bounded
    if task_mode is not None:
        if task_mode not in working_set.TASK_MODES:
            raise BrainError(f"task_mode must be one of {', '.join(working_set.TASK_MODES)}")
        if task_mode != capsule["task_mode"]:
            fields["task_mode"] = task_mode
    if risk is not None:
        if risk not in working_set.RISK_LEVELS:
            raise BrainError(f"risk must be one of {', '.join(working_set.RISK_LEVELS)}")
        if risk != capsule["risk"]:
            fields["risk"] = risk
    list_fields = (
        ("constraints", constraints),
        ("decisions_this_session", decisions),
        ("open_questions", open_questions),
        ("confirmed_facts", facts),
        ("current_hypotheses", hypotheses),
        ("files_touched", files_touched),
        ("brain_refs", brain_refs),
        ("artifact_refs", artifact_refs),
    )
    for name, incoming in list_fields:
        if incoming is None:
            continue
        merged = _bounded_items(incoming, capsule[name])
        if merged != capsule[name]:
            fields[name] = merged
    if verification is not None:
        merged_verification = _bounded_verification(verification, capsule["verification"])
        if merged_verification != capsule["verification"]:
            fields["verification"] = merged_verification
    if fields:
        working_set.update_capsule(home, session_id, **fields)
    return _metadata(home, session_id, working_set.show_capsule(home, session_id), bool(fields))
