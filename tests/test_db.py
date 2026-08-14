import sqlite3

import pytest

from second_brain import db
from second_brain.errors import MigrationError


def test_migrate_creates_schema(brain_home):
    dbf = db.db_path(brain_home)
    conn = db.connect(dbf)
    try:
        v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        assert v == 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"schema_version", "projects"} <= tables
    finally:
        conn.close()


def test_migrate_idempotent(brain_home):
    dbf = db.db_path(brain_home)
    assert db.migrate(dbf) == []
    assert db.migrate(dbf) == []


def test_pragmas(brain_home):
    conn = db.connect(db.db_path(brain_home))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    finally:
        conn.close()


def test_foreign_keys_enforced(brain_home):
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, pid TEXT REFERENCES projects(id))"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child (pid) VALUES ('nope')")
    finally:
        conn.close()


def test_reopen_after_commit(brain_home):
    dbf = db.db_path(brain_home)
    conn = db.connect(dbf)
    conn.execute("INSERT INTO projects (id, name, created_at) VALUES ('p1', 'P1', '2026-01-01')")
    conn.commit()
    conn.close()
    conn = db.connect(dbf)
    try:
        assert conn.execute("SELECT name FROM projects WHERE id='p1'").fetchone()[0] == "P1"
    finally:
        conn.close()


def test_split_statements_handles_strings_and_comments():
    script = """
    -- leading comment; with semicolon
    INSERT INTO t VALUES ('a;b');
    INSERT INTO t VALUES ('c');
    """
    stmts = db.split_statements(script)
    assert len(stmts) == 2
    assert "a;b" in stmts[0]


def test_split_statements_incomplete_raises():
    with pytest.raises(MigrationError):
        db.split_statements("SELECT 1; SELECT")


def test_custom_migrations_dir_ordering(tmp_path):
    d = tmp_path / "migs"
    d.mkdir()
    (d / "0001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    (d / "0002_b.sql").write_text("CREATE TABLE b (x INTEGER);")
    dbfile = tmp_path / "db.sqlite"
    applied = db.migrate(dbfile, migrations_dir=d)
    assert applied == [1, 2]
    assert db.migrate(dbfile, migrations_dir=d) == []
