"""Harness-neutral, deterministic model routing for the P2.6 slice.

This module owns only the bounded decision contract and selector.  It composes
existing Brain primitives (the sparse skill router, risk assessor, and
caller-recorded cross-model outcome reports) but does not persist decisions,
change routing policy, or know how a host invokes a provider.  Hermes/provider
wiring is deliberately a later adapter step.

The selector is policy-bounded rather than self-learning:

* candidates and their capability/cost/role metadata are supplied by the
  caller;
* the lowest-cost eligible candidate wins;
* premium is permitted only for an explicit, bounded justification code or an
  objective high-risk/capability/role signal;
* unavailable candidates produce an explicit fallback or an explicit failure;
* task text is used transiently and only its existing 16-hex Brain task hash is
  retained in :class:`ModelDecision`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import os
from pathlib import Path
from typing import Any

from . import contracts, crossmodel, db, decisions, risk, router
from .errors import BrainError

MODEL_ROUTING_SCHEMA_VERSION = 1
MAX_CANDIDATES = 32
MAX_TEXT_CHARS = 256
MAX_CAPABILITIES = 16
MAX_ROLE_ENTRIES = 16

TIERS: tuple[str, ...] = ("efficient", "balanced", "premium")
COST_CLASSES: tuple[str, ...] = ("low", "medium", "high")
RISK_CLASSES: tuple[str, ...] = risk.RISK_LEVELS
_TIER_RANK = {value: index for index, value in enumerate(TIERS)}
_COST_RANK = {value: index for index, value in enumerate(COST_CLASSES)}
_RISK_RANK = {value: index for index, value in enumerate(RISK_CLASSES)}
_PRICE_CLASS_RANK = {"low": 1, "medium": 2, "high": 3}

class TaskClass(StrEnum):
    TRIVIAL = "trivial"
    NAVIGATION = "navigation"
    IMPLEMENTATION = "implementation"
    DEBUGGING = "debugging"
    VERIFICATION = "verification"
    EXPLORATION = "exploration"
    HIGH_RISK = "high_risk"
    CONTINUATION = "continuation"

TASK_CLASSES: tuple[str, ...] = tuple(item.value for item in TaskClass)


def classify_task(task_or_hash: str, *, risk_class: str | None = None) -> TaskClass:
    """Map 16-hex task hash or task content to a TaskClass."""
    if isinstance(task_or_hash, TaskClass):
        return task_or_hash
    text_val = str(task_or_hash).strip()
    lower_val = text_val.lower()
    for item in TaskClass:
        if lower_val == item.value:
            return item
    if risk_class in ("HIGH", "CRITICAL"):
        return TaskClass.HIGH_RISK
    if len(text_val) == 16 and all(c in "0123456789abcdefABCDEF" for c in text_val):
        idx = int(text_val, 16) % len(TASK_CLASSES)
        return TaskClass(TASK_CLASSES[idx])
    if any(w in lower_val for w in ("continue", "continuation", "resume", "pick up")):
        return TaskClass.CONTINUATION
    if any(w in lower_val for w in ("verify", "verification", "check", "assert", "audit", "lint", "gate")):
        return TaskClass.VERIFICATION
    if any(w in lower_val for w in ("debug", "debugging", "fix", "bug", "error", "failure", "trace", "issue", "crash")):
        return TaskClass.DEBUGGING
    if any(w in lower_val for w in ("navigate", "navigation", "find", "search", "locate", "where", "list", "grep", "glob")):
        return TaskClass.NAVIGATION
    if any(w in lower_val for w in ("explore", "exploration", "investigate", "research", "survey", "discover")):
        return TaskClass.EXPLORATION
    if any(w in lower_val for w in ("critical", "high risk", "security", "permission", "drop table", "destroy", "root")):
        return TaskClass.HIGH_RISK
    if any(w in lower_val for w in ("trivial", "summarize", "summary", "readme", "ping", "hello", "echo", "typo")):
        return TaskClass.TRIVIAL
    if any(w in lower_val for w in ("implement", "implementation", "build", "create", "write", "add", "develop", "refactor", "code")):
        return TaskClass.IMPLEMENTATION
    return TaskClass.IMPLEMENTATION


map_task_class = classify_task
# Only integrator/validator adapters may supply policy overrides.  Worker and
# normal requests still use objective task/file risk signals, but cannot raise
# their own minimum tier or premium justification.
_TRUSTED_POLICY_ROLES = frozenset({"integrator", "validator"})

# Cross-model reports are keyed by model_id, not provider/model identity.
# Quality stats are therefore unsafe when one model_id belongs to multiple
# providers; ambiguous entries deliberately receive no inferred score.


# This is a small, explicit role policy.  It mirrors the existing Brain/Prime
# role vocabulary without moving Prime policy into this selector.  A premium
# candidate still needs a separate justification below.
_ROLE_MINIMUM_TIER = {
    "normal": "efficient",
    "worker": "efficient",
    "dev": "efficient",
    "validator": "efficient",
    "driver": "balanced",
    "integrator": "balanced",
    "orchestrator": "balanced",
    "hard_orchestrator": "premium",
}
_ROLE_MAXIMUM_TIER = {role: "premium" for role in _ROLE_MINIMUM_TIER}

_PREMIUM_JUSTIFICATION_CODES = frozenset(
    {
        "ambiguity",
        "architecture",
        "capability_requirement",
        "critical_risk",
        "formal_verification",
        "high_risk",
        "repeated_failure",
        "role_policy",
        "security",
    }
)
_PREMIUM_CAPABILITIES = frozenset(
    {"architecture", "security", "formal_verification", "critical_reasoning", "deep_reasoning"}
)
_CAPABILITY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("architecture", ("architecture", "architectural", "system design", "redesign")),
    ("security", ("security", "secret", "credential", "authentication")),
    ("formal_verification", ("formal verification", "prove invariant", "proof obligation")),
    ("verification", ("verify", "verification", "validate", "validation", "audit")),
    ("debugging", ("debug", "debugging", "root cause", "diagnose", "diagnosis")),
    ("coding", ("implement", "implementation", "code", "patch", "refactor")),
    ("retrieval", ("retrieve", "retrieval", "search", "recall", "context")),
)
_BALANCED_MARKERS = (
    "debug",
    "investigate",
    "verify",
    "validation",
    "review",
    "refactor",
    "analy",
    "ambiguous",
    "uncertain",
)
_PREMIUM_MARKERS = (
    "architecture",
    "architectural",
    "critical",
    "production",
    "distributed",
    "data loss",
    "security boundary",
    "formal verification",
)


class ModelRoutingError(BrainError):
    """Bounded model-routing input/contract error with a stable error code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(f"{code}: {message or code}")


