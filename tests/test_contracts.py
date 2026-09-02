"""Phase 0B shared event/protocol contracts (plan §6.2/6.4/6.5/6.7/8.2/9.4/11.2/14).

Deterministic serialization contract tests: canonical packets, NO_INJECTION,
supersede deltas, delivery dedupe, epoch/fingerprint round-trips, tool outcome
state machine, unknown-event policy, and ledger schema versioning.
"""

import json

import pytest

from second_brain import contracts
from second_brain.contracts import (
    BrainDeliveryRecord,
    BrainInjectionDecision,
    BrainLifecycleEvent,
    BrainPacket,
    Confidence,
    DivergenceCategory,
    EpochReason,
    InjectionDecision,
    LedgerHeader,
    LifecycleEventType,
    MemoryItemStatus,
    NoInjectionReason,
    PacketItem,
    RequestEpoch,
    RequestFingerprint,
    SimplificationReviewOutcome,
    SurfaceVisibility,
    ToolOutcome,
    ToolOutcomeState,
    ToolSignal,
    canonical_json,
    is_already_delivered,
    read_ledger_header,
    stable_content_hash,
)
from second_brain.errors import BrainError


def test_estimate_tokens_uses_calibrated_ratio(tmp_path, monkeypatch) -> None:
    """The shared estimator reads the model ratio from the calibration state."""
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(tmp_path))
    state = tmp_path / "state" / "calibration"
    state.mkdir(parents=True)
    (state / "tokens.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_chars_per_token": 4.0,
                "models": {
                    "test-model": {
                        "chars_per_token": 2.0,
                        "source": "calibrated",
                        "pair_count": 2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert contracts.estimate_tokens("x" * 10, model="test-model") == 5
    assert contracts.estimate_tokens("x" * 10, model="missing-model") == 2



def test_calibrate_tokens_reports_insufficient_data(tmp_path) -> None:
    state = contracts.calibrate_tokens(tmp_path)
    assert state["source"] == "default"
    assert state["pair_count"] == 0
    assert state["models"] == {}


def test_calibrate_tokens_fits_measured_pairs_without_raw_content(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"session": "s", "kind": "provider_request_meta", "model": "m", "prompt_chars": 400},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
        {"session": "s", "kind": "provider_request_meta", "model": "m", "prompt_chars": 800},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 300},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["source"] == "calibrated"
    assert state["pair_count"] == 2
    assert state["models"]["m"]["chars_per_token"] == 4.0  # type: ignore[index]
    assert "prompt" not in (tmp_path / "state" / "calibration" / "tokens.json").read_text(
        encoding="utf-8"
    )

def test_estimate_tokens_missing_or_invalid_calibration_uses_explicit_default(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(tmp_path))
    assert contracts.estimate_tokens("x" * 9) == 2
    state = tmp_path / "state" / "calibration"
    state.mkdir(parents=True)
    (state / "tokens.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_chars_per_token": "not-a-ratio",
                "models": {
                    "m": {
                        "chars_per_token": float("nan"),
                        "source": "calibrated",
                        "pair_count": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    info = contracts.token_estimator_info("m")
    assert info == {"chars_per_token": 4.0, "source": "default", "pair_count": 0}
    assert contracts.estimate_tokens("x" * 9, model="m") == 2

def test_estimator_accepts_json_integral_pair_count_like_typescript(tmp_path) -> None:
    state = tmp_path / "state" / "calibration"
    state.mkdir(parents=True)
    (state / "tokens.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": {
                    "m": {
                        "chars_per_token": 8.0,
                        "source": "calibrated",
                        "pair_count": 1.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert contracts.token_estimator_info("m", home=tmp_path) == {
        "chars_per_token": 8.0,
        "source": "calibrated",
        "pair_count": 1,
    }


def test_calibrate_tokens_uses_input_token_deltas_and_tool_bytes_fallback(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"session": "s", "kind": "tool_result", "output_bytes": 400},
        {"session": "s", "kind": "provider_request_meta", "model": "m", "prompt_chars": 800},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
        {"session": "s", "kind": "assistant_usage", "input_tokens": 200},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["models"]["m"]["chars_per_token"] == 8.0  # type: ignore[index]
    assert state["pair_count"] == 1


def test_estimator_rejects_malformed_or_overflowing_calibration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(tmp_path))
    state = tmp_path / "state" / "calibration"
    state.mkdir(parents=True)
    path = state / "tokens.json"
    path.write_bytes(b"{\xff")
    assert contracts.estimate_tokens("x" * 8) == 2
    path.write_text(
        '{"schema_version":1,"default_chars_per_token":4.0,"models":'
        '{"m":{"chars_per_token":' + "9" * 5000 + ',"source":"calibrated","pair_count":1}}}',
        encoding="utf-8",
    )
    assert contracts.estimate_tokens("x" * 8, model="m") == 2


def test_calibrated_top_level_state_does_not_override_fixed_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(tmp_path))
    state = tmp_path / "state" / "calibration"
    state.mkdir(parents=True)
    (state / "tokens.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "calibrated",
                "pair_count": 0,
                "default_chars_per_token": 2.0,
            }
        ),
        encoding="utf-8",
    )
    assert contracts.estimate_tokens("x" * 8) == 2


def test_calibration_skips_malformed_telemetry_numbers(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    (telemetry_dir / "s.jsonl").write_text(
        '{"session":"s","kind":"provider_request_meta","model":"m","prompt_chars":'
        + "9" * 5000
        + '}\n{"session":"s","kind":"assistant_usage","model":"m","input_tokens":100}\n',
        encoding="utf-8",
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["source"] == "default"
    assert state["pair_count"] == 0

def test_calibration_ignores_records_without_session_or_valid_model(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"kind": "provider_request_meta", "model": "m", "prompt_chars": 400},
        {"session": "s", "kind": "provider_request_meta", "model": 123, "prompt_chars": 400},
        {"session": "s", "kind": "assistant_usage", "model": 123, "input_tokens": 100},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["source"] == "default"
    assert state["pair_count"] == 0

def test_calibration_invalid_usage_invalidates_pending_measurement(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"session": "s", "kind": "provider_request_meta", "model": "m", "prompt_chars": 400},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
        {"session": "s", "kind": "provider_request_meta", "model": "m", "prompt_chars": 800},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 200},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["models"]["m"]["chars_per_token"] == 4.0  # type: ignore[index]
    assert state["pair_count"] == 1


def test_new_provider_prompt_supersedes_all_pending_tool_fallbacks(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"session": "s", "kind": "tool_result", "model": "m", "output_bytes": 400},
        {"session": "s", "kind": "provider_request_meta", "prompt_chars": 800},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["models"]["m"]["chars_per_token"] == 8.0  # type: ignore[index]

def test_malformed_provider_or_assistant_model_invalidates_pending(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"session": "s", "kind": "tool_result", "model": "m", "output_bytes": 400},
        {"session": "s", "kind": "provider_request_meta", "model": 123, "prompt_chars": 800},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
        {"session": "s", "kind": "tool_result", "model": "m", "output_bytes": 400},
        {"session": "s", "kind": "assistant_usage", "model": 123, "input_tokens": 100},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 200},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["source"] == "default"
    assert state["pair_count"] == 0


def test_calibration_skips_invalid_utf8_telemetry_file(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    (telemetry_dir / "bad.jsonl").write_bytes(b"{\xff")
    state = contracts.calibrate_tokens(tmp_path)
    assert state["source"] == "default"
    assert state["pair_count"] == 0

def test_invalid_provider_measurement_supersedes_pending_tool_fallback(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"session": "s", "kind": "tool_result", "model": "m", "output_bytes": 400},
        {"session": "s", "kind": "provider_request_meta", "model": "m", "prompt_chars": "bad"},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["source"] == "default"
    assert state["pair_count"] == 0

def test_provider_record_without_prompt_preserves_tool_fallback(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {"session": "s", "kind": "tool_result", "model": "m", "output_bytes": 400},
        {"session": "s", "kind": "provider_request_meta", "model": "m"},
        {"session": "s", "kind": "assistant_usage", "model": "m", "input_tokens": 100},
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    state = contracts.calibrate_tokens(tmp_path)
    assert state["models"]["m"]["chars_per_token"] == 4.0  # type: ignore[index]
    assert state["pair_count"] == 1


def test_cli_calibration_home_is_used_by_estimator(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("SECOND_BRAIN_HOME", raising=False)
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    (telemetry_dir / "s.jsonl").write_text(
        '{"session":"s","kind":"provider_request_meta","model":"m","prompt_chars":200}\n'
        '{"session":"s","kind":"assistant_usage","model":"m","input_tokens":100}\n',
        encoding="utf-8",
    )
    from second_brain.cli import main

    assert main(["--home", str(tmp_path), "calibrate", "tokens", "--json"]) == 0
    capsys.readouterr()
    assert contracts.estimate_tokens("x" * 10, model="m") == 5


def test_calibration_state_contains_aggregates_only(tmp_path) -> None:
    telemetry_dir = tmp_path / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {
            "session": "s",
            "kind": "provider_request_meta",
            "model": "m",
            "prompt_chars": 400,
            "prompt": "DO NOT STORE THIS",
        },
        {
            "session": "s",
            "kind": "assistant_usage",
            "model": "m",
            "input_tokens": 100,
            "output": "DO NOT STORE THIS",
        },
    ]
    (telemetry_dir / "s.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    contracts.calibrate_tokens(tmp_path)
    state_text = (tmp_path / "state" / "calibration" / "tokens.json").read_text(encoding="utf-8")
    assert "DO NOT STORE THIS" not in state_text
    assert "prompt" not in state_text
    assert "output" not in state_text


def _item(
    memory_id: str = "mem-abc",
    version: int = 1,
    status: MemoryItemStatus = MemoryItemStatus.CURRENT,
    confidence: Confidence = Confidence.HIGH,
    supersedes: tuple[str, int] | None = None,
) -> PacketItem:
    return PacketItem(
        memory_id=memory_id,
        version=version,
        status=status,
        confidence=confidence,
        title="Fix migration ordering",
        observation="Migration must run idempotently.",
        guidance="Verify schema_version before applying.",
        evidence=f"brain://{memory_id}/{version}",
        supersedes=supersedes,
    )


def _packet(**kw: object) -> BrainPacket:
    defaults: dict[str, object] = {
        "packet_id": "pkt-1",
        "project": "second-brain",
        "scope": "task",
        "items": [_item()],
    }
    defaults.update(kw)
    return BrainPacket(**defaults)  # type: ignore[arg-type]


def test_packet_byte_identical_for_same_input() -> None:
    a = _packet()
    b = _packet()
    assert a.render() == b.render()
    assert a.render().encode("utf-8") == b.render().encode("utf-8")


def test_packet_timestamp_excluded_from_stable_content() -> None:
    pkt = _packet()
    assert pkt.render(ts="2026-08-16T00:00:00Z") == pkt.render(ts=None)
    assert stable_content_hash(pkt.render(ts="2026-08-16T00:00:00Z")) == stable_content_hash(
        pkt.render()
    )


def test_no_relevant_memory_yields_no_injection() -> None:
    d = BrainInjectionDecision(
        decision=InjectionDecision.NO_INJECTION,
        reason=NoInjectionReason.NO_RELEVANT_MEMORY,
        candidate_ids=[],
        selected_ids=[],
        packet_ref=None,
        packet_token_size=None,
        recipient="worker-a",
    )
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.NO_RELEVANT_MEMORY
    assert d.packet_ref is None
    assert d.packet_token_size is None


def test_new_version_renders_supersedes_delta() -> None:
    pkt = _packet(items=[_item(version=4, supersedes=("mem-abc", 3))])
    text = pkt.render()
    assert "UPDATE mem-abc v4 supersedes mem-abc v3" in text
    assert "mem-abc@3" not in text  # old version never presented
    assert "status: current" in text


def test_contradicted_item_is_labeled() -> None:
    text = _packet(
        items=[_item(status=MemoryItemStatus.CONTRADICTED, confidence=Confidence.LOW)]
    ).render()
    assert "status: contradicted" in text
    assert "confidence: low" in text


def test_delivery_dedupe_skips_already_delivered() -> None:
    h = stable_content_hash(_packet().render())
    rec = BrainDeliveryRecord(
        delivery_id="d1",
        root_session_id="s1",
        agent_session_id="a1",
        branch_id="b1",
        memory_id="mem-abc",
        memory_version=1,
        canonical_hash=h,
        packet_id="pkt-1",
        delivered_event_id="e1",
        delivered_at="2026-08-16T00:00:00Z",
        superseded_by_delivery_id=None,
    )
    assert is_already_delivered(h, [rec])
    assert not is_already_delivered(
        stable_content_hash(_packet(packet_id="pkt-2").render()), [rec]
    )


def test_canonical_json_sorted_keys_and_list_order() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert canonical_json({"a": 2, "b": 1}) == '{"a":2,"b":1}'
    assert canonical_json({"xs": ["z", "a", "m"]}) == '{"xs":["z","a","m"]}'


def test_simplification_review_outcomes_are_canonical() -> None:
    assert [item.value for item in SimplificationReviewOutcome] == [
        "simplify",
        "reuse",
        "defer",
        "no_action",
    ]

def test_stop_lifecycle_events_are_canonical() -> None:
    assert LifecycleEventType.STOP_DECIDED.value == "stop_decided"
    assert LifecycleEventType.STOP_FINALIZED.value == "stop_finalized"

def test_accuracy_gate_lifecycle_event_is_canonical() -> None:
    assert LifecycleEventType.ACCURACY_GATE.value == "accuracy_gate"

def test_independent_verification_lifecycle_event_is_canonical() -> None:
    assert LifecycleEventType.INDEPENDENT_VERIFICATION.value == "independent_verification"


def test_environment_assessment_lifecycle_event_is_canonical() -> None:
    assert LifecycleEventType.ENVIRONMENT_ASSESSMENT.value == "environment_assessment"


def test_epoch_deterministic_and_reason_roundtrip() -> None:
    e = RequestEpoch(
        epoch_id="ep1",
        session_id="s1",
        agent_id="a1",
        reason=EpochReason.COMPACTION,
        provider="deepseek",
        model="deepseek-v4-flash",
        role_profile="worker",
        system_hash="h1",
        tools_hash="h2",
        config_hash="h3",
        host_adapter_version="0.1.0",
        start_seq=10,
        end_seq=None,
    )
    text = canonical_json(e)
    assert text == canonical_json(RequestEpoch.from_dict(json.loads(text)))
    assert '"reason":"compaction"' in text


def test_fingerprint_divergence_roundtrip_and_null_cache_fields() -> None:
    f = RequestFingerprint(
        request_id="r1",
        epoch_id="ep1",
        seq=5,
        session_id="s1",
        agent_id="a1",
        role_profile="orchestrator",
        provider="openai",
        model="gpt-5.6-luna",
        system_structural_hash="s",
        tool_schema_structural_hash="t",
        message_sequence_hash="m",
        model_visible_prefix_hash="p",
        prompt_affecting_config_hash="c",
        previous_request_id=None,
        first_divergence_category=DivergenceCategory.COMPACTION_REPLACEMENT,
        cache_read_tokens=None,
        cache_write_tokens=None,
        cache_miss_tokens=None,
    )
    text = canonical_json(f)
    assert '"first_divergence_category":"COMPACTION_REPLACEMENT"' in text
    assert '"cache_read_tokens":null' in text
    rt = RequestFingerprint.from_dict(json.loads(text))
    assert rt.first_divergence_category is DivergenceCategory.COMPACTION_REPLACEMENT
    assert rt.cache_read_tokens is None
    assert rt.cache_write_tokens is None
    assert rt.cache_miss_tokens is None


def test_tool_outcome_transitions() -> None:
    assert ToolOutcomeState().apply(ToolSignal.NOT_STARTED).state is ToolOutcome.TOOL_NOT_STARTED
    started = ToolOutcomeState().apply(ToolSignal.STARTED)
    assert started.apply(ToolSignal.OUTCOME_UNKNOWN).state is ToolOutcome.TOOL_OUTCOME_UNKNOWN
    assert started.apply(ToolSignal.RESULT).state is ToolOutcome.COMPLETE


def test_tool_outcome_invalid_transitions() -> None:
    with pytest.raises(BrainError):
        ToolOutcomeState().apply(ToolSignal.RESULT)  # result before any start
    with pytest.raises(BrainError):
        ToolOutcomeState().apply(ToolSignal.STARTED).apply(ToolSignal.STARTED)  # double start
    with pytest.raises(BrainError):
        ToolOutcomeState().apply(ToolSignal.OUTCOME_UNKNOWN)  # unknown before any start


def test_unknown_required_event_rejected_unknown_ignorable_skipped() -> None:
    base = {
        "seq": 1,
        "event_id": "e1",
        "internal_session_id": "s1",
        "agent_id": "a1",
        "parent_event_id": None,
        "host_entry_id": None,
        "host_parent_entry_id": None,
        "segment_id": None,
        "event_type": "mystery_event",
        "timestamp": "2026-08-16T00:00:00Z",
        "surface_visibility": SurfaceVisibility.RAW_ONLY,
        "ignorable": False,
        "payload": {},
        "artifact_sha256": None,
        "source_event_ids": [],
    }
    with pytest.raises(BrainError):
        BrainLifecycleEvent.from_dict(base)
    assert BrainLifecycleEvent.from_dict({**base, "ignorable": True}) is None


def test_prime_host_lifecycle_events_turn_end_and_agent_ended_accepted() -> None:
    """Live Prime host events mirrored by the extension (SCHEMA.md kinds
    turn_end / agent_end) are canonical and parse — regression for the
    "unknown required event type: 'turn_end' / 'agent_ended'" rejection."""
    for event_type, payload in (
        ("turn_end", {"turn_index": 3, "tool_result_count": 2}),
        ("agent_ended", {"message_count": 5}),
    ):
        ev = BrainLifecycleEvent.from_dict(
            {
                "seq": 0,
                "event_id": f"mirror-{event_type}",
                "internal_session_id": "s1",
                "agent_id": "a1",
                "parent_event_id": None,
                "event_type": event_type,
                "timestamp": "2026-08-16T00:00:00Z",
                "surface_visibility": SurfaceVisibility.RAW_ONLY,
                "ignorable": False,
                "payload": payload,
            }
        )
        assert ev is not None
        assert ev.event_type in (
            LifecycleEventType.TURN_END,
            LifecycleEventType.AGENT_ENDED,
        )
        # roundtrip through canonical JSON stays stable
        assert BrainLifecycleEvent.from_dict(json.loads(canonical_json(ev))) == ev


def test_lifecycle_event_roundtrip() -> None:
    ev = BrainLifecycleEvent(
        seq=1,
        event_id="e1",
        internal_session_id="s1",
        agent_id="a1",
        parent_event_id=None,
        host_entry_id="h1",
        host_parent_entry_id=None,
        segment_id="seg1",
        event_type=LifecycleEventType.TOOL_COMPLETED,
        timestamp="2026-08-16T00:00:00Z",
        surface_visibility=SurfaceVisibility.MODEL_VISIBLE_APPEND,
        ignorable=False,
        payload={"tool": "bash", "exit_code": 0},
        artifact_sha256=None,
        source_event_ids=["e0"],
    )
    assert BrainLifecycleEvent.from_dict(json.loads(canonical_json(ev))) == ev


def test_ledger_schema_versioning() -> None:
    h = {
        "schema_version": 1,
        "brain_version": "0.1.0",
        "adapter_name": "prime",
        "adapter_version": "0.1.0",
        "created_at": "2026-08-16T00:00:00Z",
    }
    header = read_ledger_header(h)
    assert isinstance(header, LedgerHeader)
    assert header.schema_version == contracts.LEDGER_SCHEMA_VERSION
    with pytest.raises(BrainError, match="newer runtime"):
        read_ledger_header({**h, "schema_version": 2})
    with pytest.raises(BrainError, match="no in-memory upgrader"):
        read_ledger_header({**h, "schema_version": 0})


def test_packet_byte_identical_roundtrip() -> None:
    pkt = _packet(
        items=[
            _item(),
            _item(
                memory_id="mem-xyz",
                version=2,
                status=MemoryItemStatus.CONTRADICTED,
                confidence=Confidence.LOW,
                supersedes=("mem-xyz", 1),
            ),
        ]
    )
    text = pkt.render()
    assert BrainPacket.parse(text).render() == text
