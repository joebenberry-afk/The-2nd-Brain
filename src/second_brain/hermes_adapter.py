"""Thin Hermes-to-Second-Brain lifecycle adapter.

Hermes owns the plugin lifecycle and ephemeral prompt injection. This module only
translates those callbacks into the existing Brain session, AutoInject, semantic
writeback, telemetry, and ledger primitives. It deliberately does not maintain a Hermes-
specific memory or retrieval store.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import subprocess
import tomllib
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
    injection_slots,
    ledger,
    router,
    skills,
    vmem,
)
from .errors import BrainError
from .security.identifiers import validate_project_id

ADAPTER_VERSION = "0.1.0"
_HOST = "hermes"
_RETIRED_EVENTS = frozenset(
    {
        "worker_task_prepare",
        "worker_task_request",
        "worker_event",
        "worker_result_review",
        "worker_result_correction",
        "worker_result_corrected",
    }
)
_SUPPORTED_EVENTS = frozenset(
    {
        "session_start",
        "pre_llm_call",
        "post_tool_call",
        "post_api_request",
        "api_request_error",
        "session_before_compact",
        "writeback",
        "session_end",
        "handoff_create",
        "handoff_read",
    }
)
_VMEM_HOT_CONTEXT_BUDGET = 512
_TOOL_RESULT_MAX_CHARS = 4000
_ATTRIBUTION_FIELD_MAX_CHARS = 64


_VMEM_CACHE_BREAKPOINT_FILE = "cache_breakpoints.json"
_SESSION_CACHE_STATE: dict[tuple[Path, str], dict[str, Any]] = {}


def _load_vmem_cache_state(home: Path, host_session_id: str) -> dict[str, Any]:
    key = (home.absolute(), host_session_id)
    if key in _SESSION_CACHE_STATE:
        return dict(_SESSION_CACHE_STATE[key])
    internal_id = ledger.internal_session_id(host_session_id)
    sdir = home / "state" / "sessions" / internal_id
    fpath = sdir / _VMEM_CACHE_BREAKPOINT_FILE
    if fpath.is_file():
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _SESSION_CACHE_STATE[key] = data
                return dict(data)
        except Exception:
            pass
    state = {
        "previous_rendered_context": None,
        "last_tool_result_bytes": 0,
        "session_before_compact": False,
        "last_provider": None,
        "last_model": None,
        "last_cache_read_tokens": None,
    }
    _SESSION_CACHE_STATE[key] = state
    return dict(state)


def _save_vmem_cache_state(home: Path, host_session_id: str, state: dict[str, Any]) -> None:
    _SESSION_CACHE_STATE[(home.absolute(), host_session_id)] = dict(state)
    internal_id = ledger.internal_session_id(host_session_id)
    sdir = home / "state" / "sessions" / internal_id
    sdir.mkdir(parents=True, exist_ok=True)
    fpath = sdir / _VMEM_CACHE_BREAKPOINT_FILE
    tmp = sdir / f"{_VMEM_CACHE_BREAKPOINT_FILE}.tmp.{os.getpid()}"
    try:
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(fpath)
    except Exception:
        with contextlib.suppress(Exception):
            fpath.write_text(json.dumps(state), encoding="utf-8")


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

    The raw Hermes session identifier is kept as metadata, while the canonical Brain
    host-session key includes the configured bot name. This prevents a reconnect from
    creating unrelated Brain state and keeps the three team bots distinguishable even
    when they use the same project.
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
    except BrainError:
        raise
    except Exception:
        project_id = validate_project_id(explicit_project or "default")

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


_REVIEW_EVIDENCE_MAX_BYTES = 4_096


def _injection_attribution(
    binding: HermesBinding,
    task: str,
    turn_id: str | None,
    decision: contracts.BrainInjectionDecision,
) -> dict[str, str]:
    """Build one bounded, privacy-safe attribution shared by all surfaces.

    The decision is always the value returned by the live AutoInject lifecycle
    authority.  The identifier contains no task text and is stable for the same host
    session, task hash, turn, and decision.
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
        with ledger.LedgerStore(home, binding.host_session_id, host=binding.session.host).open(
            create=True
        ) as store:
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

    with ledger.LedgerStore(home, binding.host_session_id, host=binding.session.host).open(
        create=True
    ) as store:
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
    """Run the visibility plan without owning routing state.

    Advisory/shadow by default; only 'enforced' mode may extend the returned packet.
    """
    try:
        plan = skills.build_plan(home, task, session_id=session_id, project_id=project_id)
        plan, hydrated_bodies = skills.hydrate_plan(home, plan)
        return skills.plan_to_evidence(plan), hydrated_bodies
    except Exception:
        return None, {}


