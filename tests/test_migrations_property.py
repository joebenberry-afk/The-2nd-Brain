"""Hypothesis property tests for the migration framework and backup roundtrip.

Invariants:
- Applying any prefix of the migration sequence and then the remainder yields
  the same final schema as applying all at once, and re-running is a no-op.
- Backup -> restore roundtrip preserves project rows exactly (recovery).

Each example manages its own temporary directory (no pytest fixtures inside
@given bodies).
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from second_brain import backup as backup_mod
from second_brain import db, paths

ROOT = Path(__file__).resolve().parent.parent


def _migration_chain(base: Path) -> Path:
    d = base / "migs"
    d.mkdir()
    (d / "0001_a.sql").write_text("CREATE TABLE a (x INTEGER);", encoding="utf-8")
    (d / "0002_b.sql").write_text("CREATE TABLE b (x INTEGER REFERENCES a(x));", encoding="utf-8")
    (d / "0003_c.sql").write_text("CREATE TABLE c (x INTEGER);", encoding="utf-8")
    return d


def _minimal_brain(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    paths.ensure_layout(home)
    (home / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    cfg = home / "config"
    for name in paths.REQUIRED_CONFIG_FILES:
        (cfg / name).write_text("schema_version = 1\n", encoding="utf-8")
    shutil.copytree(ROOT / "templates", home / "templates", dirs_exist_ok=True)
    db.migrate(db.db_path(home))


@settings(max_examples=8)
@given(k=st.integers(min_value=0, max_value=3))
def test_any_prefix_then_remainder_equals_full_apply(k: int) -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        full = _migration_chain(base)
        dbfile = base / "brain.sqlite"

        prefix = base / "prefix"
        prefix.mkdir()
        for f in sorted(full.glob("*.sql"))[:k]:
            shutil.copy2(f, prefix / f.name)

        assert db.migrate(dbfile, migrations_dir=prefix) == list(range(1, k + 1))

        conn = sqlite3.connect(dbfile)
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert tables == {"schema_version"} | set("abc"[:k])
        finally:
            conn.close()

        assert db.migrate(dbfile, migrations_dir=full) == list(range(k + 1, 4))

        conn = sqlite3.connect(dbfile)
        try:
            v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            assert v == 3
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert {"schema_version", "a", "b", "c"} <= tables
        finally:
            conn.close()

        assert db.migrate(dbfile, migrations_dir=full) == []


@settings(max_examples=5)
@given(
    pid=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-"),
        min_size=1,
        max_size=24,
    ),
    name=st.text(min_size=1, max_size=40),
)
def test_backup_restore_preserves_rows(pid: str, name: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        home = base / "brain"
        _minimal_brain(home)

        conn = db.connect(db.db_path(home))
        conn.execute(
            "INSERT INTO projects (id, name, created_at) VALUES (?, ?, '2026-01-01')",
            (pid, name),
        )
        conn.commit()
        conn.close()

        bdir = backup_mod.create_backup(home)
        home2 = base / "brain2"
        home2.mkdir()
        backup_mod.restore_backup(home2, bdir)

        conn = db.connect(db.db_path(home2))
        try:
            rows = conn.execute("SELECT id, name FROM projects").fetchall()
            assert [tuple(r) for r in rows] == [(pid, name)]
        finally:
            conn.close()
