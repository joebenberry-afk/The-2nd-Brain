"""Focused tests for paired economics (synthetic fixtures never become evidence)."""

from __future__ import annotations

from pathlib import Path

from second_brain import economics


def synthetic_pair(off: float, on: float, *, pass_off: bool = True, pass_on: bool = True) -> dict:
    return {
        "off": {"tokens": off, "turns": 2, "wall_ms": off, "dollars": off / 1000},
        "on": {"tokens": on, "turns": 1, "wall_ms": on, "dollars": on / 1000},
        "pass_off": pass_off,
        "pass_on": pass_on,
    }


def test_cuped_reduces_variance_on_correlated_fixture():
    synthetic_x = [10.0, 20.0, 30.0, 40.0, 50.0]
    synthetic_delta = [-1.2, -1.9, -3.2, -3.8, -5.1]

    theta, adjusted = economics.cuped(synthetic_x, synthetic_delta)

    assert theta < 0
    assert economics.variance(adjusted) < economics.variance(synthetic_delta)


def test_msprt_abstains_below_three_pairs():
    synthetic_runs = [synthetic_pair(100, 90), synthetic_pair(100, 90)]

    result = economics.verdict(synthetic_runs, alpha=0.05, tau=0.05)

    assert result["n"] == 2
    assert result["verdict"] == "INSUFFICIENT"
    assert result["lambda"] is None


def test_msprt_detects_known_effect():
    synthetic_runs = [
        synthetic_pair(100, 50),
        synthetic_pair(100, 49),
        synthetic_pair(100, 51),
    ]
    result = economics.verdict(synthetic_runs, alpha=0.05, tau=0.05)

    assert result["n"] == 3
    assert result["r_bar"] < 0
    assert result["lambda"] >= 20
    assert result["verdict"] == "POSITIVE"

def test_governor_delegates_to_economics(monkeypatch):
    from second_brain import governor

    calls = []

    def fake_verdict(runs):
        calls.append(runs)
        return {"n": 1, "verdict": "POSITIVE"}

    monkeypatch.setattr(governor.economics, "verdict", fake_verdict)
    result = governor.classify_roi(
        [governor.SessionTokens("on", cost_total=2.0, cost_total_seen=1)],
        [governor.SessionTokens("off", cost_total=3.0, cost_total_seen=1)],
        min_sessions=1,
    )

    assert calls and calls[0][0]["off"]["tokens"] == 3.0
    assert result.status == "POSITIVE_ROI"


def test_cost_preserves_null_when_price_missing():
    assert economics.cost_per_run(
        {"input_tokens": 10, "output_tokens": 2, "cache_read_tokens": 3, "cache_write_tokens": 4},
        None,
    ) is None

def test_cost_uses_cache_multipliers_exactly():
    assert economics.cost_per_run(
        {"input_tokens": 10, "output_tokens": 2, "cache_read_tokens": 3, "cache_write_tokens": 4},
        {"base_in": 2.0, "base_out": 3.0},
    ) == 2.0 * (10 + 0.10 * 3 + 1.25 * 4) + 3.0 * 2


def test_config_carries_experimental_economics_defaults():
    config = economics.load_config(Path(__file__).parents[1])
    assert (config.uncached_in, config.cache_read, config.cache_write) == (1.0, 0.10, 1.25)
    assert (config.alpha, config.tau) == (0.05, 0.05)


def test_fixture_schema_is_valid():
    economics.validate_fixture(
        {
            "class": "MICRO",
            "tasks": [
                {
                    "task_id": "micro-01",
                    "prompt": "Inspect src/second_brain/economics.py and report its public functions.",
                    "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                    "acceptance": {"command": "python -c \"import second_brain.economics\"", "expect_exit": 0},
                },
                {
                    "task_id": "micro-02",
                    "prompt": "Inspect src/second_brain/telemetry.py and report its public functions.",
                    "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                    "acceptance": {"command": "python -m pytest tests/test_telemetry.py -q", "expect_exit": 0},
                },
            ],
        }
    )
