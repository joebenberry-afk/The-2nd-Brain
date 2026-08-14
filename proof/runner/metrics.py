"""Small aggregate metrics for normalized proof records."""

from __future__ import annotations

from collections.abc import Iterable
from statistics import mean
from typing import Any


def _numbers(records: Iterable[dict[str, Any]], key: str) -> list[float]:
    return [float(record[key]) for record in records if isinstance(record.get(key), (int, float))]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = [record for record in records if isinstance(record.get("success"), bool)]
    successes = sum(record["success"] is True for record in attempted)
    wall = _numbers(attempted, "wall_seconds")
    tokens = _numbers(attempted, "input_tokens")
    return {
        "attempted": len(attempted),
        "successes": successes,
        "success_rate": successes / len(attempted) if attempted else None,
        "first_pass_rate": (
            sum(record.get("first_pass_success") is True for record in attempted) / len(attempted)
            if attempted
            else None
        ),
        "mean_wall_seconds": mean(wall) if wall else None,
        "mean_input_tokens": mean(tokens) if tokens else None,
    }
