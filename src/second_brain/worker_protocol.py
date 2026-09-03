"""Harness-neutral worker communication helpers.

The packet/result dataclasses live in :mod:`second_brain.contracts`. This module
only connects bounded Brain references to those contracts; it does not know
about Hermes, Prime, Codex, or any host transport.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import artifacts, db, jit, ledger, semantic
from .contracts import (
    WORKER_CONTEXT_MAX_CHARS,
    WORKER_CONTEXT_MAX_TOTAL_CHARS,
    WORKER_PACKET_MAX_BYTES,
    BrainLifecycleEvent,
    LifecycleEventType,
    SurfaceVisibility,
    WorkerContextResolution,
    WorkerLifecycle,
    WorkerPacketError,
    WorkerTaskPacket,
    canonical_json,
    estimate_tokens,
    stable_content_hash,
)
from .errors import BrainError
DEFAULT_LEASE_SECONDS = 300
MAX_DISPATCH_PAYLOAD_BYTES = 16 * 1024

_WORKER_EVENT_STATES = {
    "accepted": WorkerLifecycle.WORKING,
    "worker_accepted": WorkerLifecycle.WORKING,
    "working": WorkerLifecycle.WORKING,
    "worker_started": WorkerLifecycle.WORKING,
    "started": WorkerLifecycle.WORKING,
    "input_required": WorkerLifecycle.INPUT_REQUIRED,
    "auth_required": WorkerLifecycle.AUTH_REQUIRED,
    "completed": WorkerLifecycle.COMPLETED,
    "worker_completed": WorkerLifecycle.COMPLETED,
    "failed": WorkerLifecycle.FAILED,
    "worker_failed": WorkerLifecycle.FAILED,
    "rejected": WorkerLifecycle.REJECTED,
    "worker_rejected": WorkerLifecycle.REJECTED,
    "cancelled": WorkerLifecycle.CANCELED,
    "canceled": WorkerLifecycle.CANCELED,
    "worker_cancelled": WorkerLifecycle.CANCELED,
    "worker_canceled": WorkerLifecycle.CANCELED,
    "task_completed": WorkerLifecycle.COMPLETED,
    "task_failed": WorkerLifecycle.FAILED,


}
def _memory_id(ref: str) -> str | None:
    value = ref
    if value.startswith("memory:"):
        value = value.removeprefix("memory:")
    elif value.startswith("brain://"):
        value = value.removeprefix("brain://")
        if value.startswith("memory/"):
            value = value.removeprefix("memory/")
        elif value.startswith("artifact/"):
            return None
    else:
        return None
    if "@" in value:
        value = value.split("@", 1)[0]
    return value if value.startswith("mem-") else None


def _artifact_ref(ref: str) -> str | None:
    return artifacts.parse_ref(ref)


def _load_reference(home: Path, ref: str) -> tuple[str, bytes]:
    memory_id = _memory_id(ref)
    if memory_id is not None:
        try:
            memory = semantic.show_memory(home, memory_id)
        except (BrainError, OSError, sqlite3.Error) as exc:
            raise WorkerPacketError(
                "CONTEXT_REF_UNRESOLVED", f"memory ref unavailable: {ref}"
            ) from exc
        return "memory", str(memory["body"]).encode("utf-8")

    artifact_ref = _artifact_ref(ref)
    if artifact_ref is not None:
        try:
            return "artifact", artifacts.expand(home, artifact_ref)
        except (BrainError, OSError) as exc:
            raise WorkerPacketError(
                "CONTEXT_REF_UNRESOLVED", f"artifact ref unavailable: {ref}"
            ) from exc

    raise WorkerPacketError("CONTEXT_REF_UNRESOLVED", f"unsupported Brain context ref: {ref}")


def resolve_context_refs(
    home: Path | str, packet: WorkerTaskPacket
) -> list[WorkerContextResolution]:
    """Resolve bounded ``context_refs`` through canonical Brain storage.

    Memory files and content-addressed artifacts are the supported reference
    types. Full source bytes are hashed for auditability; only a bounded UTF-8
    preview is returned for ephemeral worker context. Raw content is never
    suitable for telemetry or ledger payloads and callers must use
    ``context_metadata`` there.
    """
    packet.validate()
    home_path = Path(home)
    resolved: list[WorkerContextResolution] = []
    visible_total = 0
    for ref in packet.context_refs:
        kind, raw = _load_reference(home_path, ref)
        text = raw.decode("utf-8", errors="replace")
        visible = text[:WORKER_CONTEXT_MAX_CHARS]
        item = WorkerContextResolution(
            ref=ref,
            kind=kind,
            content=visible,
            content_sha256=hashlib.sha256(raw).hexdigest(),
            content_chars=len(text),
            truncated=len(text) > len(visible),
        ).validate()
        visible_total += len(item.content)
        if visible_total > WORKER_CONTEXT_MAX_TOTAL_CHARS:
            raise WorkerPacketError("CONTEXT_REF_TOO_LARGE", "resolved context exceeds total bound")
        resolved.append(item)
    return resolved


def context_metadata(
    resolved: list[WorkerContextResolution], home: Path | str | None = None
) -> dict[str, Any]:
    """Return bounded, privacy-safe resolution metadata for Brain records."""
    entries = [item.validate().metadata() for item in resolved]
    visible_chars = sum(len(item.content) for item in resolved)
    visible_bytes = sum(len(item.content.encode("utf-8")) for item in resolved)
    return {
        "resolved_count": len(entries),
        "visible_chars": visible_chars,
        "visible_bytes": visible_bytes,
        "visible_tokens_estimate": (
            estimate_tokens("x" * visible_chars, home=home) if visible_chars else 0
        ),
        "source_chars": sum(int(item["content_chars"]) for item in entries),
        "refs": entries,
        "resolution_sha256": stable_content_hash(entries),
    }



def _latest_context_snapshot(
    home: Path,
    parent_session_id: str,
    packet_sha256: str,
    offset: int = 0,
) -> dict[str, Any] | None:
    """Read the latest committed context snapshot from the existing ledger."""
    ledger_path = ledger.LedgerStore(home, parent_session_id).dbfile
    if not ledger_path.is_file():
        return None
    uri = "file:" + ledger_path.as_posix() + "?mode=ro"
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(uri, uri=True)
        rows = conn.execute(
            "SELECT sha256 FROM object_refs "
            "WHERE role = 'worker_context_snapshot' ORDER BY added_at DESC"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            conn.close()
    matching = 0
    for (snapshot_hash,) in rows:
        if not isinstance(snapshot_hash, str) or not snapshot_hash:
            continue
        object_path = ledger_path.parent / "objects" / snapshot_hash
        try:
            raw = object_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != snapshot_hash:
                continue
            snapshot = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(snapshot, dict) and snapshot.get("packet_sha256") == packet_sha256:
            if matching >= offset:
                return snapshot
            matching += 1
    return None


def _store_context_snapshot(
    home: Path, parent_session_id: str, snapshot: dict[str, Any]
) -> str:
    """Store a context snapshot in the existing per-session object store."""
    data = canonical_json(snapshot).encode("utf-8")
    with ledger.LedgerStore(home, parent_session_id).open(create=True) as store:
        return store.add_object(data, mime="application/json", role="worker_context_snapshot")


def _jit_snapshot(home: Path, packet: WorkerTaskPacket) -> dict[str, Any]:
    """Compile a safe parent-session JIT body and ignore its volatile header."""
    safe_session = ledger.internal_session_id(packet.parent_session_id)
    try:
        capsule = jit.compile_context(
            Path(home), safe_session, packet.objective, project_key=packet.project_id
        )
        text = capsule.read_text(encoding="utf-8")
        body = text.split("\n# Task", 1)[1] if "\n# Task" in text else text
        body = "\n".join(
            line for line in body.splitlines() if not line.startswith("updated_at:")
        )
        raw = body.encode("utf-8")
        visible = body[:WORKER_CONTEXT_MAX_TOTAL_CHARS]
        return {
            "body": visible,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "visible_bytes": len(visible.encode("utf-8")),
        }
    except (BrainError, OSError, ValueError):
        return {"body": "", "sha256": "", "bytes": 0, "visible_bytes": 0}


def _handoff_delta(
    resolved: list[WorkerContextResolution],
    metadata: dict[str, Any],
    prior: dict[str, Any] | None,
    current_jit: dict[str, Any],
) -> tuple[list[WorkerContextResolution], list[str], str, int]:
    current_refs = {entry["ref_sha256"]: entry for entry in metadata["refs"]}
    prior_refs = {
        entry["ref_sha256"]: entry
        for entry in (prior or {}).get("refs", [])
        if isinstance(entry, dict) and isinstance(entry.get("ref_sha256"), str)
    }
    changed = [
        item
        for item in resolved
        if (
            item.metadata()["ref_sha256"] not in prior_refs
            or prior_refs[item.metadata()["ref_sha256"]].get("content_sha256")
            != item.content_sha256
        )
    ]
    removed = sorted(set(prior_refs) - set(current_refs))
    prior_jit = str((prior or {}).get("jit_body", ""))
    current_jit_text = str(current_jit.get("body", ""))
    jit_delta = ""
    if prior is not None and prior_jit != current_jit_text:
        diff = difflib.unified_diff(
            prior_jit.splitlines(), current_jit_text.splitlines(),
            fromfile="previous-jit", tofile="current-jit", lineterm="",
        )
        jit_delta = "\n".join(diff)[:WORKER_CONTEXT_MAX_TOTAL_CHARS]
    delta_bytes = len(
        canonical_json(
            {
                "changed_refs": prompt_context(changed),
                "removed_ref_hashes": removed,
                "jit_delta": jit_delta,
            }
        ).encode("utf-8")
    )
    return changed, removed, jit_delta, delta_bytes


def prepare_context_handoff(
    home: Path | str, packet: WorkerTaskPacket
) -> dict[str, Any]:
    """Prepare a stable full/reuse/delta worker context handoff.

    The first use stores a canonical snapshot in the existing session object
    store. Later preparation compares reference content hashes and the stable
    JIT body hash against the last committed snapshot. Unchanged context emits
    references/fingerprints only; changed context emits changed references and
    a bounded JIT line delta.
    """
    packet.validate()
    home_path = Path(home)
    resolved = resolve_context_refs(home_path, packet)
    metadata = context_metadata(resolved, home=home_path)
    jit_info = _jit_snapshot(home_path, packet)
    snapshot_core = {
        "packet_sha256": packet.canonical_hash(),
        "refs": metadata["refs"],
        "resolution_sha256": metadata["resolution_sha256"],
        "jit_body_sha256": jit_info["sha256"],
        "jit_body_bytes": jit_info["bytes"],
        "jit_body": jit_info["body"],
    }
    fingerprint = stable_content_hash(
        {
            "refs": snapshot_core["refs"],
            "jit_body_sha256": snapshot_core["jit_body_sha256"],
        }
    )
    previous = _latest_context_snapshot(
        home_path, packet.parent_session_id, packet.canonical_hash()
    )
    previous_fingerprint = previous.get("context_fingerprint") if previous else None
    if previous is None:
        mode = "full"
        changed = resolved
        removed: list[str] = []
        jit_delta = ""
        delta_bytes = 0
    elif previous_fingerprint == fingerprint:
        mode = "unchanged"
        changed = []
        removed = []
        jit_delta = ""
        delta_bytes = 0
    else:
        mode = "delta"
        changed, removed, jit_delta, delta_bytes = _handoff_delta(
            resolved, metadata, previous, jit_info
        )
    snapshot = {**snapshot_core, "context_fingerprint": fingerprint}
    snapshot_hash = _store_context_snapshot(home_path, packet.parent_session_id, snapshot)
    full_payload = prompt_context(resolved) if mode == "full" else []
    delta_payload = {
        "changed_refs": prompt_context(changed) if mode == "delta" else [],
        "removed_ref_hashes": removed,
        "jit_delta": jit_delta if mode == "delta" else "",
    }
    jit_context = jit_info["body"] if mode == "full" else ""
    handoff_wire = {
        "mode": mode,
        "resolved_context": full_payload,
        "context_delta": delta_payload,
        "context_fingerprint": fingerprint,
        "jit_context": jit_context,
    }
    handoff_bytes = len(canonical_json(handoff_wire).encode("utf-8"))
    if handoff_bytes > WORKER_PACKET_MAX_BYTES:
        raise WorkerPacketError(
            "CONTEXT_HANDOFF_TOO_LARGE", "worker context handoff exceeds byte bound"
        )
    return {
        **metadata,
        "mode": mode,
        "reused": mode == "unchanged",
        "cache_hit": mode == "unchanged",
        "context_fingerprint": fingerprint,
        "previous_context_fingerprint": previous_fingerprint,
        "context_snapshot_sha256": snapshot_hash,
        "packet_sha256": packet.canonical_hash(),
        "resolved_context": full_payload,
        "context_delta": delta_payload,
        "context_handoff_bytes": handoff_bytes,
        "context_handoff_tokens_estimate": estimate_tokens("x" * handoff_bytes, home=home_path),
        "context_delta_bytes": delta_bytes,
        "context_delta_tokens_estimate": (
            estimate_tokens("x" * delta_bytes, home=home_path) if delta_bytes else 0
        ),
        "changed_ref_count": len(changed),
        "removed_ref_count": len(removed),
        "jit_body_sha256": jit_info["sha256"],
        "jit_body_bytes": jit_info["bytes"],
        "jit_delta_sha256": stable_content_hash(jit_delta),
        "jit_delta_bytes": len(jit_delta.encode("utf-8")),
        "jit_context": jit_context,
    }


def handoff_metadata(handoff: dict[str, Any]) -> dict[str, Any]:
    """Strip raw context from a handoff for ledger/telemetry records."""
    keys = (
        "resolved_count", "visible_chars", "visible_bytes", "visible_tokens_estimate",
        "source_chars", "resolution_sha256", "mode", "reused", "cache_hit",
        "context_fingerprint", "previous_context_fingerprint", "context_snapshot_sha256",
        "packet_sha256", "context_handoff_bytes", "context_handoff_tokens_estimate",
        "context_delta_bytes",
        "context_delta_tokens_estimate", "changed_ref_count", "removed_ref_count",
        "jit_body_sha256", "jit_body_bytes", "jit_delta_sha256", "jit_delta_bytes", "refs",
    )
    return {key: handoff.get(key) for key in keys}

def validate_context_handoff(
    home: Path | str, packet: WorkerTaskPacket, handoff: Any
) -> dict[str, Any]:
    """Validate a prepared handoff without resolving or re-rendering context."""
    if not isinstance(handoff, dict):
        raise WorkerPacketError("CONTEXT_HANDOFF_MALFORMED", "context handoff must be an object")
    if handoff.get("packet_sha256") != packet.canonical_hash():
        raise WorkerPacketError("CONTEXT_HANDOFF_MISMATCH", "handoff packet hash does not match")
    if handoff.get("mode") not in {"full", "unchanged", "delta"}:
        raise WorkerPacketError("CONTEXT_HANDOFF_MALFORMED", "invalid context handoff mode")
    handoff_bytes = handoff.get("context_handoff_bytes")
    if (
        not isinstance(handoff_bytes, int)
        or handoff_bytes < 0
        or handoff_bytes > WORKER_PACKET_MAX_BYTES
    ):
        raise WorkerPacketError("CONTEXT_HANDOFF_TOO_LARGE", "invalid context handoff byte bound")
    expected_bytes = len(
        canonical_json(
            {
                "mode": handoff.get("mode"),
                "resolved_context": handoff.get("resolved_context", []),
                "context_delta": handoff.get("context_delta", {}),
                "context_fingerprint": handoff.get("context_fingerprint"),
                "jit_context": handoff.get("jit_context", ""),
            }
        ).encode("utf-8")
    )
    if expected_bytes != handoff_bytes:
        raise WorkerPacketError(
            "CONTEXT_HANDOFF_MISMATCH", "handoff byte accounting does not match"
        )
    latest = _latest_context_snapshot(
        Path(home), packet.parent_session_id, packet.canonical_hash()
    )
    previous = _latest_context_snapshot(
        Path(home), packet.parent_session_id, packet.canonical_hash(), offset=1
    )
    if latest is None:
        raise WorkerPacketError("CONTEXT_HANDOFF_MISMATCH", "handoff snapshot is not current")
    resolved = resolve_context_refs(Path(home), packet)
    metadata = context_metadata(resolved, home=home)
    jit_info = _jit_snapshot(Path(home), packet)
    fingerprint = stable_content_hash(
        {"refs": metadata["refs"], "jit_body_sha256": jit_info["sha256"]}
    )
    if (
        latest.get("context_fingerprint") != fingerprint
        or handoff.get("context_fingerprint") != fingerprint
    ):
        raise WorkerPacketError("CONTEXT_HANDOFF_MISMATCH", "handoff snapshot is not current")
    mode = handoff["mode"]
    if mode == "full":
        expected_context = prompt_context(resolved)
        expected_delta = {
            "changed_refs": [],
            "removed_ref_hashes": [],
            "jit_delta": "",
        }
        expected_jit = jit_info["body"]
    elif mode == "unchanged":
        expected_context = []
        expected_delta = {
            "changed_refs": [],
            "removed_ref_hashes": [],
            "jit_delta": "",
        }
        expected_jit = ""
    else:
        if previous is None:
            raise WorkerPacketError("CONTEXT_HANDOFF_MISMATCH", "delta snapshot is unavailable")
        changed, removed, jit_delta, _ = _handoff_delta(
            resolved, metadata, previous, jit_info
        )
        expected_context = []
        expected_delta = {
            "changed_refs": prompt_context(changed),
            "removed_ref_hashes": removed,
            "jit_delta": jit_delta,
        }
        expected_jit = ""
    expected_wire = {
        "mode": mode,
        "resolved_context": expected_context,
        "context_delta": expected_delta,
        "context_fingerprint": fingerprint,
        "jit_context": expected_jit,
    }
    supplied_wire = {
        key: handoff.get(key, {} if key == "context_delta" else [])
        for key in ("mode", "resolved_context", "context_delta", "context_fingerprint", "jit_context")
    }
    if canonical_json(supplied_wire) != canonical_json(expected_wire):
        raise WorkerPacketError(
            "CONTEXT_HANDOFF_MISMATCH", "handoff content does not match current context"
        )
    return handoff


def prompt_context(resolved: list[WorkerContextResolution]) -> list[dict[str, Any]]:
    """Return the bounded ephemeral context block for a worker prompt."""
    return [
        {
            "ref": item.ref,
            "kind": item.kind,
            "content": item.content,
            "content_sha256": item.content_sha256,
            "content_chars": item.content_chars,
            "truncated": item.truncated,
        }
        for item in resolved
    ]
def _worker_db(home: Path | str) -> Path:
    home_path = Path(home)
    dbfile = db_path = home_path / "db" / "brain.sqlite"
    if db.pending_migrations(dbfile):
        db.migrate(dbfile)
    return db_path


def _lease_seconds(home: Path | str, value: int | float | None = None) -> int:
    if value is not None:
        return max(1, int(value))
    for filename in ("v2.toml", "brain.toml"):
        try:
            raw = tomllib.loads((Path(home) / "config" / filename).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        for section_name in ("worker", "workers", "brainstem"):
            section = raw.get(section_name)
            if isinstance(section, dict):
                configured = section.get("lease_seconds", section.get("worker_lease_seconds"))
                if isinstance(configured, int) and not isinstance(configured, bool) and configured > 0:
                    return configured
    return DEFAULT_LEASE_SECONDS


def _as_dt(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)

def _renewal_lease(
    existing: str | None, current: datetime, seconds: int
) -> str:
    proposed = current + timedelta(seconds=seconds)
    if existing is None:
        return proposed.isoformat()
    return max(_as_dt(existing), proposed).isoformat()


def _packet_hash(value: object) -> str:
    if not _is_sha256(value):
        raise WorkerPacketError("PROTOCOL_ERROR", "packet_sha256 must be a sha256 hex digest")
    return value.lower()


def _task_row(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM worker_tasks WHERE task_id = ?", (task_id,)).fetchone()
    return dict(row) if row is not None else None

def lookup_task(
    home: Path | str, task_id: str, packet_sha256: str
) -> dict[str, Any] | None:
    """Authenticate a task identity without mutating lifecycle or leases."""
    digest = _packet_hash(packet_sha256)
    conn = db.connect(_worker_db(home))
    try:
        row = _task_row(conn, task_id)
        if row is None:
            return None
        if row["packet_sha256"].lower() != digest:
            raise WorkerPacketError("PROTOCOL_ERROR", "task_id is bound to another packet hash")
        return _result(row, duplicate=True)
    finally:
        conn.close()

def task_owner_session(
    home: Path | str, task_id: str, packet_sha256: str
) -> str | None:
    """Return the immutable driver session for an authenticated task."""
    if lookup_task(home, task_id, packet_sha256) is None:
        return None
    conn = db.connect(_worker_db(home))
    try:
        row = conn.execute(
            "SELECT session_id FROM worker_task_meta WHERE task_id=?", (task_id,)
        ).fetchone()
        return row["session_id"] if row is not None else None
    finally:
        conn.close()

def verify_result_binding(
    home: Path | str,
    task_id: str,
    packet_sha256: str,
    result_sha256: str,
) -> str | None:
    """Return an error code unless task, packet, and persisted result agree."""
    task = lookup_task(home, task_id, packet_sha256)
    if task is None:
        return "ORPHAN_TASK"
    if not _is_sha256(result_sha256):
        return "PROTOCOL_ERROR"
    conn = db.connect(_worker_db(home))
    try:
        meta = conn.execute(
            "SELECT session_id FROM worker_task_meta WHERE task_id=?", (task_id,)
        ).fetchone()
    finally:
        conn.close()
    session_id = meta["session_id"] if meta else None
    if not session_id:
        return "RESULT_NOT_RECORDED"
    path = ledger.LedgerStore(home, session_id).dbfile
    if not path.exists():
        return "RESULT_NOT_RECORDED"
    try:
        with sqlite3.connect(path) as ledger_conn:
            rows = ledger_conn.execute(
                "SELECT event_type,payload_json FROM events "
                "WHERE event_type IN ('worker_completed','result_corrected')"
            ).fetchall()
    except sqlite3.Error:
        return "RESULT_NOT_RECORDED"
    for _event_type, raw in rows:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("task_id") == task_id
            and payload.get("result_sha256") == result_sha256
        ):
            return None
    return "RESULT_NOT_RECORDED"


def _result(row: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "state": row["state"],
        "lease_expires_at": row["lease_expires_at"],
        "packet_sha256": row["packet_sha256"],
        "accepted_at": row["accepted_at"],
        "settled_at": row["settled_at"],
        "updated_at": row["updated_at"],
        "duplicate": duplicate,
    }


def register_task(
    home: Path | str,
    task_id: str,
    packet_sha256: str,
    *,
    session_id: str | None = None,
    dispatch_payload: dict[str, Any] | None = None,
    lease_seconds: int | float | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Persist a newly submitted task, preserving an existing task identity."""
    digest = _packet_hash(packet_sha256)
    dispatch_json = None
    if dispatch_payload is not None:
        if not isinstance(dispatch_payload, dict):
            raise WorkerPacketError("PROTOCOL_ERROR", "dispatch_payload must be an object")
        dispatch_json = canonical_json(dispatch_payload)
        if len(dispatch_json.encode("utf-8")) > MAX_DISPATCH_PAYLOAD_BYTES:
            raise WorkerPacketError("PROTOCOL_ERROR", "dispatch_payload exceeds bounded redelivery size")
    current = _as_dt(now)
    updated = current.isoformat()
    expiry = (current + timedelta(seconds=_lease_seconds(home, lease_seconds))).isoformat()
    conn = db.connect(_worker_db(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _task_row(conn, task_id)
        if row is not None:
            if row["packet_sha256"].lower() != digest:
                raise WorkerPacketError("PROTOCOL_ERROR", "task_id is bound to another packet hash")
            conn.commit()
            return _result(row, duplicate=True)
        conn.execute(
            "INSERT INTO worker_tasks(task_id,state,lease_expires_at,packet_sha256,accepted_at,settled_at,updated_at) "
            "VALUES(?, ?, ?, ?, NULL, NULL, ?)",
            (task_id, WorkerLifecycle.SUBMITTED, expiry, digest, updated),
        )
        conn.execute(
            "INSERT OR REPLACE INTO worker_task_meta(task_id,redeliveries,failure_reason,session_id,delivered_at,dispatch_payload,updated_at) "
            "VALUES(?, 0, NULL, ?, NULL, ?, ?)",
            (
                task_id,
                session_id,
                dispatch_json,
                updated,
            ),
        )
        conn.commit()
        row = _task_row(conn, task_id)
        assert row is not None
        return _result(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _emit_worker_event(
    home: Path | str,
    session_id: str | None,
    task_id: str,
    state: str,
    payload: dict[str, Any],
) -> None:
    if not session_id:
        return
    event_type = {
        WorkerLifecycle.COMPLETED: LifecycleEventType.WORKER_COMPLETED,
        WorkerLifecycle.FAILED: LifecycleEventType.WORKER_FAILED,
        WorkerLifecycle.CANCELED: LifecycleEventType.WORKER_CANCELLED,
    }.get(state, LifecycleEventType.WORKER_MESSAGE)
    event_types = (
        [LifecycleEventType.WORKER_COMPLETED, LifecycleEventType.TASK_FAILED]
        if payload.get("failure_reason") == "lease_expired"
        else [event_type]
    )
    stamp = str(payload.get("updated_at") or datetime.now(UTC).isoformat())
    events = [
        BrainLifecycleEvent(
            seq=0,
            event_id=f"worker-{task_id}-{kind.value}-{stable_content_hash(payload)[:16]}",
            internal_session_id=ledger.internal_session_id(session_id),
            agent_id="worker-plane",
            event_type=kind,
            timestamp=stamp,
            surface_visibility=SurfaceVisibility.BOOKKEEPING,
            ignorable=False,
            payload={"task_id": task_id, "state": state, **payload},
        )
        for kind in event_types
    ]
    try:
        with ledger.LedgerStore(home, session_id).open(create=True) as store:
            store.append_events(events)
    except Exception:
        # State persistence remains authoritative; a missing host ledger must
        # not turn a lease reaper into a stuck worker.
        return


def record_worker_event(
    home: Path | str,
    task_id: str,
    packet_sha256: str,
    event: str,
    *,
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
    now: datetime | str | None = None,
    lease_seconds: int | float | None = None,
) -> dict[str, Any]:
    """Apply one worker event with packet identity and lease renewal guards."""
    digest = _packet_hash(packet_sha256)
    if not isinstance(event, str) or not event.strip():
        raise WorkerPacketError("PROTOCOL_ERROR", "worker event must be non-empty")
    event_key = event.strip().casefold()
    target = _WORKER_EVENT_STATES.get(event_key)
    if target is None and event_key != "delivered":
        raise WorkerPacketError("INVALID_TRANSITION", f"unknown worker event: {event}")
    current = _as_dt(now)
    updated = current.isoformat()
    conn = db.connect(_worker_db(home))
    emit: tuple[str | None, str, dict[str, Any]] | None = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _task_row(conn, task_id)
        if row is None:
            raise WorkerPacketError("ORPHAN_TASK", f"unknown task_id: {task_id}")
        if row["packet_sha256"].lower() != digest:
            raise WorkerPacketError("PROTOCOL_ERROR", "task_id is bound to another packet hash")
        if row["state"] in WorkerLifecycle.TERMINAL_STATES:
            # Terminal tasks are immutable; a late transport ack is harmless.
            if event_key == "delivered" or row["state"] == target:
                conn.commit()
                return _result(row, duplicate=True)
            raise WorkerPacketError("INVALID_TRANSITION", "terminal worker task is immutable")
        if event_key == "delivered":
            meta = conn.execute(
                "SELECT delivered_at FROM worker_task_meta WHERE task_id=?", (task_id,)
            ).fetchone()
            lease = _renewal_lease(
                row["lease_expires_at"], current, _lease_seconds(home, lease_seconds)
            )
            if meta is not None and meta["delivered_at"] is not None:
                conn.execute(
                    "UPDATE worker_tasks SET lease_expires_at=?, updated_at=? WHERE task_id=?",
                    (lease, updated, task_id),
                )
                conn.execute(
                    "UPDATE worker_task_meta SET session_id=COALESCE(session_id,?), updated_at=? WHERE task_id=?",
                    (session_id, updated, task_id),
                )
                conn.commit()
                changed = _task_row(conn, task_id)
                assert changed is not None
                return _result(changed, duplicate=True)
            lease = _renewal_lease(
                row["lease_expires_at"], current, _lease_seconds(home, lease_seconds)
            )
            conn.execute(
                "UPDATE worker_tasks SET lease_expires_at=?, updated_at=? WHERE task_id=?",
                (lease, updated, task_id),
            )
            conn.execute(
                "UPDATE worker_task_meta SET delivered_at=?, session_id=COALESCE(session_id,?), updated_at=? WHERE task_id=?",
                (updated, session_id, updated, task_id),
            )
            conn.commit()
            changed = _task_row(conn, task_id)
            assert changed is not None
            return _result(changed)
        if row["state"] == target:
            lease = _renewal_lease(
                row["lease_expires_at"], current, _lease_seconds(home, lease_seconds)
            )
            conn.execute(
                "UPDATE worker_tasks SET lease_expires_at=?, updated_at=? WHERE task_id=?",
                (lease, updated, task_id),
            )
            conn.execute(
                "UPDATE worker_task_meta SET session_id=COALESCE(session_id,?), updated_at=? WHERE task_id=?",
                (session_id, updated, task_id),
            )
            conn.commit()
            changed = _task_row(conn, task_id)
            assert changed is not None
            return _result(changed, duplicate=True)
        if target == WorkerLifecycle.COMPLETED and row["accepted_at"] is None:
            raise WorkerPacketError("PROTOCOL_ERROR", "completed task has no ACCEPTED fact")
        new_state = WorkerLifecycle.transition(row["state"], target)
        lease = _renewal_lease(
            row["lease_expires_at"], current, _lease_seconds(home, lease_seconds)
        )
        accepted_at = row["accepted_at"] or (
            updated if new_state == WorkerLifecycle.WORKING else None
        )
        conn.execute(
            "UPDATE worker_tasks SET state=?, lease_expires_at=?, accepted_at=?, updated_at=? WHERE task_id=?",
            (new_state, lease, accepted_at, updated, task_id),
        )
        conn.execute(
            "UPDATE worker_task_meta SET session_id=COALESCE(session_id,?), updated_at=? WHERE task_id=?",
            (session_id, updated, task_id),
        )
        conn.commit()
        changed = _task_row(conn, task_id)
        assert changed is not None
        if new_state in WorkerLifecycle.TERMINAL_STATES:
            meta = conn.execute(
                "SELECT session_id FROM worker_task_meta WHERE task_id=?", (task_id,)
            ).fetchone()
            emit = (
                meta["session_id"] if meta else session_id,
                new_state,
                {
                    "task_id": task_id,
                    "event": event_key,
                    "updated_at": updated,
                    **(
                        {"result_sha256": payload.get("result_sha256")}
                        if isinstance(payload, dict) and payload.get("result_sha256")
                        else {}
                    ),
                },
            )
        out = _result(changed)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if emit:
        _emit_worker_event(home, emit[0], task_id, emit[1], emit[2])
    return out


def process_worker_event(
    home: Path | str, event: dict[str, Any], **kwargs: Any
) -> dict[str, Any]:
    """Mapping-friendly alias used by adapters and transport bridges."""
    if not isinstance(event, dict):
        raise WorkerPacketError("PROTOCOL_ERROR", "worker event must be an object")
    task_id = event.get("task_id")
    digest = event.get("packet_sha256")
    kind = event.get("event") or event.get("type") or event.get("status")
    return record_worker_event(
        home,
        task_id,
        digest,
        kind,
        payload=event,
        session_id=event.get("session_id"),
        **kwargs,
    )


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in value
    )

def _has_postcondition_evidence(evidence: Any) -> bool:
    """Accept only bounded, executable test or diff evidence."""
    try:
        if len(canonical_json(evidence).encode("utf-8")) > 4_096:
            return False
    except (TypeError, ValueError):
        return False

    def valid_test(item: Any) -> bool:
        if not isinstance(item, dict) or set(item) - {"name", "command", "exit_code"}:
            return False
        identities = [item[key] for key in ("name", "command") if key in item]
        if not identities or any(
            not isinstance(value, str) or not 0 < len(value) <= 512
            for value in identities
        ):
            return False
        return type(item.get("exit_code")) is int

    def valid_diff(item: Any) -> bool:
        if not isinstance(item, dict) or not set(item).issubset(
            {"diff_sha256", "diff_hash"}
        ):
            return False
        sha = item.get("diff_sha256")
        alias = item.get("diff_hash")
        if "diff_sha256" in item:
            if not _is_sha256(sha):
                return False
            return "diff_hash" not in item or alias == sha
        return _is_sha256(alias)

    if isinstance(evidence, dict):
        tests = evidence.get("tests")
        if set(evidence) == {"tests"} and isinstance(tests, list) and len(tests) <= 16:
            return all(valid_test(item) for item in tests) and any(
                type(item["exit_code"]) is int and item["exit_code"] == 0
                for item in tests
            )
        return valid_diff(evidence)
    if isinstance(evidence, list) and len(evidence) <= 16:
        return all(valid_diff(item) for item in evidence) and bool(evidence)
    return False


def _approved_review_evidence(
    home: Path | str, session_id: str | None, task_id: str
) -> Any:
    if not session_id:
        return None
    path = ledger.LedgerStore(home, session_id).dbfile
    if not path.exists():
        return None
    try:
        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM events WHERE event_type='result_reviewed'"
            ).fetchall()
    except sqlite3.Error:
        return None
    for (raw,) in rows:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("task_id") == task_id
            and payload.get("approved") is True
            and isinstance(payload.get("result_sha256"), str)
            and _is_sha256(payload["result_sha256"])
            and payload.get("evidence") is not None
        ):
            return payload["evidence"]
    return None

