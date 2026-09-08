import json
import sqlite3

import pytest

from second_brain import backup, db
from second_brain.errors import BrainError, MigrationError
from second_brain.fingerprints import BottleneckCategory, BottleneckFingerprintStore
from second_brain.goals import GoalStore


def test_p4_tables_are_in_primary_database(brain_home):
    GoalStore(brain_home)
    BottleneckFingerprintStore(brain_home)
    conn = db.connect(db.db_path(brain_home))
    try:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {
        "goals",
        "goal_events",
        "bottleneck_fingerprints",
        "heartbeat_state",
        "heartbeat_runs",
    } <= names
    assert not list((brain_home / "state" / "goals").glob("*.sqlite"))
    assert not list((brain_home / "state" / "fingerprints").glob("*.sqlite"))


def test_records_survive_store_reopen(brain_home):
    goals = GoalStore(brain_home)
    fingerprints = BottleneckFingerprintStore(brain_home)
    goal = goals.create_goal("Ship P4", "Canonical persistence", ["migration"])
    fingerprint = fingerprints.record_bottleneck(
        BottleneckCategory.PROMPT_BLOAT,
        "Prompt bloat",
        "Trim unused context",
        impact_score=7.5,
        evidence_refs=["telemetry:1"],
        metadata={"z": 1, "a": "stable"},
    )
    del goals, fingerprints

    reopened_goal = GoalStore(brain_home).get_goal(goal.goal_id)
    reopened_fingerprint = BottleneckFingerprintStore(brain_home).list_top_bottlenecks()[0]
    assert reopened_goal == goal
    assert reopened_fingerprint.fingerprint_id == fingerprint.fingerprint_id
    assert reopened_fingerprint.metadata == {"z": 1, "a": "stable"}


def test_migration_is_idempotent(brain_home):
    db.migrate(db.db_path(brain_home))
    db.migrate(db.db_path(brain_home))
    conn = db.connect(db.db_path(brain_home))
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_version WHERE version = 10").fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_backup_restore_preserves_p4_records(brain_home, tmp_path):
    goal = GoalStore(brain_home).create_goal("Backup me", "Must survive restore")
    fingerprint = BottleneckFingerprintStore(brain_home).record_bottleneck(
        "TOOL_CHAIN_THRASH", "Repeated search", "Use cache", metadata={"source": "test"}
    )
    snapshot = backup.create_backup(brain_home)
    restored_home = tmp_path / "restored"
    backup.restore_backup(restored_home, snapshot)

    restored_goal = GoalStore(restored_home).get_goal(goal.goal_id)
    restored_fingerprint = BottleneckFingerprintStore(restored_home).list_top_bottlenecks()[0]
    assert restored_goal == goal
    assert restored_fingerprint.fingerprint_id == fingerprint.fingerprint_id


def test_non_empty_legacy_sidecar_is_refused_and_preserved(brain_home):
    sidecar = brain_home / "state" / "goals" / "goals.sqlite"
    sidecar.parent.mkdir(parents=True)
    conn = sqlite3.connect(sidecar)
    try:
        conn.execute("CREATE TABLE old_goals (goal_id TEXT)")
        conn.execute("INSERT INTO old_goals VALUES ('legacy')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MigrationError, match="non-empty legacy goals sidecar"):
        GoalStore(brain_home)
    assert sidecar.exists()
    assert sqlite3.connect(sidecar).execute("SELECT COUNT(*) FROM old_goals").fetchone()[0] == 1


def test_json_bounds_and_finite_scores(brain_home):
    goal = GoalStore(brain_home).create_goal("x" * 1000, "y" * 1000, ["z" * 1000])
    assert len(goal.title) == 512
    assert len(goal.description) == 512
    assert len(goal.milestones[0].title) == 512

    store = BottleneckFingerprintStore(brain_home)
    with pytest.raises(BrainError, match="finite"):
        store.record_bottleneck("PROMPT_BLOAT", "desc", "fix", impact_score=float("nan"))
    fingerprint = store.record_bottleneck(
        "PROMPT_BLOAT",
        "d" * 1000,
        "m" * 1000,
        evidence_refs=[str(i) for i in range(100)],
        metadata={"b": 1, "a": 2},
    )
    conn = db.connect(db.db_path(brain_home))
    try:
        row = conn.execute(
            "SELECT description, mitigation, evidence_refs_json, metadata_json "
            "FROM bottleneck_fingerprints WHERE fingerprint_id = ?",
            (fingerprint.fingerprint_id,),
        ).fetchone()
    finally:
        conn.close()
    assert len(row["description"]) == 512
    assert len(row["mitigation"]) == 512
    assert len(json.loads(row["evidence_refs_json"])) == 64
    assert row["metadata_json"] == '{"a":2,"b":1}'


def test_malformed_metadata_is_rejected_before_insert(brain_home):
    store = BottleneckFingerprintStore(brain_home)
    with pytest.raises(BrainError, match="malformed metadata"):
        store.record_bottleneck(
            "PROMPT_BLOAT", "description", "mitigation", metadata={"bad": object()}
        )
    conn = db.connect(db.db_path(brain_home))
    try:
        assert conn.execute("SELECT COUNT(*) FROM bottleneck_fingerprints").fetchone()[0] == 0
    finally:
        conn.close()


def test_non_empty_legacy_fingerprint_sidecar_is_refused_and_preserved(brain_home):
    sidecar = brain_home / "state" / "fingerprints" / "fingerprints.sqlite"
    sidecar.parent.mkdir(parents=True)
    conn = sqlite3.connect(sidecar)
    try:
        conn.execute("CREATE TABLE old_fingerprints (fingerprint_id TEXT)")
        conn.execute("INSERT INTO old_fingerprints VALUES ('legacy')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MigrationError, match="non-empty legacy fingerprints sidecar"):
        BottleneckFingerprintStore(brain_home)
    assert sidecar.exists()


def test_empty_legacy_sidecars_are_removed(brain_home):
    goals_sidecar = brain_home / "state" / "goals" / "goals.sqlite"
    fingerprints_sidecar = brain_home / "state" / "fingerprints" / "fingerprints.sqlite"
    goals_sidecar.parent.mkdir(parents=True)
    fingerprints_sidecar.parent.mkdir(parents=True)
    goals_sidecar.touch()
    fingerprints_sidecar.touch()

    GoalStore(brain_home)
    BottleneckFingerprintStore(brain_home)
    assert not goals_sidecar.exists()
    assert not fingerprints_sidecar.exists()
