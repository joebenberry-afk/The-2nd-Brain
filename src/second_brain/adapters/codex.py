"""Codex hook adapter (SHADOW, Phase 0C; plan §6.10)."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .. import ledger


def run(home: Path) -> int:
    """Codex hook adapter (SHADOW, Phase 0C; plan §6.10).

    Reads ONE JSON object from stdin {session_id, project, task, agent_id,
    branch, role, source}; writes ONE JSON object to stdout. Task text NEVER
    passes through argv (STOP §23 #6) — stdin only. Fail-open: malformed or
    missing input -> NO_INJECTION(BRAIN_UNAVAILABLE), exit 0.
    """
    import json

    from .. import autoinject, contracts, injection_slots

    payload = None
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except Exception:  # fail-open: never raise into the hook
        payload = None
    payload_dict = payload if isinstance(payload, dict) else {}
    task = None
    if isinstance(payload, dict):
        task = payload.get("task") or payload.get("prompt")
        if not (isinstance(task, str) and task.strip()):
            task = None
    if task is None:
        # Stop/SessionEnd carry no prompt: record the finalization trigger
        # only (plan §3.1 — no model-based extraction inside the short hook).
        if str(payload_dict.get("source") or "") in ("Stop", "SessionEnd"):
            try:
                session = contracts.BrainSessionIdentity(
                    internal_session_id=ledger.internal_session_id(
                        str(payload_dict.get("session_id") or "codex-anon")
                    ),
                    host="codex-hooks",
                    host_session_id=str(payload_dict.get("session_id") or "codex-anon"),
                    project_id=autoinject._resolve_project_id(
                        home, payload_dict.get("cwd"), payload_dict.get("project")
                    ),
                    created_at=datetime.now(UTC).isoformat(),
                    status="active",
                    pinned=False,
                    schema_version=1,
                )
                autoinject.BrainLifecycle(home, session).finalize_session(
                    tool_call_args=payload_dict.get("tool_call_args")
                    or payload_dict.get("tool_calls"),
                    final_message=payload_dict.get("last_assistant_message"),
                )
            except Exception:  # fail-open: never break the hook
                pass
        bad = contracts.BrainInjectionDecision(
            decision=contracts.InjectionDecision.NO_INJECTION,
            reason=contracts.NoInjectionReason.BRAIN_UNAVAILABLE,
            candidate_ids=[],
            selected_ids=[],
            packet_ref=None,
            packet_token_size=None,
            recipient="codex",
        )
        print(contracts.canonical_json(autoinject.shadow_output(bad, None, None)))
        return 0
    payload_dict = payload if isinstance(payload, dict) else {}
    session_id = str(payload_dict.get("session_id") or "codex-anon")
    project_id = autoinject._resolve_project_id(
        home, payload_dict.get("cwd"), payload_dict.get("project")
    )
    agent_id = str(payload_dict.get("agent_id") or payload_dict.get("model") or "codex")
    branch = str(payload_dict.get("branch") or "main")
    role = str(payload_dict.get("role") or "worker")
    session = contracts.BrainSessionIdentity(
        internal_session_id=ledger.internal_session_id(session_id),
        host="codex-hooks",
        host_session_id=session_id,
        project_id=project_id,
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=1,
    )
    lifecycle = autoinject.BrainLifecycle(home, session)
    decision = lifecycle.prepare_injection(
        task,
        project_id=project_id,
        agent_id=agent_id,
        role_profile=role,
        session_id=session_id,
        branch_id=branch,
        cwd=str(payload_dict.get("cwd")) if payload_dict.get("cwd") else None,
    )
    packet = autoinject.render_packet(decision)
    delivery_id = lifecycle.last_delivery_ids[0] if lifecycle.last_delivery_ids else None
    source = str(payload_dict.get("source") or "")
    is_start = source in ("SessionStart", "session_start") or not bool(
        payload_dict.get("is_delta") or payload_dict.get("turn_index", 0) > 0
    )
    prefix = injection_slots.assemble_prefix(
        home=home,
        project_id=project_id,
        role=role,
        task=task,
    )
    prefix_drift = injection_slots.record_and_check_prefix_drift(
        home, session_id, prefix
    )
    tail = injection_slots.assemble_tail(delta_context=packet)
    mode = os.environ.get("SECOND_BRAIN_AUTOINJECT_MODE", "shadow").strip().lower()
    if mode in ("advisory", "active"):
        if source in ("SessionStart", "session_start"):
            print(contracts.canonical_json({"additionalContext": prefix, "prefix": prefix}))
        elif is_start:
            ctx_text = f"{prefix}\n\n{tail}" if (prefix and tail) else (tail or prefix)
            print(contracts.canonical_json({"additionalContext": ctx_text}))
        else:
            if tail:
                print(contracts.canonical_json({"additionalContext": tail}))
            else:
                print("{}")
    else:
        # SHADOW: deterministic output contract is unchanged by T2.4 --
        # assemble_prefix/record_and_check_prefix_drift above still run (so
        # drift telemetry is recorded every turn), but the JSON shape stays
        # exactly the pre-T2.4 {decision, reason, packet, packet_tokens,
        # candidate_ids, selected_ids, delivery_id} contract.
        print(contracts.canonical_json(autoinject.shadow_output(decision, packet, delivery_id)))
    return 0
