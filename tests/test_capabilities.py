"""T2.6 provider capability table tests, plus T4.3 harness capability
profile/tier tests.

Covers `second_brain.capabilities.get_provider_capabilities` (the narrow,
config-driven, seven-field nullable schema) and its single narrow
integration point in `vmem._load_economics_parameters` (T2.1); and the
T4.3 DB-backed `observe`/`declare`/`harness_tier`/`list_capabilities`/
`tier_behavior` harness capability surface + its CLI command.
"""

from __future__ import annotations

import json

import pytest

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
    _write_v2_toml(brain_home, '[providers.other]\ncache_support = "explicit"\n')
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

    def test_provider_table_price_override_still_applies_before_cache_support_check(
        self, brain_home
    ):
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


# ---------------------------------------------------------------------------
# T4.3: harness capability profiles and tiers.
# ---------------------------------------------------------------------------


def test_migration_0015_fresh_create_and_idempotent(brain_home):
    """`brain_home` already ran `db.migrate` (0015 included); a second
    `migrate` is a no-op and the table/index exist with the exact brief
    schema."""
    from second_brain import db

    dbfile = db.db_path(brain_home)
    assert db.migrate(dbfile) == []
    conn = db.connect(dbfile)
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(harness_capabilities)")}
        assert cols == {
            "harness_id",
            "capability",
            "supported",
            "version",
            "observed_at",
            "evidence_json",
        }
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(harness_capabilities)")}
        assert any("harness" in name for name in indexes)
    finally:
        conn.close()


