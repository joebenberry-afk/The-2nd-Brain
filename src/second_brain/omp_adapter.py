"""Thin OMP-to-Second-Brain transport adapters.

OMP owns lifecycle and request transport. Brain owns model decisions and the
bounded worker-context handoff; this module only validates host packets and
calls the existing Brain primitives.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts, handoff, ledger, model_routing, skills, worker_protocol, working_set

_MAX_TASK_CHARS = 2048
_MAX_IDENTITY_CHARS = 128
_MAX_CANDIDATES = model_routing.MAX_CANDIDATES


def _text(value: Any, limit: int = _MAX_IDENTITY_CHARS) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _required_text(
    payload: Mapping[str, Any], name: str, limit: int = contracts.WORKER_TEXT_MAX_CHARS
) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > limit:
        raise contracts.WorkerPacketError(
            "PROTOCOL_ERROR", f"{name} must be a bounded non-empty string"
        )
    return value


def _worker_text(value: Any, default: str) -> str:
    text = value if isinstance(value, str) else default
    return text[: contracts.WORKER_TEXT_MAX_CHARS]


def _context_refs(home: Path, session_id: str, override: Any) -> list[str]:
    if override is not None:
        if not isinstance(override, list):
            raise contracts.WorkerPacketError("MALFORMED_TASK", "context_refs must be a list")
        return [value for value in override if isinstance(value, str)]
    capsule = working_set.show_capsule(home, session_id)
    refs = list(capsule.get("brain_refs") or [])
    refs.extend(
        value
        for value in capsule.get("artifact_refs") or []
        if isinstance(value, str)
        and (
            value.startswith("artifact:")
            or value.startswith("brain://artifact/")
            or value.startswith("[brain-artifact:sha256:")
        )
    )
    return refs


def _prepare_worker_context(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    host_session_id = _text(payload.get("host_session_id") or payload.get("session_id"))
    role = _text(payload.get("role")) or "driver"
    provider = _text(payload.get("provider")) or "unknown"
    model = _text(payload.get("model")) or "unknown"
    worker_role = _text(payload.get("worker_role")) or "worker"
    task_id = _text(payload.get("task_id"))
    if not task_id or not host_session_id:
        raise contracts.WorkerPacketError(
            "MALFORMED_TASK", "task_id and host_session_id are required"
        )
    if role not in contracts.COORDINATOR_ROLES:
        raise contracts.WorkerPacketError(
            "UNAUTHORIZED_COORDINATOR", "driver role is not authorized"
        )
    packet = contracts.WorkerTaskPacket(
        task_id=task_id,
        parent_session_id=host_session_id,
        driver_identity=contracts.AgentIdentity(
            agent_id=f"omp:{host_session_id}",
            internal_session_id=ledger.internal_session_id(host_session_id),
            host_agent_id="omp",
            parent_agent_id=None,
            role_profile=role,
            model=model,
            provider=provider,
            created_at=_text(payload.get("created_at")) or host_session_id,
        ),
        requested_role=worker_role,
        objective=_worker_text(payload.get("task"), "delegated worker task"),
        scope=_worker_text(payload.get("scope"), _text(payload.get("cwd")) or "repository"),
        constraints=payload.get("constraints", []),
        evidence_requirements=payload.get("evidence_requirements", []),
        completion_condition=_worker_text(
            payload.get("completion_condition"), "Return bounded evidence for the requested task"
        ),
        context_refs=_context_refs(home, host_session_id, payload.get("context_refs")),
        fanout_index=0,
        fanout=1,
        depth=int(payload.get("depth", 0)),
        project_id=_text(payload.get("project_id")),
        repo_root=_text(payload.get("cwd"), contracts.WORKER_REF_MAX_CHARS),
        access_intent=_text(payload.get("access_intent")),
    ).validate()
    context_handoff = worker_protocol.prepare_context_handoff(home, packet, host="omp")
    registration = worker_protocol.admit_worker_attempt(home, packet)
    if packet.access_intent == "read_only":
        worker_protocol.record_worker_event(
            home,
            packet.task_id,
            packet.canonical_hash(),
            "worker_started",
            attempt_id=registration["attempt_id"],
            session_id=host_session_id,
            host="omp",
        )
    response = {
        "status": "prepared",
        "task_id": packet.task_id,
        "attempt_id": registration["attempt_id"],
        "packet_sha256": packet.canonical_hash(),
        "project_id": packet.project_id,
        "worktree_id": registration["worktree_id"],
        "access_intent": packet.access_intent,
        "worker_role": packet.requested_role,
        "worker_model": model,
        "context_metadata": worker_protocol.handoff_metadata(context_handoff),
        "context_handoff": context_handoff,
    }
    if "callback_token" in registration:
        response["callback_token"] = registration["callback_token"]
    return response


def _prepare_skill_visibility(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    task = _text(payload.get("task"), _MAX_TASK_CHARS)
    if not task:
        return {"visibility_plan": None, "hydrated_instructions": {}, "error": "NO_TASK"}
    session_id = _text(payload.get("host_session_id") or payload.get("session_id"))
    project_id = _text(payload.get("project_id"))
    plan = skills.build_plan(home, task, session_id=session_id, project_id=project_id)
    plan, hydrated_bodies = skills.hydrate_plan(home, plan)
    return {
        "visibility_plan": skills.plan_to_evidence(plan),
        "hydrated_instructions": hydrated_bodies,
        "error": None,
    }


def _candidates(payload: Mapping[str, Any], role: str) -> list[dict[str, Any]]:
    raw = payload.get("candidates")
    if raw is None or raw == []:
        elevated = role.casefold() in {"driver", "integrator", "orchestrator"}
        return [
            {
                "provider": _text(payload.get("provider")),
                "model": _text(payload.get("model")),
                "tier": "balanced" if elevated else "efficient",
                "cost_class": "medium" if elevated else "low",
            }
        ]
    if not isinstance(raw, list) or len(raw) > _MAX_CANDIDATES:
        raise model_routing.ModelRoutingError(
            "MALFORMED_ROUTING_INPUT", "candidate metadata must be a bounded list"
        )
    result: list[dict[str, Any]] = []
    for value in raw:
        if not isinstance(value, Mapping):
            raise model_routing.ModelRoutingError(
                "MALFORMED_CANDIDATE", "candidate must be an object"
            )
        candidate = dict(value)
        candidate["provider"] = _text(candidate.get("provider"))
        candidate["model"] = _text(candidate.get("model"))
        result.append(candidate)
    return result



def _list_or_none(value: Any) -> list[str] | None:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else None


def _prepare_handoff_create(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    session_id = _text(payload.get("host_session_id") or payload.get("session_id"))
    envelope, artifact = handoff.create_handoff_envelope(
        home,
        session_id,
        source_harness=_text(payload.get("source_harness")) or "omp",
        target_harness=_text(payload.get("target_harness")),
        target_role=_text(payload.get("target_role")),
        source_task_id=_text(payload.get("task_id")),
        source_role=_text(payload.get("bot_role") or payload.get("role")),
        project_id=_text(payload.get("project_id")),
        context_refs=_list_or_none(payload.get("context_refs")),
        artifact_refs=_list_or_none(payload.get("artifact_refs")),
        evidence_refs=_list_or_none(payload.get("evidence_refs")),
        unavailable_evidence=_list_or_none(payload.get("unavailable_evidence")),
    )
    return {
        "envelope": envelope.to_dict(),
        "markdown_path": artifact.artifact_path,
        "envelope_bytes": envelope.envelope_bytes(),
    }


def _prepare_handoff_read(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    envelope_data = payload.get("envelope")
    if not isinstance(envelope_data, dict):
        raise contracts.HandoffError("HANDOFF_MALFORMED", "envelope must be an object")
    return handoff.read_handoff_envelope(
        home,
        envelope_data,
        expected_project_id=_text(payload.get("project_id")) or None,
        allow_stale=bool(payload.get("allow_stale", False)),
    )


def to_result_packet(payload: Mapping[str, Any]) -> contracts.WorkerResultPacket:
    """Validate a wire dict into a WorkerResultPacket (thin, directly testable seam)."""
    return contracts.WorkerResultPacket.from_dict(dict(payload))


def _worker_result_identity(
    home: Path, task_id: str, session_id: str | None, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Assemble a worker AgentIdentity dict from the bridge's flat wire fields.

    `worker-result-bridge.ts` sends flat `worker_agent`/`worker_model`/`worker_role`
    fields (mirroring `worker-context-bridge.ts`'s flat `role`/`provider`/`model`),
    never a pre-built nested `worker_identity`. This mirrors how
    `_prepare_worker_context` assembles `driver_identity` from its own flat fields.
    The real bridge never populates `worker_role`, so an invalid/missing role
    falls back to the role recorded at task-dispatch time.
    """
    role = _text(payload.get("worker_role"))
    if role not in contracts.WORKER_ROLES:
        dispatch = worker_protocol.dispatch_snapshot(home, task_id)
        requested_role = dispatch.get("requested_role") if isinstance(dispatch, dict) else None
        role = requested_role if requested_role in contracts.WORKER_ROLES else "worker"
    return {
        "agent_id": _text(payload.get("worker_agent")) or f"omp-worker:{task_id}",
        "internal_session_id": (
            ledger.internal_session_id(session_id) if session_id else "unavailable"
        ),
        "host_agent_id": "omp",
        "parent_agent_id": None,
        "role_profile": role,
        "model": _text(payload.get("worker_model")) or "unknown",
        "provider": "omp",
        "created_at": _text(payload.get("created_at")) or datetime.now(UTC).isoformat(),
    }


