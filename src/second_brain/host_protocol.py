"""BrainHostProtocol v1 — the versioned, Brain-owned host contract.

An OMP (or OpenCode, or Hermes) integration supplies *facts about the host*; it never
supplies Brain semantics. This module is the only place that decides which Brain
features a host may run, and it decides from advertised **capabilities**, never from a
version string.

Two rules, both from the v3 harness-independence requirement:

* a missing *optional* capability disables only the features that depend on it;
* a missing *safety* capability refuses the dependent feature (fail-closed) instead of
  falling back to a path that can execute but cannot safely release its writer.

The contract deliberately names no host-internal field: ``native_execution_id`` is the
opaque id the bridge reports, and the bridge — not Brain — absorbs any renaming of
``jobId``/``id``/``agentUrlId`` behind it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1

#: Capabilities a bridge may advertise. Every one is a fact about the host, not a wish.
CAPABILITIES: tuple[str, ...] = (
    "effective_tool_grant",
    "execution_binding",
    "settlement_observation",
    "cleanup_observation",
    "cancellation_observation",
    "execution_census",
    # "Authenticated" is part of the capability, not a footnote: an observation that
    # any code in the agent's execution context could emit is a claim, not evidence.
    # Without this, a host that merely asserts settlement would unlock mutating work.
    "authenticated_observation_source",
)

#: Brain features and the capabilities each one needs. ``required`` refuses the feature
#: when absent; ``optional`` only narrows it. A feature with no requirements runs
#: anywhere the adapter is present.
FEATURE_REQUIREMENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "memory": {"required": (), "optional": ()},
    "retrieval": {"required": (), "optional": ()},
    "context_injection": {"required": (), "optional": ()},
    "telemetry": {"required": (), "optional": ("effective_tool_grant",)},
    "read_only_delegation_declared": {
        # A restricted mode: Brain knows which execution ran and can correlate its
        # result. It is NOT a security-qualified lane, because nothing here proves the
        # host's final effective tool grant (see SB-ORCH-001).
        "required": ("execution_binding",),
        "optional": ("cancellation_observation",),
    },
    "read_only_delegation_verified": {
        # The qualified lane: the host's effective tool grant is observed, so a worker
        # named `scout` cannot have been granted a mutating tool after resolution.
        "required": (
            "execution_binding",
            "effective_tool_grant",
            "authenticated_observation_source",
        ),
        "optional": ("cancellation_observation",),
    },
    "mutating_delegation": {
        # The whole point: a writer lease may only be released on authenticated
        # settlement and cleanup, so all three are required, not optional.
        "required": (
            "execution_binding",
            "settlement_observation",
            "cleanup_observation",
            "authenticated_observation_source",
        ),
        "optional": ("execution_census", "cancellation_observation"),
    },
    "settlement_recovery": {
        "required": (
            "settlement_observation",
            "execution_census",
            "authenticated_observation_source",
        ),
        "optional": ("cancellation_observation",),
    },
}

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_MAX_TEXT = 512

#: How much authority a feature's being enabled actually carries.
#: ``unrestricted`` — no host capability needed; ``restricted`` — a mode whose missing
#: check is itself the risk, so it is informational and must not be wired to dispatch
#: without proof; ``safety_qualified`` — gated on capabilities *and* provenance.
FEATURE_CLASS: dict[str, str] = {
    "memory": "unrestricted",
    "retrieval": "unrestricted",
    "context_injection": "unrestricted",
    "telemetry": "unrestricted",
    "read_only_delegation_declared": "restricted",
    "read_only_delegation_verified": "safety_qualified",
    "mutating_delegation": "safety_qualified",
    "settlement_recovery": "safety_qualified",
}


@dataclass(frozen=True)
class QualifiedHostIdentity:
    """The exact host build the Brain has qualified, identified by artifact hashes.

    A *record*, not a runtime value: it is produced when a candidate is qualified and
    reviewed, together with the hashes of the advertisement and of the bridge artifact
    that were reviewed. Nothing at execution time may invent one.
    """

    vendor: str
    name: str
    version: str
    advertisement_sha256: str
    bridge_sha256: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("vendor", self.vendor),
            ("name", self.name),
            ("version", self.version),
        ):
            if not isinstance(value, str) or value.strip() == "":
                raise HostProtocolError(
                    "MALFORMED_QUALIFICATION", f"{field_name} must be a non-empty string"
                )
        for field_name, digest in (
            ("advertisement_sha256", self.advertisement_sha256),
            ("bridge_sha256", self.bridge_sha256),
        ):
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise HostProtocolError(
                    "MALFORMED_QUALIFICATION", f"{field_name} must be a sha256 hex digest"
                )


@dataclass(frozen=True)
class AdvertisementProvenance:
    """Proof that one exact advertisement came from the qualified host build.

    The *record* is the anchor: the digest carried here must equal the record's own
    advertisement hash, so a digest computed from some other advertisement cannot be
    paired with a legitimate record. (Forging the record itself is forging the
    qualification, which is outside this layer's power — see the authority channel.)
    """

    host: QualifiedHostIdentity
    advertisement_sha256: str

    def __post_init__(self) -> None:
        if self.advertisement_sha256 != self.host.advertisement_sha256:
            raise HostProtocolError(
                "PROVENANCE_MISBOUND",
                "provenance digest does not match the qualified record's advertisement hash",
            )


def loads_strict(raw: bytes) -> Any:
    """Parse JSON bytes, refusing ambiguous documents instead of resolving them.

    Public because every consumer of an advertisement, a qualification record or an
    observation must reject ambiguity the same way: ``json.loads`` silently keeps the last
    of two duplicate keys, so a document repeating ``"cleanup_observation"`` could be one
    thing to the code that verifies it and another to whoever reads the file later.
    """

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise HostProtocolError(
                    "DUPLICATE_JSON_KEY",
                    f"document repeats the key {key!r}; ambiguous JSON is refused",
                )
            seen[key] = value
        return seen

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, ValueError) as exc:
        # HostProtocolError from the hook is not a ValueError subclass and propagates.
        raise HostProtocolError(
            "MALFORMED_MANIFEST", f"document is not JSON: {exc}"
        ) from exc


def advertisement_sha256(advertisement: dict[str, Any] | bytes) -> str:
    """Canonical hash of an advertisement: the parsed object, not the raw file bytes.

    **Scope of this hash:** it identifies the *canonicalised advertisement object*
    (keys sorted, whitespace normalised), so two differently serialised JSON files that
    parse to the same object share one identity, and JSON bytes and an already-parsed
    object hash identically. It is NOT a byte-level artifact hash. A qualification record
    that needs both — "the exact file that was reviewed" and "the exact semantics Brain
    negotiated" — should carry ``advertisement_artifact_sha256`` alongside this value.

    Ambiguous documents are refused rather than resolved (see :func:`loads_strict`).
    """
    if isinstance(advertisement, bytes):
        parsed: Any = loads_strict(advertisement)
    else:
        parsed = advertisement
    try:
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HostProtocolError(
            "MALFORMED_MANIFEST", f"advertisement is not JSON-serialisable: {exc}"
        ) from exc
    return hashlib.sha256(canonical).hexdigest()


class HostProtocolError(Exception):
    """A manifest or observation that does not satisfy the contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _text(value: Any, field: str, *, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostProtocolError("MALFORMED_MANIFEST", f"{field} must be a non-empty string")
    if len(value) > limit:
        raise HostProtocolError("MALFORMED_MANIFEST", f"{field} exceeds {limit} chars")
    return value


def _token(value: Any, field: str) -> str:
    text = _text(value, field, limit=64)
    if _TOKEN_RE.match(text) is None:
        raise HostProtocolError("MALFORMED_MANIFEST", f"{field} must be a lowercase identifier")
    return text


def _generation(value: Any, field: str = "host_generation") -> int:
    """A generation is an exact non-negative integer; zero is a real generation."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HostProtocolError("MALFORMED_OBSERVATION", f"{field} must be a non-negative integer")
    return value


def parse_manifest(raw: Any) -> dict[str, Any]:
    """Validate a bridge advertisement.

    Unknown capabilities and unknown protocol versions are refused rather than ignored:
    a bridge that advertises something Brain does not understand may be describing a
    contract Brain cannot honour, and guessing which half is compatible is how silent
    degradation starts.
    """
    if not isinstance(raw, dict):
        raise HostProtocolError("MALFORMED_MANIFEST", "manifest must be an object")
    version = raw.get("protocol_version")
    # `True == 1` in Python, so a boolean version would otherwise pass as v1.
    if isinstance(version, bool) or not isinstance(version, int) or version != PROTOCOL_VERSION:
        raise HostProtocolError(
            "UNSUPPORTED_PROTOCOL_VERSION",
            f"bridge advertises protocol_version {version!r}; "
            f"this Brain implements {PROTOCOL_VERSION}",
        )
    bridge = raw.get("bridge")
    host = raw.get("host")
    if not isinstance(bridge, dict) or not isinstance(host, dict):
        raise HostProtocolError("MALFORMED_MANIFEST", "bridge and host must be objects")
    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, dict):
        raise HostProtocolError("MALFORMED_MANIFEST", "capabilities must be an object")
    advertised: dict[str, bool] = {}
    for name, value in capabilities.items():
        if name not in CAPABILITIES:
            raise HostProtocolError(
                "UNKNOWN_CAPABILITY", f"bridge advertises unknown capability {name!r}"
            )
        if not isinstance(value, bool):
            raise HostProtocolError("MALFORMED_MANIFEST", f"capability {name} must be a boolean")
        advertised[name] = value
    evidence = raw.get("evidence")
    if evidence is not None and not isinstance(evidence, dict):
        raise HostProtocolError("MALFORMED_MANIFEST", "evidence must be an object when present")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "bridge": {
            "name": _token(bridge.get("name"), "bridge.name"),
            "version": _text(bridge.get("version"), "bridge.version", limit=64),
        },
        "host": {
            "vendor": _token(host.get("vendor"), "host.vendor"),
            "name": _token(host.get("name"), "host.name"),
            "version": _text(host.get("version"), "host.version", limit=64),
        },
        # Absent capability == not available. Never inferred from the host version.
        "capabilities": {name: advertised.get(name, False) for name in CAPABILITIES},
        "evidence": {str(k): str(v) for k, v in (evidence or {}).items()},
    }


#: Features whose failure means a *safety* invariant would be weakened. These are
#: additionally gated on the advertisement itself being trusted and bound to the
#: qualified host identity: an advertisement is a claim, and a claim that arrives
#: through a channel agent-controlled code can write is not evidence.
def verify_advertisement(
    advertisement: dict[str, Any] | bytes,
    *,
    qualified: QualifiedHostIdentity,
) -> AdvertisementProvenance:
    """Bind an advertisement to the qualified host build, or refuse.

    There is deliberately no boolean form: the only way to obtain a provenance is to
    present bytes whose hash and identity match a qualification record. A caller cannot
    assert trust; it can only present artifacts that were reviewed.
    """
    digest = advertisement_sha256(advertisement)
    if digest != qualified.advertisement_sha256:
        raise HostProtocolError(
            "ADVERTISEMENT_NOT_QUALIFIED",
            "advertisement bytes do not match the qualified record "
            f"(got {digest[:16]}…, expected {qualified.advertisement_sha256[:16]}…)",
        )
    if isinstance(advertisement, bytes):
        parsed: Any = loads_strict(advertisement)
    else:
        parsed = advertisement
    manifest = parse_manifest(parsed)
    host = manifest["host"]
    if (host["vendor"], host["name"], host["version"]) != (
        qualified.vendor,
        qualified.name,
        qualified.version,
    ):
        raise HostProtocolError(
            "HOST_IDENTITY_MISMATCH",
            f"advertisement names {host['vendor']}/{host['name']} {host['version']}, "
            f"qualified record is {qualified.vendor}/{qualified.name} {qualified.version}",
        )
    return AdvertisementProvenance(host=qualified, advertisement_sha256=digest)


SAFETY_FEATURES: tuple[str, ...] = (
    "mutating_delegation",
    "settlement_recovery",
    "read_only_delegation_verified",
)


def negotiate(
    raw_manifest: Any,
    *,
    provenance: AdvertisementProvenance | None = None,
) -> dict[str, Any]:
    """Decide which Brain features may run on the host behind this advertisement.

    ``provenance`` can only come from :func:`verify_advertisement` against a
    qualification record, and it is bound to the advertisement's bytes: a provenance
    obtained for one advertisement does not authorise another. Without it every
    safety-qualified feature is refused, whatever the manifest claims.
    """
    raw = raw_manifest
    if isinstance(raw, bytes):
        raw = loads_strict(raw)
    manifest = parse_manifest(raw)
    available = manifest["capabilities"]
    digest = (
        advertisement_sha256(raw_manifest) if isinstance(raw_manifest, (dict, bytes)) else ""
    )
    host = manifest["host"]
    provenance_matches = (
        provenance is not None
        and provenance.advertisement_sha256 == digest
        # Same value by construction, stated explicitly: the incoming advertisement must
        # match the *record's* hash, not merely the digest the provenance carries.
        and provenance.advertisement_sha256 == provenance.host.advertisement_sha256
        and (provenance.host.vendor, provenance.host.name, provenance.host.version)
        == (host["vendor"], host["name"], host["version"])
    )
    safety_gate = (
        "advertisement is not bound to a qualified host identity"
        if provenance is None
        else "provenance was computed for different advertisement bytes"
    )
    features: dict[str, dict[str, Any]] = {}
    for feature, requirement in FEATURE_REQUIREMENTS.items():
        missing = [name for name in requirement["required"] if not available.get(name)]
        narrowed = [name for name in requirement["optional"] if not available.get(name)]
        feature_class = FEATURE_CLASS[feature]
        gated = feature in SAFETY_FEATURES and not provenance_matches
        reason = "capabilities present" if not missing else "missing: " + ", ".join(missing)
        if gated and not missing:
            reason = safety_gate
        features[feature] = {
            "enabled": not missing and not gated,
            "reason": reason,
            "narrowed_by": narrowed,
            "feature_class": feature_class,
            "security_qualified": feature_class == "safety_qualified",
        }
    disabled = {name: info for name, info in features.items() if not info["enabled"]}
    return {
        "protocol_version": PROTOCOL_VERSION,
        "host": host,
        "bridge": manifest["bridge"],
        "capabilities": available,
        "features": features,
        "refusals": sorted(disabled),
        "fail_closed": bool(disabled),
        "advertisement_sha256": digest,
        "provenance": "verified" if provenance_matches else "unverified",
    }


def parse_observation(
    raw: Any,
    *,
    expect_attempt_id: str | None = None,
    expect_host_generation: int | None = None,
) -> dict[str, Any]:
    """Validate one host observation, binding it to an exact attempt and generation.

    Passing the identity the caller *intended* turns this from structural validation
    into an end-to-end binding check: a well-formed payload for a different attempt or
    generation is refused rather than silently accepted.
    """
    if not isinstance(raw, dict):
        raise HostProtocolError("MALFORMED_OBSERVATION", "observation must be an object")
    version = raw.get("protocol_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != PROTOCOL_VERSION:
        raise HostProtocolError(
            "UNSUPPORTED_PROTOCOL_VERSION", "observation protocol_version mismatch"
        )
    kind = _text(raw.get("kind"), "kind", limit=64)
    attempt_id = _text(raw.get("attempt_id"), "attempt_id")
    host_generation = _generation(raw.get("host_generation"))
    if expect_attempt_id is not None and attempt_id != expect_attempt_id:
        raise HostProtocolError(
            "BINDING_MISMATCH",
            f"observation names attempt {attempt_id!r}, expected {expect_attempt_id!r}",
        )
    if expect_host_generation is not None and host_generation != expect_host_generation:
        raise HostProtocolError(
            "BINDING_MISMATCH",
            f"observation names generation {host_generation}, expected {expect_host_generation}",
        )
    method = _text(raw.get("method"), "method")
    observation = _text(raw.get("observation"), "observation")
    parsed: dict[str, Any] = {
        "kind": kind,
        "attempt_id": attempt_id,
        "host_generation": host_generation,
        "method": method,
        "observation": observation,
    }
    if kind == "HostWorkerBinding":
        parsed["native_execution_id"] = _text(raw.get("native_execution_id"), "native_execution_id")
        parsed["agent_id"] = _text(raw.get("agent_id"), "agent_id")
    elif kind == "HostWorkerSettlement":
        parsed["native_execution_id"] = _text(raw.get("native_execution_id"), "native_execution_id")
        if not isinstance(raw.get("executor_settled"), bool):
            raise HostProtocolError("MALFORMED_OBSERVATION", "executor_settled must be a boolean")
        parsed["executor_settled"] = raw["executor_settled"]
    elif kind == "HostWorkerCleanup":
        parsed["native_execution_id"] = _text(raw.get("native_execution_id"), "native_execution_id")
        if not isinstance(raw.get("cleanup_complete"), bool):
            raise HostProtocolError("MALFORMED_OBSERVATION", "cleanup_complete must be a boolean")
        parsed["cleanup_complete"] = raw["cleanup_complete"]
    elif kind == "HostCancellation":
        parsed["native_execution_id"] = _text(raw.get("native_execution_id"), "native_execution_id")
        if not isinstance(raw.get("cancelled"), bool):
            raise HostProtocolError("MALFORMED_OBSERVATION", "cancelled must be a boolean")
        parsed["cancelled"] = raw["cancelled"]
    elif kind == "HostToolGrant":
        parsed["resolved_agent"] = _text(raw.get("resolved_agent"), "resolved_agent")
        tools = raw.get("effective_tools")
        if not isinstance(tools, list) or any(not isinstance(t, str) or not t for t in tools):
            raise HostProtocolError(
                "MALFORMED_OBSERVATION", "effective_tools must be a list of names"
            )
        parsed["effective_tools"] = sorted(set(tools))
        digest = raw.get("effective_tool_surface_hash")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise HostProtocolError(
                "MALFORMED_OBSERVATION", "effective_tool_surface_hash must be sha256 hex"
            )
        parsed["effective_tool_surface_hash"] = digest
        if not isinstance(raw.get("read_only"), bool):
            raise HostProtocolError("MALFORMED_OBSERVATION", "read_only must be a boolean")
        parsed["read_only"] = raw["read_only"]
    elif kind == "HostExecutionInventory":
        resources = raw.get("resources")
        if not isinstance(resources, list):
            raise HostProtocolError("MALFORMED_OBSERVATION", "resources must be a list")
        normalized: list[dict[str, Any]] = []
        for entry in resources:
            if not isinstance(entry, dict):
                # Silently dropping a malformed row would present a shorter list as
                # valid evidence; the inventory must fail closed instead.
                raise HostProtocolError(
                    "MALFORMED_OBSERVATION", "every resource entry must be an object"
                )
            if not isinstance(entry.get("observed_terminal"), bool):
                raise HostProtocolError(
                    "MALFORMED_OBSERVATION",
                    "observed_terminal must be a boolean (what was observed, not a truthy value)",
                )
            normalized.append(
                {
                    "kind": _text(entry.get("kind"), "resources[].kind", limit=64),
                    "id": _text(entry.get("id"), "resources[].id"),
                    # What was OBSERVED, not what is true: a listed execution that looks
                    # terminal is not proof that its worktree cannot still mutate.
                    "observed_terminal": entry["observed_terminal"],
                }
            )
        parsed["resources"] = sorted(normalized, key=lambda item: (item["kind"], item["id"]))
        for flag, message in (
            ("census_available", "census_available must be a boolean"),
            ("census_scope_complete", "census_scope_complete must be a boolean"),
        ):
            if not isinstance(raw.get(flag), bool):
                raise HostProtocolError("MALFORMED_OBSERVATION", message)
            parsed[flag] = raw[flag]
    else:
        raise HostProtocolError("UNKNOWN_OBSERVATION_KIND", f"unknown observation kind {kind!r}")
    return parsed
