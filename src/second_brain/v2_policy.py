"""Strict v2 policy loading and migration entry point."""

from __future__ import annotations

import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from . import db
from .errors import BrainError

REPOSITORY_HOME = Path(__file__).resolve().parents[2]
_POLICY_RELATIVE_PATH = Path("config") / "v2.toml"


class RolloutStage(StrEnum):
    OFF = "OFF"
    SHADOW = "SHADOW"
    ADVISORY = "ADVISORY"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"


_STAGE_ORDER = {stage: index for index, stage in enumerate(RolloutStage)}


class _FrozenRollout(dict[str, RolloutStage]):
    """A dict-compatible rollout mapping with every mutator disabled."""

    def __setitem__(self, key: str, value: RolloutStage) -> None:
        raise TypeError("rollout mapping is immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("rollout mapping is immutable")

    def clear(self) -> None:
        raise TypeError("rollout mapping is immutable")

    def pop(self, key: str, default: object = None) -> RolloutStage:
        raise TypeError("rollout mapping is immutable")

    def popitem(self) -> tuple[str, RolloutStage]:
        raise TypeError("rollout mapping is immutable")

    def setdefault(self, key: str, default: RolloutStage | None = None) -> RolloutStage:
        raise TypeError("rollout mapping is immutable")

    def update(self, *args: object, **kwargs: RolloutStage) -> None:
        raise TypeError("rollout mapping is immutable")

    def __ior__(self, other: object) -> _FrozenRollout:
        raise TypeError("rollout mapping is immutable")

    def __deepcopy__(self, memo: dict[int, object]) -> _FrozenRollout:
        return _FrozenRollout(self)


_TOP_KEYS = frozenset(
    {
        "schema_version",
        "rollout",
        "admission",
        "retrieval",
        "brainstem",
        "learning",
        "culture",
        "frontier",
        "verification",
        "economics",
        "prices",
        "models",
        "providers",
    }
)
_SECTION_KEYS = {
    "rollout": frozenset(
        {"admission", "retrieval", "brainstem", "learning", "culture", "frontier", "verification"}
    ),
    "admission": frozenset({"min_score"}),
    "retrieval": frozenset({"max_candidates", "top_k", "token_budget"}),
    "brainstem": frozenset({"context_char_budget", "worker_slots", "premium_model_turns"}),
    "learning": frozenset({"surprise_threshold"}),
    "culture": frozenset(),
    "frontier": frozenset({"min_importance"}),
    "verification": frozenset({"floor"}),
    "economics": frozenset({"uncached_in", "cache_read", "cache_write", "alpha", "tau"}),
    "prices": frozenset(),
}
_MODEL_KEYS = frozenset({"context_tokens"})
_PROVIDER_KEYS = frozenset(
    {
        "cache_support",
        "cache_scope",
        "min_cacheable_tokens",
        "ttl_seconds",
        "breakpoints_supported",
        "usage_fields",
        "context_tokens",
        "cache_read",
        "cache_write",
    }
)

_REQUIRED_SECTIONS = frozenset(
    {
        "rollout",
        "admission",
        "retrieval",
        "brainstem",
        "learning",
        "culture",
        "frontier",
        "verification",
    }
)
_REQUIRED_KEYS = {
    "rollout": _SECTION_KEYS["rollout"],
    "admission": frozenset({"min_score"}),
    "retrieval": frozenset({"max_candidates", "top_k", "token_budget"}),
    "brainstem": frozenset({"context_char_budget", "worker_slots", "premium_model_turns"}),
    "learning": frozenset({"surprise_threshold"}),
    "culture": frozenset(),
    "frontier": frozenset({"min_importance"}),
    "verification": frozenset({"floor"}),
}


def _fail(message: str) -> BrainError:
    return BrainError(f"Invalid v2 policy: {message}")


def _table(raw: object, name: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise _fail(f"{name} must be a TOML table")
    return raw


def _check_unknown(table: Mapping[str, object], allowed: frozenset[str], name: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise _fail(f"unknown key(s) in {name}: {', '.join(unknown)}")


def _check_named_tables(
    raw: object,
    name: str,
    allowed: frozenset[str],
) -> None:
    table = _table(raw, name)
    for entry_name, entry in table.items():
        if not isinstance(entry_name, str) or not entry_name.strip():
            raise _fail(f"{name} entry name must be non-empty text")
        _check_unknown(_table(entry, f"{name}.{entry_name}"), allowed, f"{name}.{entry_name}")


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _fail(f"{name} must be a positive integer")
    return value


def _bounded_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{name} must be a number between 0 and 1")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise _fail(f"{name} must be a number between 0 and 1")
    return result


@dataclass(frozen=True)
class V2Policy:
    schema_version: int
    rollout: dict[str, RolloutStage]
    admission_min_score: float
    retrieval_max_candidates: int
    retrieval_top_k: int
    retrieval_token_budget: int
    context_char_budget: int
    worker_slots: int
    premium_model_turns: int
    surprise_threshold: float
    frontier_min_importance: float
    verification_floor: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version <= 0
        ):
            raise _fail("schema_version must be a positive integer")
        if not isinstance(self.rollout, Mapping):
            raise _fail("rollout must be a mapping")
        copied: dict[str, RolloutStage] = {}
        for feature, stage in self.rollout.items():
            if not isinstance(feature, str) or not feature.strip() or len(feature) > 256:
                raise _fail("rollout feature must be non-empty text of at most 256 characters")
            try:
                copied[feature] = stage if isinstance(stage, RolloutStage) else RolloutStage(stage)
            except (TypeError, ValueError) as exc:
                raise _fail(f"invalid rollout stage for {feature!r}") from exc
        object.__setattr__(self, "rollout", _FrozenRollout(copied))
        _bounded_float(self.admission_min_score, "admission.min_score")
        for name, value in (
            ("retrieval.max_candidates", self.retrieval_max_candidates),
            ("retrieval.top_k", self.retrieval_top_k),
            ("retrieval.token_budget", self.retrieval_token_budget),
            ("brainstem.context_char_budget", self.context_char_budget),
            ("brainstem.worker_slots", self.worker_slots),
            ("brainstem.premium_model_turns", self.premium_model_turns),
        ):
            _positive_int(value, name)
        if self.retrieval_top_k > self.retrieval_max_candidates:
            raise _fail("retrieval.top_k cannot exceed retrieval.max_candidates")
        _bounded_float(self.surprise_threshold, "learning.surprise_threshold")
        _bounded_float(self.frontier_min_importance, "frontier.min_importance")
        if not isinstance(self.verification_floor, str) or self.verification_floor not in {
            "targeted",
            "full",
        }:
            raise _fail("verification.floor must be 'targeted' or 'full'")


def load_policy(home: Path) -> V2Policy:
    """Load and strictly validate the complete home policy file."""
    path = Path(home) / _POLICY_RELATIVE_PATH
    if not path.is_file():
        raise _fail(f"missing policy file: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise _fail(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise _fail("root must be a TOML table")
    _check_unknown(raw, _TOP_KEYS, "root")
    _check_named_tables(raw.get("models", {}), "models", _MODEL_KEYS)
    _check_named_tables(raw.get("providers", {}), "providers", _PROVIDER_KEYS)
    schema_version = raw.get("schema_version")
    if schema_version != 1 or isinstance(schema_version, bool):
        raise _fail("schema_version must be 1")
    for name, allowed in _SECTION_KEYS.items():
        if name in raw and name != "prices":
            _check_unknown(_table(raw[name], name), allowed, name)
    missing_sections = sorted(_REQUIRED_SECTIONS - set(raw))
    if missing_sections:
        raise _fail(f"missing required table(s): {', '.join(missing_sections)}")
    for name in _REQUIRED_SECTIONS:
        table = _table(raw[name], name)
        missing = sorted(_REQUIRED_KEYS[name] - set(table))
        if missing:
            raise _fail(f"missing required key(s) in {name}: {', '.join(missing)}")

    rollout_raw = _table(raw["rollout"], "rollout")
    rollout: dict[str, RolloutStage] = {}
    for feature, value in rollout_raw.items():
        try:
            rollout[feature] = RolloutStage(value)
        except (TypeError, ValueError) as exc:
            raise _fail(f"invalid rollout stage for {feature!r}") from exc

    admission = _table(raw["admission"], "admission")
    retrieval = _table(raw["retrieval"], "retrieval")
    brainstem = _table(raw["brainstem"], "brainstem")
    learning = _table(raw["learning"], "learning")
    frontier = _table(raw["frontier"], "frontier")
    verification = _table(raw["verification"], "verification")
    verification_floor = verification["floor"]
    if not isinstance(verification_floor, str):
        raise _fail("verification.floor must be 'targeted' or 'full'")
    return V2Policy(
        schema_version=schema_version,
        rollout=rollout,
        admission_min_score=_bounded_float(admission["min_score"], "admission.min_score"),
        retrieval_max_candidates=_positive_int(
            retrieval["max_candidates"], "retrieval.max_candidates"
        ),
        retrieval_top_k=_positive_int(retrieval["top_k"], "retrieval.top_k"),
        retrieval_token_budget=_positive_int(retrieval["token_budget"], "retrieval.token_budget"),
        context_char_budget=_positive_int(
            brainstem["context_char_budget"], "brainstem.context_char_budget"
        ),
        worker_slots=_positive_int(brainstem["worker_slots"], "brainstem.worker_slots"),
        premium_model_turns=_positive_int(
            brainstem["premium_model_turns"], "brainstem.premium_model_turns"
        ),
        surprise_threshold=_bounded_float(
            learning["surprise_threshold"], "learning.surprise_threshold"
        ),
        frontier_min_importance=_bounded_float(
            frontier["min_importance"], "frontier.min_importance"
        ),
        verification_floor=verification_floor,
    )


def stage_allows(current: RolloutStage, required: RolloutStage) -> bool:
    """Return whether ``current`` meets the minimum required stage."""
    try:
        return _STAGE_ORDER[current] >= _STAGE_ORDER[required]
    except (KeyError, TypeError) as exc:
        raise BrainError("invalid rollout stage") from exc


def require_stage(policy: V2Policy, feature: str, required: RolloutStage) -> RolloutStage:
    """Return the configured stage when it meets a feature's requirement."""
    if not isinstance(feature, str) or not feature.strip():
        raise BrainError("Invalid v2 policy: feature must be non-empty text")
    try:
        actual = policy.rollout[feature]
    except KeyError as exc:
        raise BrainError(f"Unknown rollout feature: {feature}") from exc
    if not stage_allows(actual, required):
        raise BrainError(f"Rollout stage for {feature!r} is {actual}, requires {required}")
    return actual


def ensure_v2_migrated(home: Path) -> None:
    """Apply pending migrations through the existing database migration API."""
    dbfile = db.db_path(Path(home))
    if db.pending_migrations(dbfile):
        db.migrate(dbfile)
