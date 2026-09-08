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


def test_model_switch_preflight_order(brain_home: Path) -> None:
    """When model changes, steps 1-8 execute in order; if load > target * 0.85, reclaim
    runs;

    if overflow, returns INPUT_REQUIRED(CONTEXT_OVERFLOW); emits MODEL_ROUTE_TRANSITION
    + decision.
    """
    session_id = "hermes:Brain-Dev:model-switch-session"
    store = vmem.VMemStore(brain_home, session_id)

    # Store objects in VMem
    for i in range(5):
        store.store_object(
            vmem.SessionObjectKind.TOOL_OBSERVATION,
            title=f"result-{i}",
            content=f"Observation content {i} " + ("w" * 800),
            summary=f"Summary {i}",
        )

    # Scenario A: Normal switch where load is within capacity
    result = hermes_adapter.model_switch_preflight(
        brain_home,
        session_id,
        target_provider="test-provider",
        target_model="test-model-large",
        current_provider="test-provider",
        current_model="test-model-small",
    )
    assert result["status"] == "ok"
    assert result["proceed"] is True
    assert result["cache_cold"] is True  # step 3: model-scoped provider marks cache cold
    assert result["target_capacity"] == 128_000  # step 1: default 128_000

    # Scenario B: Target capacity configured in config/v2.toml is tight, causing load > 0.85 * cap
    # Write config/v2.toml with small context_tokens for 'test-model-tight' (e.g. 1000 tokens)
    v2_toml = brain_home / "config" / "v2.toml"
    v2_toml.parent.mkdir(parents=True, exist_ok=True)
    v2_toml.write_text(
        """
[models.test-model-tight]
context_tokens = 1000

[providers.test-provider]
cache_scope = "model"
""",
        encoding="utf-8",
    )

    result_tight = hermes_adapter.model_switch_preflight(
        brain_home,
        session_id,
        target_provider="test-provider",
        target_model="test-model-tight",
        current_provider="test-provider",
        current_model="test-model-large",
    )
    # Step 5 must run reclaim because initial load > 1000 * 0.85 = 850
    assert result_tight["reclaimed_count"] > 0
    assert result_tight["load"] <= 1000
    # Scenario C: Context overflow when target capacity is smaller than minimal resident objects
    # Store a pinned object that cannot be evicted
    store.store_object(
        vmem.SessionObjectKind.TOOL_OBSERVATION,
        title="pinned-object",
        content="Pinned critical content " + ("p" * 200),
        pinned=True,
    )
    v2_toml.write_text(
        """
[models.test-model-overflow]
context_tokens = 10

[providers.test-provider]
cache_scope = "model"
""",
        encoding="utf-8",
    )
    result_overflow = hermes_adapter.model_switch_preflight(
        brain_home,
        session_id,
        target_provider="test-provider",
        target_model="test-model-overflow",
        current_provider="test-provider",
        current_model="test-model-tight",
    )
    assert result_overflow["status"] == "INPUT_REQUIRED"
    assert result_overflow["error"] == "CONTEXT_OVERFLOW"
    assert "INPUT_REQUIRED(CONTEXT_OVERFLOW)" in str(result_overflow.get("reason", ""))


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