def test_tier_from_bound_observed_events(brain_home):
    """Only observations bound to the current version/config can raise tiers."""
    harness_id = "claude-code"
    host_version = "2.0"
    config_binding = "config-a"
    assert capabilities.harness_tier(brain_home, harness_id) == "T0"

    marked = capabilities.observe(
        brain_home,
        harness_id,
        "session_start",
        version=host_version,
        config_binding=config_binding,
    )
    assert marked == ("session_events",)
    assert (
        capabilities.harness_tier(
            brain_home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
        == "T0"
    )

    marked = capabilities.observe(
        brain_home,
        harness_id,
        "tool_call",
        version=host_version,
        config_binding=config_binding,
    )
    assert marked == ("tool_events",)
    assert (
        capabilities.harness_tier(
            brain_home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
        == "T1"
    )

    marked = capabilities.observe(
        brain_home,
        harness_id,
        "omp_worker_context_handoff",
        version=host_version,
        config_binding=config_binding,
    )
    assert marked == ("subagents",)
    assert (
        capabilities.harness_tier(
            brain_home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
        == "T2"
    )


def test_stale_unbound_and_declared_capabilities_stay_conservative(brain_home):
    harness_id = "stale-harness"
    capabilities.observe(
        brain_home,
        harness_id,
        "tool_call",
        version="1.0",
        config_binding="config-a",
    )
    capabilities.declare(brain_home, harness_id, "subagents", True, version="2.0")

    assert capabilities.harness_tier(brain_home, harness_id) == "T0"
    profile = capabilities.snapshot(
        brain_home,
        harness_id,
        host_version="2.0",
        config_binding="config-a",
    )
    assert capabilities.tier_from_snapshot(profile) == "T0"
    assert profile["capabilities"]["tool_events"]["status"] == "unavailable"
    assert profile["capabilities"]["subagents"]["status"] == "declared"
    assert (
        capabilities.harness_tier(
            brain_home,
            harness_id,
            host_version="2.0",
            config_binding="config-other",
        )
        == "T0"
    )


def test_capability_matrix_uses_current_bound_observations(brain_home):
    harness_id = "matrix-harness"
    capabilities.declare(brain_home, harness_id, "subagents", True)
    capabilities.observe(
        brain_home,
        harness_id,
        "tool_call",
        version="1.0",
        config_binding="config-a",
    )

    missing = capabilities.generate_capability_matrix(brain_home, harnesses=(harness_id,))[
        "harnesses"
    ][harness_id]
    assert missing["tier"] == "T0"
    assert missing["supported_count"] == 0
    assert missing["capabilities"]["tool_events"]["status"] == "unavailable"
    assert missing["capabilities"]["subagents"]["status"] == "declared"

    current = capabilities.generate_capability_matrix(
        brain_home,
        harnesses=(harness_id,),
        host_bindings={harness_id: {"host_version": "1.0", "config_binding": "config-a"}},
    )["harnesses"][harness_id]
    assert current["tier"] == "T1"
    assert current["supported_count"] == 1
    assert current["capabilities"]["tool_events"]["status"] == "observed"


def test_observe_session_compact_maps_to_two_capabilities(brain_home):
    """`session_compact` is real evidence for BOTH session_events and
    compaction_events -- one kind may evidence more than one capability
    when genuinely supported."""
    harness_id = "codex"
    marked = capabilities.observe(brain_home, harness_id, "session_compact")
    assert set(marked) == {"session_events", "compaction_events"}
    state = capabilities.list_capabilities(brain_home, harness_id)
    assert state["session_events"]["supported"] is True
    assert state["compaction_events"]["supported"] is True


def test_observe_is_idempotent_upsert(brain_home):
    """Re-observing the same evidence never errors; it refreshes
    observed_at/evidence_json and keeps supported=true."""
    harness_id = "hermes"
    capabilities.observe(brain_home, harness_id, "assistant_usage")
    first = capabilities.list_capabilities(brain_home, harness_id)["usage_telemetry"]
    capabilities.observe(brain_home, harness_id, "assistant_usage")
    second = capabilities.list_capabilities(brain_home, harness_id)["usage_telemetry"]
    assert first["supported"] is True
    assert second["supported"] is True
    assert second["evidence"]["event_kind"] == "assistant_usage"


def test_feature_degrades_to_lower_tier_behavior(brain_home):
    """Bound observations authorize behavior; denial removes that authority."""
    harness_id = "antigravity"
    host_version = "1.0"
    config_binding = "config-a"
    assert (
        capabilities.tier_behavior(
            brain_home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
        == capabilities.TIER_BEHAVIOR["T0"]
    )

    capabilities.observe(
        brain_home,
        harness_id,
        "tool_call",
        version=host_version,
        config_binding=config_binding,
    )
    capabilities.observe(
        brain_home,
        harness_id,
        "omp_worker_context_handoff",
        version=host_version,
        config_binding=config_binding,
    )
    assert (
        capabilities.tier_behavior(
            brain_home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
        == capabilities.TIER_BEHAVIOR["T2"]
    )

    # Explicit denial on the T2-trigger capability degrades caller-visible
    # behavior to T1 (tool_events remains observed for this host).
    capabilities.declare(brain_home, harness_id, "subagents", False)
    assert (
        capabilities.tier_behavior(
            brain_home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
        == capabilities.TIER_BEHAVIOR["T1"]
    )
    assert capabilities.list_capabilities(brain_home, harness_id)["subagents"]["supported"] is False

    # Removing the remaining T1-trigger capability degrades to the T0 floor.
    capabilities.declare(brain_home, harness_id, "tool_events", False)
    assert (
        capabilities.tier_behavior(
            brain_home,
            harness_id,
            host_version=host_version,
            config_binding=config_binding,
        )
        == capabilities.TIER_BEHAVIOR["T0"]
    )


def test_unknown_capability_never_assumed(brain_home):
    """An unmapped event_kind is a deterministic no-op; declare() rejects
    an invalid capability name deterministically; a never-recorded
    capability reads back unsupported/unknown, never silently true."""
    harness_id = "no-evidence-harness"

    marked = capabilities.observe(brain_home, harness_id, "context_paging")
    assert marked == ()
    state = capabilities.list_capabilities(brain_home, harness_id)
    assert all(row["supported"] is None for row in state.values())

    with pytest.raises(capabilities.UnknownCapabilityError):
        capabilities.declare(brain_home, harness_id, "not_a_real_capability", True)

    # Table is still empty for this harness after the rejected declare().
    state_after = capabilities.list_capabilities(brain_home, harness_id)
    assert all(row["supported"] is None for row in state_after.values())

    # A never-recorded capability on a DIFFERENT, otherwise-populated
    # harness also reads back unsupported/unknown, never true.
    capabilities.declare(brain_home, "populated-harness", "session_events", True)
    other_state = capabilities.list_capabilities(brain_home, "populated-harness")
    assert other_state["budget_enforcement"]["supported"] is None


def test_declare_rejects_non_bool_supported(brain_home):
    """No truthy-string coercion -- `supported` must be an actual bool."""
    with pytest.raises(TypeError):
        capabilities.declare(brain_home, "h", "session_events", json.loads('"true"'))


def test_declare_persists_explicit_false_distinct_from_never_recorded(brain_home):
    capabilities.declare(brain_home, "h", "budget_enforcement", False, version="1.0")
    row = capabilities.list_capabilities(brain_home, "h")["budget_enforcement"]
    assert row["supported"] is False
    assert row["version"] == "1.0"
    # Distinct from a capability never declared/observed at all:
    assert capabilities.list_capabilities(brain_home, "h")["model_rewrite"]["supported"] is None


def test_cli_v2_harness_capabilities_json_output_shape(brain_home, capsys):
    from second_brain import cli

    capabilities.declare(brain_home, "cli-harness", "subagents", True, version="2.0")
    capabilities.observe(
        brain_home,
        "cli-harness",
        "tool_call",
        version="2.0",
        config_binding="cli-config",
    )
    capabilities.observe(
        brain_home,
        "cli-harness",
        "omp_worker_context_handoff",
        version="2.0",
        config_binding="cli-config",
    )

    assert (
        cli.main(
            [
                "--home",
                str(brain_home),
                "v2",
                "harness",
                "capabilities",
                "cli-harness",
                "--host-version",
                "2.0",
                "--config-binding",
                "cli-config",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["harness_id"] == "cli-harness"
    assert payload["tier"] == "T2"
    assert payload["tier_behavior"] == capabilities.TIER_BEHAVIOR["T2"]
    assert set(payload["capabilities"]) == capabilities.KNOWN_CAPABILITIES
    assert payload["capabilities"]["subagents"]["supported"] is True
    assert payload["capabilities"]["subagents"]["status"] == "observed"
    assert payload["capabilities"]["subagents"]["version"] == "2.0"

    # Read-only: no DB mutation beyond the earlier declare/observe calls.
    before = capabilities.list_capabilities(brain_home, "cli-harness")
    cli.main(
        [
            "--home",
            str(brain_home),
            "v2",
            "harness",
            "capabilities",
            "cli-harness",
            "--host-version",
            "2.0",
            "--config-binding",
            "cli-config",
        ]
    )
    after = capabilities.list_capabilities(brain_home, "cli-harness")
    assert before == after
