"""Thin Hermes-to-Second-Brain lifecycle adapter.

Hermes owns the plugin lifecycle and ephemeral prompt injection. This module
only translates those callbacks into the existing Brain session, AutoInject,
semantic writeback, telemetry, and ledger primitives. It deliberately does
not maintain a Hermes-specific memory or retrieval store.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import (
    artifacts,
    autoinject,
    contracts,
    firewall,
    handoff,
    ledger,
    model_routing,
    router,
    skills,
    vmem,
    worker_protocol,
)
from .errors import BrainError

ADAPTER_VERSION = "0.1.0"
_HOST = "hermes"
_SUPPORTED_EVENTS = {
    "session_start",
    "pre_llm_call",
    "post_tool_call",
    "post_api_request",
    "api_request_error",
    "writeback",
    "session_end",
    "worker_task_prepare",
    "worker_task_request",
    "worker_result_review",
    "worker_result_correction",
    "worker_result_corrected",
    "handoff_create",
    "handoff_read",
}
_VMEM_HOT_CONTEXT_BUDGET = 512
_TOOL_RESULT_MAX_CHARS = 4000
_ATTRIBUTION_FIELD_MAX_CHARS = 64
_MODEL_CANDIDATE_KEYS = ("candidates", "model_candidates", "candidate_metadata", "models")
_MODEL_ROUTING_MAX_ERROR_CHARS = 128


@dataclass(frozen=True)
class HermesBinding:
    """Stable mapping of one Hermes bot/session to Brain identities."""

    bot_name: str
    bot_role: str
    hermes_session_id: str
    host_session_id: str
    brain_session_id: str
    agent_id: str
    project_id: str
    repo_root: str
    provider: str
    model: str
    branch_id: str
    session: contracts.BrainSessionIdentity


def _first_text(payload: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return default


def _git_capture(cwd: str, args: list[str]) -> str | None:
    if not cwd:
        return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return value or None


def _repo_root(payload: dict[str, Any]) -> str:
    configured = _first_text(payload, "repo_root", "cwd")
    if not configured:
        configured = str(Path.cwd())
    return _git_capture(configured, ["rev-parse", "--show-toplevel"]) or configured


def telemetry_stem(session_id: str) -> str:
    """Return the existing AutoInject telemetry filename stem."""
    return autoinject._sanitize_stem(session_id)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_text(value: Any, limit: int = _TOOL_RESULT_MAX_CHARS) -> str:
    """Convert host data to bounded, deterministic text."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = contracts.canonical_json(value)
        except Exception:
            text = str(value)
    return text[:limit]


def _raw_tool_result(value: Any) -> tuple[str, bytes]:
    """Decode the complete preserve-first Hermes result transport."""
    if isinstance(value, dict) and "__hermes_raw_bytes_b64" in value:
        raw_bytes = base64.b64decode(str(value["__hermes_raw_bytes_b64"]))
        return raw_bytes.decode("utf-8", errors="replace"), raw_bytes
    if isinstance(value, dict) and "__hermes_raw_text" in value:
        text = str(value["__hermes_raw_text"])
        return text, text.encode("utf-8")
    if isinstance(value, str):
        return value, value.encode("utf-8")
    text = contracts.canonical_json(value)
    return text, text.encode("utf-8")


