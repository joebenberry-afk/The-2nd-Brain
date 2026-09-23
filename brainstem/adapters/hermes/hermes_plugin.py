"""Standalone Hermes plugin for The Second Brain.

The plugin is deliberately small: Hermes supplies lifecycle callbacks,
host-frozen prompt sections, and ephemeral context injection; the Brain CLI
owns identity, retrieval, durable writes, telemetry, and the session ledger.
"""

from __future__ import annotations

import base64
import contextvars
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLUGIN_VERSION = "0.1.0"
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


def register(ctx: Any) -> None:
    """Register Brain context, memory and passive observer hooks."""
    settings = _settings(ctx)
    client = _BrainClient(settings)
    current_session: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "second_brain_hermes_session", default=None
    )

    def bounded_text(value: Any, limit: int = _MAX_LIFECYCLE_VALUE_CHARS) -> str:
        return str(value or "")[:limit]

    def model_identity(provider: Any, model: Any) -> dict[str, str] | None:
        if not isinstance(provider, str) or not provider:
            return None
        if not isinstance(model, str) or not model:
            return None
        return {"provider": bounded_text(provider), "model": bounded_text(model)}

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
        actual_model = (
            response_model if isinstance(response_model, str) and response_model else model
        )
        actual = model_identity(provider, actual_model)
        payload: dict[str, Any] = {
            "event": event,
            "turn_id": bounded_text(turn_id),
            "api_request_id": bounded_text(api_request_id),
            "actual_identity": actual,
            "response_model": bounded_text(response_model),
            "status": bounded_text(status or "unknown"),
        }
        if usage is not None:
            payload["usage"] = _bounded_lifecycle_value(usage)
        if cost is not None:
            payload["cost"] = _bounded_lifecycle_value(cost)
        if failure_code:
            payload["failure_code"] = bounded_text(failure_code)
        client.request(_common(settings, session_id, actual_model, provider) | payload)

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
        response = client.request(
            _common(settings, active_session, model, provider)
            | {
                "event": "pre_llm_call",
                "task": user_message or "",
                "turn_id": turn_id,
            }
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
    ctx.register_tool(
        name="second_brain_writeback",
        toolset="second_brain",
        schema=_WRITEBACK_SCHEMA,
        handler=writeback,
        description=_WRITEBACK_SCHEMA["description"],
    )
    ctx.register_tool(
        name="second_brain_handoff_read",
        toolset="second_brain",
        schema=_HANDOFF_READ_SCHEMA,
        handler=handoff_read,
        description=_HANDOFF_READ_SCHEMA["description"],
    )