def _estimate_resident_load(home: Path, objects: list[vmem.SessionObject], model: str) -> int:
    total = 0
    for o in objects:
        try:
            content_bytes = artifacts.expand(home, o.content_sha256)
            text = content_bytes.decode("utf-8", errors="replace")
            total += contracts.estimate_tokens(text, model=model, home=home)
        except Exception:
            if o.summary:
                total += contracts.estimate_tokens(o.summary, model=model, home=home)
            else:
                total += o.token_estimate
    return total


def _refresh_host_model_context(home: Path, session_id: str, provider: str, model: str) -> None:
    """Rebound Brain cache/VMem to the host-chosen context size, never select a model."""
    state = _load_vmem_cache_state(home, session_id)
    prior = (state.get("last_provider"), state.get("last_model"))
    if prior[0] is None or prior == (provider, model):
        return
    config = home / "config" / "v2.toml"
    capacity = 128_000
    cache_scope = "model"
    if config.is_file():
        data = tomllib.loads(config.read_text(encoding="utf-8"))
        entry = data.get("models", {}).get(model) or data.get("models", {}).get("default")
        if isinstance(entry, dict) and isinstance(entry.get("context_tokens"), int):
            capacity = max(1, entry["context_tokens"])
        provider_entry = data.get("providers", {}).get(provider) or data.get("providers", {}).get(
            "default"
        )
        if isinstance(provider_entry, dict) and provider_entry.get("cache_scope") == "account":
            cache_scope = "account"
    if cache_scope == "model":
        state["last_cache_read_tokens"] = 0
    state["previous_rendered_context"] = None
    _save_vmem_cache_state(home, session_id, state)
    store = vmem.VMemStore(home, session_id)
    resident = [
        obj
        for obj in store.list_objects()
        if obj.residency_state in (vmem.ResidencyState.RESIDENT, vmem.ResidencyState.FAULTED_IN)
    ]
    if _estimate_resident_load(home, resident, model) > int(capacity * 0.85):
        store.evict_to_budget(max_tokens=int(capacity * 0.85))


