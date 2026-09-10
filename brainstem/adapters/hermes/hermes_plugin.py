"""Standalone Hermes plugin for The Second Brain.

The plugin is deliberately small: Hermes supplies lifecycle callbacks,
host-frozen prompt sections, and ephemeral context injection; the Brain CLI
owns identity, retrieval, durable writes, telemetry, and the session ledger.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PLUGIN_VERSION = "0.1.0"
_MAX_MODEL_CANDIDATES = 32
_MAX_DECISION_CACHE = 64
_MAX_LIFECYCLE_VALUE_CHARS = 128

_WRITEBACK_SCHEMA = {
    "name": "second_brain_writeback",
    "description": (
        "Record one significant, evidence-backed project event in The Second Brain "
        "as a candidate memory. Do not use for routine chat or every command."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title for the significant event."},
            "observation": {
                "type": "string",
                "description": "The durable project fact or event, stated precisely.",
            },
            "guidance": {
                "type": "string",
                "description": "Optional bounded guidance for future agents.",
            },
            "evidence": {
                "type": "array",
                "description": "Evidence references supporting the event.",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["evidence", "episode", "test", "decision", "import"],
                        },
                    },
                    "required": ["ref"],
                },
            },
        },
        "required": ["title", "observation"],
    },
}

_DELEGATE_SCHEMA = {
    "name": "second_brain_delegate",
    "description": (
        "Submit one bounded Brain WorkerTaskPacket to a persistent Hermes worker profile."
    ),
    "parameters": {
        "type": "object",
        "properties": {"packet": {"type": "object"}},
        "required": ["packet"],
    },
}
_REVIEW_SCHEMA = {
    "name": "second_brain_review_worker_result",
    "description": "Record coordinator review of one bounded Brain WorkerResultPacket.",
    "parameters": {
        "type": "object",
        "properties": {
            "result": {"type": "object"},
            "approved": {"type": "boolean"},
            "evidence": {
                "oneOf": [{"type": "object"}, {"type": "array"}],
                "description": "Bounded postcondition evidence: an exit-0 test or SHA-256 diff.",
            },
        },
        "required": ["result"],
    },
}
_CORRECT_SCHEMA = {
    "name": "second_brain_correct_worker_result",
    "description": (
        "Reject one bounded worker result, request a bounded same-task correction, "
        "and return the corrected result for final review."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "packet": {"type": "object"},
            "result": {"type": "object"},
            "reason": {"type": "string"},
            "requested_changes": {"type": "array", "items": {"type": "string"}},
            "evidence_requirements": {"type": "array", "items": {"type": "string"}},
            "correction_attempt": {"type": "integer"},
        },
        "required": ["packet", "result", "reason"],
    },
}
_HANDOFF_READ_SCHEMA = {
    "name": "second_brain_handoff_read",
    "description": (
        "Validate and losslessly recover a Brain Handoff Envelope (P3.17) produced by "
        "another harness. Returns the bounded continuation state (objective, "
        "verification, decisions, next_action) without any source transcript."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "envelope": {"type": "object", "description": "The BrainHandoffEnvelope JSON object."},
            "project_id": {
                "type": "string",
                "description": "Expected project id; mismatch is rejected.",
            },
            "allow_stale": {
                "type": "boolean",
                "description": (
                    "Accept and explicitly classify stale capsule state instead of rejecting."
                ),
            },
        },
        "required": ["envelope"],
    },
}


@dataclass(frozen=True)
class _Settings:
    brain_home: Path
    brain_python: str
    bot_name: str
    bot_role: str
    project_id: str | None
    repo_root: str
    timeout_seconds: float
    worker_profile: str
    hermes_cli: str
    worker_timeout_seconds: float
    model_candidates: tuple[dict[str, Any], ...] | None


def _configured_candidates(value: Any) -> tuple[dict[str, Any], ...] | None:
    """Normalize only bounded provider/model metadata from plugin settings."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > _MAX_MODEL_CANDIDATES:
        return ()
    candidates: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return ()
        candidate: dict[str, Any] = {}
        for key in ("provider", "model", "tier", "cost", "cost_class", "availability"):
            if key in item:
                candidate[key] = item[key]
        for key in ("capabilities", "capability"):
            if key in item:
                raw = item[key]
                if isinstance(raw, list):
                    candidate[key] = [str(label)[:_MAX_LIFECYCLE_VALUE_CHARS] for label in raw[:16]]
                elif isinstance(raw, str):
                    candidate[key] = raw[:_MAX_LIFECYCLE_VALUE_CHARS]
        candidates.append(candidate)
    return tuple(candidates)