def _text(value: Any, field_name: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{field_name} must be a string")
    if len(value) > MAX_TEXT_CHARS:
        raise ModelRoutingError(
            "ROUTING_INPUT_TOO_LARGE", f"{field_name} exceeds {MAX_TEXT_CHARS} chars"
        )
    if required and not value.strip():
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{field_name} must not be empty")
    return value


def _label(value: Any, field_name: str, allowed: Sequence[str]) -> str:
    if not isinstance(value, str):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{field_name} must be a string")
    normalized = value.strip().lower()
    canonical = {label.lower(): label for label in allowed}.get(normalized)
    if canonical is None:
        raise ModelRoutingError(
            "INVALID_ROUTING_LABEL",
            f"{field_name} must be one of {', '.join(allowed)}",
        )
    return canonical


def _capability(value: Any) -> str:
    if not isinstance(value, str):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", "capabilities must be strings")
    normalized = "_".join(value.strip().lower().replace("-", " ").split())
    if not normalized or len(normalized) > MAX_TEXT_CHARS:
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", "invalid capability")
    return normalized


def _bounded_labels(values: Any, field_name: str, *, limit: int) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{field_name} must be a sequence")
    if len(values) > limit:
        raise ModelRoutingError("ROUTING_INPUT_TOO_LARGE", f"{field_name} has too many entries")
    result = tuple(sorted({_capability(value) for value in values}))
    return result


def _roles(values: Any, field_name: str = "roles") -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{field_name} must be a sequence")
    if len(values) > MAX_ROLE_ENTRIES:
        raise ModelRoutingError("ROUTING_INPUT_TOO_LARGE", f"{field_name} has too many entries")
    out: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_CHARS:
            raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"invalid {field_name} entry")
        out.add(value.strip().lower())
    return tuple(sorted(out))



def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ModelRoutingError("MALFORMED_DECISION", f"{field_name} must be boolean")
    return value


def _optional_score(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{field_name} must be a number")
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{field_name} must be between 0 and 1")
    return score


@dataclass(frozen=True)
class ModelCandidate:
    """Bounded provider/model metadata supplied to the Brain selector.

    ``provider`` and ``model`` are opaque runtime identifiers and are preserved
    byte-for-byte.  Labels and capabilities are normalized because they are
    policy vocabulary rather than provider identifiers.
    """

    provider: str
    model: str
    tier: str = "efficient"
    capabilities: tuple[str, ...] = ()
    cost_class: str = "low"
    roles: tuple[str, ...] = ()
    available: bool = True
    provider_available: bool = True
    model_available: bool = True
    max_risk: str = "CRITICAL"
    quality_score: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "model", _text(self.model, "model"))
        object.__setattr__(self, "tier", _label(self.tier, "tier", TIERS))
        object.__setattr__(self, "cost_class", _label(self.cost_class, "cost_class", COST_CLASSES))
        object.__setattr__(self, "max_risk", _label(self.max_risk, "max_risk", RISK_CLASSES))
        object.__setattr__(
            self,
            "capabilities",
            _bounded_labels(self.capabilities, "capabilities", limit=MAX_CAPABILITIES),
        )
        object.__setattr__(self, "roles", _roles(self.roles))
        for name in ("available", "provider_available", "model_available"):
            if not isinstance(getattr(self, name), bool):
                raise ModelRoutingError("MALFORMED_ROUTING_INPUT", f"{name} must be boolean")
        object.__setattr__(
            self, "quality_score", _optional_score(self.quality_score, "quality_score")
        )

    @property
    def is_available(self) -> bool:
        return self.available and self.provider_available and self.model_available

    @property
    def availability_reason(self) -> str:
        if not self.provider_available:
            return "PROVIDER_UNAVAILABLE"
        if not self.model_available:
            return "MODEL_UNAVAILABLE"
        if not self.available:
            return "MODEL_UNAVAILABLE"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "capabilities": list(self.capabilities),
            "cost_class": self.cost_class,
            "roles": list(self.roles),
            "available": self.available,
            "provider_available": self.provider_available,
            "model_available": self.model_available,
            "max_risk": self.max_risk,
            "quality_score": self.quality_score,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModelCandidate:
        if not isinstance(data, Mapping):
            raise ModelRoutingError("MALFORMED_CANDIDATE", "candidate must be an object")
        try:
            return cls(
                provider=data["provider"],
                model=data["model"],
                tier=data.get("tier", "efficient"),
                capabilities=tuple(data.get("capabilities", ())),
                cost_class=data.get("cost_class", "low"),
                roles=tuple(data.get("roles", ())),
                available=data.get("available", True),
                provider_available=data.get("provider_available", True),
                model_available=data.get("model_available", True),
                max_risk=data.get("max_risk", "CRITICAL"),
                quality_score=data.get("quality_score"),
            )
        except KeyError as exc:
            raise ModelRoutingError("MALFORMED_CANDIDATE", f"missing {exc.args[0]}") from exc
        except ModelRoutingError as exc:
            raise ModelRoutingError("MALFORMED_CANDIDATE", str(exc)) from exc

    def canonical_json(self) -> str:
        return contracts.canonical_json(self.to_dict())


