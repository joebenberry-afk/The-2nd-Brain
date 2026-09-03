"""T2.6 provider capability table tests.

Covers `second_brain.capabilities.get_provider_capabilities` (the narrow,
config-driven, seven-field nullable schema) and its single narrow
integration point in `vmem._load_economics_parameters` (T2.1).
"""

from __future__ import annotations

from second_brain import capabilities, vmem


def _write_v2_toml(home, text: str) -> None:
    config_dir = home / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "v2.toml").write_text(text, encoding="utf-8")


def test_missing_provider_row_uses_conservative_defaults(brain_home):
    """No [providers.<id>] section at all -> cache_support='none', every
    other field None. Never inferred from the provider id itself."""
    _write_v2_toml(brain_home, "[economics]\nuncached_in = 1.0\n")
    result = capabilities.get_provider_capabilities(brain_home, "unknown-provider")
    assert result == {
        "cache_support": "none",
        "cache_scope": None,
        "min_cacheable_tokens": None,
        "ttl_seconds": None,
        "breakpoints_supported": None,
        "usage_fields": None,
        "context_tokens": None,
    }


def test_no_config_file_uses_conservative_defaults(brain_home):
    """No config/v2.toml at all (never written) -> same conservative defaults."""
    result = capabilities.get_provider_capabilities(brain_home, "anthropic")
    assert result["cache_support"] == "none"
    assert result["cache_scope"] is None
    assert result["context_tokens"] is None


def test_present_row_full_fields_returns_verbatim(brain_home):
    """A fully-populated row is returned exactly as configured -- no fields
    silently dropped or coerced beyond their declared type."""
    _write_v2_toml(
        brain_home,
        """
[providers.anthropic]
cache_support = "explicit"
cache_scope = "account"
min_cacheable_tokens = 1024
ttl_seconds = 300
breakpoints_supported = true
usage_fields = ["cache_read_input_tokens", "cache_creation_input_tokens"]
context_tokens = 200000
""",
    )
    result = capabilities.get_provider_capabilities(brain_home, "anthropic")
    assert result == {
        "cache_support": "explicit",
        "cache_scope": "account",
        "min_cacheable_tokens": 1024,
        "ttl_seconds": 300,
        "breakpoints_supported": True,
        "usage_fields": ["cache_read_input_tokens", "cache_creation_input_tokens"],
        "context_tokens": 200000,
    }


def test_present_row_partial_fields_leaves_rest_none(brain_home):
    """A row that only sets cache_support leaves every other field None --
    not inferred, not defaulted to a non-'none' value."""
    _write_v2_toml(
        brain_home,
        """
[providers.deepseek]
cache_support = "implicit"
""",
    )
    result = capabilities.get_provider_capabilities(brain_home, "deepseek")
    assert result["cache_support"] == "implicit"
    assert result["cache_scope"] is None
    assert result["min_cacheable_tokens"] is None
    assert result["ttl_seconds"] is None
    assert result["breakpoints_supported"] is None
    assert result["usage_fields"] is None
    assert result["context_tokens"] is None


def test_present_row_with_absent_cache_support_stays_none(brain_home):
    """Unlike a MISSING row (which defaults to cache_support='none'), a
    PRESENT row that simply omits cache_support stays None."""
    _write_v2_toml(
        brain_home,
        """
[providers.deepseek]
cache_scope = "model"
""",
    )
    result = capabilities.get_provider_capabilities(brain_home, "deepseek")
    assert result["cache_support"] is None
    assert result["cache_scope"] == "model"


def test_malformed_config_fails_open_to_conservative_defaults(brain_home):
    """Unparseable TOML never raises -- fails open exactly like a missing row."""
    _write_v2_toml(brain_home, "[providers.anthropic\ncache_support = broken toml here")
    result = capabilities.get_provider_capabilities(brain_home, "anthropic")
    assert result["cache_support"] == "none"
    assert result["cache_scope"] is None
    assert result["context_tokens"] is None


