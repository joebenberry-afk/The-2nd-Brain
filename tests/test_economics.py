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
    assert result["verdict"] == "POSITIVE"
    assert result["lambda_status"] == "overflow"
    assert result["lambda"] is None
    assert result["log_lambda"] > 709


def test_likelihood_export_distinguishes_overflow_limit_and_missing_data(tmp_path, monkeypatch):
    import json
    import math

    import pytest
    from scripts import run_paired_economics as runner

    finite = economics.verdict([synthetic_pair(100, n) for n in (90, 100, 110)])
    limit = economics.verdict([synthetic_pair(100, 50)] * 3)
    missing = economics.verdict([])
    assert finite["lambda_status"] == "finite"
    assert math.isclose(math.log(finite["lambda"]), finite["log_lambda"])
    assert limit["lambda_status"] == "positive_infinity"
    assert limit["lambda"] is None and limit["log_lambda"] is None
    assert limit["verdict"] == "POSITIVE"
    assert missing["lambda_status"] == "insufficient_data"
    assert missing["verdict"] == "INSUFFICIENT"
    export = tmp_path / "qualification.json"
    monkeypatch.setattr(runner, "QUALIFICATION", export)
    summary = {"harness": "omp", "finite": finite, "limit": limit, "missing": missing}
    runner._write_qualification(summary)
    decoded = json.loads(export.read_text(), parse_constant=runner._reject_nonfinite)
    assert decoded["economics"]["omp"] == summary
    for invalid in ("Infinity", "NaN", "-Infinity", "1e999"):
        original = '{"economics": {}, "old": ' + invalid + "}"
        export.write_text(original, encoding="utf-8")
        with pytest.raises(ValueError):
            runner._write_qualification(summary)
        assert export.read_text(encoding="utf-8") == original


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


def test_acceptance_isolated_cli_ignores_foreign_brain_environment(tmp_path, monkeypatch):
    import subprocess
    import sys

    from scripts import run_paired_economics as runner

    isolated_home = tmp_path / "isolated-brain"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(tmp_path / "foreign-parent-brain"))
    monkeypatch.setenv("SECOND_BRAIN_RUNTIME_ROOT", str(tmp_path / "foreign-runtime-root"))
    python = subprocess.list2cmdline([sys.executable])
    home = subprocess.list2cmdline([str(isolated_home)])
    command = (
        f"{python} -m second_brain --home {home} init && "
        f"{python} -m second_brain --home {home} doctor --json"
    )

    assert runner._acceptance(command, tmp_path) is True
    assert (isolated_home / "db" / "brain.sqlite").is_file()


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
    monkeypatch.setattr(
        runner,
        "_runtime_identity",
        lambda _: {"python": "runtime", "module": "module", "source_root": "root"},
    )
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
    assert record["regression_pass"] is True
    assert record["acceptance_pass"] is None
    assert "private prompt" not in json.dumps(record)
    assert "private acceptance" not in json.dumps(record)


