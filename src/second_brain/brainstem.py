"""Brainstem attention and intervention coordinator (Plan §7.4).

Coordinates budget state, context pressure, route transitions, retrieval scheduling,
verification intensity, and intervention gating using only repository-true structured signals.
Deterministic rule evaluation governs; adaptive learned overrides remain SHADOW and
can never bypass hard budget caps or authority floors.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from . import contracts, db, decisions
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


@dataclass(frozen=True)
class BrainstemSignals:
    """Repository-true structured signals. Missing signals are None."""

    budget_tokens_used: int | None = None
    budget_tokens_cap: int | None = None
    budget_hard_cap: int | None = None
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

    # Check for empty / all-missing signals
    if _is_empty_signals(signals_obj):
        retrieve = False
        inject_budget = 500
        route_floor = "T0"
        evict = False
        verify_level = "targeted"
        scout_allowed = False
        reasons.append("CONSERVATIVE_DEFAULTS_APPLIED")
        hard_cap = 3000
    else:
        # 1. Context pressure & Eviction
        resident = signals_obj.resident_tokens
        limit = signals_obj.context_token_limit or 8000
        cap = signals_obj.budget_tokens_cap or 2000
        hard_cap = signals_obj.budget_hard_cap or 3000
        used = signals_obj.budget_tokens_used or 0

        if resident is not None and limit is not None and resident >= 0.8 * limit:
            evict = True
            reasons.append("CONTEXT_PRESSURE_HIGH")
            inject_budget = max(200, int(0.5 * cap))
        else:
            evict = False
            inject_budget = min(cap, max(200, hard_cap - used))

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
    if learned_override:
        # Guard A: Hard budget cap cannot be bypassed
        req_budget = learned_override.get("inject_budget")
        if req_budget is not None and isinstance(req_budget, (int, float)):
            req_budget_int = int(req_budget)
            if req_budget_int > hard_cap:
                inject_budget = hard_cap
                reasons.append(f"OVERRIDE_BUDGET_CAPPED_AT_HARD_LIMIT:{hard_cap}")
            else:
                inject_budget = req_budget_int
                reasons.append("OVERRIDE_BUDGET_APPLIED")

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
            elif (signals_obj.risk_class or "LOW").upper() in ("HIGH", "CRITICAL") or task in ("debugging", "verification", "exploration"):
                scout_allowed = True
                reasons.append("OVERRIDE_SCOUT_ALLOWED")
            else:
                reasons.append("OVERRIDE_SCOUT_REJECTED_FOR_LOW_RISK")

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
    inputs_hash = hashlib.sha256(
        contracts.canonical_json(signals_dict).encode("utf-8")
    ).hexdigest()

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
