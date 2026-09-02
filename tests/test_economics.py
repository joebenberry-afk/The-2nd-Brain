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


def test_fixture_set_is_exact_and_task_ids_are_unique():
    import json
    from pathlib import Path
    from scripts import run_paired_economics as runner

    paths = sorted(Path(runner.FIXTURE_DIR).glob("*.json"))
    assert [path.stem for path in paths] == [
        "DEBUG", "DEEP", "HANDOFF", "MICRO", "RESEARCH", "REVIEW", "STANDARD"
    ]
    tasks = runner.load_tasks()
    assert len(tasks) == 14
    assert len({task["task_id"] for task in tasks}) == 14
    for path in paths:
        economics.validate_fixture(json.loads(path.read_text(encoding="utf-8")))


def test_runner_maps_both_profiles_to_explicit_governor_profiles():
    from scripts import run_paired_economics as runner

    assert runner.profile_env("OFF")["SECOND_BRAIN_GOVERNOR_BRAIN_CORE"] == "0"
    assert runner.profile_env("ON")["SECOND_BRAIN_GOVERNOR_BRAIN_CORE"] == "1"
    assert runner.PROFILE_TO_ABLATION["OFF"] != runner.PROFILE_TO_ABLATION["ON"]


def test_runner_aggregates_multiple_telemetry_files():
    import json
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from scripts import run_paired_economics as runner

    with TemporaryDirectory() as temp:
        paths = []
        for index, total in enumerate((10, 20)):
            path = Path(temp) / f"session-{index}.jsonl"
            path.write_text(json.dumps({
                "kind": "assistant_usage",
                "input_tokens": total,
                "output_tokens": 2,
                "cache_read_tokens": 1,
                "cache_write_tokens": 0,
                "total_tokens": total + 3,
            }) + "\n", encoding="utf-8")
            paths.append(path)
        aggregate = runner.aggregate_telemetry(paths)
    assert aggregate["input_tokens"] == 30
    assert aggregate["output_tokens"] == 4
    assert aggregate["total_tokens"] == 36
    assert aggregate["model_turns"] == 2

def test_verdict_retains_partial_pairs_and_null_metric_means():
    synthetic_runs = [
        {"off": {"tokens": 100, "turns": 2}, "on": {"tokens": 90, "turns": 1}},
        {"off": {"tokens": None, "turns": None}, "on": {"tokens": 80, "turns": 1}},
    ]
    result = economics.verdict(synthetic_runs)
    assert result["n"] == 1
    assert result["turns_delta"] is None


def test_qualification_preserves_baseline_metadata(tmp_path, monkeypatch):
    import json
    from scripts import run_paired_economics as runner

    baseline = {
        "schema_version": 2,
        "metadata": {"gate": "SHADOW", "source_identity": "baseline"},
        "generation_basis": {"commit": "abc"},
        "phase": "v2-0",
        "economics": {"old": True},
    }
    qualification = tmp_path / "qualification.json"
    qualification.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(runner, "QUALIFICATION", qualification)
    monkeypatch.setattr(runner, "_host_command", lambda _: None)
    monkeypatch.setattr(runner, "load_tasks", lambda: [])
    runner.run("prime", "OFF", 1)
    result = json.loads(qualification.read_text(encoding="utf-8"))
    assert result["metadata"] == baseline["metadata"]
    assert result["generation_basis"] == baseline["generation_basis"]
    assert result["phase"] == "v2-0"
    assert result["economics"]["old"] is True
    assert result["economics"]["prime"]["usage_capture"] is False


def test_cost_ignores_host_reported_cost_total_and_requires_all_counters():
    usage = {
        "input_tokens": 10,
        "output_tokens": 2,
        "cache_read_tokens": 3,
        "cache_write_tokens": 4,
        "cost_total": 999.0,
    }
    assert economics.cost_per_run(usage, {"base_in": 2.0, "base_out": 3.0}) == 36.6
    usage.pop("cache_write_tokens")
    assert economics.cost_per_run(usage, {"base_in": 2.0, "base_out": 3.0}) is None


def test_aggregate_telemetry_preserves_partial_counter_null():
    import json
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from scripts import run_paired_economics as runner

    with TemporaryDirectory() as temp:
        path = Path(temp) / "partial.jsonl"
        path.write_text(json.dumps({
            "kind": "assistant_usage",
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_read_tokens": None,
            "cache_write_tokens": 0,
            "total_tokens": 12,
        }) + "\n", encoding="utf-8")
        aggregate = runner.aggregate_telemetry([path])
    assert aggregate["input_tokens"] == 10
    assert aggregate["cache_read_tokens"] is None


def test_fixture_rejects_boolean_expect_exit():
    import pytest

    with pytest.raises(ValueError):
        economics.validate_fixture({
            "class": "MICRO",
            "tasks": [
                {"task_id": "a", "prompt": "a", "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                 "acceptance": {"command": "x", "expect_exit": 0}},
                {"task_id": "b", "prompt": "b", "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                 "acceptance": {"command": "x", "expect_exit": False}},
            ],
        })