def test_run_one_preserves_brain_initialization_failure(tmp_path, monkeypatch):
    from scripts import run_paired_economics as runner

    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")

    def fake_subprocess(args, **kwargs):
        class Completed:
            returncode = 1 if "-m" in args else 0

        return Completed()

    monkeypatch.setattr(runner.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(
        runner,
        "_runtime_identity",
        lambda _: {"python": "runtime", "module": "module", "source_root": "root"},
    )
    task = {
        "task_id": "init-failure",
        "prompt": "prompt",
        "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
        "acceptance": {"command": "true", "expect_exit": 0},
    }
    record = runner._run_one("prime", task, "ON", ["host"])
    assert record is not None
    assert record["host_exit"] is None
    assert record["acceptance_pass"] is None
    assert record["usage_capture"] is False
    assert record["initialization_error"]


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
    monkeypatch.setattr(
        runner,
        "_runtime_identity",
        lambda _: {"python": "runtime", "module": "module", "source_root": "root"},
    )
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
    from second_brain.hybrid_retrieval import HybridCascadeRetriever

    memory_id = semantic.add_memory(
        brain_home,
        title="SQLite concurrency",
        body="Use WAL and a bounded busy timeout for concurrent SQLite readers.",
        scope="project",
        project_id="retrieval-profile",
        grade="TESTED",
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
    expected_body = "\n\nUse WAL and a bounded busy timeout for concurrent SQLite readers.\n"
    baseline_matches = semantic.search_memories(
        brain_home,
        "SQLite concurrency",
        project_id="retrieval-profile",
        top_k=4,
        include_duplicates=True,
    )
    candidate_matches = (
        HybridCascadeRetriever()
        .retrieve(brain_home, "SQLite concurrency", project_id="retrieval-profile", top_k=4)
        .matches
    )
    assert baseline_matches[0]["_body"] == expected_body
    assert candidate_matches[0].body == expected_body
    assert row["baseline"]["context_chars"] == row["candidate"]["context_chars"] == 89

    retained = output_path.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run_retrieval_economics(brain_home, output_path=output_path)
    assert output_path.read_bytes() == retained


def test_native_study_protocol_is_bounded_to_three_pairs(tmp_path):
    import json

    from scripts import run_paired_economics as runner

    protocol = {
        "pairs": [{"pair": index, "order": ["baseline", "candidate"]} for index in range(1, 5)],
        "same_postconditions": {},
        "controller_model": "openai-codex/gpt-6-astra:low",
        "worker_model": "openai-codex/gpt-5.6-luna:low",
    }
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    import pytest

    with pytest.raises(ValueError, match="exactly three"):
        runner._protocol_study(path)


def test_native_acceptance_uses_executed_result_and_session_bound_workers(tmp_path):
    import json

    from scripts import run_paired_economics as runner

    settings = {
        "autoinject_mode": "active",
        "admission_stage": "SHADOW",
        "learning_stage": "SHADOW",
        "retrieval_token_budget": 1200,
    }
    command = "python /approved/read.py /approved/input.json"
    names = ["CandidateP1One", "CandidateP1Two"]
    parent = tmp_path / "controller.jsonl"
    children = [tmp_path / f"{name}.jsonl" for name in names]

    def call(name, args, identifier):
        return {"type": "toolCall", "name": name, "arguments": args, "id": identifier}

    def write_session(path, calls, results):
        rows = [{"message": {"role": "assistant", "content": calls}}]
        rows.extend({"message": result} for result in results)
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    macro = call("bash", {"command": command}, "macro")
    dispatch = call(
        "task",
        {
            "tasks": [
                {"name": name, "agent": "scout", "access_intent": "read_only"} for name in names
            ]
        },
        "dispatch",
    )
    reply = {
        "role": "toolResult",
        "toolCallId": "macro",
        "isError": False,
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "observed_settings": settings,
                        "engram_id": "approved",
                        "version": 1,
                        "macro_model_calls": 0,
                        "cache_hit": True,
                        "native_commands": [],
                    }
                ),
            }
        ],
    }
    for child in children:
        write_session(
            child,
            [call("yield", {"data": settings}, "yield")],
            [
                {"role": "toolResult", "toolCallId": "yield", "isError": False},
            ],
        )
    write_session(parent, [macro, dispatch], [reply])

    def accepted():
        return runner._native_acceptance(
            parent, children, "candidate", 1, {"same_postconditions": settings}, command
        )[0]

    assert accepted()
    # A successful macro plus a fabricated sidecar cannot repair a wrong native answer.
    children[0].with_suffix(".json").write_text(json.dumps(settings), encoding="utf-8")
    write_session(
        children[0],
        [
            call(
                "yield",
                {
                    "data": {
                        **settings,
                        "retrieval_token_budget": 999,
                    }
                },
                "yield",
            )
        ],
        [{"role": "toolResult", "toolCallId": "yield", "isError": False}],
    )
    assert not accepted()
    write_session(
        children[0],
        [call("yield", {"data": settings}, "yield")],
        [
            {"role": "toolResult", "toolCallId": "yield", "isError": False},
        ],
    )
    write_session(parent, [macro, dispatch], [{**reply, "isError": True}])
    assert not accepted()
    write_session(
        parent,
        [
            macro,
            dispatch,
            call(
                "bash",
                {"command": "python read.py input.json"},
                "alternate",
            ),
        ],
        [reply],
    )
    assert not accepted()