def _config(ctx: Any, key: str, default: Any = None) -> Any:
    try:
        return ctx.get_config(key, default=default)
    except Exception:
        return default


def _settings(ctx: Any) -> _Settings:
    configured_home = _config(ctx, "brain_home")
    brain_home = Path(
        str(
            configured_home
            or os.environ.get("SECOND_BRAIN_HOME")
            or Path.home() / "Documents" / "The-Second-Brain"
        )
    ).expanduser()
    configured_python = _config(ctx, "brain_python")
    if configured_python:
        brain_python = str(configured_python)
    else:
        candidate = brain_home / (
            ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
        )
        brain_python = (
            str(candidate) if candidate.is_file() else (shutil.which("brainctl") or sys.executable)
        )
    bot_name = str(_config(ctx, "bot_name", default="") or "")
    if not bot_name:
        bot_name = str(getattr(ctx, "profile_name", "") or "hermes-bot")
    bot_role = str(_config(ctx, "bot_role", default="") or "")
    if not bot_role:
        bot_role = {
            "brain-dev": "dev",
            "brain-validator": "validator",
            "brain-integrator": "integrator",
        }.get(bot_name.lower(), "worker")
    configured_project = _config(ctx, "project_id")
    project_id = str(configured_project) if configured_project else None
    repo_root = str(
        _config(
            ctx,
            "repo_root",
            default=os.environ.get("TERMINAL_CWD") or os.getcwd(),
        )
        or os.getcwd()
    )
    try:
        timeout_seconds = max(1.0, float(_config(ctx, "timeout_seconds", default=5.0)))
    except (TypeError, ValueError):
        timeout_seconds = 5.0
    return _Settings(
        brain_home=brain_home,
        brain_python=brain_python,
        bot_name=bot_name,
        bot_role=bot_role,
        project_id=project_id,
        repo_root=repo_root,
        timeout_seconds=timeout_seconds,
        worker_profile=str(_config(ctx, "worker_profile", default="") or ""),
        hermes_cli=str(_config(ctx, "hermes_cli", default="hermes") or "hermes"),
        worker_timeout_seconds=max(
            30.0, float(_config(ctx, "worker_timeout_seconds", default=180.0) or 180.0)
        ),
        model_candidates=_configured_candidates(_config(ctx, "model_candidates")),
    )


