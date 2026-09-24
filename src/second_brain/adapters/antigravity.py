"""Google Antigravity lifecycle hook adapter (plan §8-§18)."""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

from .. import ledger


def run(home: Path) -> int:
    """Google Antigravity lifecycle hook adapter — official hook contract (plan §8-§18).

    Reads ONE JSON object from stdin (the official Antigravity hook payload,
    camelCase per the exa.hooks_pb protobuf JSON mapping, e.g.
    conversationId / workspacePaths / transcriptPath / artifactDirectoryPath /
    modelName, plus per-event args: preInvocationHookArgs{invocationNum,
    initialNumSteps}, postInvocationHookArgs{...}, postToolHookArgs{stepIdx,
    toolCall{name,args}, error}, stopHookArgs{executionNum, terminationReason,
    error, fullyIdle}, preToolHookArgs{...}).

    Writes ONE JSON object to stdout per the official result contracts:
      SessionStart   -> {"systemPrompt": "<PREFIX>", "injectSteps":
                         [{"ephemeralMessage": "<PREFIX>"}], "prefix": "<PREFIX>"}
                         or {} on any failure (fail-open). PREFIX (T2.4: the
                         lean kernel + T1.6 memory commands + project
                         identity line) is rendered here, once, at session
                         start; sha256(PREFIX) is recorded for later
                         prefix_drift comparison (telemetry only, never in
                         the hook response).
      PreInvocation  -> {"injectSteps":[{"ephemeralMessage": "..."}]} or {}
      PostInvocation -> {} (telemetry only)
      PostToolUse    -> {}
      Stop           -> {} (memory finalization only; Brain never decides
                         whether the host agent stops or continues)
    PreToolUse is intentionally NOT installed (no permission bypass); if one
    ever arrives, the handler returns {} without a decision.
    AutoInject visibility comes ONLY from the existing Brain mode resolution
    (SECOND_BRAIN_AUTOINJECT_* env override > config/autoinject.toml > default),
    never from a wrapper-local default. Lean runtime influence is resolved by
    the harness-neutral lean_runtime helper against the canonical skill file.

    Fail-open: any error or malformed input -> the event-appropriate safe
    empty response, exit 0.
    """
    import contextlib
    import json

    from .. import (
        antigravity_transcript,
        autoinject,
        contracts,
        injection_slots,
        lean_runtime,
    )

    # Read raw bytes and decode explicitly as UTF-8 (utf-8-sig tolerates a
    # stray leading BOM) when a binary stdin buffer is available.
    # `sys.stdin.read()` decodes through Python's locale-dependent default
    # encoding, which on this class of Windows host resolves to a legacy
    # code page (not UTF-8) absent PYTHONIOENCODING — the real
    # Antigravity/PowerShell hook transport never sets that variable, so any
    # non-ASCII byte in the JSON payload was silently mis-decoded under the
    # ambient code page. Text-mode stdin (e.g. an `io.StringIO` in tests)
    # has no `.buffer`; fall back to the plain text read for it.
    payload = None
    try:
        stdin_buffer = getattr(sys.stdin, "buffer", None)
        raw = (
            stdin_buffer.read().decode("utf-8-sig")
            if stdin_buffer is not None
            else sys.stdin.read()
        )
        payload = json.loads(raw) if raw.strip() else None
    except Exception:  # fail-open: never raise into the hook
        payload = None
    payload_dict = payload if isinstance(payload, dict) else {}

    def _get(*keys: str, default: object = None) -> object:
        for key in keys:
            if key in payload_dict:
                return payload_dict[key]
        return default

    # --- Event: prefer the args-block contract, fall back to legacy event tag ---
    args_key = None
    for candidate, ev in (
        ("sessionStartHookArgs", "SessionStart"),
        ("preInvocationHookArgs", "PreInvocation"),
        ("postInvocationHookArgs", "PostInvocation"),
        ("postToolHookArgs", "PostToolUse"),
        ("preToolHookArgs", "PreToolUse"),
        ("stopHookArgs", "Stop"),
    ):
        if isinstance(payload_dict.get(candidate), dict):
            args_key = candidate
            event = ev
            break
    else:
        event = str(_get("event", default="PreInvocation") or "PreInvocation")

    # The official CLI sends event fields FLAT at the payload root (e.g.
    # stepIdx/toolCall/error for PostToolUse); the app may send them nested
    # under the per-event args block. Merge: nested wins, root fills gaps.
    _EVENT_FIELDS = {
        "PreInvocation": ("invocationNum", "initialNumSteps"),
        "PostInvocation": ("invocationNum", "initialNumSteps"),
        "PostToolUse": ("stepIdx", "toolCall", "error"),
        "PreToolUse": ("toolCall", "stepIdx"),
        "Stop": ("executionNum", "terminationReason", "error", "fullyIdle"),
    }
    raw_hook_args = payload_dict.get(args_key) if args_key else {}
    hook_args = raw_hook_args if isinstance(raw_hook_args, dict) else {}
    for field in _EVENT_FIELDS.get(event, ()):
        if field not in hook_args and field in payload_dict:
            hook_args[field] = payload_dict[field]

    # --- Common metadata (official camelCase + snake_case fallback) ---
    conversation_id = str(
        _get("conversationId", "conversation_id", "session_id") or "antigravity-anon"
    )
    raw_workspace = _get("workspacePaths", "workspace_paths", default=[]) or []
    if isinstance(raw_workspace, str):
        raw_workspace = [raw_workspace]
    if not isinstance(raw_workspace, list):
        raw_workspace = []
    workspace_paths = [str(w) for w in raw_workspace if str(w).strip()]
    transcript_path = str(_get("transcriptPath", "transcript_path") or "")
    model_name = str(_get("modelName", "model", "agent_id") or "unknown")
    parent_conversation_id = str(_get("parentConversationId", "parent_conversation_id") or "")
    is_subagent = bool(parent_conversation_id)

    cwd = workspace_paths[0] if workspace_paths else None
    resolved_project = autoinject._resolve_project_id(home, str(cwd) if cwd else None, None)
    role = "worker" if is_subagent else "driver"

    session = contracts.BrainSessionIdentity(
        internal_session_id=ledger.internal_session_id(conversation_id),
        host="antigravity",
        host_session_id=conversation_id,
        project_id=resolved_project,
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=1,
    )

    def _log_telem(kind: str, **fields: object) -> None:
        with contextlib.suppress(Exception):
            tdir = home / "telemetry" / "agent-performance"
            tdir.mkdir(parents=True, exist_ok=True)
            rec = {
                "v": 2,
                "kind": kind,
                "session": conversation_id,
                "model": model_name,
                "project": resolved_project,
                "event": event,
                "harness": "antigravity",
                "ts": datetime.now(UTC).isoformat(),
                **fields,
            }
            with (tdir / "antigravity-hooks.jsonl").open("a", encoding="utf-8") as f:
                f.write(contracts.canonical_json(rec) + "\n")

    # ---------- SessionStart: session-constant PREFIX ----------
    if event in ("SessionStart", "session_start"):
        try:
            lean_outcome = lean_runtime.decide_lean_runtime(home, role, "SessionStart")
            lean_block = (
                lean_runtime.compose_lean_kernel_block(lean_outcome.kernel)
                if lean_outcome.decision == "inject" and lean_outcome.kernel
                else None
            )
            prefix = injection_slots.assemble_prefix(
                home=home,
                project_id=resolved_project,
                role=role,
                lean_kernel=lean_block,
            )
            prefix_drift = injection_slots.record_and_check_prefix_drift(
                home, conversation_id, prefix
            )
            _log_telem(
                "session_start",
                prefix_drift=1 if prefix_drift else 0,
                prefix_sha256=hashlib.sha256(prefix.encode("utf-8")).hexdigest(),
            )
            out = {
                "systemPrompt": prefix,
                "injectSteps": [{"ephemeralMessage": prefix}],
                "prefix": prefix,
            }
            print(contracts.canonical_json(out))
        except Exception:
            _log_telem("session_start_fail_open")
            print("{}")
        return 0

    # ---------- Stop: memory finalization only; no lifecycle decision ----------
    if event == "Stop":
        termination_reason = str(hook_args.get("terminationReason") or "") or ""
        error = str(hook_args.get("error") or "") or ""
        try:
            autoinject.BrainLifecycle(home, session).finalize_session(
                tool_call_args=hook_args.get("tool_call_args")
                or hook_args.get("tool_calls")
                or antigravity_transcript.extract_tool_call_args(transcript_path),
                final_message=hook_args.get("last_assistant_message")
                or payload_dict.get("last_assistant_message"),
            )
        except Exception:
            _log_telem("stop_finalization_error")
        else:
            _log_telem(
                "stop_finalized",
                termination_reason=termination_reason,
                fully_idle=bool(hook_args.get("fullyIdle", False)),
                error=error[:120] if error else None,
            )
        print("{}")
        return 0

    # ---------- PostInvocation: telemetry only ----------
    if event == "PostInvocation":
        _log_telem("turn_end", invocation_num=hook_args.get("invocationNum"))
        print("{}")
        return 0

    # ---------- PostToolUse: nested toolCall telemetry; {} output ----------
    if event == "PostToolUse":
        raw_tool_call = hook_args.get("toolCall")
        tool_call = raw_tool_call if isinstance(raw_tool_call, dict) else {}
        tool_name = str(tool_call.get("name") or "unknown")
        step_idx = hook_args.get("stepIdx")
        tool_error = str(hook_args.get("error") or "") or None
        _log_telem(
            "tool_result",
            tool=tool_name,
            step_idx=step_idx,
            success=not tool_error,
            error=tool_error[:120] if tool_error else None,
        )
        print("{}")
        return 0

    # ---------- PreToolUse: never a blanket allow (no permission bypass) ----------
    if event == "PreToolUse":
        raw_tool_call = hook_args.get("toolCall")
        tool_call = raw_tool_call if isinstance(raw_tool_call, dict) else {}
        _log_telem("pretooluse_seen", tool=str(tool_call.get("name") or "unknown"))
        print("{}")
        return 0

    # ---------- PreInvocation: bounded context + canonical Lean kernel ----------
    # Actual task: prefer the real transcript (bounded tail), fall back to
    # legacy flat fields for backwards compatibility with internal tools/tests.
    task = None
    if transcript_path:
        task = antigravity_transcript.extract_latest_user_task(transcript_path)
    if not (isinstance(task, str) and task.strip()):
        task = (
            payload_dict.get("task")
            or payload_dict.get("prompt")
            or payload_dict.get("user_message")
        )
    if not (isinstance(task, str) and task.strip()):
        # Distinguish unavailable task context from unavailable Brain.
        _log_telem("preinvocation_no_task", transcript_path=transcript_path or None)
        print("{}")
        return 0

    try:
        lifecycle = autoinject.BrainLifecycle(home, session)
        invocation_num = int(hook_args.get("invocationNum") or 1)
        is_delta = invocation_num > 1
        decision = lifecycle.prepare_injection(
            task,
            project_id=resolved_project,
            agent_id=model_name,
            role_profile=role,
            session_id=conversation_id,
            branch_id="main",
            cwd=str(cwd) if cwd else None,
            is_delta=is_delta,
        )
        packet = autoinject.render_packet(decision)
        delivery_id = lifecycle.last_delivery_ids[0] if lifecycle.last_delivery_ids else None
        mode = autoinject.resolve_autoinject_mode(home).strip().lower()

        # Lean runtime influence (canonical skill file, harness-neutral).
        lean_base = packet if packet else task
        lean_outcome = lean_runtime.decide_lean_runtime(home, role, lean_base)
        lean_block = (
            lean_runtime.compose_lean_kernel_block(lean_outcome.kernel)
            if lean_outcome.decision == "inject" and lean_outcome.kernel
            else None
        )

        prefix = injection_slots.assemble_prefix(
            home=home,
            project_id=resolved_project,
            role=role,
            lean_kernel=lean_block,
            task=task,
        )
        prefix_drift = injection_slots.record_and_check_prefix_drift(home, conversation_id, prefix)
        tail = injection_slots.assemble_tail(delta_context=packet)

        # Compose the model-visible ephemeral message. PREFIX (lean kernel +
        # T1.6 commands + project line) is bounded/always-non-empty by
        # construction, so it must never be sent bare -- only alongside real
        # substance: the lean kernel itself (lean_block truthy, matching the
        # pre-T2.4 gate exactly) or a non-empty TAIL (the AutoInject
        # packet). An irrelevant task with no packet and no lean kernel
        # still yields NO ephemeral message, same as before T2.4.
        ephemeral = None
        if mode in ("active", "advisory"):
            if lean_block and tail:
                ephemeral = prefix + "\n\n" + tail
            elif lean_block:
                ephemeral = prefix
            elif tail:
                ephemeral = tail
        _log_telem(
            "preinvocation",
            decision=decision.decision.value,
            packet_tokens=decision.packet_token_size,
            delivery_id=delivery_id,
            candidate_count=len(decision.candidate_ids),
            selected_count=len(decision.selected_ids),
            lean_decision=lean_outcome.decision,
            lean_reason=lean_outcome.reason,
            lean_mode=lean_outcome.mode,
            lean_eval_source=lean_outcome.eval_source,
            lean_kernel_chars=lean_outcome.kernel_chars,
            lean_dedup_hit=lean_outcome.dedup_hit,
            autoinject_mode=mode,
            model_visible=bool(ephemeral),
            is_delta=is_delta,
            prefix_drift=1 if prefix_drift else 0,
            prefix_sha256=hashlib.sha256(prefix.encode("utf-8")).hexdigest(),
        )

        if ephemeral is None:
            print("{}")
        else:
            out = {"injectSteps": [{"ephemeralMessage": ephemeral}]}
            print(contracts.canonical_json(out))
        return 0
    except Exception:
        _log_telem("preinvocation_fail_open", decision="NO_INJECTION", reason="BRAIN_UNAVAILABLE")
        print("{}")
        return 0
