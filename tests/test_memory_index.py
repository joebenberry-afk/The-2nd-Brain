"""Phase 6: SQLite FTS5 memory index (migration 0007, indexer, search parity)."""

import sqlite3
from typing import cast

from second_brain import backup, db, paths, semantic


def _add(home, title, body, **kw):
    return semantic.add_memory(home, title, body, **kw)


def _index_tables(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    virtual = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return tables, virtual


def test_migration_0007_fresh_create(brain_home):
    dbf = db.db_path(brain_home)
    conn = db.connect(dbf)
    try:
        v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        assert v == 9
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_index)")}
        assert {
            "memory_id",
            "title",
            "summary",
            "project_id",
            "scope",
            "status",
            "evidence_grade",
            "current_version",
            "created_at",
            "updated_at",
            "body_path",
            "tags",
            "file_hash",
            "indexed_at",
        } <= cols
    finally:
        conn.close()


def test_migrate_idempotent_reopen(brain_home):
    dbf = db.db_path(brain_home)
    assert db.migrate(dbf) == []
    conn = db.connect(dbf)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='memory_index'").fetchone()[
                0
            ]
            == 1
        )
    finally:
        conn.close()


def test_backup_restore_preserves_index(brain_home, tmp_path, monkeypatch):
    mid = _add(brain_home, title="WAL hygiene", body="stale sidecar frames")
    semantic.index_memory(brain_home, mid)
    dbf = db.db_path(brain_home)
    conn = db.connect(dbf)
    try:
        assert conn.execute("SELECT COUNT(*) FROM memory_index").fetchone()[0] == 1
    finally:
        conn.close()

    bdir = backup.create_backup(brain_home, note="fts-test")
    # restore into a fresh home
    home2 = tmp_path / "brain2"
    backup.restore_backup(home2, bdir, force=True)
    conn2 = db.connect(db.db_path(home2))
    try:
        rows = conn2.execute("SELECT memory_id FROM memory_index").fetchall()
        assert len(rows) == 1
        assert rows[0]["memory_id"] == mid
        # FTS5 content restored with the DB snapshot and is queryable
        hits = conn2.execute(
            "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ?", ('"wal"*',)
        ).fetchall()
        assert [h["memory_id"] for h in hits] == [mid]
    finally:
        conn2.close()


def test_add_memory_indexes_automatically(brain_home):
    mid = _add(brain_home, title="Router noise", body="trigger phrases")
    conn = db.connect(db.db_path(brain_home))
    try:
        row = conn.execute("SELECT * FROM memory_index WHERE memory_id=?", (mid,)).fetchone()
        assert row is not None
        assert row["title"] == "Router noise"
        hits = conn.execute(
            "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ?", ('"trigger"*',)
        ).fetchall()
        assert [h["memory_id"] for h in hits] == [mid]
    finally:
        conn.close()


def test_curate_updates_index_metadata(brain_home):
    mid = _add(brain_home, title="Evidence map", body="scout output")
    semantic.curate(brain_home, mid, grade="TESTED", status="current")
    conn = db.connect(db.db_path(brain_home))
    try:
        row = conn.execute("SELECT * FROM memory_index WHERE memory_id=?", (mid,)).fetchone()
        assert row["evidence_grade"] == "TESTED"
        assert row["status"] == "current"
    finally:
        conn.close()


def test_supersede_reindexes_new_version(brain_home):
    mid = _add(brain_home, title="Old title", body="old body content")
    semantic.supersede(brain_home, mid, new_body="fresh body with quasar", change_note="v2")
    conn = db.connect(db.db_path(brain_home))
    try:
        row = conn.execute("SELECT * FROM memory_index WHERE memory_id=?", (mid,)).fetchone()
        assert row["current_version"] == 2
        assert row["body_path"].endswith("__v2.md")
        old_hits = conn.execute(
            "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?", ('"content"*',)
        ).fetchone()[0]
        assert old_hits == 0  # v1-only body word no longer indexed (title is shared)
        new_hits = conn.execute(
            "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?", ('"quasar"*',)
        ).fetchone()[0]
        assert new_hits == 1
    finally:
        conn.close()


def test_reindex_all_incremental_and_purge(brain_home):
    mid = _add(brain_home, title="Stable memory", body="steady state")
    first = semantic.reindex_all(brain_home)
    assert first["skipped"] >= 1 and first["purged"] == 0  # auto-indexed at add: unchanged
    second = semantic.reindex_all(brain_home)
    assert second["skipped"] >= 1  # unchanged files skipped

    # hand-edit the canonical file -> hash changes -> reindexed
    row = semantic.show_memory(brain_home, mid)
    path = paths.Path(row["path"])
    path.write_text(
        path.read_text(encoding="utf-8").replace("steady state", "drifting state"), encoding="utf-8"
    )
    third = semantic.reindex_all(brain_home)
    assert third["indexed"] >= 1
    conn = db.connect(db.db_path(brain_home))
    try:
        hits = conn.execute(
            "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?", ('"drifting"*',)
        ).fetchone()[0]
        assert hits == 1
    finally:
        conn.close()

    # delete the file -> purge
    paths.Path(row["path"]).unlink()
    fourth = semantic.reindex_all(brain_home)
    assert fourth["purged"] >= 1
    conn = db.connect(db.db_path(brain_home))
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM memory_index WHERE memory_id=?", (mid,)).fetchone()[
                0
            ]
            == 0
        )
    finally:
        conn.close()


