import json
from pathlib import Path

from second_brain import capsule_runtime
from second_brain.errors import BrainError


def test_ensure_creates_bounded_capsule_and_returns_identity(brain_home):
    objective = "objective " + ("x" * 700)

    result = capsule_runtime.ensure_capsule(
        brain_home,
        "omp-session-1",
        objective=objective,
        next_action=objective,
    )

    assert result["session_id"] == "omp-session-1"
    assert result["changed"] is True
    assert result["capsule_bytes"] > 0
    assert len(result["capsule"]["objective"]) <= capsule_runtime.MAX_TEXT_CHARS
    assert len(result["capsule"]["next_action"]) <= capsule_runtime.MAX_TEXT_CHARS
    assert "x" * 700 not in json.dumps(result["capsule"])


def test_update_merges_recent_state_without_replacing_prior_state(brain_home):
    capsule_runtime.ensure_capsule(brain_home, "s1", objective="Build it")
    capsule_runtime.update_capsule(
        brain_home,
        "s1",
        decisions=["reuse VMem"],
        open_questions=["Is the host restarted?"],
    )

    result = capsule_runtime.update_capsule(
        brain_home,
        "s1",
        decisions=["persist before compact"],
        open_questions=["Is the host restarted?"],
        verification={"pre_compaction": "persisted"},
    )

    capsule = result["capsule"]
    assert capsule["decisions_this_session"] == ["reuse VMem", "persist before compact"]
    assert capsule["open_questions"] == ["Is the host restarted?"]
    assert capsule["verification"]["pre_compaction"] == "persisted"
    assert result["changed"] is True


def test_update_is_noop_for_unchanged_state(brain_home):
    first = capsule_runtime.ensure_capsule(brain_home, "s1", objective="Build it")
    second = capsule_runtime.ensure_capsule(brain_home, "s1", objective="Build it")

    assert second["changed"] is False
    assert second["capsule"]["updated_at"] == first["capsule"]["updated_at"]


def test_corrupt_existing_capsule_is_not_replaced(brain_home):
    capsule_runtime.ensure_capsule(brain_home, "s1", objective="Build it")
    path = brain_home / "state" / "sessions" / "s1" / "active-state.json"
    path.write_text("{broken", encoding="utf-8")

    try:
        capsule_runtime.ensure_capsule(brain_home, "s1", objective="Replace me")
    except BrainError as exc:
        assert "Corrupt" in str(exc)
    else:
        raise AssertionError("corrupt capsule was silently replaced")


def test_capsule_metadata_hashes_atomic_file(brain_home):
    result = capsule_runtime.ensure_capsule(brain_home, "s1", objective="Build it")
    path = Path(result["capsule_path"])

    assert path.is_file()
    assert result["capsule_sha256"]
    assert result["capsule_bytes"] == path.stat().st_size


def test_update_drops_oldest_item_to_capsule_history_beyond_max(brain_home):
    capsule_runtime.ensure_capsule(brain_home, "s2", objective="Build it")
    items = [f"decision-{i}" for i in range(8)]
    capsule_runtime.update_capsule(brain_home, "s2", decisions=items)

    history_path = brain_home / "state" / "sessions" / "s2" / "capsule-history.jsonl"
    assert not history_path.exists()

    result = capsule_runtime.update_capsule(brain_home, "s2", decisions=["decision-8"])

    capsule = result["capsule"]
    assert capsule["decisions_this_session"] == [f"decision-{i}" for i in range(1, 9)]
    assert len(capsule["decisions_this_session"]) == capsule_runtime.MAX_ITEMS

    lines = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["dropped_item"] == "decision-0"
    assert lines[0]["field"] == "decisions_this_session"
    assert lines[0]["session_id"] == "s2"
    assert lines[0]["ts"]
