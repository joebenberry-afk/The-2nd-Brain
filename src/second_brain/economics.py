"""Paired token economics with CUPED adjustment and mSPRT evidence.

This module consumes host-reported telemetry only. Missing usage and prices remain
unknown rather than being converted to zero or an invented dollar amount.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class EconomicsConfig:
    """Experimental economics parameters loaded from ``config/v2.toml``."""

    uncached_in: float = 1.0
    cache_read: float = 0.10
    cache_write: float = 1.25
    alpha: float = 0.05
    tau: float = 0.05
    prices: Mapping[str, Mapping[str, float | None]] = field(default_factory=dict)


def load_config(home: Path | str) -> EconomicsConfig:
    """Load economics parameters and prices; absent values use safe defaults."""
    path = Path(home) / "config" / "v2.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raw = {}
    section = raw.get("economics") if isinstance(raw, dict) else None
    section = section if isinstance(section, dict) else {}

    def number(name: str, default: float) -> float:
        value = section.get(name, default)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default

    prices_raw = raw.get("prices") if isinstance(raw, dict) else None
    prices: dict[str, dict[str, float | None]] = {}
    if isinstance(prices_raw, dict):
        for model, values in prices_raw.items():
            if isinstance(model, str) and isinstance(values, dict):
                prices[model] = {
                    str(name): (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
                    for name, value in values.items()
                    if isinstance(name, str)
                }
    return EconomicsConfig(
        uncached_in=number("uncached_in", 1.0),
        cache_read=number("cache_read", 0.10),
        cache_write=number("cache_write", 1.25),
        alpha=number("alpha", 0.05),
        tau=number("tau", 0.05),
        prices=prices,
    )


def variance(values: Sequence[float]) -> float:
    """Population variance, the variance convention used by the plan's formulas."""
    if not values:
        return float("nan")
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def covariance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return float("nan")
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    return sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right)) / len(left)


def cuped(covariate: Sequence[float], deltas: Sequence[float]) -> tuple[float, list[float]]:
    """Return ``theta`` and CUPED-adjusted deltas using OFF as covariate."""
    if len(covariate) != len(deltas) or not covariate:
        raise ValueError("CUPED inputs must be non-empty and have equal lengths")
    x_mean = sum(covariate) / len(covariate)
    x_variance = variance(covariate)
    theta = 0.0 if x_variance == 0 else covariance(covariate, deltas) / x_variance
    return theta, [d - theta * (x - x_mean) for x, d in zip(covariate, deltas)]


def _value(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _metric(run: Mapping[str, Any], profile: str, *names: str) -> Any:
    arm = run.get(profile)
    if isinstance(arm, Mapping):
        value = _value(arm, *names)
        if value is not None or any(name in arm for name in names):
            return value
    return _value(run, *(f"{profile}_{name}" for name in names))


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) else None


def _price_values(prices: Mapping[str, Any] | None) -> tuple[float, float] | None:
    if not isinstance(prices, Mapping):
        return None
    base_in = _value(prices, "base_in", "input", "input_price", "base_input")
    base_out = _value(prices, "base_out", "output", "output_price", "base_output")
    base_in = _number(base_in)
    base_out = _number(base_out)
    if base_in is None or base_out is None:
        return None
    return base_in, base_out


def cost_per_run(
    usage: Mapping[str, Any],
    prices: Mapping[str, Any] | None,
    *,
    multipliers: Mapping[str, Any] | None = None,
) -> float | None:
    """Calculate dollars from host usage and per-token model prices.

    ``None`` is returned whenever usage or either base price is unavailable.
    """
    bases = _price_values(prices)
    if bases is None:
        return None
    values = [
        _number(_value(usage, "input_tokens", "input", "uncached_in")),
        _number(_value(usage, "cache_read_tokens", "cache_read")),
        _number(_value(usage, "cache_write_tokens", "cache_write")),
        _number(_value(usage, "output_tokens", "output")),
    ]
    if any(value is None for value in values):
        return None
    uncached_in, cache_read, cache_write, output = values  # type: ignore[misc]
    multipliers = multipliers or {}
    mi_value = _number(_value(multipliers, "uncached_in", "uncached_in_multiplier"))
    mi = 1.0 if mi_value is None else mi_value
    mr = _number(_value(multipliers, "cache_read", "cache_read_multiplier"))
    mw = _number(_value(multipliers, "cache_write", "cache_write_multiplier"))
    mr = 0.10 if mr is None else mr
    mw = 1.25 if mw is None else mw
    base_in, base_out = bases
    return base_in * (mi * uncached_in + mr * cache_read + mw * cache_write) + base_out * output