FIXTURE = [
    ("WAL hygiene", "restore safety", "stale sidecar frames"),
    ("Scout promotion", "evidence map", "read-only repository explorer"),
    ("Sleep consolidation", "replay queue", "dreaming never verified facts"),
    ("Immune quarantine", "fingerprint scan", "baseline drift detection"),
]


def _build_fixture(home):
    ids = {}
    for title, summary, body in FIXTURE:
        ids[title] = _add(home, title=title, summary=summary, body=body)
    return ids


def test_search_parity_fts_vs_linear(brain_home, monkeypatch):
    _build_fixture(brain_home)
    for term, expected_titles in [
        ("WAL", ["WAL hygiene"]),
        ("SAFETY", ["WAL hygiene"]),  # summary
        ("sidecar", ["WAL hygiene"]),  # body
        ("scout", ["Scout promotion"]),
        ("explorer", ["Scout promotion"]),
        ("sleep", ["Sleep consolidation"]),
        ("quarantine", ["Immune quarantine"]),
        ("zzz", []),
        ("WAL lesson", []),  # AND of prefixes: no doc has both
    ]:
        fts = semantic.search_memories(brain_home, term)
        assert {r["title"] for r in fts} == set(expected_titles), term
        # parity with the linear engine on word/prefix terms
        linear = semantic._search_linear(brain_home, term)
        assert {r["memory_id"] for r in fts} == {r["memory_id"] for r in linear}, term


def test_search_fallback_linear_when_fts_unavailable(brain_home, monkeypatch):
    _build_fixture(brain_home)
    monkeypatch.setattr(semantic, "_FTS_MODULE_CHECKED", True)
    monkeypatch.setattr(semantic, "_FTS_MODULE_OK", False)
    monkeypatch.setattr(semantic, "_fts_available", lambda conn: False)
    for term in ("WAL", "SAFETY", "sidecar", "zzz"):
        got = semantic.search_memories(brain_home, term)
        assert {r["memory_id"] for r in got} == {
            r["memory_id"] for r in semantic._search_linear(brain_home, term)
        }, term


def test_search_fallback_when_index_empty_but_memories_exist(brain_home):
    ids = _build_fixture(brain_home)
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute("DELETE FROM memory_fts")
        conn.execute("DELETE FROM memory_index")
        conn.commit()
    finally:
        conn.close()
    # empty index + existing memories -> linear fallback, not empty results
    got = semantic.search_memories(brain_home, "sidecar")
    assert {r["memory_id"] for r in got} == {ids["WAL hygiene"]}


def test_search_known_divergence_middle_substring(brain_home):
    """Documented Phase 6 divergence: FTS5 matches word prefixes only."""
    _add(brain_home, title="Sidecar", body="sidecar frames")
    # middle substring matches the linear scan but NOT FTS5 prefix matching
    assert len(semantic._search_linear(brain_home, "car")) == 1
    assert len(semantic.search_memories(brain_home, "car")) == 0
    # word-prefix still matches
    assert len(semantic.search_memories(brain_home, "side")) == 1


def test_search_empty_index_empty_results(brain_home):
    assert semantic.search_memories(brain_home, "anything") == []


def test_fts_available_only_module_missing_is_permanent(brain_home, monkeypatch):
    """N-C: transient OperationalErrors must NOT degrade the process to linear."""

    class StubConn:
        def __init__(self, message):
            self.message = message

        def execute(self, *args):
            raise sqlite3.OperationalError(self.message)

    monkeypatch.setattr(semantic, "_FTS_MODULE_CHECKED", False)
    monkeypatch.setattr(semantic, "_FTS_MODULE_OK", False)

    # transient error: False for this call, NOT cached -> next call retries
    assert semantic._fts_available(cast(sqlite3.Connection, StubConn("disk I/O error"))) is False
    assert semantic._FTS_MODULE_CHECKED is False
    assert semantic._FTS_MODULE_OK is False

    # real database still works after the transient error (not poisoned)
    conn = db.connect(db.db_path(brain_home))
    try:
        assert semantic._fts_available(conn) is True
    finally:
        conn.close()

    # module-missing error: cached permanently
    monkeypatch.setattr(semantic, "_FTS_MODULE_CHECKED", False)
    monkeypatch.setattr(semantic, "_FTS_MODULE_OK", False)
    err_conn = cast(sqlite3.Connection, StubConn("no such module: fts5"))
    assert semantic._fts_available(err_conn) is False
    assert semantic._FTS_MODULE_CHECKED is True
    assert semantic._FTS_MODULE_OK is False
    disk_conn = cast(sqlite3.Connection, StubConn("disk I/O error"))
    assert semantic._fts_available(disk_conn) is False  # cached miss
