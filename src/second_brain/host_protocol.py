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

import re
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
)

#: Brain features and the capabilities each one needs. ``required`` refuses the feature
#: when absent; ``optional`` only narrows it. A feature with no requirements runs
#: anywhere the adapter is present.
FEATURE_REQUIREMENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "memory": {"required": (), "optional": ()},
    "retrieval": {"required": (), "optional": ()},
    "context_injection": {"required": (), "optional": ()},
    "telemetry": {"required": (), "optional": ("effective_tool_grant",)},
    "read_only_delegation": {
        "required": ("execution_binding",),
        "optional": ("cancellation_observation", "effective_tool_grant"),
    },
    "mutating_delegation": {
        # The whole point: a writer lease may only be released on authenticated
        # settlement and cleanup, so both are required, not optional.
        "required": ("execution_binding", "settlement_observation", "cleanup_observation"),
        "optional": ("execution_census", "cancellation_observation"),
    },
    "settlement_recovery": {
        "required": ("settlement_observation", "execution_census"),
        "optional": ("cancellation_observation",),
    },
}

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_MAX_TEXT = 512


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
    if version != PROTOCOL_VERSION:
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


def negotiate(raw_manifest: Any) -> dict[str, Any]:
    """Decide which Brain features may run on the host behind this advertisement."""
    manifest = parse_manifest(raw_manifest)
    available = manifest["capabilities"]
    features: dict[str, dict[str, Any]] = {}
    for feature, requirement in FEATURE_REQUIREMENTS.items():
        missing = [name for name in requirement["required"] if not available.get(name)]
        narrowed = [name for name in requirement["optional"] if not available.get(name)]
        features[feature] = {
            "enabled": not missing,
            "reason": "capabilities present" if not missing else "missing: " + ", ".join(missing),
            "narrowed_by": narrowed,
        }
    disabled = {name: info for name, info in features.items() if not info["enabled"]}
    return {
        "protocol_version": PROTOCOL_VERSION,
        "host": manifest["host"],
        "bridge": manifest["bridge"],
        "capabilities": available,
        "features": features,
        "refusals": sorted(disabled),
        "fail_closed": bool(disabled),
    }


def parse_observation(raw: Any) -> dict[str, Any]:
    """Validate one host observation, binding it to an exact attempt and generation."""
    if not isinstance(raw, dict):
        raise HostProtocolError("MALFORMED_OBSERVATION", "observation must be an object")
    if raw.get("protocol_version") != PROTOCOL_VERSION:
        raise HostProtocolError(
            "UNSUPPORTED_PROTOCOL_VERSION", "observation protocol_version mismatch"
        )
    kind = _text(raw.get("kind"), "kind", limit=64)
    attempt_id = _text(raw.get("attempt_id"), "attempt_id")
    host_generation = _generation(raw.get("host_generation"))
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
    elif kind == "HostExecutionCensus":
        resources = raw.get("resources")
        if not isinstance(resources, list):
            raise HostProtocolError("MALFORMED_OBSERVATION", "resources must be a list")
        parsed["resources"] = sorted(
            (
                {
                    "kind": _text(entry.get("kind"), "resources[].kind", limit=64),
                    "id": _text(entry.get("id"), "resources[].id"),
                    "quiescent": bool(entry.get("quiescent")),
                }
                for entry in resources
                if isinstance(entry, dict)
            ),
            key=lambda entry: (entry["kind"], entry["id"]),
        )
        if not isinstance(raw.get("resources_complete"), bool):
            raise HostProtocolError("MALFORMED_OBSERVATION", "resources_complete must be a boolean")
        parsed["resources_complete"] = raw["resources_complete"]
    else:
        raise HostProtocolError("UNKNOWN_OBSERVATION_KIND", f"unknown observation kind {kind!r}")
    return parsed
