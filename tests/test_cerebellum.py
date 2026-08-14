"""Tests for the Cerebellum predictive workflow monitor (Phase 12)."""

import json
from pathlib import Path
from statistics import median

from second_brain import cerebellum
from second_brain import working_set as ws

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "workflows.json"


def _read(path, purpose="understand", hash=None):
    return {
        "path": path,
        "hash": hash or path,
        "purpose": purpose,
        "ts": "2026-08-14T00:00:00+00:00",
    }


def _state(reads=None, requirements=None, files_touched=None):
    return cerebellum.assess_state(reads or [], requirements or [], files_touched or [])


# ---------------------------------------------------------------------------
# Rule math
# ---------------------------------------------------------------------------


def test_looping_rule_pure_repeat():
    result = _state(
        reads=[_read("a.py"), _read("a.py")],
        requirements=[{"id": "R1", "importance": "critical", "status": "unverified"}],
    )
    assert result["progress"] == "looping"
    assert result["signals"][0]["name"] == "looping"
    assert "a.py" in result["signals"][0]["detail"]


def test_looping_rule_new_path_between_repeats_clears():
    result = _state(reads=[_read("a.py"), _read("b.py"), _read("a.py")])
    assert result["progress"] == "progressing"


def test_looping_rule_status_change_clears():
    result = _state(
        reads=[_read("a.py"), _read("a.py")],
        requirements=[{"id": "R1", "importance": "critical", "status": "verified"}],
    )
    assert result["progress"] == "progressing"


def test_looping_rule_different_hash_not_repeat():
    result = _state(reads=[_read("a.py", hash="h1"), _read("a.py", hash="h2")])
    assert result["progress"] == "progressing"


def test_scout_should_shrink_candidates():
    reads = [
        _read("f.py", purpose="scout candidates"),
        _read("g.py", purpose="explore"),
        _read("f.py", purpose="scout candidates"),
    ]
    result = _state(reads=reads)
    names = [s["name"] for s in result["signals"]]
    assert "scout_should_shrink_candidates" in names
    assert result["progress"] == "stalled"
    # A single scout read does not fire the rule.
    result = _state(reads=[_read("f.py", purpose="scout")])
    assert result["progress"] == "progressing"


def test_test_should_discriminate_hypothesis():
    requirements = [
        {
            "id": "REQ-1",
            "importance": "high",
            "status": "unverified",
            "evidence": ["test failed on this path"],
        }
    ]
    # x.py re-read twice, but a new path in between keeps the looping rule quiet.
    result = _state(reads=[_read("x.py"), _read("y.py"), _read("x.py")], requirements=requirements)
    names = [s["name"] for s in result["signals"]]
    assert "test_should_discriminate_hypothesis" in names
    assert result["progress"] == "stalled"
    # No test evidence -> no signal.
    requirements = [{"id": "REQ-1", "importance": "high", "status": "unverified", "evidence": []}]
    assert (
        _state(reads=[_read("x.py"), _read("y.py"), _read("x.py")], requirements=requirements)[
            "progress"
        ]
        == "progressing"
    )
    # Verified requirement -> no signal.
    requirements = [
        {"id": "REQ-1", "importance": "high", "status": "verified", "evidence": ["test failed"]}
    ]
    assert (
        _state(reads=[_read("x.py"), _read("y.py"), _read("x.py")], requirements=requirements)[
            "progress"
        ]
        == "progressing"
    )


def test_verification_should_close_requirements():
    requirements = [
        {
            "id": "REQ-1",
            "importance": "critical",
            "status": "unverified",
            "evidence": ["some evidence"],
        }
    ]
    # y.py read three times total, but with a new path interleaved (no looping).
    result = _state(
        reads=[_read("y.py"), _read("z.py"), _read("y.py"), _read("y.py")],
        requirements=requirements,
    )
    names = [s["name"] for s in result["signals"]]
    assert "verification_should_close_requirements" in names
    assert result["progress"] == "stalled"
    # Two reads are not enough for this rule.
    result = _state(reads=[_read("y.py"), _read("z.py"), _read("y.py")], requirements=requirements)
    assert result["progress"] == "progressing"
    # Material requirement without evidence -> no signal.
    requirements = [
        {"id": "REQ-1", "importance": "critical", "status": "unverified", "evidence": []}
    ]
    assert (
        _state(
            reads=[_read("y.py"), _read("z.py"), _read("y.py"), _read("y.py")],
            requirements=requirements,
        )["progress"]
        == "progressing"
    )


def test_determinism():
    args = {
        "reads": [_read("a.py"), _read("a.py"), _read("b.py", purpose="scout")],
        "requirements": [
            {
                "id": "R1",
                "importance": "critical",
                "status": "unverified",
                "evidence": ["flaky test"],
            }
        ],
    }
    first = cerebellum.assess_state(**args)
    second = cerebellum.assess_state(**args)
    assert first == second


def test_events_shape():
    result = _state(reads=[_read("a.py"), _read("a.py")])
    assert result["events"][0]["rule"] == "looping"
    assert result["events"][0]["expected"]
    assert result["events"][0]["actual"]
    assert result["events"][0]["detail"]


def test_healthy_workflow_progressing():
    result = _state(reads=[_read("a.py"), _read("b.py"), _read("c.py")])
    assert result["progress"] == "progressing"
    assert result["signals"] == []


def test_fixed_baseline_rule():
    assert cerebellum._fixed_looping([_read("a.py"), _read("a.py")]) is False
    assert cerebellum._fixed_looping([_read("a.py"), _read("a.py"), _read("a.py")]) is True


# ---------------------------------------------------------------------------
# assess_workflow (working-set integration)
# ---------------------------------------------------------------------------


def test_assess_workflow_empty_session_progressing(brain_home):
    result = cerebellum.assess_workflow(brain_home, "no-such-session")
    assert result["progress"] == "progressing"
    assert result["session"] == "no-such-session"


def test_assess_workflow_reads_working_set(brain_home):
    ws.init_capsule(brain_home, "s1", "Find the bug")
    ws.add_requirement(brain_home, "s1", "Locate the leak", importance="critical")
    ws.record_read(brain_home, "s1", "a.py", "understand")
    ws.record_read(brain_home, "s1", "a.py", "understand")
    result = cerebellum.assess_workflow(brain_home, "s1")
    assert result["progress"] == "looping"
    assert result["signals"][0]["name"] == "looping"


# ---------------------------------------------------------------------------
# Eval fixture + acceptance
# ---------------------------------------------------------------------------


def test_eval_fixture_shape():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    workflows = data["workflows"]
    assert len(workflows) >= 10
    outcomes = [w["outcome"] for w in workflows]
    assert outcomes.count("looping") >= 5
    assert outcomes.count("healthy") >= 5


def test_eval_acceptance():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = cerebellum.eval_cerebellum(data["workflows"])
    assert result["n"] == len(data["workflows"])
    # Acceptance 1: cerebellum agreement >= fixed agreement.
    assert result["cerebellum_agreement"] >= result["fixed_agreement"]
    # Acceptance 2 (plan §108): earlier detection — median cerebellum flag
    # read-count is strictly below the fixed 3-read threshold on looping cases.
    flag_reads = [e["cerebellum_read"] for e in result["early_detection"]]
    assert all(read is not None for read in flag_reads)
    assert median(flag_reads) < cerebellum.FIXED_BASELINE_REPEATS
    # Every looping case is flagged by the cerebellum before or at the fixed rule.
    for entry in result["early_detection"]:
        fixed = entry["fixed_read"]
        if fixed is not None:
            assert entry["cerebellum_read"] <= fixed
