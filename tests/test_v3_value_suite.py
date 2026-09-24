"""Unit tests for the value-suite scoring surface (scripts/v3_value_suite.py).

Scoring and aggregation only: answer checks, event/session reading, paired deltas,
bootstrap CIs and the pass rule. No host process, no provider, no repository copy.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

WORKTREE = Path(__file__).resolve().parents[1]


def _suite() -> Any:
    spec = importlib.util.spec_from_file_location(
        "v3_value_suite", WORKTREE / "scripts" / "v3_value_suite.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUITE: Any = _suite()


# ---------------------------------------------------------------------------
# Answer checking
# ---------------------------------------------------------------------------


def test_answer_matches_requires_every_group() -> None:
    groups = [["RLM_MAX_DEPTH"], ["depth 1", "depth of 1"], ["recursion", "depth"]]
    ok = SUITE.answer_matches("The cap is RLM_MAX_DEPTH=1, i.e. depth 1, no recursion.", groups)
    assert ok["ok"] is True
    assert ok["missing_groups"] == []
    missing = SUITE.answer_matches("The cap is depth 1 for child recursion.", groups)
    assert missing["ok"] is False
    assert missing["missing_groups"] == [["RLM_MAX_DEPTH"]]


def test_answer_matches_is_case_insensitive_and_regex() -> None:
    assert SUITE.answer_matches("numeric ORDER", [["numeric order"]])["ok"] is True
    assert SUITE.answer_matches("| n |", [["\\|\\s*n\\s*\\|"]])["ok"] is True
    assert SUITE.answer_matches("n", [["\\|\\s*n\\s*\\|"]])["ok"] is False


def test_answer_matches_rejects_empty_text() -> None:
    assert SUITE.answer_matches("   \n ", [["anything"]])["ok"] is False
    assert SUITE.answer_matches("", [["anything"]])["ok"] is False


def test_answer_matches_reports_every_missing_group() -> None:
    result = SUITE.answer_matches("nothing here", [["a"], ["b"]])
    assert result["missing_groups"] == [["a"], ["b"]]


def test_answer_blocks_takes_last_nonempty_block() -> None:
    assert SUITE.answer_blocks(["", "first", "  ", "last"]) == "last"
    assert SUITE.answer_blocks([]) == ""


# ---------------------------------------------------------------------------
# Host-stream reading
# ---------------------------------------------------------------------------


def _event_stream(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\nnot json\n"


def test_assistant_text_blocks_reads_text_parts_and_skips_others() -> None:
    raw = _event_stream(
        {
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "thinking", "text": "hm"}]},
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "final "}, {"type": "text", "text": "answer"}],
            },
        },
        {"type": "message_end", "message": {"role": "user", "content": "ignore me"}},
    )
    assert SUITE.assistant_text_blocks(raw) == ["final answer"]


def test_stream_tool_calls_counts_by_name() -> None:
    raw = _event_stream(
        {"type": "tool_execution_start", "toolName": "read"},
        {"type": "tool_execution_start", "toolName": "read"},
        {"type": "tool_execution_start", "toolName": "grep"},
        {"type": "message_end", "message": {"role": "assistant", "content": []}},
    )
    assert SUITE.stream_tool_calls(raw) == {"read": 2, "grep": 1}


def test_stream_custom_messages_dedupes_and_extracts_memory_ids() -> None:
    packet = "packet mem-b67de5057f76 and mem-a8d221e64549 inside"
    raw = _event_stream(
        {
            "type": "message_start",
            "message": {
                "role": "custom",
                "customType": "brain.autoinject.packet",
                "content": packet,
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "custom",
                "customType": "brain.autoinject.packet",
                "content": packet,
            },
        },
        {
            "type": "message_end",
            "message": {"role": "custom", "customType": "ledger.mirror", "content": "noise"},
        },
    )
    messages = SUITE.stream_custom_messages(raw)
    assert len(messages) == 1
    assert messages[0]["customType"] == "brain.autoinject.packet"
    assert messages[0]["chars"] == len(packet)
    assert messages[0]["memory_ids"] == ["mem-a8d221e64549", "mem-b67de5057f76"]


# ---------------------------------------------------------------------------
# Session files (subagent capture)
# ---------------------------------------------------------------------------


def _session_file(path: Path, *, parent: bool, usage: dict | None, tools: list[str]) -> None:
    records: list[dict] = [{"type": "session", "id": path.stem, "cwd": "."}]
    if not parent:
        records[0]["parentSession"] = "root.jsonl"
    if usage is not None:
        records.append(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "usage": usage,
                    "content": [{"type": "toolCall", "name": name} for name in tools],
                },
            }
        )
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def test_session_inventory_separates_subagents_and_totals_their_usage(tmp_path: Path) -> None:
    root = tmp_path / "root.jsonl"
    _session_file(root, parent=True, usage={"input": 100, "output": 10}, tools=["read"])
    child = tmp_path / "child.jsonl"
    _session_file(
        child,
        parent=False,
        usage={"input": 7, "output": 3, "cacheRead": 5, "cost": {"total": 0.5}},
        tools=["grep", "grep"],
    )
    inventory = SUITE.session_inventory(tmp_path)
    assert inventory["files"] == 2
    assert inventory["root_files"] == 1
    assert inventory["subagent_files"] == 1
    assert inventory["subagent_usage"] == {
        "input": 7,
        "output": 3,
        "cacheRead": 5,
        "cacheWrite": None,
        "reasoningTokens": None,
    }
    assert inventory["subagent_tool_calls"] == {"grep": 2}
    assert inventory["subagent_tool_calls_total"] == 2
    assert inventory["subagent_assistant_messages"] == 1
    assert inventory["subagent_cost_total"] == 0.5


def test_session_inventory_without_subagents_reports_nothing(tmp_path: Path) -> None:
    _session_file(tmp_path / "root.jsonl", parent=True, usage={"input": 5}, tools=[])
    inventory = SUITE.session_inventory(tmp_path)
    assert inventory["subagent_files"] == 0
    assert inventory["subagent_usage"]["input"] is None
    assert inventory["subagent_tool_calls_total"] == 0


def test_session_inventory_missing_directory(tmp_path: Path) -> None:
    inventory = SUITE.session_inventory(tmp_path / "absent")
    assert inventory["files"] == 0
    assert inventory["subagent_files"] == 0


def test_session_inventory_unknown_when_a_child_lacks_a_field(tmp_path: Path) -> None:
    _session_file(tmp_path / "root.jsonl", parent=True, usage={"input": 5}, tools=[])
    _session_file(
        tmp_path / "a.jsonl", parent=False, usage={"input": 100, "output": 1, "cacheRead": 4},
        tools=[],
    )
    _session_file(tmp_path / "b.jsonl", parent=False, usage={"cacheRead": 6}, tools=[])
    inventory = SUITE.session_inventory(tmp_path)
    assert inventory["subagent_files"] == 2
    # 100 is what the children that reported it used; the arm's real total is unknown.
    assert inventory["subagent_usage"]["input"] is None
    assert inventory["subagent_usage"]["output"] is None
    # Unknown stays per field: every child request reported cacheRead.
    assert inventory["subagent_usage"]["cacheRead"] == 10


def test_session_inventory_unknown_when_a_child_message_omits_a_field(tmp_path: Path) -> None:
    records = [
        {"type": "session", "id": "child", "parentSession": "root.jsonl", "cwd": "."},
        {
            "type": "message",
            "message": {"role": "assistant", "usage": {"input": 10, "output": 1}, "content": []},
        },
        {
            "type": "message",
            "message": {"role": "assistant", "usage": {"input": 20}, "content": []},
        },
    ]
    path = tmp_path / "child.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    inventory = SUITE.session_inventory(tmp_path)
    assert inventory["subagent_assistant_messages"] == 2
    assert inventory["subagent_usage"]["input"] == 30
    # 1 would silently skip the second request's usage.
    assert inventory["subagent_usage"]["output"] is None


def test_session_inventory_cost_unknown_when_a_child_never_reported_it(tmp_path: Path) -> None:
    _session_file(
        tmp_path / "a.jsonl", parent=False, usage={"input": 1, "cost": {"total": 0.5}}, tools=[]
    )
    _session_file(tmp_path / "b.jsonl", parent=False, usage={"input": 2}, tools=[])
    inventory = SUITE.session_inventory(tmp_path)
    assert inventory["subagent_usage"]["input"] == 3
    assert inventory["subagent_cost_total"] is None


# ---------------------------------------------------------------------------
# One run record: measure_run -> run_metrics
# ---------------------------------------------------------------------------


def _measure_task(task_id: str = "M1") -> dict[str, Any]:
    return {
        "id": task_id,
        "class": "memory",
        "prompt": "describe the runtime state ledger",
        "groups": [["ok"]],
        "memory_ids": [],
    }


def _host(raw: str, sessions_dir: Path, tmp_path: Path) -> dict[str, Any]:
    """The shape run_host returns, with no host process behind it."""
    return {
        "raw": raw,
        "result": {"returncode": 0, "wall_ms": 1.0, "stderr_tail": ""},
        "sessions_dir": str(sessions_dir),
        "home": None,
        "cwd": str(tmp_path / "proj"),
        "overlay": None,
        "repo_copy": {"method": "copytree", "files": 1, "excluded": [], "fallback": False},
    }


def _assistant_usage(usage: dict[str, int]) -> dict:
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "usage": usage,
        },
    }


def test_measure_run_totals_subagent_usage_as_measured_numbers(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _session_file(
        sessions / "child.jsonl",
        parent=False,
        usage={
            "input": 5,
            "output": 1,
            "cacheRead": 0,
            "cacheWrite": 0,
            "reasoningTokens": 0,
            "cost": {"total": 0.25},
        },
        tools=["read"],
    )
    raw = _event_stream(
        _assistant_usage(
            {"input": 107, "output": 13, "cacheRead": 2, "cacheWrite": 0, "reasoningTokens": 0}
        )
    )
    record = SUITE.measure_run(
        _measure_task(), "candidate", 0, "M1-candidate-R0", _host(raw, sessions, tmp_path)
    )
    metrics = SUITE.run_metrics(record)
    assert metrics["tokens_in_out"] == 126
    assert record["provider_usage"]["tokens_all"] == 128
    assert metrics["tool_calls"] == 1
    assert metrics["model_requests"] == 2
    assert metrics["correct"] is True


def test_measure_run_leaves_usage_unknown_when_a_child_lacks_a_field(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _session_file(
        sessions / "child-a.jsonl",
        parent=False,
        usage={
            "input": 100,
            "output": 10,
            "cacheRead": 4,
            "cacheWrite": 0,
            "reasoningTokens": 0,
        },
        tools=[],
    )
    _session_file(sessions / "child-b.jsonl", parent=False, usage={"cacheRead": 6}, tools=[])
    raw = _event_stream(
        _assistant_usage(
            {"input": 50, "output": 5, "cacheRead": 1, "cacheWrite": 0, "reasoningTokens": 0}
        )
    )
    record = SUITE.measure_run(
        _measure_task(), "candidate", 0, "M1-candidate-R0", _host(raw, sessions, tmp_path)
    )
    assert record["provider_usage_subagents"]["input"] is None
    assert record["provider_usage"]["input"] is None
    assert SUITE.run_metrics(record)["tokens_in_out"] is None
    # Fully reported by every child request, so still a real total.
    assert record["provider_usage"]["cacheRead"] == 11


# ---------------------------------------------------------------------------
# Paired deltas, bootstrap CI, pass rule
# ---------------------------------------------------------------------------


def _run(
    task: str, arm: str, rep: int, tokens: int | None, tools: int, correct: bool = True
) -> dict:
    return {
        "task": task,
        "class": "memory",
        "arm": arm,
        "rep": rep,
        "status": "ok",
        "correct": correct,
        "provider_usage": {"input": tokens, "output": 0, "tokens_all": tokens},
        "tool_calls_total": tools,
        "model_requests": 1,
    }


def test_run_metrics_null_when_host_never_reported_usage() -> None:
    run = _run("T1", "native", 0, None, 3)
    assert SUITE.run_metrics(run)["tokens_in_out"] is None
    assert SUITE.run_metrics(run)["tool_calls"] == 3


def test_run_metrics_reads_numeric_token_totals() -> None:
    """A merged subagent total is numeric: a reported total is never 'unknown'."""
    run = _run("T1", "native", 0, None, 3)
    run["provider_usage"] = {"input": 107.0, "output": 13.0}
    assert SUITE.run_metrics(run)["tokens_in_out"] == 120.0
    run["provider_usage"] = {"input": 107, "output": None}
    assert SUITE.run_metrics(run)["tokens_in_out"] is None


def test_paired_deltas_median_over_reps_and_delta() -> None:
    tasks = [{"id": "T1", "class": "memory", "groups": []}]
    runs = [
        _run("T1", "native", 0, 1000, 4),
        _run("T1", "native", 1, 1200, 6),
        _run("T1", "candidate", 0, 700, 2),
        _run("T1", "candidate", 1, 900, 4),
    ]
    rows = SUITE.paired_deltas(
        runs, tasks, ["native", "candidate"], lambda run: SUITE.run_metrics(run)["tokens_in_out"]
    )
    assert rows[0]["native_median"] == 1100
    assert rows[0]["candidate_median"] == 800
    assert rows[0]["delta"] == -300
    assert rows[0]["paired"] is True


def test_paired_deltas_unpaired_when_usage_unknown() -> None:
    tasks = [{"id": "T1", "class": "memory", "groups": []}]
    runs = [
        _run("T1", "native", 0, None, 4),
        _run("T1", "candidate", 0, 700, 2),
    ]
    rows = SUITE.paired_deltas(
        runs, tasks, ["native", "candidate"], lambda run: SUITE.run_metrics(run)["tokens_in_out"]
    )
    assert rows[0]["delta"] is None
    assert rows[0]["paired"] is False


def test_paired_deltas_missing_arm_run_is_not_paired() -> None:
    tasks = [{"id": "T1", "class": "memory", "groups": []}]
    runs = [_run("T1", "native", 0, 1000, 4)]
    rows = SUITE.paired_deltas(
        runs, tasks, ["native", "candidate"], lambda run: SUITE.run_metrics(run)["tokens_in_out"]
    )
    assert rows[0]["delta"] is None


def test_bootstrap_ci_is_seeded_and_brackets_the_median() -> None:
    deltas = [-500.0, -400.0, -300.0, -200.0, -100.0, -50.0, -20.0, 10.0]
    first = SUITE.bootstrap_ci(deltas, seed=7, iters=500)
    second = SUITE.bootstrap_ci(deltas, seed=7, iters=500)
    assert first == second
    assert first is not None
    assert first[0] <= -150.0 <= first[1]
    assert SUITE.bootstrap_ci([1.0], seed=7) is None


def _class_entry(
    tokens_delta: float | None,
    calls_delta: float | None,
    native_rate: float,
    candidate_rate: float,
) -> dict:
    return {
        "tokens_in_out": {"median_delta": tokens_delta, "ci": None, "per_task": []},
        "tool_calls": {"median_delta": calls_delta, "ci": None, "per_task": []},
        "correctness": {
            "native": {"rate": native_rate},
            "candidate": {"rate": candidate_rate},
        },
    }


def test_pass_rule_memory_class_passes_on_fewer_tokens() -> None:
    summary = {"memory": _class_entry(-300.0, 0.0, 1.0, 1.0)}
    verdict = SUITE.evaluate_pass_rule(summary, ["native", "candidate"])
    assert verdict["memory"]["pass"] is True
    assert verdict["pass"] is False  # no_benefit class was not measured


def test_pass_rule_memory_class_passes_on_fewer_tool_calls() -> None:
    summary = {"memory": _class_entry(0.0, -2.0, 1.0, 1.0)}
    assert SUITE.evaluate_pass_rule(summary, ["native", "candidate"])["memory"]["pass"] is True


def test_pass_rule_memory_class_fails_on_correctness_regression() -> None:
    summary = {"memory": _class_entry(-300.0, -2.0, 1.0, 0.5)}
    verdict = SUITE.evaluate_pass_rule(summary, ["native", "candidate"])
    assert verdict["memory"]["pass"] is False
    assert "correctness" in verdict["memory"]["reasons"][0]


def test_pass_rule_memory_class_fails_without_reduction() -> None:
    summary = {"memory": _class_entry(120.0, 1.0, 1.0, 1.0)}
    verdict = SUITE.evaluate_pass_rule(summary, ["native", "candidate"])
    assert verdict["memory"]["pass"] is False
    assert "no reduction" in verdict["memory"]["reasons"][0]


def test_pass_rule_no_benefit_class_fails_on_measurable_increase() -> None:
    summary = {
        "memory": _class_entry(-300.0, -2.0, 1.0, 1.0),
        "no_benefit": _class_entry(40.0, 1.0, 1.0, 1.0),
    }
    verdict = SUITE.evaluate_pass_rule(summary, ["native", "candidate"])
    assert verdict["no_benefit"]["pass"] is False
    assert verdict["pass"] is False


def test_pass_rule_no_benefit_class_allows_configured_slack() -> None:
    summary = {
        "memory": _class_entry(-300.0, -2.0, 1.0, 1.0),
        "no_benefit": _class_entry(40.0, 1.0, 1.0, 1.0),
    }
    verdict = SUITE.evaluate_pass_rule(
        summary, ["native", "candidate"], slack_tokens=50.0, slack_tool_calls=2.0
    )
    assert verdict["no_benefit"]["pass"] is True
    assert verdict["pass"] is True


def test_pass_rule_reports_unpaired_metrics() -> None:
    summary = {"memory": _class_entry(None, -2.0, 1.0, 1.0)}
    verdict = SUITE.evaluate_pass_rule(summary, ["native", "candidate"])
    assert verdict["memory"]["pass"] is False
    assert "unpaired" in verdict["memory"]["reasons"][0]


def test_class_summary_pairs_per_class() -> None:
    tasks = [
        {"id": "M1", "class": "memory", "groups": []},
        {"id": "N1", "class": "no_benefit", "groups": [["x"]]},
    ]
    runs = [
        _run("M1", "native", 0, 1000, 5),
        _run("M1", "candidate", 0, 500, 1),
        _run("N1", "native", 0, 200, 0),
        _run("N1", "candidate", 0, 220, 0),
    ]
    summary = SUITE.class_summary(runs, tasks, ["native", "candidate"], seed=1, bootstrap_iters=50)
    assert summary["memory"]["tokens_in_out"]["median_delta"] == -500.0
    assert summary["memory"]["tool_calls"]["median_delta"] == -4.0
    assert summary["no_benefit"]["tokens_in_out"]["median_delta"] == 20.0
    assert summary["memory"]["correctness"]["native"]["rate"] == 1.0


def test_class_summary_scores_correctness_per_class() -> None:
    tasks = [
        {"id": "M1", "class": "memory", "groups": []},
        {"id": "N1", "class": "no_benefit", "groups": []},
    ]
    runs = [
        _run("M1", "native", 0, 1000, 5, correct=True),
        _run("M1", "candidate", 0, 500, 1, correct=False),
        _run("N1", "native", 0, 200, 4, correct=False),
        _run("N1", "candidate", 0, 100, 1, correct=True),
    ]
    summary = SUITE.class_summary(runs, tasks, ["native", "candidate"], seed=1, bootstrap_iters=50)
    # Each class scores its own tasks: the campaign-wide average would read 0.5 twice.
    assert summary["memory"]["correctness"]["native"] == {
        "runs": 1,
        "graded": 1,
        "correct": 1,
        "rate": 1.0,
    }
    assert summary["memory"]["correctness"]["candidate"] == {
        "runs": 1,
        "graded": 1,
        "correct": 0,
        "rate": 0.0,
    }
    assert summary["no_benefit"]["correctness"]["native"]["rate"] == 0.0
    assert summary["no_benefit"]["correctness"]["candidate"]["rate"] == 1.0
    # The gate must see the memory-class regression, not the flat global rate.
    verdict = SUITE.evaluate_pass_rule(summary, ["native", "candidate"])
    assert verdict["memory"]["pass"] is False
    assert verdict["pass"] is False


# ---------------------------------------------------------------------------
# Failed runs
# ---------------------------------------------------------------------------


def _failed_run(tmp_path: Path, task: dict[str, Any]) -> dict[str, Any]:
    return SUITE.error_run_record(
        task, "candidate", 0, f"{task['id']}-candidate-R0", tmp_path, RuntimeError("boom")
    )


def test_error_run_record_reports_unknown_counts(tmp_path: Path) -> None:
    record = _failed_run(tmp_path, _measure_task())
    metrics = SUITE.run_metrics(record)
    assert record["status"] == "error"
    assert record["error"] == "RuntimeError: boom"
    assert metrics["tool_calls"] is None
    assert metrics["model_requests"] is None
    assert metrics["tokens_in_out"] is None
    assert record["provider_usage"]["input"] is None
    assert metrics["correct"] is False


def test_failed_run_cannot_pose_as_a_measurement(tmp_path: Path) -> None:
    task = _measure_task()
    failed = _failed_run(tmp_path, task)
    native = _run(task["id"], "native", 0, 1000, 4)
    rows = SUITE.paired_deltas(
        [native, failed],
        [task],
        ["native", "candidate"],
        lambda run: SUITE.run_metrics(run)["tool_calls"],
    )
    # A fabricated 0 would read as candidate -4: a measured efficiency win.
    assert rows[0]["candidate_median"] is None
    assert rows[0]["delta"] is None
    assert rows[0]["paired"] is False
    summary = SUITE.class_summary(
        [native, failed], [task], ["native", "candidate"], seed=1, bootstrap_iters=10
    )
    assert summary["memory"]["correctness"]["candidate"] == {
        "runs": 1,
        "graded": 0,
        "correct": 0,
        "rate": 0.0,
    }


# ---------------------------------------------------------------------------
# Task file and helpers
# ---------------------------------------------------------------------------


def test_load_tasks_reads_the_authored_file() -> None:
    tasks = SUITE.load_tasks(WORKTREE / "outputs/reports/v3-agent-experience/value/tasks.jsonl")
    ids = [task["id"] for task in tasks]
    assert len(ids) == len(set(ids))
    assert sum(1 for task in tasks if task["class"] == "memory") >= 10
    assert sum(1 for task in tasks if task["class"] == "no_benefit") >= 10
    for task in tasks:
        assert task["prompt"].strip()
        assert task["groups"], task["id"]
        if task["class"] == "memory":
            assert task["memory_ids"], task["id"]
            assert all(memory.startswith("mem-") for memory in task["memory_ids"])


def test_load_tasks_rejects_a_task_without_checks(tmp_path: Path) -> None:
    path = tmp_path / "tasks.jsonl"
    path.write_text(json.dumps({"id": "X", "class": "memory", "prompt": "p"}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"check\.groups"):
        SUITE.load_tasks(path)


def test_load_tasks_rejects_duplicate_ids(tmp_path: Path) -> None:
    row = {"id": "X", "class": "memory", "prompt": "p", "check": {"groups": [["a"]]}}
    path = tmp_path / "tasks.jsonl"
    path.write_text(json.dumps(row) + "\n" + json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        SUITE.load_tasks(path)


def test_select_tasks_filters_and_rejects_unknown_ids() -> None:
    tasks = SUITE.load_tasks(WORKTREE / "outputs/reports/v3-agent-experience/value/tasks.jsonl")
    selected = SUITE.select_tasks(tasks, "VG-M05,VG-N02", "")
    assert [task["id"] for task in selected] == ["VG-M05", "VG-N02"]
    assert SUITE.select_tasks(tasks, "", "no_benefit")
    with pytest.raises(ValueError, match="unknown task ids"):
        SUITE.select_tasks(tasks, "NOPE", "")


def test_sum_optional_and_sum_known_keep_unknown_null() -> None:
    assert SUITE._sum_optional(3, 4) == 7.0
    assert SUITE._sum_optional(3, None) is None
    assert SUITE._sum_optional(None, None) is None
    assert SUITE._sum_known([1, 2, 3]) == 6
    assert SUITE._sum_known([1, None]) is None
    assert SUITE._sum_known([]) is None


def test_sum_optional_preserves_integer_token_totals() -> None:
    total = SUITE._sum_optional(107, 13)
    assert total == 120
    assert isinstance(total, int)
    assert SUITE._sum_optional(1.5, 2.5) == 4.0