def _command_from_args(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("command", "cmd"):
            command = value.get(key)
            if isinstance(command, str):
                return command
    return _bounded_text(value, 1000)


def _default_role(bot_name: str) -> str:
    return {
        "brain-dev": "dev",
        "brain-validator": "validator",
        "brain-integrator": "integrator",
    }.get(bot_name.lower(), "worker")


def resolve_binding(home: Path | str, payload: dict[str, Any]) -> HermesBinding:
    """Resolve Hermes metadata into one stable Brain session binding.

    The raw Hermes session identifier is kept as metadata, while the canonical
    Brain host-session key includes the configured bot name. This prevents a
    reconnect from creating unrelated Brain state and keeps the three team bots
    distinguishable even when they use the same project.
    """
    home_path = Path(home)
    bot_name = _first_text(
        payload,
        "bot_name",
        "bot",
        default="hermes-bot",
    )
    bot_role = _first_text(payload, "bot_role", "role", default=_default_role(bot_name))
    hermes_session_id = _first_text(
        payload,
        "hermes_session_id",
        "session_id",
        default=os.environ.get("HERMES_SESSION_ID", "hermes-anon"),
    )
    host_session_id = f"{_HOST}:{bot_name}:{hermes_session_id}"
    brain_session_id = ledger.internal_session_id(host_session_id)
    agent_id = f"{_HOST}:{bot_name}"
    repo_root = _repo_root(payload)

    explicit_project = _first_text(payload, "project_id", "project") or None
    try:
        project_id = autoinject._resolve_project_id(home_path, repo_root, explicit_project)
    except Exception:
        project_id = explicit_project or "default"

    provider = _first_text(payload, "provider", default="unknown")
    model = _first_text(payload, "model", default="unknown")
    branch_id = _first_text(
        payload,
        "branch_id",
        "branch",
        default=_git_capture(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"]) or "main",
    )
    session = contracts.BrainSessionIdentity(
        internal_session_id=brain_session_id,
        host=_HOST,
        host_session_id=host_session_id,
        project_id=project_id,
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=contracts.LEDGER_SCHEMA_VERSION,
    )
    return HermesBinding(
        bot_name=bot_name,
        bot_role=bot_role,
        hermes_session_id=hermes_session_id,
        host_session_id=host_session_id,
        brain_session_id=brain_session_id,
        agent_id=agent_id,
        project_id=project_id,
        repo_root=repo_root,
        provider=provider,
        model=model,
        branch_id=branch_id,
        session=session,
    )


def _identity_fields(binding: HermesBinding) -> dict[str, Any]:
    return {
        "harness": _HOST,
        "adapter_version": ADAPTER_VERSION,
        "bot_name": binding.bot_name,
        "bot_role": binding.bot_role,
        "hermes_session_id": binding.hermes_session_id,
        "brain_session_id": binding.brain_session_id,
        "project_id": binding.project_id,
        "repo_root": binding.repo_root,
        "provider": binding.provider,
        "model": binding.model,
        "branch_id": binding.branch_id,
    }


def _event_id(binding: HermesBinding, event_type: contracts.LifecycleEventType, key: str) -> str:
    digest = contracts.stable_content_hash(
        {"host_session_id": binding.host_session_id, "event_type": event_type.value, "key": key}
    )[:24]
    return f"hermes-{event_type.value}-{digest}"


def _agent_identity(binding: HermesBinding) -> contracts.AgentIdentity:
    return contracts.AgentIdentity(
        agent_id=binding.agent_id,
        internal_session_id=binding.brain_session_id,
        host_agent_id=binding.bot_name,
        parent_agent_id=None,
        role_profile=binding.bot_role,
        model=binding.model,
        provider=binding.provider,
        created_at=binding.session.created_at,
    )


def _worker_payload(
    binding: HermesBinding,
    packet: contracts.WorkerTaskPacket,
    result: contracts.WorkerResultPacket | None = None,
    status: str = "created",
    failure_code: str | None = None,
    context_metadata: dict[str, Any] | None = None,
    correction: contracts.WorkerCorrectionPacket | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        **_identity_fields(binding),
        "task_id": packet.task_id,
        "parent_session_id": packet.parent_session_id,
        "project_id": packet.project_id,
        "repo_root": packet.repo_root,
        "requested_role": packet.requested_role,
        "fanout": packet.fanout,
        "fanout_index": packet.fanout_index,
        "depth": packet.depth,
        "packet_bytes": len(packet.canonical_json().encode("utf-8")),
        "packet_sha256": packet.canonical_hash(),
        "status": status,
    }
    if context_metadata is not None:
        payload.update(
            {
                "context_ref_count": context_metadata.get("resolved_count", 0),
                "context_visible_chars": context_metadata.get("visible_chars", 0),
                "context_visible_bytes": context_metadata.get("visible_bytes", 0),
                "context_visible_tokens_estimate": context_metadata.get(
                    "visible_tokens_estimate", 0
                ),
                "context_source_chars": context_metadata.get("source_chars", 0),
                "context_resolution_sha256": context_metadata.get("resolution_sha256"),
                "context_mode": context_metadata.get("mode"),
                "context_reused": context_metadata.get("reused", False),
                "context_cache_hit": context_metadata.get("cache_hit", False),
                "context_fingerprint": context_metadata.get("context_fingerprint"),
                "previous_context_fingerprint": context_metadata.get(
                    "previous_context_fingerprint"
                ),
                "context_snapshot_sha256": context_metadata.get("context_snapshot_sha256"),
                "context_handoff_bytes": context_metadata.get("context_handoff_bytes", 0),
                "context_handoff_tokens_estimate": context_metadata.get(
                    "context_handoff_tokens_estimate", 0
                ),
                "context_delta_bytes": context_metadata.get("context_delta_bytes", 0),
                "context_delta_tokens_estimate": context_metadata.get(
                    "context_delta_tokens_estimate", 0
                ),
                "context_changed_ref_count": context_metadata.get("changed_ref_count", 0),
                "context_removed_ref_count": context_metadata.get("removed_ref_count", 0),
                "jit_body_sha256": context_metadata.get("jit_body_sha256"),
                "jit_body_bytes": context_metadata.get("jit_body_bytes", 0),
                "jit_delta_sha256": context_metadata.get("jit_delta_sha256"),
                "jit_delta_bytes": context_metadata.get("jit_delta_bytes", 0),
            }
        )
    if failure_code:
        payload["failure_code"] = failure_code
    if correction is not None:
        payload.update(
            {
                "correction_sha256": correction.canonical_hash(),
                "original_result_sha256": correction.original_result_sha256,
                "correction_attempt": correction.correction_attempt,
            }
        )
    if result is not None:
        payload.update(
            {
                "worker_session_id": result.worker_identity.internal_session_id,
                "worker_agent_id": result.worker_identity.agent_id,
                "worker_bot": result.worker_identity.host_agent_id,
                "worker_role": result.worker_identity.role_profile,
                "result_bytes": len(result.canonical_json().encode("utf-8")),
                "result_sha256": result.canonical_hash(),
                "failure_code": result.failure_code,
                "retryable": result.retryable,
                "correction_of_hash": result.correction_of_hash,
                "correction_attempt": result.correction_attempt,
            }
        )
    return payload


def _resolve_worker_context(
    home: Path, packet: contracts.WorkerTaskPacket
) -> tuple[list[contracts.WorkerContextResolution], dict[str, Any]]:
    resolved = worker_protocol.resolve_context_refs(home, packet)
    return resolved, worker_protocol.context_metadata(resolved, home=home)


def _context_event_payload(
    binding: HermesBinding,
    packet: contracts.WorkerTaskPacket,
    metadata: dict[str, Any],
    *,
    status: str = "resolved",
    failure_code: str | None = None,
) -> dict[str, Any]:
    payload = {
        **_identity_fields(binding),
        "task_id": packet.task_id,
        "parent_session_id": packet.parent_session_id,
        "packet_sha256": packet.canonical_hash(),
        "status": status,
        "context_ref_count": metadata.get("resolved_count", 0),
        "context_visible_chars": metadata.get("visible_chars", 0),
        "context_visible_bytes": metadata.get("visible_bytes", 0),
        "context_visible_tokens_estimate": metadata.get("visible_tokens_estimate", 0),
        "context_source_chars": metadata.get("source_chars", 0),
        "context_resolution_sha256": metadata.get("resolution_sha256"),
        "context_snapshot_sha256": metadata.get("context_snapshot_sha256"),
        "context_mode": metadata.get("mode"),
        "context_reused": metadata.get("reused", False),
        "context_cache_hit": metadata.get("cache_hit", False),
        "context_fingerprint": metadata.get("context_fingerprint"),
        "previous_context_fingerprint": metadata.get("previous_context_fingerprint"),
        "context_handoff_bytes": metadata.get("context_handoff_bytes", 0),
        "context_handoff_tokens_estimate": metadata.get(
            "context_handoff_tokens_estimate", 0
        ),
        "context_delta_bytes": metadata.get("context_delta_bytes", 0),
        "context_delta_tokens_estimate": metadata.get("context_delta_tokens_estimate", 0),
        "context_changed_ref_count": metadata.get("changed_ref_count", 0),
        "context_removed_ref_count": metadata.get("removed_ref_count", 0),
        "jit_body_sha256": metadata.get("jit_body_sha256"),
        "jit_body_bytes": metadata.get("jit_body_bytes", 0),
        "jit_delta_sha256": metadata.get("jit_delta_sha256"),
        "jit_delta_bytes": metadata.get("jit_delta_bytes", 0),
    }
    if failure_code:
        payload["failure_code"] = failure_code
    return payload


def _append_context_resolution(
    home: Path,
    binding: HermesBinding,
    packet: contracts.WorkerTaskPacket,
    metadata: dict[str, Any],
) -> None:
    payload = _context_event_payload(binding, packet, metadata)
    payload["context_refs"] = metadata["refs"]
    _append_event(
        home,
        binding,
        contracts.LifecycleEventType.TASK_CONTEXT_RESOLVED,
        payload,
        key=f"{packet.task_id}:context:{metadata['resolution_sha256']}",
    )
    autoinject._append_telemetry(
        home, binding.host_session_id, "hermes_worker_context_resolved", payload
    )


def _unavailable_result(packet: contracts.WorkerTaskPacket) -> contracts.WorkerResultPacket:
    return contracts.WorkerResultPacket(
        task_id=packet.task_id,
        worker_identity=contracts.AgentIdentity(
            agent_id=f"unavailable:{packet.requested_role}",
            internal_session_id="unavailable",
            host_agent_id=f"Brain-{packet.requested_role.title()}",
            parent_agent_id=None,
            role_profile=packet.requested_role,
            model="unknown",
            provider="hermes",
            created_at=packet.driver_identity.created_at,
        ),
        status="failed",
        failure_code="WORKER_UNAVAILABLE",
        retryable=True,
        limitations=["persistent worker profile was not configured"],
    ).validate()


def prepare_worker_task(
    home: Path | str, binding: HermesBinding, packet_data: dict[str, Any]
) -> dict[str, Any]:
    """Validate and resolve a task before a host invokes its worker."""
    if binding.bot_role not in contracts.COORDINATOR_ROLES:
        return {
            **_response_base(binding, "worker_task_prepare"),
            "status": "failed",
            "failure_code": "UNAUTHORIZED_COORDINATOR",
        }
    home_path = Path(home)
    try:
        packet = contracts.WorkerTaskPacket.from_dict(packet_data)
        _register_binding(home_path, binding)
        handoff = worker_protocol.prepare_context_handoff(home_path, packet)
    except contracts.WorkerPacketError as exc:
        return {
            **_response_base(binding, "worker_task_prepare"),
            "status": "failed",
            "failure_code": exc.code,
        }
    return {
        **_response_base(binding, "worker_task_prepare"),
        "status": "prepared",
        "task_id": packet.task_id,
        "packet_sha256": packet.canonical_hash(),
        "context_metadata": worker_protocol.handoff_metadata(handoff),
        "context_handoff": handoff,
    }


def request_worker_task(
    home: Path | str,
    binding: HermesBinding,
    packet_data: dict[str, Any],
    result_data: dict[str, Any] | None = None,
    context_handoff_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and correlate one bounded task; never execute delegated work locally."""
    if binding.bot_role not in contracts.COORDINATOR_ROLES:
        return {
            **_response_base(binding, "worker_task_request"),
            "status": "failed",
            "failure_code": "UNAUTHORIZED_COORDINATOR",
        }
    try:
        packet = contracts.WorkerTaskPacket.from_dict(packet_data)
    except contracts.WorkerPacketError as exc:
        return {
            **_response_base(binding, "worker_task_request"),
            "status": "failed",
            "failure_code": exc.code,
        }
    home_path = Path(home)
    _register_binding(home_path, binding)
    try:
        if context_handoff_data is None:
            context_handoff = worker_protocol.prepare_context_handoff(home_path, packet)
        else:
            context_handoff = worker_protocol.validate_context_handoff(
                home_path, packet, context_handoff_data
            )
        context_metadata = worker_protocol.handoff_metadata(context_handoff)
    except contracts.WorkerPacketError as exc:
        base = _worker_payload(binding, packet, status="failed", failure_code=exc.code)
        for event_type, suffix in (
            (contracts.LifecycleEventType.TASK_CREATED, "created"),
            (contracts.LifecycleEventType.TASK_ASSIGNED, "assigned"),
        ):
            _append_event(home_path, binding, event_type, base, key=f"{packet.task_id}:{suffix}")
        context_failure = _context_event_payload(
            binding,
            packet,
            {
                "resolved_count": 0,
                "visible_chars": 0,
                "source_chars": 0,
                "resolution_sha256": "",
            },
            status="failed",
            failure_code=exc.code,
        )
        _append_event(
            home_path,
            binding,
            contracts.LifecycleEventType.TASK_CONTEXT_RESOLVED,
            context_failure,
            key=f"{packet.task_id}:context-failed:{exc.code}",
        )
        _append_event(
            home_path,
            binding,
            contracts.LifecycleEventType.WORKER_FAILED,
            base,
            key=f"{packet.task_id}:context-failed",
        )
        autoinject._append_telemetry(
            home_path, binding.host_session_id, "hermes_worker_lifecycle", base
        )
        return {
            **_response_base(binding, "worker_task_request"),
            "status": "failed",
            "failure_code": exc.code,
            "task_id": packet.task_id,
        }

    base = _worker_payload(binding, packet, context_metadata=context_metadata)
    _append_event(
        home_path,
        binding,
        contracts.LifecycleEventType.TASK_CREATED,
        base,
        key=f"{packet.task_id}:created",
    )
    _append_event(
        home_path,
        binding,
        contracts.LifecycleEventType.TASK_ASSIGNED,
        base,
        key=f"{packet.task_id}:assigned",
    )
    _append_context_resolution(home_path, binding, packet, context_metadata)
    _append_event(
        home_path,
        binding,
        contracts.LifecycleEventType.WORKER_STARTED,
        base,
        key=f"{packet.task_id}:started",
    )
    if result_data is None:
        result = _unavailable_result(packet)
    else:
        try:
            result = contracts.WorkerResultPacket.from_dict(result_data)
            if result.task_id != packet.task_id:
                raise contracts.WorkerPacketError("MALFORMED_RESULT", "task_id does not correlate")
        except contracts.WorkerPacketError as exc:
            result = contracts.WorkerResultPacket(
                packet.task_id, _agent_identity(binding), "failed", failure_code=exc.code
            ).validate()
    event_type = (
        contracts.LifecycleEventType.WORKER_COMPLETED
        if result.status == "completed"
        else contracts.LifecycleEventType.WORKER_CANCELLED
        if result.status == "cancelled"
        else contracts.LifecycleEventType.WORKER_FAILED
    )
    result_payload = _worker_payload(
        binding, packet, result, result.status, context_metadata=context_metadata
    )
    _append_event(
        home_path, binding, event_type, result_payload, key=f"{packet.task_id}:{result.status}"
    )
    _append_event(
        home_path,
        binding,
        contracts.LifecycleEventType.RESULT_RETURNED,
        result_payload,
        key=f"{packet.task_id}:returned",
    )
    autoinject._append_telemetry(
        home_path, binding.host_session_id, "hermes_worker_lifecycle", result_payload
    )
    return {
        **_response_base(binding, "worker_task_request"),
        "status": result.status,
        "failure_code": result.failure_code,
        "task_id": packet.task_id,
        "packet_bytes": len(packet.canonical_json().encode("utf-8")),
        "packet_sha256": packet.canonical_hash(),
        "result_sha256": result.canonical_hash(),
        "context_metadata": context_metadata,
        "context_handoff": context_handoff,
        "result": json.loads(result.canonical_json()),
    }


def review_worker_result(
    home: Path | str, binding: HermesBinding, result_data: dict[str, Any], approved: bool = True
) -> dict[str, Any]:
    if binding.bot_role not in contracts.COORDINATOR_ROLES:
        return {
            **_response_base(binding, "worker_result_review"),
            "status": "failed",
            "failure_code": "UNAUTHORIZED_COORDINATOR",
        }
    try:
        result = contracts.WorkerResultPacket.from_dict(result_data)
    except contracts.WorkerPacketError as exc:
        return {
            **_response_base(binding, "worker_result_review"),
            "status": "failed",
            "failure_code": exc.code,
        }
    payload = {
        **_identity_fields(binding),
        "task_id": result.task_id,
        "worker_session_id": result.worker_identity.internal_session_id,
        "worker_agent_id": result.worker_identity.agent_id,
        "worker_role": result.worker_identity.role_profile,
        "result_bytes": len(result.canonical_json().encode("utf-8")),
        "result_sha256": result.canonical_hash(),
        "correction_of_hash": result.correction_of_hash,
        "correction_attempt": result.correction_attempt,
        "reviewed": True,
        "approved": bool(approved),
        "status": "reviewed" if approved else "rejected",
    }
    _append_event(
        Path(home),
        binding,
        contracts.LifecycleEventType.RESULT_REVIEWED,
        payload,
        key=f"{result.task_id}:review:{int(approved)}:{result.canonical_hash()}",
    )
    autoinject._append_telemetry(
        Path(home), binding.host_session_id, "hermes_worker_result_reviewed", payload
    )
    return {
        **_response_base(binding, "worker_result_review"),
        "status": payload["status"],
        "task_id": result.task_id,
        "result_sha256": result.canonical_hash(),
    }


def request_worker_correction(
    home: Path | str,
    binding: HermesBinding,
    packet_data: dict[str, Any],
    result_data: dict[str, Any],
    reason: str,
    requested_changes: list[str] | None = None,
    evidence_requirements: list[str] | None = None,
    correction_attempt: int = 1,
) -> dict[str, Any]:
    """Reject one result and return a bounded same-task correction packet."""
    if binding.bot_role not in contracts.COORDINATOR_ROLES:
        return {
            **_response_base(binding, "worker_result_correction"),
            "status": "failed",
            "failure_code": "UNAUTHORIZED_COORDINATOR",
        }
    try:
        packet = contracts.WorkerTaskPacket.from_dict(packet_data)
        result = contracts.WorkerResultPacket.from_dict(result_data)
        if packet.task_id != result.task_id:
            raise contracts.WorkerPacketError("MALFORMED_RESULT", "task_id does not correlate")
        correction = contracts.WorkerCorrectionPacket(
            task_id=packet.task_id,
            parent_session_id=packet.parent_session_id,
            worker_identity=result.worker_identity,
            reviewer_identity=_agent_identity(binding),
            original_result_sha256=result.canonical_hash(),
            reason=reason,
            requested_changes=requested_changes or [],
            evidence_requirements=evidence_requirements or [],
            correction_attempt=correction_attempt,
        ).validate()
    except contracts.WorkerPacketError as exc:
        return {
            **_response_base(binding, "worker_result_correction"),
            "status": "failed",
            "failure_code": exc.code,
        }

    rejected = review_worker_result(home, binding, result_data, approved=False)
    if rejected.get("status") != "rejected":
        return rejected
    payload = {
        **_identity_fields(binding),
        "task_id": correction.task_id,
        "parent_session_id": correction.parent_session_id,
        "worker_session_id": correction.worker_identity.internal_session_id,
        "worker_agent_id": correction.worker_identity.agent_id,
        "worker_role": correction.worker_identity.role_profile,
        "original_result_sha256": correction.original_result_sha256,
        "correction_sha256": correction.canonical_hash(),
        "correction_attempt": correction.correction_attempt,
        "requested_change_count": len(correction.requested_changes),
        "evidence_requirement_count": len(correction.evidence_requirements),
        "status": "requested",
    }
    _append_event(
        Path(home),
        binding,
        contracts.LifecycleEventType.RESULT_CORRECTION_REQUESTED,
        payload,
        key=f"{correction.task_id}:correction:{correction.correction_attempt}:{correction.canonical_hash()}",
    )
    autoinject._append_telemetry(
        Path(home), binding.host_session_id, "hermes_worker_result_correction_requested", payload
    )
    return {
        **_response_base(binding, "worker_result_correction"),
        "status": "correction_requested",
        "task_id": correction.task_id,
        "original_result_sha256": correction.original_result_sha256,
        "correction_sha256": correction.canonical_hash(),
        "correction": json.loads(correction.canonical_json()),
    }


def return_corrected_worker_result(
    home: Path | str,
    binding: HermesBinding,
    packet_data: dict[str, Any],
    original_result_data: dict[str, Any],
    correction_data: dict[str, Any],
    corrected_result_data: dict[str, Any],
    context_handoff_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, hash, and return one corrected result for final review."""
    if binding.bot_role not in contracts.COORDINATOR_ROLES:
        return {
            **_response_base(binding, "worker_result_corrected"),
            "status": "failed",
            "failure_code": "UNAUTHORIZED_COORDINATOR",
        }
    try:
        packet = contracts.WorkerTaskPacket.from_dict(packet_data)
        original = contracts.WorkerResultPacket.from_dict(original_result_data)
        correction = contracts.WorkerCorrectionPacket.from_dict(correction_data)
        corrected = contracts.WorkerResultPacket.from_dict(corrected_result_data)
        original_hash = original.canonical_hash()
        if packet.task_id != original.task_id or packet.task_id != corrected.task_id:
            raise contracts.WorkerPacketError("MALFORMED_RESULT", "task_id does not correlate")
        if correction.task_id != packet.task_id:
            raise contracts.WorkerPacketError(
                "MALFORMED_CORRECTION", "correction task_id does not correlate"
            )
        if correction.original_result_sha256 != original_hash:
            raise contracts.WorkerPacketError(
                "CORRECTION_MISMATCH", "original result hash does not match"
            )
        if corrected.correction_of_hash != original_hash:
            raise contracts.WorkerPacketError(
                "CORRECTION_MISMATCH", "corrected result does not cite original hash"
            )
        if corrected.correction_attempt != correction.correction_attempt:
            raise contracts.WorkerPacketError(
                "CORRECTION_MISMATCH", "correction attempt does not correlate"
            )
        if (
            corrected.worker_identity.host_agent_id != correction.worker_identity.host_agent_id
            or corrected.worker_identity.role_profile != correction.worker_identity.role_profile
        ):
            raise contracts.WorkerPacketError(
                "CORRECTION_MISMATCH", "corrected worker identity does not correlate"
            )
        if context_handoff_data is None:
            context_handoff = worker_protocol.prepare_context_handoff(Path(home), packet)
        else:
            context_handoff = worker_protocol.validate_context_handoff(
                Path(home), packet, context_handoff_data
            )
        context_metadata = worker_protocol.handoff_metadata(context_handoff)
    except contracts.WorkerPacketError as exc:
        return {
            **_response_base(binding, "worker_result_corrected"),
            "status": "failed",
            "failure_code": exc.code,
        }

    payload = _worker_payload(
        binding,
        packet,
        corrected,
        "corrected",
        context_metadata=context_metadata,
        correction=correction,
    )
    _append_event(
        Path(home),
        binding,
        contracts.LifecycleEventType.RESULT_CORRECTED,
        payload,
        key=f"{packet.task_id}:corrected:{correction.correction_attempt}:{corrected.canonical_hash()}",
    )
    _append_event(
        Path(home),
        binding,
        contracts.LifecycleEventType.RESULT_RETURNED,
        payload,
        key=f"{packet.task_id}:corrected-returned:{correction.correction_attempt}:{corrected.canonical_hash()}",
    )
    autoinject._append_telemetry(
        Path(home), binding.host_session_id, "hermes_worker_result_corrected", payload
    )
    return {
        **_response_base(binding, "worker_result_corrected"),
        "status": "completed",
        "task_id": packet.task_id,
        "result_sha256": corrected.canonical_hash(),
        "correction_sha256": correction.canonical_hash(),
        "context_metadata": context_metadata,
        "context_handoff": context_handoff,
        "result": json.loads(corrected.canonical_json()),
    }


def _injection_attribution(
    binding: HermesBinding,
    task: str,
    turn_id: str | None,
    decision: contracts.BrainInjectionDecision,
) -> dict[str, str]:
    """Build one bounded, privacy-safe attribution shared by all surfaces.

    The decision is always the value returned by the live AutoInject lifecycle
    authority.  The identifier contains no task text and is stable for the
    same host session, task hash, turn, and decision.
    """
    task_sha256 = _sha256(task)
    decision_value = decision.decision.value
    correlation = {
        "host_session_id": binding.host_session_id,
        "task_sha256": task_sha256,
        "turn_id": turn_id or "",
        "decision": decision_value,
    }
    decision_id = f"hermes-injection-{contracts.stable_content_hash(correlation)[:24]}"
    reason_code = (
        decision.reason.value
        if decision.reason is not None
        else ("NO_TASK" if not task else "INJECTED")
    )
    return {
        "injection_decision_id": decision_id,
        "decision_source": "autoinject",
        "decision": decision_value,
        "profile": _bounded_text(binding.bot_role, _ATTRIBUTION_FIELD_MAX_CHARS),
        "reason_code": _bounded_text(reason_code, _ATTRIBUTION_FIELD_MAX_CHARS),
    }


def _append_event(
    home: Path,
    binding: HermesBinding,
    event_type: contracts.LifecycleEventType,
    payload: dict[str, Any],
    *,
    key: str,
    visibility: contracts.SurfaceVisibility = contracts.SurfaceVisibility.BOOKKEEPING,
) -> bool:
    event = contracts.BrainLifecycleEvent(
        seq=0,
        event_id=_event_id(binding, event_type, key),
        internal_session_id=binding.brain_session_id,
        agent_id=binding.agent_id,
        event_type=event_type,
        timestamp=datetime.now(UTC).isoformat(),
        surface_visibility=visibility,
        ignorable=False,
        payload=payload,
    )
    try:
        with ledger.LedgerStore(home, binding.host_session_id).open(create=True) as store:
            store.append_events([event])
        return True
    except Exception:
        # The hook must never break Hermes. The telemetry path is also
        # best-effort, so a ledger failure is represented by the missing row.
        return False


def _register_binding(home: Path, binding: HermesBinding) -> None:
    already_started = autoinject._has_session_started(home, binding.host_session_id)
    lifecycle = autoinject.BrainLifecycle(home, binding.session)
    lifecycle.start_session(binding.session)

    with ledger.LedgerStore(home, binding.host_session_id).open(create=True) as store:
        store.create_session(binding.session)
        store.register_agent(
            {
                "agent_id": binding.agent_id,
                "internal_session_id": binding.brain_session_id,
                "host_agent_id": binding.bot_name,
                "role_profile": binding.bot_role,
                "model": binding.model,
                "provider": binding.provider,
                "created_at": binding.session.created_at,
            }
        )

    # Always ensure the canonical ledger has its lifecycle row. Telemetry may
    # outlive a purged/rebuilt ledger, so its idempotency marker is not the
    # authority for whether the ledger event exists.
    _append_event(
        home,
        binding,
        contracts.LifecycleEventType.SESSION_STARTED,
        _identity_fields(binding),
        key="session-start",
    )
    if not already_started:
        autoinject._append_telemetry(
            home,
            binding.host_session_id,
            "hermes_session_started",
            _identity_fields(binding),
        )


def _response_base(binding: HermesBinding, event: str) -> dict[str, Any]:
    return {
        "adapter_version": ADAPTER_VERSION,
        "event": event,
        "brain_session_id": binding.brain_session_id,
        "host_session_id": binding.host_session_id,
        "bot_name": binding.bot_name,
        "bot_role": binding.bot_role,
    }


def _route_task(home: Path, task: str) -> tuple[list[str], bool]:
    """Run the existing deterministic router without owning routing state."""
    try:
        result = router.route(home, task)
        selected = result.get("selected", [])
        if not isinstance(selected, list) or any(not isinstance(name, str) for name in selected):
            return [], True
        return selected, False
    except Exception:
        # Routing is advisory. A routing failure must not suppress the existing
        # bounded AutoInject path or break the Hermes host.
        return [], True


def _visibility_task(
    home: Path, task: str, session_id: str, project_id: str
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Run the visibility plan without owning routing state. Advisory/shadow
    by default; only 'enforced' mode may extend the returned packet."""
    try:
        plan = skills.build_plan(home, task, session_id=session_id, project_id=project_id)
        plan, hydrated_bodies = skills.hydrate_plan(home, plan)
        return skills.plan_to_evidence(plan), hydrated_bodies
    except Exception:
        return None, {}


def _model_candidates(payload: dict[str, Any], binding: HermesBinding) -> list[dict[str, Any]]:
    """Parse bounded host metadata without letting Hermes choose a model."""
    raw: Any = None
    supplied = False
    for key in _MODEL_CANDIDATE_KEYS:
        if key in payload:
            raw = payload[key]
            supplied = True
            break
    if not supplied or raw is None:
        return [{"provider": binding.provider, "model": binding.model}]
    if isinstance(raw, dict):
        raw = raw.get("candidates", raw.get("models"))
    if not isinstance(raw, list):
        raise model_routing.ModelRoutingError(
            "MALFORMED_ROUTING_INPUT", "candidate metadata must be a list"
        )
    if len(raw) > model_routing.MAX_CANDIDATES:
        raise model_routing.ModelRoutingError(
            "ROUTING_INPUT_TOO_LARGE", "candidate list exceeds bound"
        )
    candidates: list[dict[str, Any]] = []
    for value in raw:
        if not isinstance(value, dict):
            raise model_routing.ModelRoutingError(
                "MALFORMED_CANDIDATE", "candidate must be an object"
            )
        candidate = dict(value)
        if "cost_class" not in candidate and "cost" in candidate:
            candidate["cost_class"] = candidate["cost"]
        availability = candidate.pop("availability", None)
        if isinstance(availability, dict):
            for name in ("available", "provider_available", "model_available"):
                if name in availability and name not in candidate:
                    candidate[name] = availability[name]
        elif availability is not None and "available" not in candidate:
            candidate["available"] = availability
        candidates.append(candidate)
    return candidates


def _route_model(
    home: Path,
    binding: HermesBinding,
    payload: dict[str, Any],
    task: str,
) -> tuple[model_routing.ModelDecision | None, str | None]:
    if not task:
        return None, "NO_TASK"
    try:
        decision = model_routing.route_model(
            task,
            _model_candidates(payload, binding),
            role=binding.bot_role,
            bot_role=binding.bot_role,
            task_id=_first_text(payload, "task_id"),
            brain_session_id=binding.brain_session_id,
            host_session_id=binding.host_session_id,
            project_id=binding.project_id,
            bot_name=binding.bot_name,
            policy_profile=payload.get("policy_profile", "default"),
            home=home,
            repo_root=binding.repo_root,
            files_touched=payload.get(
                "files_touched", payload.get("files", payload.get("repo_files", ()))
            ),
            capability_requirements=payload.get(
                "capability_requirements", payload.get("required_capabilities", ())
            ),
            risk_class=payload.get("risk_class"),
            risk_level=payload.get("risk_level"),
            risk_score=payload.get("risk_score"),
            user_criticality=payload.get("user_criticality"),
            minimum_tier=payload.get("minimum_tier"),
            max_tier=payload.get("max_tier"),
            max_cost_class=payload.get("max_cost_class", "high"),
            premium_justification=payload.get(
                "premium_justification", payload.get("premium_reason")
            ),
            repeated_failure=bool(payload.get("repeated_failure", False)),
            ambiguity=bool(payload.get("ambiguity", False)),
            min_quality_score=payload.get("min_quality_score"),
        )
        return decision, None
    except model_routing.ModelRoutingError as exc:
        return None, _bounded_text(str(exc), _MODEL_ROUTING_MAX_ERROR_CHARS)
    except Exception:
        return None, "BRAIN_ROUTING_UNAVAILABLE"


def _model_identity(
    provider: str | None, model: str | None, tier: str | None
) -> dict[str, str] | None:
    if not provider or not model:
        return None
    return {
        "provider": _bounded_text(provider, _ATTRIBUTION_FIELD_MAX_CHARS),
        "model": _bounded_text(model, _ATTRIBUTION_FIELD_MAX_CHARS),
        "tier": _bounded_text(tier or "", _ATTRIBUTION_FIELD_MAX_CHARS),
    }


def _model_decision_event_payload(
    binding: HermesBinding, decision: model_routing.ModelDecision
) -> dict[str, Any]:
    """Return the bounded, task-text-free lifecycle representation."""
    return {
        "routing_event": "model_decision",
        "decision_id": decision.decision_id,
        "task_hash": decision.task_hash,
        "candidate_set_hash": decision.candidate_set_hash,
        "selected_provider": decision.selected_provider,
        "selected_model": decision.selected_model,
        "selected_tier": decision.selected_tier,
        "original_selected_provider": decision.original_selected_provider,
        "original_selected_model": decision.original_selected_model,
        "original_selected_tier": decision.original_selected_tier,
        "fallback_provider": decision.fallback_provider,
        "fallback_model": decision.fallback_model,
        "fallback_tier": decision.selected_tier if decision.fallback_used else None,
        "selected_identity": _model_identity(
            decision.selected_provider, decision.selected_model, decision.selected_tier
        ),
        "original_identity": _model_identity(
            decision.original_selected_provider,
            decision.original_selected_model,
            decision.original_selected_tier,
        ),
        "fallback_identity": _model_identity(
            decision.fallback_provider, decision.fallback_model, decision.selected_tier
        ),
        "fallback_used": decision.fallback_used,
        "role": binding.bot_role,
        "session_id": binding.host_session_id,
        "brain_session_id": binding.brain_session_id,
        "project_id": binding.project_id,
        "risk_class": decision.risk_class,
        "risk_score": decision.risk_score,
        "economic_class": decision.economic_class,
        "reason": decision.reason_code,
        "reason_code": decision.reason_code,
        "status": decision.status,
        "failure_code": decision.failure_code,
        "routing_error": decision.routing_error,
        "model_decision": decision.to_dict(),
    }


def _vmem_context(home: Path, binding: HermesBinding, task: str = "") -> dict[str, Any]:
    """Render existing VMem and fault in a task-referenced cold object."""
    try:
        store = vmem.VMemStore(home, binding.host_session_id)
        rendered = store.render_hot_context(max_tokens=_VMEM_HOT_CONTEXT_BUDGET)
        lowered = task.casefold()
        faulted_in_ids: list[str] = []
        faulted_content: list[str] = []
        for obj in store.list_objects():
            if obj.residency_state == vmem.ResidencyState.EVICTED and (
                obj.obj_id.casefold() in lowered or obj.title.casefold() in lowered
            ):
                faulted, content = store.fault_in(obj.obj_id)
                faulted_in_ids.append(faulted.obj_id)
                faulted_content.append(_bounded_text(content, _VMEM_HOT_CONTEXT_BUDGET * 4))
                break
        if faulted_in_ids:
            current_objects = store.list_objects()
            resident_objects = [
                obj
                for obj in current_objects
                if obj.residency_state
                in (vmem.ResidencyState.RESIDENT, vmem.ResidencyState.FAULTED_IN)
            ]
            evicted_objects = [
                obj for obj in current_objects if obj.residency_state == vmem.ResidencyState.EVICTED
            ]
            rendered["resident_count"] = len(resident_objects)
            rendered["evicted_count"] = len(evicted_objects)
            rendered["resident_tokens"] = sum(obj.token_estimate for obj in resident_objects)
            rendered["resident_objects"] = [obj.to_dict() for obj in resident_objects]
            rendered["evicted_refs"] = [
                {
                    "obj_id": obj.obj_id,
                    "kind": obj.kind.value,
                    "title": obj.title,
                    "tokens": obj.token_estimate,
                }
                for obj in evicted_objects[: vmem.MAX_REF_TABLE_ENTRIES]
            ]
        rendered_text = _bounded_text(rendered.get("rendered_text", ""), 2048)
        if faulted_content:
            rendered_text += "\n\n[SECOND_BRAIN_FAULTED_IN]\n" + "\n".join(faulted_content)
        rendered["rendered_text"] = _bounded_text(rendered_text, 4096)
        rendered["faulted_in_ids"] = faulted_in_ids
        rendered["context_changed"] = bool(faulted_in_ids)
        rendered["context_chars"] = len(rendered["rendered_text"])
        rendered["context_tokens"] = (
            contracts.estimate_tokens(rendered["rendered_text"], home=home)
            if rendered["context_chars"]
            else 0
        )
        return rendered
    except Exception:
        return {
            "session_id": binding.host_session_id,
            "resident_count": 0,
            "evicted_count": 0,
            "resident_tokens": 0,
            "rendered_text": "",
            "resident_objects": [],
            "evicted_refs": [],
            "faulted_in_ids": [],
            "context_changed": False,
            "context_chars": 0,
            "context_tokens": 0,
            "status": "fail_open",
        }


def _handle_post_tool_call(
    home: Path, binding: HermesBinding, payload: dict[str, Any]
) -> dict[str, Any]:
    _register_binding(home, binding)
    tool_name = _first_text(payload, "tool_name", "tool", default="unknown")
    raw_value = payload["raw_result"] if "raw_result" in payload else payload.get("result", "")
    raw_text, raw_bytes = _raw_tool_result(raw_value)
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    raw_artifact = artifacts.store_bytes(
        home,
        raw_bytes,
        kind="hermes_tool_result",
        tool=tool_name,
        session=binding.host_session_id,
    )
    if raw_artifact["hash"] != raw_sha or artifacts.expand(home, raw_sha) != raw_bytes:
        raise ValueError("preserve-first Hermes artifact verification failed")

    args_value = payload.get("args", {})
    args_text = _bounded_text(args_value, 1000)
    command = _command_from_args(args_value)
    reduction = firewall.reduce_observation(
        raw_text,
        command=command,
        tool=tool_name,
        session=binding.host_session_id,
        home=None,
        max_chars=firewall.MAX_DISTILL_CHARS,
    )
    visible_text = reduction.distilled_text
    if reduction.lossless_retrieval_handle:
        visible_text = visible_text.replace(
            reduction.lossless_retrieval_handle, raw_artifact["handle"]
        )
    old_hint = artifacts.recover_hint(reduction.raw_object_ref)
    visible_text = visible_text.replace(old_hint, artifacts.recover_hint(raw_sha))
    recovery_line = (
        f"Raw Artifact: {raw_artifact['handle']}\n{artifacts.recover_hint(raw_sha)}"
    )
    if raw_artifact["handle"] not in visible_text:
        visible_text = visible_text[: firewall.MAX_DISTILL_CHARS - len(recovery_line)]
        visible_text += "\n" + recovery_line
    visible_text = visible_text[: firewall.MAX_DISTILL_CHARS]
    visible_bytes = len(visible_text.encode("utf-8"))
    reduction_ratio = max(0.0, 1.0 - (visible_bytes / max(len(raw_bytes), 1)))
    status = _first_text(payload, "status", default="unknown")
    tool_call_id = _first_text(payload, "tool_call_id", default="") or None
    turn_id = _first_text(payload, "turn_id", default="") or None
    vmem_metadata = {
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "turn_id": turn_id,
        "status": status,
        "args_sha256": _sha256(args_text),
        "raw_artifact_ref": raw_sha,
        "recovery_handle": raw_artifact["handle"],
        "original_result_chars": len(raw_text),
        "original_result_bytes": len(raw_bytes),
        "original_result_sha256": raw_sha,
        "visible_result_chars": len(visible_text),
        "visible_result_bytes": visible_bytes,
        "reduction_ratio": round(reduction_ratio, 6),
        "distilled": True,
    }
    store = vmem.VMemStore(home, binding.host_session_id)
    obj = store.store_object(
        vmem.SessionObjectKind.TOOL_OBSERVATION,
        title=f"{tool_name} result",
        content=visible_text,
        summary=visible_text,
        artifact_ref=raw_sha,
        metadata=vmem_metadata,
    )
    evicted = store.render_hot_context(max_tokens=_VMEM_HOT_CONTEXT_BUDGET).get("evicted_refs", [])
    stored = store.get_object(obj.obj_id)
    event_payload = {
        **_identity_fields(binding),
        "obj_id": obj.obj_id,
        "object_kind": obj.kind.value,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "turn_id": turn_id,
        "status": status,
        "result_sha256": raw_sha,
        "result_chars": len(raw_text),
        "original_result_chars": len(raw_text),
        "original_result_bytes": len(raw_bytes),
        "original_result_sha256": raw_sha,
        "artifact_ref": raw_sha,
        "recovery_handle": raw_artifact["handle"],
        "visible_result_chars": len(visible_text),
        "visible_result_bytes": visible_bytes,
        "reduction_ratio": round(reduction_ratio, 6),
        "distilled": True,
        "evicted_count": len(evicted),
        "residency_state": stored.residency_state.value if stored else "UNKNOWN",
        "vmem_budget_tokens": _VMEM_HOT_CONTEXT_BUDGET,
    }
    _append_event(
        home,
        binding,
        contracts.LifecycleEventType.TOOL_COMPLETED,
        event_payload,
        key=tool_call_id or turn_id or obj.obj_id,
    )
    autoinject._append_telemetry(
        home, binding.host_session_id, "hermes_post_tool_call", event_payload
    )
    return {
        **_response_base(binding, "post_tool_call"),
        "status": "ok",
        "obj_id": obj.obj_id,
        "kind": obj.kind.value,
        "residency_state": stored.residency_state.value if stored else "UNKNOWN",
        "evicted_count": len(evicted),
        "original_result_bytes": len(raw_bytes),
        "original_result_sha256": raw_sha,
        "artifact_ref": raw_sha,
        "recovery_handle": raw_artifact["handle"],
        "visible_result_bytes": visible_bytes,
        "reduction_ratio": round(reduction_ratio, 6),
    }


def _handle_session_start(home: Path, binding: HermesBinding) -> dict[str, Any]:
    _register_binding(home, binding)
    return {**_response_base(binding, "session_start"), "status": "registered"}


def _handle_pre_llm(home: Path, binding: HermesBinding, payload: dict[str, Any]) -> dict[str, Any]:
    _register_binding(home, binding)
    task = _first_text(payload, "task", "user_message", "prompt")
    turn_id = _first_text(payload, "turn_id", default="") or None
    vmem_context = _vmem_context(home, binding, task)
    selected_routes, routing_error = _route_task(home, task) if task else ([], False)
    visibility_plan, hydrated_bodies = (
        _visibility_task(home, task, binding.host_session_id, binding.project_id)
        if task
        else (None, {})
    )
    model_decision, model_routing_error = _route_model(home, binding, payload, task)
    model_event_payload = (
        _model_decision_event_payload(binding, model_decision)
        if model_decision is not None
        else None
    )
    lifecycle = autoinject.BrainLifecycle(home, binding.session)
    decision = lifecycle.prepare_injection(
        task,
        project_id=binding.project_id,
        agent_id=binding.agent_id,
        role_profile=binding.bot_role,
        session_id=binding.host_session_id,
        branch_id=binding.branch_id,
        cwd=binding.repo_root,
    )
    packet = autoinject.render_packet(decision)
    mode = autoinject.resolve_autoinject_mode(home)
    visible_packet = packet if packet and mode in {"advisory", "active"} else None
    enforced_visible = visibility_plan is not None and visibility_plan.get("mode") == "enforced"
    if enforced_visible and hydrated_bodies:
        specialist_text = "\n\n".join(
            hydrated_bodies[skill_id] for skill_id in sorted(hydrated_bodies)
        )
        if visible_packet:
            visible_packet = f"{visible_packet}\n\n{specialist_text}"
        else:
            visible_packet = specialist_text
    reason = decision.reason.value if decision.reason is not None else None
    attribution = _injection_attribution(binding, task, turn_id, decision)
    event_type = (
        contracts.LifecycleEventType.BRAIN_PACKET_DELIVERED
        if visible_packet is not None
        else contracts.LifecycleEventType.BRAIN_NO_INJECTION
    )
    event_payload = {
        "project_id": binding.project_id,
        "task_sha256": _sha256(task),
        "decision": decision.decision.value,
        "reason": reason,
        "candidate_count": len(decision.candidate_ids),
        "selected_ids": decision.selected_ids,
        "packet_tokens": decision.packet_token_size,
        "mode": mode,
        "model_visible": visible_packet is not None,
        "delivery_count": len(lifecycle.last_delivery_ids),
        "turn_id": turn_id,
        "attribution": attribution,
        "selected_routes": selected_routes,
        "visibility_plan": visibility_plan,
        "routing_error": routing_error,
        "model_decision_id": model_decision.decision_id if model_decision else None,
        "model_routing_status": (
            model_decision.status if model_decision else "fail_open"
        ),
        "model_routing_error": model_routing_error,
        "model_selected_provider": (
            model_decision.selected_provider if model_decision else None
        ),
        "model_selected_model": model_decision.selected_model if model_decision else None,
        "model_selected_tier": model_decision.selected_tier if model_decision else None,
        "model_reason_code": model_decision.reason_code if model_decision else None,
        "model_fallback_used": model_decision.fallback_used if model_decision else False,
        "vmem_context_chars": vmem_context.get("context_chars", 0),
        "vmem_context_tokens": vmem_context.get("context_tokens", 0),
        "vmem_context_changed": vmem_context.get("context_changed", False),
        "vmem_resident_count": vmem_context.get("resident_count", 0),
        "vmem_evicted_count": vmem_context.get("evicted_count", 0),
        "vmem_resident_tokens": vmem_context.get("resident_tokens", 0),
        "vmem_faulted_in_ids": vmem_context.get("faulted_in_ids", []),
    }
    _append_event(
        home,
        binding,
        event_type,
        event_payload,
        key=turn_id or attribution["injection_decision_id"],
        visibility=(
            contracts.SurfaceVisibility.MODEL_VISIBLE_APPEND
            if visible_packet is not None
            else contracts.SurfaceVisibility.BOOKKEEPING
        ),
    )
    autoinject._append_telemetry(
        home,
        binding.host_session_id,
        "hermes_pre_llm_call",
        {
            **event_payload,
            "project_id": binding.project_id,
            "bot_name": binding.bot_name,
            "bot_role": binding.bot_role,
        },
    )
    if model_event_payload is not None and model_decision is not None:
        _append_event(
            home,
            binding,
            contracts.LifecycleEventType.DECISION,
            model_event_payload,
            key=f"{turn_id or 'no-turn'}:{model_decision.decision_id}",
        )
        autoinject._append_telemetry(
            home,
            binding.host_session_id,
            "model_routing_decision",
            model_event_payload,
        )
        autoinject._append_telemetry(
            home,
            binding.host_session_id,
            "hermes_model_decision",
            model_event_payload,
        )
        if model_decision.fallback_used:
            autoinject._append_telemetry(
                home,
                binding.host_session_id,
                "model_fallback_used",
                model_event_payload,
            )
        if model_decision.selected_provider and model_decision.selected_model:
            invocation_started = {
                **_identity_fields(binding),
                "routing_event": "model_invocation_started",
                "decision_id": model_decision.decision_id,
                "task_hash": model_decision.task_hash,
                "turn_id": turn_id,
                "selected_identity": _model_identity(
                    model_decision.selected_provider,
                    model_decision.selected_model,
                    model_decision.selected_tier,
                ),
                "fallback_used": model_decision.fallback_used,
                "fallback_reason": model_decision.fallback_reason,
            }
            _append_event(
                home,
                binding,
                contracts.LifecycleEventType.DECISION,
                invocation_started,
                key=f"start:{turn_id or 'no-turn'}:{model_decision.decision_id}",
            )
            autoinject._append_telemetry(
                home,
                binding.host_session_id,
                "model_invocation_started",
                invocation_started,
            )
    return {
        **_response_base(binding, "pre_llm_call"),
        "status": "ok",
        "turn_id": turn_id,
        "decision": decision.decision.value,
        "reason": reason,
        "attribution": attribution,
        "selected_ids": decision.selected_ids,
        "packet": visible_packet,
        "packet_tokens": decision.packet_token_size,
        "model_visible": visible_packet is not None,
        "mode": mode,
        "delivery_ids": lifecycle.last_delivery_ids,
        "selected_routes": selected_routes,
        "visibility_plan": visibility_plan,
        "routing_error": routing_error,
        "vmem_context": vmem_context,
        "vmem_context_chars": vmem_context.get("context_chars", 0),
        "vmem_context_tokens": vmem_context.get("context_tokens", 0),
        "vmem_context_changed": vmem_context.get("context_changed", False),
        "vmem_faulted_in_ids": vmem_context.get("faulted_in_ids", []),
        "model_routing_status": model_decision.status if model_decision else "fail_open",
        "model_routing_error": model_routing_error,
        "model_decision": model_decision.to_dict() if model_decision else None,
        "selected_provider": model_decision.selected_provider if model_decision else None,
        "selected_model": model_decision.selected_model if model_decision else None,
        "selected_tier": model_decision.selected_tier if model_decision else None,
        "reason_code": model_decision.reason_code if model_decision else None,
        "fallback_used": model_decision.fallback_used if model_decision else False,
        "fallback_provider": model_decision.fallback_provider if model_decision else None,
        "fallback_model": model_decision.fallback_model if model_decision else None,
        "fallback_reason": model_decision.fallback_reason if model_decision else None,
        "original_selected_provider": (
            model_decision.original_selected_provider if model_decision else None
        ),
        "original_selected_model": (
            model_decision.original_selected_model if model_decision else None
        ),
        "original_selected_tier": (
            model_decision.original_selected_tier if model_decision else None
        ),
    }


def _handle_writeback(
    home: Path, binding: HermesBinding, payload: dict[str, Any]
) -> dict[str, Any]:
    _register_binding(home, binding)
    evidence = payload.get("evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    lifecycle = autoinject.BrainLifecycle(home, binding.session)
    memory_id = lifecycle.writeback_candidate(
        session_id=binding.host_session_id,
        project_id=binding.project_id,
        title=_first_text(payload, "title"),
        observation=_first_text(payload, "observation"),
        guidance=_first_text(payload, "guidance"),
        evidence=evidence,
    )
    event_payload = {
        "memory_id": memory_id,
        "project_id": binding.project_id,
        "status": "candidate",
        "evidence_count": len(evidence),
        "title_sha256": _sha256(_first_text(payload, "title")),
        "observation_sha256": _sha256(_first_text(payload, "observation")),
    }
    _append_event(
        home,
        binding,
        contracts.LifecycleEventType.FINDING,
        event_payload,
        key=memory_id,
    )
    autoinject._append_telemetry(
        home,
        binding.host_session_id,
        "hermes_writeback_candidate",
        {**event_payload, "bot_name": binding.bot_name, "bot_role": binding.bot_role},
    )
    return {
        **_response_base(binding, "writeback"),
        "status": "candidate",
        "memory_id": memory_id,
        "project_id": binding.project_id,
    }


def _bounded_invocation_value(value: Any) -> Any:
    if isinstance(value, dict):
        allowed = {
            "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens",
            "output_tokens", "cache_read_tokens", "cache_write_tokens", "amount",
            "value", "currency", "unit",
        }
        return {
            str(key)[:64]: _bounded_invocation_value(item)
            for key, item in list(value.items())[:16]
            if str(key) in allowed
        }
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _bounded_text(value, 128)


def _handle_api_lifecycle(
    home: Path, binding: HermesBinding, payload: dict[str, Any]
) -> dict[str, Any]:
    """Record bounded model invocation facts without retaining response content."""
    _register_binding(home, binding)
    event = _first_text(payload, "event", default="api_request_error")
    selected_raw = payload.get("selected_identity")
    if isinstance(selected_raw, dict):
        selected = _model_identity(
            selected_raw.get("provider"), selected_raw.get("model"), selected_raw.get("tier")
        )
    else:
        selected = _model_identity(
            payload.get("selected_provider"),
            payload.get("selected_model"),
            payload.get("selected_tier"),
        )
    actual_raw = payload.get("actual_identity")
    if isinstance(actual_raw, dict):
        actual = _model_identity(
            actual_raw.get("provider"), actual_raw.get("model"), actual_raw.get("tier")
        )
    else:
        actual = _model_identity(
            payload.get("actual_provider", payload.get("provider")),
            payload.get("actual_model", payload.get("model")),
            None,
        )
    event_payload: dict[str, Any] = {
        **_identity_fields(binding),
        "routing_event": f"model_{event}",
        "lifecycle_event": event,
        "decision_id": _bounded_text(payload.get("decision_id"), _ATTRIBUTION_FIELD_MAX_CHARS),
        "turn_id": _bounded_text(payload.get("turn_id"), _ATTRIBUTION_FIELD_MAX_CHARS),
        "api_request_id": _bounded_text(
            payload.get("api_request_id"), _ATTRIBUTION_FIELD_MAX_CHARS
        ),
        "selected_identity": selected,
        "actual_identity": actual,
        "response_model": _bounded_text(
            payload.get("response_model"), _ATTRIBUTION_FIELD_MAX_CHARS
        ),
        "status": _bounded_text(
            payload.get("status")
            or ("completed" if event == "post_api_request" else "failed"),
            64,
        ),
    }
    if payload.get("fallback_used"):
        fallback = payload.get("fallback_identity")
        original = payload.get("original_selected_identity")
        event_payload["fallback_used"] = True
        event_payload["fallback_identity"] = _model_identity(
            fallback.get("provider") if isinstance(fallback, dict) else None,
            fallback.get("model") if isinstance(fallback, dict) else None,
            fallback.get("tier") if isinstance(fallback, dict) else None,
        )
        event_payload["fallback_reason"] = _bounded_text(
            payload.get("fallback_reason"), _ATTRIBUTION_FIELD_MAX_CHARS
        )
        event_payload["original_selected_identity"] = _model_identity(
            original.get("provider") if isinstance(original, dict) else None,
            original.get("model") if isinstance(original, dict) else None,
            original.get("tier") if isinstance(original, dict) else None,
        )
    for name in ("usage", "cost", "failure_code"):
        if payload.get(name) is not None:
            event_payload[name] = (
                _bounded_invocation_value(payload[name])
                if name in {"usage", "cost"}
                else _bounded_text(payload[name], _ATTRIBUTION_FIELD_MAX_CHARS)
            )
    key = ":".join(
        [
            event_payload["decision_id"] or "no-decision",
            event_payload["api_request_id"] or event_payload["turn_id"] or "no-request",
            event,
        ]
    )
    _append_event(
        home,
        binding,
        contracts.LifecycleEventType.DECISION,
        event_payload,
        key=key,
    )
    telemetry_kind = (
        "model_invocation_completed"
        if event == "post_api_request"
        else "model_invocation_failed"
    )
    autoinject._append_telemetry(
        home,
        binding.host_session_id,
        telemetry_kind,
        {**event_payload, "bot_name": binding.bot_name, "bot_role": binding.bot_role},
    )
    if event_payload.get("fallback_used"):
        autoinject._append_telemetry(
            home,
            binding.host_session_id,
            "model_fallback_used",
            {**event_payload, "bot_name": binding.bot_name, "bot_role": binding.bot_role},
        )
    return {
        **_response_base(binding, event),
        "status": event_payload["status"],
        "decision_id": event_payload["decision_id"] or None,
        "selected_identity": selected,
        "actual_identity": actual,
    }


def _handle_session_end(
    home: Path, binding: HermesBinding, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    _register_binding(home, binding)
    payload = payload or {}
    tool_args = payload.get("tool_call_args") or payload.get("tool_calls")
    if tool_args is None:
        transcript_path = (
            payload.get("transcript_path")
            or payload.get("transcriptPath")
            or payload.get("transcript")
        )
        if transcript_path:
            try:
                from .cli import _claude_tool_call_args

                tool_args = _claude_tool_call_args(transcript_path)
            except Exception:
                tool_args = []
    lifecycle = autoinject.BrainLifecycle(home, binding.session)
    lifecycle.finalize_session(
        tool_call_args=tool_args,
        final_message=payload.get("final_message")
        or payload.get("last_assistant_message"),
    )
    _append_event(
        home,
        binding,
        contracts.LifecycleEventType.SESSION_FINALIZED,
        {"brain_session_id": binding.brain_session_id, "bot_name": binding.bot_name},
        key="session-end",
    )
    checkpoint: dict[str, Any] = {"ok": False}
    try:
        with ledger.LedgerStore(home, binding.host_session_id).open() as store:
            checkpoint = ledger.checkpoint_ledger(store)
    except Exception:
        pass
    autoinject._append_telemetry(
        home,
        binding.host_session_id,
        "hermes_session_finalized",
        {
            "brain_session_id": binding.brain_session_id,
            "checkpoint_ok": checkpoint.get("ok", False),
        },
    )
    return {
        **_response_base(binding, "session_end"),
        "status": "finalized",
        "checkpoint": checkpoint,
    }

def _handoff_list_or_none(value: Any) -> list[str] | None:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else None


def _handle_handoff_create(
    home: Path, binding: HermesBinding, payload: dict[str, Any]
) -> dict[str, Any]:
    """Create a canonical Brain Handoff Envelope (§3 P3.17) for this session.

    Uses the same :func:`second_brain.handoff.create_handoff_envelope` the
    OMP adapter calls, so envelope schema and validation never diverge by
    harness.
    """
    _register_binding(home, binding)
    try:
        envelope, artifact = handoff.create_handoff_envelope(
            home,
            binding.brain_session_id,
            source_harness=_HOST,
            target_harness=_first_text(payload, "target_harness"),
            target_role=_first_text(payload, "target_role"),
            source_task_id=_first_text(payload, "task_id"),
            source_role=binding.bot_role,
            project_id=binding.project_id,
            context_refs=_handoff_list_or_none(payload.get("context_refs")),
            artifact_refs=_handoff_list_or_none(payload.get("artifact_refs")),
            evidence_refs=_handoff_list_or_none(payload.get("evidence_refs")),
            unavailable_evidence=_handoff_list_or_none(payload.get("unavailable_evidence")),
        )
    except contracts.HandoffError as exc:
        return {
            **_response_base(binding, "handoff_create"),
            "status": "failed",
            "failure_code": exc.code,
        }
    except BrainError as exc:
        return {
            **_response_base(binding, "handoff_create"),
            "status": "failed",
            "failure_code": "HANDOFF_SOURCE_UNAVAILABLE",
            "error": str(exc)[:128],
        }
    return {
        **_response_base(binding, "handoff_create"),
        "status": "created",
        "envelope": envelope.to_dict(),
        "markdown_path": artifact.artifact_path,
        "envelope_bytes": envelope.envelope_bytes(),
    }


def _handle_handoff_read(
    home: Path, binding: HermesBinding, payload: dict[str, Any]
) -> dict[str, Any]:
    """Validate and losslessly recover a Brain Handoff Envelope (§3 P3.17)."""
    _register_binding(home, binding)
    envelope_data = payload.get("envelope")
    if not isinstance(envelope_data, dict):
        return {
            **_response_base(binding, "handoff_read"),
            "status": "failed",
            "failure_code": "HANDOFF_MALFORMED",
        }
    try:
        recovered = handoff.read_handoff_envelope(
            home,
            envelope_data,
            expected_project_id=(binding.project_id or None),
            allow_stale=bool(payload.get("allow_stale", False)),
        )
    except contracts.HandoffError as exc:
        return {
            **_response_base(binding, "handoff_read"),
            "status": "failed",
            "failure_code": exc.code,
        }
    return {**_response_base(binding, "handoff_read"), "status": "recovered", **recovered}



def handle_request(home: Path | str, payload: object) -> dict[str, Any]:
    """Handle one Hermes adapter request without raising into the host."""
    if not isinstance(payload, dict):
        return {"adapter_version": ADAPTER_VERSION, "event": "unknown", "status": "fail_open"}
    event = _first_text(payload, "event", default="unknown")
    if event not in _SUPPORTED_EVENTS:
        return {"adapter_version": ADAPTER_VERSION, "event": event, "status": "fail_open"}
    home_path = Path(home)
    if not (home_path / "VERSION").is_file() or not (home_path / "db" / "brain.sqlite").is_file():
        return {"adapter_version": ADAPTER_VERSION, "event": event, "status": "fail_open"}
    try:
        binding = resolve_binding(home_path, payload)
        if event == "session_start":
            return _handle_session_start(home_path, binding)
        if event == "pre_llm_call":
            return _handle_pre_llm(home_path, binding, payload)
        if event == "post_tool_call":
            return _handle_post_tool_call(home_path, binding, payload)
        if event == "writeback":
            return _handle_writeback(home_path, binding, payload)
        if event == "worker_task_prepare":
            packet = payload.get("packet")
            if not isinstance(packet, dict):
                return {
                    **_response_base(binding, event),
                    "status": "failed",
                    "failure_code": "MALFORMED_TASK",
                }
            return prepare_worker_task(home_path, binding, packet)
        if event == "post_api_request":
            return _handle_api_lifecycle(home_path, binding, payload)
        if event == "api_request_error":
            return _handle_api_lifecycle(home_path, binding, payload)
        if event == "worker_task_request":
            packet = payload.get("packet")
            if not isinstance(packet, dict):
                return {
                    **_response_base(binding, event),
                    "status": "failed",
                    "failure_code": "MALFORMED_TASK",
                }
            return request_worker_task(
                home_path,
                binding,
                packet,
                payload.get("result"),
                payload.get("context_handoff"),
            )
        if event == "worker_result_review":
            result = payload.get("result")
            if not isinstance(result, dict):
                return {
                    **_response_base(binding, event),
                    "status": "failed",
                    "failure_code": "MALFORMED_RESULT",
                }
            return review_worker_result(
                home_path, binding, result, bool(payload.get("approved", True))
            )
        if event == "worker_result_correction":
            packet = payload.get("packet")
            result = payload.get("result")
            if not isinstance(packet, dict) or not isinstance(result, dict):
                return {
                    **_response_base(binding, event),
                    "status": "failed",
                    "failure_code": "MALFORMED_CORRECTION",
                }
            return request_worker_correction(
                home_path,
                binding,
                packet,
                result,
                _first_text(payload, "reason"),
                payload.get("requested_changes"),
                payload.get("evidence_requirements"),
                int(payload.get("correction_attempt", 1)),
            )
        if event == "worker_result_corrected":
            packet = payload.get("packet")
            original = payload.get("original_result")
            correction = payload.get("correction")
            corrected = payload.get("result")
            if not all(
                isinstance(value, dict) for value in (packet, original, correction, corrected)
            ):
                return {
                    **_response_base(binding, event),
                    "status": "failed",
                    "failure_code": "MALFORMED_CORRECTION",
                }
            assert isinstance(packet, dict)
            assert isinstance(original, dict)
            assert isinstance(correction, dict)
            assert isinstance(corrected, dict)
            return return_corrected_worker_result(
                home_path,
                binding,
                packet,
                original,
                correction,
                corrected,
                payload.get("context_handoff"),
            )
        if event == "handoff_create":
            return _handle_handoff_create(home_path, binding, payload)
        if event == "handoff_read":
            return _handle_handoff_read(home_path, binding, payload)
        return _handle_session_end(home_path, binding, payload)
    except Exception:
        return {
            "adapter_version": ADAPTER_VERSION,
            "event": event,
            "status": "fail_open",
            "error": "BRAIN_UNAVAILABLE",
        }
