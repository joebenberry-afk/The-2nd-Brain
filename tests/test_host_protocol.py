"""BrainHostProtocol v1 contract: capability-driven negotiation, fail-closed refusals.

The point of these tests is not that the current OMP behaves; it is that a *future* host
is judged by the capabilities it advertises. A version string must change nothing, a
missing safety capability must refuse its feature, a missing optional capability must
leave unrelated features running, and an advertisement that is not bound to a qualified
host identity must not unlock a safety feature no matter what it claims.
"""

import pytest

from second_brain import host_protocol


def _manifest(**capabilities: bool) -> dict:
    base = {name: False for name in host_protocol.CAPABILITIES}
    base.update(capabilities)
    return {
        "protocol_version": 1,
        "bridge": {"name": "brain-host-bridge", "version": "1.0.0"},
        "host": {"vendor": "oh-my-pi", "name": "pi-coding-agent", "version": "18.2.8"},
        "capabilities": base,
    }


# --- negotiation -------------------------------------------------------------


def test_stock_18_2_8_keeps_read_only_work_and_refuses_mutating_delegation() -> None:
    """The live stock shape: binding and cancellation; no grant, settlement or cleanup."""
    decision = host_protocol.negotiate(
        _manifest(execution_binding=True, cancellation_observation=True)
    )

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    assert decision["features"]["settlement_recovery"]["enabled"] is False
    # Declared read-only work is a restricted mode, not a security-qualified lane.
    assert decision["features"]["read_only_delegation_declared"]["enabled"] is True
    assert decision["features"]["read_only_delegation_verified"]["enabled"] is False
    for feature in ("memory", "retrieval", "context_injection", "telemetry"):
        assert decision["features"][feature]["enabled"] is True


def test_declared_read_only_is_not_verified_read_only() -> None:
    """Without the effective tool grant, 'scout' is a name, not proof of read-only tools."""
    decision = host_protocol.negotiate(
        _manifest(execution_binding=True, authenticated_observation_source=True)
    )

    assert decision["features"]["read_only_delegation_verified"]["enabled"] is False
    verified_reason = decision["features"]["read_only_delegation_verified"]["reason"]
    assert "effective_tool_grant" in verified_reason


def test_a_capable_bridge_enables_the_safety_features_once_the_advertisement_is_trusted() -> None:
    decision = host_protocol.negotiate(
        _manifest(
            execution_binding=True,
            effective_tool_grant=True,
            settlement_observation=True,
            cleanup_observation=True,
            execution_census=True,
            authenticated_observation_source=True,
        ),
        trusted_advertisement=True,
        expect_host_version="18.2.8",
    )

    assert decision["features"]["mutating_delegation"]["enabled"] is True
    assert decision["features"]["read_only_delegation_verified"]["enabled"] is True
    assert decision["refusals"] == []
    assert decision["fail_closed"] is False


def test_a_tampered_advertisement_cannot_unlock_a_safety_feature() -> None:
    """Claiming every safety capability is not evidence: the advertisement must be bound."""
    claiming_everything = _manifest(
        execution_binding=True,
        effective_tool_grant=True,
        settlement_observation=True,
        cleanup_observation=True,
        execution_census=True,
        authenticated_observation_source=True,
    )

    decision = host_protocol.negotiate(claiming_everything)

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    assert decision["features"]["read_only_delegation_verified"]["enabled"] is False
    assert decision["features"]["mutating_delegation"]["safety_gated"] is True
    reason = decision["features"]["mutating_delegation"]["reason"]
    assert "not bound to a qualified host identity" in reason
    # Unrelated features are untouched by the safety gate.
    assert decision["features"]["memory"]["enabled"] is True


def test_an_advertisement_for_a_different_host_build_refuses_safety_features() -> None:
    capable = _manifest(
        execution_binding=True,
        settlement_observation=True,
        cleanup_observation=True,
        authenticated_observation_source=True,
    )

    decision = host_protocol.negotiate(
        capable, trusted_advertisement=True, expect_host_version="18.2.9"
    )

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    reason = decision["features"]["mutating_delegation"]["reason"]
    assert "18.2.9" in reason and "18.2.8" in reason


