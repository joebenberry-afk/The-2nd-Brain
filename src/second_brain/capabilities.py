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


def observe(home: Path | str, harness_id: str, event_kind: str) -> tuple[str, ...]:
    """Map one known telemetry `event_kind` to the harness capability(ies)
    it evidences and upsert each as `supported=true` with evidence.

    Idempotent: re-observing the same evidence re-upserts `observed_at`/
    `evidence_json` and keeps `supported=true` -- never errors on repeat.

    `event_kind` is untrusted/evolving external telemetry input (unlike a
    caller-supplied capability name): an event kind with no known mapping
    is a deterministic NO-OP -- the capability table is left unchanged for
    `harness_id`, and no capability is ever silently marked supported.
    Returns the tuple of capabilities that were marked supported (empty
    when the event kind is unmapped).
    """
    capabilities = _EVENT_KIND_CAPABILITIES.get(event_kind, ())
    if not capabilities:
        return ()
    dbfile = _capabilities_db(home)
    observed_at = _now_iso()
    conn = db.connect(dbfile)
    try:
        with conn:
            for capability in capabilities:
                evidence_json = json.dumps(
                    {"event_kind": event_kind, "observed_at": observed_at}, sort_keys=True
                )
                conn.execute(
                    "INSERT INTO harness_capabilities"
                    "(harness_id, capability, supported, version, observed_at, evidence_json) "
                    "VALUES (?, ?, 1, NULL, ?, ?) "
                    "ON CONFLICT(harness_id, capability) DO UPDATE SET "
                    "supported = 1, observed_at = excluded.observed_at, "
                    "evidence_json = excluded.evidence_json",
                    (harness_id, capability, observed_at, evidence_json),
                )
    finally:
        conn.close()
    return capabilities


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
    evidence_json = json.dumps(evidence, sort_keys=True) if evidence is not None else None
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


def harness_tier(home: Path | str, harness_id: str) -> str:
    """T0/T1/T2 per the T4.3 brief's exact rule.

    T2 when any of model_rewrite/tool_filter/subagents/budget_enforcement
    is supported=true (wins over T1 and T0). Else T1 when any of
    tool_events/usage_telemetry/cache_telemetry/compaction_events is
    supported=true. Else T0 -- the floor, including a harness with zero
    recorded capabilities at all (missing capability degrades to the
    lower tier, never raises, never assumes support).
    """
    state = list_capabilities(home, harness_id)
    supported = {name for name, row in state.items() if row["supported"] is True}
    if supported & _T2_TRIGGER_CAPABILITIES:
        return "T2"
    if supported & _T1_TRIGGER_CAPABILITIES:
        return "T1"
    return "T0"


def tier_behavior(home: Path | str, harness_id: str) -> str:
    """`TIER_BEHAVIOR[harness_tier(home, harness_id)]` -- the one narrow,
    genuinely tier-conditional read helper this task adds so the tier
    computation is proven to actually gate caller-visible behavior (T4.3
    tests), without wiring tier-gating into unrelated adapters."""
    return TIER_BEHAVIOR[harness_tier(home, harness_id)]


def generate_capability_matrix(
    home: Path | str,
    harnesses: tuple[str, ...] = ("prime", "claude-code", "codex", "antigravity", "hermes"),
) -> dict[str, Any]:
    """Generate a full capability matrix across all supported and available harnesses."""
    home_p = Path(home)
    matrix: dict[str, Any] = {
        "harnesses": {},
        "generated_at": _now_iso(),
    }
    for h in harnesses:
        state = list_capabilities(home_p, h)
        tier = harness_tier(home_p, h)
        behavior = tier_behavior(home_p, h)
        supported = [name for name, row in state.items() if row["supported"] is True]
        unsupported = [name for name, row in state.items() if row["supported"] is False]
        unknown = [name for name, row in state.items() if row["supported"] is None]
        matrix["harnesses"][h] = {
            "tier": tier,
            "behavior": behavior,
            "capabilities": state,
            "supported_count": len(supported),
            "unsupported_count": len(unsupported),
            "unknown_count": len(unknown),
        }
    return matrix
