"""Tests for the metacognitive monitor (Phase 11)."""

import json
from pathlib import Path

from second_brain import monitor

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trajectories.json"


def _conf(**overrides):
    """assess_confidence with empty defaults; override any input."""
    args = {
        "capsule": {},
        "requirements": [],
        "reads": [],
        "telemetry_records": [],
        "git_info": {},
    }
    args.update(overrides)
    return monitor.assess_confidence(**args)


def _sig(result, name):
    return next(s for s in result["signals"] if s["name"] == name)


# ---------------------------------------------------------------------------
# Signal math
# ---------------------------------------------------------------------------


def test_failed_commands_signal():
    telemetry = [
        {"kind": "tool_result", "tool": "bash", "is_error": True},
        {"kind": "tool_result", "tool": "bash", "is_error": True},
    ]
    assert _sig(_conf(telemetry_records=telemetry), "failed_commands")["strength"] == 2
    assert _sig(_conf(telemetry_records=telemetry[:1]), "failed_commands")["strength"] == 1
    assert _sig(_conf(), "failed_commands")["strength"] == 0
    # non-error results and other kinds do not count
    mixed = [{"kind": "tool_result", "is_error": False}, {"kind": "turn_end"}]
    assert _sig(_conf(telemetry_records=mixed), "failed_commands")["strength"] == 0


def test_repeated_reads_signal():
    reads = [
        {"path": "a.py", "hash": "h1", "purpose": "understand"},
        {"path": "a.py", "hash": "h1", "purpose": "understand"},
        {"path": "b.py", "hash": "h2", "purpose": "understand"},
        {"path": "b.py", "hash": "h2", "purpose": "understand"},
    ]
    assert _sig(_conf(reads=reads), "repeated_reads")["value"] == 2
    assert _sig(_conf(reads=reads), "repeated_reads")["strength"] == 1
    reads3 = [
        *reads,
        {"path": "c.py", "hash": "h3", "purpose": "understand"},
        {"path": "c.py", "hash": "h3", "purpose": "understand"},
    ]
    assert _sig(_conf(reads=reads3), "repeated_reads")["strength"] == 2
    assert _sig(_conf(reads=[{"path": "a.py", "hash": "h1"}]), "repeated_reads")["strength"] == 0
    # Same path but different hash is NOT a repeated read.
    reads_diff_hash = [{"path": "a.py", "hash": "h1"}, {"path": "a.py", "hash": "h2"}]
    assert _sig(_conf(reads=reads_diff_hash), "repeated_reads")["strength"] == 0


def test_untested_requirements_signal():
    reqs = [
        {"id": "R1", "importance": "critical", "status": "unverified", "evidence": []},
        {"id": "R2", "importance": "high", "status": "partially_verified", "evidence": []},
        {"id": "R3", "importance": "critical", "status": "verified", "evidence": []},
        {"id": "R4", "importance": "normal", "status": "unverified", "evidence": []},
    ]
    assert _sig(_conf(requirements=reqs), "untested_requirements")["value"] == 2
    assert _sig(_conf(requirements=reqs), "untested_requirements")["strength"] == 2
    assert _sig(_conf(requirements=reqs[:1]), "untested_requirements")["strength"] == 1
    assert _sig(_conf(), "untested_requirements")["strength"] == 0


def test_hypothesis_reversals_signal():
    assert (
        _sig(_conf(capsule={"current_hypotheses": ["a", "b"]}), "hypothesis_reversals")["strength"]
        == 0
    )
    assert (
        _sig(_conf(capsule={"current_hypotheses": ["a", "b", "c"]}), "hypothesis_reversals")[
            "strength"
        ]
        == 1
    )
    assert (
        _sig(_conf(capsule={"current_hypotheses": list(range(6))}), "hypothesis_reversals")[
            "strength"
        ]
        == 2
    )


def test_open_questions_signal():
    assert _sig(_conf(capsule={}), "open_questions")["strength"] == 0
    assert _sig(_conf(capsule={"open_questions": ["q"]}), "open_questions")["strength"] == 1
    assert _sig(_conf(capsule={"open_questions": ["q1", "q2"]}), "open_questions")["strength"] == 1
    assert (
        _sig(_conf(capsule={"open_questions": ["q1", "q2", "q3"]}), "open_questions")["strength"]
        == 2
    )


