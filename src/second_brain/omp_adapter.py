"""OMP transport for approved skill visibility and durable memory handoffs.

OMP owns agent, model, tool and task lifecycles. Legacy execution-control
operations refuse before opening a Brain home or creating state.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import contracts, handoff, skills
from .errors import BrainError
from .security.identifiers import validate_project_id

_MAX_TASK_CHARS = 2048
_MAX_IDENTITY_CHARS = 128
_RETIRED_WORKER_OPERATIONS = frozenset(
    {"worker_context", "worker_bind", "worker_dispatch_failed", "worker_lifecycle", "worker_result"}
)


def _text(value: Any, limit: int = _MAX_IDENTITY_CHARS) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _project_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("project_id")
    return validate_project_id(value) if value not in (None, "") else ""


def _prepare_skill_visibility(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    task = _text(payload.get("task"), _MAX_TASK_CHARS)
    if not task:
        return {"visibility_plan": None, "hydrated_instructions": {}, "error": "NO_TASK"}
    session_id = _text(payload.get("host_session_id") or payload.get("session_id"))
    project_id = _project_id(payload)
    plan = skills.build_plan(home, task, session_id=session_id, project_id=project_id)
    plan, hydrated_bodies = skills.hydrate_plan(home, plan)
    return {
        "visibility_plan": skills.plan_to_evidence(plan),
        "hydrated_instructions": hydrated_bodies,
        "error": None,
    }


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
        project_id=_project_id(payload),
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
        expected_project_id=_project_id(payload) or None,
        allow_stale=bool(payload.get("allow_stale", False)),
    )


def handle_request(home: Path | str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Dispatch retained context calls; reject retired operations without side effects."""
    if not isinstance(payload, Mapping):
        return {"status": "failed", "failure_code": "MALFORMED_REQUEST"}
    operation = payload.get("operation")
    if isinstance(operation, str) and operation in _RETIRED_WORKER_OPERATIONS:
        return {"status": "failed", "failure_code": "ORCHESTRATION_REMOVED"}
    if operation == "skill_visibility":
        try:
            return _prepare_skill_visibility(Path(home), payload)
        except BrainError:
            return {
                "visibility_plan": None,
                "hydrated_instructions": {},
                "error": "INVALID_PROJECT_ID",
            }
        except Exception:
            return {
                "visibility_plan": None,
                "hydrated_instructions": {},
                "error": "VISIBILITY_UNAVAILABLE",
            }
    if operation == "handoff_create":
        try:
            return _prepare_handoff_create(Path(home), payload)
        except contracts.HandoffError as exc:
            return {"status": "failed", "failure_code": exc.code}
        except BrainError:
            return {"status": "failed", "failure_code": "INVALID_PROJECT_ID"}
        except Exception:
            return {"status": "failed", "failure_code": "HANDOFF_UNAVAILABLE"}
    if operation == "handoff_read":
        try:
            return _prepare_handoff_read(Path(home), payload)
        except contracts.HandoffError as exc:
            return {"status": "failed", "failure_code": exc.code}
        except BrainError:
            return {"status": "failed", "failure_code": "INVALID_PROJECT_ID"}
        except Exception:
            return {"status": "failed", "failure_code": "HANDOFF_UNAVAILABLE"}
    if operation is None:
        return {"decision": None, "error": "MODEL_ROUTING_REMOVED"}
    return {"status": "failed", "failure_code": "UNSUPPORTED_OPERATION"}
