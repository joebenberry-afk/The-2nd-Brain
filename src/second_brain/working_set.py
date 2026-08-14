"""Working set: active-state capsule, requirement ledger, read ledger.

Phase 4 (plan §100, schema §17, ledger §18, read ledger §73). Per-session state
lives under ``<home>/state/sessions/<session-id>/``:

- ``active-state.json`` — the Active State Capsule (plan §17);
- ``requirements.json`` — the requirement-to-evidence ledger (plan §18);
- ``read-ledger.json`` — append-only record of file reads (plan §73).

Every write is atomic (temp file + ``os.replace``). Every load validates the
stored shape: a missing ledger file yields an empty default, a missing capsule
raises, and a corrupt file always raises
:class:`~second_brain.errors.BrainError` naming the path — never silent.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from .errors import BrainError

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

TASK_MODES: tuple[str, ...] = (
    "MICRO",
    "STANDARD",
    "DEEP",
    "DEBUG",
    "RESEARCH",
    "REVIEW",
    "ADVISOR",
    "EXECUTOR",
    "HANDOFF",
)
RISK_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

REQUIREMENT_STATUSES: tuple[str, ...] = (
    "unverified",
    "partially_verified",
    "verified",
    "not_applicable",
    "blocked",
)
IMPORTANCES: tuple[str, ...] = ("critical", "high", "normal", "low")
MATERIAL_IMPORTANCES: frozenset[str] = frozenset({"critical", "high"})

# Capsule schema (plan §17). ``updated_at`` is auto-managed on every write.
CAPSULE_LIST_FIELDS: tuple[str, ...] = (
    "constraints",
    "confirmed_facts",
    "current_hypotheses",
    "decisions_this_session",
    "files_touched",
    "open_questions",
    "brain_refs",
    "artifact_refs",
)
CAPSULE_FIELDS: tuple[str, ...] = (
    "objective",
    "task_mode",
    "risk",
    *CAPSULE_LIST_FIELDS,
    "verification",
    "next_action",
    "updated_at",
)
_VERIFICATION_VALUE_TYPES: tuple[type, ...] = (str, int, float, bool)

_REQ_ID_RE = re.compile(r"^REQ-(\d+)$")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def session_dir(home: Path, session_id: str) -> Path:
    """Return the per-session working-set directory (path-safe id only)."""
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        raise BrainError(f"Invalid session id {session_id!r}: must match {SESSION_ID_RE.pattern}")
    if session_id in (".", ".."):
        raise BrainError(f"Invalid session id {session_id!r}: path traversal")
    return Path(home) / "state" / "sessions" / session_id


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> object:
    """Load JSON; missing or corrupt files raise BrainError naming the path."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise BrainError(f"Missing state file: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise BrainError(f"Corrupt state file {path}: {exc}") from exc


