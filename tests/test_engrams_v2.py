"""Focused workflow engram execution, cache, and distillation tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from second_brain import crossmodel, engram
from second_brain.errors import BrainError
from second_brain.security.paths import resolve_under


def _event(tool: str, session: str = "session", **args: object) -> dict[str, object]:
    return {
        "kind": "tool_call",
        "session": session,
        "tool": tool,
        "input": args,
        "result": {"exit_code": 0, "side_effect": False},
    }


def _result(
    tool: str, *, exit_code: int = 0, side_effect: bool = False, **extra: object
) -> dict[str, object]:
    return {"tool": tool, "exit_code": exit_code, "side_effect": side_effect, **extra}


def _io_runner(home: Path, calls: list[str]):
    def run(tool: str, args: Mapping[str, object]) -> dict[str, object]:
        calls.append(tool)
        if tool == "write_marker":
            path = resolve_under(home, str(args["path"]), allow_missing=True)
            path.write_text(str(args["content"]), encoding="utf-8")
            return _result(tool, side_effect=True)
        if tool == "read_file":
            path = resolve_under(home, str(args["path"]))
            return _result(tool, content=path.read_text(encoding="utf-8"))
        raise RuntimeError(f"unsupported owned test tool: {tool}")

    return run


def _predicate_runner(home: Path, calls: list[str]):
    def run(predicate: str, args: Mapping[str, object]) -> dict[str, object]:
        calls.append(predicate)
        path = resolve_under(home, str(args["path"]), allow_missing=predicate == "path_exists")
        if predicate == "path_exists":
            return _result(predicate, exit_code=0 if path.exists() else 1)
        if predicate == "file_nonempty":
            return _result(predicate, exit_code=0 if path.is_file() and path.stat().st_size else 1)
        if predicate == "file_contains":
            return _result(
                predicate,
                exit_code=0
                if path.is_file() and str(args["text"]) in path.read_text(encoding="utf-8")
                else 1,
            )
        raise RuntimeError(f"unsupported owned test predicate: {predicate}")

    return run


def test_engram_detected_only_from_repeated_successful_calls() -> None:
    seq1 = [_event("git_status"), _event("git_diff"), _event("run_test")]
    seq2 = [_event("read_file"), _event("edit_file")]
    seq3 = [
        _event("git_status"),
        _event("git_diff"),
        _event("run_test"),
        _event("git_commit"),
    ]
    assert engram.detect_workflow_engrams([seq1], min_support=2, min_len=3, max_len=5) == []

    found = engram.detect_workflow_engrams([seq1, seq2, seq3], min_support=2, min_len=3, max_len=5)[
        0
    ]
    assert found["sequence"] == ["git_status", "git_diff", "run_test"]
    assert found["support"] == 2
    assert len(found["procedure"]) == 3
    assert found["provenance"]
    assert "valid_for" not in found
    assert "precondition" not in found["procedure"][0]


def test_missing_executor_is_refused(brain_home: Path) -> None:
    engram.register_workflow_engram(
        brain_home,
        {"engram_id": "requires-runner", "version": 1, "procedure": [{"tool": "read_file"}]},
    )
    with pytest.raises(BrainError, match="tool_runner"):
        engram.run_deterministic(brain_home, "requires-runner", params={})


def test_real_side_effects_and_predicates_execute_each_time(brain_home: Path) -> None:
    engram.register_workflow_engram(
        brain_home,
        {
            "engram_id": "owned-side-effect",
            "version": 1,
            "procedure": [
                {
                    "tool": "write_marker",
                    "args_template": {"path": "$path", "content": "$content"},
                    "precondition": {
                        "predicate": "path_exists",
                        "args_template": {"path": "$path"},
                        "expect_exit": 1,
                    },
                    "postcondition": {
                        "predicate": "file_contains",
                        "args_template": {"path": "$path", "text": "$content"},
                        "expect_exit": 0,
                    },
                }
            ],
        },
    )
    tool_calls: list[str] = []
    predicate_calls: list[str] = []
    runner = _io_runner(brain_home, tool_calls)
    predicates = _predicate_runner(brain_home, predicate_calls)
    first = engram.run_deterministic(
        brain_home,
        "owned-side-effect",
        params={"path": "state/marker.txt", "content": "owned"},
        tool_runner=runner,
        predicate_runner=predicates,
    )
    assert first["success"] is True
    assert first["cache_hit"] is False
    assert (brain_home / "state" / "marker.txt").read_text(encoding="utf-8") == "owned"
    second = engram.run_deterministic(
        brain_home,
        "owned-side-effect",
        params={"path": "state/marker.txt", "content": "owned"},
        tool_runner=runner,
        predicate_runner=predicates,
    )
    assert second["success"] is False
    assert second["reason"] == "precondition_failed"
    assert tool_calls == ["write_marker"]
    assert predicate_calls.count("path_exists") == 2


@pytest.mark.parametrize(
    ("initial", "content", "expected_success"),
    [(None, "created", True), ("original", "", False)],
)
def test_step_preconditions_observe_prior_effects(
    brain_home: Path, initial: str | None, content: str, expected_success: bool
) -> None:
    target = brain_home / "state" / "ordered.txt"
    if initial is not None:
        target.write_text(initial, encoding="utf-8")
    engram.register_workflow_engram(
        brain_home,
        {
            "engram_id": "ordered-conditions",
            "procedure": [
                {
                    "tool": "write_marker",
                    "args_template": {"path": "$path", "content": "$content"},
                    "effect": "write",
                },
                {
                    "tool": "read_file",
                    "args_template": {"path": "$path"},
                    "effect": "read",
                    "precondition": {
                        "predicate": "file_nonempty",
                        "args_template": {"path": "$path"},
                        "expect_exit": 0,
                    },
                },
            ],
        },
    )
    result = engram.run_deterministic(
        brain_home,
        "ordered-conditions",
        {"path": "state/ordered.txt", "content": content},
        tool_runner=_io_runner(brain_home, []),
        predicate_runner=_predicate_runner(brain_home, []),
    )
    assert result["success"] is expected_success
    assert target.read_text(encoding="utf-8") == content
    if expected_success:
        assert result["steps"][1]["output"]["content"] == content
    else:
        assert result["failed_step"] == 1
        assert result["failed_phase"] == "precondition"
        assert result["steps_executed"] == 1


def test_failed_tool_preserves_actual_outcome_and_side_effects(brain_home: Path) -> None:
    target = brain_home / "state" / "partial.txt"

    def partial_write(tool: str, _args: Mapping[str, object]) -> dict[str, object]:
        target.write_text("partial", encoding="utf-8")
        return _result(tool, exit_code=7, side_effect=True, stderr="write failed after mutation")

    engram.register_workflow_engram(
        brain_home,
        {
            "engram_id": "partial-outcome",
            "procedure": [{"tool": "partial_write", "effect": "write"}],
        },
    )
    result = engram.run_deterministic(brain_home, "partial-outcome", {}, tool_runner=partial_write)
    assert result["success"] is False
    assert result["steps_executed"] == 1
    assert result["steps"][0]["output"]["exit_code"] == 7
    assert result["steps"][0]["output"]["stderr"] == "write failed after mutation"
    assert target.read_text(encoding="utf-8") == "partial"


def test_read_only_cache_invalidates_on_changed_input(brain_home: Path) -> None:
    source = brain_home / "state" / "input.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("before", encoding="utf-8")
    engram.register_workflow_engram(
        brain_home,
        {
            "engram_id": "owned-read-cache",
            "version": 1,
            "cache_policy": "read_only",
            "cache_inputs": ["path"],
            "procedure": [
                {
                    "tool": "read_file",
                    "effect": "read",
                    "args_template": {"path": "$path"},
                    "postcondition": {
                        "predicate": "file_nonempty",
                        "args_template": {"path": "$path"},
                        "expect_exit": 0,
                    },
                }
            ],
        },
    )
    tool_calls: list[str] = []
    predicates: list[str] = []
    params = {"path": "state/input.txt"}
    first = engram.run_deterministic(
        brain_home,
        "owned-read-cache",
        params=params,
        tool_runner=_io_runner(brain_home, tool_calls),
        predicate_runner=_predicate_runner(brain_home, predicates),
    )
    second = engram.run_deterministic(
        brain_home,
        "owned-read-cache",
        params=params,
        tool_runner=_io_runner(brain_home, tool_calls),
        predicate_runner=_predicate_runner(brain_home, predicates),
    )
    source.write_text("after", encoding="utf-8")
    third = engram.run_deterministic(
        brain_home,
        "owned-read-cache",
        params=params,
        tool_runner=_io_runner(brain_home, tool_calls),
        predicate_runner=_predicate_runner(brain_home, predicates),
    )
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["steps_executed"] == 0
    assert third["cache_hit"] is False
    assert third["steps"][0]["output"]["content"] == "after"
    assert tool_calls == ["read_file", "read_file"]


def test_failed_tool_and_failed_postcondition_are_not_cached(brain_home: Path) -> None:
    source = brain_home / "state" / "input.txt"
    gate = brain_home / "state" / "gate.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("data", encoding="utf-8")
    gate.write_text("", encoding="utf-8")
    engram.register_workflow_engram(
        brain_home,
        {
            "engram_id": "owned-failure-cache",
            "version": 1,
            "cache_policy": "read_only",
            "cache_inputs": ["path"],
            "procedure": [
                {
                    "tool": "read_file",
                    "effect": "read",
                    "args_template": {"path": "$path"},
                    "postcondition": {
                        "predicate": "file_contains",
                        "args_template": {"path": "$gate", "text": "open"},
                        "expect_exit": 0,
                    },
                }
            ],
        },
    )
    calls: list[str] = []
    predicates: list[str] = []
    params = {"path": "state/input.txt", "gate": "state/gate.txt"}
    first = engram.run_deterministic(
        brain_home,
        "owned-failure-cache",
        params=params,
        tool_runner=_io_runner(brain_home, calls),
        predicate_runner=_predicate_runner(brain_home, predicates),
    )
    gate.write_text("open", encoding="utf-8")
    second = engram.run_deterministic(
        brain_home,
        "owned-failure-cache",
        params=params,
        tool_runner=_io_runner(brain_home, calls),
        predicate_runner=_predicate_runner(brain_home, predicates),
    )
    assert first["success"] is False
    assert first["reason"] == "postcondition_failed"
    assert second["success"] is True
    assert second["cache_hit"] is False
    assert calls == ["read_file", "read_file"]


def test_invalid_identity_and_immutable_versions(brain_home: Path) -> None:
    with pytest.raises(BrainError, match="engram name"):
        engram.register_workflow_engram(
            brain_home, {"engram_id": "../escape", "procedure": [{"tool": "read_file"}]}
        )
    with pytest.raises(BrainError, match="positive integer"):
        engram.register_workflow_engram(
            brain_home,
            {
                "engram_id": "versioned",
                "version": 0,
                "procedure": [{"tool": "read_file"}],
            },
        )
    first = engram.register_workflow_engram(
        brain_home,
        {"engram_id": "versioned", "version": 1, "procedure": [{"tool": "read_file"}]},
    )
    with pytest.raises(BrainError, match="already exists"):
        engram.register_workflow_engram(
            brain_home,
            {"engram_id": "versioned", "version": 1, "procedure": [{"tool": "write_marker"}]},
        )
    second = engram.register_workflow_engram(
        brain_home,
        {"engram_id": "versioned", "version": 2, "procedure": [{"tool": "write_marker"}]},
    )
    assert first["content_sha256"] != second["content_sha256"]
    assert json.loads((brain_home / "engrams" / "deterministic" / "versioned_v1.json").read_text())[
        "procedure"
    ] == [{"tool": "read_file"}]


def test_crossmodel_transfer_stays_candidate_until_verified(brain_home: Path) -> None:
    transfer = crossmodel.propose_transfer(
        brain_home,
        engram_id="engram-clean-check",
        from_model="claude-3-5-sonnet",
        to_model="claude-3-5-haiku",
        harness="claude-code",
    )
    assert transfer["status"] == "candidate"
    assert transfer["rollout_stage"] == "SHADOW"
    assert transfer["verified"] is False
    assert transfer["scope"] == "candidate"


def test_teacher_student_requires_same_acceptance(brain_home: Path) -> None:
    fixture = {
        "expected_postconditions": ["exit_code_0", "diff_clean", "lint_passed"],
        "student_run": {
            "passed_postconditions": ["exit_code_0", "diff_clean"],
            "acceptance_passed": False,
        },
    }
    eval_fail = crossmodel.evaluate_teacher_student(
        brain_home,
        engram_id="engram-clean-check",
        teacher_model="claude-3-5-sonnet",
        student_model="claude-3-5-haiku",
        fixture=fixture,
    )
    assert eval_fail["status"] == "HELD"
    assert eval_fail["transfer_approved"] is False

    fixture_pass = {
        "expected_postconditions": ["exit_code_0", "diff_clean", "lint_passed"],
        "student_run": {
            "passed_postconditions": ["exit_code_0", "diff_clean", "lint_passed"],
            "acceptance_passed": True,
        },
    }
    eval_pass = crossmodel.evaluate_teacher_student(
        brain_home,
        engram_id="engram-clean-check",
        teacher_model="claude-3-5-sonnet",
        student_model="claude-3-5-haiku",
        fixture=fixture_pass,
    )
    assert eval_pass["status"] == "VERIFIED"
    assert eval_pass["transfer_approved"] is True
