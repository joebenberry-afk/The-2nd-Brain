from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from second_brain import db, telemetry
from second_brain.heartbeat import HeartbeatConfig, HeartbeatCoordinator, LocalHeartbeatEngine


def _config(home: Path, text: str) -> None:
    (home / "config" / "brain.toml").write_text(text, encoding="utf-8")


def test_shadow_is_read_only_and_active_prunes(brain_home: Path, tmp_path: Path):
    shadow = HeartbeatCoordinator(brain_home).run_if_due("session_start", "s1", tmp_path, force=True)
    assert shadow["mode"] == "shadow"
    assert shadow["model_tokens_used"] == 0
    assert shadow["maintenance_mutated"] is False

    _config(brain_home, "schema_version = 1\n[heartbeat]\nmode = 'active'\nmin_interval_seconds = 0\n")
    active = HeartbeatCoordinator(brain_home).run_if_due("session_shutdown", "s1", tmp_path, force=True)
    assert active["mode"] == "active"
    assert active["model_tokens_used"] == 0
    assert active["maintenance_mutated"] is True


def test_off_does_not_probe_or_mutate(brain_home: Path, tmp_path: Path):
    _config(brain_home, "schema_version = 1\n[heartbeat]\nmode = 'off'\n")
    result = HeartbeatCoordinator(brain_home).run_if_due("session_start", "s1", tmp_path, force=True)
    assert result == {
        "mode": "off", "event": "session_start", "due": False, "ran": False,
        "healthy": True, "db_ok": True, "cache_pruned_count": 0,
        "git_dirty": False, "issue_codes": [], "latency_ms": 0,
        "model_tokens_used": 0, "maintenance_mutated": False,
    }


def test_shadow_counts_without_deleting_expired_cache(brain_home: Path):
    cache_file = brain_home / "state" / "cache" / "action_cache.sqlite"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cache_file) as conn:
        conn.execute(
            "CREATE TABLE action_cache (action_key TEXT PRIMARY KEY, action_type TEXT, "
            "target TEXT, proof_json TEXT, output_ref TEXT, output_summary TEXT, "
            "tokens_saved_estimate INTEGER, hit_count INTEGER, created_at TEXT, "
            "last_accessed_at TEXT, expires_at TEXT)"
        )
        conn.execute(
            "INSERT INTO action_cache VALUES ('k', 'x', 't', '{}', 'r', 's', 0, 0, ?, ?, ?)",
            ("2020-01-01", "2020-01-01", "2020-01-02"),
        )
    status = LocalHeartbeatEngine(brain_home).pulse(mode="shadow")
    assert status.cache_pruned_count == 1
    with sqlite3.connect(cache_file) as conn:
        assert conn.execute("SELECT COUNT(*) FROM action_cache").fetchone()[0] == 1


def test_interval_skip_and_force(brain_home: Path, tmp_path: Path):
    _config(brain_home, "schema_version = 1\n[heartbeat]\nmode = 'shadow'\nmin_interval_seconds = 60\n")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    first = HeartbeatCoordinator(brain_home).run_if_due("turn_start", "s1", tmp_path, force=True, now=now)
    skipped = HeartbeatCoordinator(brain_home).run_if_due("turn_start", "s1", tmp_path, now=now + timedelta(seconds=1))
    forced = HeartbeatCoordinator(brain_home).run_if_due("session_shutdown", "s1", tmp_path, force=True, now=now + timedelta(seconds=1))
    assert first["ran"] is True
    assert skipped["due"] is False and skipped["ran"] is False
    assert forced["due"] is True and forced["ran"] is True


def test_concurrent_callers_reserve_one_run(brain_home: Path, tmp_path: Path):
    _config(brain_home, "schema_version = 1\n[heartbeat]\nmode = 'shadow'\nmin_interval_seconds = 60\n")
    results: list[dict] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        barrier.wait()
        results.append(HeartbeatCoordinator(brain_home).run_if_due("turn_start", "s1", tmp_path, now=datetime(2026, 1, 1, tzinfo=UTC)))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sum(result["ran"] for result in results) == 1
    with db.connect(db.db_path(brain_home)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0] == 1


def test_probe_failures_are_visible_and_nonthrowing(brain_home: Path, tmp_path: Path):
    status = LocalHeartbeatEngine(brain_home).pulse(tmp_path / "missing-repo", mode="shadow")
    assert "git_probe" in status.issues
    missing = HeartbeatCoordinator(tmp_path / "missing-home").run_if_due("session_start", "s1", tmp_path, force=True)
    assert "db_missing" in missing["issue_codes"]
    assert missing["ran"] is False


def test_cache_prune_failure_is_visible(brain_home: Path, monkeypatch, tmp_path: Path):
    _config(brain_home, "schema_version = 1\n[heartbeat]\nmode = 'active'\nmin_interval_seconds = 0\n")
    from second_brain import heartbeat
    original = heartbeat.ActionCacheStore.prune_expired
    monkeypatch.setattr(heartbeat.ActionCacheStore, "prune_expired", lambda self: (_ for _ in ()).throw(RuntimeError("no")))
    result = HeartbeatCoordinator(brain_home).run_if_due("session_start", "s1", tmp_path, force=True)
    assert "cache_prune" in result["issue_codes"]
    monkeypatch.setattr(heartbeat.ActionCacheStore, "prune_expired", original)


def test_config_fallback_is_bounded(brain_home: Path):
    _config(brain_home, "[heartbeat\ninvalid")
    config = HeartbeatConfig.load(brain_home)
    assert (config.mode, config.min_interval_seconds, config.max_run_history) == ("shadow", 60, 256)
    assert config.warning and len(config.warning) <= 200


def test_retains_only_configured_runs(brain_home: Path, tmp_path: Path):
    _config(brain_home, "schema_version = 1\n[heartbeat]\nmode = 'shadow'\nmin_interval_seconds = 0\nmax_run_history = 256\n")
    coordinator = HeartbeatCoordinator(brain_home)
    for index in range(260):
        coordinator.run_if_due("turn_start", f"s{index}", tmp_path, force=True, now=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index))
    with db.connect(db.db_path(brain_home)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0] == 256


def test_append_record_is_privacy_safe(brain_home: Path):
    record = telemetry.append_record(
        brain_home, "s1", "heartbeat_pulse",
        {"mode": "shadow", "event": "session_start", "due": True, "ran": True,
         "healthy": True, "db_ok": True, "cache_pruned_count": 0, "git_dirty": False,
         "issue_codes": [], "latency_ms": 1, "model_tokens_used": 0,
         "prompt": "secret"},
    )
    assert record["kind"] == "heartbeat_pulse"
    assert "prompt" not in record
    assert telemetry.validate(brain_home)["issues"] == []
    line = next((brain_home / "telemetry" / "agent-performance").glob("*.jsonl")).read_text()
    assert "secret" not in line


def test_heartbeat_cli_prints_result_and_appends(brain_home: Path, capsys):
    from second_brain import cli

    assert cli.main(
        [
            "--home", str(brain_home), "heartbeat", "run",
            "--event", "session_start", "--session", "cli-session", "--force", "--json",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "shadow"
    records = telemetry.iter_records(brain_home)
    assert [record["kind"] for _, _, record in records] == ["heartbeat_pulse"]