def _atomic_write_json(path: Path, data: object) -> None:
    """Write JSON atomically (same-dir temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise BrainError(f"Could not write {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Active State Capsule
# ---------------------------------------------------------------------------


def _validate_capsule_fields(path: Path, capsule: dict) -> None:
    """Raise BrainError when the capsule dict violates the plan §17 schema."""
    err = f"Corrupt capsule {path}"
    if not isinstance(capsule.get("objective"), str) or not capsule["objective"].strip():
        raise BrainError(f"{err}: objective must be a non-empty string")
    if capsule.get("task_mode") not in TASK_MODES:
        raise BrainError(f"{err}: task_mode must be one of {', '.join(TASK_MODES)}")
    if capsule.get("risk") not in RISK_LEVELS:
        raise BrainError(f"{err}: risk must be one of {', '.join(RISK_LEVELS)}")
    for field in CAPSULE_LIST_FIELDS:
        value = capsule.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise BrainError(f"{err}: {field} must be a list of strings")
    verification = capsule.get("verification")
    if not isinstance(verification, dict) or any(not isinstance(key, str) for key in verification):
        raise BrainError(f"{err}: verification must be an object with string keys")
    bad_values = [
        key
        for key, value in verification.items()
        if value is not None and not isinstance(value, _VERIFICATION_VALUE_TYPES)
    ]
    if bad_values:
        raise BrainError(f"{err}: verification values must be JSON scalars: {bad_values}")
    if not isinstance(capsule.get("next_action"), str):
        raise BrainError(f"{err}: next_action must be a string")
    if not isinstance(capsule.get("updated_at"), str) or not capsule["updated_at"]:
        raise BrainError(f"{err}: updated_at must be a non-empty string")


def _load_capsule(path: Path) -> dict:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise BrainError(f"Corrupt capsule {path}: expected a JSON object")
    missing = [field for field in CAPSULE_FIELDS if field not in data]
    if missing:
        raise BrainError(f"Corrupt capsule {path}: missing fields {', '.join(missing)}")
    _validate_capsule_fields(path, data)
    return data


def init_capsule(
    home: Path,
    session_id: str,
    objective: str,
    task_mode: str = "STANDARD",
    risk: str = "MEDIUM",
    constraints: list[str] | None = None,
) -> Path:
    """Create a new Active State Capsule. Fails if one already exists."""
    directory = session_dir(home, session_id)
    if not isinstance(objective, str) or not objective.strip():
        raise BrainError("objective must be a non-empty string")
    if task_mode not in TASK_MODES:
        raise BrainError(f"task_mode must be one of {', '.join(TASK_MODES)}")
    if risk not in RISK_LEVELS:
        raise BrainError(f"risk must be one of {', '.join(RISK_LEVELS)}")
    if constraints is None:
        constraints = []
    if not isinstance(constraints, list) or any(not isinstance(item, str) for item in constraints):
        raise BrainError("constraints must be a list of strings")

    path = directory / "active-state.json"
    if path.exists():
        raise BrainError(f"Capsule already exists for session {session_id!r}: {path}")
    capsule = {
        "objective": objective,
        "task_mode": task_mode,
        "risk": risk,
        "constraints": list(constraints),
        "confirmed_facts": [],
        "current_hypotheses": [],
        "decisions_this_session": [],
        "files_touched": [],
        "open_questions": [],
        "verification": {},
        "next_action": "",
        "brain_refs": [],
        "artifact_refs": [],
        "updated_at": _utcnow(),
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BrainError(f"Cannot create session directory {directory}: {exc}") from exc
    _atomic_write_json(path, capsule)
    return path


def update_capsule(home: Path, session_id: str, **fields: object) -> Path:
    """Partially merge fields into the capsule and refresh ``updated_at``."""
    path = session_dir(home, session_id) / "active-state.json"
    capsule = _load_capsule(path)
    if "updated_at" in fields:
        raise BrainError("updated_at is managed automatically and cannot be set")
    unknown = [name for name in fields if name not in CAPSULE_FIELDS]
    if unknown:
        raise BrainError(f"Unknown capsule field(s): {', '.join(sorted(unknown))}")
    capsule.update(fields)
    _validate_capsule_fields(path, capsule)
    capsule["updated_at"] = _utcnow()
    _atomic_write_json(path, capsule)
    return path


def show_capsule(home: Path, session_id: str) -> dict:
    """Return the capsule contents (BrainError if missing or corrupt)."""
    return _load_capsule(session_dir(home, session_id) / "active-state.json")


# ---------------------------------------------------------------------------
# Requirement ledger (plan §18)
# ---------------------------------------------------------------------------


def _validate_req_entry(path: Path, index: int, entry: object) -> None:
    err = f"Corrupt requirement ledger {path}"
    if not isinstance(entry, dict):
        raise BrainError(f"{err}: entry {index} is not an object")
    for key in ("id", "requirement", "importance", "status"):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"{err}: entry {index} field {key!r} invalid")
    if entry["importance"] not in IMPORTANCES:
        raise BrainError(f"{err}: entry {index} importance must be one of {', '.join(IMPORTANCES)}")
    if entry["status"] not in REQUIREMENT_STATUSES:
        raise BrainError(
            f"{err}: entry {index} status must be one of {', '.join(REQUIREMENT_STATUSES)}"
        )
    evidence = entry.get("evidence")
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
        raise BrainError(f"{err}: entry {index} evidence must be a list of strings")


def _load_requirements(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = _read_json(path)
    if not isinstance(data, list):
        raise BrainError(f"Corrupt requirement ledger {path}: expected a JSON list")
    for index, entry in enumerate(data):
        _validate_req_entry(path, index, entry)
    return data


def _find_req(entries: list[dict], req_id: str, path: Path) -> dict:
    for entry in entries:
        if entry["id"] == req_id:
            return entry
    raise BrainError(f"Unknown requirement id {req_id!r} in {path}")


def add_requirement(
    home: Path,
    session_id: str,
    requirement: str,
    req_id: str | None = None,
    importance: str = "normal",
) -> dict:
    """Append a requirement entry. Auto id REQ-001, REQ-002, ... (gap-free)."""
    if not isinstance(requirement, str) or not requirement.strip():
        raise BrainError("requirement must be a non-empty string")
    if importance not in IMPORTANCES:
        raise BrainError(f"importance must be one of {', '.join(IMPORTANCES)}")
    path = session_dir(home, session_id) / "requirements.json"
    entries = _load_requirements(path)
    if any(entry["requirement"] == requirement for entry in entries):
        raise BrainError(f"Duplicate requirement: {requirement!r}")
    if req_id is None:
        highest = 0
        for entry in entries:
            match = _REQ_ID_RE.match(entry["id"])
            if match:
                highest = max(highest, int(match.group(1)))
        req_id = f"REQ-{highest + 1:03d}"
    else:
        if not isinstance(req_id, str) or not _REQ_ID_RE.fullmatch(req_id):
            raise BrainError(f"Invalid requirement id {req_id!r}: must match REQ-<number>")
        if any(entry["id"] == req_id for entry in entries):
            raise BrainError(f"Requirement id already exists: {req_id}")
    entry = {
        "id": req_id,
        "requirement": requirement,
        "importance": importance,
        "evidence": [],
        "status": "unverified",
    }
    entries.append(entry)
    _atomic_write_json(path, entries)
    return entry


def add_evidence(home: Path, session_id: str, req_id: str, evidence: str) -> dict:
    """Append an evidence line to a requirement. Returns the updated entry."""
    if not isinstance(evidence, str) or not evidence.strip():
        raise BrainError("evidence must be a non-empty string")
    path = session_dir(home, session_id) / "requirements.json"
    entries = _load_requirements(path)
    entry = _find_req(entries, req_id, path)
    entry["evidence"].append(evidence)
    _atomic_write_json(path, entries)
    return entry


def set_requirement_status(home: Path, session_id: str, req_id: str, status: str) -> dict:
    """Set a requirement's status (enum-validated). Returns the updated entry."""
    if status not in REQUIREMENT_STATUSES:
        raise BrainError(f"status must be one of {', '.join(REQUIREMENT_STATUSES)}")
    path = session_dir(home, session_id) / "requirements.json"
    entries = _load_requirements(path)
    entry = _find_req(entries, req_id, path)
    entry["status"] = status
    _atomic_write_json(path, entries)
    return entry


