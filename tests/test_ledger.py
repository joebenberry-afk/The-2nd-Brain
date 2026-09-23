"""P2 session ledger tests (plan §9, §9.10, §11.2, §14; Phase G).

Append-only ledger substrate + independent replay/invariant checker:
contiguity, duplicate/invalid-parent rejection, object digests, FTS search +
LIKE fallback, schema versioning, replay rejection of injected corruption,
and tool-crash state classification.
"""

import hashlib
import json
import sqlite3

import pytest

from second_brain import ledger as ledger_mod
from second_brain.contracts import (
    BrainLifecycleEvent,
    BrainSessionIdentity,
    LifecycleEventType,
    SurfaceVisibility,
    ToolOutcome,
)
from second_brain.errors import BrainError

HOST = "host-session-1"


def _ev(
    seq: int,
    event_id: str,
    event_type: LifecycleEventType,
    *,
    parent: str | None = None,
    agent: str = "a1",
    payload: dict | None = None,
    ignorable: bool = False,
    segment: str | None = "seg-1",
    artifact_sha256: str | None = None,
) -> BrainLifecycleEvent:
    return BrainLifecycleEvent(
        seq=seq,
        event_id=event_id,
        internal_session_id=ledger_mod.internal_session_id(HOST),
        agent_id=agent,
        parent_event_id=parent,
        host_entry_id=f"h-{event_id}",
        host_parent_entry_id=f"h-{parent}" if parent else None,
        segment_id=segment,
        event_type=event_type,
        timestamp="2026-08-16T01:00:00Z",
        surface_visibility=SurfaceVisibility.RAW_ONLY,
        ignorable=ignorable,
        payload=payload or {},
        artifact_sha256=artifact_sha256,
        source_event_ids=[],
    )


@pytest.fixture
def store(tmp_path):
    s = ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True)
    yield s
    s.close()


def _seed(store, n: int = 4, prefix: str = "e") -> list[BrainLifecycleEvent]:
    events = []
    for i in range(1, n + 1):
        events.append(
            _ev(
                i,
                f"{prefix}-{i}",
                LifecycleEventType.USER_TASK,
                parent=f"{prefix}-{i - 1}" if i > 1 else None,
            )
        )
    store.append_events(events)
    return events


