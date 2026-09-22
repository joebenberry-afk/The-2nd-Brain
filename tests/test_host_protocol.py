"""BrainHostProtocol v1 contract: capability-driven negotiation, fail-closed refusals.

The point of these tests is not that the current OMP behaves; it is that a *future* host
is judged by the capabilities it advertises, and that no caller can promote a claim into
evidence. A version string must change nothing, a missing safety capability must refuse
its feature, a missing optional capability must leave unrelated features running, and an
advertisement unlocks a safety feature only when its exact bytes are bound to a qualified
host build by a record — never because a caller asked for trust.
"""

import json

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


def _capable(**overrides: bool) -> dict:
    granted = {
        "execution_binding": True,
        "effective_tool_grant": True,
        "settlement_observation": True,
        "cleanup_observation": True,
        "execution_census": True,
        "authenticated_observation_source": True,
    }
    granted.update(overrides)
    return _manifest(**granted)


def _qualification(advertisement: dict, **overrides: str) -> host_protocol.QualifiedHostIdentity:
    fields = {
        "vendor": "oh-my-pi",
        "name": "pi-coding-agent",
        "version": "18.2.8",
        "advertisement_sha256": host_protocol.advertisement_sha256(advertisement),
        "bridge_sha256": "a" * 64,
    }
    fields.update(overrides)
    return host_protocol.QualifiedHostIdentity(**fields)  # type: ignore[arg-type]


# --- negotiation -------------------------------------------------------------


def test_stock_18_2_8_keeps_read_only_work_and_refuses_mutating_delegation() -> None:
    """The live stock shape: binding and cancellation; no grant, settlement or cleanup."""
    decision = host_protocol.negotiate(
        _manifest(execution_binding=True, cancellation_observation=True)
    )

    assert decision["features"]["mutating_delegation"]["enabled"] is False
    assert decision["features"]["settlement_recovery"]["enabled"] is False
    # Declared read-only work is a restricted, informational mode — not a qualified lane.
    declared = decision["features"]["read_only_delegation_declared"]
    assert declared["enabled"] is True
    assert declared["feature_class"] == "restricted"
    assert declared["security_qualified"] is False
    assert decision["features"]["read_only_delegation_verified"]["enabled"] is False
    for feature in ("memory", "retrieval", "context_injection", "telemetry"):
        assert decision["features"][feature]["enabled"] is True
        assert decision["features"][feature]["feature_class"] == "unrestricted"


def test_declared_read_only_is_never_security_qualified() -> None:
    """A role name is not authority: the verified lane needs the effective tool grant."""
    decision = host_protocol.negotiate(
        _manifest(execution_binding=True, authenticated_observation_source=True)
    )

    verified = decision["features"]["read_only_delegation_verified"]
    assert verified["enabled"] is False
    assert "effective_tool_grant" in verified["reason"]
    assert decision["features"]["read_only_delegation_declared"]["security_qualified"] is False


def test_a_qualified_capable_advertisement_enables_the_safety_features() -> None:
    advertisement = _capable()
    decision = host_protocol.negotiate(
        advertisement,
        provenance=host_protocol.verify_advertisement(
            advertisement, qualified=_qualification(advertisement)
        ),
    )

    assert decision["provenance"] == "verified"
    assert decision["features"]["mutating_delegation"]["enabled"] is True
    assert decision["features"]["read_only_delegation_verified"]["enabled"] is True
    assert decision["refusals"] == []


def test_a_tampered_advertisement_cannot_unlock_a_safety_feature() -> None:
    """Claiming every safety capability is not evidence, with or without a provenance."""
    advertisement = _capable()

    unverified = host_protocol.negotiate(advertisement)
    assert unverified["provenance"] == "unverified"
    assert unverified["features"]["mutating_delegation"]["enabled"] is False
    reason = unverified["features"]["mutating_delegation"]["reason"]
    assert "not bound to a qualified host identity" in reason

    # A provenance obtained for other bytes must not authorise this advertisement.
    original = _capable(cleanup_observation=False)
    provenance = host_protocol.verify_advertisement(
        original, qualified=_qualification(original)
    )
    tampered = host_protocol.negotiate(advertisement, provenance=provenance)
    assert tampered["provenance"] == "unverified"
    assert tampered["features"]["mutating_delegation"]["enabled"] is False
    assert "different advertisement bytes" in tampered["features"]["mutating_delegation"]["reason"]

    # Unrelated features are untouched by the safety gate.
    assert unverified["features"]["memory"]["enabled"] is True