def _material_gate_blocks(home: Path) -> bool:
    """Honor verification.toml's material_unverified_blocks_completion.

    Defaults to True when the config file or key is missing/unparseable
    (fail-safe direction: the gate stays closed).
    """
    try:
        cfg = tomllib.loads((home / "config" / "verification.toml").read_text(encoding="utf-8"))
        ledger = cfg.get("requirement_ledger") or {}
        value = ledger.get("material_unverified_blocks_completion", True)
        return bool(value)
    except (OSError, tomllib.TOMLDecodeError):
        return True


def check_requirements(home: Path, session_id: str) -> dict:
    """Material-requirement completion check (plan §18).

    Material = importance in MATERIAL_IMPORTANCES. A material requirement with a
    status outside {verified, not_applicable} blocks completion. Returns
    ``{"material_total", "material_unverified", "entries"}`` where ``entries``
    are the material-unverified entry dicts.
    """
    path = session_dir(home, session_id) / "requirements.json"
    entries = _load_requirements(path)
    material = [e for e in entries if e["importance"] in MATERIAL_IMPORTANCES]
    unverified = [e for e in material if e["status"] not in ("verified", "not_applicable")]
    gate = _material_gate_blocks(home)
    return {
        "material_total": len(material),
        "material_unverified": len(unverified),
        "gate": gate,
        "blocks": gate and len(unverified) > 0,
        "entries": unverified,
    }


