"""Tests for cache-break points and model-switch preflight (T2.3).

Core rule:
Paging/eviction runs ONLY when at least one of the 5 cache-break conditions holds:
(a) previous tool_result bytes exceed the configured RTD threshold;
(b) session_before_compact event occurred;
(c) model/provider changed since last request;
(d) last assistant_usage.cache_read_tokens == 0;
(e) resident tokens > capacity_hard (default 6000 or 1.5 * budget).

If NONE hold, return the previous rendered context view unchanged (byte-identical).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from second_brain import hermes_adapter, vmem


def _start_payload(session: str = "cache-break-session", bot: str = "Brain-Dev") -> dict[str, Any]:
    return {
        "event": "session_start",
        "hermes_session_id": session,
        "bot_name": bot,
        "bot_role": "dev",
        "project_id": "proj-test",
        "repo_root": str(Path(__file__).resolve().parent.parent),
        "provider": "test-provider",
        "model": "test-model",
    }


def test_paging_skipped_when_no_break_point(brain_home: Path) -> None:
    """When none of (a)-(e) hold, _vmem_context returns byte-identical output to
    previous call without running eviction."""
    payload = _start_payload(session="session-skip-break")
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    store = vmem.VMemStore(brain_home, binding.host_session_id)

    # Store resident objects within budget (e.g. 2 objects of 200 tokens each)
    store.store_object(
        vmem.SessionObjectKind.TOOL_OBSERVATION,
        title="tool-1 result",
        content="Alpha observation content " + ("x" * 100),
        summary="Alpha summary",
    )
    store.store_object(
        vmem.SessionObjectKind.TOOL_OBSERVATION,
        title="tool-2 result",
        content="Beta observation content " + ("y" * 100),
        summary="Beta summary",
    )

    # Initial render (first turn)
    first_context = hermes_adapter._vmem_context(brain_home, binding, task="investigate alpha")
    first_rendered_text = first_context.get("rendered_text", "")
    assert len(first_rendered_text) > 0

    # Ensure break conditions are all false:
    # (a) small previous tool result (e.g. 50 bytes < 8000 threshold)
    # (b) no session_before_compact
    # (c) same provider/model
    # (d) cache was warm (cache_read_tokens > 0)
    # (e) resident tokens < capacity_hard (6000)
    post_payload = payload | {
        "event": "post_tool_call",
        "tool_name": "bash",
        "result": "short output",
        "tool_call_id": "call-small",
    }
    hermes_adapter.handle_request(brain_home, post_payload)

    # An object match alone must not bypass the cache-break gate.
    second_context = hermes_adapter._vmem_context(brain_home, binding, task="investigate alpha")

    assert second_context.get("rendered_text") == first_rendered_text
    assert second_context.get("context_changed") is False


def test_host_model_change_rebounds_brain_context_without_blocking_request(
    brain_home: Path,
) -> None:
    payload = _start_payload(session="host-model-change")
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    store = vmem.VMemStore(brain_home, binding.host_session_id)
    obj = store.store_object(
        vmem.SessionObjectKind.TOOL_OBSERVATION,
        title="recoverable context",
        content="evidence " * 200,
        summary="recoverable summary",
        pinned=True,
    )
    first = hermes_adapter.handle_request(
        brain_home,
        payload
        | {
            "event": "pre_llm_call",
            "task": "read recoverable context",
            "turn_id": "first",
        },
    )
    assert first["status"] == "ok"
    (brain_home / "config" / "v2.toml").write_text(
        "[models.tiny]\ncontext_tokens = 10\n[providers.test-provider]\ncache_scope = 'model'\n",
        encoding="utf-8",
    )
    changed = hermes_adapter.handle_request(
        brain_home,
        payload
        | {
            "event": "pre_llm_call",
            "task": "read recoverable context",
            "turn_id": "second",
            "model": "tiny",
        },
    )
    assert changed["status"] == "ok"
    assert "model_decision" not in changed
    state = hermes_adapter._load_vmem_cache_state(brain_home, binding.host_session_id)
    assert state["last_model"] == "tiny"
    assert store.get_object(obj.obj_id) is not None


def test_hard_capacity_forces_eviction_ignoring_net(brain_home: Path) -> None:
    """When resident tokens > capacity_hard, eviction runs immediately even if all
    candidates have net <= 0 and previous tool result was small."""
    payload = _start_payload(session="session-hard-capacity")
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    store = vmem.VMemStore(brain_home, binding.host_session_id)

    # Store objects exceeding capacity_hard (6000 tokens, e.g. 7 objects of 1000 tokens each)
    for i in range(8):
        store.store_object(
            vmem.SessionObjectKind.TOOL_OBSERVATION,
            title=f"heavy-object-{i}",
            content=f"Heavy content {i} " + ("h" * 4000),  # ~1000 tokens
            summary="",
        )

    resident_before = [
        o
        for o in store.list_objects()
        if o.residency_state in (vmem.ResidencyState.RESIDENT, vmem.ResidencyState.FAULTED_IN)
    ]
    tokens_before = sum(o.token_estimate for o in resident_before)
    assert tokens_before > 6000  # exceeds capacity_hard

    # Set small tool result (condition a is False), same model (c False), no compact (b False)
    post_payload = payload | {
        "event": "post_tool_call",
        "tool_name": "bash",
        "result": "small",
        "tool_call_id": "call-small-hard",
    }
    hermes_adapter.handle_request(brain_home, post_payload)

    # Render context - condition (e) must force eviction even if candidates have net <= 0
    ctx = hermes_adapter._vmem_context(brain_home, binding, task="check heavy status")
    assert ctx.get("evicted_count", 0) > 0

    resident_after = [
        o
        for o in store.list_objects()
        if o.residency_state in (vmem.ResidencyState.RESIDENT, vmem.ResidencyState.FAULTED_IN)
    ]
    tokens_after = sum(o.token_estimate for o in resident_after)
    assert tokens_after < tokens_before


def test_same_native_session_id_cannot_reuse_another_home_context(
    brain_home: Path, tmp_path: Path, monkeypatch
) -> None:
    from conftest import make_brain

    other_home = make_brain(tmp_path / "other-brain", monkeypatch)
    payload = _start_payload(session="shared-host-session")
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    vmem.VMemStore(brain_home, binding.host_session_id).store_object(
        vmem.SessionObjectKind.TOOL_OBSERVATION,
        title="A-only secret",
        content="A-only secret content",
        summary="A-only secret",
    )
    first = hermes_adapter.handle_request(
        brain_home, payload | {"event": "pre_llm_call", "task": "recall", "turn_id": "a"}
    )
    assert first["status"] == "ok"
    assert "A-only secret" in first["vmem_context"]["rendered_text"]
    second = hermes_adapter.handle_request(
        other_home, payload | {"event": "pre_llm_call", "task": "recall", "turn_id": "b"}
    )
    assert second["status"] == "ok"
    assert "A-only secret" not in second["vmem_context"]["rendered_text"]