def test_invalid_enum_values_are_not_fabricated(brain_home):
    """An out-of-vocabulary cache_support/cache_scope value is never passed
    through verbatim -- it is not real config data, so it stays None."""
    _write_v2_toml(
        brain_home,
        """
[providers.weird]
cache_support = "sometimes"
cache_scope = "galaxy"
""",
    )
    result = capabilities.get_provider_capabilities(brain_home, "weird")
    assert result["cache_support"] is None
    assert result["cache_scope"] is None


def test_never_infers_from_provider_name(brain_home):
    """A provider_id that looks like a well-known caching provider (e.g.
    'anthropic') gets no special-cased behavior when its row is absent."""
    _write_v2_toml(brain_home, "[providers.other]\ncache_support = \"explicit\"\n")
    result = capabilities.get_provider_capabilities(brain_home, "anthropic")
    assert result["cache_support"] == "none"
    assert result["cache_scope"] is None


class TestT21EconomicsIntegration:
    """T2.1 integration: `_load_economics_parameters(home, provider_id=...)`
    forces cache_write == cache_read only when the provider's capability
    row reports cache_support == 'none'."""

    def test_cache_write_equals_cache_read_when_cache_support_none(self, brain_home):
        _write_v2_toml(
            brain_home,
            """
[economics]
cache_read = 0.10
cache_write = 1.25

[providers.no-cache-provider]
cache_support = "none"
""",
        )
        econ = vmem._load_economics_parameters(brain_home, provider_id="no-cache-provider")
        assert econ["cache_read"] == 0.10
        assert econ["cache_write"] == 0.10
        assert econ["cache_write"] == econ["cache_read"]

    def test_unchanged_when_cache_support_explicit(self, brain_home):
        _write_v2_toml(
            brain_home,
            """
[economics]
cache_read = 0.10
cache_write = 1.25

[providers.anthropic]
cache_support = "explicit"
""",
        )
        econ = vmem._load_economics_parameters(brain_home, provider_id="anthropic")
        assert econ["cache_read"] == 0.10
        assert econ["cache_write"] == 1.25

    def test_cache_write_equals_cache_read_when_capability_row_absent(self, brain_home):
        """A missing [providers.<id>] row defaults to cache_support='none'
        per the T2.6 schema, so the T2.1 collapse applies here too --
        unlike an explicit non-'none' row, absence is not neutral."""
        _write_v2_toml(
            brain_home,
            """
[economics]
cache_read = 0.10
cache_write = 1.25
""",
        )
        econ = vmem._load_economics_parameters(brain_home, provider_id="unknown-provider")
        assert econ["cache_read"] == 0.10
        assert econ["cache_write"] == 0.10

    def test_unchanged_when_provider_id_omitted(self, brain_home):
        """Existing (pre-T2.6) call sites that pass no provider_id at all
        must observe byte-identical behavior."""
        _write_v2_toml(
            brain_home,
            """
[economics]
cache_read = 0.10
cache_write = 1.25

[providers.no-cache-provider]
cache_support = "none"
""",
        )
        econ = vmem._load_economics_parameters(brain_home)
        assert econ["cache_read"] == 0.10
        assert econ["cache_write"] == 1.25

    def test_provider_table_price_override_still_applies_before_cache_support_check(self, brain_home):
        """The existing [providers.<id>] cache_read/cache_write price
        override logic (untouched by T2.6) still runs; cache_support='none'
        then collapses cache_write onto whatever cache_read resolved to."""
        _write_v2_toml(
            brain_home,
            """
[economics]
cache_read = 0.10
cache_write = 1.25

[providers.no-cache-provider]
cache_read = 0.20
cache_support = "none"
""",
        )
        econ = vmem._load_economics_parameters(brain_home, provider_id="no-cache-provider")
        assert econ["cache_read"] == 0.20
        assert econ["cache_write"] == 0.20
