"""Observational Brain retrieval and context sizing from structured signals."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import capabilities, contracts, decisions
from .errors import BrainError

_VERIFY_LEVEL_RANKS: dict[str, int] = {
    "none": 0,
    "targeted": 1,
    "full": 2,
    "isolated": 3,
}

_MIN_USEFUL_INJECTION_TOKENS = 200
_CONSERVATIVE_INJECTION_TOKENS = 500
_CONTEXT_ACTIVE_NUMERATOR = 4
_CONTEXT_ACTIVE_DENOMINATOR = 5


def _token_count(value: object, field: str, *, nullable: bool = True) -> int | None:
    if value is None and nullable:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        suffix = " or None" if nullable else ""
        raise BrainError(f"{field} must be a non-negative integer{suffix}")
    return value


def _bound_injection(
    requested: int,
    *,
    operation_cap: int | None,
    resident: int | None,
    context_limit: int | None,
    reasons: list[str],
) -> int:
    """Bound only Brain-injected context, never native task or agent spend."""
    allowance = min(requested, operation_cap) if operation_cap is not None else requested
    if context_limit is not None:
        active_limit = (context_limit * _CONTEXT_ACTIVE_NUMERATOR) // _CONTEXT_ACTIVE_DENOMINATOR
        allowance = min(allowance, max(0, active_limit - (resident or 0)))
    if allowance < requested:
        reasons.append(f"INJECTION_BUDGET_CAPPED_AT_APPLICABLE_LIMIT:{allowance}")
    if 0 < allowance < _MIN_USEFUL_INJECTION_TOKENS:
        reasons.append(f"INJECTION_ABSTAINED_BELOW_USEFUL_MINIMUM:{allowance}")
        return 0
    return allowance


@dataclass(frozen=True)
class BrainstemSignals:
    """Optional observed context signals; missing measurements remain unknown."""

    budget_tokens_cap: int | None = None  # Brain injection per-operation cap
    cache_epoch: int | None = None
    cache_is_cold: bool | None = None
    resident_tokens: int | None = None
    context_token_limit: int | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_tier: str | None = None
    task_class: str | None = None
    risk_class: str | None = None
    retrieval_confidence: float | None = None
    recent_failures: int | None = None
    harness_id: str | None = None
    host_version: str | None = None
    host_config_binding: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrainstemDecision:
    """Observational Brain context and evidence recommendation."""

    retrieve: bool
    inject_budget: int
    evict: bool
    verify_level: str
    reason_codes: tuple[str, ...]
    decision_ref: str | None = None
    rollout_stage: str = "SHADOW"

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieve": self.retrieve,
            "inject_budget": self.inject_budget,
            "evict": self.evict,
            "verify_level": self.verify_level,
            "reason_codes": list(self.reason_codes),
            "decision_ref": self.decision_ref,
            "rollout_stage": self.rollout_stage,
        }


def _is_empty_signals(s: BrainstemSignals) -> bool:
    return all(getattr(s, f) is None for f in s.__annotations__)


def _offline_capability_snapshot() -> dict[str, Any]:
    return {
        "harness_id": None,
        "host_version": None,
        "config_binding": None,
        "capabilities": {
            name: {
                "supported": None,
                "version": None,
                "observed_at": None,
                "evidence": None,
                "status": "unknown",
            }
            for name in sorted(capabilities.KNOWN_CAPABILITIES)
        },
    }


def _resolve_capability_snapshot(
    home: Path,
    signals: BrainstemSignals,
    *,
    host_context: Mapping[str, Any] | None,
    supplied_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = dict(host_context or {})
    harness_id = context.get("harness_id", signals.harness_id)
    host_version = context.get("host_version", signals.host_version)
    config_binding = context.get("config_binding", signals.host_config_binding)
    if supplied_snapshot is not None:
        if not isinstance(supplied_snapshot, Mapping):
            raise BrainError("capability_snapshot must be an object")
        for key, expected in (
            ("harness_id", harness_id),
            ("host_version", host_version),
            ("config_binding", config_binding),
        ):
            value = supplied_snapshot.get(key)
            if value is not None and (not isinstance(value, str) or not value):
                raise BrainError(f"capability_snapshot.{key} must be a non-empty string or None")
            if expected is not None and value != expected:
                raise BrainError(f"capability_snapshot.{key} does not match host context")
        rows = supplied_snapshot.get("capabilities")
        if not isinstance(rows, Mapping):
            raise BrainError("capability_snapshot.capabilities must be an object")
        result = {
            key: supplied_snapshot.get(key)
            for key in ("harness_id", "host_version", "config_binding")
        }
        normalized = {}
        for name in sorted(capabilities.KNOWN_CAPABILITIES):
            row = rows.get(name, {})
            if not isinstance(row, dict):
                raise BrainError(f"capability_snapshot.capabilities.{name} must be an object")
            normalized[name] = {
                **row,
                "status": capabilities._capability_status(
                    row,
                    name,
                    host_version=result["host_version"],
                    config_binding=result["config_binding"],
                ),
            }
        result["capabilities"] = normalized
        return result
    if harness_id is None:
        return _offline_capability_snapshot()
    if not isinstance(harness_id, str) or not harness_id:
        raise BrainError("host_context.harness_id must be a non-empty string")
    return capabilities.snapshot(
        home,
        harness_id,
        host_version=host_version,
        config_binding=config_binding,
    )


def _snapshot_status(snapshot: Mapping[str, Any], capability: str) -> str:
    rows = snapshot.get("capabilities")
    row = rows.get(capability) if isinstance(rows, Mapping) else None
    status = row.get("status") if isinstance(row, Mapping) else None
    return (
        status
        if status in {"declared", "observed", "unavailable", "denied", "unknown"}
        else "unknown"
    )


def decide(
    home: Path | str,
    signals: BrainstemSignals | Mapping[str, Any],
    *,
    task_id: str | None = None,
    session_id: str | None = None,
    learned_override: Mapping[str, Any] | None = None,
    host_context: Mapping[str, Any] | None = None,
    capability_snapshot: Mapping[str, Any] | None = None,
    rollout_stage: str = "SHADOW",
) -> BrainstemDecision:
    """Recommend Brain-local retrieval and context size; never control host execution."""
    home_p = Path(home)
    if not isinstance(signals, BrainstemSignals):
        signals = BrainstemSignals(
            **{key: signals.get(key) for key in BrainstemSignals.__dataclass_fields__}
        )
    reasons: list[str] = []
    cap = _token_count(signals.budget_tokens_cap, "budget_tokens_cap")
    resident = _token_count(signals.resident_tokens, "resident_tokens")
    limit = _token_count(signals.context_token_limit, "context_token_limit")
    if host_context is not None and not isinstance(host_context, Mapping):
        raise BrainError("host_context must be an object")
    evidence = _resolve_capability_snapshot(
        home_p,
        signals,
        host_context=host_context,
        supplied_snapshot=capability_snapshot,
    )
    if _is_empty_signals(signals):
        retrieve = False
        evict = False
        requested = _CONSERVATIVE_INJECTION_TOKENS
        reasons.append("CONSERVATIVE_DEFAULTS_APPLIED")
    else:
        evict = (
            resident is not None
            and limit is not None
            and (resident * _CONTEXT_ACTIVE_DENOMINATOR >= limit * _CONTEXT_ACTIVE_NUMERATOR)
        )
        if evict:
            reasons.append("CONTEXT_PRESSURE_HIGH")
        retrieve = (signals.task_class or "standard").lower() not in ("trivial", "clear")
        reasons.append("TASK_REQUIRES_RETRIEVAL" if retrieve else "TRIVIAL_TASK_SKIP_RETRIEVAL")
        requested = cap if cap is not None else _CONSERVATIVE_INJECTION_TOKENS
        if cap is None or resident is None or limit is None:
            requested = min(requested, _CONSERVATIVE_INJECTION_TOKENS)
            reasons.append("CONSERVATIVE_BUDGET_DEFAULT_APPLIED")
    verify_level = (
        "full" if (signals.risk_class or "LOW").upper() in ("HIGH", "CRITICAL") else "targeted"
    )
    if learned_override:
        override_budget = learned_override.get("inject_budget")
        if override_budget is not None:
            requested = _token_count(
                override_budget, "learned_override.inject_budget", nullable=False
            )
            assert requested is not None
        override_verify = learned_override.get("verify_level")
        if override_verify is not None:
            level = str(override_verify).lower()
            if _VERIFY_LEVEL_RANKS.get(level, -1) >= _VERIFY_LEVEL_RANKS[verify_level]:
                verify_level = level
                reasons.append("OVERRIDE_VERIFY_LEVEL_APPLIED")
            else:
                reasons.append("OVERRIDE_VERIFY_FLOOR_REJECTED")
    if evidence.get("harness_id") and _snapshot_status(evidence, "prompt_injection") != "observed":
        requested = 0
        reasons.append("INJECTION_ABSTAINED_CAPABILITY_UNOBSERVED")
    inject_budget = _bound_injection(
        requested,
        operation_cap=cap,
        resident=resident,
        context_limit=limit,
        reasons=reasons,
    )
    result = {
        "retrieve": retrieve,
        "inject_budget": inject_budget,
        "evict": evict,
        "verify_level": verify_level,
        "reason_codes": reasons,
    }
    inputs = signals.to_dict()
    inputs["capability_snapshot"] = evidence
    digest = hashlib.sha256(contracts.canonical_json(inputs).encode("utf-8")).hexdigest()[:16]
    decision_id = decisions.record(
        home_p,
        kind="brainstem",
        session_id=session_id or f"brainstem-{digest}",
        task_id=task_id or f"task-bs-{digest}",
        chosen=result,
        alternatives=[{"retrieve": not retrieve, "evict": not evict}],
        propensity=1.0,
        randomized=False,
        policy_version="v7.4-memory",
        stage=rollout_stage,
        inputs=inputs,
    )
    return BrainstemDecision(
        retrieve=retrieve,
        inject_budget=inject_budget,
        evict=evict,
        verify_level=verify_level,
        reason_codes=tuple(reasons),
        decision_ref=decision_id,
        rollout_stage=rollout_stage,
    )
