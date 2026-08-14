"""Paired bootstrap calculations using only the Python standard library."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import mean


@dataclass(frozen=True)
class BootstrapResult:
    n: int
    estimate: float
    lower: float
    upper: float
    seed: int
    resamples: int

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot calculate a quantile of empty data")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def paired_bootstrap(
    off: Sequence[float],
    active: Sequence[float],
    *,
    seed: int,
    resamples: int = 10_000,
) -> BootstrapResult:
    """Return the mean ACTIVE-OFF delta and a percentile 95% interval."""
    if len(off) != len(active) or not off:
        raise ValueError("paired bootstrap requires equally sized non-empty inputs")
    deltas = [float(a) - float(b) for b, a in zip(off, active, strict=True)]
    rng = random.Random(seed)
    estimates = [mean(deltas[rng.randrange(len(deltas))] for _ in deltas) for _ in range(resamples)]
    return BootstrapResult(
        n=len(deltas),
        estimate=mean(deltas),
        lower=_quantile(estimates, 0.025),
        upper=_quantile(estimates, 0.975),
        seed=seed,
        resamples=resamples,
    )