def test_init_manifest_and_header(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        internal = ledger_mod.internal_session_id(HOST)
        assert s.session_path.name == internal
        assert s.dbfile.is_file()
        assert (s.session_path / "manifest.json").is_file()
        header = s.header()
        assert header["schema_version"] == str(ledger_mod.LEDGER_SCHEMA_VERSION)
        assert header["adapter_name"] == "second-brain"
    manifest = json.loads((s.session_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["internal_id"] == ledger_mod.internal_session_id(HOST)
    assert manifest["host_session_id"] == HOST


def test_manifest_replacement_recovers_after_a_windows_reader_releases(store, monkeypatch) -> None:
    if ledger_mod.os.name != "nt":
        pytest.skip("Windows file-sharing contract")
    _seed(store, 2)
    target = store.session_path / "manifest.json"
    replace = ledger_mod.os.replace
    with target.open("rb") as reader:

        def replace_then_release(source, destination):
            try:
                replace(source, destination)
            finally:
                reader.close()

        monkeypatch.setattr(ledger_mod.os, "replace", replace_then_release)
        reopened = ledger_mod.LedgerStore(store._home, HOST, host="test")
        try:
            reopened.open(create=True)
            assert [event.event_id for event in reopened.replay(["e-1", "e-2"]).events] == [
                "e-1",
                "e-2",
            ]
        finally:
            reopened.close()


def test_manifest_replacement_preserves_existing_file_on_permanent_error(
    store, monkeypatch
) -> None:
    target = store.session_path / "manifest.json"
    before = target.read_bytes()

    def deny_replace(source, destination):
        error = PermissionError("persistent destination denial")
        error.winerror = 5
        raise error

    monkeypatch.setattr(ledger_mod.os, "replace", deny_replace)
    with pytest.raises(PermissionError, match="persistent destination denial"):
        store._write_manifest()
    assert target.read_bytes() == before
    assert not list(store.session_path.glob("manifest.json.tmp.*"))


def test_internal_id_is_hash_not_raw(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True):
        pass
    raw_path = tmp_path / "state" / "sessions" / HOST
    assert not raw_path.exists()  # never the raw host id as a path
    assert (tmp_path / "state" / "sessions" / ledger_mod.internal_session_id(HOST)).is_dir()


def test_append_contiguity_and_rejects(store) -> None:
    _seed(store, 3)
    with pytest.raises(BrainError, match="contiguity"):
        store.append_events([_ev(5, "x-5", LifecycleEventType.USER_TASK)])  # gap
    with pytest.raises(BrainError, match="contiguity"):
        store.append_events([_ev(3, "x-3", LifecycleEventType.USER_TASK)])  # overlap
    with pytest.raises(BrainError, match="duplicate event_id"):
        store.append_events([_ev(4, "e-1", LifecycleEventType.USER_TASK)])
    with pytest.raises(BrainError, match="invalid parent"):
        store.append_events([_ev(4, "e-4", LifecycleEventType.USER_TASK, parent="ghost")])
    ok = store.append_events([_ev(4, "e-4", LifecycleEventType.USER_TASK, parent="e-3")])
    assert ok == [4]


def test_unknown_required_vs_ignorable_events(store) -> None:
    base = {
        "seq": 1,
        "event_id": "u-1",
        "internal_session_id": ledger_mod.internal_session_id(HOST),
        "agent_id": "a1",
        "parent_event_id": None,
        "event_type": "mystery_event",
        "timestamp": "2026-08-16T01:00:00Z",
        "surface_visibility": SurfaceVisibility.RAW_ONLY,
        "ignorable": False,
        "payload": {},
    }
    with pytest.raises(BrainError):
        BrainLifecycleEvent.from_dict(base)
    assert BrainLifecycleEvent.from_dict({**base, "ignorable": True}) is None


def test_objects_digest_verified(store) -> None:
    digest = store.add_object(b"hello ledger", mime="text/plain", role="artifact")
    assert store.read_object(digest) == b"hello ledger"
    # tamper: direct file write -> digest mismatch fails loud
    path = store.session_path / "objects" / digest
    path.write_bytes(b"tampered")
    with pytest.raises(BrainError, match="digest mismatch"):
        store.read_object(digest)
    # missing file fails loud
    (store.session_path / "objects" / digest).unlink()
    with pytest.raises(BrainError, match="missing"):
        store.read_object(digest)


def test_integrity_and_flush(store) -> None:
    _seed(store, 3)
    assert store.integrity()["seq_contiguous"] is True
    assert store.integrity()["orphan_parents"] == 0
    store.flush()
    assert store.integrity()["event_count"] == 3


def test_fts_search_and_reindex(store) -> None:
    _seed(store, 2)
    store.append_events(
        [
            _ev(
                3,
                "e-3",
                LifecycleEventType.WORKER_REPORT,
                payload={"title": "adaptive fan-out", "summary": "replaces hard cap"},
            )
        ]
    )
    if ledger_mod.LedgerStore.fts_available():
        hits = store.search("adaptive", event_type="worker_report")
        assert len(hits) == 1
        assert hits[0]["event_id"] == "e-3"
        assert hits[0]["payload"]["title"] == "adaptive fan-out"
    # segment/agent filters
    hits = store.search("fan-out", segment="seg-1", agent="a1")
    assert len(hits) == 1
    store.reindex()
    hits = store.search("fan-out")
    assert len(hits) == 1


def test_like_fallback_when_fts_unavailable(store, monkeypatch) -> None:
    _seed(store, 1)
    store.append_events([_ev(2, "e-2", LifecycleEventType.DECISION, payload={"task": "migration"})])
    monkeypatch.setattr(ledger_mod.LedgerStore, "fts_available", staticmethod(lambda: False))
    hits = store.search("migration")
    assert len(hits) == 1 and hits[0]["event_id"] == "e-2"


@pytest.mark.parametrize("create", [False, True])
def test_schema_versioning(tmp_path, create) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True):
        pass
    internal = ledger_mod.internal_session_id(HOST)
    dbfile = tmp_path / "state" / "sessions" / internal / "ledger.sqlite"
    conn = sqlite3.connect(dbfile)
    conn.execute("UPDATE ledger_meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(BrainError, match="unsupported"):
        ledger_mod.LedgerStore(tmp_path, HOST).open(create=create)
    conn = sqlite3.connect(dbfile)
    conn.execute("UPDATE ledger_meta SET value = '0' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(BrainError, match="unsupported"):
        ledger_mod.LedgerStore(tmp_path, HOST).open(create=create)


def _legacy_ledger(home, version="2"):
    with ledger_mod.LedgerStore(home, HOST, host="test").open(create=True) as store:
        _seed(store, 3)
        dbfile = store.dbfile
    with sqlite3.connect(dbfile) as conn:
        conn.execute("ALTER TABLE events DROP COLUMN envelope_hash")
        conn.execute("DELETE FROM ledger_meta WHERE key='envelope_chain_origin'")
        conn.execute("ALTER TABLE events DROP COLUMN prev_hash")
        conn.execute("UPDATE ledger_meta SET value=? WHERE key='schema_version'", (version,))
        conn.execute("UPDATE events SET payload_json=? WHERE seq=2", ('{ "note": "雪 café" }',))
        original = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
    return dbfile, original


@pytest.mark.parametrize("create,version", [(False, "1"), (True, "2")])
def test_legacy_resume_preserves_history_and_labels_derived_chain(tmp_path, create, version):

    dbfile, original = _legacy_ledger(tmp_path, version)
    manifest_path = dbfile.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(schema_version=1, host_artifacts=[{"kind": "transcript", "path": "old"}])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=create) as store:
        integrity = store.integrity()
        assert integrity["hash_chain_ok"] is True
        origin = integrity["hash_chain_origin"]
        assert origin["origin"] == "derived_legacy_backfill"
        assert origin["pre_migration_authenticity_verified"] is False
        assert origin["legacy_through_seq"] == 3
        snapshot = store.read_object(origin["source_snapshot_sha256"])
        assert hashlib.sha256(snapshot).hexdigest() == origin["source_snapshot_sha256"]
        retained = tmp_path / "retained.sqlite"
        retained.write_bytes(snapshot)
        with sqlite3.connect(retained) as before:
            assert before.execute("SELECT * FROM events ORDER BY seq").fetchall() == original
            assert before.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        store.append_events([_ev(0, "stop-proof", LifecycleEventType.STOP_DECIDED)])
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as reopened:
        assert reopened.integrity()["hash_chain_origin"] == origin
        with pytest.raises(BrainError, match="duplicate event_id"):
            reopened.append_events([_ev(0, "stop-proof", LifecycleEventType.STOP_DECIDED)])
    with sqlite3.connect(dbfile) as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        assert [row[:-2] for row in rows[:3]] == original
        assert [(row[0], row[1]) for row in rows[3:]] == [(4, "stop-proof")]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated == {**manifest, "schema_version": 3}


def _v1_chained_ledger(home):
    with ledger_mod.LedgerStore(home, HOST, host="test").open(create=True) as store:
        _seed(store, 3)
        dbfile = store.dbfile
    with sqlite3.connect(dbfile) as conn:
        conn.execute("ALTER TABLE events DROP COLUMN envelope_hash")
        conn.execute("DELETE FROM ledger_meta WHERE key='envelope_chain_origin'")
        running = "0" * 64
        for seq, payload in conn.execute(
            "SELECT seq,payload_json FROM events ORDER BY seq"
        ).fetchall():
            running = hashlib.sha256((running + payload).encode("utf-8")).hexdigest()
            conn.execute("UPDATE events SET prev_hash=? WHERE seq=?", (running, seq))
        conn.execute("UPDATE ledger_meta SET value='1' WHERE key='schema_version'")
        conn.execute("UPDATE events SET prev_hash=NULL WHERE seq=3")
        original = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
    return dbfile, original


def test_v1_chained_resume_preserves_prefix_and_snapshots_unhashed_suffix(tmp_path):
    dbfile, original = _v1_chained_ledger(tmp_path)
    for create in (False, True):
        with ledger_mod.LedgerStore(tmp_path, HOST).open(create=create) as store:
            integrity = store.integrity()
            assert integrity["hash_chain_ok"] is True
            assert integrity["hash_chain_verified_through_seq"] == 3
            origin = integrity["hash_chain_origin"]
            assert origin["preserved_chain_through_seq"] == 2
            assert origin["pre_migration_authenticity_verified"] is False
            snapshot = store.read_object(origin["source_snapshot_sha256"])
    with sqlite3.connect(dbfile) as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        assert [row[:-1] for row in rows[:2]] == original[:2]
        assert [row[:-2] for row in rows] == [row[:-1] for row in original]
        assert rows[2][-2] is not None
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM object_refs WHERE role='legacy-ledger-snapshot'"
            ).fetchone()[0]
            == 1
        )
    restored = tmp_path / "restored.sqlite"
    restored.write_bytes(snapshot)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT * FROM events ORDER BY seq").fetchall() == original
        assert dict(conn.execute("SELECT key,value FROM ledger_meta"))["schema_version"] == "1"


def test_v2_payload_chain_migrates_without_rewriting_old_events(tmp_path, monkeypatch):
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as store:
        _seed(store, 3)
        dbfile = store.dbfile
    with sqlite3.connect(dbfile) as conn:
        conn.execute("ALTER TABLE events DROP COLUMN envelope_hash")
        conn.execute("DELETE FROM ledger_meta WHERE key='envelope_chain_origin'")
        running = "0" * 64
        for seq, payload in conn.execute(
            "SELECT seq,payload_json FROM events ORDER BY seq"
        ).fetchall():
            running = hashlib.sha256((running + payload).encode("utf-8")).hexdigest()
            conn.execute("UPDATE events SET prev_hash=? WHERE seq=?", (running, seq))
        conn.execute("UPDATE ledger_meta SET value='2' WHERE key='schema_version'")
        original = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
    migrate = ledger_mod.LedgerStore._migrate_envelope_chain

    def interrupted(store, **kwargs):
        migrate(store, **kwargs)
        raise KeyboardInterrupt("before v3 commit")

    with monkeypatch.context() as patch:
        patch.setattr(ledger_mod.LedgerStore, "_migrate_envelope_chain", interrupted)
        with pytest.raises(KeyboardInterrupt):
            ledger_mod.LedgerStore(tmp_path, HOST).open()
    with sqlite3.connect(dbfile) as conn:
        assert conn.execute("SELECT * FROM events ORDER BY seq").fetchall() == original
        assert dict(conn.execute("SELECT key,value FROM ledger_meta"))["schema_version"] == "2"
        assert conn.execute(
            "SELECT value FROM ledger_meta WHERE key='envelope_chain_origin'"
        ).fetchone() is None
    with ledger_mod.LedgerStore(tmp_path, HOST).open() as store:
        origin = store.integrity()["envelope_chain_origin"]
        assert origin["origin"] == "derived_predecessor"
        assert origin["legacy_schema_version"] == 2
        assert origin["pre_migration_authenticity_verified"] is False
        snapshot = store.read_object(origin["source_snapshot_sha256"])
        backup = tmp_path / "v2-snapshot.sqlite"
        backup.write_bytes(snapshot)
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT * FROM events ORDER BY seq").fetchall() == original
        store.append_events([_ev(0, "v3-event", LifecycleEventType.FINDING)])
        assert store.integrity()["hash_chain_ok"] is True
    with sqlite3.connect(dbfile) as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        assert [row[:-1] for row in rows[:3]] == original
        assert rows[3][-2] is None
    with ledger_mod.LedgerStore(tmp_path, HOST).open() as store:
        assert store.integrity()["envelope_chain_origin"] == origin
        assert store.integrity()["hash_chain_verified_through_seq"] == 4


@pytest.mark.parametrize("damage", ["prefix", "hole", "watermark"])
def test_v1_chained_resume_refuses_unproven_history(tmp_path, damage):
    dbfile, _ = _v1_chained_ledger(tmp_path)
    with sqlite3.connect(dbfile) as conn:
        if damage == "prefix":
            conn.execute("""UPDATE events SET payload_json='{"tampered":true}' WHERE seq=1""")
        elif damage == "hole":
            conn.execute("UPDATE events SET prev_hash=NULL WHERE seq=1")
        else:
            conn.execute("INSERT INTO ledger_meta VALUES ('last_verified_seq','3')")
        original = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
    with pytest.raises(BrainError):
        ledger_mod.LedgerStore(tmp_path, HOST).open()
    with sqlite3.connect(dbfile) as conn:
        assert conn.execute("SELECT * FROM events ORDER BY seq").fetchall() == original
        assert dict(conn.execute("SELECT key,value FROM ledger_meta"))["schema_version"] == "1"


def test_legacy_migration_interruption_rolls_back_then_retries(tmp_path, monkeypatch):
    dbfile, original = _legacy_ledger(tmp_path, "1")
    migrate = ledger_mod.LedgerStore._migrate_legacy_chain

    def interrupted(store):
        migrate(store)
        raise KeyboardInterrupt("interrupted before commit")

    with monkeypatch.context() as patch:
        patch.setattr(ledger_mod.LedgerStore, "_migrate_legacy_chain", interrupted)
        with pytest.raises(KeyboardInterrupt):
            ledger_mod.LedgerStore(tmp_path, HOST).open(create=True)
    with sqlite3.connect(dbfile) as conn:
        assert conn.execute("SELECT * FROM events ORDER BY seq").fetchall() == original
        assert dict(conn.execute("SELECT key,value FROM ledger_meta"))["schema_version"] == "1"
        assert (
            conn.execute("SELECT value FROM ledger_meta WHERE key='hash_chain_origin'").fetchone()
            is None
        )
    with ledger_mod.LedgerStore(tmp_path, HOST).open() as store:
        assert store.integrity()["hash_chain_verified_through_seq"] == 3


def test_legacy_concurrent_open_and_manifest_recovery(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    dbfile, original = _legacy_ledger(tmp_path)
    manifest_path = dbfile.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def denied(*args):
        raise PermissionError("manifest temporarily locked")

    with monkeypatch.context() as patch:
        patch.setattr(ledger_mod.LedgerStore, "_write_manifest", denied)
        with pytest.raises(PermissionError):
            ledger_mod.LedgerStore(tmp_path, HOST).open()

    def reopen(create):
        with ledger_mod.LedgerStore(tmp_path, HOST).open(create=create) as store:
            return store.header()["hash_chain_origin"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        origins = list(pool.map(reopen, [False, True]))
    assert origins[0] == origins[1]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["schema_version"] == 3
    with sqlite3.connect(dbfile) as conn:
        assert [row[:-2] for row in conn.execute("SELECT * FROM events ORDER BY seq")] == original


def test_partial_chain_is_refused_without_overwriting_integrity(tmp_path):
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as store:
        _seed(store, 3)
        dbfile = store.dbfile
    with sqlite3.connect(dbfile) as conn:
        conn.execute("UPDATE events SET envelope_hash=NULL WHERE seq=2")
        original = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
    for create in (False, True):
        with pytest.raises(BrainError, match="envelope hash chain is missing or malformed"):
            ledger_mod.LedgerStore(tmp_path, HOST).open(create=create)
    with sqlite3.connect(dbfile) as conn:
        assert conn.execute("SELECT * FROM events ORDER BY seq").fetchall() == original


def test_legacy_concurrent_migration_commits_one_origin(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    dbfile, original = _legacy_ledger(tmp_path)
    barrier = Barrier(2)

    def open_legacy(create):
        barrier.wait(timeout=5)
        with ledger_mod.LedgerStore(tmp_path, HOST).open(create=create) as store:
            return store.header()["hash_chain_origin"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        origins = list(pool.map(open_legacy, [False, True]))
    assert origins[0] == origins[1]
    with sqlite3.connect(dbfile) as conn:
        assert [row[:-2] for row in conn.execute("SELECT * FROM events ORDER BY seq")] == original
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM object_refs WHERE role='legacy-ledger-snapshot'"
            ).fetchone()[0]
            == 1
        )


def test_replay_projection_and_compare(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _seed(s, 3)
        proj = s.replay(["e-1", "e-2", "e-3"])
        assert [e.event_id for e in proj.events] == ["e-1", "e-2", "e-3"]
    # independent fresh replay
    replayed = ledger_mod.replay_session(tmp_path, HOST, ["e-1", "e-2", "e-3"])
    assert [e.event_id for e in replayed.events] == ["e-1", "e-2", "e-3"]
    assert ledger_mod.compare_projection(proj, replayed) is None


def test_replay_rejects_seq_gap(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _seed(s, 3)
        conn = sqlite3.connect(s.dbfile)
        conn.execute("DELETE FROM events WHERE seq = 2")
        conn.commit()
        conn.close()
        with pytest.raises(BrainError, match="seq not contiguous"):
            s.replay(["e-1", "e-3"])


def test_replay_rejects_orphan_parent(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _seed(s, 2)
        conn = sqlite3.connect(s.dbfile)
        conn.execute("UPDATE events SET parent_event_id = 'ghost' WHERE seq = 2")
        conn.commit()
        conn.close()
        with pytest.raises(BrainError, match="orphan"):
            s.replay(["e-1", "e-2"])


def test_replay_rejects_broken_lineage_pointer(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _seed(s, 3)
        with pytest.raises(BrainError, match="lineage event missing"):
            s.replay(["e-1", "ghost"])


def test_replay_rejects_a_tampered_checkpointed_event(tmp_path, capsys) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as store:
        _seed(store, 3)
        assert store.integrity()["hash_chain_verified_through_seq"] == 3
        conn = sqlite3.connect(store.dbfile)
        try:
            row = conn.execute("SELECT payload_json FROM events WHERE seq = 2").fetchone()
            payload = json.loads(row[0])
            payload["task"] = "tampered"
            conn.execute("UPDATE events SET payload_json = ? WHERE seq = 2", (json.dumps(payload),))
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(BrainError, match="hash chain"):
            store.replay(["e-1", "e-2", "e-3"])
        from second_brain import cli

        status = cli.main(
            ["--home", str(tmp_path), "ledger", "verify", HOST, "--lineage", "e-1,e-2,e-3"]
        )
        report = json.loads(capsys.readouterr().out)
        assert status == 1
        assert report["integrity"]["hash_chain_ok"] is False
        assert report["replay_ok"] is False


def test_replay_rejects_missing_object(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _seed(s, 1)
        digest = s.add_object(b"payload bytes")
        (s.session_path / "objects" / digest).unlink()
        with pytest.raises(BrainError, match="object digest failures"):
            s.replay(["e-1"])


def test_classify_tool_outcome() -> None:
    events = [
        _ev(1, "t1-req", LifecycleEventType.TOOL_REQUESTED, payload={"tool_call_id": "t1"}),
        _ev(2, "t2-req", LifecycleEventType.TOOL_REQUESTED, payload={"tool_call_id": "t2"}),
        _ev(3, "t2-sta", LifecycleEventType.TOOL_STARTED, payload={"tool_call_id": "t2"}),
        _ev(4, "t3-req", LifecycleEventType.TOOL_REQUESTED, payload={"tool_call_id": "t3"}),
        _ev(5, "t3-sta", LifecycleEventType.TOOL_STARTED, payload={"tool_call_id": "t3"}),
        _ev(6, "t3-done", LifecycleEventType.TOOL_COMPLETED, payload={"tool_call_id": "t3"}),
    ]
    out = ledger_mod.classify_tool_outcome(events)
    assert out["t1"]["state"] == ToolOutcome.TOOL_NOT_STARTED.value
    assert "no durable start" in out["t1"]["guidance"]
    assert out["t2"]["state"] == ToolOutcome.TOOL_OUTCOME_UNKNOWN.value
    assert "Verify external state first" in out["t2"]["guidance"]
    assert out["t3"]["state"] == ToolOutcome.COMPLETE.value
    assert out["t3"]["guidance"] == ""


def test_cli_ledger_flow(tmp_path) -> None:
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    home = tmp_path / "brain"
    home.mkdir()

    def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "second_brain", "--home", str(home), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=home,
            input=stdin,
            timeout=120,
        )

    assert run("init").returncode == 0
    r = run("ledger", "init", "--session", HOST)
    assert r.returncode == 0, r.stderr
    internal = json.loads(r.stdout)["initialized"]
    assert (home / "state" / "sessions" / internal / "ledger.sqlite").is_file()

    event = {
        "seq": 1,
        "event_id": "e-1",
        "internal_session_id": internal,
        "agent_id": "a1",
        "parent_event_id": None,
        "event_type": "user_task",
        "timestamp": "2026-08-16T01:00:00Z",
        "surface_visibility": "raw_only",
        "ignorable": False,
        "payload": {"task": "migration ordering"},
    }
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(event))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["appended"] == [1]

    # unknown REQUIRED event -> error, exit 2 (per spec)
    bad = dict(event, seq=2, event_id="e-2", event_type="mystery_event")
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(bad))
    assert r.returncode == 2
    assert "mystery_event" in r.stderr

    # unknown ignorable -> skipped, no error
    skip = dict(event, seq=2, event_id="e-2", event_type="mystery_event", ignorable=True)
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(skip))
    assert r.returncode == 0
    assert json.loads(r.stdout)["appended"] == []

    r = run("ledger", "verify", HOST)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["integrity"]["seq_contiguous"] is True
    assert out["replay_ok"] is True

    r = run("ledger", "search", HOST, "--query", "migration")
    assert r.returncode == 0
    assert len(json.loads(r.stdout)["hits"]) == 1

    r = run("ledger", "reindex", HOST)
    assert r.returncode == 0
    assert json.loads(r.stdout)["indexed"] == 1


def test_cli_ledger_init_project_attribution(tmp_path) -> None:
    """Project attribution regression: ``ledger init --cwd`` resolves
    project_id through the SAME ladder AutoInject uses (registry root
    containing the cwd); explicit ``--project`` wins; no ``--cwd``/``--project``
    keeps the historical '' (empty session-ledger project_id gap)."""
    import os
    import subprocess
    import sys

    from second_brain import registry

    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    home = tmp_path / "brain"
    home.mkdir()

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "second_brain", "--home", str(home), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=home,
            timeout=120,
        )

    assert run("init").returncode == 0
    proj_dir = tmp_path / "proj-x"
    proj_dir.mkdir()
    registry.add_project(home, proj_dir, name="Proj X", project_id="proj-x")

    def project_id(host: str) -> str | None:
        internal = ledger_mod.internal_session_id(host)
        conn = sqlite3.connect(home / "state" / "sessions" / internal / "ledger.sqlite")
        try:
            row = conn.execute("SELECT project_id FROM sessions").fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    # --cwd inside the registered project root -> resolved via the ladder
    r = run("ledger", "init", "--session", "host-cwd", "--cwd", str(proj_dir))
    assert r.returncode == 0, r.stderr
    assert project_id("host-cwd") == "proj-x"

    # explicit --project still wins over --cwd resolution
    r = run(
        "ledger",
        "init",
        "--session",
        "host-exp",
        "--project",
        "explicit-proj",
        "--cwd",
        str(proj_dir),
    )
    assert r.returncode == 0, r.stderr
    assert project_id("host-exp") == "explicit-proj"

    # no --cwd / no --project -> '' unchanged
    r = run("ledger", "init", "--session", "host-none")
    assert r.returncode == 0, r.stderr
    assert project_id("host-none") == ""


def _cli_env(tmp_path):
    """Shared CLI harness: env-clean brainctl against a tmp home."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    home = tmp_path / "brain"
    home.mkdir()

    def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "second_brain", "--home", str(home), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=home,
            input=stdin,
            timeout=120,
        )

    return home, run


def test_cli_ledger_init_persists_canonical_ancestry_and_resume(tmp_path) -> None:
    home, run = _cli_env(tmp_path)

    def dbfile(host: str):
        return home / "state" / "sessions" / ledger_mod.internal_session_id(host) / "ledger.sqlite"

    def identity(host: str) -> tuple:
        conn = sqlite3.connect(dbfile(host))
        try:
            row = conn.execute(
                "SELECT host, host_session_id, project_id, created_at, status, "
                "pinned, schema_version, current_segment_id, root_parent_session_id "
                "FROM sessions WHERE internal_session_id = ?",
                (ledger_mod.internal_session_id(host),),
            ).fetchone()
            assert row is not None
            return row
        finally:
            conn.close()

    root_a = "root-a"
    child_b = "child-b"
    grandchild_c = "grandchild-c"
    root_d = "root-d"
    root_a_internal = ledger_mod.internal_session_id(root_a)

    assert run("ledger", "init", "--session", root_a).returncode == 0
    child = run(
        "ledger",
        "init",
        "--session",
        child_b,
        "--parent-session",
        root_a,
        "--project",
        "project-original",
    )
    assert child.returncode == 0, child.stderr
    original_child_identity = identity(child_b)
    assert original_child_identity[-1] == root_a_internal

    parent_bytes = dbfile(child_b).read_bytes()
    grandchild = run(
        "ledger",
        "init",
        "--session",
        grandchild_c,
        "--parent-session",
        child_b,
    )
    assert grandchild.returncode == 0, grandchild.stderr
    assert identity(grandchild_c)[-1] == root_a_internal
    assert dbfile(child_b).read_bytes() == parent_bytes

    cycle = run("ledger", "init", "--session", root_a, "--parent-session", grandchild_c)
    assert cycle.returncode == 2
    assert "cannot resolve to the child session itself" in cycle.stderr
    assert identity(root_a)[-1] is None

    resumed = run("ledger", "init", "--session", child_b)
    assert resumed.returncode == 0, resumed.stderr
    assert identity(child_b) == original_child_identity
    repeated = run("ledger", "init", "--session", child_b, "--parent-session", root_a)
    assert repeated.returncode == 0, repeated.stderr
    assert identity(child_b) == original_child_identity

    assert run("ledger", "init", "--session", root_d).returncode == 0
    conflict = run("ledger", "init", "--session", child_b, "--parent-session", root_d)
    assert conflict.returncode == 2
    assert "conflicting root parent" in conflict.stderr
    assert identity(child_b) == original_child_identity


def test_cli_ledger_parent_resolution_rejects_unowned_parent_without_writes(
    tmp_path,
) -> None:
    home, run = _cli_env(tmp_path)
    parent = "claimed-parent"
    child = "unattributed-child"
    missing = run("ledger", "init", "--session", child, "--parent-session", "missing-parent")
    assert missing.returncode == 2
    assert "parent ledger not initialized" in missing.stderr
    assert not (
        home / "state" / "sessions" / ledger_mod.internal_session_id(child) / "ledger.sqlite"
    ).exists()
    assert run("ledger", "init", "--session", parent).returncode == 0
    parent_db = (
        home / "state" / "sessions" / ledger_mod.internal_session_id(parent) / "ledger.sqlite"
    )
    conn = sqlite3.connect(parent_db)
    try:
        conn.execute(
            "UPDATE sessions SET host_session_id = 'different-owner' WHERE internal_session_id = ?",
            (ledger_mod.internal_session_id(parent),),
        )
        conn.commit()
    finally:
        conn.close()
    parent_bytes = parent_db.read_bytes()

    result = run("ledger", "init", "--session", child, "--parent-session", parent)
    assert result.returncode == 2
    assert "not owned by host session" in result.stderr
    assert parent_db.read_bytes() == parent_bytes
    assert not (
        home / "state" / "sessions" / ledger_mod.internal_session_id(child) / "ledger.sqlite"
    ).exists()


def _mirror_event(eid: str, event_type: str, **payload) -> dict:
    """One event exactly as the Prime extension mirror sends it: no seq
    (ledger auto-assigns), no internal_session_id (CLI derives it)."""
    return {
        "event_id": eid,
        "agent_id": "a1",
        "parent_event_id": None,
        "event_type": event_type,
        "timestamp": "2026-08-16T01:00:00Z",
        "surface_visibility": "raw_only",
        "ignorable": False,
        "payload": payload,
    }


def test_cli_append_accepts_live_prime_events(tmp_path) -> None:
    """Live host sequence (turn_end / agent_ended) is accepted by ledger
    append and persists contiguously (regression: 'unknown required event
    type: turn_end/agent_ended')."""
    _home, run = _cli_env(tmp_path)
    assert run("ledger", "init", "--session", HOST).returncode == 0
    batch = [
        _mirror_event(
            "live-1", "session_started", agent_id="a1", model="deepseek/deepseek-v4-flash"
        ),
        _mirror_event("live-2", "user_task", task_sha256="abc123"),
        _mirror_event("live-3", "tool_requested", tool="bash", tool_call_id="t1"),
        _mirror_event("live-4", "tool_completed", tool="bash", tool_call_id="t1", output_bytes=42),
        _mirror_event("live-5", "turn_end", turn_index=0, tool_result_count=1),
        _mirror_event("live-6", "agent_ended", message_count=1),
    ]
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(batch))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["appended"] == [1, 2, 3, 4, 5, 6]
    r = run("ledger", "verify", HOST)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["integrity"]["seq_contiguous"] is True
    assert out["replay_ok"] is True


def test_cli_rejected_append_then_retry_stays_contiguous(tmp_path) -> None:
    """A rejected event (unknown non-ignorable) fails the append without
    advancing sequence state; the next append still lands contiguous."""
    _home, run = _cli_env(tmp_path)
    assert run("ledger", "init", "--session", HOST).returncode == 0
    ok = _mirror_event("ok-1", "user_task", task_sha256="abc")
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(ok))
    assert r.returncode == 0
    assert json.loads(r.stdout)["appended"] == [1]

    bad = _mirror_event("bad-1", "mystery_event")
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(bad))
    assert r.returncode == 2
    assert "mystery_event" in r.stderr

    # retry with the real event type: still contiguous, no gap from the failure
    retry = _mirror_event("ok-2", "turn_end", turn_index=0)
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(retry))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["appended"] == [2]
    out = json.loads(run("ledger", "verify", HOST).stdout)
    assert out["integrity"]["seq_contiguous"] is True


