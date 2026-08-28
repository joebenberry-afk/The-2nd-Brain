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
from pathlib import Path
from typing import Any

from . import artifacts, jit, ledger, semantic
from .contracts import (
    WORKER_CONTEXT_MAX_CHARS,
    WORKER_CONTEXT_MAX_TOTAL_CHARS,
    WORKER_PACKET_MAX_BYTES,
    WorkerContextResolution,
    WorkerPacketError,
    WorkerTaskPacket,
    canonical_json,
    stable_content_hash,
)
from .errors import BrainError


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


def context_metadata(resolved: list[WorkerContextResolution]) -> dict[str, Any]:
    """Return bounded, privacy-safe resolution metadata for Brain records."""
    entries = [item.validate().metadata() for item in resolved]
    visible_chars = sum(len(item.content) for item in resolved)
    visible_bytes = sum(len(item.content.encode("utf-8")) for item in resolved)
    return {
        "resolved_count": len(entries),
        "visible_chars": visible_chars,
        "visible_bytes": visible_bytes,
        "visible_tokens_estimate": max(1, visible_chars // 4) if visible_chars else 0,
        "source_chars": sum(int(item["content_chars"]) for item in entries),
        "refs": entries,
        "resolution_sha256": stable_content_hash(entries),
    }



def _latest_context_snapshot(
    home: Path, parent_session_id: str, packet_sha256: str
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
        if (
            isinstance(snapshot, dict)
            and snapshot.get("packet_sha256") == packet_sha256
        ):
            return snapshot
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
    metadata = context_metadata(resolved)
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
        "context_handoff_tokens_estimate": max(1, handoff_bytes // 4),
        "context_delta_bytes": delta_bytes,
        "context_delta_tokens_estimate": max(1, delta_bytes // 4) if delta_bytes else 0,
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
    latest = _latest_context_snapshot(Path(home), packet.parent_session_id, packet.canonical_hash())
    if latest is None or latest.get("context_fingerprint") != handoff.get("context_fingerprint"):
        raise WorkerPacketError("CONTEXT_HANDOFF_MISMATCH", "handoff snapshot is not current")
    if (
        handoff.get("mode") == "unchanged"
        and (
            handoff.get("resolved_context")
            or (handoff.get("context_delta") or {}).get("changed_refs")
        )
    ):
        raise WorkerPacketError(
            "CONTEXT_HANDOFF_MALFORMED", "unchanged handoff carries context"
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
