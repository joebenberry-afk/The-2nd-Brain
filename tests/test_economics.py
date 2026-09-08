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
    assert result["lambda"] == float("inf")


def test_cost_preserves_null_when_price_missing():
    assert (
        economics.cost_per_run(
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_tokens": 3,
                "cache_write_tokens": 4,
            },
            None,
        )
        is None
    )


def test_cost_uses_cache_multipliers_exactly():
    assert (
        economics.cost_per_run(
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_tokens": 3,
                "cache_write_tokens": 4,
            },
            {"base_in": 2.0, "base_out": 3.0},
        )
        == 2.0 * (10 + 0.10 * 3 + 1.25 * 4) + 3.0 * 2
    )


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
                    "prompt": (
                        "Inspect src/second_brain/economics.py and report its public functions."
                    ),
                    "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                    "acceptance": {
                        "command": 'python -c "import second_brain.economics"',
                        "expect_exit": 0,
                    },
                },
                {
                    "task_id": "micro-02",
                    "prompt": (
                        "Inspect src/second_brain/telemetry.py and report its public functions."
                    ),
                    "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                    "acceptance": {
                        "command": "python -m pytest tests/test_telemetry.py -q",
                        "expect_exit": 0,
                    },
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
        "DEBUG",
        "DEEP",
        "HANDOFF",
        "MICRO",
        "RESEARCH",
        "REVIEW",
        "STANDARD",
    ]
    tasks = runner.load_tasks()
    assert len(tasks) == 14
    assert len({task["task_id"] for task in tasks}) == 14
    for path in paths:
        economics.validate_fixture(json.loads(path.read_text(encoding="utf-8")))


