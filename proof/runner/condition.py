"""Experimental condition definitions and deterministic pair randomization."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum


class Condition(StrEnum):
    C0_OFF = "C0_OFF"
    C1_OBSERVABILITY = "C1_OBSERVABILITY"
    C2_SHADOW = "C2_SHADOW"
    C3_ACTIVE = "C3_ACTIVE"
    C4_ACTIVE_FROZEN = "C4_ACTIVE_FROZEN"
    C5_MEMORY_ONLY = "C5_MEMORY_ONLY"
    C6_SKILLS_ONLY = "C6_SKILLS_ONLY"
    C7_NO_TRANSFER = "C7_NO_TRANSFER"


@dataclass(frozen=True)
class ConditionSpec:
    name: Condition
    brain_enabled: bool
    extension_enabled: bool
    learning_enabled: bool
    official_prime_path: bool
    description: str


CONDITIONS: dict[Condition, ConditionSpec] = {
    Condition.C0_OFF: ConditionSpec(
        Condition.C0_OFF,
        brain_enabled=False,
        extension_enabled=False,
        learning_enabled=False,
        official_prime_path=True,
        description="ordinary agent baseline; no Brain APIs or extension",
    ),
    Condition.C1_OBSERVABILITY: ConditionSpec(
        Condition.C1_OBSERVABILITY,
        brain_enabled=False,
        extension_enabled=True,
        learning_enabled=False,
        official_prime_path=True,
        description="Prime telemetry only; no behavior mutation",
    ),
    Condition.C2_SHADOW: ConditionSpec(
        Condition.C2_SHADOW,
        brain_enabled=True,
        extension_enabled=True,
        learning_enabled=True,
        official_prime_path=False,
        description="shadow calculations; recommendations are not injected",
    ),
    Condition.C3_ACTIVE: ConditionSpec(
        Condition.C3_ACTIVE,
        brain_enabled=True,
        extension_enabled=True,
        learning_enabled=True,
        official_prime_path=False,
        description="reserved for verified automatic Prime integration",
    ),
    Condition.C4_ACTIVE_FROZEN: ConditionSpec(
        Condition.C4_ACTIVE_FROZEN,
        brain_enabled=True,
        extension_enabled=True,
        learning_enabled=False,
        official_prime_path=False,
        description="reserved for verified automatic ACTIVE integration",
    ),
    Condition.C5_MEMORY_ONLY: ConditionSpec(
        Condition.C5_MEMORY_ONLY,
        brain_enabled=True,
        extension_enabled=True,
        learning_enabled=False,
        official_prime_path=False,
        description="reserved memory-only ablation",
    ),
    Condition.C6_SKILLS_ONLY: ConditionSpec(
        Condition.C6_SKILLS_ONLY,
        brain_enabled=True,
        extension_enabled=True,
        learning_enabled=False,
        official_prime_path=False,
        description="reserved skills-only ablation",
    ),
    Condition.C7_NO_TRANSFER: ConditionSpec(
        Condition.C7_NO_TRANSFER,
        brain_enabled=True,
        extension_enabled=True,
        learning_enabled=False,
        official_prime_path=False,
        description="reserved no-transfer control",
    ),
}


def parse_condition(value: str | Condition) -> Condition:
    """Parse a condition name without accepting silent aliases."""
    if isinstance(value, Condition):
        return value
    try:
        return Condition(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Condition)
        raise ValueError(f"unknown condition {value!r}; expected one of {allowed}") from exc


def pair_order(
    first: str | Condition, second: str | Condition, task_id: str, seed: int
) -> list[Condition]:
    """Return a reproducible randomized order for one paired task."""
    values = [parse_condition(first), parse_condition(second)]
    random.Random(f"{seed}:{task_id}").shuffle(values)
    return values
