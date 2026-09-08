"""Tests for the Token Governor module."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import governor


def _rec(kind: str, **kw) -> dict:
    """Create a telemetry record with defaults."""
    rec = {
        "v": 2,
        "ts": "2026-08-18T10:00:00.000Z",
        "kind": kind,
        "session": "test_session",
    }
    rec.update(kw)
    return rec


def _write_session(home: Path, session_id: str, records: list[dict]) -> None:
    """Write telemetry records to a session file."""
    tel_dir = home / "telemetry" / "agent-performance"
    tel_dir.mkdir(parents=True, exist_ok=True)

    session_file = tel_dir / f"{session_id}.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _write_ledger_session(
    home: Path,
    host_session_id: str,
    *,
    project_id: str,
    root_parent_session_id: str | None = None,
) -> Path:
    """Create one production-shaped session identity and return its ledger."""
    from second_brain import contracts, ledger

    with ledger.LedgerStore(home, host_session_id, host="prime").open(create=True) as store:
        store.create_session(
            contracts.BrainSessionIdentity(
                internal_session_id=ledger.internal_session_id(host_session_id),
                host="prime",
                host_session_id=host_session_id,
                project_id=project_id,
                created_at="2026-08-18T10:00:00.000Z",
                status="active",
                pinned=False,
                schema_version=ledger.LEDGER_SCHEMA_VERSION,
                root_parent_session_id=root_parent_session_id,
            )
        )
        return store.dbfile


class TestSessionTokensBasic:
    """Basic SessionTokens parsing tests."""

    def test_empty_session(self, brain_home):
        """Parsing an empty session file."""
        _write_session(brain_home, "empty", [])
        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "empty.jsonl"
        )
        assert tokens.session_id == "empty"
        assert tokens.model_turns == 0
        assert tokens.total_tokens == 0

    def test_basic_usage(self, brain_home):
        """Parse a session with basic assistant_usage."""
        records = [
            _rec("session_start", model="gpt-4"),
            _rec("assistant_usage", input_tokens=100, output_tokens=50, total_tokens=150),
            _rec("session_shutdown"),
        ]
        _write_session(brain_home, "basic", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "basic.jsonl"
        )

        assert tokens.session_id == "basic"
        assert tokens.input_tokens == 100
        assert tokens.output_tokens == 50
        assert tokens.total_tokens == 150
        assert tokens.model_turns == 1
        assert tokens.model == "gpt-4"

    def test_model_invocation_completed_preserves_null_cache_write(self, brain_home):
        records = [
            _rec(
                "model_invocation_completed",
                usage={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_tokens": 3,
                    "cache_write_tokens": None,
                },
            )
        ]
        _write_session(brain_home, "hermes", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "hermes.jsonl"
        )

        assert tokens.input_tokens == 10
        assert tokens.output_tokens == 5
        assert tokens.cache_read_tokens == 3
        assert tokens.cache_write_tokens is None
        assert tokens.source_kind == "model_invocation_completed"

    def test_honesty_missing_cost(self, brain_home):
        """HONESTY RULE: absent cost_total reported as None, not 0."""
        records = [
            _rec("session_start"),
            _rec("assistant_usage", input_tokens=100, output_tokens=50, total_tokens=150),
            # Note: no cost_total field
        ]
        _write_session(brain_home, "no_cost", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "no_cost.jsonl"
        )

        assert tokens.cost_total is None
        assert tokens.cost_total_seen == 0

    def test_honesty_partial_cost(self, brain_home):
        """Track how many records had cost_total (HONESTY RULE)."""
        records = [
            _rec("session_start"),
            _rec(
                "assistant_usage",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                cost_total=0.01,
            ),
            _rec("assistant_usage", input_tokens=50, output_tokens=30, total_tokens=80),  # no cost
            _rec(
                "assistant_usage",
                input_tokens=75,
                output_tokens=40,
                total_tokens=115,
                cost_total=0.015,
            ),
        ]
        _write_session(brain_home, "partial_cost", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "partial_cost.jsonl"
        )

        assert tokens.cost_total == pytest.approx(0.025)
        assert tokens.cost_total_seen == 2
        assert tokens.model_turns == 3


class TestDerivedMetrics:
    """Tests for derived metrics calculation."""

    def test_context_peak(self, brain_home):
        """Extract context peak from turn_end.context_usage.percent."""
        records = [
            _rec("session_start"),
            _rec("turn_end", turn=0, context_usage={"percent": 42.5}),
            _rec("turn_end", turn=1, context_usage={"percent": 91.3}),
            _rec("turn_end", turn=2, context_usage={"percent": 65.0}),
        ]
        _write_session(brain_home, "ctx_peak", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "ctx_peak.jsonl"
        )

        assert tokens.context_peak == 91  # Should be int(91.3)

    def test_tool_bytes(self, brain_home):
        """Track tool input/output bytes."""
        records = [
            _rec("session_start"),
            _rec("tool_call", tool="bash", input_bytes=100),
            _rec("tool_result", tool="bash", output_bytes=500),
            _rec("tool_call", tool="bash", input_bytes=50),
            _rec("tool_result", tool="bash", output_bytes=1000, is_error=True),
        ]
        _write_session(brain_home, "tool_bytes", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "tool_bytes.jsonl"
        )

        assert tokens.tool_calls == 2
        assert tokens.tool_input_bytes == 150
        assert tokens.tool_output_bytes == 1500

    def test_brain_injection(self, brain_home):
        """Track brain_injected_tokens from brain_packet_delivered."""
        records = [
            _rec("session_start"),
            _rec("brain_packet_delivered", packet_tokens=100, model_visible=True),
            _rec("brain_packet_delivered", packet_tokens=50, model_visible=False),  # shadow
            _rec("brain_packet_delivered", packet_tokens=75, model_visible=True),
        ]
        _write_session(brain_home, "brain_inject", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "brain_inject.jsonl"
        )

        assert tokens.brain_injected_tokens == 175  # 100 + 75
        assert tokens.brain_packets_delivered == 2
        assert tokens.brain_packets_shadow == 1

    def test_autoinject_cache_hit_rate(self, brain_home):
        """Compute autoinject cache hit rate."""
        records = [
            _rec("session_start"),
            _rec("autoinject_shadow_decision", cache_hit=True),
            _rec("autoinject_shadow_decision", cache_hit=True),
            _rec("autoinject_shadow_decision", cache_hit=False),
        ]
        _write_session(brain_home, "cache_rate", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "cache_rate.jsonl"
        )

        assert tokens.autoinject_cache_hits == 2
        assert tokens.autoinject_cache_misses == 1
        assert tokens.autoinject_cache_hit_rate == pytest.approx(2.0 / 3.0)

    def test_compaction_count(self, brain_home):
        """Track compaction events."""
        records = [
            _rec("session_start"),
            _rec("session_compact", from_extension=False),
            _rec("session_compact", from_extension=True),
        ]
        _write_session(brain_home, "compactions", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "compactions.jsonl"
        )

        assert tokens.compactions == 2


class TestRoleAttribution:
    """Tests for role attribution (driver vs worker)."""

    def test_driver_vs_worker(self, brain_home):
        """Attribute tokens by role."""
        _write_session(
            brain_home,
            "driver",
            [
                _rec("session_start", role="driver"),
                _rec("assistant_usage", input_tokens=100, output_tokens=50, total_tokens=150),
            ],
        )
        _write_session(
            brain_home,
            "worker",
            [
                _rec("session_start", role="worker"),
                _rec("assistant_usage", input_tokens=200, output_tokens=100, total_tokens=300),
            ],
        )

        sessions = governor.parse_telemetry(brain_home)
        attribution = governor.attribute_roles(sessions)

        assert attribution["driver_turns"] == 1
        assert attribution["driver_input_tokens"] == 100
        assert attribution["worker_turns"] == 1
        assert attribution["worker_input_tokens"] == 200

    def test_role_attribution_handles_explicit_null_counters(self, brain_home):
        _write_session(
            brain_home,
            "driver-null",
            [
                _rec("session_start", role="driver"),
                _rec(
                    "assistant_usage",
                    input_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                ),
            ],
        )

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "driver-null.jsonl"
        )
        attribution = governor.attribute_roles([tokens])

        assert tokens.input_tokens is None
        assert tokens.output_tokens is None
        assert tokens.total_tokens is None
        assert tokens.driver_tokens == 0
        assert attribution["driver_turns"] == 1
        assert attribution["driver_input_tokens"] == 0
        assert attribution["driver_output_tokens"] == 0
        assert attribution["driver_total_tokens"] == 0


class TestFeatureFlags:
    """Tests for feature flag resolution."""

    def test_default_flags(self, brain_home):
        """All features default to True."""
        flags = governor.resolve_features(brain_home)

        assert flags["brain_core"] is True
        assert flags["autoinject"] is True
        assert flags["semantic_vectors"] is True
        assert len(flags) == 11  # 11 feature flags

    def test_config_override(self, brain_home, tmp_path):
        """Config file overrides defaults."""
        config_dir = brain_home / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_file = config_dir / "governor.toml"
        config_file.write_text("[features]\nautoinject = false\nsemantic_vectors = false\n")

        flags = governor.resolve_features(brain_home)

        assert flags["autoinject"] is False
        assert flags["semantic_vectors"] is False
        assert flags["brain_core"] is True  # unchanged

    def test_env_override(self, brain_home):
        """Environment variables override config/defaults."""
        env = {
            "SECOND_BRAIN_GOVERNOR_AUTOINJECT": "0",
            "SECOND_BRAIN_GOVERNOR_ACTION_CACHE": "1",
        }

        flags = governor.resolve_features(brain_home, env=env)

        assert flags["autoinject"] is False
        assert flags["action_cache"] is True

    def test_unknown_flag_error(self, brain_home):
        """Unknown flags in config raise ValueError."""
        config_dir = brain_home / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_file = config_dir / "governor.toml"
        config_file.write_text("[features]\nunknown_feature = false\n")

        with pytest.raises(ValueError, match="Unknown feature flag"):
            governor.resolve_features(brain_home)

    def test_feature_source_env(self, brain_home):
        """Identify which layer set a flag (env)."""
        env = {"SECOND_BRAIN_GOVERNOR_AUTOINJECT": "0"}
        governor.resolve_features(brain_home, env=env)

        source = governor.feature_source("autoinject", brain_home, env=env)
        assert source == "env"

    def test_feature_source_config(self, brain_home):
        """Identify which layer set a flag (config)."""
        config_dir = brain_home / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_file = config_dir / "governor.toml"
        config_file.write_text("[features]\nautoinject = false\n")

        source = governor.feature_source("autoinject", brain_home, env={})
        assert source == "config"

    def test_feature_source_default(self, brain_home):
        """Identify which layer set a flag (default)."""
        source = governor.feature_source("autoinject", brain_home, env={})
        assert source == "default"


class TestROIClassification:
    """Tests for ROI classification."""

    def test_positive_roi(self, brain_home):
        """Brain ON uses fewer tokens than Brain OFF."""
        on_records = [
            [
                _rec(
                    "assistant_usage",
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    cost_total=0.01,
                )
            ],
            [
                _rec(
                    "assistant_usage",
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    cost_total=0.01,
                )
            ],
            [
                _rec(
                    "assistant_usage",
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    cost_total=0.01,
                )
            ],
        ]
        off_records = [
            [
                _rec(
                    "assistant_usage",
                    input_tokens=200,
                    output_tokens=100,
                    total_tokens=300,
                    cost_total=0.02,
                )
            ],
            [
                _rec(
                    "assistant_usage",
                    input_tokens=200,
                    output_tokens=100,
                    total_tokens=300,
                    cost_total=0.02,
                )
            ],
            [
                _rec(
                    "assistant_usage",
                    input_tokens=200,
                    output_tokens=100,
                    total_tokens=300,
                    cost_total=0.02,
                )
            ],
        ]

        for i, recs in enumerate(on_records):
            _write_session(brain_home, f"on_{i}", recs)
        for i, recs in enumerate(off_records):
            _write_session(brain_home, f"off_{i}", recs)

        tel_path = brain_home / "telemetry" / "agent-performance"
        on = [governor.parse_telemetry_session(tel_path / f"on_{i}.jsonl") for i in range(3)]
        off = [governor.parse_telemetry_session(tel_path / f"off_{i}.jsonl") for i in range(3)]

        verdict = governor.classify_roi(on, off)

        assert verdict.status == "POSITIVE_ROI"
        assert verdict.on_tokens == pytest.approx(0.03)
        assert verdict.off_tokens == pytest.approx(0.06)

    def test_negative_roi(self, brain_home):
        """Brain ON uses more tokens than Brain OFF."""
        on = []
        off = []

        for i in range(3):
            _write_session(
                brain_home,
                f"on_neg_{i}",
                [_rec("assistant_usage", input_tokens=200, output_tokens=100, cost_total=0.02)],
            )
            on.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"on_neg_{i}.jsonl"
                )
            )

        for i in range(3):
            _write_session(
                brain_home,
                f"off_neg_{i}",
                [_rec("assistant_usage", input_tokens=100, output_tokens=50, cost_total=0.01)],
            )
            off.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"off_neg_{i}.jsonl"
                )
            )

        verdict = governor.classify_roi(on, off)

        assert verdict.status == "NEGATIVE_ROI"

    def test_neutral_roi(self, brain_home):
        """Brain ON cost within neutral band of Brain OFF."""
        on = []
        off = []

        for i in range(3):
            _write_session(
                brain_home,
                f"on_neut_{i}",
                [
                    _rec(
                        "assistant_usage",
                        input_tokens=100,
                        output_tokens=50,
                        cost_total=0.0102,  # +2%
                    )
                ],
            )
            on.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"on_neut_{i}.jsonl"
                )
            )

        for i in range(3):
            _write_session(
                brain_home,
                f"off_neut_{i}",
                [_rec("assistant_usage", input_tokens=100, output_tokens=50, cost_total=0.01)],
            )
            off.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"off_neut_{i}.jsonl"
                )
            )

        verdict = governor.classify_roi(on, off, neutral_band=0.02)

        assert verdict.status == "NEUTRAL"

    def test_insufficient_evidence_min_sessions(self, brain_home):
        """Insufficient sessions (below min_sessions)."""
        on = []
        for i in range(2):  # Only 2, need 3
            _write_session(
                brain_home,
                f"on_tiny_{i}",
                [_rec("assistant_usage", input_tokens=100, cost_total=0.01)],
            )
            on.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"on_tiny_{i}.jsonl"
                )
            )

        off = []
        for i in range(3):
            _write_session(
                brain_home,
                f"off_tiny_{i}",
                [_rec("assistant_usage", input_tokens=100, cost_total=0.01)],
            )
            off.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"off_tiny_{i}.jsonl"
                )
            )

        verdict = governor.classify_roi(on, off)

        assert verdict.status == "INSUFFICIENT_EVIDENCE"
        assert "on_sessions" in verdict.reason or "min" in verdict.reason

    def test_insufficient_evidence_missing_cost(self, brain_home):
        """HONESTY: missing cost_total makes verdict INSUFFICIENT_EVIDENCE."""
        on = []
        for i in range(3):
            _write_session(
                brain_home,
                f"on_no_cost_{i}",
                [
                    _rec("assistant_usage", input_tokens=100)  # no cost_total
                ],
            )
            on.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"on_no_cost_{i}.jsonl"
                )
            )

        off = []
        for i in range(3):
            _write_session(
                brain_home,
                f"off_no_cost_{i}",
                [_rec("assistant_usage", input_tokens=100, cost_total=0.01)],
            )
            off.append(
                governor.parse_telemetry_session(
                    brain_home / "telemetry" / "agent-performance" / f"off_no_cost_{i}.jsonl"
                )
            )

        verdict = governor.classify_roi(on, off)

        assert verdict.status == "INSUFFICIENT_EVIDENCE"
        assert "cost_total" in verdict.reason


class TestCLI:
    """Tests for CLI commands."""

    def test_governor_report_json(self, brain_home):
        """CLI: brainctl governor report --json."""
        _write_session(
            brain_home,
            "cli_test",
            [
                _rec("session_start", model="test-model"),
                _rec("assistant_usage", input_tokens=100, output_tokens=50, total_tokens=150),
            ],
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "governor",
                "report",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert isinstance(output, list)
        assert len(output) >= 1
        assert "session_id" in output[0]
        assert "input_tokens" in output[0]

    def test_governor_flags_json(self, brain_home):
        """CLI: brainctl governor flags --json."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "governor",
                "flags",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert isinstance(output, dict)
        assert "autoinject" in output
        assert "value" in output["autoinject"]
        assert "source" in output["autoinject"]

    def test_governor_profiles_json(self, brain_home):
        """CLI: brainctl governor profiles --json."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "governor",
                "profiles",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert result.returncode == 0
        profiles = json.loads(result.stdout)
        assert "A_BRAIN_OFF" in profiles
        assert "I_FULL_V1" in profiles
        assert profiles["A_BRAIN_OFF"]["autoinject"] is False
        assert profiles["I_FULL_V1"]["autoinject"] is True

    def test_governor_profile_get_json(self, brain_home):
        """CLI: brainctl governor profile <name> --json."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "governor",
                "profile",
                "A_BRAIN_OFF",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert result.returncode == 0
        profile = json.loads(result.stdout)
        assert profile["brain_core"] is False
        assert profile["autoinject"] is False

    def test_governor_profile_get_env(self, brain_home):
        """CLI: brainctl governor profile <name> --env."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "governor",
                "profile",
                "I_FULL_V1",
                "--env",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert result.returncode == 0
        assert "SECOND_BRAIN_GOVERNOR_AUTOINJECT=1" in result.stdout


class TestExtendedSection41Metrics:
    """Tests for all section 4.1 token tracking fields."""

    def test_section_41_all_fields_populated(self, brain_home):
        """Verify all §4.1 telemetry fields are properly aggregated."""
        records = [
            _rec("session_start", role="driver", model="deepseek-v4-pro"),
            _rec(
                "assistant_usage",
                provider="deepseek",
                model="deepseek-v4-pro",
                input_tokens=1000,
                output_tokens=200,
                cache_read_tokens=800,
                cache_write_tokens=100,
                total_tokens=1200,
                context_window=128000,
                compaction_tokens=150,
                cost_total=0.005,
            ),
            _rec("tool_call", tool="search", input_bytes=64),
            _rec(
                "tool_result",
                tool="search",
                output_bytes=2048,
                raw_bytes=4096,
                model_visible_bytes=512,
            ),
            _rec(
                "brain_packet_delivered",
                packet_tokens=80,
                retrieval_tokens=40,
                generated_tokens=20,
                model_visible=True,
            ),
            _rec("action_cache", hit=True, model_calls_avoided=1),
            _rec("action_cache", hit=False),
            _rec("session_vmem", page_fault=True),
            _rec("session_vmem", evicted=True),
            _rec("delta_sync", repeated_read_avoided=True),
            _rec("turn_end", turn=0, context_usage={"percent": 45.0}),
            _rec("session_compact", compaction_tokens=100),
        ]
        _write_session(brain_home, "sec41_session", records)

        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "sec41_session.jsonl"
        )

        # Provider / model / role
        assert tokens.provider == "deepseek"
        assert tokens.model == "deepseek-v4-pro"
        assert tokens.role == "driver"

        # Core tokens
        assert tokens.input_tokens == 1000
        assert tokens.output_tokens == 200
        assert tokens.cache_read_tokens == 800
        assert tokens.cache_write_tokens == 100
        assert tokens.total_tokens == 1200
        assert tokens.cost_total == pytest.approx(0.005)
        assert tokens.cost_total_seen == 1
        assert tokens.context_window == 128000
        assert tokens.context_peak == 45
        assert tokens.driver_tokens == 1200
        assert tokens.worker_tokens == 0

        # Tool bytes
        assert tokens.tool_calls == 1
        assert tokens.tool_input_bytes == 64
        assert tokens.tool_output_bytes == 2048
        assert tokens.tool_output_raw_bytes == 4096
        assert tokens.tool_output_model_visible_bytes == 512

        # Brain tokens
        assert tokens.brain_injected_tokens == 80
        assert tokens.retrieval_result_tokens == 40
        assert tokens.brain_generated_tokens == 20
        assert tokens.brain_packets_delivered == 1

        # Optimization & cache counters
        assert tokens.action_cache_hits == 1
        assert tokens.action_cache_misses == 1
        assert tokens.model_calls_avoided == 1
        assert tokens.session_page_faults == 1
        assert tokens.session_evictions == 1
        assert tokens.repeated_reads_avoided == 1

        # Compactions (150 from assistant_usage + 100 from session_compact)
        assert tokens.compactions == 1
        assert tokens.compaction_tokens == 250


class TestAblationProfiles:
    """Tests for ablation profiles (§4.2, §24.2)."""

    def test_all_predefined_profiles_exist(self):
        """All profiles A through I from §24.2 exist."""
        expected = [
            "A_BRAIN_OFF",
            "B_BASIC_BRAIN",
            "C_OBSERVATION_FIREWALL",
            "D_CONTEXT_PAGING",
            "E_ACTION_CACHE",
            "F_DELTA_SYNC",
            "G_HYBRID_RETRIEVAL",
            "H_TOOL_WORKING_SET",
            "I_FULL_V1",
        ]
        for name in expected:
            profile = governor.get_ablation_profile(name)
            assert isinstance(profile, dict)
            assert len(profile) == 11

    def test_brain_off_profile_all_disabled(self):
        """A_BRAIN_OFF has every feature set to False."""
        profile = governor.get_ablation_profile("A_BRAIN_OFF")
        assert all(v is False for v in profile.values())

    def test_full_v1_profile_all_enabled(self):
        """I_FULL_V1 has every feature set to True."""
        profile = governor.get_ablation_profile("I_FULL_V1")
        assert all(v is True for v in profile.values())

    def test_profile_env_generation(self):
        """get_profile_env generates SECOND_BRAIN_GOVERNOR_<KEY>=0/1."""
        env = governor.get_profile_env("A_BRAIN_OFF")
        assert env["SECOND_BRAIN_GOVERNOR_BRAIN_CORE"] == "0"
        assert env["SECOND_BRAIN_GOVERNOR_AUTOINJECT"] == "0"

        env_full = governor.get_profile_env("I_FULL_V1")
        assert env_full["SECOND_BRAIN_GOVERNOR_BRAIN_CORE"] == "1"
        assert env_full["SECOND_BRAIN_GOVERNOR_AUTOINJECT"] == "1"

    def test_unknown_profile_raises_key_error(self):
        """Invalid profile name raises KeyError."""
        with pytest.raises(KeyError, match="Unknown ablation profile"):
            governor.get_ablation_profile("NONEXISTENT_PROFILE")


class TestCacheEpochAttribution:
    """Tests for T2.5 cache-epoch cause attribution (governor.SessionTokens.cache_epochs)."""

    def test_cache_epoch_cause_attribution(self, brain_home):
        """Covers all 5 named cause-attribution scenarios from the T2.5 brief."""
        # Scenario: system_prefix_sha changes between two cache-write turns -> brain_prefix.
        # The first epoch in any session has no prior baseline -> unknown (scenario 5).
        records = [
            _rec("turn_start", turn=1),
            _rec("provider_request_meta", system_prefix_sha="p1", tool_surface_sha="t1"),
            _rec("assistant_usage", cache_write_tokens=100),
            _rec("turn_start", turn=2),
            _rec("provider_request_meta", system_prefix_sha="p2", tool_surface_sha="t1"),
            _rec("assistant_usage", cache_write_tokens=50),
        ]
        _write_session(brain_home, "prefix_change", records)
        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "prefix_change.jsonl"
        )
        assert tokens.cache_epochs == [
            {"turn": 1, "cause": "unknown", "write_tokens": 100},
            {"turn": 2, "cause": "brain_prefix", "write_tokens": 50},
        ]

        # Scenario: only tool_surface_sha changes -> tool_surface.
        records = [
            _rec("turn_start", turn=1),
            _rec("provider_request_meta", system_prefix_sha="p1", tool_surface_sha="t1"),
            _rec("assistant_usage", cache_write_tokens=100),
            _rec("turn_start", turn=2),
            _rec("provider_request_meta", system_prefix_sha="p1", tool_surface_sha="t2"),
            _rec("assistant_usage", cache_write_tokens=50),
        ]
        _write_session(brain_home, "tool_surface_change", records)
        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "tool_surface_change.jsonl"
        )
        assert tokens.cache_epochs[1] == {"turn": 2, "cause": "tool_surface", "write_tokens": 50}

        # Scenario: neither sha changes between two cache-write turns -> harness.
        records = [
            _rec("turn_start", turn=1),
            _rec("provider_request_meta", system_prefix_sha="p1", tool_surface_sha="t1"),
            _rec("assistant_usage", cache_write_tokens=100),
            _rec("turn_start", turn=2),
            _rec("provider_request_meta", system_prefix_sha="p1", tool_surface_sha="t1"),
            _rec("assistant_usage", cache_write_tokens=50),
        ]
        _write_session(brain_home, "no_change", records)
        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "no_change.jsonl"
        )
        assert tokens.cache_epochs[1] == {"turn": 2, "cause": "harness", "write_tokens": 50}

        # Scenario: cache writes with no provider_request_meta at all (Claude Code path) -> unknown.
        records = [
            _rec("turn_start", turn=1),
            _rec("assistant_usage", cache_write_tokens=100),
        ]
        _write_session(brain_home, "no_provider_meta", records)
        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "no_provider_meta.jsonl"
        )
        assert tokens.cache_epochs == [{"turn": 1, "cause": "unknown", "write_tokens": 100}]

    def test_cache_epoch_excludes_zero_and_absent_write_turns(self, brain_home):
        """Turns with cache_write_tokens == 0 or absent are not included in cache_epochs."""
        records = [
            _rec("turn_start", turn=1),
            _rec("provider_request_meta", system_prefix_sha="p1", tool_surface_sha="t1"),
            _rec("assistant_usage", cache_write_tokens=0),
            _rec("turn_start", turn=2),
            _rec("provider_request_meta", system_prefix_sha="p1", tool_surface_sha="t1"),
            _rec("assistant_usage", input_tokens=10),  # cache_write_tokens absent
        ]
        _write_session(brain_home, "zero_writes", records)
        tokens = governor.parse_telemetry_session(
            brain_home / "telemetry" / "agent-performance" / "zero_writes.jsonl"
        )
        assert tokens.cache_epochs == []


class TestCheckBudget:
    """T3.1 hard/soft budget caps: governor.check_budget."""

    def test_ok_below_soft_threshold(self, brain_home):
        """Usage below cap * soft_ratio is OK."""
        records = [
            _rec(
                "assistant_usage",
                session="budget-ok",
                input_tokens=100,
                output_tokens=100,
                total_tokens=200,
            )
        ]
        _write_session(brain_home, "budget-ok", records)
        result = governor.check_budget(brain_home, "budget-ok", "driver")
        assert result == {"state": "OK", "used": 200, "cap": 400000}

    def test_soft_cap_at_boundary(self, brain_home):
        """Usage exactly at cap * soft_ratio is SOFT (>= boundary)."""
        # worker cap defaults to 120000; soft_ratio 0.8 -> soft threshold 96000.
        records = [_rec("assistant_usage", session="budget-soft", total_tokens=96000)]
        _write_session(brain_home, "budget-soft", records)
        result = governor.check_budget(brain_home, "budget-soft", "worker")
        assert result == {"state": "SOFT", "used": 96000, "cap": 120000}

    def test_soft_cap_just_below_boundary_is_ok(self, brain_home):
        """One token below the soft threshold stays OK."""
        records = [
            _rec(
                "assistant_usage",
                session="budget-soft-under",
                total_tokens=95999,
            )
        ]
        _write_session(brain_home, "budget-soft-under", records)
        result = governor.check_budget(brain_home, "budget-soft-under", "worker")
        assert result["state"] == "OK"

    def test_hard_cap_at_boundary(self, brain_home):
        """Usage exactly at cap is HARD (>= boundary)."""
        records = [_rec("assistant_usage", session="budget-hard", total_tokens=120000)]
        _write_session(brain_home, "budget-hard", records)
        result = governor.check_budget(brain_home, "budget-hard", "worker")
        assert result == {"state": "HARD", "used": 120000, "cap": 120000}

    def test_worker_role_uses_worker_cap(self, brain_home):
        """role == 'worker' caps at worker_tokens, not session_tokens."""
        result = governor.check_budget(brain_home, "no-telemetry-worker", "worker")
        assert result["cap"] == 120000

    def test_non_worker_role_uses_session_cap(self, brain_home):
        """Any non-'worker' role caps at session_tokens."""
        result = governor.check_budget(brain_home, "no-telemetry-driver", "driver")
        assert result["cap"] == 400000

    def test_missing_telemetry_fails_open_without_factual_zero(self, brain_home):
        """Unavailable accounting is explicit while the governor remains fail-open."""
        result = governor.check_budget(brain_home, "never-existed", "driver")
        assert result == {
            "state": "OK",
            "used": None,
            "cap": 400000,
            "error": "ACCOUNTING_UNAVAILABLE",
        }

    @pytest.mark.parametrize("identity", ["missing", "null"])
    def test_usage_without_session_identity_is_accounting_unavailable(self, brain_home, identity):
        """Malformed usage cannot become factual cap consumption."""
        record = _rec("assistant_usage", total_tokens=500000)
        if identity == "missing":
            del record["session"]
        else:
            record["session"] = None
        _write_session(brain_home, f"{identity}-usage-session", [record])

        assert governor.check_budget(brain_home, f"{identity}-usage-session", "driver") == {
            "state": "OK",
            "used": None,
            "cap": 400000,
            "error": "ACCOUNTING_UNAVAILABLE",
        }

    def test_malformed_config_falls_back_to_defaults(self, brain_home):
        """Malformed governor.toml never raises; defaults apply."""
        (brain_home / "config" / "governor.toml").write_text("not valid toml [[[", encoding="utf-8")
        result = governor.check_budget(brain_home, "malformed-cfg", "worker")
        assert result["cap"] == 120000

    def test_custom_budget_config_overrides_defaults(self, brain_home):
        """[budgets] in governor.toml overrides the hardcoded defaults."""
        (brain_home / "config" / "governor.toml").write_text(
            "[budgets]\nsession_tokens = 1000\nworker_tokens = 500\nsoft_ratio = 0.5\n",
            encoding="utf-8",
        )
        records = [_rec("assistant_usage", session="budget-custom", total_tokens=500)]
        _write_session(brain_home, "budget-custom", records)
        result = governor.check_budget(brain_home, "budget-custom", "driver")
        assert result == {"state": "SOFT", "used": 500, "cap": 1000}

    def test_descendant_usage_counts_toward_parent(self, brain_home):
        """A worker session rooted at the parent contributes its total_tokens
        to the parent's `used` via the parent's root_parent_session_id link
        in the descendant's own ledger.sqlite `sessions` row."""
        from second_brain import contracts, ledger

        parent_host_id = "parent-session-descendant-test"
        child_host_id = "child-worker-session-descendant-test"
        parent_internal = ledger.internal_session_id(parent_host_id)

        _write_session(
            brain_home,
            parent_host_id,
            [
                _rec(
                    "assistant_usage",
                    total_tokens=1000,
                    session=parent_host_id,
                )
            ],
        )
        _write_session(
            brain_home,
            child_host_id,
            [
                _rec(
                    "assistant_usage",
                    total_tokens=2500,
                    session=child_host_id,
                )
            ],
        )

        with ledger.LedgerStore(brain_home, child_host_id, host="hermes").open(
            create=True
        ) as store:
            store.create_session(
                contracts.BrainSessionIdentity(
                    internal_session_id=ledger.internal_session_id(child_host_id),
                    host="hermes",
                    host_session_id=child_host_id,
                    project_id="default",
                    created_at="2026-08-18T10:00:00.000Z",
                    status="active",
                    pinned=False,
                    schema_version=1,
                    root_parent_session_id=parent_internal,
                )
            )

        result = governor.check_budget(brain_home, parent_host_id, "driver")
        assert result["used"] == 3500  # 1000 (own) + 2500 (descendant)

    def test_unrelated_sibling_session_not_counted(self, brain_home):
        """A ledger session with a DIFFERENT root_parent_session_id must
        never leak into this parent's usage total."""
        from second_brain import contracts, ledger

        parent_host_id = "parent-session-unrelated-test"
        other_host_id = "other-unrelated-parent-test"
        stray_host_id = "stray-child-of-other-parent"

        _write_session(
            brain_home,
            parent_host_id,
            [_rec("assistant_usage", session=parent_host_id, total_tokens=10)],
        )
        _write_session(
            brain_home,
            stray_host_id,
            [_rec("assistant_usage", session=stray_host_id, total_tokens=99999)],
        )

        with ledger.LedgerStore(brain_home, stray_host_id, host="hermes").open(
            create=True
        ) as store:
            store.create_session(
                contracts.BrainSessionIdentity(
                    internal_session_id=ledger.internal_session_id(stray_host_id),
                    host="hermes",
                    host_session_id=stray_host_id,
                    project_id="default",
                    created_at="2026-08-18T10:00:00.000Z",
                    status="active",
                    pinned=False,
                    schema_version=1,
                    root_parent_session_id=ledger.internal_session_id(other_host_id),
                )
            )

        result = governor.check_budget(brain_home, parent_host_id, "driver")
        assert result["used"] == 10

    def test_independent_roots_nested_worker_duplicate_resume_and_old_home(self, brain_home):
        """A/B/C scope, nested A usage, duplicate rows, resume, and old history."""
        from second_brain import ledger

        (brain_home / "config" / "governor.toml").write_text(
            "[budgets]\nsession_tokens = 100\nworker_tokens = 40\nsoft_ratio = 0.8\n",
            encoding="utf-8",
        )
        root_a = "root-a"
        child_a = "root-a-child"
        nested_a = "root-a-nested-child"
        root_b = "root-b"
        root_c = "root-c"
        historical = "historical-high-usage-root"
        for session_id, total in (
            (root_a, 10),
            (child_a, 15),
            (nested_a, 40),
            (root_b, 5),
            (root_c, 90),
            (historical, 500),
        ):
            _write_session(
                brain_home,
                session_id,
                [_rec("assistant_usage", session=session_id, total_tokens=total)],
            )

        _write_ledger_session(brain_home, root_a, project_id="project-one")
        _write_ledger_session(brain_home, root_b, project_id="project-one")
        _write_ledger_session(brain_home, root_c, project_id="project-two")
        _write_ledger_session(brain_home, historical, project_id="project-one")
        root_a_internal = ledger.internal_session_id(root_a)
        _write_ledger_session(
            brain_home,
            child_a,
            project_id="project-one",
            root_parent_session_id=root_a_internal,
        )
        nested_db = _write_ledger_session(
            brain_home,
            nested_a,
            project_id="project-one",
            root_parent_session_id=root_a_internal,
        )

        duplicate_dir = brain_home / "state" / "sessions" / "duplicate-nested-row"
        duplicate_dir.mkdir(parents=True)
        shutil.copy2(nested_db, duplicate_dir / "ledger.sqlite")

        expected_a = {"state": "OK", "used": 65, "cap": 100}
        assert governor.check_budget(brain_home, root_a, "driver") == expected_a
        _write_ledger_session(brain_home, root_a, project_id="project-one")
        assert governor.check_budget(brain_home, root_a, "driver") == expected_a
        assert governor.check_budget(brain_home, root_b, "driver") == {
            "state": "OK",
            "used": 5,
            "cap": 100,
        }
        assert governor.check_budget(brain_home, root_c, "driver") == {
            "state": "SOFT",
            "used": 90,
            "cap": 100,
        }
        assert governor.check_budget(brain_home, nested_a, "worker") == {
            "state": "HARD",
            "used": 40,
            "cap": 40,
        }

    def test_raw_telemetry_identity_is_not_lost_to_sanitized_sidecar(self, brain_home):
        session_id = "worker.child"
        _write_session(
            brain_home,
            session_id,
            [_rec("assistant_usage", session=session_id, total_tokens=12)],
        )
        _write_session(
            brain_home,
            "worker-child",
            [
                _rec("session_start", session=session_id),
                _rec("assistant_usage", session=session_id, total_tokens=8),
            ],
        )

        assert governor.check_budget(brain_home, session_id, "worker") == {
            "state": "OK",
            "used": 20,
            "cap": 120000,
        }

    def test_malformed_telemetry_fails_open_with_diagnostic(self, brain_home):
        telemetry_dir = brain_home / "telemetry" / "agent-performance"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        (telemetry_dir / "malformed.jsonl").write_text("{not-json}\n", encoding="utf-8")

        assert governor.check_budget(brain_home, "malformed", "worker") == {
            "state": "OK",
            "used": None,
            "cap": 120000,
            "error": "ACCOUNTING_UNAVAILABLE",
        }

    def test_unreadable_ledger_fails_open_with_diagnostic(self, brain_home):
        _write_session(
            brain_home,
            "healthy-session",
            [_rec("assistant_usage", session="healthy-session", total_tokens=10)],
        )
        corrupt_dir = brain_home / "state" / "sessions" / "corrupt-ledger"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "ledger.sqlite").write_bytes(b"not sqlite")

        assert governor.check_budget(brain_home, "healthy-session", "driver") == {
            "state": "OK",
            "used": None,
            "cap": 400000,
            "error": "ACCOUNTING_UNAVAILABLE",
        }