def test_an_advertisement_from_an_unqualified_build_is_refused() -> None:
    """The qualification record names the build; anything else is not that build."""
    advertisement = _capable()

    with pytest.raises(host_protocol.HostProtocolError) as mismatch:
        host_protocol.verify_advertisement(
            advertisement, qualified=_qualification(advertisement, version="18.2.9")
        )
    assert mismatch.value.code == "HOST_IDENTITY_MISMATCH"

    with pytest.raises(host_protocol.HostProtocolError) as bytes_moved:
        host_protocol.verify_advertisement(
            advertisement, qualified=_qualification(advertisement, advertisement_sha256="b" * 64)
        )
    assert bytes_moved.value.code == "ADVERTISEMENT_NOT_QUALIFIED"
    assert not hasattr(host_protocol, "trusted_advertisement")


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
    advertisement = _capable(**{capability: False})
    decision = host_protocol.negotiate(
        advertisement,
        provenance=host_protocol.verify_advertisement(
            advertisement, qualified=_qualification(advertisement)
        ),
    )

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


def test_a_boolean_protocol_version_is_not_version_one() -> None:
    """`True == 1` in Python: a boolean must not pass as a protocol revision."""
    boolean_version = _manifest()
    boolean_version["protocol_version"] = True
    with pytest.raises(host_protocol.HostProtocolError) as error:
        host_protocol.parse_manifest(boolean_version)
    assert error.value.code == "UNSUPPORTED_PROTOCOL_VERSION"


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