def test_cli_batch_with_ignorable_skip_stays_contiguous(tmp_path) -> None:
    """Skipped unknown-ignorable events must not consume seq slots: the
    surviving events get contiguous auto-assigned seqs (regression for the
    CLI seq-counter gap that poisoned later mirror writes)."""
    _home, run = _cli_env(tmp_path)
    assert run("ledger", "init", "--session", HOST).returncode == 0
    batch = [
        _mirror_event("m-1", "user_task", task_sha256="a"),
        dict(
            _mirror_event("m-2", "host_artifact_ref", kind="transcript", path="x.jsonl"),
            ignorable=True,
        ),
        _mirror_event("m-3", "turn_end", turn_index=0),
    ]
    r = run("ledger", "append", "--session", HOST, "--stdin-json", stdin=json.dumps(batch))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["appended"] == [1, 2]  # no slot for the skip
    out = json.loads(run("ledger", "verify", HOST).stdout)
    assert out["integrity"]["seq_contiguous"] is True
    assert out["integrity"]["event_count"] == 2


def test_cli_concurrent_appends_all_contiguous(tmp_path) -> None:
    """Concurrent mirror appends (one process per event, as the extension
    fires them) all land contiguous: seq assignment happens inside the
    append transaction (regression for 'seq contiguity violated: batch
    starts at N but ledger expects N+1' races)."""
    import concurrent.futures

    _home, run = _cli_env(tmp_path)
    assert run("ledger", "init", "--session", HOST).returncode == 0

    def append(i: int):
        return run(
            "ledger",
            "append",
            "--session",
            HOST,
            "--stdin-json",
            stdin=json.dumps(_mirror_event(f"race-{i}", "user_task", task_sha256=str(i))),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(append, range(8)))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results if r.returncode != 0]
    appended = sorted(s for r in results for s in json.loads(r.stdout)["appended"])
    assert appended == list(range(1, 9))
    out = json.loads(run("ledger", "verify", HOST).stdout)
    assert out["integrity"]["seq_contiguous"] is True
    assert out["integrity"]["event_count"] == 8