def test_host_capture_preserves_answer_streams_on_nonzero_exit(tmp_path):
    import sys

    from scripts import run_paired_economics as runner

    capture = tmp_path / "private"
    env = {"SECOND_BRAIN_ECONOMICS_CAPTURE_DIR": str(capture)}
    result = runner._run_host(
        [
            sys.executable,
            "-c",
            "import sys; print('ANSWER'); print('ERROR', file=sys.stderr); sys.exit(3)",
        ],
        "prompt",
        tmp_path,
        env,
    )
    assert result == 3
    assert (capture / "stdout.txt").read_text(encoding="utf-8") == "ANSWER\n"
    assert (capture / "stderr.txt").read_text(encoding="utf-8") == "ERROR\n"
    assert runner._execution_metadata(capture)["status"] == "completed"


def test_collect_reviews_qualifies_without_host_rerun_and_rejects_tampering(tmp_path, monkeypatch):
    import hashlib

    from scripts import run_paired_economics as runner

    task = runner.load_tasks()[0]
    source_identity = runner._source_identity()
    catalog_identity = runner._task_catalog_identity()
    runtime_identity = {
        "python": "runtime",
        "module": "module",
        "source_root": "root",
        "source_commit": "runtime-commit",
        "source_tree_sha256": "runtime-tree",
    }
    monkeypatch.setattr(runner, "_runtime_identity", lambda _: runtime_identity)
    answer = tmp_path / "answer.txt"
    answer.write_text("actual answer\n", encoding="utf-8")
    digest = hashlib.sha256(answer.read_bytes()).hexdigest()

    def record(run_id, profile):
        return {
            "schema_version": 3,
            "classification": "observed",
            "runtime_identity": runtime_identity,
            "qualification_eligible": True,
            "source_identity": source_identity,
            "task_catalog_identity": catalog_identity,
            "task_identity": runner._stable_hash(task),
            "run_id": run_id,
            "task_id": task["task_id"],
            "profile": profile,
            "repo_fixture_commit": task["repo_fixture_commit"],
            "host_exit": 0,
            "regression_pass": True,
            "response_artifact": {
                "path": str(answer),
                "sha256": digest,
                "bytes": answer.stat().st_size,
            },
            "telemetry": {
                "total_tokens": 10,
                "model_turns": 1,
                "wall_ms": 1,
                "input_tokens": 5,
                "output_tokens": 5,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
            "usage_capture": True,
            "dollars": 1.0,
            "acceptance_pass": True,
        }

    runs = [record("off", "OFF"), record("on", "ON")]
    reviews = [
        {
            "run_id": run["run_id"],
            "task_id": run["task_id"],
            "fixture_commit": run["repo_fixture_commit"],
            "response_artifact_sha256": digest,
            "reviewer_identity": "independent-reviewer",
            "accepted": True,
            "evidence": "answer checked against frozen rubric",
            "rationale": "all required labels present",
        }
        for run in runs
    ]
    monkeypatch.setattr(
        runner,
        "_run_host",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    summary = runner.collect_reviews(runs, reviews, reviewer_identity="independent-reviewer")
    assert summary["quality_status"] == "QUALIFIED"
    assert summary["quality_qualified_pairs"] == 1
    assert summary["token_statistic"]["n"] == 1
    assert summary["quality_qualified_economics"]["n"] == 1

    missing_pin = runner.collect_reviews(runs, reviews)
    assert missing_pin["quality_status"] == "FAILED"
    extra = runner.collect_reviews(
        runs,
        [*reviews, {**reviews[0], "run_id": "unknown"}],
        reviewer_identity="independent-reviewer",
    )
    assert extra["quality_status"] == "FAILED"
    assert extra["quality_qualified_economics"] is None
    synthetic = runner.collect_reviews(
        [{**run, "classification": "simulation"} for run in runs],
        reviews,
        reviewer_identity="independent-reviewer",
    )
    assert synthetic["quality_status"] == "FAILED"
    no_usage = runner.collect_reviews(
        [{**run, "usage_capture": False} for run in runs],
        reviews,
        reviewer_identity="independent-reviewer",
    )
    assert no_usage["quality_status"] == "QUALIFIED"
    assert no_usage["quality_qualified_economics"] is None
    missing_runtime = runner.collect_reviews(
        [{**run, "runtime_identity": None} for run in runs],
        reviews,
        reviewer_identity="independent-reviewer",
    )
    assert missing_runtime["quality_status"] == "FAILED"
    assert missing_runtime["quality_qualified_economics"] is None
    wrong_runtime = runner.collect_reviews(
        [{**runs[0], "runtime_identity": {**runtime_identity, "source_commit": "wrong"}}, runs[1]],
        reviews,
        reviewer_identity="independent-reviewer",
    )
    assert wrong_runtime["quality_status"] == "FAILED"
    assert wrong_runtime["quality_qualified_economics"] is None

    answer.write_text("tampered\n", encoding="utf-8")
    rejected = runner.collect_reviews(runs, reviews, reviewer_identity="independent-reviewer")
    assert rejected["quality_status"] == "FAILED"
    assert rejected["quality_qualified_pairs"] == 0
    assert rejected["records"][0]["acceptance_pass"] is None
    answer.write_text("actual answer\n", encoding="utf-8")

    failed_host = runner.collect_reviews(
        [{**run, "host_exit": 1} for run in runs],
        reviews,
        reviewer_identity="independent-reviewer",
    )
    assert failed_host["quality_status"] == "FAILED"
    assert failed_host["quality_qualified_economics"] is None
    assert failed_host["token_statistic"]["n"] == 1

    invalid_exit = runner.collect_reviews(
        [{**run, "host_exit": False} for run in runs],
        reviews,
        reviewer_identity="independent-reviewer",
    )
    assert invalid_exit["quality_status"] == "FAILED"

    failed_regression = runner.collect_reviews(
        [{**run, "regression_pass": False} for run in runs],
        reviews,
        reviewer_identity="independent-reviewer",
    )
    assert failed_regression["quality_status"] == "FAILED"
    assert failed_regression["quality_qualified_economics"] is None


def test_run_one_fails_closed_without_runtime_identity(tmp_path, monkeypatch):
    from scripts import run_paired_economics as runner

    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(runner, "_runtime_identity", lambda _: None)
    monkeypatch.setattr(
        runner,
        "_source_identity",
        lambda: {"source_commit": "producer", "source_tree_sha256": "producer-tree"},
    )
    monkeypatch.setattr(
        runner,
        "_task_catalog_identity",
        lambda: {"sha256": "catalog", "task_count": 1, "task_ids": ["micro-test"]},
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("setup must not run")),
    )
    monkeypatch.setattr(
        runner,
        "_run_host",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("host must not run")),
    )
    record = runner._run_one(
        "omp",
        {
            "task_id": "micro-test",
            "prompt": "prompt",
            "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
        },
        "OFF",
        ["omp", "--print", "--no-title"],
    )
    assert record["host_status"] == "setup_error"
    assert record["runtime_identity"] is None
    assert record["qualification_eligible"] is False


