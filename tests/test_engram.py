"""Tests for workflow engrams (Phase 19)."""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import engram, episodes, skillforge
from second_brain.errors import BrainError


def _forge_skill(home, name, trigger="some trigger", lesson="some lesson"):
    eid = episodes.create_episode(
        home,
        "success",
        f"{name} worked",
        sections={"Trigger signals": trigger, "Reusable lesson": lesson},
    )
    skillforge.forge_candidate(home, name, [eid])
    skillforge.shadow_candidate(home, name, trigger_cases=[], baseline_cases=[])


# ---------------------------------------------------------------------------
# Detection math
# ---------------------------------------------------------------------------


def test_detect_support_and_ordering():
    sequences = [
        ["scout", "lean-build", "accuracy-gate"],
        ["scout", "lean-build"],
        ["scout"],
        ["scout", "lean-build", "accuracy-gate", "scout"],
    ]
    result = engram.detect_engrams(sequences)
    by_seq = {tuple(item["sequence"]): item for item in result}
    # (scout, lean-build) appears in sequences 0, 1, 3 -> support 3.
    assert by_seq[("scout", "lean-build")]["support"] == 3
    assert by_seq[("scout", "lean-build")]["example_tasks"] == [0, 1, 3]
    # Longer patterns first at equal support: (scout, lean-build, accuracy-gate)
    # support 2 in sequences 0 and 3.
    triple = by_seq[("scout", "lean-build", "accuracy-gate")]
    assert triple["support"] == 2
    assert triple["example_tasks"] == [0, 3]
    # Ordered by support DESC then length DESC.
    assert [item["sequence"] for item in result[:2]] == [
        ["scout", "lean-build"],
        ["scout", "lean-build", "accuracy-gate"],
    ]


def test_detect_length_bounds_and_min_support():
    sequences = [
        ["a", "b", "c", "d"],
        ["a", "b", "c", "d"],
        ["a", "b"],
    ]
    result = engram.detect_engrams(sequences, min_support=2, min_len=3, max_len=3)
    assert [item["sequence"] for item in result] == [
        ["a", "b", "c"],
        ["b", "c", "d"],
    ]
    assert all(item["support"] == 2 for item in result)
    # min_support filters patterns with support < 3 out (len-3 windows have
    # support 2 only).
    result = engram.detect_engrams(sequences, min_support=3, min_len=3, max_len=3)
    assert result == []


def test_detect_overlapping_windows_counted_once_per_sequence():
    sequences = [["a", "b", "a", "b"], ["a", "b"]]
    result = engram.detect_engrams(sequences, min_support=2, min_len=2, max_len=2)
    # (a,b) occurs twice in sequence 0 but counts once; support 2 from both.
    assert [item["sequence"] for item in result] == [["a", "b"]]
    assert result[0]["support"] == 2
    assert result[0]["example_tasks"] == [0, 1]


def test_detect_alphabetical_tiebreak():
    sequences = [["a", "b"], ["a", "c"]]
    result = engram.detect_engrams(sequences, min_support=1, min_len=2, max_len=2)
    assert [item["sequence"] for item in result] == [["a", "b"], ["a", "c"]]


def test_detect_deterministic():
    sequences = [["x", "y", "z"], ["x", "y"], ["y", "z", "x", "y"]]
    assert engram.detect_engrams(sequences) == engram.detect_engrams(sequences)


def test_detect_invalid_input():
    with pytest.raises(BrainError, match="sequences"):
        engram.detect_engrams("nope")  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="sequence 0"):
        engram.detect_engrams([["ok", 5]])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Write / validate
# ---------------------------------------------------------------------------


def _setup(home):
    _forge_skill(home, "scout")
    _forge_skill(home, "lean-build")
    _forge_skill(home, "accuracy-gate")


def test_write_engram_structure(brain_home):
    _setup(brain_home)
    path = engram.write_engram(
        brain_home,
        "unfamiliar-bug",
        skills=["scout", "lean-build", "accuracy-gate"],
        source_sequences=[["scout", "lean-build"], ["scout", "lean-build", "accuracy-gate"]],
        trigger_note="unfamiliar repository state",
    )
    assert path == brain_home / "engrams" / "candidates" / "unfamiliar-bug.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: unfamiliar-bug" in text
    assert "status: candidate" in text
    assert '"scout", "lean-build", "accuracy-gate"' in text
    assert "sources: 2" in text
    assert "# References" in text
    assert "# Trigger\n\nunfamiliar repository state" in text
    assert "# Evidence" in text
    assert "- scout -> lean-build" in text
    assert "# Non-responsibilities" in text
    assert "duplicates NO skill logic" in text
    assert "Procedure" not in text.split("# Non-responsibilities")[0]


