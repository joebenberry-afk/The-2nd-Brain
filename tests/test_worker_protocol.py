from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from second_brain import artifacts, contracts, hermes_adapter, semantic, worker_protocol

REPO_ROOT = Path(__file__).resolve().parent.parent


def _identity(role: str, *, session: str, bot: str) -> contracts.AgentIdentity:
    return contracts.AgentIdentity(
        agent_id=f"hermes:{bot}",
        internal_session_id=session,
        host_agent_id=bot,
        parent_agent_id=None,
        role_profile=role,
        model="test-model",
        provider="test-provider",
        created_at="2026-08-23T00:00:00Z",
    )


def _packet(
    home: Path, ref: str, session: str = "hermes:Brain-Integrator:p12-test"
) -> contracts.WorkerTaskPacket:
    return contracts.WorkerTaskPacket(
        task_id="p12-correction-test",
        parent_session_id=session,
        driver_identity=_identity("integrator", session="driver-brain", bot="Brain-Integrator"),
        requested_role="dev",
        objective="Inspect the bounded communication seam",
        scope="src and tests only",
        constraints=["read-only"],
        evidence_requirements=["return canonical evidence"],
        completion_condition="return a concise result",
        context_refs=[ref],
        project_id="second-brain",
        repo_root=str(REPO_ROOT),
        access_intent="read_only",
    ).validate()


def test_terminal_receipt_rejects_payload_that_does_not_match_its_hash(brain_home) -> None:
    task, digest = "authenticated-receipt", "b" * 64
    worker_protocol.register_task(brain_home, task, digest, session_id="driver")
    worker_protocol.record_worker_event(brain_home, task, digest, "accepted")
    result = contracts.WorkerResultPacket(
        task,
        _identity("worker", session="worker-session", bot="worker"),
        "completed",
        summary="verified outcome",
    ).validate()
    payload = {**json.loads(result.canonical_json()), "result_sha256": result.canonical_hash()}
    with pytest.raises(contracts.WorkerPacketError, match="PROTOCOL_ERROR"):
        worker_protocol.record_worker_event(
            brain_home, task, digest, "completed", payload={**payload, "summary": "altered outcome"}
        )
    task_state = worker_protocol.lookup_task(brain_home, task, digest)
    assert task_state is not None
    assert task_state["state"] == "WORKING"
    worker_protocol.record_worker_event(brain_home, task, digest, "completed", payload=payload)
    assert worker_protocol.verify_result_binding(
        brain_home, task, digest, result.canonical_hash()
    ) is None


def test_context_refs_resolve_memory_and_artifact_with_bounded_metadata(brain_home: Path) -> None:
    memory_id = semantic.add_memory(
        brain_home,
        "P12 context fixture",
        "Canonical memory body for worker context resolution.",
        project_id="second-brain",
        grade="TESTED",
    )
    semantic.curate(brain_home, memory_id, status="current")
    artifact = artifacts.store_text(
        brain_home, "Canonical artifact body for worker context resolution.", "test-log"
    )
    packet = _packet(brain_home, f"memory:{memory_id}")
    packet = contracts.WorkerTaskPacket(
        **{
            **packet.__dict__,
            "context_refs": [f"memory:{memory_id}", f"artifact:{artifact['hash']}"],
        }
    ).validate()

    resolved = worker_protocol.resolve_context_refs(brain_home, packet)
    metadata = worker_protocol.context_metadata(resolved)

    assert [item.kind for item in resolved] == ["memory", "artifact"]
    assert "Canonical memory body" in resolved[0].content
    assert "Canonical artifact body" in resolved[1].content
    assert metadata["resolved_count"] == 2
    assert metadata["resolution_sha256"]
    assert all("content" not in item for item in metadata["refs"])
    assert sum(len(item.content) for item in resolved) <= contracts.WORKER_CONTEXT_MAX_TOTAL_CHARS

    with pytest.raises(contracts.WorkerPacketError, match="CONTEXT_REF_UNRESOLVED"):
        worker_protocol.resolve_context_refs(
            brain_home,
            contracts.WorkerTaskPacket(
                **{**packet.__dict__, "context_refs": ["unsupported:ref"]}
            ).validate(),
        )