def test_cli_concurrent_init_and_append_burst(tmp_path) -> None:
    """P3-E fix regression (plan §24.8: zero recurrence of ledger error
    classes): a BURST of concurrent init+append chains on a BRAND-NEW session
    ledger (one process per event, exactly how the extension mirrors events
    at child-session spawn / task-arrival moments) must ALL succeed. Covers
    the first-init race the 8-way append test cannot: busy_timeout before any
    statement, bounded journal_mode=WAL retry, unique manifest temp names,
    and the resolve retry keep it self-healing; seq stays contiguous and the
    durable ledger remains the sequence authority."""
    import concurrent.futures
    import time as _time

    _home, run = _cli_env(tmp_path)
    host = f"burst-{_time.time_ns()}"

    def init_and_append(i: int):
        init = run("ledger", "init", "--session", host, "--host", "prime")
        if init.returncode != 0:
            return init
        return run(
            "ledger",
            "append",
            "--session",
            host,
            "--stdin-json",
            stdin=json.dumps(_mirror_event(f"burst-{i}", "user_task", task_sha256=str(i))),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(init_and_append, range(8)))
    bad = [r for r in results if r.returncode != 0]
    assert not bad, [r.stderr for r in bad]
    appended = sorted(s for r in results for s in json.loads(r.stdout)["appended"])
    assert appended == list(range(1, 9))
    out = json.loads(run("ledger", "verify", host).stdout)
    assert out["integrity"]["seq_contiguous"] is True
    assert out["integrity"]["event_count"] == 8