def _vmem_context(
    home: Path,
    binding: HermesBinding,
    task: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render existing VMem and fault in a task-referenced cold object.

    Enforces cache break-point gate (a)-(e): (a) previous tool_result bytes >
    [rtd].threshold_chars (default 8000); (b) session_before_compact event occurred; (c)
    model/provider changed since last request; (d) last
    assistant_usage.cache_read_tokens == 0; (e) resident tokens > capacity_hard (default
    6000).

    If NONE hold and a previous rendered view exists, return the previous view byte-
    identical without running eviction or fault-in.
    """
    try:
        store = vmem.VMemStore(home, binding.host_session_id)
        state = _load_vmem_cache_state(home, binding.host_session_id)

        # (a) Previous tool_result bytes > threshold_chars
        threshold_chars = 8000
        try:
            cpath = home / "config" / "context.toml"
            if cpath.is_file():
                cdata = tomllib.loads(cpath.read_text(encoding="utf-8"))
                threshold_chars = int(cdata.get("rtd", {}).get("threshold_chars", 8000))
        except Exception:
            pass
        env_th = os.environ.get("SECOND_BRAIN_RTD_THRESHOLD")
        if env_th and env_th.isdigit():
            threshold_chars = int(env_th)

        tool_bytes = state.get("last_tool_result_bytes", 0)
        if payload and "previous_tool_result_bytes" in payload:
            tool_bytes = payload["previous_tool_result_bytes"]
        elif payload and "tool_result_bytes" in payload:
            tool_bytes = payload["tool_result_bytes"]
        cond_a = tool_bytes > threshold_chars

        # (b) session_before_compact event occurred
        cond_b = bool(state.get("session_before_compact", False))
        if payload and payload.get("session_before_compact"):
            cond_b = True

        # (c) model/provider changed since last request
        current_provider = None
        current_model = None
        if payload:
            current_provider = payload.get("provider") or payload.get("selected_provider")
            current_model = payload.get("model") or payload.get("selected_model")
        if not current_provider:
            current_provider = binding.provider
        if not current_model:
            current_model = binding.model

        last_prov = state.get("last_provider")
        last_mod = state.get("last_model")
        cond_c = False
        if last_prov is not None and current_provider is not None and last_prov != current_provider:
            cond_c = True
        if last_mod is not None and current_model is not None and last_mod != current_model:
            cond_c = True

        # (d) last assistant_usage.cache_read_tokens == 0
        last_cache_read = state.get("last_cache_read_tokens")
        if payload and "cache_read_tokens" in payload:
            last_cache_read = payload["cache_read_tokens"]
        elif payload and "last_cache_read_tokens" in payload:
            last_cache_read = payload["last_cache_read_tokens"]
        cond_d = last_cache_read is not None and last_cache_read == 0

        # (e) resident tokens > capacity_hard (default 6000 or 1.5 * budget)
        capacity_hard = 6000
        current_resident = [
            o
            for o in store.list_objects()
            if o.residency_state in (vmem.ResidencyState.RESIDENT, vmem.ResidencyState.FAULTED_IN)
        ]
        resident_tokens = sum(o.token_estimate for o in current_resident)
        cond_e = resident_tokens > capacity_hard

        break_point = cond_a or cond_b or cond_c or cond_d or cond_e
        previous_view = state.get("previous_rendered_context")

        if not break_point and previous_view is not None:
            # Skip eviction and return byte-identical rendered context
            result = dict(previous_view)
            result["context_changed"] = False
            return result

        # Break-point triggered or initial render: perform full rendering & eviction
        rendered = store.render_hot_context(max_tokens=_VMEM_HOT_CONTEXT_BUDGET)
        lowered = task.casefold() if task else ""
        faulted_in_ids: list[str] = []
        faulted_content: list[str] = []
        if lowered:
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

        # Update cache state and reset one-shot break flags
        state["previous_rendered_context"] = rendered
        state["last_tool_result_bytes"] = 0
        state["session_before_compact"] = False
        state["last_provider"] = current_provider
        state["last_model"] = current_model
        _save_vmem_cache_state(home, binding.host_session_id, state)

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
    artifacts.add_ref(
        home,
        raw_artifact["hash"],
        owner=f"rtd:{ledger.internal_session_id(binding.host_session_id)}",
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

    recovery_line = f"Raw Artifact: {raw_artifact['handle']}\n{artifacts.recover_hint(raw_sha)}"
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
    # Store without per-tool-call eviction; retain byte count for cache-break condition (a).
    stored = store.get_object(obj.obj_id)
    state = _load_vmem_cache_state(home, binding.host_session_id)
    state["last_tool_result_bytes"] = len(raw_bytes)
    _save_vmem_cache_state(home, binding.host_session_id, state)
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
        "evicted_count": 0,
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
        "evicted_count": 0,
        "original_result_bytes": len(raw_bytes),
        "original_result_sha256": raw_sha,
        "artifact_ref": raw_sha,
        "recovery_handle": raw_artifact["handle"],
        "visible_result_bytes": visible_bytes,
        "reduction_ratio": round(reduction_ratio, 6),
    }


def _handle_session_start(home: Path, binding: HermesBinding) -> dict[str, Any]:
    _register_binding(home, binding)
    prefix = injection_slots.assemble_prefix(
        home=home,
        project_id=binding.project_id or "default",
        role=binding.bot_role,
    )
    injection_slots.record_and_check_prefix_drift(home, binding.host_session_id, prefix)
    return {
        **_response_base(binding, "session_start"),
        "status": "registered",
        "prefix": prefix,
        "prefix_sha256": hashlib.sha256(prefix.encode("utf-8")).hexdigest(),
    }


def _handle_pre_llm(home: Path, binding: HermesBinding, payload: dict[str, Any]) -> dict[str, Any]:
    _register_binding(home, binding)
    task = _first_text(payload, "task", "user_message", "prompt")
    turn_id = _first_text(payload, "turn_id", default="") or None
    provider = _first_text(payload, "provider", "selected_provider", default=binding.provider)
    model = _first_text(payload, "model", "selected_model", default=binding.model)
    with contextlib.suppress(Exception):
        _refresh_host_model_context(home, binding.host_session_id, provider, model)

    vmem_context = _vmem_context(home, binding, task, payload=payload)
    selected_routes, routing_error = _route_task(home, task) if task else ([], False)
    visibility_plan, hydrated_bodies = (
        _visibility_task(home, task, binding.host_session_id, binding.project_id)
        if task
        else (None, {})
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
        specialist_text = "\n\n".join(hydrated_bodies[k] for k in sorted(hydrated_bodies))
        visible_packet = (
            f"{visible_packet}\n\n{specialist_text}" if visible_packet else specialist_text
        )
    prefix = injection_slots.assemble_prefix(
        home=home, project_id=binding.project_id or "default", role=binding.bot_role
    )
    prefix_drift = injection_slots.record_and_check_prefix_drift(
        home, binding.host_session_id, prefix
    )
    tail = injection_slots.assemble_tail(
        delta_context=visible_packet,
        hot_context_refs=vmem_context.get("rendered_text"),
        hydrated_skills=hydrated_bodies if enforced_visible else None,
    )
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
        "prefix_sha256": hashlib.sha256(prefix.encode("utf-8")).hexdigest(),
        "prefix_drift": 1 if prefix_drift else 0,
        "turn_id": turn_id,
        "attribution": attribution,
        "selected_routes": selected_routes,
        "visibility_plan": visibility_plan,
        "routing_error": routing_error,
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
        {**event_payload, "bot_name": binding.bot_name, "bot_role": binding.bot_role},
    )
    return {
        **_response_base(binding, "pre_llm_call"),
        "status": "ok",
        "turn_id": turn_id,
        "decision": decision.decision.value,
        "reason": reason,
        "attribution": attribution,
        "prefix": prefix,
        "prefix_sha256": event_payload["prefix_sha256"],
        "prefix_drift": event_payload["prefix_drift"],
        "tail": tail,
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
    """Record host-observed invocation identity and usage, never a Brain model choice."""
    _register_binding(home, binding)
    usage = payload.get("usage")
    if isinstance(usage, dict) and type(usage.get("cache_read_tokens")) in (int, float):
        state = _load_vmem_cache_state(home, binding.host_session_id)
        state["last_cache_read_tokens"] = int(usage["cache_read_tokens"])
        _save_vmem_cache_state(home, binding.host_session_id, state)
    event = _first_text(payload, "event", default="api_request_error")
    actual_raw = payload.get("actual_identity")
    provider = (
        actual_raw.get("provider")
        if isinstance(actual_raw, dict)
        else payload.get("actual_provider", payload.get("provider", binding.provider))
    )
    model = (
        actual_raw.get("model")
        if isinstance(actual_raw, dict)
        else payload.get("actual_model", payload.get("model", binding.model))
    )
    response_model = payload.get("response_model")
    if isinstance(response_model, str) and response_model:
        model = response_model
    actual = {
        "provider": _bounded_text(provider, _ATTRIBUTION_FIELD_MAX_CHARS),
        "model": _bounded_text(model, _ATTRIBUTION_FIELD_MAX_CHARS),
    }
    observed: dict[str, Any] = {
        **_identity_fields(binding),
        "lifecycle_event": event,
        "turn_id": _bounded_text(payload.get("turn_id"), _ATTRIBUTION_FIELD_MAX_CHARS),
        "api_request_id": _bounded_text(
            payload.get("api_request_id"), _ATTRIBUTION_FIELD_MAX_CHARS
        ),
        "actual_identity": actual,
        "response_model": _bounded_text(response_model, _ATTRIBUTION_FIELD_MAX_CHARS),
        "status": _bounded_text(
            payload.get("status") or ("completed" if event == "post_api_request" else "failed"), 64
        ),
    }
    for field in ("usage", "cost", "failure_code"):
        if payload.get(field) is not None:
            observed[field] = (
                _bounded_invocation_value(payload[field])
                if field in {"usage", "cost"}
                else _bounded_text(payload[field], _ATTRIBUTION_FIELD_MAX_CHARS)
            )
    _append_event(
        home,
        binding,
        contracts.LifecycleEventType.MODEL_INVOCATION_OBSERVED,
        observed,
        key=f"{observed['api_request_id'] or observed['turn_id']}:{event}",
    )
    kind = (
        "model_invocation_completed" if event == "post_api_request" else "model_invocation_failed"
    )
    autoinject._append_telemetry(
        home,
        binding.host_session_id,
        kind,
        {**observed, "bot_name": binding.bot_name, "bot_role": binding.bot_role},
    )
    return {
        **_response_base(binding, event),
        "status": observed["status"],
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
        final_message=payload.get("final_message") or payload.get("last_assistant_message"),
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
            "error": str(exc)[:128],
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
    if event in _RETIRED_EVENTS:
        return {
            "adapter_version": ADAPTER_VERSION,
            "event": event,
            "status": "failed",
            "failure_code": "ORCHESTRATION_REMOVED",
        }
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
        if event == "session_before_compact":
            state = _load_vmem_cache_state(home_path, binding.host_session_id)
            state["session_before_compact"] = True
            _save_vmem_cache_state(home_path, binding.host_session_id, state)
            return {**_response_base(binding, "session_before_compact"), "status": "ok"}
        if event == "writeback":
            return _handle_writeback(home_path, binding, payload)
        if event == "post_api_request":
            return _handle_api_lifecycle(home_path, binding, payload)
        if event == "api_request_error":
            return _handle_api_lifecycle(home_path, binding, payload)
        if event == "handoff_create":
            return _handle_handoff_create(home_path, binding, payload)
        if event == "handoff_read":
            return _handle_handoff_read(home_path, binding, payload)
        if event == "session_end":
            return _handle_session_end(home_path, binding, payload)
        return {"adapter_version": ADAPTER_VERSION, "event": event, "status": "fail_open"}
    except contracts.HandoffError as exc:
        return {
            "adapter_version": ADAPTER_VERSION,
            "event": event,
            "status": "failed",
            "failure_code": exc.code,
            "error": str(exc),
        }
    except Exception:
        return {
            "adapter_version": ADAPTER_VERSION,
            "event": event,
            "status": "fail_open",
            "error": "BRAIN_UNAVAILABLE",
        }
