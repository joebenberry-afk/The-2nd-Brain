"""
Provider capability table (plan T2.6) and harness capability profiles/tiers
(plan T4.3).

Two independent, unrelated schemas share this module by design (T4.3
brief: "extend the existing provider-capability module" rather than create
a second control plane):

1. `get_provider_capabilities` -- a narrow, config-driven schema describing
   what a request-routing provider truthfully advertises about prompt
   caching and context capacity. Every field is nullable and comes verbatim
   from `config/v2.toml [providers.<provider_id>]` -- never inferred from
   the model or provider name. A missing provider row and an
   unreadable/malformed config file both fail open to the same
   conservative defaults: no cache support, every other field unknown.

2. `observe`/`declare`/`harness_tier`/`list_capabilities`/`tier_behavior`
   (T4.3) -- a DB-backed `harness_capabilities` table (migration
   `0015_harness_capabilities.sql`) recording what a HOST HARNESS (Claude
   Code, Codex, Antigravity, Hermes, ...) actually supports: session
   lifecycle, prompt injection, tool/usage/cache/compaction telemetry,
   model rewriting, tool filtering, subagents, budget enforcement. Unlike
   the fail-open provider schema above, an unknown *capability name* here
   is a caller-contract violation (a typo'd literal, not untrusted
   external input) and raises `UnknownCapabilityError`; an unknown
   *telemetry event kind* passed to `observe` is untrusted/evolving
   external input and is a deterministic no-op instead.

T3.3 (capability-aware routing) remains a future task and is out of scope
here.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db, paths

_CACHE_SUPPORT_VALUES = frozenset({"implicit", "explicit", "none"})
_CACHE_SCOPE_VALUES = frozenset({"model", "account"})

# Conservative defaults for a missing provider row, or an unreadable/
# malformed config file (fail open, never raise).
_CONSERVATIVE_DEFAULTS: dict[str, Any] = {
    "cache_support": "none",
    "cache_scope": None,
    "min_cacheable_tokens": None,
    "ttl_seconds": None,
    "breakpoints_supported": None,
    "usage_fields": None,
    "context_tokens": None,
}


def get_provider_capabilities(home: Path | str, provider_id: str) -> dict[str, Any]:
    """Read the `[providers.<provider_id>]` capability row from
    `config/v2.toml`. Returns exactly these seven nullable fields:
    cache_support, cache_scope, min_cacheable_tokens, ttl_seconds,
    breakpoints_supported, usage_fields, context_tokens.

    - Missing row -> conservative defaults (cache_support="none", rest None).
    - Unreadable/malformed config -> same conservative defaults (fail open).
    - Present row with an individual field missing or of the wrong shape ->
      that field stays None (never inferred, never defaulted to a
      non-`none` value).
    """
    path = Path(home) / "config" / "v2.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return dict(_CONSERVATIVE_DEFAULTS)

    providers = raw.get("providers") if isinstance(raw, dict) else None
    row = providers.get(provider_id) if isinstance(providers, dict) else None
    if not isinstance(row, dict):
        return dict(_CONSERVATIVE_DEFAULTS)

    # A present row starts fully unknown (None) -- unlike a missing row,
    # an absent `cache_support` field here does NOT default to "none".
    result: dict[str, Any] = {key: None for key in _CONSERVATIVE_DEFAULTS}

    cache_support = row.get("cache_support")
    if isinstance(cache_support, str) and cache_support in _CACHE_SUPPORT_VALUES:
        result["cache_support"] = cache_support

    cache_scope = row.get("cache_scope")
    if isinstance(cache_scope, str) and cache_scope in _CACHE_SCOPE_VALUES:
        result["cache_scope"] = cache_scope

    min_cacheable_tokens = row.get("min_cacheable_tokens")
    if isinstance(min_cacheable_tokens, int) and not isinstance(min_cacheable_tokens, bool):
        result["min_cacheable_tokens"] = min_cacheable_tokens

    ttl_seconds = row.get("ttl_seconds")
    if isinstance(ttl_seconds, int) and not isinstance(ttl_seconds, bool):
        result["ttl_seconds"] = ttl_seconds

    breakpoints_supported = row.get("breakpoints_supported")
    if isinstance(breakpoints_supported, bool):
        result["breakpoints_supported"] = breakpoints_supported

    usage_fields = row.get("usage_fields")
    if isinstance(usage_fields, list) and all(isinstance(f, str) for f in usage_fields):
        result["usage_fields"] = list(usage_fields)

    context_tokens = row.get("context_tokens")
    if isinstance(context_tokens, int) and not isinstance(context_tokens, bool):
        result["context_tokens"] = context_tokens

    return result


# ---------------------------------------------------------------------------
# T4.3: harness capability profiles and tiers.
# ---------------------------------------------------------------------------

#: Exact capability vocabulary (T4.3 brief) -- no extras, no fewer.
KNOWN_CAPABILITIES: frozenset[str] = frozenset(
    {
        "session_events",
        "prompt_injection",
        "tool_events",
        "usage_telemetry",
        "cache_telemetry",
        "compaction_events",
        "model_rewrite",
        "tool_filter",
        "subagents",
        "budget_enforcement",
    }
)

#: Capabilities whose supported=true triggers at least tier T1.
_T1_TRIGGER_CAPABILITIES: frozenset[str] = frozenset(
    {"tool_events", "usage_telemetry", "cache_telemetry", "compaction_events"}
)

#: Capabilities whose supported=true triggers tier T2 (T2 wins over T1/T0).
_T2_TRIGGER_CAPABILITIES: frozenset[str] = frozenset(
    {"model_rewrite", "tool_filter", "subagents", "budget_enforcement"}
)

#: Shared human-readable tier-behavior strings. Declared once here; other
#: tasks/modules that need tier-conditional behavior should import this
#: rather than redefine it (T4.3 brief: "reuse one shared declaration").
TIER_BEHAVIOR: dict[str, str] = {
    "T0": (
        "Baseline harness: only session lifecycle / prompt-injection "
        "visibility (or nothing) is confirmed. Treat as opaque -- observe "
        "only, never assume tool, usage, or control-surface access."
    ),
    "T1": (
        "Operationally observable harness: tool, usage, cache, or "
        "compaction telemetry is confirmed. Safe to report cost/perf "
        "metrics for this harness; still no control surface."
    ),
    "T2": (
        "Fully governable harness: model rewriting, tool filtering, "
        "subagent orchestration, or budget enforcement is confirmed. Safe "
        "to enable adapter-side governance features for this harness."
    ),
}


class UnknownCapabilityError(ValueError):
    """Raised when a caller passes a capability name outside
    `KNOWN_CAPABILITIES`. A wrong literal capability string is a
    programming-time caller-contract violation, not untrusted external
    input -- unlike `get_provider_capabilities`'s fail-open behavior on a
    malformed config file, this is loud and deterministic."""


# Known telemetry `kind` (see `telemetry.KNOWN_KINDS`) -> the harness
# capability/capabilities it evidences when observed. One kind may
# evidence more than one capability only when real evidence supports both
# (e.g. `session_compact` is both a session-lifecycle event AND a
# compaction event). Capabilities with no entry on the right-hand side of
# any mapping here have no `observe()` path yet -- see the T4.3 task
# report for the grep-based evidence and the documented gaps
# (`cache_telemetry`, `budget_enforcement`: no distinct emitted kind
# unambiguously reports either today; only reachable via `declare`).
_EVENT_KIND_CAPABILITIES: dict[str, tuple[str, ...]] = {
    # Session lifecycle.
    "session_start": ("session_events",),
    "session_started": ("session_events",),
    "session_finalized": ("session_events",),
    "session_shutdown": ("session_events",),
    "session_compact": ("session_events", "compaction_events"),
    "session_before_compact": ("session_events", "compaction_events"),
    # Prompt injection.
    "brain_packet_delivered": ("prompt_injection",),
    "brain_no_injection": ("prompt_injection",),
    "autoinject_shadow_decision": ("prompt_injection",),
    "codex_hook_shadow_decision": ("prompt_injection",),
    # Tool events.
    "tool_call": ("tool_events",),
    "tool_result": ("tool_events",),
    "claude_code_tool_result": ("tool_events",),
    # Usage telemetry.
    "assistant_usage": ("usage_telemetry",),
    "provider_request_meta": ("usage_telemetry",),
    "provider_response_meta": ("usage_telemetry",),
    # Model rewrite: `rtd_shadow` is the only kind that evidences the
    # model-visible content actually being rewritten before the model sees
    # it (Reversible Tool Distillation substitutes the tool result body).
    # `hermes_model_decision`/`model_fallback_used`/`model_routing_decision`/
    # `model_invocation_*` are model SELECTION/dispatch bookkeeping (which
    # provider/model was chosen, retried, or invoked), not prompt/content
    # rewriting, so they are deliberately not mapped here.
    "rtd_shadow": ("model_rewrite",),
    # Tool filter.
    "stop_blocked": ("tool_filter",),
    "stop_allowed": ("tool_filter",),
    "orchestrator_policy_violation": ("tool_filter",),
    # Subagents.
    "omp_worker_context_handoff": ("subagents",),
    "omp_worker_child_result": ("subagents",),
    "hermes_worker_lifecycle": ("subagents",),
    "handoff_sent": ("subagents",),
}


def _capabilities_db(home: Path | str) -> Path:
    """Self-healing DB open, mirroring `worker_protocol._worker_db`."""
    dbfile = paths.db_path(Path(home))
    if db.pending_migrations(dbfile):
        db.migrate(dbfile)
    return dbfile


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def observe(
    home: Path | str,
    harness_id: str,
    event_kind: str,
    *,
    version: str | None = None,
    config_binding: str | None = None,
) -> tuple[str, ...]:
    """Record observed capability evidence for a host harness.

    ``version`` and ``config_binding`` bind the observation to the host
    instance that produced it.  Legacy callers may omit them, but such rows
    remain historical evidence and are never current observed support in
    :func:`snapshot`.
    """
    capabilities = _EVENT_KIND_CAPABILITIES.get(event_kind, ())
    if not capabilities:
        return ()
    if version is not None and not isinstance(version, str):
        raise TypeError(f"version must be str or None, got {type(version).__name__}")
    if config_binding is not None and not isinstance(config_binding, str):
        raise TypeError(f"config_binding must be str or None, got {type(config_binding).__name__}")
    dbfile = _capabilities_db(home)
    observed_at = _now_iso()
    conn = db.connect(dbfile)
    try:
        with conn:
            for capability in capabilities:
                evidence: dict[str, Any] = {
                    "event_kind": event_kind,
                    "observed_at": observed_at,
                    "source": "observed",
                }
                if version is not None:
                    evidence["host_version"] = version
                if config_binding is not None:
                    evidence["config_binding"] = config_binding
                evidence_json = json.dumps(evidence, sort_keys=True)
                conn.execute(
                    "INSERT INTO harness_capabilities"
                    "(harness_id, capability, supported, version, observed_at, evidence_json) "
                    "VALUES (?, ?, 1, ?, ?, ?) "
                    "ON CONFLICT(harness_id, capability) DO UPDATE SET "
                    "supported = 1, version = excluded.version, "
                    "observed_at = excluded.observed_at, "
                    "evidence_json = excluded.evidence_json",
                    (harness_id, capability, version, observed_at, evidence_json),
                )
    finally:
        conn.close()
    return capabilities


def _declared_evidence(evidence: Any) -> dict[str, Any]:
    """Tag declaration provenance without changing caller-provided values."""
    if isinstance(evidence, dict):
        result = dict(evidence)
        result["source"] = "declared"
        return result
    return {"source": "declared", "value": evidence}


def _capability_status(
    row: dict[str, Any],
    capability: str,
    *,
    host_version: str | None,
    config_binding: str | None,
) -> str:
    supported = row.get("supported")
    if supported is not None and type(supported) is not bool:
        return "unknown"
    if supported is None:
        return "unknown"
    if supported is False:
        return "denied"
    evidence = row.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("source") != "observed":
        return "declared"
    event_kind = evidence.get("event_kind")
    observed_version = row.get("version")
    observed_binding = evidence.get("config_binding")
    if (
        not isinstance(host_version, str)
        or not host_version
        or observed_version != host_version
        or not isinstance(config_binding, str)
        or not config_binding
        or observed_binding != config_binding
        or evidence.get("host_version") != host_version
        or not isinstance(event_kind, str)
        or capability not in _EVENT_KIND_CAPABILITIES.get(event_kind, ())
    ):
        return "unavailable"
    return "observed"


def snapshot(
    home: Path | str,
    harness_id: str,
    *,
    host_version: str | None = None,
    config_binding: str | None = None,
) -> dict[str, Any]:
    """Take one immutable, host-bound capability read for a decision.

    Status is one of ``declared``, ``observed``, ``unavailable``, ``denied``,
    or ``unknown``.  A declaration or an unbound/old observation is not
    promoted to current observed support.
    """
    if not isinstance(harness_id, str) or not harness_id:
        raise TypeError("harness_id must be a non-empty string")
    if host_version is not None and not isinstance(host_version, str):
        raise TypeError(f"host_version must be str or None, got {type(host_version).__name__}")
    if config_binding is not None and not isinstance(config_binding, str):
        raise TypeError(f"config_binding must be str or None, got {type(config_binding).__name__}")
    state = list_capabilities(home, harness_id)
    rows: dict[str, dict[str, Any]] = {}
    for name, row in state.items():
        enriched = dict(row)
        enriched["status"] = _capability_status(
            row,
            name,
            host_version=host_version,
            config_binding=config_binding,
        )
        rows[name] = enriched
    return {
        "harness_id": harness_id,
        "host_version": host_version,
        "config_binding": config_binding,
        "capabilities": rows,
    }


def declare(
    home: Path | str,
    harness_id: str,
    capability: str,
    supported: bool,
    *,
    version: str | None = None,
    evidence: Any = None,
) -> None:
    """Explicitly record a harness capability's supported state from
    install-time adapter knowledge (e.g. a harness's own hooks.json/plugin
    manifest). Unlike `observe`, `supported` may be explicit `False` --
    that persists distinctly from "never recorded" so a caller can look up
    a harness that explicitly does NOT support a capability and read back
    a real `False`, never a missing row.

    Raises `UnknownCapabilityError` for a capability name outside
    `KNOWN_CAPABILITIES`, and `TypeError` when `supported` is not an
    actual `bool` (no truthy-string coercion, matching this campaign's
    strict-bool convention elsewhere).
    """
    if capability not in KNOWN_CAPABILITIES:
        raise UnknownCapabilityError(
            f"unknown capability {capability!r}; must be one of {sorted(KNOWN_CAPABILITIES)}"
        )
    if not isinstance(supported, bool):
        raise TypeError(f"supported must be bool, got {type(supported).__name__}")
    if version is not None and not isinstance(version, str):
        raise TypeError(f"version must be str or None, got {type(version).__name__}")

    dbfile = _capabilities_db(home)
    observed_at = _now_iso()
    evidence_json = (
        json.dumps(_declared_evidence(evidence), sort_keys=True)
        if evidence is not None
        else json.dumps({"source": "declared"}, sort_keys=True)
    )
    conn = db.connect(dbfile)
    try:
        with conn:
            conn.execute(
                "INSERT INTO harness_capabilities"
                "(harness_id, capability, supported, version, observed_at, evidence_json) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(harness_id, capability) DO UPDATE SET "
                "supported = excluded.supported, version = excluded.version, "
                "observed_at = excluded.observed_at, evidence_json = excluded.evidence_json",
                (harness_id, capability, int(supported), version, observed_at, evidence_json),
            )
    finally:
        conn.close()


def list_capabilities(home: Path | str, harness_id: str) -> dict[str, dict[str, Any]]:
    """Full current state of every known capability for `harness_id`.

    Always returns exactly the 10 `KNOWN_CAPABILITIES` keys. A capability
    with no recorded row reads back as
    `{"supported": None, "version": None, "observed_at": None, "evidence": None}`
    -- never silently `True`. Shared by `harness_tier` and the
    `brainctl v2 harness capabilities` CLI command so neither duplicates
    this SQL.
    """
    dbfile = _capabilities_db(home)
    conn = db.connect(dbfile, readonly=True)
    try:
        rows = conn.execute(
            "SELECT capability, supported, version, observed_at, evidence_json "
            "FROM harness_capabilities WHERE harness_id = ?",
            (harness_id,),
        ).fetchall()
    finally:
        conn.close()

    result: dict[str, dict[str, Any]] = {
        name: {"supported": None, "version": None, "observed_at": None, "evidence": None}
        for name in KNOWN_CAPABILITIES
    }
    for row in rows:
        capability = row["capability"]
        if capability not in result:
            continue  # defensive: never surface a row outside the fixed vocabulary
        evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else None
        result[capability] = {
            "supported": bool(row["supported"]),
            "version": row["version"],
            "observed_at": row["observed_at"],
            "evidence": evidence,
        }
    return result


def tier_from_snapshot(profile: dict[str, Any]) -> str:
    """Derive the effective tier from one host-bound capability snapshot.

    Only capabilities with ``status=observed`` can authorize governance.
    Raw declarations and stale/unbound observations remain visible in the
    snapshot for diagnosis but never raise the effective tier.
    """
    rows = profile.get("capabilities")
    if not isinstance(rows, dict):
        return "T0"
    observed = {
        name
        for name, row in rows.items()
        if isinstance(row, dict) and row.get("status") == "observed"
    }
    if observed & _T2_TRIGGER_CAPABILITIES:
        return "T2"
    if observed & _T1_TRIGGER_CAPABILITIES:
        return "T1"
    return "T0"


def harness_tier(
    home: Path | str,
    harness_id: str,
    *,
    host_version: str | None = None,
    config_binding: str | None = None,
) -> str:
    """Return the effective tier for the current host binding.

    Missing host binding is deliberately conservative: declarations and
    historical observations remain below the current ``observed`` threshold.
    """
    return tier_from_snapshot(
        snapshot(
            home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
    )


def tier_behavior(
    home: Path | str,
    harness_id: str,
    *,
    host_version: str | None = None,
    config_binding: str | None = None,
) -> str:
    """Return the behavior permitted by the effective host-bound tier."""
    return TIER_BEHAVIOR[
        harness_tier(
            home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
    ]


def generate_capability_matrix(
    home: Path | str,
    harnesses: tuple[str, ...] = ("prime", "claude-code", "codex", "antigravity", "hermes"),
    *,
    host_bindings: Mapping[str, Mapping[str, str | None]] | None = None,
) -> dict[str, Any]:
    """Generate a matrix from one snapshot per harness.

    ``host_bindings`` maps harness IDs to the current ``host_version`` and
    ``config_binding``. Missing bindings remain conservative and cannot
    promote declarations or historical observations.
    """
    home_p = Path(home)
    matrix: dict[str, Any] = {
        "harnesses": {},
        "generated_at": _now_iso(),
    }
    for h in harnesses:
        binding = host_bindings.get(h) if host_bindings is not None else None
        if binding is None:
            binding = {}
        if not isinstance(binding, Mapping):
            raise TypeError(f"host_bindings[{h!r}] must be a mapping")
        profile = snapshot(
            home_p,
            h,
            host_version=binding.get("host_version"),
            config_binding=binding.get("config_binding"),
        )
        tier = tier_from_snapshot(profile)
        behavior = TIER_BEHAVIOR[tier]
        state = profile["capabilities"]
        supported = [name for name, row in state.items() if row.get("status") == "observed"]
        unsupported = [name for name, row in state.items() if row.get("status") == "denied"]
        unknown = [
            name
            for name, row in state.items()
            if row.get("status") in {"unknown", "declared", "unavailable"}
        ]
        matrix["harnesses"][h] = {
            "tier": tier,
            "behavior": behavior,
            "capabilities": state,
            "supported_count": len(supported),
            "unsupported_count": len(unsupported),
            "unknown_count": len(unknown),
        }
    return matrix