@pytest.mark.parametrize(
    "capability",
    [
        "execution_binding",
        "settlement_observation",
        "cleanup_observation",
        "authenticated_observation_source",
    ],
)
def test_each_missing_required_capability_refuses_mutating_delegation(capability: str) -> None:
    """Mutation check: removing any single safety capability refuses the feature."""
    full = {
        "execution_binding": True,
        "settlement_observation": True,
        "cleanup_observation": True,
        "execution_census": True,
        "authenticated_observation_source": True,
    }
    full[capability] = False

    decision = host_protocol.negotiate(_manifest(**full), trusted_advertisement=True)

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    assert capability in decision["features"]["mutating_delegation"]["reason"]


def test_an_optional_capability_only_narrows_its_dependents() -> None:
    decision = host_protocol.negotiate(_manifest(execution_binding=True))

    assert decision["features"]["read_only_delegation_declared"]["enabled"] is True
    assert decision["features"]["read_only_delegation_declared"]["narrowed_by"] == [
        "cancellation_observation"
    ]
    assert decision["features"]["telemetry"]["enabled"] is True


def test_capabilities_are_never_inferred_from_the_host_version() -> None:
    """A newer version number alone must change nothing."""
    baseline = host_protocol.negotiate(_manifest(execution_binding=True))
    newer = _manifest(execution_binding=True)
    newer["host"]["version"] = "99.0.0"

    assert host_protocol.negotiate(newer)["features"] == baseline["features"]


def test_unknown_capability_and_foreign_protocol_version_are_refused() -> None:
    unknown = _manifest()
    unknown["capabilities"]["settlement_attestation"] = True
    with pytest.raises(host_protocol.HostProtocolError) as unknown_error:
        host_protocol.parse_manifest(unknown)
    assert unknown_error.value.code == "UNKNOWN_CAPABILITY"

    foreign = _manifest()
    foreign["protocol_version"] = 2
    with pytest.raises(host_protocol.HostProtocolError) as version_error:
        host_protocol.parse_manifest(foreign)
    assert version_error.value.code == "UNSUPPORTED_PROTOCOL_VERSION"

    # An unknown capability never implicitly grants anything.
    decision = host_protocol.negotiate(
        _manifest(execution_binding=True), trusted_advertisement=True
    )
    assert decision["features"]["mutating_delegation"]["enabled"] is False


def test_absent_capabilities_default_to_unavailable() -> None:
    raw = _manifest()
    raw["capabilities"] = {"execution_binding": True}

    manifest = host_protocol.parse_manifest(raw)

    assert manifest["capabilities"]["cleanup_observation"] is False
    assert set(manifest["capabilities"]) == set(host_protocol.CAPABILITIES)


# --- observations ------------------------------------------------------------


def _settlement(executor_settled: object) -> dict:
    return {
        "protocol_version": 1,
        "kind": "HostWorkerSettlement",
        "attempt_id": "attempt-1",
        "host_generation": 1,
        "native_execution_id": "ReconWorker",
        "executor_settled": executor_settled,
        "method": "host observation",
        "observation": "execution ended",
    }


def test_observation_binds_to_attempt_and_generation() -> None:
    parsed = host_protocol.parse_observation(
        {
            "protocol_version": 1,
            "kind": "HostWorkerBinding",
            "attempt_id": "attempt-7e8459ce",
            "host_generation": 0,
            "native_execution_id": "ReconWorker",
            "agent_id": "ReconWorker",
            "method": "host snapshot",
            "observation": "agent ReconWorker bound to ReconWorker",
        }
    )

    assert parsed["host_generation"] == 0