def _prepare_worker_result(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    task_id = _text(payload.get("task_id"))
    packet_sha256 = _text(payload.get("packet_sha256"))
    attempt_id = _text(payload.get("attempt_id"))
    session_id = _text(payload.get("host_session_id") or payload.get("session_id"))
    if not task_id or not packet_sha256 or not attempt_id or not session_id:
        return {"status": "failed", "failure_code": "MALFORMED_RESULT"}
    binding_error = worker_protocol.verify_attempt_binding(
        home, task_id, packet_sha256, attempt_id, session_id
    )
    if binding_error is not None:
        return {"status": "failed", "failure_code": binding_error, "task_id": task_id}
    try:
        result = to_result_packet(
            {
                **payload,
                "worker_identity": _worker_result_identity(home, task_id, session_id, payload),
            }
        )
    except contracts.WorkerPacketError as exc:
        return {"status": "failed", "failure_code": exc.code, "task_id": task_id}
    dispatch = worker_protocol.dispatch_snapshot(home, result.task_id)
    if isinstance(dispatch, dict):
        requested_role = dispatch.get("requested_role")
        if (
            isinstance(requested_role, str)
            and result.worker_identity.role_profile != requested_role
        ):
            return {"status": "failed", "failure_code": "UNAUTHORIZED_WORKER", "task_id": task_id}
    try:
        receipt = worker_protocol.record_worker_event(
            home,
            result.task_id,
            packet_sha256,
            result.status,
            payload={
                **json.loads(result.canonical_json()),
                "result_sha256": result.canonical_hash(),
            },
            attempt_id=attempt_id,
            session_id=session_id,
            host="omp",
        )
    except contracts.WorkerPacketError as exc:
        return {"status": "failed", "failure_code": exc.code, "task_id": result.task_id}
    result_sha256 = receipt.get("result_sha256")
    if not isinstance(result_sha256, str):
        return {
            "status": "failed",
            "failure_code": "RESULT_NOT_RECORDED",
            "task_id": result.task_id,
        }
    return {
        "status": result.status,
        "failure_code": result.failure_code,
        "task_id": result.task_id,
        "packet_sha256": packet_sha256,
        "attempt_id": attempt_id,
        "result_sha256": result_sha256,
    }


def _prepare_worker_bind(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return worker_protocol.bind_worker_attempt(
        home,
        task_id=_required_text(payload, "task_id"),
        packet_sha256=_required_text(payload, "packet_sha256"),
        host_session_id=_required_text(payload, "host_session_id"),
        attempt_id=_required_text(payload, "attempt_id"),
        project_id=_required_text(payload, "project_id"),
        worktree_id=_required_text(payload, "worktree_id"),
        callback_token=_required_text(payload, "callback_token"),
        host_generation=payload.get("host_generation"),
        native_attempt_id=payload.get("native_attempt_id"),
        native_job_id=payload.get("native_job_id"),
        agent_id=payload.get("agent_id"),
    )


def _prepare_worker_dispatch_failed(
    home: Path, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return worker_protocol.record_worker_dispatch_failure(
        home,
        task_id=_required_text(payload, "task_id"),
        packet_sha256=_required_text(payload, "packet_sha256"),
        host_session_id=_required_text(payload, "host_session_id"),
        attempt_id=_required_text(payload, "attempt_id"),
        project_id=_required_text(payload, "project_id"),
        worktree_id=_required_text(payload, "worktree_id"),
        callback_token=_required_text(payload, "callback_token"),
        failure_code=payload.get("failure_code"),
        host="omp",
    )


def _prepare_worker_lifecycle(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return worker_protocol.ingest_worker_lifecycle(
        home,
        task_id=_required_text(payload, "task_id"),
        packet_sha256=_required_text(payload, "packet_sha256"),
        host_session_id=_required_text(payload, "host_session_id"),
        attempt_id=_required_text(payload, "attempt_id"),
        project_id=_required_text(payload, "project_id"),
        worktree_id=_required_text(payload, "worktree_id"),
        callback_token=_required_text(payload, "callback_token"),
        host_generation=payload.get("host_generation"),
        native_attempt_id=payload.get("native_attempt_id"),
        native_job_id=payload.get("native_job_id"),
        agent_id=payload.get("agent_id"),
        sequence=payload.get("sequence"),
        outcome=payload.get("outcome"),
        executor_settled=payload.get("executor_settled"),
        cleanup_complete=payload.get("cleanup_complete"),
        host="omp",
    )


def handle_request(home: Path | str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return one bounded OMP routing or worker-context response."""
    if not isinstance(payload, Mapping):
        return {"decision": None, "error": "MALFORMED_ROUTING_INPUT"}
    if payload.get("operation") == "worker_context":
        try:
            return _prepare_worker_context(Path(home), payload)
        except contracts.WorkerPacketError as exc:
            return {"status": "failed", "failure_code": exc.code}
        except Exception:
            return {"status": "failed", "failure_code": "CONTEXT_UNAVAILABLE"}
    if payload.get("operation") in {
        "worker_bind",
        "worker_dispatch_failed",
        "worker_lifecycle",
    }:
        try:
            if payload.get("operation") == "worker_bind":
                return _prepare_worker_bind(Path(home), payload)
            if payload.get("operation") == "worker_dispatch_failed":
                return _prepare_worker_dispatch_failed(Path(home), payload)
            return _prepare_worker_lifecycle(Path(home), payload)
        except contracts.WorkerPacketError as exc:
            return {"status": "rejected", "failure_code": exc.code}
        except Exception:
            return {"status": "rejected", "failure_code": "PERSISTENCE_UNAVAILABLE"}
    if payload.get("operation") == "worker_result":
        try:
            return _prepare_worker_result(Path(home), payload)
        except contracts.WorkerPacketError as exc:
            return {
                "status": "failed",
                "failure_code": exc.code,
                "task_id": _text(payload.get("task_id")),
            }
        except Exception:
            return {
                "status": "failed",
                "failure_code": "RESULT_UNAVAILABLE",
                "task_id": _text(payload.get("task_id")),
            }
    if payload.get("operation") == "skill_visibility":
        try:
            return _prepare_skill_visibility(Path(home), payload)
        except Exception:
            return {
                "visibility_plan": None,
                "hydrated_instructions": {},
                "error": "VISIBILITY_UNAVAILABLE",
            }
    if payload.get("operation") == "handoff_create":
        try:
            return _prepare_handoff_create(Path(home), payload)
        except contracts.HandoffError as exc:
            return {"status": "failed", "failure_code": exc.code}
        except Exception:
            return {"status": "failed", "failure_code": "HANDOFF_UNAVAILABLE"}
    if payload.get("operation") == "handoff_read":
        try:
            return _prepare_handoff_read(Path(home), payload)
        except contracts.HandoffError as exc:
            return {"status": "failed", "failure_code": exc.code}
        except Exception:
            return {"status": "failed", "failure_code": "HANDOFF_UNAVAILABLE"}
    task = _text(payload.get("task"), _MAX_TASK_CHARS)
    if not task:
        return {"decision": None, "error": "NO_TASK"}
    try:
        session_id = _text(payload.get("host_session_id") or payload.get("session_id"))
        role = _text(payload.get("bot_role") or payload.get("role")) or "worker"
        project_id = _text(payload.get("project_id"))
        decision = model_routing.route_model(
            task,
            _candidates(payload, role),
            role=role,
            task_id=_text(payload.get("task_id")),
            brain_session_id="",
            host_session_id=session_id,
            project_id=project_id,
            bot_name="omp",
            policy_profile=_text(payload.get("policy_profile")) or "default",
            home=home,
            repo_root=_text(payload.get("cwd")) or str(home),
            files_touched=payload.get("files_touched", ()),
            capability_requirements=payload.get("capability_requirements", ()),
            risk_class=payload.get("risk_class"),
            risk_level=payload.get("risk_level"),
            risk_score=payload.get("risk_score"),
            user_criticality=payload.get("user_criticality"),
            minimum_tier=payload.get("minimum_tier"),
            max_tier=payload.get("max_tier"),
            max_cost_class=payload.get("max_cost_class", "high"),
            premium_justification=payload.get("premium_justification"),
            repeated_failure=bool(payload.get("repeated_failure", False)),
            ambiguity=bool(payload.get("ambiguity", False)),
            min_quality_score=payload.get("min_quality_score"),
        )
        return {"decision": decision.to_dict()}
    except model_routing.ModelRoutingError as exc:
        return {"decision": None, "error": str(exc)[:128]}
    except Exception:
        return {"decision": None, "error": "BRAIN_ROUTING_UNAVAILABLE"}