@dataclass(frozen=True)
class CandidateAssessment:
    """Decision-time, privacy-safe evaluation of one candidate."""

    provider: str
    model: str
    tier: str
    capabilities: tuple[str, ...]
    cost_class: str
    roles: tuple[str, ...]
    available: bool
    policy_eligible: bool
    eligible: bool
    fallback_eligible: bool
    exclusion_reason: str | None
    quality_score: float | None
    risk_suitable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "capabilities": list(self.capabilities),
            "cost_class": self.cost_class,
            "roles": list(self.roles),
            "available": self.available,
            "policy_eligible": self.policy_eligible,
            "eligible": self.eligible,
            "fallback_eligible": self.fallback_eligible,
            "exclusion_reason": self.exclusion_reason,
            "quality_score": self.quality_score,
            "risk_suitable": self.risk_suitable,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CandidateAssessment:
        if not isinstance(data, Mapping):
            raise ModelRoutingError("MALFORMED_DECISION", "candidate assessment must be an object")
        try:
            return cls(
                provider=_text(data["provider"], "provider"),
                model=_text(data["model"], "model"),
                tier=_label(data["tier"], "tier", TIERS),
                capabilities=_bounded_labels(
                    data.get("capabilities", ()), "capabilities", limit=MAX_CAPABILITIES
                ),
                cost_class=_label(data["cost_class"], "cost_class", COST_CLASSES),
                roles=_roles(data.get("roles", ())),
                available=_strict_bool(data["available"], "available"),
                policy_eligible=_strict_bool(data["policy_eligible"], "policy_eligible"),
                eligible=_strict_bool(data["eligible"], "eligible"),
                fallback_eligible=_strict_bool(data["fallback_eligible"], "fallback_eligible"),
                exclusion_reason=data.get("exclusion_reason"),
                quality_score=_optional_score(data.get("quality_score"), "quality_score"),
                risk_suitable=_strict_bool(data["risk_suitable"], "risk_suitable"),
            )
        except KeyError as exc:
            raise ModelRoutingError("MALFORMED_DECISION", f"missing {exc.args[0]}") from exc


@dataclass(frozen=True)
class ModelDecision:
    """Bounded Brain-owned model-selection result.

    No task transcript is retained.  ``decision_id`` is deterministic for the
    same task hash, identity, candidate metadata, policy, and selection inputs;
    ``created_at`` is intentionally excluded from that ID.
    """

    decision_id: str
    task_hash: str
    task_id: str
    brain_session_id: str
    host_session_id: str
    project_id: str
    bot_name: str
    bot_role: str
    policy_profile: str
    candidate_set_hash: str
    eligible_candidates: tuple[CandidateAssessment, ...]
    selected_provider: str | None
    selected_model: str | None
    selected_tier: str | None
    selected_cost_class: str | None
    selected_routes: tuple[str, ...]
    risk_class: str
    risk_score: int
    capability_requirements: tuple[str, ...]
    economic_class: str | None
    reason_code: str
    fallback_used: bool
    fallback_provider: str | None
    fallback_model: str | None
    fallback_reason: str | None
    original_selected_provider: str | None
    original_selected_model: str | None
    original_selected_tier: str | None
    status: str
    failure_code: str | None
    routing_error: bool
    created_at: str
    escalation: bool = False

    def validate(self) -> ModelDecision:
        if len(self.eligible_candidates) > MAX_CANDIDATES:
            raise ModelRoutingError("DECISION_TOO_LARGE", "candidate list exceeds bound")
        if len(self.task_hash) != 16 or any(
            char not in "0123456789abcdef" for char in self.task_hash
        ):
            raise ModelRoutingError(
                "MALFORMED_DECISION", "task_hash must be 16 lowercase hex chars"
            )
        if not isinstance(self.risk_score, int) or self.risk_score < 0:
            raise ModelRoutingError("MALFORMED_DECISION", "risk_score must be non-negative")
        if not isinstance(self.escalation, bool):
            raise ModelRoutingError("MALFORMED_DECISION", "escalation must be a boolean")
        _label(self.risk_class, "risk_class", RISK_CLASSES)
        if self.status not in {"selected", "failed"}:
            raise ModelRoutingError("MALFORMED_DECISION", "invalid decision status")
        if self.status == "selected":
            if not self.selected_provider or not self.selected_model or not self.selected_tier:
                raise ModelRoutingError(
                    "MALFORMED_DECISION", "selected decision is missing model identity"
                )
            selected = [
                candidate
                for candidate in self.eligible_candidates
                if candidate.provider == self.selected_provider
                and candidate.model == self.selected_model
            ]
            if not selected:
                raise ModelRoutingError(
                    "MALFORMED_DECISION", "selected model is not an eligible candidate"
                )
            selected_candidate = selected[0]
            if not (
                selected_candidate.eligible
                or (self.fallback_used and selected_candidate.fallback_eligible)
            ):
                raise ModelRoutingError(
                    "MALFORMED_DECISION", "selected model is not an eligible candidate"
                )
            if self.selected_tier != selected_candidate.tier:
                raise ModelRoutingError("MALFORMED_DECISION", "selected tier mismatch")
            if (
                self.selected_cost_class is None
                or self.selected_cost_class != selected_candidate.cost_class
                or self.economic_class != self.selected_cost_class
            ):
                raise ModelRoutingError("MALFORMED_DECISION", "selected economic class mismatch")
        elif any(
            value is not None
            for value in (self.selected_provider, self.selected_model, self.selected_tier)
        ):
            raise ModelRoutingError("MALFORMED_DECISION", "failed decision must not select a model")
        if self.fallback_used:
            if self.status != "selected":
                raise ModelRoutingError("MALFORMED_DECISION", "failed decision cannot use fallback")
            if not self.fallback_provider or not self.fallback_model or not self.fallback_reason:
                raise ModelRoutingError("MALFORMED_DECISION", "fallback decision is incomplete")
            if not self.original_selected_model or not self.original_selected_provider:
                raise ModelRoutingError("MALFORMED_DECISION", "fallback lacks original selection")
            if (
                self.fallback_provider != self.selected_provider
                or self.fallback_model != self.selected_model
            ):
                raise ModelRoutingError("MALFORMED_DECISION", "fallback identity mismatch")
            original = [
                candidate
                for candidate in self.eligible_candidates
                if candidate.provider == self.original_selected_provider
                and candidate.model == self.original_selected_model
            ]
            if not original or self.original_selected_tier != original[0].tier:
                raise ModelRoutingError("MALFORMED_DECISION", "original selection mismatch")
        elif any(
            value is not None
            for value in (self.fallback_provider, self.fallback_model, self.fallback_reason)
        ):
            raise ModelRoutingError("MALFORMED_DECISION", "unexpected fallback identity")

        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_ROUTING_SCHEMA_VERSION,
            "decision_id": self.decision_id,
            "task_hash": self.task_hash,
            "task_id": self.task_id,
            "brain_session_id": self.brain_session_id,
            "host_session_id": self.host_session_id,
            "project_id": self.project_id,
            "bot_name": self.bot_name,
            "bot_role": self.bot_role,
            "policy_profile": self.policy_profile,
            "candidate_set_hash": self.candidate_set_hash,
            "eligible_candidates": [candidate.to_dict() for candidate in self.eligible_candidates],
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "selected_tier": self.selected_tier,
            "selected_cost_class": self.selected_cost_class,
            "selected_routes": list(self.selected_routes),
            "risk_class": self.risk_class,
            "risk_score": self.risk_score,
            "capability_requirements": list(self.capability_requirements),
            "economic_class": self.economic_class,
            "reason_code": self.reason_code,
            "fallback_used": self.fallback_used,
            "fallback_provider": self.fallback_provider,
            "fallback_model": self.fallback_model,
            "fallback_reason": self.fallback_reason,
            "original_selected_provider": self.original_selected_provider,
            "original_selected_model": self.original_selected_model,
            "original_selected_tier": self.original_selected_tier,
            "status": self.status,
            "failure_code": self.failure_code,
            "routing_error": self.routing_error,
            "escalation": self.escalation,
            "created_at": self.created_at,
        }

    def canonical_json(self) -> str:
        return contracts.canonical_json(self.to_dict())

    def canonical_hash(self) -> str:
        return contracts.stable_content_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModelDecision:
        if not isinstance(data, Mapping):
            raise ModelRoutingError("MALFORMED_DECISION", "decision must be an object")
        try:
            decision = cls(
                decision_id=_text(data["decision_id"], "decision_id"),
                task_hash=_text(data["task_hash"], "task_hash"),
                task_id=_text(data.get("task_id", ""), "task_id", required=False),
                brain_session_id=_text(
                    data.get("brain_session_id", ""), "brain_session_id", required=False
                ),
                host_session_id=_text(
                    data.get("host_session_id", ""), "host_session_id", required=False
                ),
                project_id=_text(data.get("project_id", ""), "project_id", required=False),
                bot_name=_text(data.get("bot_name", ""), "bot_name", required=False),
                bot_role=_text(data.get("bot_role", "normal"), "bot_role"),
                policy_profile=_text(data.get("policy_profile", "default"), "policy_profile"),
                candidate_set_hash=_text(data["candidate_set_hash"], "candidate_set_hash"),
                eligible_candidates=tuple(
                    CandidateAssessment.from_dict(item)
                    for item in data.get("eligible_candidates", ())
                ),
                selected_provider=data.get("selected_provider"),
                selected_model=data.get("selected_model"),
                selected_tier=data.get("selected_tier"),
                selected_cost_class=data.get("selected_cost_class"),
                selected_routes=tuple(data.get("selected_routes", ())),
                risk_class=data["risk_class"],
                risk_score=data["risk_score"],
                capability_requirements=tuple(data.get("capability_requirements", ())),
                economic_class=data.get("economic_class"),
                reason_code=_text(data["reason_code"], "reason_code"),
                fallback_used=bool(data["fallback_used"]),
                fallback_provider=data.get("fallback_provider"),
                fallback_model=data.get("fallback_model"),
                fallback_reason=data.get("fallback_reason"),
                original_selected_provider=data.get("original_selected_provider"),
                original_selected_model=data.get("original_selected_model"),
                original_selected_tier=data.get("original_selected_tier"),
                status=data["status"],
                failure_code=data.get("failure_code"),
                routing_error=bool(data.get("routing_error", False)),
                escalation=bool(data.get("escalation", False)),
                created_at=_text(data["created_at"], "created_at"),
            )
            return decision.validate()
        except KeyError as exc:
            raise ModelRoutingError("MALFORMED_DECISION", f"missing {exc.args[0]}") from exc


