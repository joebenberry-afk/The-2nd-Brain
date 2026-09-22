"""BrainHostProtocol v1 contract: capability-driven negotiation, fail-closed refusals.

The point of these tests is not that the current OMP behaves; it is that a *future*
host is judged by the capabilities it advertises. A version string must change nothing,
a missing safety capability must refuse its feature, and a missing optional capability
must leave unrelated features running.
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


def test_stock_18_2_8_keeps_read_only_work_and_refuses_mutating_delegation() -> None:
    """The live stock shape: binding, cancellation and census; no settlement or cleanup."""
    decision = host_protocol.negotiate(
        _manifest(execution_binding=True, cancellation_observation=True, execution_census=True)
    )

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    assert decision["features"]["settlement_recovery"]["enabled"] is False
    assert decision["refusals"] == ["mutating_delegation", "settlement_recovery"]
    for feature in ("memory", "retrieval", "context_injection", "read_only_delegation"):
        assert decision["features"][feature]["enabled"] is True


def test_a_capable_bridge_enables_mutating_delegation() -> None:
    decision = host_protocol.negotiate(
        _manifest(
            execution_binding=True,
            settlement_observation=True,
            cleanup_observation=True,
            execution_census=True,
            authenticated_observation_source=True,
        )
    )

    assert decision["features"]["mutating_delegation"]["enabled"] is True
    assert decision["refusals"] == []
    assert decision["fail_closed"] is False


def test_settlement_claims_without_an_authentication_boundary_still_refuse_mutating() -> None:
    """A host that merely asserts settlement must not unlock mutating work."""
    decision = host_protocol.negotiate(
        _manifest(
            execution_binding=True,
            settlement_observation=True,
            cleanup_observation=True,
            execution_census=True,
            authenticated_observation_source=False,
        )
    )

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    reason = decision["features"]["mutating_delegation"]["reason"]
    assert "authenticated_observation_source" in reason


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

    decision = host_protocol.negotiate(_manifest(**full))

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    assert capability in decision["features"]["mutating_delegation"]["reason"]


def test_an_optional_capability_only_narrows_its_dependents() -> None:
    decision = host_protocol.negotiate(_manifest(execution_binding=True))

    assert decision["features"]["read_only_delegation"]["enabled"] is True
    assert decision["features"]["read_only_delegation"]["narrowed_by"] == [
        "cancellation_observation",
        "effective_tool_grant",
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


def test_absent_capabilities_default_to_unavailable() -> None:
    raw = _manifest()
    raw["capabilities"] = {"execution_binding": True}

    manifest = host_protocol.parse_manifest(raw)

    assert manifest["capabilities"]["cleanup_observation"] is False
    assert set(manifest["capabilities"]) == set(host_protocol.CAPABILITIES)


def test_observation_binds_to_attempt_and_generation() -> None:
    parsed = host_protocol.parse_observation(
        {
            "protocol_version": 1,
            "kind": "HostWorkerSettlement",
            "attempt_id": "attempt-7e8459ce",
            "host_generation": 0,
            "native_execution_id": "ReconWorker",
            "executor_settled": True,
            "method": "ctx.getAsyncJobSnapshot() terminal status",
            "observation": "execution ReconWorker reached completed",
        }
    )

    assert parsed["host_generation"] == 0
    assert parsed["executor_settled"] is True


@pytest.mark.parametrize("generation", [None, -1, 1.5, "1", True])
def test_observation_refuses_a_non_exact_generation(generation: object) -> None:
    """Unknown is never a wildcard, and zero is a real generation."""
    with pytest.raises(host_protocol.HostProtocolError) as error:
        host_protocol.parse_observation(
            {
                "protocol_version": 1,
                "kind": "HostCancellation",
                "attempt_id": "attempt-1",
                "host_generation": generation,
                "native_execution_id": "job-1",
                "cancelled": True,
                "method": "snapshot terminal status",
                "observation": "job-1 reached failed",
            }
        )

    assert error.value.code == "MALFORMED_OBSERVATION"


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
                "method": "requested tools",
                "observation": "read only tool set",
            }
        )


def test_census_resources_are_normalized_and_sorted() -> None:
    parsed = host_protocol.parse_observation(
        {
            "protocol_version": 1,
            "kind": "HostExecutionCensus",
            "attempt_id": "attempt-1",
            "host_generation": 2,
            "resources": [
                {"kind": "host_execution", "id": "b", "quiescent": True},
                {"kind": "worktree", "id": "a", "quiescent": False},
            ],
            "resources_complete": True,
            "method": "snapshot enumeration",
            "observation": "two resources listed",
        }
    )

    # Resources are ordered by (kind, id), never by insertion order.
    assert [(entry["kind"], entry["id"]) for entry in parsed["resources"]] == [
        ("host_execution", "b"),
        ("worktree", "a"),
    ]
    assert parsed["resources_complete"] is True
