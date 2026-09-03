"""
Provider capability table (plan T2.6).

A narrow, config-driven schema describing what a request-routing provider
truthfully advertises about prompt caching and context capacity. Every
field is nullable and comes verbatim from `config/v2.toml
[providers.<provider_id>]` -- never inferred from the model or provider
name. A missing provider row and an unreadable/malformed config file both
fail open to the same conservative defaults: no cache support, every
other field unknown.

This module intentionally implements only the schema below. T3.3
(capability-aware routing) and T4.3 (harness-capability vocabulary/tiers)
are future tasks and are out of scope here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

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