def test_verifier_disagreement_signal():
    reqs = [{"id": "R1", "evidence": ["verifier REJECTed the claim"]}]
    assert _sig(_conf(requirements=reqs), "verifier_disagreement")["strength"] == 2
    reqs2 = [{"id": "R1", "evidence": ["I disagree with that", "independent verifier flagged"]}]
    assert _sig(_conf(requirements=reqs2), "verifier_disagreement")["strength"] == 2
    assert _sig(_conf(), "verifier_disagreement")["strength"] == 0


def test_flaky_tests_signal():
    for text in ("test is flaky", "intermittent failure", "NONDETERMINISTIC ordering"):
        reqs = [{"id": "R1", "evidence": [text]}]
        assert _sig(_conf(requirements=reqs), "flaky_tests")["strength"] == 2
    assert _sig(_conf(), "flaky_tests")["strength"] == 0


def test_speculative_edits_signal():
    assert (
        _sig(_conf(capsule={"files_touched": list(range(5))}), "speculative_edits")["strength"] == 0
    )
    assert (
        _sig(_conf(capsule={"files_touched": list(range(6))}), "speculative_edits")["strength"] == 1
    )
    assert (
        _sig(_conf(capsule={"files_touched": list(range(11))}), "speculative_edits")["strength"]
        == 2
    )


def test_context_pressure_signal():
    tele = [{"kind": "context", "context_usage": {"percent": 50}}]
    assert _sig(_conf(telemetry_records=tele), "context_pressure")["strength"] == 0
    tele = [{"kind": "context", "context_usage": {"percent": 51}}]
    assert _sig(_conf(telemetry_records=tele), "context_pressure")["strength"] == 1
    tele = [{"kind": "context", "context_usage": {"percent": 80}}]
    assert _sig(_conf(telemetry_records=tele), "context_pressure")["strength"] == 1
    tele = [{"kind": "context", "context_usage": {"percent": 81}}]
    assert _sig(_conf(telemetry_records=tele), "context_pressure")["strength"] == 2
    # max across records wins
    tele = [
        {"kind": "context", "context_usage": {"percent": 20}},
        {"kind": "context", "context_usage": {"percent": 90}},
    ]
    assert _sig(_conf(telemetry_records=tele), "context_pressure")["strength"] == 2
    assert _sig(_conf(), "context_pressure")["strength"] == 0


def test_stale_source_signal():
    assert _sig(_conf(git_info={"dirty": False}), "stale_source")["strength"] == 0
    assert _sig(_conf(git_info={"dirty": True}), "stale_source")["strength"] == 1
    assert (
        _sig(_conf(git_info={"dirty": True, "uncommitted_files": 5}), "stale_source")["strength"]
        == 1
    )
    assert (
        _sig(_conf(git_info={"dirty": True, "uncommitted_files": 6}), "stale_source")["strength"]
        == 2
    )
    assert (
        _sig(_conf(git_info={"dirty": False, "uncommitted_files": 9}), "stale_source")["strength"]
        == 2
    )


def test_search_depth_signal():
    reads = [{"path": f"f{i}.py", "hash": f"h{i}", "purpose": "search for x"} for i in range(4)]
    assert _sig(_conf(reads=reads), "search_depth")["strength"] == 0
    reads = [{"path": f"f{i}.py", "hash": f"h{i}", "purpose": "search"} for i in range(5)]
    assert _sig(_conf(reads=reads), "search_depth")["strength"] == 1
    reads = [{"path": f"f{i}.py", "hash": f"h{i}", "purpose": "Search"} for i in range(10)]
    assert _sig(_conf(reads=reads), "search_depth")["strength"] == 2
    reads = [{"path": "a.py", "hash": "h", "purpose": "understand"}]
    assert _sig(_conf(reads=reads), "search_depth")["strength"] == 0


def test_all_signals_have_detail_and_fixed_order():
    result = _conf()
    assert [s["name"] for s in result["signals"]] == [
        "failed_commands",
        "repeated_reads",
        "untested_requirements",
        "hypothesis_reversals",
        "open_questions",
        "verifier_disagreement",
        "flaky_tests",
        "speculative_edits",
        "context_pressure",
        "stale_source",
        "search_depth",
    ]
    for signal in result["signals"]:
        assert signal["detail"]
        assert signal["effect"] in monitor.AXES
        assert signal["strength"] in (0, 1, 2)


# ---------------------------------------------------------------------------
# Thresholds and axes
# ---------------------------------------------------------------------------