def test_write_engram_default_trigger(brain_home):
    _setup(brain_home)
    path = engram.write_engram(
        brain_home, "default-trigger", skills=["scout"], source_sequences=[["scout"]]
    )
    assert "(infer from first skill)" in path.read_text(encoding="utf-8")


def test_write_engram_missing_skill_raises(brain_home):
    with pytest.raises(BrainError, match="do not exist"):
        engram.write_engram(
            brain_home, "ghost", skills=["scout", "ghost-skill"], source_sequences=[["scout"]]
        )


def test_write_engram_collision_retry_no_overwrite(brain_home):
    _setup(brain_home)
    first = engram.write_engram(brain_home, "dup", skills=["scout"], source_sequences=[["scout"]])
    second = engram.write_engram(brain_home, "dup", skills=["scout"], source_sequences=[["scout"]])
    assert first != second
    assert second.name == "dup-1.md"
    # Content of the first is untouched.
    assert first.read_text(encoding="utf-8").startswith("---\nname: dup")


def test_validate_engram_ok(brain_home):
    _setup(brain_home)
    engram.write_engram(
        brain_home,
        "ok-engram",
        skills=["scout", "lean-build"],
        source_sequences=[["scout", "lean-build"]],
    )
    result = engram.validate_engram(brain_home, "ok-engram")
    assert result["ok"] is True
    assert result["issues"] == []


def test_validate_engram_catches_issues(brain_home):
    _setup(brain_home)
    path = engram.write_engram(
        brain_home, "bad-engram", skills=["scout"], source_sequences=[["scout"]]
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace("# Evidence\n\n- scout\n", "# Evidence\n\n\n")
    text += "\n# Procedure\n\n1. do the whole thing myself\n"
    text = text.replace('skills: ["scout"]', 'skills: ["scout", "ghost-skill"]')
    path.write_text(text, encoding="utf-8")
    result = engram.validate_engram(brain_home, "bad-engram")
    assert result["ok"] is False
    joined = "\n".join(result["issues"])
    assert "ghost-skill" in joined
    assert "Procedure" in joined
    assert "Evidence" in joined


def test_validate_unknown_engram_raises(brain_home):
    with pytest.raises(BrainError, match="No candidate engram"):
        engram.validate_engram(brain_home, "nope")


def test_list_engrams(brain_home):
    _setup(brain_home)
    assert engram.list_engrams(brain_home) == []
    engram.write_engram(brain_home, "b-engram", skills=["scout"], source_sequences=[["scout"]])
    engram.write_engram(brain_home, "a-engram", skills=["scout"], source_sequences=[["scout"]])
    assert engram.list_engrams(brain_home) == ["a-engram", "b-engram"]


# ---------------------------------------------------------------------------
# Hypothesis: brute-force cross-check + determinism
# ---------------------------------------------------------------------------


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(
        st.lists(st.sampled_from(("a", "b", "c", "d")), min_size=1, max_size=6),
        min_size=1,
        max_size=6,
    )
)
def test_detect_matches_brute_force(brain_home, sequences):
    result = engram.detect_engrams(sequences, min_support=2, min_len=2, max_len=3)
    # Determinism.
    assert engram.detect_engrams(sequences, min_support=2, min_len=2, max_len=3) == result
    # Brute-force cross-check.
    brute: dict[tuple[str, ...], int] = {}
    for sequence in sequences:
        windows = set()
        for start in range(len(sequence)):
            for length in (2, 3):
                if start + length <= len(sequence):
                    windows.add(tuple(sequence[start : start + length]))
        for window in windows:
            brute[window] = brute.get(window, 0) + 1
    detected = {tuple(item["sequence"]): item["support"] for item in result}
    expected = {window: count for window, count in brute.items() if count >= 2}
    assert detected == expected
