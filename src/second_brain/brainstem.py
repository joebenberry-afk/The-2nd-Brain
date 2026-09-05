"""Brainstem attention and intervention coordinator (Plan §7.4).

Coordinates budget state, context pressure, route transitions, retrieval scheduling,
verification intensity, and intervention gating using only repository-true structured signals.
Deterministic rule evaluation governs; adaptive learned overrides remain SHADOW and
can never bypass hard budget caps or authority floors.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import contracts, decisions
from .errors import BrainError

_VERIFY_LEVEL_RANKS: dict[str, int] = {
    "none": 0,
    "targeted": 1,
    "full": 2,
    "isolated": 3,
}

_ROUTE_FLOOR_RANKS: dict[str, int] = {
    "T0": 0,
    "T1": 1,
    "T2": 2,
    "cheap": 0,
    "standard": 1,
    "premium": 2,
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
    hard_cap: int | None,
    used: int | None,
    resident: int | None,
    context_limit: int | None,
    reasons: list[str],
) -> int:
    """Bound optional injected tokens while preserving 20% context headroom."""
    allowance = requested
    if operation_cap is not None:
        allowance = min(allowance, operation_cap)
    if hard_cap is not None:
        remaining = hard_cap if used is None else max(0, hard_cap - used)
        allowance = min(allowance, remaining)
    if context_limit is not None:
        active_limit = (context_limit * _CONTEXT_ACTIVE_NUMERATOR) // _CONTEXT_ACTIVE_DENOMINATOR
        available_context = active_limit if resident is None else max(0, active_limit - resident)
        allowance = min(allowance, available_context)
    if allowance < requested:
        reasons.append(f"INJECTION_BUDGET_CAPPED_AT_APPLICABLE_LIMIT:{allowance}")
    if 0 < allowance < _MIN_USEFUL_INJECTION_TOKENS:
        reasons.append(f"INJECTION_ABSTAINED_BELOW_USEFUL_MINIMUM:{allowance}")
        return 0
    return allowance


@dataclass(frozen=True)
class BrainstemSignals:
    """Token counts share one integer-token unit; missing signals are None."""

    budget_tokens_used: int | None = None  # cumulative total-budget usage
    budget_tokens_cap: int | None = None  # per-operation injection cap
    budget_hard_cap: int | None = None  # total allowance for the same usage scope
    cache_epoch: int | None = None
    cache_is_cold: bool | None = None
    resident_tokens: int | None = None  # current context occupancy
    context_token_limit: int | None = None  # context-window capacity
    model_provider: str | None = None
    model_name: str | None = None
    model_tier: str | None = None
    task_class: str | None = None
    risk_class: str | None = None
    retrieval_confidence: float | None = None
    worker_pressure: float | None = None
    recent_failures: int | None = None
    provider_quota_remaining: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrainstemDecision:
    """Compact deterministic decision output by the Brainstem coordinator."""

    retrieve: bool
    inject_budget: int
    route_floor: str
    evict: bool
    verify_level: str
    scout_allowed: bool
    reason_codes: tuple[str, ...]
    decision_ref: str | None = None
    rollout_stage: str = "SHADOW"

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieve": self.retrieve,
            "inject_budget": self.inject_budget,
            "route_floor": self.route_floor,
            "evict": self.evict,
            "verify_level": self.verify_level,
            "scout_allowed": self.scout_allowed,
            "reason_codes": list(self.reason_codes),
            "decision_ref": self.decision_ref,
            "rollout_stage": self.rollout_stage,
        }


def _is_empty_signals(s: BrainstemSignals) -> bool:
    return all(getattr(s, f) is None for f in s.__annotations__)


def decide(
    home: Path | str,
    signals: BrainstemSignals | Mapping[str, Any],
    *,
    task_id: str | None = None,
    session_id: str | None = None,
    learned_override: Mapping[str, Any] | None = None,
    rollout_stage: str = "SHADOW",
) -> BrainstemDecision:
    """Evaluate structured signals deterministically and output a BrainstemDecision."""
    home_p = Path(home)
    if not isinstance(signals, BrainstemSignals):
        signals_obj = BrainstemSignals(
            budget_tokens_used=signals.get("budget_tokens_used"),
            budget_tokens_cap=signals.get("budget_tokens_cap"),
            budget_hard_cap=signals.get("budget_hard_cap"),
            cache_epoch=signals.get("cache_epoch"),
            cache_is_cold=signals.get("cache_is_cold"),
            resident_tokens=signals.get("resident_tokens"),
            context_token_limit=signals.get("context_token_limit"),
            model_provider=signals.get("model_provider"),
            model_name=signals.get("model_name"),
            model_tier=signals.get("model_tier"),
            task_class=signals.get("task_class"),
            risk_class=signals.get("risk_class"),
            retrieval_confidence=signals.get("retrieval_confidence"),
            worker_pressure=signals.get("worker_pressure"),
            recent_failures=signals.get("recent_failures"),
            provider_quota_remaining=signals.get("provider_quota_remaining"),
        )
    else:
        signals_obj = signals

    reasons: list[str] = []
    task = (signals_obj.task_class or "standard").lower()
    risk = (signals_obj.risk_class or "LOW").upper()
    used = _token_count(signals_obj.budget_tokens_used, "budget_tokens_used")
    cap = _token_count(signals_obj.budget_tokens_cap, "budget_tokens_cap")
    hard_cap = _token_count(signals_obj.budget_hard_cap, "budget_hard_cap")
    resident = _token_count(signals_obj.resident_tokens, "resident_tokens")
    limit = _token_count(signals_obj.context_token_limit, "context_token_limit")
    complete_budget_context = (
        used is not None
        and cap is not None
        and hard_cap is not None
        and resident is not None
        and limit is not None
    )

    # Check for empty / all-missing signals
    if _is_empty_signals(signals_obj):
        retrieve = False
        requested_budget = _CONSERVATIVE_INJECTION_TOKENS
        route_floor = "T0"
        evict = False
        verify_level = "targeted"
        scout_allowed = False
        reasons.append("CONSERVATIVE_DEFAULTS_APPLIED")
    else:
        # 1. Context pressure & Eviction
        pressure = (
            resident is not None
            and limit is not None
            and resident * _CONTEXT_ACTIVE_DENOMINATOR >= limit * _CONTEXT_ACTIVE_NUMERATOR
        )
        evict = pressure
        if pressure:
            reasons.append("CONTEXT_PRESSURE_HIGH")

        if used is None or cap is None or hard_cap is None or resident is None or limit is None:
            requested_budget = _CONSERVATIVE_INJECTION_TOKENS
            reasons.append("CONSERVATIVE_BUDGET_DEFAULT_APPLIED")
        elif pressure:
            requested_budget = max(
                _MIN_USEFUL_INJECTION_TOKENS,
                cap // 2,
            )
        else:
            requested_budget = min(
                cap,
                max(_MIN_USEFUL_INJECTION_TOKENS, hard_cap - used),
            )
        # 2. Retrieval scheduling
        if task in ("trivial", "clear"):
            retrieve = False
            reasons.append("TRIVIAL_TASK_SKIP_RETRIEVAL")
        else:
            retrieve = True
            reasons.append("TASK_REQUIRES_RETRIEVAL")

        # 3. Risk, verification intensity, routing floor, and scout gating
        if risk in ("HIGH", "CRITICAL"):
            route_floor = "T2"
            verify_level = "full"
            scout_allowed = True
            reasons.append("HIGH_RISK_ELEVATION")
        elif task in ("debugging", "verification", "exploration"):
            route_floor = "T1"
            verify_level = "targeted"
            scout_allowed = True
            reasons.append("EXPLORATION_SCOUT_ALLOWED")
        else:
            route_floor = "T0"
            verify_level = "targeted"
            scout_allowed = False
            reasons.append("STANDARD_DISPATCH")
    # 4. Adaptive learned override validation in SHADOW
    override_budget: int | None = None
    if learned_override:
        req_budget = learned_override.get("inject_budget")
        if req_budget is not None:
            validated_override = _token_count(
                req_budget,
                "learned_override.inject_budget",
                nullable=False,
            )
            assert validated_override is not None
            override_budget = validated_override
            requested_budget = validated_override
        # Guard B: Verification floor cannot be downgraded below risk requirement
        req_verify = learned_override.get("verify_level")
        if req_verify is not None:
            req_rank = _VERIFY_LEVEL_RANKS.get(str(req_verify).lower(), -1)
            floor_rank = _VERIFY_LEVEL_RANKS.get(verify_level, 1)
            if req_rank >= floor_rank:
                verify_level = str(req_verify).lower()
                reasons.append("OVERRIDE_VERIFY_LEVEL_APPLIED")
            else:
                reasons.append("OVERRIDE_VERIFY_FLOOR_REJECTED")

        # Guard C: Route floor cannot be downgraded below risk requirement
        req_route = learned_override.get("route_floor")
        if req_route is not None:
            req_r_rank = _ROUTE_FLOOR_RANKS.get(str(req_route), -1)
            floor_r_rank = _ROUTE_FLOOR_RANKS.get(route_floor, 0)
            if req_r_rank >= floor_r_rank:
                route_floor = str(req_route)
                reasons.append("OVERRIDE_ROUTE_FLOOR_APPLIED")
            else:
                reasons.append("OVERRIDE_ROUTE_FLOOR_REJECTED")

        # Guard D: Scout gating override
        req_scout = learned_override.get("scout_allowed")
        if isinstance(req_scout, bool):
            if not req_scout:
                scout_allowed = False
                reasons.append("OVERRIDE_SCOUT_DISALLOWED")
            elif (signals_obj.risk_class or "LOW").upper() in ("HIGH", "CRITICAL") or task in (
                "debugging",
                "verification",
                "exploration",
            ):
                scout_allowed = True
                reasons.append("OVERRIDE_SCOUT_ALLOWED")
            else:
                reasons.append("OVERRIDE_SCOUT_REJECTED_FOR_LOW_RISK")

    if not complete_budget_context:
        requested_budget = min(
            requested_budget,
            _CONSERVATIVE_INJECTION_TOKENS,
        )

    inject_budget = _bound_injection(
        requested_budget,
        operation_cap=cap,
        hard_cap=hard_cap,
        used=used,
        resident=resident,
        context_limit=limit,
        reasons=reasons,
    )
    if override_budget is not None:
        if inject_budget == override_budget:
            reasons.append("OVERRIDE_BUDGET_APPLIED")
        else:
            reasons.append(f"OVERRIDE_BUDGET_CAPPED_AT_APPLICABLE_LIMIT:{inject_budget}")

    decision_dict = {
        "retrieve": retrieve,
        "inject_budget": inject_budget,
        "route_floor": route_floor,
        "evict": evict,
        "verify_level": verify_level,
        "scout_allowed": scout_allowed,
        "reason_codes": reasons,
    }

    signals_dict = signals_obj.to_dict()
    inputs_hash = hashlib.sha256(contracts.canonical_json(signals_dict).encode("utf-8")).hexdigest()

    decision_id = decisions.record(
        home_p,
        kind="brainstem",
        session_id=session_id or f"brainstem-{inputs_hash[:16]}",
        task_id=task_id or f"task-bs-{inputs_hash[:16]}",
        chosen=decision_dict,
        alternatives=[{"retrieve": not retrieve, "evict": not evict}],
        propensity=1.0,
        randomized=False,
        policy_version="v7.4",
        stage=rollout_stage,
        inputs=signals_dict,
    )

    return BrainstemDecision(
        retrieve=retrieve,
        inject_budget=inject_budget,
        route_floor=route_floor,
        evict=evict,
        verify_level=verify_level,
        scout_allowed=scout_allowed,
        reason_codes=tuple(reasons),
        decision_ref=decision_id,
        rollout_stage=rollout_stage,
    )