def test_context_handoff_reuses_unchanged_and_emits_changed_delta(brain_home: Path) -> None:
    memory_id = semantic.add_memory(
        brain_home,
        "P13 handoff fixture",
        "Initial stable worker context.",
        project_id="second-brain",
        grade="TESTED",
    )
    semantic.curate(brain_home, memory_id, status="current")
    packet = _packet(brain_home, f"brain://{memory_id}")
    binding = hermes_adapter.resolve_binding(
        brain_home,
        {
            "bot_name": "Brain-Integrator",
            "bot_role": "integrator",
            "hermes_session_id": "p13-handoff",
            "project_id": "second-brain",
            "repo_root": str(REPO_ROOT),
        },
    )
    initial = contracts.WorkerResultPacket(
        task_id=packet.task_id,
        worker_identity=_identity("dev", session="worker-brain", bot="Brain-Dev"),
        status="completed",
        summary="initial",
    ).validate()

    first = worker_protocol.prepare_context_handoff(brain_home, packet, host="test")
    assert first["mode"] == "full"
    assert first["reused"] is False
    assert len(first["resolved_context"]) == 1
    full_response = hermes_adapter.request_worker_task(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        first,
    )
    assert full_response["context_metadata"]["mode"] == "full"
    assert len(full_response["context_handoff"]["resolved_context"]) == 1
    forged = json.loads(json.dumps(first))
    forged["resolved_context"][0]["content"] = "forged context"
    forged["context_handoff_bytes"] = len(
        contracts.canonical_json(
            {
                "mode": forged["mode"],
                "resolved_context": forged["resolved_context"],
                "context_delta": forged["context_delta"],
                "context_fingerprint": forged["context_fingerprint"],
                "jit_context": forged["jit_context"],
            }
        ).encode("utf-8")
    )
    with pytest.raises(contracts.WorkerPacketError, match="CONTEXT_HANDOFF_MISMATCH"):
        worker_protocol.validate_context_handoff(brain_home, packet, forged)

    unchanged = worker_protocol.prepare_context_handoff(brain_home, packet, host="test")
    assert unchanged["mode"] == "unchanged"
    assert unchanged["reused"] is True
    assert unchanged["cache_hit"] is True
    assert unchanged["resolved_context"] == []
    assert unchanged["context_delta"]["changed_refs"] == []
    assert unchanged["context_delta"]["jit_delta"] == ""
    assert unchanged["context_handoff_bytes"] < first["context_handoff_bytes"]
    unchanged_response = hermes_adapter.request_worker_task(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        unchanged,
    )
    assert unchanged_response["status"] == "completed"
    assert unchanged_response["terminal_noop"] is True
    assert "context_metadata" not in unchanged_response

    semantic.supersede(
        brain_home,
        memory_id,
        new_body="Changed worker context with one bounded delta.",
        change_note="P13 delta fixture",
    )
    changed = worker_protocol.prepare_context_handoff(brain_home, packet, host="test")
    assert changed["mode"] == "delta"
    assert changed["reused"] is False
    assert changed["cache_hit"] is False
    assert changed["resolved_context"] == []
    assert len(changed["context_delta"]["changed_refs"]) == 1
    assert "Changed worker context" in changed["context_delta"]["changed_refs"][0]["content"]
    assert changed["context_delta_bytes"] <= 16_384
    assert changed["context_delta_tokens_estimate"] > 0
    changed_response = hermes_adapter.request_worker_task(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        changed,
    )
    assert changed_response["status"] == "completed"
    assert changed_response["terminal_noop"] is True
    assert "context_handoff" not in changed_response

    ledger_path = hermes_adapter.ledger.LedgerStore(
        brain_home, binding.host_session_id
    ).dbfile
    with sqlite3.connect(ledger_path) as conn:
        payloads = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT payload_json FROM events WHERE event_type = 'task_context_resolved'"
            )
        ]
    assert {payload["context_mode"] for payload in payloads} == {"full"}
    assert all('"content":' not in json.dumps(payload) for payload in payloads)
    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    telemetry_payloads = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("kind") == "hermes_worker_context_resolved"
    ]
    assert {payload["context_mode"] for payload in telemetry_payloads} == {"full"}


