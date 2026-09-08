import json
from pathlib import Path

import pytest

from second_brain import cli, db, telemetry
from second_brain.errors import BrainError
from second_brain.fingerprints import BottleneckFingerprintStore
from second_brain.radar import ImprovementRadar


def _write_stream(home: Path, session: str, target_sha: str) -> None:
    path = telemetry.telemetry_dir(home) / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "v": 2,
            "kind": "tool_call",
            "session": session,
            "ts": f"2026-08-29T00:00:0{index}Z",
            "tool": "read",
            "input_bytes": 10,
            "target_sha256": target_sha,
        }
        for index in (1, 2, 3)
    ]
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def test_radar_observation_deduplicates_scoped_fingerprint(brain_home):
    _write_stream(brain_home, "s1", "a" * 64)
    radar = ImprovementRadar(brain_home)
    first = radar.observe_session("s1", project_id="project-a")
    _write_stream(brain_home, "s2", "a" * 64)
    second = radar.observe_session("s2", project_id="project-a")
    assert first[0]["fingerprints"][0]["occurrence_count"] == 1
    assert second[0]["fingerprints"][0]["occurrence_count"] == 2


def test_fingerprint_scope_does_not_cross_projects(brain_home):
    store = BottleneckFingerprintStore(brain_home)
    a = store.record_bottleneck("TOOL_CHAIN_THRASH", "same signal", "cache", scope_id="a")
    b = store.record_bottleneck("TOOL_CHAIN_THRASH", "same signal", "cache", scope_id="b")
    assert a.fingerprint_id != b.fingerprint_id


def test_fingerprint_has_no_raw_tool_payload(brain_home):
    store = BottleneckFingerprintStore(brain_home)
    row = store.record_bottleneck(
        "UNCOMPRESSED_PAYLOAD",
        "large result",
        "artifact",
        scope_id="p",
        evidence_refs=[{"record_hash": "b" * 64, "output_bytes": 100}],
    )
    encoded = json.dumps(row.to_dict(), sort_keys=True)
    assert "Authorization" not in encoded
    assert "secret-value" not in encoded


def test_fingerprint_rejects_invalid_values(brain_home):
    store = BottleneckFingerprintStore(brain_home)
    with pytest.raises(BrainError):
        store.record_bottleneck("", "signal", "cache")
    with pytest.raises(BrainError):
        store.record_bottleneck("TOOL_CHAIN_THRASH", "signal", "cache", impact_score=float("nan"))
    with pytest.raises(BrainError):
        store.record_bottleneck(
            "TOOL_CHAIN_THRASH",
            "signal",
            "cache",
            metadata={"x": "y" * 10_000},
        )


def test_fingerprint_merges_latest_bounded_evidence_by_hash(brain_home):
    store = BottleneckFingerprintStore(brain_home)
    first_refs = [{"record_hash": f"{index:064x}", "output_bytes": index} for index in range(64)]
    second_refs = [
        {"record_hash": f"{index:064x}", "output_bytes": index + 100} for index in range(32, 96)
    ]
    first = store.record_bottleneck(
        "TOOL_CHAIN_THRASH", "same signal", "cache", scope_id="p", evidence_refs=first_refs
    )
    second = store.record_bottleneck(
        "TOOL_CHAIN_THRASH", "same signal", "cache", scope_id="p", evidence_refs=second_refs
    )
    assert first.occurrence_count == 1
    assert second.occurrence_count == 2
    assert len(second.evidence_refs or []) == 64
    assert [ref["record_hash"] for ref in second.evidence_refs or []] == [
        f"{index:064x}" for index in range(32, 96)
    ]


def test_record_alert_uses_deterministic_fixed_mapping(brain_home):
    from second_brain.radar import ImprovementAlert, InefficiencyPattern

    store = BottleneckFingerprintStore(brain_home)
    expected = {
        InefficiencyPattern.REPEATED_READ: "TOOL_CHAIN_THRASH",
        InefficiencyPattern.TOOL_ERROR_LOOP: "TOOL_CHAIN_THRASH",
        InefficiencyPattern.SEARCH_THRASH: "RETRIEVAL_OVERLOAD",
        InefficiencyPattern.REDUNDANT_TEST_RUN: "TOOL_CHAIN_THRASH",
        InefficiencyPattern.CONTEXT_CHURN: "PROMPT_BLOAT",
    }
    for pattern, category in expected.items():
        row = store.record_alert(
            ImprovementAlert(pattern, "WARNING", "secret summary", tokens_wasted_estimate=999999),
            scope_id="p",
            evidence_refs=[],
        )
        assert row.category.value == category
        assert row.description != "secret summary"


def test_radar_emits_fingerprint_telemetry_without_raw_payload(brain_home):
    _write_stream(brain_home, "telemetry-session", "c" * 64)
    radar = ImprovementRadar(brain_home)
    radar.observe_session("telemetry-session", project_id="project-a")
    records = list(telemetry.iter_records(brain_home))
    fingerprint_records = [
        record for _, _, record in records if record.get("kind") == "bottleneck_fingerprint"
    ]
    assert len(fingerprint_records) == 1
    record = fingerprint_records[0]
    assert set(record) >= {
        "fingerprint_id",
        "category",
        "scope_id",
        "occurrence_count",
        "impact_score",
        "evidence_count",
        "evidence_hash",
    }
    assert "target_sha256" not in record
    assert "Authorization" not in json.dumps(record)


def test_radar_cli_retains_existing_keys_and_flattens_fingerprints(brain_home, repo, capsys):
    _write_stream(brain_home, "cli-session", "d" * 64)
    assert (
        cli.main(
            [
                "--home",
                str(brain_home),
                "radar",
                "observe",
                "cli-session",
                "--project-id",
                "project-a",
                "--repo",
                str(repo),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) >= {"candidate_count", "candidates", "radar_overhead_ms", "fingerprints"}
    assert len(payload["fingerprints"]) == 1
    assert payload["fingerprints"][0]["category"] == "TOOL_CHAIN_THRASH"


def test_radar_bounds_long_project_scope_for_store_and_telemetry(brain_home):
    _write_stream(brain_home, "long-scope", "e" * 64)
    project_id = "project-" + ("x" * 200)
    result = ImprovementRadar(brain_home).observe_session("long-scope", project_id=project_id)
    assert result[0]["fingerprints"][0]["scope_id"] == project_id[:128]
    records = [
        record
        for _, _, record in telemetry.iter_records(brain_home)
        if record.get("kind") == "bottleneck_fingerprint"
    ]
    assert records[0]["scope_id"] == project_id[:128]


def test_radar_migrates_missing_fingerprint_on_duplicate_observation(brain_home):
    _write_stream(brain_home, "legacy", "f" * 64)
    radar = ImprovementRadar(brain_home)
    first = radar.observe_session("legacy", project_id="project-a")[0]
    path = brain_home / "state" / "radar" / "candidates.json"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted[0].pop("fingerprints", None)
    path.write_text(json.dumps(persisted), encoding="utf-8")
    connection = db.connect(db.db_path(brain_home))
    try:
        connection.execute("DELETE FROM bottleneck_fingerprints")
        connection.commit()
    finally:
        connection.close()

    migrated = radar.observe_session("legacy", project_id="project-a")[0]
    assert migrated["candidate_id"] == first["candidate_id"]
    assert len(migrated["fingerprints"]) == 1
    assert migrated["fingerprints"][0]["occurrence_count"] == 1
