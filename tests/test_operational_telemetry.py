import json
from pathlib import Path

import pytest

from second_brain import telemetry


def _write_records(home: Path, records: list[dict]) -> None:
    path = telemetry.telemetry_dir(home) / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def _heartbeat(**fields: object) -> dict:
    record = {
        "mode": "shadow",
        "event": "session_start",
        "due": True,
        "ran": True,
        "healthy": True,
        "db_ok": True,
        "cache_pruned_count": 0,
        "git_dirty": False,
        "issue_codes": [],
        "latency_ms": 0,
        "model_tokens_used": 0,
        "artifacts_gc_count": 0,
    }
    record.update(fields)
    return record


def test_append_record_accepts_bounded_p4_and_filters_content(brain_home: Path):
    record = telemetry.append_record(
        brain_home,
        "s1",
        "heartbeat_pulse",
        _heartbeat(prompt="secret", payload={"secret": "value"}, api_key="secret"),
    )
    assert record["kind"] == "heartbeat_pulse"
    assert telemetry.validate(brain_home)["issues"] == []
    line = next(telemetry.telemetry_dir(brain_home).glob("*.jsonl")).read_text(encoding="utf-8")
    assert "secret" not in line
    assert "payload" not in line


def test_append_record_refuses_session_path_escape(brain_home: Path):
    with pytest.raises(ValueError, match="session"):
        telemetry.append_record(brain_home, "../escape", "heartbeat_pulse", _heartbeat())


def test_validate_reports_one_issue_per_invalid_p4_field(brain_home: Path):
    _write_records(
        brain_home,
        [
            {
                "v": 2,
                "kind": "heartbeat_pulse",
                "session": "s",
                "ts": "2026-08-29T00:00:00Z",
                **_heartbeat(mode="bad", due="yes", latency_ms=-1, model_tokens_used=1),
            }
        ],
    )
    issues = telemetry.validate(brain_home)["issues"]
    assert len(issues) == 4
    assert {issue.split("invalid ", 1)[1].split(":", 1)[0] for issue in issues} == {
        "mode",
        "due",
        "latency_ms",
        "model_tokens_used",
    }


def test_operational_report_counts_grouped_events_and_hash_rereads(brain_home: Path):
    records = [
        {
            "v": 2,
            "kind": "session_start",
            "session": "s",
            "ts": "2026-08-29T00:00:00Z",
            "role": "driver",
            "harness": "prime",
        },
        {
            "v": 2,
            "kind": "turn_start",
            "session": "s",
            "ts": "2026-08-29T00:00:01Z",
            "role": "worker",
            "harness": "omp",
        },
        {
            "v": 2,
            "kind": "tool_call",
            "session": "s",
            "ts": "2026-08-29T00:00:02Z",
            "tool": "read",
            "target_sha256": "a" * 64,
        },
        {
            "v": 2,
            "kind": "tool_call",
            "session": "s",
            "ts": "2026-08-29T00:00:03Z",
            "tool": "read",
            "target_sha256": "a" * 64,
        },
        {
            "v": 2,
            "kind": "tool_result",
            "session": "s",
            "ts": "2026-08-29T00:00:04Z",
            "is_error": True,
            "output_bytes": 5,
        },
        {
            "v": 2,
            "kind": "extension_error",
            "session": "s",
            "ts": "2026-08-29T00:00:05Z",
        },
        {
            "v": 2,
            "kind": "heartbeat_pulse",
            "session": "s",
            "ts": "2026-08-29T00:00:06Z",
            **_heartbeat(),
        },
        {
            "v": 3,
            "kind": "assistant_usage",
            "session": "s",
            "ts": "2026-08-29T00:00:07Z",
            "input_tokens": 2,
            "output_tokens": 3,
            "total_tokens": 5,
        },
        {
            "v": 2,
            "kind": "bottleneck_fingerprint",
            "session": "s",
            "ts": "2026-08-29T00:00:08Z",
            "fingerprint_id": "fp",
            "category": "tool",
            "occurrence_count": 1,
            "impact_score": 1,
        },
        {
            "v": 2,
            "kind": "optimization_proposal",
            "session": "s",
            "ts": "2026-08-29T00:00:09Z",
            "proposal_id": "p",
            "status": "proposed",
        },
    ]
    _write_records(brain_home, records)
    result = telemetry.operational_report(brain_home)
    assert result["provider_tokens"] == {
        "input": 2,
        "output": 3,
        "total": 5,
        "cache_read": None,
        "cache_write": None,
    }
    assert result["file_reads"] == 2
    assert result["file_rereads"] == 1
    assert result["driver_events"] == 1
    assert result["worker_events"] == 1
    assert result["tool_errors"] == 1
    assert result["extension_errors"] == 1
    assert result["heartbeat_runs"] == 1
    assert result["fingerprint_events"] == 1
    assert result["optimization_events"] == 1


def test_validate_rejects_unbounded_bottleneck_evidence_hash(brain_home: Path):
    _write_records(
        brain_home,
        [
            {
                "v": 2,
                "kind": "bottleneck_fingerprint",
                "session": "s",
                "ts": "2026-08-29T00:00:00Z",
                "fingerprint_id": "fp",
                "category": "tool",
                "scope_id": "project",
                "occurrence_count": 1,
                "impact_score": 1.0,
                "evidence_count": 1,
                "evidence_hash": "raw-evidence",
            }
        ],
    )
    issues = telemetry.validate(brain_home)["issues"]
    assert len(issues) == 1
    assert "invalid evidence_hash" in issues[0]


def test_operational_report_groups_omp_worker_and_parent_roles(brain_home: Path):
    _write_records(
        brain_home,
        [
            {
                "v": 3,
                "kind": "omp_worker_context_handoff",
                "session": "s",
                "ts": "2026-08-29T00:00:00Z",
                "worker_role": "worker",
                "parent_role": "driver",
            }
        ],
    )
    result = telemetry.operational_report(brain_home)
    assert result["worker_events"] == 1
    assert result["driver_events"] == 1