def test_result_hash_and_correction_lifecycle_are_canonical(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_id = semantic.add_memory(
        brain_home,
        "P12 lifecycle fixture",
        "A canonical memory reference for the correction lifecycle.",
        project_id="second-brain",
        grade="TESTED",
    )
    semantic.curate(brain_home, memory_id, status="current")
    packet = _packet(brain_home, f"brain://{memory_id}")
    binding = hermes_adapter.resolve_binding(
        brain_home,
        {
            "bot_name": "Brain-Integrator",
            "bot_role": "integrator",
            "hermes_session_id": "p12-test",
            "project_id": "second-brain",
            "repo_root": str(REPO_ROOT),
        },
    )
    bad_packet = contracts.WorkerTaskPacket(
        **{**packet.__dict__, "task_id": "p12-role-mismatch"}
    ).validate()
    bad_result = contracts.WorkerResultPacket(
        task_id=bad_packet.task_id,
        worker_identity=_identity("integrator", session="wrong-worker", bot="Brain-Integrator"),
        status="completed",
    )
    bad_response = hermes_adapter.request_worker_task(
        brain_home,
        binding,
        json.loads(bad_packet.canonical_json()),
        json.loads(bad_result.canonical_json()),
    )
    assert bad_response["status"] == "failed"
    assert bad_response["failure_code"] == "UNAUTHORIZED_WORKER"
    initial = contracts.WorkerResultPacket(
        task_id=packet.task_id,
        worker_identity=_identity(
            "dev", session="worker-brain", bot="Brain-Dev"
        ),
        status="completed",
        summary="Initial bounded evidence.",
        evidence_refs=["memory:" + memory_id],
    ).validate()
    initial_hash = initial.canonical_hash()
    assert initial_hash == contracts.stable_content_hash(initial)
    assert (
        contracts.WorkerResultPacket.from_dict(json.loads(initial.canonical_json())).canonical_hash()
        == initial_hash
    )

    first = hermes_adapter.request_worker_task(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
    )
    assert first["status"] == "completed"
    assert first["result_sha256"] == initial_hash
    assert first["context_metadata"]["resolved_count"] == 1

    def unexpected(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("terminal duplicate resolved context")

    monkeypatch.setattr(
        hermes_adapter.worker_protocol, "validate_context_handoff", unexpected
    )
    duplicate = hermes_adapter.request_worker_task(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        context_handoff_data=first["context_handoff"],
    )
    assert duplicate["status"] == "completed"
    assert duplicate["terminal_noop"] is True
    assert "context_handoff" not in duplicate

    correction_request = hermes_adapter.request_worker_correction(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        "Add the resolved Brain reference and explicit test evidence.",
        requested_changes=["include the Brain context ref", "include the test command"],
        evidence_requirements=["context_resolution_sha256", "tests_run"],
    )
    assert correction_request["status"] == "correction_requested"
    correction = correction_request["correction"]
    correction_hash = correction_request["correction_sha256"]
    assert correction["original_result_sha256"] == initial_hash
    assert len(correction_request["correction"]["reason"]) > 0

    corrected = contracts.WorkerResultPacket(
        task_id=packet.task_id,
        worker_identity=initial.worker_identity,
        status="completed",
        summary="Corrected bounded evidence with the requested Brain reference.",
        evidence_refs=["memory:" + memory_id, "test:p12-correction"],
        tests_run=["pytest tests/test_worker_protocol.py -q"],
        correction_of_hash=initial_hash,
        correction_attempt=1,
    ).validate()
    returned = hermes_adapter.return_corrected_worker_result(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        correction,
        json.loads(corrected.canonical_json()),
    )
    assert returned["status"] == "completed"
    assert returned["result_sha256"] == corrected.canonical_hash()
    assert returned["result_sha256"] != initial_hash
    replayed_correction = {
        **correction,
        "reviewer_identity": {
            **correction["reviewer_identity"],
            "agent_id": "hermes:Brain-Other",
        },
    }
    replayed = hermes_adapter.return_corrected_worker_result(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        replayed_correction,
        json.loads(corrected.canonical_json()),
    )
    assert replayed["status"] == "failed"
    assert replayed["failure_code"] == "UNAUTHORIZED_COORDINATOR"
    mismatched_provenance = hermes_adapter.return_corrected_worker_result(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        {**correction, "original_result_sha256": "f" * 64},
        json.loads(corrected.canonical_json()),
    )
    assert mismatched_provenance["status"] == "failed"
    assert mismatched_provenance["failure_code"] == "CORRECTION_MISMATCH"
    other_binding = hermes_adapter.resolve_binding(
        brain_home,
        {
            "bot_name": "Brain-Integrator",
            "bot_role": "integrator",
            "hermes_session_id": "other-reviewer",
            "project_id": "second-brain",
            "repo_root": str(REPO_ROOT),
        },
    )
    other_reviewer = _identity(
        "integrator", session=other_binding.brain_session_id, bot="Brain-Integrator"
    )
    cross_session = hermes_adapter.return_corrected_worker_result(
        brain_home,
        other_binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        {**correction, "reviewer_identity": json.loads(contracts.canonical_json(other_reviewer))},
        json.loads(corrected.canonical_json()),
    )
    assert cross_session["status"] == "failed"
    assert cross_session["failure_code"] == "UNAUTHORIZED_COORDINATOR"

    failed_corrected = contracts.WorkerResultPacket(
        **{
            **corrected.__dict__,
            "status": "failed",
            "failure_code": "WORKER_FAILED",
        }
    ).validate()
    failed_return = hermes_adapter.return_corrected_worker_result(
        brain_home,
        binding,
        json.loads(packet.canonical_json()),
        json.loads(initial.canonical_json()),
        correction,
        json.loads(failed_corrected.canonical_json()),
    )
    assert failed_return["status"] == "failed"
    assert failed_return["failure_code"] == "MALFORMED_RESULT"

    corrected_review = json.loads(corrected.canonical_json())
    corrected_review.update(
        {
            "packet_sha256": packet.canonical_hash(),
            "result_sha256": corrected.canonical_hash(),
        }
    )
    approved = hermes_adapter.review_worker_result(
        brain_home,
        binding,
        corrected_review,
        approved=True,
        evidence={"tests": [{"name": "pytest tests/test_worker_protocol.py", "exit_code": 0}]},
    )
    assert approved["status"] == "reviewed"
    assert approved["result_sha256"] == corrected.canonical_hash()

    ledger_path = hermes_adapter.ledger.LedgerStore(
        brain_home, binding.host_session_id
    ).dbfile
    with sqlite3.connect(ledger_path) as conn:
        rows = [
            (row[0], json.loads(row[1]))
            for row in conn.execute("SELECT event_type, payload_json FROM events ORDER BY seq")
        ]
    event_types = [kind for kind, _payload in rows]
    assert "task_context_resolved" in event_types
    assert event_types.count("result_reviewed") == 2
    rejected_review = next(
        payload
        for kind, payload in rows
        if kind == "result_reviewed" and payload["approved"] is False
    )
    assert rejected_review["reviewed"] is True
    assert "result_correction_requested" in event_types
    assert "result_corrected" in event_types
    corrected_row = next(payload for kind, payload in rows if kind == "result_corrected")
    assert corrected_row["original_result_sha256"] == initial_hash
    assert corrected_row["result_sha256"] == corrected.canonical_hash()
    assert corrected_row["correction_sha256"] == correction_hash
    assert corrected_row["context_resolution_sha256"]

    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    records = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()]
    kinds = [record["kind"] for record in records]
    assert "hermes_worker_context_resolved" in kinds
    assert "hermes_worker_result_correction_requested" in kinds
    assert "hermes_worker_result_corrected" in kinds
    assert all(
        '"content":' not in json.dumps(record)
        for record in records
        if record["kind"].startswith("hermes_worker")
    )


def test_worker_numeric_fields_reject_bool_and_float(brain_home: Path) -> None:
    packet = _packet(brain_home, "memory:none")
    for field, value in (("fanout", 4.0), ("fanout_index", True), ("depth", 1.0)):
        with pytest.raises(contracts.WorkerPacketError):
            contracts.WorkerTaskPacket(
                **{**packet.__dict__, field: value}
            ).validate()

    result = contracts.WorkerResultPacket(
        task_id="numeric-result",
        worker_identity=_identity("dev", session="worker", bot="Brain-Dev"),
        status="completed",
        correction_of_hash="a" * 64,
        correction_attempt=1,
    )
    for value in (1.0, True):
        with pytest.raises(contracts.WorkerPacketError):
            contracts.WorkerResultPacket(
                **{**result.__dict__, "correction_attempt": value}
            ).validate()
    with pytest.raises(contracts.WorkerPacketError, match="retryable"):
        contracts.WorkerResultPacket(
            **{
                **result.__dict__,
                "correction_attempt": 0,
                "correction_of_hash": None,
                "retryable": 1,
            }
        ).validate()

    correction = contracts.WorkerCorrectionPacket(
        task_id="numeric-correction",
        parent_session_id="driver",
        worker_identity=_identity("dev", session="worker", bot="Brain-Dev"),
        reviewer_identity=_identity("integrator", session="driver", bot="Brain-Integrator"),
        original_result_sha256="a" * 64,
        reason="fix",
    )
    for value in (1.0, True):
        with pytest.raises(contracts.WorkerPacketError):
            contracts.WorkerCorrectionPacket(
                **{**correction.__dict__, "correction_attempt": value}
            ).validate()

    task_data = json.loads(packet.canonical_json())
    task_data["constraints"] = "read-only"
    with pytest.raises(contracts.WorkerPacketError, match="MALFORMED_TASK"):
        contracts.WorkerTaskPacket.from_dict(task_data)
    result_data = json.loads(result.canonical_json())
    result_data["evidence_refs"] = "not-a-list"
    with pytest.raises(contracts.WorkerPacketError, match="MALFORMED_RESULT"):
        contracts.WorkerResultPacket.from_dict(result_data)
    correction_data = json.loads(correction.canonical_json())
    correction_data["requested_changes"] = "not-a-list"
    with pytest.raises(contracts.WorkerPacketError, match="MALFORMED_CORRECTION"):
        contracts.WorkerCorrectionPacket.from_dict(correction_data)
