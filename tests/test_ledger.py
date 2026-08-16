"""P2 session ledger tests (plan §9, §9.10, §11.2, §14; Phase G).

Append-only ledger substrate + independent replay/invariant checker:
contiguity, duplicate/invalid-parent rejection, object digests, FTS search +
LIKE fallback, schema versioning, replay rejection of injected corruption,
and tool-crash state classification.
"""

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
        artifact_sha256=None,
        source_event_ids=[],
    )


@pytest.fixture
def store(tmp_path):
    s = ledger_mod.LedgerStore(tmp_path, HOST).open(create=True)
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
                parent=f"{prefix}-{i-1}" if i > 1 else None,
            )
        )
    store.append_events(events)
    return events


def test_init_manifest_and_header(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
        internal = ledger_mod.internal_session_id(HOST)
        assert s.session_path.name == internal
        assert s.dbfile.is_file()
        assert (s.session_path / "manifest.json").is_file()
        header = s.header()
        assert header["schema_version"] == "1"
        assert header["adapter_name"] == "second-brain"
    manifest = json.loads((s.session_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["internal_id"] == ledger_mod.internal_session_id(HOST)
    assert manifest["host_session_id"] == HOST


def test_internal_id_is_hash_not_raw(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True):
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


def test_schema_versioning(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True):
        pass
    internal = ledger_mod.internal_session_id(HOST)
    dbfile = tmp_path / "state" / "sessions" / internal / "ledger.sqlite"
    conn = sqlite3.connect(dbfile)
    conn.execute("UPDATE ledger_meta SET value = '2' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(BrainError, match="newer runtime"):
        ledger_mod.LedgerStore(tmp_path, HOST).open()
    conn = sqlite3.connect(dbfile)
    conn.execute("UPDATE ledger_meta SET value = '0' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(BrainError, match="no in-memory upgrader"):
        ledger_mod.LedgerStore(tmp_path, HOST).open()


def test_replay_projection_and_compare(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
        _seed(s, 3)
        proj = s.replay(["e-1", "e-2", "e-3"])
        assert [e.event_id for e in proj.events] == ["e-1", "e-2", "e-3"]
        assert ledger_mod.compare_projection(proj, proj) is None
    # independent fresh replay
    replayed = ledger_mod.replay_session(tmp_path, HOST, ["e-1", "e-2", "e-3"])
    assert [e.event_id for e in replayed.events] == ["e-1", "e-2", "e-3"]


def test_replay_rejects_seq_gap(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
        _seed(s, 3)
        conn = sqlite3.connect(s.dbfile)
        conn.execute("DELETE FROM events WHERE seq = 2")
        conn.commit()
        conn.close()
        with pytest.raises(BrainError, match="seq not contiguous"):
            s.replay(["e-1", "e-3"])


def test_replay_rejects_orphan_parent(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
        _seed(s, 2)
        conn = sqlite3.connect(s.dbfile)
        conn.execute("UPDATE events SET parent_event_id = 'ghost' WHERE seq = 2")
        conn.commit()
        conn.close()
        with pytest.raises(BrainError, match="orphan"):
            s.replay(["e-1", "e-2"])


def test_replay_rejects_broken_lineage_pointer(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
        _seed(s, 3)
        with pytest.raises(BrainError, match="lineage event missing"):
            s.replay(["e-1", "ghost"])


def test_replay_detects_payload_tamper_via_compare(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
        _seed(s, 3)
        captured = s.replay(["e-1", "e-2", "e-3"])
        conn = sqlite3.connect(s.dbfile)
        row = conn.execute("SELECT payload_json FROM events WHERE seq = 2").fetchone()
        payload = json.loads(row[0])
        payload["task"] = "tampered"
        conn.execute("UPDATE events SET payload_json = ? WHERE seq = 2", (json.dumps(payload),))
        conn.commit()
        conn.close()
        replayed = s.replay(["e-1", "e-2", "e-3"])
        divergence = ledger_mod.compare_projection(captured, replayed)
        assert divergence is not None
        assert "payload differs" in divergence


def test_replay_rejects_missing_object(tmp_path) -> None:
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
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
        capture_output=True, text=True, env=env, cwd=home, timeout=120, check=True,
    )
    r = subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), "ledger", "init",
         "--session", HOST,
         "--host-artifact", "transcript=C:/sessions/host-1.jsonl",
         "--host-artifact", "telemetry=C:/brain/telemetry/agent-performance/host-1.jsonl"],
        capture_output=True, text=True, env=env, cwd=home, timeout=120,
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
        [sys.executable, "-m", "second_brain", "--home", str(home), "ledger", "init",
         "--session", "other-session", "--host-artifact", "noseparator"],
        capture_output=True, text=True, env=env, cwd=home, timeout=120,
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
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
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
    store.append_events(
        [
            _ev(1, "task", LifecycleEventType.USER_TASK, payload={"task_sha256": "abc"}),
            _ev(
                2,
                "dec",
                LifecycleEventType.DECISION,
                payload={"decision": "use X", "rationale": "because Y"},
                parent="task",
            ),
        ]
    )
    digest = store.add_object(b"exact artifact bytes", mime="text/plain", role="artifact")
    # attach the artifact to the decision event via direct update (mirror of tool flow)
    store._conn.execute(
        "UPDATE events SET artifact_sha256 = ? WHERE event_id = 'dec'", (digest,)
    )
    store._conn.commit()
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
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
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
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
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
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True) as s:
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
    with ledger_mod.LedgerStore(tmp_path, HOST).open(create=True):
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
        with ledger_mod.LedgerStore(tmp_path, host).open(create=True) as s:
            _create(s, host)
    ledger_mod.SessionLifecycle(tmp_path, "host-a").mark_status("inactive_grace")
    ledger_mod.SessionLifecycle(tmp_path, "host-c").mark_status("inactive_grace")
    ledger_mod.SessionLifecycle(tmp_path, "host-c").pin(True)
    assert ledger_mod.select_oldest_inactive_unpinned(tmp_path) == "host-a"
    rows = ledger_mod.list_sessions(tmp_path)
    live = {r["host_session_id"] for r in rows if not r.get("purged")}
    assert live == {"host-a", "host-b", "host-c"}