def _inventory(**overrides: object) -> dict:
    payload: dict = {
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
    payload.update(overrides)
    return payload


def test_inventory_reports_observation_and_never_inferred_quiescence() -> None:
    """An inventory is what the host listed; scope completeness is stated, not assumed."""
    parsed = host_protocol.parse_observation(_inventory())

    assert [(entry["kind"], entry["id"]) for entry in parsed["resources"]] == [
        ("host_execution", "b"),
        ("worktree", "a"),
    ]
    assert parsed["census_scope_complete"] is False
    with pytest.raises(host_protocol.HostProtocolError):
        host_protocol.parse_observation(_inventory(census_scope_complete="yes"))


@pytest.mark.parametrize("value", ["yes", 1, 0, None, "false"])
def test_inventory_refuses_a_coerced_terminal_flag(value: object) -> None:
    """A truthy value is not an observation: the flag must be a real boolean."""
    payload = _inventory(
        resources=[{"kind": "host_execution", "id": "b", "observed_terminal": value}]
    )

    with pytest.raises(host_protocol.HostProtocolError) as error:
        host_protocol.parse_observation(payload)

    assert error.value.code == "MALFORMED_OBSERVATION"


def test_inventory_refuses_a_malformed_row_instead_of_dropping_it() -> None:
    """Dropping an unreadable row would present a shorter list as valid evidence."""
    payload = _inventory(
        resources=[
            {"kind": "host_execution", "id": "b", "observed_terminal": True},
            "not-an-object",
        ]
    )

    with pytest.raises(host_protocol.HostProtocolError) as error:
        host_protocol.parse_observation(payload)

    assert error.value.code == "MALFORMED_OBSERVATION"


def test_ambiguous_json_is_refused_not_resolved_by_key_order() -> None:
    """A repeated key must not become a parser-dependent way to look qualified."""
    duplicated_capability = (
        b'{"protocol_version":1,"bridge":{"name":"brain-host-bridge","version":"1.0.0"},'
        b'"host":{"vendor":"oh-my-pi","name":"pi-coding-agent","version":"18.2.8"},'
        b'"capabilities":{"execution_binding":true,"cleanup_observation":false,'
        b'"cleanup_observation":true,"settlement_observation":true,'
        b'"authenticated_observation_source":true}}'
    )
    duplicated_version = (
        b'{"protocol_version":1,"protocol_version":2,'
        b'"bridge":{"name":"brain-host-bridge","version":"1.0.0"},'
        b'"host":{"vendor":"oh-my-pi","name":"pi-coding-agent","version":"18.2.8"},'
        b'"capabilities":{}}'
    )

    for raw in (duplicated_capability, duplicated_version):
        for entry_point in (
            lambda payload: host_protocol.advertisement_sha256(payload),
            lambda payload: host_protocol.negotiate(payload),
            lambda payload: host_protocol.verify_advertisement(
                payload,
                qualified=host_protocol.QualifiedHostIdentity(
                    vendor="oh-my-pi",
                    name="pi-coding-agent",
                    version="18.2.8",
                    advertisement_sha256="a" * 64,
                    bridge_sha256="b" * 64,
                ),
            ),
        ):
            with pytest.raises(host_protocol.HostProtocolError) as error:
                entry_point(raw)
            assert error.value.code == "DUPLICATE_JSON_KEY"


def test_unrelated_extra_fields_cannot_change_a_decision() -> None:
    """Only validated fields decide; extras cannot smuggle a capability or a trust flag."""
    advertisement = _capable()
    advertisement["trusted"] = True
    advertisement["trusted_advertisement"] = True
    advertisement["security"] = {"authenticated_observation_source": True}
    advertisement["capabilities"]["not_a_capability"] = True

    with pytest.raises(host_protocol.HostProtocolError) as unknown:
        host_protocol.parse_manifest(advertisement)
    assert unknown.value.code == "UNKNOWN_CAPABILITY"

    clean = _capable()
    qualified = _qualification(clean)
    provenance = host_protocol.verify_advertisement(clean, qualified=qualified)
    smuggled = {**_capable(), "trusted": True}
    decision = host_protocol.negotiate(smuggled, provenance=provenance)

    assert decision["provenance"] == "unverified"
    assert decision["features"]["mutating_delegation"]["enabled"] is False


def test_a_provenance_cannot_be_rebound_to_another_advertisement() -> None:
    """The record is the anchor: a digest from elsewhere must not pair with it."""
    qualified = _qualification(_capable(cleanup_observation=False))
    other_digest = host_protocol.advertisement_sha256(_capable())

    with pytest.raises(host_protocol.HostProtocolError) as misbound:
        host_protocol.AdvertisementProvenance(host=qualified, advertisement_sha256=other_digest)

    assert misbound.value.code == "PROVENANCE_MISBOUND"


def test_bytes_and_parsed_advertisements_hash_identically() -> None:
    """A legitimate verification must not become 'unverified' because the caller parsed first."""
    advertisement = _capable()
    raw = json.dumps(advertisement, indent=2).encode("utf-8")
    qualified = host_protocol.QualifiedHostIdentity(
        vendor="oh-my-pi",
        name="pi-coding-agent",
        version="18.2.8",
        advertisement_sha256=host_protocol.advertisement_sha256(advertisement),
        bridge_sha256="a" * 64,
    )

    provenance = host_protocol.verify_advertisement(raw, qualified=qualified)
    from_bytes = host_protocol.negotiate(raw, provenance=provenance)
    from_object = host_protocol.negotiate(json.loads(raw.decode("utf-8")), provenance=provenance)

    assert from_bytes["provenance"] == "verified"
    assert from_object["provenance"] == "verified"
    assert from_object["features"]["mutating_delegation"]["enabled"] is True


def test_an_observation_with_a_boolean_protocol_version_is_refused() -> None:
    with pytest.raises(host_protocol.HostProtocolError):
        host_protocol.parse_observation({**_settlement(True), "protocol_version": True})


def test_qualification_records_reject_malformed_hashes() -> None:
    with pytest.raises(host_protocol.HostProtocolError) as error:
        host_protocol.QualifiedHostIdentity(
            vendor="oh-my-pi",
            name="pi-coding-agent",
            version="18.2.8",
            advertisement_sha256="not-a-hash",
            bridge_sha256="a" * 64,
        )

    assert error.value.code == "MALFORMED_QUALIFICATION"
