"""Thin OMP-to-Second-Brain transport adapters.

OMP owns lifecycle and request transport. Brain owns model decisions and the
bounded worker-context handoff; this module only validates host packets and
calls the existing Brain primitives.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import contracts, ledger, model_routing, skills, worker_protocol, working_set

_MAX_TASK_CHARS = 2048
_MAX_IDENTITY_CHARS = 128
_MAX_CANDIDATES = model_routing.MAX_CANDIDATES


def _text(value: Any, limit: int = _MAX_IDENTITY_CHARS) -> str:
    return value[:limit] if isinstance(value, str) else ""


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
        project_id=_text(payload.get("project_id")) or "default",
        repo_root=_text(payload.get("cwd")) or str(home),
    ).validate()
    handoff = worker_protocol.prepare_context_handoff(home, packet)
    return {
        "status": "prepared",
        "task_id": packet.task_id,
        "packet_sha256": packet.canonical_hash(),
        "worker_role": packet.requested_role,
        "worker_model": model,
        "context_metadata": worker_protocol.handoff_metadata(handoff),
        "context_handoff": handoff,
    }


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
    if payload.get("operation") == "skill_visibility":
        try:
            return _prepare_skill_visibility(Path(home), payload)
        except Exception:
            return {
                "visibility_plan": None,
                "hydrated_instructions": {},
                "error": "VISIBILITY_UNAVAILABLE",
            }
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
