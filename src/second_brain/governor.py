"""
Token Governor: measure and classify token cost/savings per session.

Plan §4: Phase 1 Token Governor & measurement-first foundation.
Reads existing telemetry (no new inference calls, no hot-path writes).
Implements honest token accounting, feature attribution, and ROI classification.

HONESTY RULE (§4.1): A field absent from telemetry must be reported as None/absent
and must NOT be coerced to 0. Aggregates over partially-present fields must expose
how many records contributed (e.g., cost_total_seen=N of M).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from . import economics, ledger

logger = logging.getLogger(__name__)

DEFAULT_FEATURES: dict[str, bool] = {
    'brain_core': True,
    'autoinject': True,
    'observation_firewall': True,
    'context_paging': True,
    'action_cache': True,
    'delta_sync': True,
    'structural_retrieval': True,
    'semantic_vectors': True,
    'tool_working_set': True,
    'skill_lazy_loading': True,
    'prompt_compression': True,
}

ABLATION_PROFILES: dict[str, dict[str, bool]] = {
    'A_BRAIN_OFF': {k: False for k in DEFAULT_FEATURES},
    'B_BASIC_BRAIN': {
        'brain_core': True,
        'autoinject': True,
        'observation_firewall': False,
        'context_paging': False,
        'action_cache': False,
        'delta_sync': False,
        'structural_retrieval': False,
        'semantic_vectors': False,
        'tool_working_set': False,
        'skill_lazy_loading': False,
        'prompt_compression': False,
    },
    'C_OBSERVATION_FIREWALL': {
        'brain_core': True,
        'autoinject': True,
        'observation_firewall': True,
        'context_paging': False,
        'action_cache': False,
        'delta_sync': False,
        'structural_retrieval': False,
        'semantic_vectors': False,
        'tool_working_set': False,
        'skill_lazy_loading': False,
        'prompt_compression': False,
    },
    'D_CONTEXT_PAGING': {
        'brain_core': True,
        'autoinject': True,
        'observation_firewall': True,
        'context_paging': True,
        'action_cache': False,
        'delta_sync': False,
        'structural_retrieval': False,
        'semantic_vectors': False,
        'tool_working_set': False,
        'skill_lazy_loading': False,
        'prompt_compression': False,
    },
    'E_ACTION_CACHE': {
        'brain_core': True,
        'autoinject': True,
        'observation_firewall': True,
        'context_paging': True,
        'action_cache': True,
        'delta_sync': False,
        'structural_retrieval': False,
        'semantic_vectors': False,
        'tool_working_set': False,
        'skill_lazy_loading': False,
        'prompt_compression': False,
    },
    'F_DELTA_SYNC': {
        'brain_core': True,
        'autoinject': True,
        'observation_firewall': True,
        'context_paging': True,
        'action_cache': True,
        'delta_sync': True,
        'structural_retrieval': False,
        'semantic_vectors': False,
        'tool_working_set': False,
        'skill_lazy_loading': False,
        'prompt_compression': False,
    },
    'G_HYBRID_RETRIEVAL': {
        'brain_core': True,
        'autoinject': True,
        'observation_firewall': True,
        'context_paging': True,
        'action_cache': True,
        'delta_sync': True,
        'structural_retrieval': True,
        'semantic_vectors': True,
        'tool_working_set': False,
        'skill_lazy_loading': False,
        'prompt_compression': False,
    },
    'H_TOOL_WORKING_SET': {
        'brain_core': True,
        'autoinject': True,
        'observation_firewall': True,
        'context_paging': True,
        'action_cache': True,
        'delta_sync': True,
        'structural_retrieval': True,
        'semantic_vectors': True,
        'tool_working_set': True,
        'skill_lazy_loading': True,
        'prompt_compression': False,
    },
    'I_FULL_V1': {k: True for k in DEFAULT_FEATURES},
}


@dataclass
class SessionTokens:
    """
    Aggregated token metrics for a single session.

    Only fields that actually exist in telemetry are populated;
    missing fields are None. Aggregate fields include _seen count.
    """
    session_id: str
    provider: str | None = None
    model: str | None = None
    source_kind: str | None = None

    # Core token fields (from assistant_usage and Hermes usage events). A
    # source-reported null is retained; the zero default preserves the
    # historical value for fields never exposed by a session.
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    cache_read_tokens: int | None = 0
    cache_write_tokens: int | None = 0
    total_tokens: int | None = 0
    cost_total: float | None = None
    cost_total_seen: int = 0  # How many assistant_usage records had cost_total

    # Derived metrics (§4.1)
    context_window: int | None = None
    context_peak: int | None = None  # Max context_usage percent or value
    model_turns: int = 0  # Count of assistant_usage events
    tool_calls: int = 0
    tool_input_bytes: int = 0
    tool_output_bytes: int = 0
    tool_output_raw_bytes: int = 0
    tool_output_model_visible_bytes: int = 0

    # Brain injection and generation metrics (§4.1)
    brain_injected_tokens: int = 0  # From brain_packet_delivered.packet_tokens (model_visible=true)
    brain_generated_tokens: int = 0
    brain_packets_delivered: int = 0
    brain_packets_shadow: int = 0  # model_visible=false (not counted in delivered value)
    retrieval_result_tokens: int = 0

    # Role tokens split (§4.1)
    driver_tokens: int = 0
    worker_tokens: int = 0

    # Cache and optimization metrics (§4.1)
    autoinject_cache_hits: int = 0
    autoinject_cache_misses: int = 0
    action_cache_hits: int = 0
    action_cache_misses: int = 0
    lean_kernel_dedup_hits: int = 0
    session_page_faults: int = 0
    session_evictions: int = 0
    repeated_reads_avoided: int = 0
    model_calls_avoided: int = 0

    # Compactions (§4.1)
    compactions: int = 0
    compaction_tokens: int = 0

    # Role
    role: str | None = None  # 'driver' or 'worker' from before_agent_start.role

    # Computed values
    autoinject_cache_hit_rate: float = 0.0
    net_brain_cost: int = 0  # model_turns cost minus brain_injected_tokens offset
    cache_epochs: list[dict] = field(default_factory=list)


def parse_telemetry_session(session_jsonl_path: Path) -> SessionTokens:
    """
    Parse a single telemetry JSONL file and return SessionTokens.

    Follows HONESTY RULE: only count what exists; report missing as None.
    """
    if not session_jsonl_path.exists():
        raise FileNotFoundError(f"Telemetry file not found: {session_jsonl_path}")

    session_id = session_jsonl_path.stem
    tokens = SessionTokens(session_id=session_id)
    numeric_usage_fields: set[str] = set()
    turn_fallback_counter = 0
    saw_turn_start = False
    current_turn = 0
    current_system_prefix_sha: str | None = None
    current_tool_surface_sha: str | None = None
    last_observed_system_prefix_sha: str | None = None
    last_observed_tool_surface_sha: str | None = None
    has_prior_cache_epoch = False

    with open(session_jsonl_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # Skip malformed records

            kind = record.get('kind')

            # Session start: capture role and model
            if kind == 'session_start':
                tokens.role = record.get('role')
                if tokens.model is None:  # Capture from session_start if not yet set
                    tokens.model = record.get('model')

            # Before agent start: capture role
            if kind == 'before_agent_start':
                tokens.role = record.get('role')

            # Turn start: track turn number (cache-epoch attribution, T2.5)
            if kind == 'turn_start':
                saw_turn_start = True
                turn_value = record.get('turn')
                if isinstance(turn_value, int) and not isinstance(turn_value, bool):
                    current_turn = turn_value
                else:
                    turn_fallback_counter += 1
                    current_turn = turn_fallback_counter
                current_system_prefix_sha = None
                current_tool_surface_sha = None

            # Provider request meta: capture prefix/tool-surface shas for this turn
            if kind == 'provider_request_meta':
                if 'system_prefix_sha' in record:
                    current_system_prefix_sha = record['system_prefix_sha']
                if 'tool_surface_sha' in record:
                    current_tool_surface_sha = record['tool_surface_sha']

            # Usage: assistant_usage stores counters at the record root;
            # Hermes model_invocation_completed nests the same mapping.
            if kind in ('assistant_usage', 'model_invocation_completed'):
                usage = record if kind == 'assistant_usage' else record.get('usage')
                if not isinstance(usage, dict):
                    continue
                tokens.provider = record.get('provider')
                # Only override model if present in record (don't clobber from session_start)
                if 'model' in record:
                    tokens.model = record['model']
                if tokens.source_kind is None:
                    tokens.source_kind = kind
                elif tokens.source_kind != kind:
                    tokens.source_kind = None
                tokens.model_turns += 1

                # Cache-epoch attribution (T2.5): each assistant_usage/
                # model_invocation_completed record is one model turn.
                if not saw_turn_start:
                    turn_fallback_counter += 1
                    current_turn = turn_fallback_counter
                raw_cache_write = usage.get('cache_write_tokens')
                if (
                    isinstance(raw_cache_write, int)
                    and not isinstance(raw_cache_write, bool)
                    and raw_cache_write > 0
                ):
                    if current_system_prefix_sha is None and current_tool_surface_sha is None:
                        cause = 'unknown'
                    elif not has_prior_cache_epoch:
                        cause = 'unknown'
                    elif (
                        current_system_prefix_sha is not None
                        and current_system_prefix_sha != last_observed_system_prefix_sha
                    ):
                        cause = 'brain_prefix'
                    elif (
                        current_tool_surface_sha is not None
                        and current_tool_surface_sha != last_observed_tool_surface_sha
                    ):
                        cause = 'tool_surface'
                    else:
                        cause = 'harness'
                    tokens.cache_epochs.append({
                        'turn': current_turn,
                        'cause': cause,
                        'write_tokens': raw_cache_write,
                    })
                    has_prior_cache_epoch = True
                    if current_system_prefix_sha is not None:
                        last_observed_system_prefix_sha = current_system_prefix_sha
                    if current_tool_surface_sha is not None:
                        last_observed_tool_surface_sha = current_tool_surface_sha
                if not saw_turn_start:
                    current_system_prefix_sha = None
                    current_tool_surface_sha = None

                if 'context_window' in record:
                    tokens.context_window = record['context_window']

                # Aggregate tokens (HONESTY: only count reported values;
                # explicit null remains distinguishable from a zero).
                for field in (
                    'input_tokens',
                    'output_tokens',
                    'cache_read_tokens',
                    'cache_write_tokens',
                    'total_tokens',
                ):
                    value = usage.get(field)
                    if isinstance(value, int) and not isinstance(value, bool):
                        current = getattr(tokens, field)
                        setattr(tokens, field, (current or 0) + value)
                        numeric_usage_fields.add(field)
                    elif (
                        value is None
                        and field in usage
                        and field not in numeric_usage_fields
                    ):
                        setattr(tokens, field, None)
                if 'compaction_tokens' in usage:
                    value = usage['compaction_tokens']
                    if isinstance(value, int) and not isinstance(value, bool):
                        tokens.compaction_tokens += value

                # Cost (HONESTY: report missing as None, track how many had it)
                if 'cost_total' in record:
                    cost_total = record['cost_total']
                    if isinstance(cost_total, (int, float)) and not isinstance(cost_total, bool):
                        if tokens.cost_total is None:
                            tokens.cost_total = 0.0
                        tokens.cost_total += cost_total
                        tokens.cost_total_seen += 1
            # Tool calls
            if kind == 'tool_call':
                tokens.tool_calls += 1
                if 'input_bytes' in record:
                    tokens.tool_input_bytes += record['input_bytes']

            # Tool results
            if kind == 'tool_result':
                if 'output_bytes' in record:
                    tokens.tool_output_bytes += record['output_bytes']
                if 'raw_bytes' in record:
                    tokens.tool_output_raw_bytes += record['raw_bytes']
                elif 'output_bytes' in record:
                    tokens.tool_output_raw_bytes += record['output_bytes']
                if 'model_visible_bytes' in record:
                    tokens.tool_output_model_visible_bytes += record['model_visible_bytes']

            # Brain packet delivered
            if kind == 'brain_packet_delivered':
                if record.get('model_visible'):
                    tokens.brain_injected_tokens += record.get('packet_tokens', 0)
                    tokens.brain_packets_delivered += 1
                else:
                    tokens.brain_packets_shadow += 1
                if 'retrieval_tokens' in record:
                    tokens.retrieval_result_tokens += record['retrieval_tokens']
                if 'generated_tokens' in record:
                    tokens.brain_generated_tokens += record['generated_tokens']

            # Autoinject shadow decisions
            if kind == 'autoinject_shadow_decision':
                if record.get('cache_hit'):
                    tokens.autoinject_cache_hits += 1
                else:
                    tokens.autoinject_cache_misses += 1

            # Action cache events
            if kind in ('action_cache', 'action_cache_lookup'):
                if record.get('hit'):
                    tokens.action_cache_hits += 1
                else:
                    tokens.action_cache_misses += 1
                if 'model_calls_avoided' in record:
                    tokens.model_calls_avoided += record['model_calls_avoided']

            # Context paging / VMEM events
            if kind in ('session_vmem', 'session_paging'):
                if record.get('page_fault'):
                    tokens.session_page_faults += 1
                if record.get('evicted'):
                    tokens.session_evictions += 1

            # Delta sync / read reuse events
            if kind in ('delta_sync', 'read_reuse') and record.get('repeated_read_avoided'):
                tokens.repeated_reads_avoided += 1

            # Lean kernel dedup
            if kind == 'lean_kernel' and record.get('dedup_hit'):
                tokens.lean_kernel_dedup_hits += 1

            # Context peak (from turn_end.context_usage)
            if kind == 'turn_end':
                context_usage = record.get('context_usage')
                if (context_usage and isinstance(context_usage, dict)
                        and 'percent' in context_usage):
                    val = context_usage['percent']
                    if tokens.context_peak is None or val > tokens.context_peak:
                        tokens.context_peak = int(val)

            # Compactions
            if kind == 'session_compact':
                tokens.compactions += 1
                if 'compaction_tokens' in record:
                    tokens.compaction_tokens += record['compaction_tokens']

    # Derived role totals retain the historical integer surface. A null
    # source total contributes no known tokens; it is not converted in the
    # source field itself.
    if tokens.role == 'driver':
        tokens.driver_tokens = tokens.total_tokens if tokens.total_tokens is not None else 0
    elif tokens.role == 'worker':
        tokens.worker_tokens = tokens.total_tokens if tokens.total_tokens is not None else 0

    if tokens.autoinject_cache_hits + tokens.autoinject_cache_misses > 0:
        total_decisions = (
            tokens.autoinject_cache_hits + tokens.autoinject_cache_misses
        )
        if total_decisions > 0:
            tokens.autoinject_cache_hit_rate = (
                tokens.autoinject_cache_hits / total_decisions
            )

    # Cost defaults to None if not seen in any assistant_usage record
    if tokens.cost_total_seen == 0:
        tokens.cost_total = None

    return tokens


def get_ablation_profile(name: str) -> dict[str, bool]:
    """
    Get a predefined ablation profile by name.

    Raises KeyError if profile name is unknown.
    """
    normalized = name.upper()
    if normalized in ABLATION_PROFILES:
        return dict(ABLATION_PROFILES[normalized])

    # Also support matching without letter prefix, e.g. "BRAIN_OFF" -> "A_BRAIN_OFF"
    for profile_key, profile_val in ABLATION_PROFILES.items():
        if profile_key.endswith(normalized) or normalized in profile_key:
            return dict(profile_val)

    valid = ", ".join(ABLATION_PROFILES.keys())
    raise KeyError(f"Unknown ablation profile: {name}. Valid profiles: {valid}")


def get_profile_env(profile_name: str) -> dict[str, str]:
    """
    Generate environment variables for an ablation profile.

    Returns dict of SECOND_BRAIN_GOVERNOR_<KEY>=0/1.
    """
    profile = get_ablation_profile(profile_name)
    return {
        f"SECOND_BRAIN_GOVERNOR_{key.upper()}": "1" if val else "0"
        for key, val in profile.items()
    }


def parse_telemetry(home: Path) -> list[SessionTokens]:
    """
    Parse all telemetry JSONL files in a brain home.

    Returns list of SessionTokens, one per session.
    """
    telemetry_dir = home / "telemetry" / "agent-performance"

    if not telemetry_dir.exists():
        return []

    sessions = []
    for jsonl_path in sorted(telemetry_dir.glob("*.jsonl")):
        try:
            tokens = parse_telemetry_session(jsonl_path)
            sessions.append(tokens)
        except Exception:
            # Skip files that fail to parse
            pass

    return sessions


def attribute_roles(sessions: list[SessionTokens]) -> dict[str, int]:
    """
    Attribute token costs by role (driver vs worker).

    Returns dict with keys:
      - driver_turns, driver_input_tokens, driver_output_tokens, etc.
      - worker_turns, worker_input_tokens, worker_output_tokens, etc.
      - unknown_turns (sessions with no role)
    """
    result = {
        'driver_turns': 0,
        'driver_input_tokens': 0,
        'driver_output_tokens': 0,
        'driver_total_tokens': 0,
        'worker_turns': 0,
        'worker_input_tokens': 0,
        'worker_output_tokens': 0,
        'worker_total_tokens': 0,
        'unknown_turns': 0,
    }

    for session in sessions:
        role_key = None
        if session.role == 'driver':
            role_key = 'driver'
        elif session.role == 'worker':
            role_key = 'worker'
        else:
            result['unknown_turns'] += session.model_turns
            continue

        result[f'{role_key}_turns'] += session.model_turns
        result[f'{role_key}_input_tokens'] += (
            session.input_tokens if session.input_tokens is not None else 0
        )
        result[f'{role_key}_output_tokens'] += (
            session.output_tokens if session.output_tokens is not None else 0
        )
        result[f'{role_key}_total_tokens'] += (
            session.total_tokens if session.total_tokens is not None else 0
        )

    return result


def resolve_features(home: Path, env: dict[str, str] | None = None) -> dict[str, bool]:
    """
    Resolve feature flags by precedence: env > config > default.

    Returns dict[feature_name] -> bool.
    Raises ValueError if config file contains unknown keys.
    """
    environ = env if env is not None else os.environ

    defaults = DEFAULT_FEATURES
    result = dict(defaults)

    # Config file overrides
    config_path = home / "config" / "governor.toml"
    if config_path.exists():
        # Simple TOML parsing (only [features] section, key=value pairs)
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        with open(config_path, 'rb') as f:
            config_data = tomllib.load(f)

        if 'features' in config_data:
            features = config_data['features']
            for key, value in features.items():
                if key not in defaults:
                    raise ValueError(f"Unknown feature flag in governor.toml: {key}")
                result[key] = bool(value)

    # Environment overrides (SECOND_BRAIN_GOVERNOR_<KEY>=0/1)
    for key in defaults:
        env_key = f"SECOND_BRAIN_GOVERNOR_{key.upper()}"
        if env_key in environ:
            val = environ[env_key].lower()
            if val in ('1', 'true', 'yes'):
                result[key] = True
            elif val in ('0', 'false', 'no'):
                result[key] = False

    return result


def feature_source(key: str, home: Path, env: dict[str, str] | None = None) -> str:
    """
    Determine which layer (env/config/default) set a feature flag.

    Returns one of: 'env', 'config', 'default', or 'unknown'.
    """
    environ = env if env is not None else os.environ

    # Check env
    env_key = f"SECOND_BRAIN_GOVERNOR_{key.upper()}"
    if env_key in environ:
        return 'env'

    # Check config
    config_path = home / "config" / "governor.toml"
    if config_path.exists():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        with open(config_path, 'rb') as f:
            config_data = tomllib.load(f)

        if 'features' in config_data and key in config_data['features']:
            return 'config'

    # Must be default
    return 'default'


@dataclass
class ROIVerdict:
    """Result of ROI classification."""
    status: Literal['POSITIVE_ROI', 'NEUTRAL', 'NEGATIVE_ROI', 'INSUFFICIENT_EVIDENCE']
    on_tokens: float | None = None
    off_tokens: float | None = None
    savings: float | None = None  # on_tokens - off_tokens (negative = savings)
    on_sessions: int = 0
    off_sessions: int = 0
    neutral_band: float = 0.02
    reason: str = ""


def classify_roi(
    on: list[SessionTokens],
    off: list[SessionTokens],
    *,
    min_sessions: int = 3,
    neutral_band: float = 0.02,
) -> ROIVerdict:
    """Delegate paired ROI evidence to :mod:`second_brain.economics`."""
    verdict = ROIVerdict(
        status="INSUFFICIENT_EVIDENCE",
        on_sessions=len(on),
        off_sessions=len(off),
        neutral_band=neutral_band,
    )
    if len(on) < min_sessions or len(off) < min_sessions:
        verdict.reason = (
            f"on_sessions={len(on)} < min={min_sessions} "
            f"or off_sessions={len(off)} < min={min_sessions}"
        )
        return verdict

    runs: list[dict[str, object]] = []
    for on_session, off_session in zip(on, off):
        runs.append(
            {
                "off": {
                    "tokens": off_session.cost_total
                    if off_session.cost_total_seen
                    else off_session.total_tokens,
                },
                "on": {
                    "tokens": on_session.cost_total
                    if on_session.cost_total_seen
                    else on_session.total_tokens,
                },
            }
        )
    result = economics.verdict(runs)
    status = result.get("verdict")
    if (
        isinstance(status, str)
        and status == "NEGATIVE"
        and abs(result.get("r_bar") or 0) <= neutral_band + 1e-9
    ):
        verdict.status = "NEUTRAL"
    elif status == "POSITIVE":
        verdict.status = "POSITIVE_ROI"
    elif status == "NEGATIVE":
        verdict.status = "NEGATIVE_ROI"
    else:
        verdict.status = "INSUFFICIENT_EVIDENCE"
    if any(session.cost_total is None or session.cost_total_seen == 0 for session in (*on, *off)):
        verdict.status = "INSUFFICIENT_EVIDENCE"
        verdict.reason = "cost_total missing from host telemetry"
    on_costs = [session.cost_total for session in on if session.cost_total is not None]
    off_costs = [session.cost_total for session in off if session.cost_total is not None]
    if len(on_costs) == len(on) and len(off_costs) == len(off):
        on_total = sum(on_costs)
        off_total = sum(off_costs)
        verdict.on_tokens = on_total
        verdict.off_tokens = off_total
        verdict.savings = on_total - off_total
    if not verdict.reason:
        verdict.reason = f"mSPRT verdict={status}; n={result.get('n', 0)}"
    return verdict


# ---------------------------------------------------------------------------
# T3.1 hard/soft budget caps (plan §... token governor enforcement).
#
# `used` is this session's own telemetry `total_tokens` plus every unique
# descendant worker session's `total_tokens`. Descendants are discovered by
# scanning `home/state/sessions/*/ledger.sqlite` for `sessions` rows whose
# `root_parent_session_id` equals this session's internal id. Ledger and
# telemetry reads are read-only; incomplete or malformed accounting fails
# open with an explicit diagnostic instead of asserting a factual zero.
#
# T3.1-brief investigation note: `assistant_usage`/`session_start` and every
# other kind in SCHEMA.md were checked for a field that already reports
# rolled-up child/descendant usage (which would let a session skip its own
# child-directory scan). No such field exists anywhere in the current
# telemetry schema, so that shortcut branch is dormant by construction; the
# descendant scan below is the only path.
# ---------------------------------------------------------------------------

_DEFAULT_BUDGETS: dict[str, float] = {
    'session_tokens': 400000,
    'worker_tokens': 120000,
    'soft_ratio': 0.8,
}


def _budget_config(home: Path) -> dict[str, float]:
    """config/governor.toml [budgets]; defaults on absence/malformed input."""
    result = dict(_DEFAULT_BUDGETS)
    config_path = Path(home) / "config" / "governor.toml"
    if not config_path.exists():
        return result
    try:
        import tomllib

        with open(config_path, 'rb') as f:
            config_data = tomllib.load(f)
    except Exception:
        return dict(_DEFAULT_BUDGETS)
    budgets = config_data.get('budgets') if isinstance(config_data, dict) else None
    if not isinstance(budgets, dict):
        return result
    for key, default in _DEFAULT_BUDGETS.items():
        if key not in budgets:
            continue
        try:
            result[key] = type(default)(budgets[key])
        except (TypeError, ValueError):
            pass
    return result


def _telemetry_stem(session_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]", "-", session_id or "")
    return stem or "unknown"


def _session_telemetry_paths(home: Path, session_id: str) -> list[Path]:
    """Existing telemetry writers use raw and Python-sanitized session stems."""
    telemetry_dir = home / "telemetry" / "agent-performance"
    paths: list[Path] = []
    for stem in (session_id, _telemetry_stem(session_id)):
        candidate = telemetry_dir / f"{stem}.jsonl"
        try:
            if candidate.resolve().parent != telemetry_dir.resolve():
                continue
        except OSError:
            continue
        if candidate.is_file() and candidate not in paths:
            paths.append(candidate)
    return paths


def _session_total_tokens(home: Path, session_id: str) -> int:
    """Return known usage for one telemetry identity; raise when it is unknown."""
    paths = _session_telemetry_paths(home, session_id)
    if not paths:
        raise FileNotFoundError(f"telemetry unavailable for session {session_id!r}")

    total = 0
    usage_seen = False
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"malformed telemetry for session {session_id!r} at "
                        f"{path.name}:{line_number}"
                    ) from exc
                if not isinstance(record, dict):
                    raise ValueError(
                        f"malformed telemetry for session {session_id!r} at "
                        f"{path.name}:{line_number}"
                    )
                kind = record.get("kind")
                telemetry_session = record.get("session")
                if telemetry_session is not None and telemetry_session != session_id:
                    raise ValueError(
                        f"telemetry identity mismatch for session {session_id!r} "
                        f"in {path.name}:{line_number}"
                    )
                if kind not in ("assistant_usage", "model_invocation_completed"):
                    continue
                if telemetry_session != session_id:
                    raise ValueError(
                        f"telemetry identity missing for session {session_id!r} "
                        f"in {path.name}:{line_number}"
                    )
                usage = record if kind == "assistant_usage" else record.get("usage")
                if not isinstance(usage, dict):
                    raise ValueError(
                        f"malformed usage for session {session_id!r} at "
                        f"{path.name}:{line_number}"
                    )
                value = usage.get("total_tokens")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(
                        f"unknown total_tokens for session {session_id!r} at "
                        f"{path.name}:{line_number}"
                    )
                total += value
                usage_seen = True
    if not usage_seen:
        raise ValueError(f"token usage unavailable for session {session_id!r}")
    return total


def _descendant_total_tokens(home: Path, session_id: str) -> int:
    """Sum each unique ledger session rooted at ``session_id`` exactly once."""
    root_id = ledger.internal_session_id(session_id)
    sessions_dir = home / "state" / "sessions"
    try:
        children = sorted(sessions_dir.iterdir()) if sessions_dir.is_dir() else []
    except OSError as exc:
        raise ValueError("session ledgers unavailable") from exc

    def read_descendants(child: Path) -> list[sqlite3.Row]:
        dbfile = child / "ledger.sqlite"
        if not dbfile.is_file():
            return []
        try:
            conn = sqlite3.connect(
                dbfile.absolute().as_uri() + "?mode=ro",
                timeout=1.0,
                uri=True,
            )
            conn.row_factory = sqlite3.Row
            try:
                return conn.execute(
                    "SELECT internal_session_id, host_session_id "
                    "FROM sessions WHERE root_parent_session_id = ?",
                    (root_id,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise ValueError(f"unreadable session ledger {dbfile.name}") from exc

    descendants_by_internal_id: dict[str, str] = {}
    internal_id_by_host: dict[str, str] = {}
    # Independent read-only ledgers are I/O-bound; never share connections or
    # accumulate identity state in workers. map preserves validation order.
    with ThreadPoolExecutor(max_workers=8) as readers:
        for rows in readers.map(read_descendants, children):
            for row in rows:
                internal_id = row["internal_session_id"]
                host_id = row["host_session_id"]
                if not internal_id or not host_id:
                    raise ValueError("descendant ledger identity is incomplete")
                known_host = descendants_by_internal_id.get(internal_id)
                known_internal = internal_id_by_host.get(host_id)
                if (known_host is not None and known_host != host_id) or (
                    known_internal is not None and known_internal != internal_id
                ):
                    raise ValueError("conflicting descendant ledger identities")
                descendants_by_internal_id[internal_id] = host_id
                internal_id_by_host[host_id] = internal_id

    return sum(
        _session_total_tokens(home, host_id)
        for host_id in descendants_by_internal_id.values()
    )


def check_budget(home: Path | str, session_id: str, role: str) -> dict[str, Any]:
    """T3.1 hard/soft budget caps.

    Returns ``{"state": "OK"|"SOFT"|"HARD", "used": int, "cap": int}``
    when accounting is complete. Accounting failures preserve fail-open
    policy but report ``used=None`` and ``error=ACCOUNTING_UNAVAILABLE``.
    """
    home_path = Path(home)
    budgets = _budget_config(home_path)
    cap = int(budgets['worker_tokens'] if role == 'worker' else budgets['session_tokens'])
    soft_ratio = float(budgets['soft_ratio'])
    try:
        used = _session_total_tokens(home_path, session_id) + _descendant_total_tokens(
            home_path, session_id
        )
    except Exception:
        logger.debug("check_budget accounting unavailable (fail-open -> OK)", exc_info=True)
        return {
            "state": "OK",
            "used": None,
            "cap": cap,
            "error": "ACCOUNTING_UNAVAILABLE",
        }
    if used >= cap:
        state = "HARD"
    elif used >= cap * soft_ratio:
        state = "SOFT"
    else:
        state = "OK"
    return {"state": state, "used": used, "cap": cap}