def test_host_artifact_manifest_roundtrip(tmp_path) -> None:
    """T-G2: ledger init --host-artifact KIND=PATH records Prime-owned artifact
    REFERENCES in manifest.json (never copies content)."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    home = tmp_path / "brain"
    home.mkdir()
    subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), "init"],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        timeout=120,
        check=True,
    )
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "second_brain",
            "--home",
            str(home),
            "ledger",
            "init",
            "--session",
            HOST,
            "--host-artifact",
            "transcript=C:/sessions/host-1.jsonl",
            "--host-artifact",
            "telemetry=C:/brain/telemetry/agent-performance/host-1.jsonl",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    internal = ledger_mod.internal_session_id(HOST)
    manifest = json.loads(
        (home / "state" / "sessions" / internal / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["host_artifacts"] == [
        {"kind": "transcript", "path": "C:/sessions/host-1.jsonl"},
        {"kind": "telemetry", "path": "C:/brain/telemetry/agent-performance/host-1.jsonl"},
    ]
    # malformed artifact spec -> usage error
    r2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "second_brain",
            "--home",
            str(home),
            "ledger",
            "init",
            "--session",
            "other-session",
            "--host-artifact",
            "noseparator",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        timeout=120,
    )
    assert r2.returncode == 2


def test_inline_agent_registration(store) -> None:
    """T-G2: session_started agent payload fields register the agent inline."""
    store.register_agent(
        {
            "agent_id": "deepseek/deepseek-v4-flash",
            "internal_session_id": ledger_mod.internal_session_id(HOST),
            "host_agent_id": "deepseek/deepseek-v4-flash",
            "parent_agent_id": None,
            "role_profile": "worker",
            "model": "deepseek-v4-flash",
            "provider": "deepseek",
            "created_at": "2026-08-16T01:00:00Z",
        }
    )
    row = store._conn.execute(
        "SELECT role_profile, model FROM agents WHERE agent_id = ?",
        ("deepseek/deepseek-v4-flash",),
    ).fetchone()
    assert row["role_profile"] == "worker"
    assert row["model"] == "deepseek-v4-flash"


# ---------------------------------------------------------------------------
# T-G4: segments, checkpoint barrier, continuation capsule, rehydration
# ---------------------------------------------------------------------------


def test_segment_lifecycle(store) -> None:
    _seed(store, 2)
    seg1 = store.open_segment("startup")
    assert seg1 == "seg-1"
    # open_segment advanced start_seq to 3; append seqs 3-4 explicitly
    store.append_events(
        [
            _ev(3, "f-1", LifecycleEventType.USER_TASK, parent="e-2"),
            _ev(4, "f-2", LifecycleEventType.USER_TASK, parent="f-1"),
        ]
    )
    seg2 = store.open_segment("compact")
    assert seg2 == "seg-2"
    rows = store._conn.execute(
        "SELECT segment_id, start_seq, end_seq, active FROM segments ORDER BY idx"
    ).fetchall()
    assert [dict(r) for r in rows] == [
        {"segment_id": "seg-1", "start_seq": 3, "end_seq": 4, "active": 0},
        {"segment_id": "seg-2", "start_seq": 5, "end_seq": None, "active": 1},
    ]
    closed = store.close_segment()
    assert closed["segment_id"] == "seg-2"
    assert closed["end_seq"] == 4
    assert store.close_segment() is None  # nothing active


def test_checkpoint_ok_and_failure_flag(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _seed(s, 3)
        result = ledger_mod.checkpoint_ledger(s)
        assert result["ok"] is True
        assert result["durability"] == "flushed"
        assert result["integrity"]["seq_contiguous"] is True
        # inject a seq gap -> checkpoint reports failure, never raises
        conn = sqlite3.connect(s.dbfile)
        conn.execute("DELETE FROM events WHERE seq = 2")
        conn.commit()
        conn.close()
        bad = ledger_mod.checkpoint_ledger(s)
        assert bad["ok"] is False
        assert bad["integrity"]["seq_contiguous"] is False


# ---------------------------------------------------------------------------
# Hash chain (T6.3)
# ---------------------------------------------------------------------------


def test_hash_chain_verified_on_append(store) -> None:
    _seed(store, 3)
    result = store.integrity()
    assert result["hash_chain_ok"] is True
    assert result["hash_chain_verified_through_seq"] == 3
    assert result["hash_chain_break_seq"] is None


def test_append_hashes_the_values_sqlite_actually_stores(store) -> None:
    event = BrainLifecycleEvent.from_dict(
        {**vars(_ev(1, "typed", LifecycleEventType.FINDING)), "timestamp": 1790000000}
    )
    assert event is not None
    store.append_events([event])
    assert store.integrity()["hash_chain_ok"] is True
    assert store.replay(["typed"]).events[0].timestamp == "1790000000"


def test_hash_chain_detects_in_place_edit(store) -> None:
    # checkpoint through seq 2, then append seq 3 UNVERIFIED by that checkpoint
    _seed(store, 2)
    first = store.integrity()
    assert first["hash_chain_ok"] is True
    assert first["hash_chain_verified_through_seq"] == 2
    store.append_events([_ev(3, "e-3", LifecycleEventType.USER_TASK, parent="e-2")])

    # in-place edit (matching test_replay_detects_payload_tamper_via_compare's
    # tamper style): direct sqlite3 UPDATE of a row's payload_json
    conn = sqlite3.connect(store.dbfile)
    row = conn.execute("SELECT payload_json FROM events WHERE seq = 3").fetchone()
    payload = json.loads(row[0])
    payload["tampered"] = True
    conn.execute("UPDATE events SET payload_json = ? WHERE seq = 3", (json.dumps(payload),))
    conn.commit()
    conn.close()

    second = store.integrity()
    assert second["hash_chain_ok"] is False
    assert second["hash_chain_break_seq"] == 3


def test_integrity_rechecks_checkpointed_history_and_ignores_forged_watermark(store) -> None:
    _seed(store, 3)
    assert store.integrity()["hash_chain_ok"] is True
    with sqlite3.connect(store.dbfile) as conn:
        conn.execute("UPDATE events SET payload_json=? WHERE seq=2", ('{"tampered":true}',))
        conn.execute(
            "INSERT OR REPLACE INTO ledger_meta (key,value) VALUES ('last_verified_seq','999')"
        )
    result = store.integrity()
    assert result["hash_chain_ok"] is False
    assert result["hash_chain_break_seq"] == 2
    assert ledger_mod.checkpoint_ledger(store)["ok"] is False

def test_envelope_metadata_tamper_refuses_replay_and_checkpoint(store) -> None:
    _seed(store, 3)
    assert store.integrity()["hash_chain_ok"] is True
    with sqlite3.connect(store.dbfile) as conn:
        conn.execute(
            "UPDATE events SET timestamp='2026-09-22T00:00:00Z' WHERE seq=2"
        )
    result = store.integrity()
    assert result["hash_chain_ok"] is False
    assert result["hash_chain_break_seq"] == 2
    assert ledger_mod.checkpoint_ledger(store)["ok"] is False
    with pytest.raises(BrainError, match="hash chain"):
        store.replay(["e-1", "e-2", "e-3"])


def test_migrated_chain_detects_legacy_origin_rewrite(tmp_path) -> None:
    dbfile, _ = _legacy_ledger(tmp_path, "1")
    with ledger_mod.LedgerStore(tmp_path, HOST).open() as store:
        assert store.integrity()["hash_chain_ok"] is True
        with sqlite3.connect(dbfile) as conn:
            origin = json.loads(conn.execute(
                "SELECT value FROM ledger_meta WHERE key='hash_chain_origin'"
            ).fetchone()[0])
            origin["preserved_chain_through_seq"] = 999
            conn.execute(
                "UPDATE ledger_meta SET value=? WHERE key='hash_chain_origin'",
                (json.dumps(origin),),
            )
        with pytest.raises(BrainError, match="legacy origin"):
            store.integrity()


def test_purge_removes_artifact_refs_before_rmtree(tmp_path) -> None:
    from second_brain import artifacts
    from second_brain import db as db_mod

    internal = ledger_mod.internal_session_id(HOST)
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _create(s, project="proj-a")
        s.append_events(
            [
                _ev(1, "task", LifecycleEventType.USER_TASK, payload={"task_sha256": "abc"}),
                _ev(
                    2,
                    "dec",
                    LifecycleEventType.DECISION,
                    payload={"decision": "use X", "rationale": "because Y"},
                ),
            ]
        )
    info = artifacts.store_text(tmp_path, "session-scoped payload", "handoff_payload", session=HOST)
    artifacts.add_ref(tmp_path, info["hash"], owner=f"handoff:{internal}")
    artifacts.add_ref(tmp_path, info["hash"], owner=f"vmem:{internal}")
    other = artifacts.store_text(tmp_path, "other session payload", "generic")
    artifacts.add_ref(tmp_path, other["hash"], owner="vmem:other-internal-id")

    life = ledger_mod.SessionLifecycle(tmp_path, HOST)
    life.mark_status("inactive_grace")
    retention = ledger_mod.load_retention_config(tmp_path)
    life.purge(inactive=True, retention=retention)

    conn = db_mod.connect(db_mod.db_path(tmp_path), readonly=True)
    remaining = conn.execute(
        "SELECT owner FROM artifact_refs WHERE owner LIKE ?", (f"%:{internal}",)
    ).fetchall()
    assert remaining == []
    survivor = conn.execute(
        "SELECT owner FROM artifact_refs WHERE owner = 'vmem:other-internal-id'"
    ).fetchall()
    assert len(survivor) == 1
    conn.close()


def test_continuation_capsule_from_events(store) -> None:
    store.append_events(
        [
            _ev(1, "start", LifecycleEventType.SESSION_STARTED, payload={"agent_id": "a1"}),
            _ev(
                2,
                "task",
                LifecycleEventType.USER_TASK,
                payload={"task_sha256": "abc", "prompt_chars": 3},
            ),
            _ev(
                3,
                "dec",
                LifecycleEventType.DECISION,
                payload={"decision": "use X", "rationale": "because Y"},
            ),
            _ev(
                4,
                "rep",
                LifecycleEventType.WORKER_REPORT,
                payload={"worker": "w1", "summary": "done"},
            ),
        ]
    )
    capsule = store.continuation_capsule()
    assert capsule["current_task"]["task_sha256"] == "abc"
    assert any(d["decision"] == "use X" for d in capsule["decisions"])
    assert capsule["worker_status"]["w1"]["summary"] == "done"
    assert capsule["pointers"]["artifact_count"] == 0


def test_rehydrate_levels_and_dedupe(store) -> None:
    store.open_segment("startup")
    # The artifact is bound when the event is appended, exactly as the tool flow
    # does. The envelope digest covers artifact_sha256, so a post-append rewrite
    # would leave a ledger that no longer verifies.
    digest = store.add_object(b"exact artifact bytes", mime="text/plain", role="artifact")
    store.append_events(
        [
            _ev(1, "task", LifecycleEventType.USER_TASK, payload={"task_sha256": "abc"}),
            _ev(
                2,
                "dec",
                LifecycleEventType.DECISION,
                payload={"decision": "use X", "rationale": "because Y"},
                parent="task",
                artifact_sha256=digest,
            ),
        ]
    )
    store.open_segment("compact")

    rh = ledger_mod.LedgerRehydrator(store)
    l1 = rh.rehydrate(1)
    assert l1["level"] == 1
    assert l1["pointer"]["segments"][0]["segment_id"] == "seg-1"
    assert l1["pointer"]["event_range"] == {"from": 1, "to": 2}

    l2 = rh.rehydrate(2)
    assert l2["level"] == 2
    assert l2["evidence_packets"][0]["decision"] == "use X"
    assert l2["evidence_packets"][0]["rationale"] == "because Y"

    l3 = rh.rehydrate(3, from_seq=1, to_seq=2)
    assert l3["level"] == 3
    payloads = {e["event_id"]: e["payload"] for e in l3["events"]}
    assert payloads["dec"] == {"decision": "use X", "rationale": "because Y"}
    assert l3["artifacts"][0]["digest_verified"] is True
    assert l3["artifacts"][0]["excerpt"] == "exact artifact bytes"

    l4 = rh.rehydrate(4)
    assert l4["level"] == 4
    assert len(l4["segments"]) == 2
    assert len(l4["events"]) == 2

    # stable rehydration_id + dedupe: same level+content -> deduplicated
    stable = {k: v for k, v in l1.items() if k != "rehydration_id"}
    assert l1["rehydration_id"] == ledger_mod._rehydration_id(stable)
    again = rh.rehydrate(1)
    assert again["deduplicated"] is True
    assert again["rehydration_id"] == l1["rehydration_id"]
    # a different range is NOT deduplicated (returns full content, no flag)
    different = rh.rehydrate(3, from_seq=1, to_seq=1)
    assert different.get("deduplicated") is None
    assert [e["event_id"] for e in different["events"]] == ["task"]


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T-G5: crash recovery, retention, finalization, purge
# ---------------------------------------------------------------------------


def _identity(
    host: str, *, status: str = "active", pinned: bool = False, project: str = ""
) -> BrainSessionIdentity:
    return BrainSessionIdentity(
        internal_session_id=ledger_mod.internal_session_id(host),
        host="prime",
        host_session_id=host,
        project_id=project,
        created_at="2026-08-16T01:00:00Z",
        status=status,
        pinned=pinned,
        schema_version=1,
    )


def _create(store, host: str = HOST, **kw) -> None:
    store.create_session(_identity(host, **kw))


def test_status_transitions(store) -> None:
    _create(store)
    life = ledger_mod.SessionLifecycle(store._home, HOST)
    assert life.status() == "active"
    life.mark_status("inactive_grace")
    assert life.status() == "inactive_grace"
    life.mark_status("finalizing")
    life.mark_status("extracted")
    with pytest.raises(ledger_mod.SessionLifecycleError, match="invalid transition"):
        life.mark_status("active")  # extracted cannot go back
    life.mark_status("purged")
    with pytest.raises(ledger_mod.SessionLifecycleError):
        life.mark_status("bogus")


def test_recover_report_flags(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        s.append_events(
            [
                _ev(1, "comp-1", LifecycleEventType.COMPACTION_STARTED, payload={}),
                _ev(2, "t-req", LifecycleEventType.TOOL_REQUESTED, payload={"tool_call_id": "t1"}),
                _ev(3, "t-sta", LifecycleEventType.TOOL_STARTED, payload={"tool_call_id": "t1"}),
                _ev(4, "t2-req", LifecycleEventType.TOOL_REQUESTED, payload={"tool_call_id": "t2"}),
            ]
        )
    life = ledger_mod.SessionLifecycle(tmp_path, HOST)
    report = life.recover_report()
    assert report["unclosed_compaction"] == ["comp-1"]
    unknown = report["tool_outcome_unknown"]
    assert unknown == [{"tool": "t1", "guidance": unknown[0]["guidance"]}]
    not_started = report["tool_not_started"]
    assert not_started == [{"tool": "t2", "guidance": not_started[0]["guidance"]}]
    # recovery finding event appended (plan §11.3)
    with ledger_mod.LedgerStore(tmp_path, HOST).open() as s:
        assert s._conn is not None
        kinds = [
            r["event_type"]
            for r in s._conn.execute("SELECT event_type FROM events ORDER BY seq").fetchall()
        ]
        assert "finding" in kinds
    # second run: bracket closed by the recovery event -> no new recovery
    report2 = life.recover_report()
    assert report2["unclosed_compaction"] == []


def test_purge_refuses_active_and_pinned(tmp_path, monkeypatch) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _create(s)
        _seed(s, 1)
    life = ledger_mod.SessionLifecycle(tmp_path, HOST)
    with pytest.raises(ledger_mod.SessionLifecycleError, match="not purgeable"):
        life.purge()  # active refuses
    life.pin(True)
    life.mark_status("finalizing")
    with pytest.raises(ledger_mod.SessionLifecycleError, match="pinned"):
        life.purge()
    life.pin(False)
    # durable decisions exist but extraction yields nothing -> refuse purge
    with ledger_mod.LedgerStore(tmp_path, HOST).open() as s:
        s.append_events(
            [
                _ev(
                    2,
                    "dec",
                    LifecycleEventType.DECISION,
                    payload={"decision": "use X", "rationale": "y"},
                )
            ]
        )
    monkeypatch.setattr(ledger_mod.SessionLifecycle, "extract_durable", lambda self: [])
    with pytest.raises(ledger_mod.SessionLifecycleError, match="extraction produced no memories"):
        life.purge()


def test_purge_flow_with_extraction_and_receipt(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _create(s, project="proj-a")
        s.append_events(
            [
                _ev(1, "task", LifecycleEventType.USER_TASK, payload={"task_sha256": "abc"}),
                _ev(
                    2,
                    "dec",
                    LifecycleEventType.DECISION,
                    payload={"decision": "use X", "rationale": "because Y"},
                ),
                _ev(
                    3,
                    "rep",
                    LifecycleEventType.WORKER_REPORT,
                    payload={"worker": "w1", "summary": "done"},
                ),
            ]
        )
    life = ledger_mod.SessionLifecycle(tmp_path, HOST)
    life.mark_status("inactive_grace")
    retention = ledger_mod.load_retention_config(tmp_path)
    # dry-run: nothing deleted
    dry = life.purge(inactive=True, dry_run=True, retention=retention)
    assert dry["dry_run"] is True
    assert (life.session_path / "ledger.sqlite").is_file()
    # real purge with extraction
    result = life.purge(inactive=True, retention=retention)
    assert result["purged"] == HOST
    assert len(result["extracted_memory_ids"]) == 1  # the decision
    assert not life.session_path.exists()  # dir gone incl db/wal/shm
    # receipt written in the canonical db
    from second_brain import db as db_mod

    conn = db_mod.connect(db_mod.db_path(tmp_path), readonly=True)
    rows = conn.execute("SELECT * FROM purge_receipts").fetchall()
    assert len(rows) == 1
    assert rows[0]["host_session_id"] == HOST
    assert rows[0]["status_before"] == "inactive_grace"
    conn.close()


def test_purge_safety_traversal_and_identity(tmp_path, monkeypatch) -> None:
    # hostile host ids are neutralized BY the hash: hex dirs only (plan §13.1)
    for hostile in ("..", "C:/Windows", "/etc", "..\\..\\brain"):
        internal = ledger_mod.internal_session_id(hostile)
        assert set(internal) <= set("0123456789abcdef")
        assert "/" not in internal and "\\" not in internal and ":" not in internal
        d = ledger_mod.session_dir(tmp_path, hostile)
        assert d.name == internal
        assert str(d).startswith(str((tmp_path / "state" / "sessions").resolve()))
    # manifest identity mismatch refuses purge
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True):
        pass
    internal = ledger_mod.internal_session_id(HOST)
    manifest_path = tmp_path / "state" / "sessions" / internal / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["internal_id"] = "deadbeef"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    life = ledger_mod.SessionLifecycle(tmp_path, HOST)
    with pytest.raises(ledger_mod.SessionLifecycleError, match="identity mismatch"):
        life.purge(inactive=True)
    # symlink escape refused by containment
    import os as _os

    if hasattr(_os, "symlink"):
        target = tmp_path / "outside"
        target.mkdir()
        link = tmp_path / "state" / "sessions" / internal / "objects-link"
        try:
            _os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            with pytest.raises(ValueError):
                ledger_mod._contained(tmp_path / "state" / "sessions" / internal, "objects-link/x")


def test_select_oldest_inactive_unpinned(tmp_path) -> None:
    for _i, host in enumerate(("host-a", "host-b", "host-c")):
        with ledger_mod.LedgerStore(tmp_path, host, host="test").open(create=True) as s:
            _create(s, host)
    ledger_mod.SessionLifecycle(tmp_path, "host-a").mark_status("inactive_grace")
    ledger_mod.SessionLifecycle(tmp_path, "host-c").mark_status("inactive_grace")
    ledger_mod.SessionLifecycle(tmp_path, "host-c").pin(True)
    assert ledger_mod.select_oldest_inactive_unpinned(tmp_path) == "host-a"
    rows = ledger_mod.list_sessions(tmp_path)
    live = {r["host_session_id"] for r in rows if not r.get("purged")}
    assert live == {"host-a", "host-b", "host-c"}


# ---------------------------------------------------------------------------
# T-G6 fixes: seq:0 auto-assign, decision_id rehydration match
# ---------------------------------------------------------------------------


def test_append_auto_assigns_seq_zero(tmp_path) -> None:
    """T-G6-F1: events with seq<=0 auto-assign contiguous seqs."""
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        _seed(s, 1)
        seqs = s.append_events(
            [
                _ev(0, "z-1", LifecycleEventType.USER_TASK, parent="e-1"),
                _ev(0, "z-2", LifecycleEventType.USER_TASK, parent="z-1"),
            ]
        )
        assert seqs == [2, 3]
        assert s.integrity()["seq_contiguous"] is True


def test_rehydrate_decision_id_match(tmp_path) -> None:
    """T-G6-F2: --decision matches event_id OR payload decision_id."""
    with ledger_mod.LedgerStore(tmp_path, HOST, host="test").open(create=True) as s:
        s.append_events(
            [
                _ev(
                    1,
                    "d-1",
                    LifecycleEventType.DECISION,
                    payload={"decision_id": "dec-abc", "decision": "use X"},
                ),
                _ev(
                    2,
                    "d-2",
                    LifecycleEventType.DECISION,
                    payload={"decision_id": "dec-xyz", "decision": "use Y"},
                ),
            ]
        )
    rh = ledger_mod.LedgerRehydrator(ledger_mod.LedgerStore(tmp_path, HOST).open())
    by_event = rh.rehydrate(2, decision="d-1")
    assert [p["event_id"] for p in by_event["evidence_packets"]] == ["d-1"]
    by_payload = rh.rehydrate(2, decision="dec-xyz")
    assert [p["event_id"] for p in by_payload["evidence_packets"]] == ["d-2"]
    # substring match across both decision_ids -> different content (not deduped)
    by_substring = rh.rehydrate(2, decision="dec")
    assert [p["event_id"] for p in by_substring["evidence_packets"]] == ["d-1", "d-2"]
    led = ledger_mod.LedgerStore(tmp_path, HOST)
    led.close()


# ---------------------------------------------------------------------------
# T4.2: one unified session-id scheme, host-required ledger initialization
# ---------------------------------------------------------------------------


def test_ledger_store_requires_explicit_host_on_first_init(tmp_path) -> None:
    """A brand-new ledger directory with no explicit host and no prior
    manifest must raise deterministically -- never silently write
    host='prime' (T4.2)."""
    with pytest.raises(BrainError, match="requires an explicit host"):
        ledger_mod.LedgerStore(tmp_path, "never-initialized-session").open(create=True)
    session_dir = (
        tmp_path
        / "state"
        / "sessions"
        / ledger_mod.internal_session_id("never-initialized-session")
    )
    assert not (session_dir / "manifest.json").exists()

    # An explicit host succeeds and the manifest records it (never 'prime').
    with ledger_mod.LedgerStore(tmp_path, "never-initialized-session", host="hermes").open(
        create=True
    ) as s:
        assert s.header()["schema_version"] == str(ledger_mod.LEDGER_SCHEMA_VERSION)
    manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["host"] == "hermes"

    # Re-opening the now-initialized ledger without a host preserves the
    # already-recorded host instead of raising (re-open/append is unaffected).
    with ledger_mod.LedgerStore(tmp_path, "never-initialized-session").open(create=True) as s:
        assert s.header()["schema_version"] == str(ledger_mod.LEDGER_SCHEMA_VERSION)
    manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["host"] == "hermes"


def test_single_session_id_scheme(brain_home, monkeypatch) -> None:
    """Every cli.py host adapter hook/CLI site builds internal_session_id via
    ledger.internal_session_id(host_session_id) -- the single unified,
    full-sha256-hex scheme (T4.2). No adapter constructs the deleted
    'is-' + sha256(...)[:12] identity."""
    import io
    import sys
    from types import SimpleNamespace

    from second_brain import cli, contracts

    captured: list[contracts.BrainSessionIdentity] = []
    real_cls = contracts.BrainSessionIdentity

    def _spy(*args, **kwargs):
        identity = real_cls(*args, **kwargs)
        captured.append(identity)
        return identity

    monkeypatch.setattr(contracts, "BrainSessionIdentity", _spy)

    # 1) codex-hooks: Stop/SessionEnd finalization branch (no task text).
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"source": "Stop", "session_id": "codex-stop-sess"})),
    )
    cli._cmd_codex_shadow(brain_home)

    # 2) codex-hooks: main prepare_injection branch.
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "codex-main-sess",
                    "project": "proj",
                    "task": "do the thing",
                    "agent_id": "a1",
                    "branch": "main",
                    "role": "worker",
                }
            )
        ),
    )
    cli._cmd_codex_shadow(brain_home)

    # 3) antigravity hook.
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"conversationId": "agy-sess"})))
    cli._cmd_antigravity_hook(brain_home)

    # 4) claude-code hook.
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"session_id": "claude-sess", "hook_event_name": "SessionStart"})),
    )
    cli._cmd_claude_code_hook(brain_home)

    # 5) brainctl writeback.
    writeback_args = SimpleNamespace(
        home=brain_home,
        session_id="brainctl-sess",
        project_id="proj",
        title="observed pattern",
        observation="the tool always retries twice",
        guidance="",
        evidence="[]",
    )
    cli._cmd_writeback(brain_home, writeback_args)

    # 6) prime-cli shadow.
    shadow_args = SimpleNamespace(
        home=brain_home,
        autoinject_command="shadow",
        task="do it",
        project_id="proj",
        cwd=None,
        session_id="prime-sess",
        agent_id="a1",
        branch="main",
        role_profile="orchestrator",
        json=False,
    )
    cli.cmd_autoinject(shadow_args)

    assert {identity.host for identity in captured} == {
        "codex-hooks",
        "antigravity",
        "claude-code",
        "brainctl",
        "prime-cli",
    }
    assert len(captured) == 6  # 2 codex-hooks sites + 4 single-site adapters
    for identity in captured:
        expected = ledger_mod.internal_session_id(identity.host_session_id)
        assert identity.internal_session_id == expected
        assert not identity.internal_session_id.startswith("is-")
        assert len(identity.internal_session_id) == 64  # full sha256 hex digest


def test_rehydrate_refuses_tampered_chain(store) -> None:
    """A projection built from an unverified chain must not be presented as recovered memory."""
    _seed(store, 3)
    # Control: an intact ledger rehydrates.
    assert ledger_mod.LedgerRehydrator(store).rehydrate(3)["events"]
    assert store.integrity()["hash_chain_ok"] is True

    # Tamper with a stored payload without touching the recorded chain.
    store._conn.execute(
        "UPDATE events SET payload_json = ? WHERE event_id = ?",
        ('{"agent_id": "forged"}', "e-2"),
    )
    store._conn.commit()
    assert store.integrity()["hash_chain_ok"] is False

    with pytest.raises(BrainError, match="hash chain broken"):
        ledger_mod.LedgerRehydrator(store).rehydrate(3)