@pytest.mark.parametrize("generation", [None, -1, 1.5, "1", True])
def test_observation_refuses_a_non_exact_generation(generation: object) -> None:
    """Unknown is never a wildcard, and zero is a real generation."""
    payload = {
        "protocol_version": 1,
        "kind": "HostCancellation",
        "attempt_id": "attempt-1",
        "host_generation": generation,
        "native_execution_id": "job-1",
        "cancelled": True,
        "method": "snapshot terminal status",
        "observation": "job-1 was cancelled",
    }

    with pytest.raises(host_protocol.HostProtocolError) as error:
        host_protocol.parse_observation(payload)

    assert error.value.code == "MALFORMED_OBSERVATION"


def test_observation_refuses_a_payload_for_a_different_attempt_or_generation() -> None:
    """Structural validity is not enough: the caller's intended identity must match."""
    payload = {
        "protocol_version": 1,
        "kind": "HostWorkerBinding",
        "attempt_id": "attempt-intended",
        "host_generation": 4,
        "native_execution_id": "ReconWorker",
        "agent_id": "ReconWorker",
        "method": "host snapshot",
        "observation": "agent ReconWorker bound to ReconWorker",
    }

    host_protocol.parse_observation(
        payload, expect_attempt_id="attempt-intended", expect_host_generation=4
    )
    with pytest.raises(host_protocol.HostProtocolError) as other_attempt:
        host_protocol.parse_observation(payload, expect_attempt_id="attempt-other")
    assert other_attempt.value.code == "BINDING_MISMATCH"

    with pytest.raises(host_protocol.HostProtocolError) as other_generation:
        host_protocol.parse_observation(payload, expect_host_generation=5)
    assert other_generation.value.code == "BINDING_MISMATCH"


def test_safety_booleans_reject_truthy_non_booleans() -> None:
    """``true`` is the only true value for a safety fact."""
    assert host_protocol.parse_observation(_settlement(True))["executor_settled"] is True
    for value in ("true", 1, 0, None, "yes"):
        with pytest.raises(host_protocol.HostProtocolError):
            host_protocol.parse_observation(_settlement(value))


def test_cleanup_completion_must_be_explicit() -> None:
    """Cleanup is never inferred from an absent field."""
    with pytest.raises(host_protocol.HostProtocolError):
        host_protocol.parse_observation(
            {
                "protocol_version": 1,
                "kind": "HostWorkerCleanup",
                "attempt_id": "attempt-1",
                "host_generation": 1,
                "native_execution_id": "job-1",
                "method": "none",
                "observation": "nothing observed",
            }
        )


def test_tool_grant_requires_an_exact_surface_hash() -> None:
    with pytest.raises(host_protocol.HostProtocolError):
        host_protocol.parse_observation(
            {
                "protocol_version": 1,
                "kind": "HostToolGrant",
                "attempt_id": "attempt-1",
                "host_generation": 1,
                "resolved_agent": "scout",
                "effective_tools": ["read"],
                "effective_tool_surface_hash": "not-a-hash",
                "read_only": True,
                "method": "observed grant",
                "observation": "read only tool set",
            }
        )


def test_inventory_reports_observation_and_never_inferred_quiescence() -> None:
    """An inventory is what the host listed; scope completeness is stated, not assumed."""
    payload = {
        "protocol_version": 1,
        "kind": "HostExecutionInventory",
        "attempt_id": "attempt-1",
        "host_generation": 2,
        "resources": [
            {"kind": "host_execution", "id": "b", "observed_terminal": True},
            {"kind": "worktree", "id": "a", "observed_terminal": False},
        ],
        "census_available": True,
        "census_scope_complete": False,
        "method": "host snapshot enumeration (bounded window)",
        "observation": "two executions observed; absence of a row proves nothing",
    }

    parsed = host_protocol.parse_observation(payload)

    assert [(entry["kind"], entry["id"]) for entry in parsed["resources"]] == [
        ("host_execution", "b"),
        ("worktree", "a"),
    ]
    assert parsed["census_scope_complete"] is False
    with pytest.raises(host_protocol.HostProtocolError):
        host_protocol.parse_observation({**payload, "census_scope_complete": "yes"})