def test_runtime_identity_rejects_package_outside_bound_source(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys

    from scripts import run_paired_economics as runner

    root = tmp_path / "checkout"
    module = root / ".venv" / "Lib" / "site-packages" / "second_brain" / "__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    (root / "src").mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    python = str(Path(sys.executable).resolve())
    observed = {"python": python, "module": str(module), "source_root": str(root)}
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, json.dumps(observed), ""),
    )
    monkeypatch.setattr(runner.build_identity, "git_sha", lambda _: "a" * 40)
    monkeypatch.setattr(runner.build_identity, "source_tree_fingerprint", lambda _: "b" * 64)

    assert runner._runtime_identity(python) is None


def test_setup_failure_and_raw_collision_are_retained(tmp_path, monkeypatch):
    import pytest
    from scripts import run_paired_economics as runner

    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(runner, "_utc", lambda: "fixed")
    monkeypatch.setattr(
        runner,
        "_source_identity",
        lambda: {"source_commit": "a", "source_tree_sha256": "b"},
    )
    monkeypatch.setattr(
        runner,
        "_task_catalog_identity",
        lambda: {"sha256": "c", "task_count": 14, "task_ids": []},
    )
    monkeypatch.setattr(
        runner,
        "_runtime_identity",
        lambda _: {"python": "runtime", "module": "module", "source_root": "root"},
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: type("Completed", (), {"returncode": 1})(),
    )
    task = {
        "task_id": "micro-test",
        "prompt": "prompt",
        "repo_fixture_commit": "e64aac8e0432a87bd899f52efcbaf928960925e4",
    }
    record = runner._run_one("omp", task, "OFF", ["omp", "--print", "--no-title"])
    assert record["host_status"] == "setup_error"
    assert record["setup_error"]
    runner._write_json_once(
        Path(record["raw_directory"]) / "record.json",
        record,
    )
    with pytest.raises(FileExistsError):
        runner._run_one("omp", task, "OFF", ["omp", "--print", "--no-title"])