def test_axis_threshold_boundaries():
    # epistemic: 2 -> HIGH (upper boundary)
    result = _conf(
        capsule={"open_questions": ["q1", "q2"], "current_hypotheses": ["h1", "h2", "h3"]}
    )
    assert result["scores"]["epistemic"] == 2
    assert result["epistemic"] == "HIGH"
    # epistemic: 3 -> MEDIUM (lower boundary)
    result = _conf(
        capsule={"open_questions": ["q1", "q2", "q3"], "current_hypotheses": ["h1", "h2", "h3"]}
    )
    assert result["scores"]["epistemic"] == 3
    assert result["epistemic"] == "MEDIUM"
    # execution: 5 -> MEDIUM (upper boundary)
    result = _conf(
        capsule={"files_touched": list(range(11))},
        telemetry_records=[
            {"kind": "tool_result", "is_error": True},
            {"kind": "context", "context_usage": {"percent": 81}},
        ],
    )
    assert result["scores"]["execution"] == 5
    assert result["execution"] == "MEDIUM"
    # execution: 6 -> LOW (lower boundary)
    result = _conf(
        capsule={"files_touched": list(range(11))},
        telemetry_records=[
            {"kind": "tool_result", "is_error": True},
            {"kind": "tool_result", "is_error": True},
            {"kind": "context", "context_usage": {"percent": 81}},
        ],
    )
    assert result["scores"]["execution"] == 6
    assert result["execution"] == "LOW"


def test_every_axis_has_contributing_signals():
    result = _conf()
    for axis in monitor.AXES:
        names = [s["name"] for s in result["signals"] if s["effect"] == axis]
        assert names, axis
        # The axis confidence is exactly the sum of its signal strengths.
        assert result["scores"][axis] == sum(
            s["strength"] for s in result["signals"] if s["effect"] == axis
        )


def test_determinism():
    args = {
        "capsule": {
            "open_questions": ["q1", "q2", "q3"],
            "current_hypotheses": ["h1", "h2", "h3"],
            "files_touched": list(range(7)),
        },
        "requirements": [
            {
                "id": "R1",
                "importance": "critical",
                "status": "unverified",
                "evidence": ["flaky test"],
            }
        ],
        "reads": [{"path": "a.py", "hash": "h1", "purpose": "search"}],
        "telemetry_records": [{"kind": "tool_result", "is_error": True}],
        "git_info": {"dirty": True},
    }
    assert monitor.assess_confidence(**args) == monitor.assess_confidence(**args)


def test_empty_trajectory_is_high():
    result = _conf()
    assert result["epistemic"] == "HIGH"
    assert result["execution"] == "HIGH"
    assert result["verification"] == "HIGH"


def test_basic_heuristic():
    empty = ({}, [], [], [], {})
    assert monitor.basic_heuristic(*empty) == "HIGH"
    failed = ({}, [], [], [{"kind": "tool_result", "is_error": True}], {})
    assert monitor.basic_heuristic(*failed) == "LOW"
    untested = ({}, [{"id": "R1", "importance": "critical", "status": "unverified"}], [], [], {})
    assert monitor.basic_heuristic(*untested) == "LOW"
    verified = ({}, [{"id": "R1", "importance": "critical", "status": "verified"}], [], [], {})
    assert monitor.basic_heuristic(*verified) == "HIGH"


# ---------------------------------------------------------------------------
# Eval fixture
# ---------------------------------------------------------------------------


def test_eval_fixture_shape_and_agreement():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    trajectories = data["trajectories"]
    assert len(trajectories) >= 12
    outcomes = [t["outcome"] for t in trajectories]
    assert outcomes.count("bad") >= 6
    assert outcomes.count("good") >= 6

    result = monitor.eval_monitor(trajectories)
    assert result["n"] == len(trajectories)
    assert result["random_expectation"] == 0.5
    # Acceptance (plan §107): monitor beats the basic heuristic on this fixture.
    assert result["monitor_agreement"] > result["basic_agreement"]
    # And both must be at/above the honest random expectation (0.5).
    assert result["monitor_agreement"] >= 0.5
    assert result["basic_agreement"] >= 0.5
    assert set(result["monitor_predictions"]) == set(result["outcomes"])
    assert set(result["basic_predictions"]) == set(result["outcomes"])


def test_eval_monitor_robust_to_empty_trajectories():
    result = monitor.eval_monitor([{"label": "x", "outcome": "good"}])
    assert result["monitor_predictions"]["x"] == "good"
    assert result["basic_predictions"]["x"] == "good"
