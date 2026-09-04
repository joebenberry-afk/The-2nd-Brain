"""Focused T7.6 Engrams + model/harness culture + teacher/student distillation tests."""

from __future__ import annotations

from pathlib import Path

from second_brain import crossmodel, engram


def test_engram_detected_only_with_min_support() -> None:
    """Tool-call sequences must meet the minimum support threshold (>=2) to be detected."""
    seq1 = [
        {"kind": "tool_call", "tool": "git_status"},
        {"kind": "tool_call", "tool": "git_diff"},
        {"kind": "tool_call", "tool": "run_test"},
    ]
    seq2 = [
        {"kind": "tool_call", "tool": "read_file"},
        {"kind": "tool_call", "tool": "edit_file"},
    ]

    # Support = 1: Should NOT detect seq1
    res_single = engram.detect_workflow_engrams([seq1], min_support=2, min_len=3, max_len=5)
    assert res_single == []

    # Support = 2: Both session 1 and session 3 have seq1 -> Detected!
    seq3 = [
        {"kind": "tool_call", "tool": "git_status"},
        {"kind": "tool_call", "tool": "git_diff"},
        {"kind": "tool_call", "tool": "run_test"},
        {"kind": "tool_call", "tool": "git_commit"},
    ]
    res_multi = engram.detect_workflow_engrams([seq1, seq2, seq3], min_support=2, min_len=3, max_len=5)
    assert len(res_multi) >= 1
    found = res_multi[0]
    assert found["sequence"] == ["git_status", "git_diff", "run_test"]
    assert found["support"] >= 2
    assert len(found["procedure"]) == 3


def test_engram_run_uses_zero_model_calls(brain_home: Path) -> None:
    """Deterministic engram execution executes through action_cache with zero model calls."""
    engram_def = {
        "engram_id": "engram-clean-check",
        "version": 1,
        "procedure": [
            {
                "tool": "check_clean",
                "args_template": {"path": "$target_dir"},
                "precondition": {"expect_exit": 0, "actual_exit": 0},
                "postcondition": {"expect_exit": 0, "actual_exit": 0},
            },
            {
                "tool": "run_build",
                "args_template": {"mode": "fast"},
                "precondition": {"expect_exit": 0, "actual_exit": 0},
                "postcondition": {"expect_exit": 0, "actual_exit": 0},
            },
            {
                "tool": "verify_output",
                "args_template": {"artifact": "dist/bundle.js"},
                "precondition": {"expect_exit": 0, "actual_exit": 0},
                "postcondition": {"expect_exit": 0, "actual_exit": 0},
            },
        ],
    }
    engram.register_workflow_engram(brain_home, engram_def)

    tool_call_count = 0

    def mock_runner(tool: str, args: dict) -> dict:
        nonlocal tool_call_count
        tool_call_count += 1
        return {"tool": tool, "args": args, "status": "ok"}

    # Run 1: Cold execution
    res1 = engram.run_deterministic(
        brain_home,
        "engram-clean-check",
        params={"target_dir": "src/"},
        tool_runner=mock_runner,
    )
    assert res1["success"] is True
    assert res1["model_calls"] == 0
    assert res1["cache_hit"] is False
    assert tool_call_count == 3

    # Run 2: Cached execution through action_cache
    res2 = engram.run_deterministic(
        brain_home,
        "engram-clean-check",
        params={"target_dir": "src/"},
        tool_runner=mock_runner,
    )
    assert res2["success"] is True
    assert res2["model_calls"] == 0
    assert res2["cache_hit"] is True
    # Tool runner not invoked again because action_cache hit!
    assert tool_call_count == 3


def test_engram_postcondition_failure_marks_run_failed(brain_home: Path) -> None:
    """Postcondition check failures immediately halt the run and mark it failed."""
    engram_def = {
        "engram_id": "engram-failing-post",
        "version": 1,
        "procedure": [
            {
                "tool": "step_one",
                "args_template": {},
                "precondition": {"expect_exit": 0, "actual_exit": 0},
                "postcondition": {"expect_exit": 0, "actual_exit": 0},
            },
            {
                "tool": "step_two_fails_postcondition",
                "args_template": {},
                "precondition": {"expect_exit": 0, "actual_exit": 0},
                "postcondition": {"expect_exit": 0, "actual_exit": 1},  # Exit 1 != 0!
            },
            {
                "tool": "step_three_never_run",
                "args_template": {},
            },
        ],
    }
    engram.register_workflow_engram(brain_home, engram_def)

    res = engram.run_deterministic(brain_home, "engram-failing-post", params={})
    assert res["success"] is False
    assert res["failed_step"] == 1
    assert res["failed_phase"] == "postcondition"
    assert res["reason"] == "postcondition_failed"
    assert res["steps_executed"] == 1


def test_crossmodel_transfer_stays_candidate_until_verified(brain_home: Path) -> None:
    """Cross-model transfer of an engram remains a candidate in SHADOW without global scope."""
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
    # No global scope granted merely because teacher was premium model!
    assert transfer["scope"] == "candidate"


def test_teacher_student_requires_same_acceptance(brain_home: Path) -> None:
    """Student distillation must satisfy 100% of the same postconditions as the teacher."""
    fixture = {
        "expected_postconditions": ["exit_code_0", "diff_clean", "lint_passed"],
        "student_run": {
            "passed_postconditions": ["exit_code_0", "diff_clean"],  # missing lint_passed!
            "acceptance_passed": False,
        },
    }

    # Case A: Student fails one postcondition -> HELD, not approved
    eval_fail = crossmodel.evaluate_teacher_student(
        brain_home,
        engram_id="engram-clean-check",
        teacher_model="claude-3-5-sonnet",
        student_model="claude-3-5-haiku",
        fixture=fixture,
    )
    assert eval_fail["status"] == "HELD"
    assert eval_fail["transfer_approved"] is False

    # Case B: Student satisfies all postconditions -> VERIFIED
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
