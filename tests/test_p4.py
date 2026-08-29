import json
from pathlib import Path

from second_brain import p4, telemetry


def _write_repeated_read_stream(home: Path, session: str, target_hash: str, count: int = 3) -> None:
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


def _kinds(home: Path, session: str) -> list[str]:
    return [
        record["kind"]
        for _, _, record in telemetry.iter_records(home)
        if record.get("session") == session
    ]


def test_p4_pulse_runs_heartbeat_and_shutdown_radar(brain_home, tmp_path):
    result = p4.pulse(
        brain_home,
        event="session_shutdown",
        session_id="s1",
        repo_dir=tmp_path,
        project_id="second-brain",
        force=True,
    )
    assert result["heartbeat"]["model_tokens_used"] == 0
    assert "candidates" in result
    assert "fingerprints" in result


def test_session_start_and_turn_start_omit_radar_even_with_project_id(brain_home, tmp_path):
    _write_repeated_read_stream(brain_home, "s2", "a" * 64)

    for event in ("session_start", "turn_start"):
        result = p4.pulse(
            brain_home,
            event=event,
            session_id="s2",
            repo_dir=tmp_path,
            project_id="project-a",
            force=True,
        )
        assert result["candidates"] == []
        assert result["candidate_count"] == 0
        assert result["fingerprints"] == []


def test_shutdown_includes_radar_when_project_id_present(brain_home, tmp_path):
    _write_repeated_read_stream(brain_home, "s3", "b" * 64)

    result = p4.pulse(
        brain_home,
        event="session_shutdown",
        session_id="s3",
        repo_dir=tmp_path,
        project_id="project-a",
        force=True,
    )

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["candidate_type"] == "REPEATED_READ"
    assert len(result["fingerprints"]) == 1
    assert result["fingerprints"][0]["fingerprint_id"]
    assert "bottleneck_fingerprint" in _kinds(brain_home, "s3")


def test_missing_optional_project_id_does_not_crash(brain_home, tmp_path):
    _write_repeated_read_stream(brain_home, "s4", "c" * 64)

    result = p4.pulse(
        brain_home,
        event="session_shutdown",
        session_id="s4",
        repo_dir=tmp_path,
        project_id=None,
        force=True,
    )

    assert result["candidates"] == []
    assert result["candidate_count"] == 0
    assert result["fingerprints"] == []


def test_default_path_writes_exactly_one_heartbeat_record(brain_home, tmp_path):
    p4.pulse(
        brain_home,
        event="session_start",
        session_id="s5",
        repo_dir=tmp_path,
        force=True,
    )

    assert _kinds(brain_home, "s5") == ["heartbeat_pulse"]


def test_no_telemetry_leaves_jsonl_unchanged(brain_home, tmp_path):
    p4.pulse(
        brain_home,
        event="session_start",
        session_id="s6",
        repo_dir=tmp_path,
        force=True,
        emit_telemetry=False,
    )

    assert _kinds(brain_home, "s6") == []
    assert not (telemetry.telemetry_dir(brain_home) / "s6.jsonl").exists()


def test_no_telemetry_shutdown_skips_fingerprint_records_too(brain_home, tmp_path):
    _write_repeated_read_stream(brain_home, "s7", "d" * 64)

    before = (telemetry.telemetry_dir(brain_home) / "s7.jsonl").read_text(encoding="utf-8")

    result = p4.pulse(
        brain_home,
        event="session_shutdown",
        session_id="s7",
        repo_dir=tmp_path,
        project_id="project-a",
        force=True,
        emit_telemetry=False,
    )

    after = (telemetry.telemetry_dir(brain_home) / "s7.jsonl").read_text(encoding="utf-8")
    assert after == before
    assert result["candidate_count"] == 1
    assert result["fingerprints"]


def test_p4_pulse_cli_prints_result_and_appends(brain_home, capsys):
    from second_brain import cli

    assert cli.main(
        [
            "--home", str(brain_home), "p4", "pulse",
            "--event", "session_start", "--session", "cli-session", "--force", "--json",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["session_id"] == "cli-session"
    assert result["heartbeat"]["mode"] == "shadow"
    assert _kinds(brain_home, "cli-session") == ["heartbeat_pulse"]


def test_p4_pulse_cli_no_telemetry_flag(brain_home, capsys):
    from second_brain import cli

    assert cli.main(
        [
            "--home", str(brain_home), "p4", "pulse",
            "--event", "session_start", "--session", "cli-no-telemetry",
            "--force", "--no-telemetry", "--json",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["session_id"] == "cli-no-telemetry"
    assert _kinds(brain_home, "cli-no-telemetry") == []
