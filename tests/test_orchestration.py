from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from second_brain import contracts, hermes_adapter, ledger


def _identity(role: str = "integrator") -> contracts.AgentIdentity:
    return contracts.AgentIdentity(
        agent_id="agent-1", internal_session_id="session-1", host_agent_id="Brain-Integrator",
        parent_agent_id=None, role_profile=role, model="test-model", provider="test-provider",
        created_at="2026-08-22T00:00:00Z",
    )


def _packet(role: str = "integrator") -> contracts.WorkerTaskPacket:
    return contracts.WorkerTaskPacket(
        task_id="task-1", parent_session_id="parent-1", driver_identity=_identity(role),
        requested_role="dev", objective="Inspect the bounded seam", scope="src only",
        completion_condition="return evidence refs", project_id="second-brain", repo_root="repo",
    )


def test_worker_packets_are_canonical_bounded_and_role_checked() -> None:
    packet = _packet().validate()
    assert packet.canonical_json() == contracts.canonical_json(packet)
    assert len(packet.canonical_json().encode()) <= contracts.WORKER_PACKET_MAX_BYTES
    with pytest.raises(contracts.WorkerPacketError, match="UNAUTHORIZED_COORDINATOR"):
        _packet("dev").validate()
    with pytest.raises(contracts.WorkerPacketError, match="DEPTH_EXCEEDED"):
        (_packet().__class__(**{**packet.__dict__, "depth": 2})).validate()


def test_worker_result_requires_explicit_failure_and_is_bounded() -> None:
    with pytest.raises(contracts.WorkerPacketError, match="MALFORMED_FAILURE"):
        contracts.WorkerResultPacket("task-1", _identity("dev"), "failed").validate()
    result = contracts.WorkerResultPacket(
        "task-1", _identity("dev"), "completed", summary="done", evidence_refs=["test:1"]
    ).validate()
    assert json.loads(result.canonical_json())["status"] == "completed"


def test_missing_worker_is_explicit_and_correlated(brain_home: Path) -> None:
    binding = hermes_adapter.resolve_binding(brain_home, {
        "bot_name": "Brain-Integrator", "bot_role": "integrator", "hermes_session_id": "s1",
        "project_id": "second-brain", "repo_root": str(Path.cwd()),
    })
    response = hermes_adapter.request_worker_task(
        brain_home, binding, json.loads(_packet().canonical_json())
    )
    assert response["status"] == "failed"
    assert response["failure_code"] == "WORKER_UNAVAILABLE"
    with sqlite3.connect(ledger.LedgerStore(brain_home, binding.host_session_id).dbfile) as conn:
        kinds = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert "worker_started" in kinds
    assert "worker_failed" in kinds
    assert "result_returned" in kinds
    assert "task-1" in response["task_id"]