def _normalise_candidate(value: ModelCandidate | Mapping[str, Any]) -> ModelCandidate:
    if isinstance(value, ModelCandidate):
        return value
    return ModelCandidate.from_dict(value)


def _normalise_justifications(values: Sequence[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, Sequence):
        raise ModelRoutingError(
            "MALFORMED_ROUTING_INPUT", "premium_justification must be a sequence"
        )
    out = tuple(sorted({_capability(value) for value in values}))
    unknown = sorted(set(out) - _PREMIUM_JUSTIFICATION_CODES)
    if unknown:
        raise ModelRoutingError("INVALID_PREMIUM_JUSTIFICATION", ", ".join(unknown))
    return out


def _derive_capabilities(task: str, explicit: Sequence[str]) -> tuple[str, ...]:
    values = {_capability(value) for value in explicit}
    lowered = task.casefold()
    for capability, markers in _CAPABILITY_MARKERS:
        if any(marker in lowered for marker in markers):
            values.add(capability)
    return tuple(sorted(values))


def _derive_premium_reasons(
    task: str,
    risk_class: str,
    capabilities: Sequence[str],
    role: str,
    *,
    repeated_failure: bool,
    ambiguity: bool,
    explicit: Sequence[str],
) -> tuple[str, ...]:
    reasons = set(explicit)
    lowered = task.casefold()
    if risk_class == "HIGH":
        reasons.add("high_risk")
    elif risk_class == "CRITICAL":
        reasons.add("critical_risk")
    if any(capability in _PREMIUM_CAPABILITIES for capability in capabilities):
        reasons.add("capability_requirement")
    if any(marker in lowered for marker in _PREMIUM_MARKERS):
        if "architecture" in lowered or "architectural" in lowered:
            reasons.add("architecture")
        elif "security" in lowered:
            reasons.add("security")
    if repeated_failure:
        reasons.add("repeated_failure")
    if ambiguity:
        reasons.add("ambiguity")
    if role == "hard_orchestrator":
        reasons.add("role_policy")
    return tuple(sorted(reasons))


def _minimum_tier(
    task: str,
    risk_class: str,
    role: str,
    capabilities: Sequence[str],
    explicit_minimum: str | None,
) -> str:
    required = _TIER_RANK[_ROLE_MINIMUM_TIER.get(role, "efficient")]
    if risk_class in {"HIGH", "CRITICAL"}:
        required = max(required, _TIER_RANK["premium"])
    elif risk_class == "MEDIUM":
        required = max(required, _TIER_RANK["balanced"])
    lowered = task.casefold()
    if any(marker in lowered for marker in _BALANCED_MARKERS):
        required = max(required, _TIER_RANK["balanced"])
    if any(marker in lowered for marker in _PREMIUM_MARKERS):
        required = max(required, _TIER_RANK["premium"])
    if any(capability in _PREMIUM_CAPABILITIES for capability in capabilities):
        required = max(required, _TIER_RANK["premium"])
    if explicit_minimum is not None:
        required = max(required, _TIER_RANK[explicit_minimum])
    return TIERS[required]


def _risk_inputs(
    repo: Path | None,
    files_touched: Sequence[str],
    explicit_class: str | None,
    explicit_score: int | None,
    user_criticality: str | None,
) -> tuple[str, int]:
    assessed = risk.assess_risk(repo or Path.cwd(), list(files_touched), user_criticality)
    risk_class = explicit_class or assessed["level"]
    risk_score = explicit_score if explicit_score is not None else int(assessed["score"])
    _label(risk_class, "risk_class", RISK_CLASSES)
    if not isinstance(risk_score, int) or risk_score < 0:
        raise ModelRoutingError(
            "MALFORMED_ROUTING_INPUT", "risk_score must be a non-negative integer"
        )
    return risk_class, risk_score


def _route_skills(home: Path | None, task: str) -> tuple[tuple[str, ...], bool]:
    if home is None:
        return (), False
    try:
        result = router.route(home, task)
        selected = result.get("selected", [])
        if not isinstance(selected, list) or any(not isinstance(value, str) for value in selected):
            return (), True
        return tuple(selected), False
    except Exception:
        return (), True


def p_success(
    model_or_home: Any = None,
    task_or_model: Any = None,
    task_signature_arg: Any = None,
    *,
    home: Path | str | None = None,
    min_samples: int = 1,
) -> float:
    """Beta posterior mean (s + 1) / (n + 2) over outcomes from last 90 days.

    Fallback hierarchy:
    1. Exact (model_id, task_signature)
    2. (model_family, *)
    3. Default 0.5
    """
    resolved_home: Path | str | None = home
    resolved_model: Any = model_or_home
    resolved_sig: Any = task_or_model

    if task_signature_arg is not None:
        resolved_home = model_or_home
        resolved_model = task_or_model
        resolved_sig = task_signature_arg
    elif home is None and isinstance(model_or_home, Path):
        resolved_home = model_or_home
        resolved_model = task_or_model
        resolved_sig = None

    if isinstance(resolved_model, ModelCandidate):
        model_id = resolved_model.model
    else:
        model_id = str(resolved_model or "").strip()

    if not model_id:
        return 0.5

    if resolved_sig is not None:
        sig_str = str(resolved_sig.value if isinstance(resolved_sig, TaskClass) else resolved_sig).strip()
    else:
        sig_str = "implementation"

    if resolved_home is None:
        env_home = os.environ.get("SECOND_BRAIN_HOME")
        if env_home:
            resolved_home = Path(env_home)

    if resolved_home is None:
        return 0.5

    home_path = Path(resolved_home)
    dbfile = db.db_path(home_path)
    if not dbfile.is_file():
        return 0.5

    try:
        if db.pending_migrations(dbfile):
            db.migrate(dbfile)
        conn = db.connect(dbfile)
        try:
            cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            row = conn.execute(
                """SELECT SUM(success), COUNT(*)
                   FROM model_skill_outcomes
                   WHERE model_id = ? AND (skill_name = ? OR task_hash = ?) AND created_at >= ?""",
                (model_id, sig_str, sig_str, cutoff),
            ).fetchone()
            s = row[0] or 0
            n = row[1] or 0
            if n >= min_samples:
                return round((s + 1) / (n + 2), 4)

            fam_row = conn.execute(
                "SELECT family FROM model_profiles WHERE model_id = ?",
                (model_id,),
            ).fetchone()
            family = fam_row[0] if (fam_row and fam_row[0]) else (model_id.split("-")[0] if "-" in model_id else "")
            if family:
                row_fam = conn.execute(
                    """SELECT SUM(mso.success), COUNT(*)
                       FROM model_skill_outcomes mso
                       JOIN model_profiles mp ON mso.model_id = mp.model_id
                       WHERE (mp.family = ? OR mso.model_id LIKE ?) AND mso.created_at >= ?""",
                    (family, f"{family}%", cutoff),
                ).fetchone()
                s_fam = row_fam[0] or 0
                n_fam = row_fam[1] or 0
                if n_fam >= min_samples:
                    return round((s_fam + 1) / (n_fam + 2), 4)

            return 0.5
        finally:
            conn.close()
    except Exception:
        return 0.5


def _quality_score(
    home: Path | None,
    candidate: ModelCandidate,
    selected_routes: Sequence[str],
    ambiguous_models: frozenset[str] = frozenset(),
    task_signature: str | TaskClass | None = None,
) -> float | None:
    if candidate.quality_score is not None:
        return candidate.quality_score
    if candidate.model in ambiguous_models:
        return None
    if home is None:
        return None
    db_file = db.db_path(Path(home))
    if not db_file.is_file():
        return None

    sig = task_signature
    if sig is None and selected_routes:
        sig = selected_routes[0]

    try:
        if db.pending_migrations(db_file):
            db.migrate(db_file)
        conn = db.connect(db_file)
        try:
            cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            sig_str = str(sig.value if isinstance(sig, TaskClass) else (sig or "implementation")).strip()
            row = conn.execute(
                """SELECT COUNT(*) FROM model_skill_outcomes
                   WHERE model_id = ? AND (skill_name = ? OR task_hash = ?) AND created_at >= ?""",
                (candidate.model, sig_str, sig_str, cutoff),
            ).fetchone()
            if row and row[0] > 0:
                return p_success(candidate.model, sig_str, home=home)
            fam_row = conn.execute(
                "SELECT family FROM model_profiles WHERE model_id = ?",
                (candidate.model,),
            ).fetchone()
            family = fam_row[0] if (fam_row and fam_row[0]) else (candidate.model.split("-")[0] if "-" in candidate.model else "")
            if family:
                fam_cnt = conn.execute(
                    """SELECT COUNT(*) FROM model_skill_outcomes mso
                       JOIN model_profiles mp ON mso.model_id = mp.model_id
                       WHERE (mp.family = ? OR mso.model_id LIKE ?) AND mso.created_at >= ?""",
                    (family, f"{family}%", cutoff),
                ).fetchone()
                if fam_cnt and fam_cnt[0] > 0:
                    return p_success(candidate.model, sig_str, home=home)
        finally:
            conn.close()
    except Exception:
        pass
    return None


def _assessment(
    candidate: ModelCandidate,
    *,
    role: str,
    risk_class: str,
    capabilities: Sequence[str],
    minimum_tier: str,
    maximum_tier: str,
    max_cost_class: str,
    premium_reasons: Sequence[str],
    quality_score: float | None,
    min_quality_score: float | None,
) -> CandidateAssessment:
    reasons: list[str] = []
    tier_rank = _TIER_RANK[candidate.tier]
    if candidate.roles and role not in candidate.roles:
        reasons.append("ROLE_NOT_ALLOWED")
    if tier_rank < _TIER_RANK[minimum_tier]:
        reasons.append("TIER_BELOW_REQUIRED")
    if tier_rank > _TIER_RANK[maximum_tier]:
        reasons.append("TIER_ABOVE_ROLE_MAXIMUM")
    if _COST_RANK[candidate.cost_class] > _COST_RANK[max_cost_class]:
        reasons.append("COST_POLICY_EXCLUDED")
    if _RISK_RANK[candidate.max_risk] < _RISK_RANK[risk_class]:
        reasons.append("RISK_CAPABILITY_MISMATCH")
    if not set(capabilities).issubset(set(candidate.capabilities)):
        reasons.append("CAPABILITY_MISMATCH")
    if candidate.tier == "premium" and not premium_reasons:
        reasons.append("PREMIUM_NOT_JUSTIFIED")
    if min_quality_score is not None and (
        quality_score is None or quality_score < min_quality_score
    ):
        reasons.append("QUALITY_BELOW_MINIMUM")
    static_eligible = not reasons
    availability_reason = candidate.availability_reason
    available = candidate.is_available
    if not available and static_eligible:
        exclusion_reason = availability_reason
    elif reasons:
        exclusion_reason = reasons[0]
    else:
        exclusion_reason = None
    # A lower tier may be used only as an explicitly recorded availability
    # fallback.  It still must satisfy role, risk, capability, cost, premium,
    # and quality policy.
    fallback_reasons = [reason for reason in reasons if reason != "TIER_BELOW_REQUIRED"]
    fallback_eligible = not fallback_reasons and available
    return CandidateAssessment(
        provider=candidate.provider,
        model=candidate.model,
        tier=candidate.tier,
        capabilities=candidate.capabilities,
        cost_class=candidate.cost_class,
        roles=candidate.roles,
        available=available,
        policy_eligible=static_eligible,
        eligible=static_eligible and available,
        fallback_eligible=fallback_eligible,
        exclusion_reason=exclusion_reason,
        quality_score=quality_score,
        risk_suitable="RISK_CAPABILITY_MISMATCH" not in reasons,
    )


def _sort_key(candidate: CandidateAssessment) -> tuple[float, int, str, str]:
    p = candidate.quality_score if candidate.quality_score is not None and candidate.quality_score > 0 else 0.5
    price_rank = _PRICE_CLASS_RANK.get(candidate.cost_class, 1)
    expected_cost = price_rank / p
    return (
        expected_cost,
        _TIER_RANK[candidate.tier],
        candidate.provider,
        candidate.model,
    )


def _decision_id(seed: Mapping[str, Any]) -> str:
    return f"model-decision-{contracts.stable_content_hash(seed)[:24]}"


def _candidate_set_hash(candidates: Sequence[ModelCandidate]) -> str:
    values = sorted(
        (candidate.to_dict() for candidate in candidates),
        key=lambda item: (item["provider"], item["model"]),
    )
    return contracts.stable_content_hash(values)


def route_model(
    task: str,
    candidates: Sequence[ModelCandidate | Mapping[str, Any]],
    *,
    role: str = "normal",
    bot_role: str | None = None,
    task_id: str = "",
    brain_session_id: str = "",
    host_session_id: str = "",
    project_id: str = "",
    bot_name: str = "",
    policy_profile: str = "default",
    home: Path | str | None = None,
    repo: Path | str | None = None,
    repo_root: Path | str | None = None,
    files_touched: Sequence[str] = (),
    capability_requirements: Sequence[str] = (),
    required_capabilities: Sequence[str] | None = None,
    risk_class: str | None = None,
    risk_level: str | None = None,
    risk_score: int | None = None,
    user_criticality: str | None = None,
    minimum_tier: str | None = None,
    max_tier: str | None = None,
    max_cost_class: str = "high",
    premium_authorized: bool = False,
    premium_justification: Sequence[str] | str | None = None,
    repeated_failure: bool = False,
    ambiguity: bool = False,
    min_quality_score: float | None = None,
    created_at: str | None = None,
    verifier_failed: bool = False,
    previous_tier: str | None = None,
    previous_model: str | None = None,
    previous_decision: ModelDecision | None = None,
    stage: str | None = None,
    rollout_stage: str | None = None,
    task_class: str | TaskClass | None = None,
) -> ModelDecision:
    """Select one deterministic model decision from bounded candidate metadata.

    ``premium_authorized`` is intentionally not sufficient on its own: a
    bounded justification code or objective task/risk/capability/role signal is
    still required.  The argument exists so a later adapter can distinguish
    policy authorization from a host's requested model without letting the host
    choose the result.
    """
    task = _text(task, "task")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", "candidates must be a sequence")
    if len(candidates) > MAX_CANDIDATES:
        raise ModelRoutingError("ROUTING_INPUT_TOO_LARGE", "candidate list exceeds bound")
    normalized = tuple(_normalise_candidate(value) for value in candidates)
    candidate_hash = _candidate_set_hash(normalized)
    identities = [(candidate.provider, candidate.model) for candidate in normalized]
    if len(set(identities)) != len(identities):
        raise ModelRoutingError("DUPLICATE_CANDIDATE", "provider/model candidates must be unique")
    model_counts: dict[str, int] = {}
    for candidate in normalized:
        model_counts[candidate.model] = model_counts.get(candidate.model, 0) + 1
    ambiguous_models = frozenset(
        model for model, count in model_counts.items() if count > 1
    )

    role_value = _text(bot_role or role, "bot_role").strip().lower()
    if role_value not in _ROLE_MINIMUM_TIER:
        role_value = "normal"
    if (
        not isinstance(policy_profile, str)
        or not policy_profile.strip()
        or len(policy_profile) > MAX_TEXT_CHARS
    ):
        raise ModelRoutingError("MALFORMED_ROUTING_INPUT", "invalid policy_profile")
    trusted_policy = role_value in _TRUSTED_POLICY_ROLES
    home_path = Path(home) if home is not None else None
    repo_value = repo_root if repo_root is not None else repo
    repo_path = Path(repo_value) if repo_value is not None else None
    explicit_caps = (
        required_capabilities if required_capabilities is not None else capability_requirements
    ) if trusted_policy else ()
    capabilities = _derive_capabilities(task, explicit_caps)
    if len(capabilities) > MAX_CAPABILITIES:
        raise ModelRoutingError("ROUTING_INPUT_TOO_LARGE", "capability requirements exceed bound")
    risk_value = (risk_class or risk_level) if trusted_policy else None
    if risk_value is not None:
        risk_value = _label(risk_value, "risk_class", RISK_CLASSES)
    risk_value, risk_points = _risk_inputs(
        repo_path,
        files_touched,
        risk_value,
        risk_score if trusted_policy else None,
        user_criticality if trusted_policy else None,
    )
    selected_routes, routing_error = _route_skills(home_path, task)
    justifications = (
        _normalise_justifications(premium_justification) if trusted_policy else ()
    )
    premium_reasons = _derive_premium_reasons(
        task,
        risk_value,
        capabilities,
        role_value,
        repeated_failure=repeated_failure if trusted_policy else False,
        ambiguity=ambiguity if trusted_policy else False,
        explicit=justifications,
    )
    if premium_authorized and not premium_reasons:
        # Authorization without a reason must never turn a routine task into a
        # premium request.  Keep the value observable only through the outcome,
        # not as a second policy path.
        premium_reasons = ()
    if previous_decision is not None:
        verifier_failed = True
        if previous_tier is None:
            previous_tier = previous_decision.selected_tier
        if previous_model is None:
            previous_model = previous_decision.selected_model

    t_class = (
        classify_task(task)
        if task_class is None
        else (task_class.value if isinstance(task_class, TaskClass) else str(task_class))
    )
    risk_floor = (
        _label(minimum_tier, "minimum_tier", TIERS)
        if trusted_policy and minimum_tier
        else _minimum_tier(task, risk_value, role_value, capabilities, None)
    )

    minimum = risk_floor
    escalation = False
    cost_limit = _label(max_cost_class, "max_cost_class", COST_CLASSES)

    if verifier_failed and previous_tier:
        prev_idx = _TIER_RANK.get(previous_tier, 0)
        escalated_idx = min(prev_idx + 1, len(TIERS) - 1)
        higher_tier_candidates = [
            c
            for c in normalized
            if _TIER_RANK[c.tier] > prev_idx and _COST_RANK[c.cost_class] <= _COST_RANK[cost_limit]
        ]
        if higher_tier_candidates:
            effective_min_idx = max(_TIER_RANK[risk_floor], escalated_idx)
            minimum = TIERS[effective_min_idx]
            if _TIER_RANK[minimum] > prev_idx:
                escalation = True
                premium_reasons = tuple(sorted(set(premium_reasons) | {"repeated_failure"}))

    maximum = _label(max_tier or _ROLE_MAXIMUM_TIER.get(role_value, "premium"), "max_tier", TIERS)
    if _TIER_RANK[maximum] < _TIER_RANK[minimum]:
        raise ModelRoutingError("ROLE_POLICY_CONFLICT", "max_tier is below minimum_tier")
    assessed: list[CandidateAssessment] = []
    for candidate in normalized:
        quality = _quality_score(
            home_path, candidate, selected_routes, ambiguous_models, task_signature=t_class
        )
        assessed.append(
            _assessment(
                candidate,
                role=role_value,
                risk_class=risk_value,
                capabilities=capabilities,
                minimum_tier=minimum,
                maximum_tier=maximum,
                max_cost_class=cost_limit,
                premium_reasons=premium_reasons,
                quality_score=quality,
                min_quality_score=min_quality_score if trusted_policy else None,
            )
        )
    assessments = tuple(sorted(assessed, key=lambda item: (item.provider, item.model)))
    policy_candidates = [item for item in assessments if item.policy_eligible]
    preferred = sorted(policy_candidates, key=_sort_key)
    original = preferred[0] if preferred else None
    chosen: CandidateAssessment | None = None
    fallback_used = False
    fallback_reason: str | None = None
    if original is not None and original.eligible:
        chosen = original
    elif original is not None:
        fallback_candidates = sorted(
            [item for item in assessments if item.fallback_eligible], key=_sort_key
        )
        if fallback_candidates:
            chosen = fallback_candidates[0]
            fallback_used = True
            fallback_reason = original.exclusion_reason or "MODEL_UNAVAILABLE"

    status = "selected" if chosen is not None else "failed"
    failure_code = None
    if chosen is None:
        failure_code = "NO_AVAILABLE_MODEL" if original is not None else "NO_ELIGIBLE_MODEL"
    if escalation:
        reason_code = "VERIFIER_FAILURE_CASCADE"
    elif fallback_used:
        reason_code = "MODEL_UNAVAILABLE_FALLBACK"
    elif failure_code:
        reason_code = failure_code
    elif (
        premium_reasons and chosen is not None and _TIER_RANK[chosen.tier] >= _TIER_RANK["premium"]
    ):
        reason_code = "PREMIUM_ESCALATION_JUSTIFIED"
    elif (
        chosen is not None
        and _TIER_RANK[chosen.tier] > _TIER_RANK[_ROLE_MINIMUM_TIER.get(role_value, "efficient")]
    ):
        reason_code = "TASK_OR_RISK_ESCALATION"
    else:
        reason_code = "LOWEST_COST_ELIGIBLE"

    effective_stage = stage or rollout_stage or "OFF"
    if (
        chosen is not None
        and not fallback_used
        and not escalation
        and t_class in {TaskClass.TRIVIAL, TaskClass.NAVIGATION, "trivial", "navigation"}
        and effective_stage in {"CANARY", "ACTIVE"}
    ):
        eligible_candidates = [item for item in assessments if item.eligible]
        if len(eligible_candidates) > 1:
            rand_choice, propensity, randomized = decisions.randomize(
                chosen,
                eligible_candidates,
                epsilon=0.05,
                rng_seed=contracts.stable_content_hash({"task": task, "candidates": candidate_hash}),
            )
            chosen = rand_choice
            if randomized:
                reason_code = "EXPLORATION_RANDOMIZED"

    if escalation and home_path is not None and brain_session_id:
        try:
            decisions.record(
                home_path,
                kind="routing",
                session_id=brain_session_id,
                task_id=task_id or None,
                chosen={
                    "escalation": True,
                    "model": chosen.model if chosen else None,
                    "tier": chosen.tier if chosen else None,
                    "escalated_from_tier": previous_tier,
                },
                alternatives=[
                    {"model": c.model, "tier": c.tier, "cost_class": c.cost_class}
                    for c in assessments
                ],
                propensity=1.0,
                randomized=False,
                policy_version="v2.0",
                stage=effective_stage if effective_stage in decisions._ROLLOUT_STAGES else "OFF",
                inputs={"task_hash": crossmodel.task_hash(task), "escalation": True},
            )
        except Exception:
            pass

    timestamp = created_at or datetime.now(UTC).isoformat()
    _text(timestamp, "created_at")
    seed = {
        "schema_version": MODEL_ROUTING_SCHEMA_VERSION,
        "task_hash": crossmodel.task_hash(task),
        "task_id": task_id,
        "brain_session_id": brain_session_id,
        "host_session_id": host_session_id,
        "project_id": project_id,
        "bot_name": bot_name,
        "bot_role": role_value,
        "policy_profile": policy_profile,
        "candidate_set_hash": candidate_hash,
        "risk_class": risk_value,
        "risk_score": risk_points,
        "capability_requirements": capabilities,
        "selected_routes": selected_routes,
        "minimum_tier": minimum,
        "maximum_tier": maximum,
        "max_cost_class": cost_limit,
        "premium_reasons": premium_reasons,
        "selected_provider": chosen.provider if chosen else None,
        "selected_model": chosen.model if chosen else None,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "escalation": escalation,
    }
    decision = ModelDecision(
        decision_id=_decision_id(seed),
        task_hash=crossmodel.task_hash(task),
        task_id=_text(task_id, "task_id", required=False),
        brain_session_id=_text(brain_session_id, "brain_session_id", required=False),
        host_session_id=_text(host_session_id, "host_session_id", required=False),
        project_id=_text(project_id, "project_id", required=False),
        bot_name=_text(bot_name, "bot_name", required=False),
        bot_role=role_value,
        policy_profile=_text(policy_profile, "policy_profile"),
        candidate_set_hash=candidate_hash,
        eligible_candidates=assessments,
        selected_provider=chosen.provider if chosen else None,
        selected_model=chosen.model if chosen else None,
        selected_tier=chosen.tier if chosen else None,
        selected_cost_class=chosen.cost_class if chosen else None,
        selected_routes=selected_routes,
        risk_class=risk_value,
        risk_score=risk_points,
        capability_requirements=capabilities,
        economic_class=chosen.cost_class if chosen else None,
        reason_code=reason_code,
        fallback_used=fallback_used,
        fallback_provider=chosen.provider if fallback_used and chosen else None,
        fallback_model=chosen.model if fallback_used and chosen else None,
        fallback_reason=fallback_reason,
        original_selected_provider=original.provider if original else None,
        original_selected_model=original.model if original else None,
        original_selected_tier=original.tier if original else None,
        status=status,
        failure_code=failure_code,
        routing_error=routing_error,
        escalation=escalation,
        created_at=timestamp,
    )
    return decision.validate()


# Friendly aliases for callers that use the plan's selector terminology.
select_model = route_model
select_model_decision = route_model

def route_cascade(
    task_or_decision: str | ModelDecision,
    candidates: Sequence[ModelCandidate | Mapping[str, Any]],
    *,
    verifier_failed: bool = True,
    verifier_result: dict[str, Any] | None = None,
    previous_tier: str | None = None,
    previous_model: str | None = None,
    **kwargs: Any,
) -> ModelDecision:
    """Cascade routing retry one tier up following a verifier failure."""
    if verifier_result is not None:
        verifier_failed = not verifier_result.get("completion_allowed", True)

    if isinstance(task_or_decision, ModelDecision):
        task_text = kwargs.pop("task", "") or task_or_decision.task_hash
        prev_tier = previous_tier or task_or_decision.selected_tier
        prev_model = previous_model or task_or_decision.selected_model
        return route_model(
            task_text,
            candidates,
            verifier_failed=verifier_failed,
            previous_tier=prev_tier,
            previous_model=prev_model,
            previous_decision=task_or_decision,
            **kwargs,
        )
    return route_model(
        str(task_or_decision),
        candidates,
        verifier_failed=verifier_failed,
        previous_tier=previous_tier,
        previous_model=previous_model,
        **kwargs,
    )


__all__ = [
    "COST_CLASSES",
    "MAX_CANDIDATES",
    "MODEL_ROUTING_SCHEMA_VERSION",
    "RISK_CLASSES",
    "TIERS",
    "TASK_CLASSES",
    "TaskClass",
    "CandidateAssessment",
    "ModelCandidate",
    "ModelDecision",
    "ModelRoutingError",
    "classify_task",
    "map_task_class",
    "p_success",
    "route_cascade",
    "route_model",
    "select_model",
    "select_model_decision",
]