class _BrainClient:
    def __init__(self, settings: _Settings) -> None:
        self.settings = settings

    def request(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        env = dict(os.environ)
        for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
            env.pop(key, None)
        env["SECOND_BRAIN_HOME"] = str(self.settings.brain_home)
        if Path(self.settings.brain_python).name.lower().startswith("brainctl"):
            command = [
                self.settings.brain_python,
                "--home",
                str(self.settings.brain_home),
                "autoinject",
                "hermes-hook",
            ]
        else:
            command = [
                self.settings.brain_python,
                "-P",
                "-m",
                "second_brain",
                "--home",
                str(self.settings.brain_home),
                "autoinject",
                "hermes-hook",
            ]
        try:
            result = subprocess.run(
                command,
                input=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                capture_output=True,
                text=True,
                cwd=self.settings.brain_home,
                env=env,
                timeout=self.settings.timeout_seconds,
                check=False,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        for line in reversed(result.stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None


def _common(
    settings: _Settings,
    session_id: str | None,
    model: str | None,
    provider: str | None,
) -> dict[str, Any]:
    return {
        "hermes_session_id": session_id or os.environ.get("HERMES_SESSION_ID") or "hermes-anon",
        "bot_name": settings.bot_name,
        "bot_role": settings.bot_role,
        "project_id": settings.project_id,
        "repo_root": settings.repo_root,
        "provider": provider or "unknown",
        "model": model or "unknown",
    }


def _raw_result_transport(value: Any) -> Any:
    """Preserve a complete JSON-safe Hermes result for Brain-side storage."""
    if isinstance(value, bytes):
        return {"__hermes_raw_bytes_b64": base64.b64encode(value).decode("ascii")}
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return {"__hermes_raw_text": str(value)}
    return value


def _bounded_lifecycle_value(value: Any, limit: int = 2000) -> Any:
    """Keep observer metrics JSON-safe and free of response/task content."""
    if isinstance(value, dict):
        allowed = {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "amount",
            "value",
            "currency",
            "unit",
        }
        return {
            str(key)[:64]: _bounded_lifecycle_value(item, 128)
            for key, item in list(value.items())[:16]
            if str(key) in allowed
        }
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:limit]


def _invoke_persistent_worker(
    settings: _Settings,
    packet: dict[str, Any],
    context_handoff: dict[str, Any] | None = None,
    correction: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Invoke only the configured persistent Hermes profile; never parent history."""
    profile = settings.worker_profile or {
        "dev": "dev",
        "validator": "validator",
    }.get(str(packet.get("requested_role", "")))
    if not profile:
        return None
    worker_role = str(packet.get("requested_role", "worker"))
    worker_bot = {
        "dev": "Brain-Dev",
        "validator": "Brain-Validator",
        "worker": "Brain-Worker",
    }.get(worker_role, f"Brain-{worker_role.title()}")
    worker_payload: dict[str, Any] = {"worker_task_packet": packet}
    if context_handoff:
        worker_payload["worker_context_handoff"] = context_handoff
    if correction is not None:
        worker_payload["worker_correction"] = correction
    worker_prompt = (
        "You are a Second Brain worker. Execute only this bounded task packet. "
        "Do not edit files, write memory, delegate, use A2A, or copy parent history. "
        "Use read-only inspection only and return a concise structured evidence report.\n\n"
        + json.dumps(worker_payload, sort_keys=True, separators=(",", ":"))
    )
    started_at = time.time()
    command = [
        *shlex.split(settings.hermes_cli),
        "-p",
        profile,
        "chat",
        "-Q",
        "--reasoning",
        "none",
        "--pass-session-id",
        "--in",
        settings.repo_root,
        "--max-turns",
        "12",
        "--run-budget",
        str(int(settings.worker_timeout_seconds)),
        "--query-file",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            input=worker_prompt,
            capture_output=True,
            text=True,
            cwd=settings.repo_root,
            timeout=settings.worker_timeout_seconds,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    output = completed.stdout.strip()
    match = re.search(r"session_id\s*:\s*([A-Za-z0-9_-]+)", output)
    worker_hermes_session = match.group(1) if match else None
    if worker_hermes_session is None:
        pattern = f"hermes-{worker_bot}-*.jsonl"
        candidates = sorted(
            (
                path
                for path in (settings.brain_home / "telemetry" / "agent-performance").glob(pattern)
                if path.stat().st_mtime >= started_at - 1
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("kind") == "hermes_session_started":
                    worker_hermes_session = str(record.get("hermes_session_id", "")) or None
                    break
            if worker_hermes_session:
                break
    if not output or worker_hermes_session is None:
        return None
    worker_host_session = f"hermes:{worker_bot}:{worker_hermes_session}"
    worker_brain_session = hashlib.sha256(worker_host_session.encode("utf-8")).hexdigest()
    return {
        "task_id": str(packet.get("task_id", "")),
        "worker_identity": {
            "agent_id": f"hermes:{worker_bot}",
            "internal_session_id": worker_brain_session,
            "host_agent_id": worker_bot,
            "parent_agent_id": str(packet.get("driver_identity", {}).get("agent_id", "")),
            "role_profile": worker_role,
            "model": "unknown",
            "provider": "unknown",
            "created_at": datetime.now(UTC).isoformat(),
        },
        "status": "completed",
        "summary": output[:4096],
        "evidence_refs": [],
        "limitations": ["worker response is bounded to 4096 characters"],
        "failure_code": None,
        "retryable": False,
        "correction_of_hash": correction.get("original_result_sha256") if correction else None,
        "correction_attempt": int(correction.get("correction_attempt", 0)) if correction else 0,
    }


def register(ctx: Any) -> None:
    """Register the thin Brain hooks and explicit worker tools."""
    settings = _settings(ctx)
    client = _BrainClient(settings)
    current_session: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "second_brain_hermes_session", default=None
    )
    delegated_results: dict[str, dict[str, Any]] = {}
    decision_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def cache_key(session_id: str | None, turn_id: Any) -> tuple[str, str]:
        return (
            str(
                session_id
                or current_session.get()
                or os.environ.get("HERMES_SESSION_ID")
                or "hermes-anon"
            ),
            str(turn_id or ""),
        )

    def cache_decision(
        session_id: str | None,
        turn_id: Any,
        decision: dict[str, Any] | None,
        *,
        host_provider: str | None = None,
        host_model: str | None = None,
        effective_provider: str | None = None,
        effective_model: str | None = None,
    ) -> None:
        if not isinstance(decision, dict):
            return
        decision_cache[cache_key(session_id, turn_id)] = {
            "decision": dict(decision),
            "host_provider": host_provider,
            "host_model": host_model,
            "effective_provider": effective_provider,
            "effective_model": effective_model,
        }
        while len(decision_cache) > _MAX_DECISION_CACHE:
            decision_cache.pop(next(iter(decision_cache)))

    def cached_decision(session_id: str | None, turn_id: Any) -> dict[str, Any] | None:
        entry = decision_cache.get(cache_key(session_id, turn_id))
        return entry if isinstance(entry, dict) else None

    def bounded_text(value: Any, limit: int = _MAX_LIFECYCLE_VALUE_CHARS) -> str:
        return str(value or "")[:limit]

    def model_identity(provider: Any, model: Any, tier: Any = None) -> dict[str, str] | None:
        if not isinstance(provider, str) or not provider:
            return None
        if not isinstance(model, str) or not model:
            return None
        return {
            "provider": bounded_text(provider),
            "model": bounded_text(model),
            "tier": bounded_text(tier),
        }

    def lifecycle_event(
        event: str,
        *,
        session_id: str | None,
        turn_id: Any,
        api_request_id: Any,
        model: Any,
        provider: Any,
        status: Any,
        response_model: Any = None,
        usage: Any = None,
        cost: Any = None,
        failure_code: Any = None,
    ) -> None:
        entry = cached_decision(session_id, turn_id)
        decision = entry.get("decision", {}) if entry else {}
        selected = model_identity(
            decision.get("selected_provider"),
            decision.get("selected_model"),
            decision.get("selected_tier"),
        )
        effective_provider = (entry.get("effective_provider") if entry else None) or (
            provider if isinstance(provider, str) else None
        )
        effective_model = (entry.get("effective_model") if entry else None) or (
            model if isinstance(model, str) else None
        )
        actual_model = (
            response_model
            if isinstance(response_model, str) and response_model
            else effective_model
        )
        actual = model_identity(effective_provider, actual_model)
        payload: dict[str, Any] = {
            "event": event,
            "turn_id": bounded_text(turn_id),
            "api_request_id": bounded_text(api_request_id),
            "decision_id": bounded_text(decision.get("decision_id")),
            "selected_identity": selected,
            "actual_identity": actual,
            "response_model": bounded_text(response_model),
            "status": bounded_text(status or "unknown"),
        }
        if decision.get("fallback_used"):
            payload["fallback_used"] = True
            payload["fallback_identity"] = model_identity(
                decision.get("fallback_provider"),
                decision.get("fallback_model"),
                decision.get("selected_tier"),
            )
            payload["fallback_reason"] = bounded_text(decision.get("fallback_reason"))
            payload["original_selected_identity"] = model_identity(
                decision.get("original_selected_provider"),
                decision.get("original_selected_model"),
                decision.get("original_selected_tier"),
            )
        if usage is not None:
            payload["usage"] = _bounded_lifecycle_value(usage)
        if cost is not None:
            payload["cost"] = _bounded_lifecycle_value(cost)
        if failure_code:
            payload["failure_code"] = bounded_text(failure_code)
        client.request(_common(settings, session_id, actual_model, effective_provider) | payload)

    def remember_result(result: dict[str, Any] | None) -> None:
        if not isinstance(result, dict) or not result.get("task_id"):
            return
        delegated_results[str(result["task_id"])] = dict(result)
        while len(delegated_results) > 16:
            delegated_results.pop(next(iter(delegated_results)))

    session_start_responses: dict[str, dict[str, Any]] = {}

    def session_start_response(
        session_id: str | None, model: str | None, provider: str | None
    ) -> dict[str, Any] | None:
        active_session = session_id or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        cache_key = str(active_session or "hermes-anon")
        cached = session_start_responses.get(cache_key)
        if cached is not None:
            return cached
        response = client.request(
            _common(settings, active_session, model, provider) | {"event": "session_start"}
        )
        if isinstance(response, dict) and isinstance(response.get("prefix"), str):
            session_start_responses[cache_key] = dict(response)
            while len(session_start_responses) > 16:
                session_start_responses.pop(next(iter(session_start_responses)))
        return response

    def system_prompt_section(session_info: Any) -> str:
        if not isinstance(session_info, Mapping):
            return ""
        response = session_start_response(
            str(session_info.get("session_id") or "") or None,
            str(session_info.get("model") or "") or None,
            str(session_info.get("provider") or "") or None,
        )
        prefix = response.get("prefix") if response else None
        return prefix.strip() if isinstance(prefix, str) else ""

    def on_session_start(
        session_id: str | None = None,
        model: str | None = None,
        platform: str | None = None,
        **kwargs: Any,
    ) -> None:
        del platform
        active_session = session_id or os.environ.get("HERMES_SESSION_ID")
        current_session.set(active_session)
        session_start_response(active_session, model, kwargs.get("provider"))

    def pre_tool_call(
        tool_name: str | None = None,
        args: Any = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        del tool_name, args, kwargs
        active_session = session_id or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        current_session.set(active_session)
        return None

    def pre_llm_call(
        session_id: str | None = None,
        user_message: str | None = None,
        model: str | None = None,
        platform: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str] | None:
        del platform
        active_session = session_id or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        current_session.set(active_session)
        turn_id = kwargs.get("turn_id")
        provider = kwargs.get("provider")
        candidates = settings.model_candidates
        if candidates is None:
            candidates = (
                ({"provider": provider, "model": model},)
                if isinstance(provider, str) and provider and isinstance(model, str) and model
                else ()
            )
        response = client.request(
            _common(settings, active_session, model, provider)
            | {
                "event": "pre_llm_call",
                "task": user_message or "",
                "turn_id": turn_id,
                "model_candidates": [dict(candidate) for candidate in candidates],
            }
        )
        if response and isinstance(response.get("model_decision"), dict):
            cache_decision(
                active_session,
                turn_id,
                response["model_decision"],
                host_provider=provider,
                host_model=model,
            )
        tail = response.get("tail") if response else None
        if not tail and response:
            packet = response.get("packet")
            vmem_block = response.get("vmem_context", {}).get("rendered_text")
            blocks = [block for block in (packet, vmem_block) if isinstance(block, str) and block]
            tail = "\n\n".join(blocks) if blocks else None

        result: dict[str, str] = {}
        if isinstance(tail, str) and tail:
            result["context"] = tail
        return result if result else None

    def llm_request_middleware(
        request: dict[str, Any] | None = None,
        original_request: dict[str, Any] | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        api_request_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del kwargs
        original = original_request if isinstance(original_request, dict) else request
        if not isinstance(original, dict):
            original = {}
        entry = cached_decision(session_id, turn_id)
        decision = entry.get("decision", {}) if entry else {}
        selected = model_identity(
            decision.get("selected_provider"),
            decision.get("selected_model"),
            decision.get("selected_tier"),
        )
        host_provider = entry.get("host_provider") if entry else provider
        host_model = entry.get("host_model") if entry else model
        provider_in_request = "provider" in original
        extra_body = original.get("extra_body")
        provider_in_extra = isinstance(extra_body, dict) and "provider" in extra_body
        extra_provider = extra_body.get("provider") if isinstance(extra_body, dict) else None
        effective_provider = (
            original.get("provider")
            if provider_in_request
            else (extra_provider if provider_in_extra else host_provider)
        )
        effective_model = original.get("model", host_model)
        marker: dict[str, Any] = {
            "decision_id": bounded_text(decision.get("decision_id")),
            "selected_identity": selected,
            "actual_identity": model_identity(effective_provider, effective_model),
            "status": "no_decision" if not selected else "unchanged",
        }
        if selected is None:
            return {"request": dict(original), "trace_marker": marker, "trace": marker}

        provider_mismatch = selected["provider"] != effective_provider
        model_representable = "model" in original or selected["model"] == effective_model
        if provider_mismatch and not (provider_in_request or provider_in_extra):
            marker["status"] = "handoff_failed"
            lifecycle_event(
                "api_request_error",
                session_id=session_id,
                turn_id=turn_id,
                api_request_id=api_request_id,
                model=effective_model,
                provider=effective_provider,
                status="failed",
                failure_code="MODEL_PROVIDER_HANDOFF_UNREPRESENTABLE",
            )
            return {"request": dict(original), "trace_marker": marker, "trace": marker}
        if not model_representable:
            return {"request": dict(original), "trace_marker": marker, "trace": marker}
        rewritten = dict(original)
        rewritten["model"] = selected["model"]
        if provider_in_request:
            rewritten["provider"] = selected["provider"]
        elif provider_in_extra and isinstance(extra_body, dict):
            rewritten["extra_body"] = {**extra_body, "provider": selected["provider"]}
        actual_provider = (
            selected["provider"]
            if (provider_in_request or provider_in_extra)
            else effective_provider
        )
        if entry is not None:
            entry["effective_provider"] = actual_provider
            entry["effective_model"] = selected["model"]
        marker["actual_identity"] = model_identity(
            actual_provider,
            selected["model"],
            selected.get("tier"),
        )
        marker["status"] = "rewritten"
        return {"request": rewritten, "trace_marker": marker, "trace": marker}

    def post_api_request(
        session_id: str | None = None,
        turn_id: str | None = None,
        api_request_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        response: Any = None,
        **kwargs: Any,
    ) -> None:
        response_model = kwargs.get("response_model")
        if response_model is None and isinstance(response, dict):
            response_model = response.get("model")
        lifecycle_event(
            "post_api_request",
            session_id=session_id,
            turn_id=turn_id,
            api_request_id=api_request_id,
            model=kwargs.get("actual_model", model),
            provider=kwargs.get("actual_provider", provider),
            status=kwargs.get("status", "completed"),
            response_model=response_model,
            usage=kwargs.get("usage"),
            cost=kwargs.get("cost"),
        )

    def api_request_error(
        session_id: str | None = None,
        turn_id: str | None = None,
        api_request_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        error: Any = None,
        **kwargs: Any,
    ) -> None:
        del error
        lifecycle_event(
            "api_request_error",
            session_id=session_id,
            turn_id=turn_id,
            api_request_id=api_request_id,
            model=kwargs.get("actual_model", model),
            provider=kwargs.get("actual_provider", provider),
            status=kwargs.get("status", "failed"),
            response_model=kwargs.get("response_model"),
            usage=kwargs.get("usage"),
            cost=kwargs.get("cost"),
            failure_code=kwargs.get("failure_code"),
        )

    def post_tool_call(
        tool_name: str | None = None,
        args: Any = None,
        result: Any = None,
        session_id: str | None = None,
        tool_call_id: str | None = None,
        turn_id: str | None = None,
        status: str | None = None,
        **kwargs: Any,
    ) -> None:
        active_session = session_id or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        current_session.set(active_session)

        def bounded(value: Any, limit: int) -> str:
            try:
                text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
            except Exception:
                text = str(value)
            return text[:limit]

        client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {
                "event": "post_tool_call",
                "tool_name": str(tool_name or "unknown")[:200],
                "args": bounded(args, 1000),
                "result": bounded(result, 4000),
                "raw_result": _raw_result_transport(result),
                "tool_call_id": str(tool_call_id or "")[:200],
                "turn_id": str(turn_id or "")[:200],
                "status": str(status or "unknown")[:100],
            }
        )

    def on_session_finalize(
        session_id: str | None = None,
        completed: bool = False,
        interrupted: bool = False,
        model: str | None = None,
        platform: str | None = None,
        **kwargs: Any,
    ) -> None:
        del completed, interrupted, platform
        active_session = session_id or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        client.request(
            _common(settings, active_session, model, kwargs.get("provider"))
            | {"event": "session_end"}
        )

    def delegate(params: dict[str, Any], **kwargs: Any) -> str:
        active_session = (
            kwargs.get("session_id") or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        )
        packet = params.get("packet")
        if not isinstance(packet, dict):
            return json.dumps(
                {"status": "failed", "failure_code": "MALFORMED_TASK"}, separators=(",", ":")
            )
        prepared = client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {"event": "worker_task_prepare", "packet": packet}
        )
        if prepared and prepared.get("terminal_noop"):
            return json.dumps(
                prepared,
                sort_keys=True,
                separators=(",", ":"),
            )
        if not prepared or prepared.get("status") != "prepared":
            return json.dumps(
                prepared or {"status": "failed", "failure_code": "CONTEXT_REF_UNRESOLVED"},
                sort_keys=True,
                separators=(",", ":"),
            )
        result = _invoke_persistent_worker(settings, packet, prepared.get("context_handoff", {}))
        remember_result(result)
        response = client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {
                "event": "worker_task_request",
                "packet": packet,
                "result": result,
                "context_handoff": prepared.get("context_handoff", {}),
            }
        )
        if isinstance(response, dict) and isinstance(result, dict):
            cached = dict(result)
            for key in ("packet_sha256", "result_sha256"):
                if response.get(key):
                    cached[key] = response[key]
            if (
                isinstance(response.get("result"), dict)
                and response["result"].get("evidence") is not None
            ):
                cached["evidence"] = response["result"]["evidence"]
            remember_result(cached)
        return json.dumps(
            response or {"status": "failed", "failure_code": "WORKER_UNAVAILABLE"},
            sort_keys=True,
            separators=(",", ":"),
        )

    def correct(params: dict[str, Any], **kwargs: Any) -> str:
        active_session = (
            kwargs.get("session_id") or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        )
        packet = params.get("packet")
        result = params.get("result")
        if not isinstance(packet, dict) or not isinstance(result, dict):
            return json.dumps(
                {"status": "failed", "failure_code": "MALFORMED_CORRECTION"},
                separators=(",", ":"),
            )
        cached_result = delegated_results.get(str(packet.get("task_id", "")))
        if cached_result is not None:
            result = dict(cached_result)
        prepared = client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {
                "event": "worker_task_prepare",
                "packet": packet,
                "purpose": "correction",
            }
        )
        if not prepared or prepared.get("status") != "prepared":
            return json.dumps(
                prepared or {"status": "failed", "failure_code": "CONTEXT_REF_UNRESOLVED"},
                sort_keys=True,
                separators=(",", ":"),
            )
        if prepared.get("duplicate") and "context_handoff" not in prepared:
            return json.dumps(
                prepared,
                sort_keys=True,
                separators=(",", ":"),
            )
        correction_response = client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {
                "event": "worker_result_correction",
                "packet": packet,
                "result": result,
                "reason": params.get("reason", ""),
                "requested_changes": params.get("requested_changes", []),
                "evidence_requirements": params.get("evidence_requirements", []),
                "correction_attempt": params.get("correction_attempt", 1),
            }
        )
        if not correction_response or correction_response.get("status") != "correction_requested":
            return json.dumps(
                correction_response or {"status": "failed", "failure_code": "BRAIN_UNAVAILABLE"},
                sort_keys=True,
                separators=(",", ":"),
            )
        correction = correction_response["correction"]
        corrected = _invoke_persistent_worker(
            settings,
            packet,
            prepared.get("context_handoff", {}),
            correction,
        )
        if corrected is None:
            return json.dumps(
                {
                    **correction_response,
                    "status": "failed",
                    "failure_code": "WORKER_UNAVAILABLE",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        remember_result(corrected)
        response = client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {
                "event": "worker_result_corrected",
                "packet": packet,
                "original_result": result,
                "correction": correction,
                "result": corrected,
                "context_handoff": prepared.get("context_handoff", {}),
            }
        )
        if isinstance(response, dict) and isinstance(corrected, dict):
            cached = dict(corrected)
            for key in ("packet_sha256", "result_sha256"):
                if response.get(key):
                    cached[key] = response[key]
            if (
                isinstance(response.get("result"), dict)
                and response["result"].get("evidence") is not None
            ):
                cached["evidence"] = response["result"]["evidence"]
            remember_result(cached)
        return json.dumps(
            response or {"status": "failed", "failure_code": "BRAIN_UNAVAILABLE"},
            sort_keys=True,
            separators=(",", ":"),
        )

    def review(params: dict[str, Any], **kwargs: Any) -> str:
        active_session = (
            kwargs.get("session_id") or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        )
        result = params.get("result")
        if isinstance(result, dict):
            cached_result = delegated_results.get(str(result.get("task_id", "")))
            if cached_result is not None:
                result = dict(cached_result)
        response = client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {
                "event": "worker_result_review",
                "result": result,
                "approved": params.get("approved", True),
                "evidence": params.get("evidence"),
            }
        )
        return json.dumps(
            response or {"status": "failed", "failure_code": "BRAIN_UNAVAILABLE"},
            sort_keys=True,
            separators=(",", ":"),
        )

    def writeback(params: dict[str, Any], **kwargs: Any) -> str:
        active_session = (
            kwargs.get("session_id") or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        )
        evidence = params.get("evidence", [])
        if evidence is None:
            evidence = []
        response = client.request(
            _common(settings, active_session, kwargs.get("model"), kwargs.get("provider"))
            | {
                "event": "writeback",
                "title": params.get("title", ""),
                "observation": params.get("observation", ""),
                "guidance": params.get("guidance", ""),
                "evidence": evidence,
            }
        )
        return json.dumps(
            response or {"status": "fail_open"},
            sort_keys=True,
            separators=(",", ":"),
        )

    def handoff_read(params: dict[str, Any], **kwargs: Any) -> str:
        active_session = (
            kwargs.get("session_id") or current_session.get() or os.environ.get("HERMES_SESSION_ID")
        )
        envelope = params.get("envelope")
        request_payload = _common(
            settings, active_session, kwargs.get("model"), kwargs.get("provider")
        ) | {
            "event": "handoff_read",
            "envelope": envelope if isinstance(envelope, dict) else {},
        }
        if params.get("project_id"):
            request_payload["project_id"] = str(params["project_id"])
        if "allow_stale" in params:
            request_payload["allow_stale"] = bool(params["allow_stale"])
        response = client.request(request_payload)
        return json.dumps(
            response or {"status": "fail_open"},
            sort_keys=True,
            separators=(",", ":"),
        )

    register_prompt_section = getattr(ctx, "register_system_prompt_section", None)
    if callable(register_prompt_section):
        register_prompt_section(
            "second-brain-prefix",
            system_prompt_section,
            position="after_memory",
        )
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("post_api_request", post_api_request)
    ctx.register_hook("api_request_error", api_request_error)
    ctx.register_hook("on_session_finalize", on_session_finalize)
    ctx.register_middleware("llm_request", llm_request_middleware)
    ctx.register_tool(
        name="second_brain_writeback",
        toolset="second_brain",
        schema=_WRITEBACK_SCHEMA,
        handler=writeback,
        description=_WRITEBACK_SCHEMA["description"],
    )
    ctx.register_tool(
        name="second_brain_delegate",
        toolset="second_brain",
        schema=_DELEGATE_SCHEMA,
        handler=delegate,
        description=_DELEGATE_SCHEMA["description"],
    )
    ctx.register_tool(
        name="second_brain_review_worker_result",
        toolset="second_brain",
        schema=_REVIEW_SCHEMA,
        handler=review,
        description=_REVIEW_SCHEMA["description"],
    )
    ctx.register_tool(
        name="second_brain_correct_worker_result",
        toolset="second_brain",
        schema=_CORRECT_SCHEMA,
        handler=correct,
        description=_CORRECT_SCHEMA["description"],
    )
    ctx.register_tool(
        name="second_brain_handoff_read",
        toolset="second_brain",
        schema=_HANDOFF_READ_SCHEMA,
        handler=handoff_read,
        description=_HANDOFF_READ_SCHEMA["description"],
    )