def _pairs(runs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for run in runs:
        off_tokens = _number(_metric(run, "off", "tokens", "total_tokens", "total"))
        on_tokens = _number(_metric(run, "on", "tokens", "total_tokens", "total"))
        if off_tokens is None or on_tokens is None or off_tokens == 0:
            continue
        pairs.append({
            "off_tokens": off_tokens,
            "on_tokens": on_tokens,
            "off_dollars": _number(_metric(run, "off", "dollars", "cost_total")),
            "on_dollars": _number(_metric(run, "on", "dollars", "cost_total")),
            "off_turns": _number(_metric(run, "off", "turns", "model_turns")),
            "on_turns": _number(_metric(run, "on", "turns", "model_turns")),
            "off_wall": _number(_metric(run, "off", "wall_ms", "wall")),
            "on_wall": _number(_metric(run, "on", "wall_ms", "wall")),
            "pass_off": _metric(run, "off", "pass", "acceptance_pass") if isinstance(run.get("off"), Mapping) else _value(run, "pass_off"),
            "pass_on": _metric(run, "on", "pass", "acceptance_pass") if isinstance(run.get("on"), Mapping) else _value(run, "pass_on"),
        })
    return pairs


def _mean_delta(pairs: Sequence[Mapping[str, Any]], on: str, off: str) -> float | None:
    values = [float(pair[on]) - float(pair[off]) for pair in pairs if pair.get(on) is not None and pair.get(off) is not None]
    return sum(values) / len(values) if values else None


def verdict(
    runs: Iterable[Mapping[str, Any]],
    *,
    alpha: float = 0.05,
    tau: float = 0.05,
    config: EconomicsConfig | None = None,
) -> dict[str, Any]:
    """Compute paired CUPED/mSPRT verdict from normalized OFF/ON runs."""
    if config is not None:
        alpha, tau = config.alpha, config.tau
    pairs = _pairs(runs)
    n = len(pairs)
    result: dict[str, Any] = {
        "n": n,
        "r_bar": None,
        "lambda": None,
        "verdict": "INSUFFICIENT",
        "success_delta": None,
        "turns_delta": _mean_delta(pairs, "on_turns", "off_turns"),
        "dollars_delta": _mean_delta(pairs, "on_dollars", "off_dollars"),
    }
    if n:
        x = [float(pair["off_tokens"]) for pair in pairs]
        deltas = [float(pair["on_tokens"]) - float(pair["off_tokens"]) for pair in pairs]
        _, adjusted = cuped(x, deltas)
        relatives = [delta / base for delta, base in zip(adjusted, x)]
        r_bar = sum(relatives) / n
        result["r_bar"] = r_bar
        if n >= 3:
            sigma2 = variance(relatives)
            if sigma2 <= 1e-24:
                likelihood = float("inf") if r_bar else 1.0
            elif sigma2 > 0 and tau >= 0 and alpha > 0:
                denominator = sigma2 + n * tau * tau
                exponent = n * n * tau * tau * r_bar * r_bar / (2 * sigma2 * denominator)
                likelihood = float("inf") if exponent > 709 else math.sqrt(sigma2 / denominator) * math.exp(exponent)
            else:
                likelihood = None
            result["lambda"] = likelihood
            if likelihood is not None and likelihood >= 1 / alpha:
                result["verdict"] = "POSITIVE" if r_bar < 0 else "NEGATIVE" if r_bar > 0 else "INSUFFICIENT"
    successes = [float(bool(pair["pass_on"])) - float(bool(pair["pass_off"])) for pair in pairs if pair.get("pass_on") is not None and pair.get("pass_off") is not None]
    result["success_delta"] = sum(successes) / len(successes) if successes else None
    return result


def validate_fixture(data: Mapping[str, Any]) -> None:
    """Validate one economics fixture, raising ``ValueError`` on malformed data."""
    if (
        not isinstance(data, Mapping)
        or data.get("class") not in {"MICRO", "STANDARD", "DEEP", "DEBUG", "RESEARCH", "REVIEW", "HANDOFF"}
        or not isinstance(data.get("tasks"), list)
        or len(data["tasks"]) != 2
    ):
        raise ValueError("fixture requires one known class and exactly two tasks")
    for task in data["tasks"]:
        if (
            not isinstance(task, Mapping)
            or not isinstance(task.get("task_id"), str)
            or not isinstance(task.get("prompt"), str)
        ):
            raise ValueError("task requires task_id and prompt")
        if not isinstance(task.get("repo_fixture_commit"), str) or len(task["repo_fixture_commit"]) < 7:
            raise ValueError("task requires repo_fixture_commit")
        acceptance = task.get("acceptance")
        if (
            not isinstance(acceptance, Mapping)
            or not isinstance(acceptance.get("command"), str)
            or acceptance.get("expect_exit") != 0
        ):
            raise ValueError("task acceptance requires command and expect_exit=0")