def test_fixture_loader_rejects_renamed_class_content(tmp_path, monkeypatch):
    import json

    from scripts import run_paired_economics as runner

    source = Path(runner.FIXTURE_DIR)
    for path in source.glob("*.json"):
        target = tmp_path / path.name
        payload = json.loads(path.read_text(encoding="utf-8"))
        if path.stem == "MICRO":
            payload["class"] = "STANDARD"
        target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(runner, "FIXTURE_DIR", tmp_path)
    with __import__("pytest").raises(ValueError):
        runner.load_tasks()


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
            path.write_text(
                json.dumps(
                    {
                        "kind": "assistant_usage",
                        "input_tokens": total,
                        "output_tokens": 2,
                        "cache_read_tokens": 1,
                        "cache_write_tokens": 0,
                        "total_tokens": total + 3,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
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


def test_qualification_preserves_committed_baseline(tmp_path, monkeypatch):
    import json

    from scripts import run_paired_economics as runner

    qualification = tmp_path / "qualification.json"
    baseline = json.loads(runner.QUALIFICATION.read_text(encoding="utf-8"))
    qualification.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(runner, "QUALIFICATION", qualification)
    monkeypatch.setattr(runner, "_host_command", lambda _: None)
    monkeypatch.setattr(runner, "load_tasks", lambda: [])
    runner.run("prime", "OFF", 1)
    result = json.loads(qualification.read_text(encoding="utf-8"))
    for key in ("gates", "source_identity", "generation_basis", "phase", "base_commit"):
        assert result[key] == baseline[key]
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
        path.write_text(
            json.dumps(
                {
                    "kind": "assistant_usage",
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cache_read_tokens": None,
                    "cache_write_tokens": 0,
                    "total_tokens": 12,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        aggregate = runner.aggregate_telemetry([path])
    assert aggregate["input_tokens"] == 10
    assert aggregate["cache_read_tokens"] is None


def test_fixture_rejects_boolean_expect_exit():
    import pytest

    with pytest.raises(ValueError):
        economics.validate_fixture(
            {
                "class": "MICRO",
                "tasks": [
                    {
                        "task_id": "a",
                        "prompt": "a",
                        "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                        "acceptance": {"command": "x", "expect_exit": 0},
                    },
                    {
                        "task_id": "b",
                        "prompt": "b",
                        "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                        "acceptance": {"command": "x", "expect_exit": False},
                    },
                ],
            }
        )


def test_run_one_normalizes_host_usage_pricing_and_privacy(tmp_path, monkeypatch):
    import json

    from scripts import run_paired_economics as runner

    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")

    def fake_git(*args, **kwargs):
        class Completed:
            returncode = 0

        return Completed()

    def fake_host(command, prompt, worktree, env):
        telemetry = Path(env["SECOND_BRAIN_HOME"]) / "telemetry" / "agent-performance"
        telemetry.mkdir(parents=True)
        for index, total in enumerate((12, 8)):
            (telemetry / f"session-{index}.jsonl").write_text(
                json.dumps(
                    {
                        "kind": "assistant_usage",
                        "model": "deepseek-v4-flash",
                        "input_tokens": total,
                        "output_tokens": 2,
                        "cache_read_tokens": 1,
                        "cache_write_tokens": 0,
                        "total_tokens": total + 3,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        return 0

    monkeypatch.setattr(runner.subprocess, "run", fake_git)
    monkeypatch.setattr(runner, "_run_host", fake_host)
    monkeypatch.setattr(runner, "_acceptance", lambda command, worktree: True)
    task = {
        "task_id": "micro-test",
        "prompt": "private prompt",
        "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
        "acceptance": {"command": "private acceptance", "expect_exit": 0},
    }
    record = runner._run_one("prime", task, "ON", ["host"])
    assert record is not None
    assert record["telemetry"]["input_tokens"] == 20
    assert record["dollars"] == economics.cost_per_run(
        {"input_tokens": 20, "output_tokens": 4, "cache_read_tokens": 2, "cache_write_tokens": 0},
        {"base_in": 0.00000014, "base_out": 0.00000028},
    )
    assert "private prompt" not in json.dumps(record)
    assert "private acceptance" not in json.dumps(record)


def test_run_executes_off_then_on_even_when_requested_on(tmp_path, monkeypatch):
    import json

    from scripts import run_paired_economics as runner

    qualification = tmp_path / "qualification.json"
    qualification.write_text(
        json.dumps(json.loads(runner.QUALIFICATION.read_text(encoding="utf-8"))), encoding="utf-8"
    )
    monkeypatch.setattr(runner, "QUALIFICATION", qualification)
    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(runner, "_host_command", lambda _: ["host"])
    monkeypatch.setattr(
        runner,
        "load_tasks",
        lambda: [
            {
                "task_id": "micro-test",
                "prompt": "prompt",
                "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
                "acceptance": {"command": "true", "expect_exit": 0},
            }
        ],
    )
    calls = []

    def fake_one(harness, task, profile, command):
        calls.append(profile)
        return {
            "run_id": f"{profile}-run",
            "task_id": task["task_id"],
            "profile": profile,
            "telemetry": {"total_tokens": 10, "model_turns": 1, "wall_ms": 1},
            "dollars": None,
            "acceptance_pass": True,
            "usage_capture": profile == "OFF",
        }

    monkeypatch.setattr(runner, "_run_one", fake_one)
    summary = runner.run("prime", "ON", 1)
    assert calls == ["OFF", "ON"]
    assert summary["usage_capture"] is False


def test_aggregate_mixed_models_refuses_single_price():
    import json
    from tempfile import TemporaryDirectory

    from scripts import run_paired_economics as runner

    with TemporaryDirectory() as temp:
        paths = []
        for index, model in enumerate(("deepseek-v4-flash", "other-model")):
            path = Path(temp) / f"model-{index}.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "kind": "assistant_usage",
                        "model": model,
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                        "total_tokens": 2,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            paths.append(path)
        aggregate = runner.aggregate_telemetry(paths)
    assert aggregate["mixed_model"] is True


def test_known_plus_missing_model_refuses_partial_pricing(tmp_path, monkeypatch):
    import json

    from scripts import run_paired_economics as runner

    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")

    def fake_git(*args, **kwargs):
        class Completed:
            returncode = 0

        return Completed()

    def fake_host(command, prompt, worktree, env):
        telemetry = Path(env["SECOND_BRAIN_HOME"]) / "telemetry" / "agent-performance"
        telemetry.mkdir(parents=True)
        rows: list[dict[str, object]] = [
            {"kind": "assistant_usage", "model": "deepseek-v4-flash"},
            {"kind": "assistant_usage"},
        ]
        for row in rows:
            row.update(
                {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "total_tokens": 2,
                }
            )
        (telemetry / "session.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(runner.subprocess, "run", fake_git)
    monkeypatch.setattr(runner, "_run_host", fake_host)
    monkeypatch.setattr(runner, "_acceptance", lambda command, worktree: True)
    task = {
        "task_id": "model-test",
        "prompt": "private prompt",
        "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
        "acceptance": {"command": "private acceptance", "expect_exit": 0},
    }
    record = runner._run_one("prime", task, "ON", ["host"])
    assert record is not None
    assert record["usage_capture"] is True
    assert record["telemetry"]["mixed_model"] is True
    assert record["dollars"] is None
    assert record["dollars_reason"] == "mixed_or_unknown_model"


def test_public_run_with_temporary_host_writes_real_shaped_artifacts(tmp_path, monkeypatch):
    import json
    import shutil
    import sys

    from scripts import run_paired_economics as runner

    fixture_dir = tmp_path / "fixtures"
    shutil.copytree(runner.FIXTURE_DIR, fixture_dir)
    for path in fixture_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tasks"] = [
            {
                **task,
                "acceptance": {
                    "command": f'"{sys.executable}" -c "print(\'PRIVATE_TOOL_OUTPUT\')"',
                    "expect_exit": 0,
                },
            }
            for task in payload["tasks"]
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
    qualification = tmp_path / "qualification.json"
    qualification.write_text(runner.QUALIFICATION.read_text(encoding="utf-8"), encoding="utf-8")
    host = tmp_path / "host.py"
    host.write_text(
        (
            "import json, os\nfrom pathlib import Path\n"
            "home=Path(os.environ['SECOND_BRAIN_HOME'])\n"
            "assert (home/'VERSION').is_file()\n"
            "assert (home/'db'/'brain.sqlite').is_file()\n"
            "p=home/'telemetry'/'agent-performance'\n"
            "p.mkdir(parents=True, exist_ok=True)\n"
            "print('PRIVATE_HOST_OUTPUT')\n(p/'host.jsonl').write_text("
            "json.dumps({'kind':'assistant_usage','model':'de"
            "epseek-v4-flash','input_tokens':10,'output_token"
            "s':2,'cache_read_tokens':3,'cache_write_tokens':"
            "0,'total_tokens':15})+'\\n', encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(runner, "QUALIFICATION", qualification)
    monkeypatch.setenv("SECOND_BRAIN_PRIME_COMMAND", f"{sys.executable} {host}")
    summary = runner.run("prime", "ON", 1)
    assert summary["profile_mapping"] == {"OFF": "A_BRAIN_OFF", "ON": "I_FULL_V1"}
    assert summary["pairs_recorded"] == 1
    assert summary["usage_capture"] is True
    raw = list((tmp_path / "raw").glob("*.json"))
    assert len(raw) == 2
    for path in raw:
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["usage_capture"] is True
        assert Path(record["worktree"], "src", "second_brain", "governor.py").is_file()
        assert Path(
            record["raw_directory"], "brain", "telemetry", "agent-performance", "host.jsonl"
        ).is_file()
        assert record["telemetry"]["total_tokens"] == 15
        assert record["dollars"] == economics.cost_per_run(
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_tokens": 3,
                "cache_write_tokens": 0,
            },
            {"base_in": 0.00000014, "base_out": 0.00000028},
        )
        text = json.dumps(record)
        assert "Inspect" not in text
        assert "PRIVATE_HOST_OUTPUT" not in text
        assert "PRIVATE_TOOL_OUTPUT" not in text


def test_retrieval_profile_does_not_invent_provider_outcomes(brain_home, tmp_path):
    import pytest
    from scripts import run_retrieval_economics as runner

    from second_brain import semantic

    memory_id = semantic.add_memory(
        brain_home,
        title="SQLite concurrency",
        body="Use WAL and a bounded busy timeout for concurrent SQLite readers.",
        scope="project",
        project_id="retrieval-profile",
        grade="VERIFIED",
    )
    semantic.curate(brain_home, memory_id, status="current")
    output_path = tmp_path / "retrieval-profile.json"
    report = runner.run_retrieval_economics(
        brain_home,
        repeats=2,
        output_path=output_path,
    )
    assert report["provider_usage"] == {
        "tokens": None,
        "dollars": None,
        "turns": None,
        "task_success": None,
    }
    assert report["economics_verdict"] == "INSUFFICIENT"
    assert report["live_economics_eligible"] is False
    row = report["runs"][0]
    assert row["baseline"]["selected_memory_ids"] == [memory_id]
    assert row["candidate"]["selected_memory_ids"] == [memory_id]
    assert row["baseline"]["context_chars"] == row["candidate"]["context_chars"]

    retained = output_path.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run_retrieval_economics(brain_home, output_path=output_path)
    assert output_path.read_bytes() == retained