def _approved_review_result_sha(
    home: Path | str, session_id: str | None, task_id: str
) -> str | None:
    """Return the canonical result hash attached to an approved review."""
    if not session_id:
        return None
    path = ledger.LedgerStore(home, session_id).dbfile
    if not path.exists():
        return None
    try:
        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM events WHERE event_type='result_reviewed'"
            ).fetchall()
    except sqlite3.Error:
        return None
    for (raw,) in rows:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        result_sha = payload.get("result_sha256") if isinstance(payload, dict) else None
        if (
            isinstance(payload, dict)
            and payload.get("task_id") == task_id
            and payload.get("approved") is True
            and isinstance(result_sha, str)
            and _is_sha256(result_sha)
            and payload.get("evidence") is not None
        ):
            return result_sha
    return None


def _approved_review_matches(
    home: Path | str, session_id: str | None, task_id: str, evidence: Any
) -> bool:
    reviewed = _approved_review_evidence(home, session_id, task_id)
    if reviewed is None:
        return False
    return canonical_json(reviewed) == canonical_json(evidence)


def settle_task(
    home: Path | str,
    task_id: str,
    *,
    approved: bool,
    evidence: Any = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Record SETTLED only after approval and an executable postcondition."""
    if type(approved) is not bool or not approved or not _has_postcondition_evidence(evidence):
        raise WorkerPacketError("SETTLEMENT_REJECTED", "approved settlement requires postcondition evidence")
    current = _as_dt(now).isoformat()
    conn = db.connect(_worker_db(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _task_row(conn, task_id)
        if row is None:
            raise WorkerPacketError("ORPHAN_TASK", f"unknown task_id: {task_id}")
        if row["state"] != WorkerLifecycle.COMPLETED:
            raise WorkerPacketError("INVALID_TRANSITION", "only COMPLETED tasks can settle")
        if row["accepted_at"] is None:
            raise WorkerPacketError("PROTOCOL_ERROR", "completed task has no ACCEPTED fact")
        meta = conn.execute(
            "SELECT session_id FROM worker_task_meta WHERE task_id=?", (task_id,)
        ).fetchone()
        if not _approved_review_matches(
            home, meta["session_id"] if meta else None, task_id, evidence
        ):
            raise WorkerPacketError(
                "SETTLEMENT_REJECTED",
                "approved review evidence does not match settlement evidence",
            )
        result_sha = _approved_review_result_sha(
            home, meta["session_id"] if meta else None, task_id
        )
        binding_error = (
            verify_result_binding(home, task_id, row["packet_sha256"], result_sha)
            if result_sha is not None
            else "RESULT_NOT_RECORDED"
        )
        if binding_error is not None:
            raise WorkerPacketError(
                "SETTLEMENT_REJECTED",
                "approved review result is not durably bound to a worker result",
            )
        if row["settled_at"] is None:
            conn.execute(
                "UPDATE worker_tasks SET settled_at=?, updated_at=? WHERE task_id=?",
                (current, current, task_id),
            )
        conn.commit()
        row = _task_row(conn, task_id)
        assert row is not None
        return _result(row, duplicate=row["settled_at"] != current)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reap(
    home: Path | str,
    *,
    now: datetime | str | None = None,
    lease_seconds: int | float | None = None,
) -> list[dict[str, Any]]:
    """Fail expired WORKING tasks and redeliver then fail unacknowledged ones."""
    current = _as_dt(now)
    now_text = current.isoformat()
    renewal_seconds = _lease_seconds(home, lease_seconds)
    expired: list[tuple[str | None, str, str, dict[str, Any]]] = []
    redeliveries: list[tuple[str | None, str, dict[str, Any]]] = []
    conn = db.connect(_worker_db(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT wt.*, wm.session_id, wm.redeliveries, wm.dispatch_payload "
            "FROM worker_tasks wt LEFT JOIN worker_task_meta wm ON wm.task_id=wt.task_id "
            "WHERE wt.lease_expires_at < ? AND wt.state IN (?, ?)",
            (now_text, WorkerLifecycle.WORKING, WorkerLifecycle.SUBMITTED),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            if row["state"] == WorkerLifecycle.SUBMITTED:
                if not row.get("dispatch_payload"):
                    conn.execute(
                        "UPDATE worker_tasks SET state=?,updated_at=? WHERE task_id=?",
                        (WorkerLifecycle.FAILED, now_text, row["task_id"]),
                    )
                    conn.execute(
                        "UPDATE worker_task_meta SET failure_reason=?,updated_at=? WHERE task_id=?",
                        ("UNACKNOWLEDGED", now_text, row["task_id"]),
                    )
                    item = {
                        "task_id": row["task_id"],
                        "action": "failed",
                        "state": WorkerLifecycle.FAILED,
                        "failure_reason": "UNACKNOWLEDGED",
                    }
                    out.append(item)
                    expired.append(
                        (row.get("session_id"), row["task_id"], WorkerLifecycle.FAILED, item)
                    )
                    continue
                if int(row.get("redeliveries") or 0) == 0:
                    lease = (current + timedelta(seconds=renewal_seconds)).isoformat()
                    conn.execute("UPDATE worker_task_meta SET redeliveries=1,updated_at=? WHERE task_id=?", (now_text, row["task_id"]))
                    conn.execute("UPDATE worker_tasks SET lease_expires_at=?,updated_at=? WHERE task_id=?", (lease, now_text, row["task_id"]))
                    dispatch = None
                    if row.get("dispatch_payload"):
                        try:
                            parsed = json.loads(row["dispatch_payload"])
                            dispatch = parsed if isinstance(parsed, dict) else None
                        except (TypeError, json.JSONDecodeError):
                            pass
                    item = {"task_id": row["task_id"], "action": "redelivered", "state": WorkerLifecycle.SUBMITTED, "packet_sha256": row["packet_sha256"]}
                    if dispatch is not None:
                        item["packet"] = dispatch
                    out.append(item)
                    redeliveries.append((row.get("session_id"), row["task_id"], item))
                    continue
                conn.execute("UPDATE worker_tasks SET state=?,updated_at=? WHERE task_id=?", (WorkerLifecycle.FAILED, now_text, row["task_id"]))
                conn.execute("UPDATE worker_task_meta SET failure_reason=?,updated_at=? WHERE task_id=?", ("UNACKNOWLEDGED", now_text, row["task_id"]))
                state, action, reason = WorkerLifecycle.FAILED, "failed", "UNACKNOWLEDGED"
            else:
                conn.execute("UPDATE worker_tasks SET state=?,updated_at=? WHERE task_id=?", (WorkerLifecycle.FAILED, now_text, row["task_id"]))
                conn.execute("UPDATE worker_task_meta SET failure_reason=?,updated_at=? WHERE task_id=?", ("lease_expired", now_text, row["task_id"]))
                state, action, reason = WorkerLifecycle.FAILED, "failed", "lease_expired"
            item = {"task_id": row["task_id"], "action": action, "state": state, "failure_reason": reason}
            out.append(item)
            expired.append((row.get("session_id"), row["task_id"], state, item))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for session_id, task_id, item in redeliveries:
        _emit_worker_event(home, session_id, task_id, WorkerLifecycle.SUBMITTED, {**item, "event": "redelivered", "updated_at": now_text})
    for session_id, task_id, state, item in expired:
        _emit_worker_event(home, session_id, task_id, state, {**item, "updated_at": now_text})
    return out


submit_task = register_task
handle_event = process_worker_event
worker_event = record_worker_event

def correction_metadata(packet: Any) -> dict[str, Any]:
    """Canonical, bounded metadata shared by ledger and telemetry callers."""
    return {
        "correction_sha256": packet.canonical_hash(),
        "task_id": packet.task_id,
        "original_result_sha256": packet.original_result_sha256,
        "correction_attempt": packet.correction_attempt,
        "requested_change_count": len(packet.requested_changes),
        "evidence_requirement_count": len(packet.evidence_requirements),
    }


def canonical_protocol_hash(value: Any) -> str:
    """Hash arbitrary protocol data using the Brain canonical JSON rules."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