def test_appended_or_replaced_telemetry_is_accounting_aware(tmp_path):
    import json

    from scripts import run_paired_economics as runner

    path = tmp_path / "telemetry" / "agent-performance" / "session.jsonl"
    path.parent.mkdir(parents=True)
    row = {
        "kind": "assistant_usage",
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 2,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    before = runner._telemetry_snapshot(tmp_path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({**row, "input_tokens": 3, "total_tokens": 4}) + "\n")
    appended = runner.aggregate_telemetry([path], offsets=before)
    assert appended["input_tokens"] == 3
    path.write_bytes(b"replaced")
    replaced = runner.aggregate_telemetry([path], offsets=before)
    assert replaced["accounting_available"] is False
    assert replaced["input_tokens"] is None


def test_malformed_or_missing_usage_cannot_become_complete_accounting(tmp_path):
    import json

    from scripts import run_paired_economics as runner

    path = tmp_path / "usage.jsonl"
    usage = {
        "kind": "assistant_usage",
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 2,
    }
    path.write_text(json.dumps(usage) + "\n{broken\n", encoding="utf-8")
    malformed = runner.aggregate_telemetry([path])
    assert malformed["accounting_available"] is False
    assert malformed["total_tokens"] is None
    assert malformed["model_turns"] is None

    missing = {"kind": "model_invocation_completed", "usage": None}
    path.write_text(json.dumps(usage) + "\n" + json.dumps(missing), encoding="utf-8")
    incomplete = runner.aggregate_telemetry([path])
    assert incomplete["model_turns"] == 2
    assert incomplete["total_tokens"] is None

    path.write_text(json.dumps({**usage, "input_tokens": -1}), encoding="utf-8")
    assert runner.aggregate_telemetry([path])["input_tokens"] is None


def test_pair_collection_rejects_duplicate_and_reports_missing_arms():
    import pytest
    from scripts import run_paired_economics as runner

    arm = {"run_id": "one", "task_id": "micro-01", "profile": "OFF"}
    with pytest.raises(ValueError, match="duplicate"):
        runner._paired([arm, {**arm, "run_id": "two"}])
    summary = runner.collect_reviews([arm], [])
    assert summary["unpaired_records"] == ["micro-01"]
    assert summary["quality_status"] == "FAILED"