def show_requirements(home: Path, session_id: str) -> list[dict]:
    """Return all requirement entries in ledger order ([] if none)."""
    return _load_requirements(session_dir(home, session_id) / "requirements.json")


# ---------------------------------------------------------------------------
# Read ledger (plan §73)
# ---------------------------------------------------------------------------


def _validate_read_entry(path: Path, index: int, entry: object) -> None:
    err = f"Corrupt read ledger {path}"
    if not isinstance(entry, dict):
        raise BrainError(f"{err}: entry {index} is not an object")
    for key in ("path", "purpose", "ts"):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"{err}: entry {index} field {key!r} invalid")
    if entry.get("hash") is not None and not isinstance(entry["hash"], str):
        raise BrainError(f"{err}: entry {index} hash must be a string or null")
    for key in ("range", "artifact"):
        if entry.get(key) is not None and not isinstance(entry[key], str):
            raise BrainError(f"{err}: entry {index} {key} must be a string or null")
    turn = entry.get("turn")
    if turn is not None and (not isinstance(turn, int) or isinstance(turn, bool)):
        raise BrainError(f"{err}: entry {index} turn must be an integer or null")


def _load_reads(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = _read_json(path)
    if not isinstance(data, list):
        raise BrainError(f"Corrupt read ledger {path}: expected a JSON list")
    for index, entry in enumerate(data):
        _validate_read_entry(path, index, entry)
    return data


def record_read(
    home: Path,
    session_id: str,
    path: str,
    purpose: str,
    turn: int | None = None,
    range_text: str | None = None,
    artifact: str | None = None,
) -> dict:
    """Append one read entry. ``hash`` is the file's sha256 (null if missing)."""
    if not isinstance(path, str) or not path.strip():
        raise BrainError("path must be a non-empty string")
    if not isinstance(purpose, str) or not purpose.strip():
        raise BrainError("purpose must be a non-empty string")
    if turn is not None and (not isinstance(turn, int) or isinstance(turn, bool)):
        raise BrainError("turn must be an integer or None")
    for name, value in (("range_text", range_text), ("artifact", artifact)):
        if value is not None and not isinstance(value, str):
            raise BrainError(f"{name} must be a string or None")

    ledger_path = session_dir(home, session_id) / "read-ledger.json"
    entries = _load_reads(ledger_path)
    target = Path(path)
    content_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
    entry = {
        "path": path,
        "hash": content_hash,
        "range": range_text,
        "purpose": purpose,
        "turn": turn,
        "artifact": artifact,
        "ts": _utcnow(),
    }
    entries.append(entry)
    _atomic_write_json(ledger_path, entries)
    return entry


def show_reads(home: Path, session_id: str) -> list[dict]:
    """Return all read entries in append order ([] if none)."""
    return _load_reads(session_dir(home, session_id) / "read-ledger.json")
