"""Focused T7.7 Universal harness control-plane completion tests."""

from __future__ import annotations

import json
from pathlib import Path

from second_brain import capabilities, contracts, worker_protocol
from second_brain.contracts import AgentIdentity, WorkerResultPacket, WorkerTaskPacket


def _identity(role: str, *, session: str, bot: str) -> AgentIdentity:
    return AgentIdentity(
        agent_id=f"universal:{bot}",
        internal_session_id=session,
        host_agent_id=bot,
        parent_agent_id=None,
        role_profile=role,
        model="test-model",
        provider="test-provider",
        created_at="2026-08-23T00:00:00Z",
    )


def test_worker_packet_roundtrip_across_adapters() -> None:
    """Canonical worker packets roundtrip losslessly across adapter wire formats."""
    driver = _identity("integrator", session="session-root-001", bot="coordinator-main")
    task_packet = WorkerTaskPacket(
        task_id="task-canonical-001",
        parent_session_id="session-root-001",
        driver_identity=driver,
        requested_role="worker",
        objective="Run independent test validation",
        scope="src/second_brain/",
        constraints=["no_external_network", "read_only_fs"],
        evidence_requirements=["test_exit_0", "diff_clean"],
        completion_condition="pytest passes with 100% exit code 0",
        context_refs=["ref:doc-01", "ref:doc-02"],
        project_id="second-brain",
        repo_root=".",
    )
    task_packet.validate()

    # 1. Roundtrip through Prime adapter JSON wire format
    prime_wire_json = task_packet.canonical_json()
    prime_parsed = WorkerTaskPacket.from_dict(json.loads(prime_wire_json))
    assert prime_parsed.task_id == task_packet.task_id
    assert prime_parsed.objective == task_packet.objective
    assert prime_parsed.constraints == task_packet.constraints
    assert prime_parsed.canonical_hash() == task_packet.canonical_hash()

    # 2. Roundtrip through Claude Code hook payload format
    claude_code_event = {
        "session_id": "claude-session-999",
        "hook_event_name": "TaskStart",
        "task_packet": json.loads(prime_wire_json),
    }
    claude_parsed = WorkerTaskPacket.from_dict(claude_code_event["task_packet"])
    assert claude_parsed.canonical_hash() == task_packet.canonical_hash()

    # 3. Roundtrip through Hermes packet format
    hermes_message = {
        "from": "hermes-agent-1",
        "to": "worker-subagent",
        "packet": json.loads(prime_wire_json),
    }
    hermes_parsed = WorkerTaskPacket.from_dict(hermes_message["packet"])
    assert hermes_parsed.canonical_hash() == task_packet.canonical_hash()

    # 4. Result packet roundtrip
    worker_id = _identity("worker", session="session-root-001", bot="worker-sub-1")
    result_packet = WorkerResultPacket(
        task_id="task-canonical-001",
        worker_identity=worker_id,
        status="completed",
        summary="Validation completed successfully.",
        evidence_refs=["telemetry:eval-001"],
        files_changed=[],
        artifacts=["artifact:report-001"],
        tests_run=["tests/test_core.py"],
    )
    result_packet.validate()

    result_json = contracts.canonical_json(result_packet)
    result_roundtrip = WorkerResultPacket.from_dict(json.loads(result_json))
    assert result_roundtrip.task_id == result_packet.task_id
    assert result_roundtrip.status == "completed"
    assert result_roundtrip.summary == result_packet.summary
    assert result_roundtrip.artifacts == ["artifact:report-001"]


def test_missing_capability_degrades_not_fakes_support(brain_home: Path) -> None:
    """Missing capabilities degrade to conservative T0 floor; support is never faked or inferred."""
    unobserved_harness = "minimal-test-harness"

    # Current capabilities for an unobserved harness
    caps = capabilities.list_capabilities(brain_home, unobserved_harness)
    assert all(c["supported"] is None for c in caps.values())

    # Tier degrades to T0 floor
    tier = capabilities.harness_tier(brain_home, unobserved_harness)
    assert tier == "T0"

    # Behavior degrades to injection-only
    behavior = capabilities.tier_behavior(brain_home, unobserved_harness)
    assert "prompt-injection visibility" in behavior

    # Explicitly declare one unsupported capability
    capabilities.declare(brain_home, unobserved_harness, "subagents", False)
    caps_after = capabilities.list_capabilities(brain_home, unobserved_harness)
    assert caps_after["subagents"]["supported"] is False
    # Never faked as True
    assert capabilities.harness_tier(brain_home, unobserved_harness) == "T0"


def test_host_identity_not_canonical_state(brain_home: Path) -> None:
    """Host-specific session identifiers are adapter translations only; canonical state remains shared."""
    task_id = "task-cross-adapter-001"
    task_hash = "a" * 64
    driver_sess = "canonical-driver-sess"

    # 1. Register task with driver session in shared protocol
    task_record = worker_protocol.register_task(
        brain_home,
        task_id=task_id,
        packet_sha256=task_hash,
        session_id=driver_sess,
    )
    assert task_record["task_id"] == task_id
    assert task_record["state"] == "SUBMITTED"

    # 2. Worker executes under host-specific adapter ID (e.g. prime-child-uuid)
    worker_res = worker_protocol.record_worker_event(
        brain_home,
        task_id,
        task_hash,
        "accepted",
        session_id="prime-child-uuid-1234",
    )
    assert worker_res["state"] == "WORKING"

    # 3. Task owner session remains immutable driver session
    owner = worker_protocol.task_owner_session(brain_home, task_id, task_hash)
    assert owner == driver_sess

    # 4. Canonical state in worker_tasks remains unified and authoritative
    lookup = worker_protocol.lookup_task(brain_home, task_id, task_hash)
    assert lookup is not None
    assert lookup["task_id"] == task_id
    assert lookup["state"] == "WORKING"
    # Host session IDs did not fragment or partition the single canonical state
