import json
from pathlib import Path

from second_brain import telemetry
from second_brain.radar import ImprovementRadar, InefficiencyPattern


def _write_stream(home: Path, session: str, target_hash: str, count: int = 3) -> None:
    directory = telemetry.telemetry_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "v": 2,
            "kind": "tool_call",
            "session": session,
            "ts": f"2026-08-26T00:00:0{i}Z",
            "tool": "read",
            "id": f"call-{i}",
            "target_sha256": target_hash,
            "input_bytes": 80,
        }
        for i in range(count)
    ]
    (directory / f"{session}.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def test_observe_session_persists_bounded_candidate_and_deduplicates(brain_home):
    _write_stream(brain_home, "s1", "a" * 64)
    radar = ImprovementRadar(brain_home)

    first = radar.observe_session("s1", project_id="project-a", task_id="task-1")
    _write_stream(brain_home, "s2", "a" * 64)
    second = radar.observe_session("s2", project_id="project-a", task_id="task-2")

    assert len(first) == 1
    assert first[0]["candidate_type"] == InefficiencyPattern.REPEATED_READ.value
    assert first[0]["lifecycle_state"] == "candidate"
    assert first[0]["telemetry_evidence_refs"]
    assert "target_sha256" not in first[0]
    assert second[0]["candidate_id"] == first[0]["candidate_id"]
    assert second[0]["evidence_count"] > first[0]["evidence_count"]
    candidates = json.loads((brain_home / "state" / "radar" / "candidates.json").read_text())
    assert len(candidates) == 1


def test_candidate_stale_evidence_cannot_authorize_promotion(brain_home):
    _write_stream(brain_home, "stale", "b" * 64)
    radar = ImprovementRadar(brain_home)
    candidate = radar.observe_session("stale", project_id="project-a")[0]
    path = telemetry.telemetry_dir(brain_home) / "stale.jsonl"
    updated = path.read_text(encoding="utf-8").replace(
        '"input_bytes": 80',
        '"input_bytes": 81',
    )
    path.write_text(updated, encoding="utf-8")

    status = radar.validate_candidate(candidate["candidate_id"])

    assert status["status"] == "stale"
    assert status["promotion_eligible"] is False
    assert status["reason"] == "telemetry_evidence_changed"


def test_unrelated_project_gets_distinct_candidate(brain_home):
    _write_stream(brain_home, "project-a-session", "c" * 64)
    _write_stream(brain_home, "project-b-session", "c" * 64)
    radar = ImprovementRadar(brain_home)

    first = radar.observe_session("project-a-session", project_id="project-a")[0]
    second = radar.observe_session("project-b-session", project_id="project-b")[0]

    assert second["candidate_id"] != first["candidate_id"]
    assert second["project_id"] == "project-b"
