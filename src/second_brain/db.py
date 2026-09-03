"""SQLite control database: connection defaults and migration framework.

Plan §8: WAL, foreign_keys=ON, synchronous=NORMAL.
Plan §9: migrations from day one; schema_version table records applied versions.
Migrations are atomic per file: all statements of one migration apply inside a
single transaction, then its version row is committed. Re-running applies only
pending migrations (idempotent).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC
from pathlib import Path
from .errors import MigrationError
from .paths import db_path  # noqa: F401  (re-export; used as db.db_path)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

SCHEMA_VERSION_DDL = """CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);"""


def connect(dbfile: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open the Brain database with canonical pragmas."""
    path = Path(dbfile)
    path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def split_statements(script: str) -> list[str]:
    """Split a SQL script into individual statements using sqlite3's parser.

    Handles semicolons inside string literals and comments correctly.
    """
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    tail = buffer.strip()
    if tail:
        raise MigrationError(f"Trailing incomplete SQL statement: {tail[:80]!r}")
    return statements


def migration_files(migrations_dir: Path | None = None) -> list[Path]:
    d = Path(migrations_dir) if migrations_dir else MIGRATIONS_DIR
    return sorted(p for p in d.glob("*.sql") if p.name[:4].isdigit())


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(SCHEMA_VERSION_DDL)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
    return int(row["v"])

def ensure_brain_meta(conn: sqlite3.Connection) -> None:
    """Ensure control metadata exists for older databases."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS brain_meta("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO brain_meta(key, value) VALUES ('memory_epoch', '0')"
    )


def memory_epoch(conn: sqlite3.Connection) -> int:
    """Read the current canonical-memory epoch from an open connection."""
    ensure_brain_meta(conn)
    row = conn.execute(
        "SELECT value FROM brain_meta WHERE key = 'memory_epoch'"
    ).fetchone()
    try:
        return int(row["value"]) if row is not None else 0
    except (TypeError, ValueError):
        return 0


def bump_memory_epoch(conn: sqlite3.Connection) -> int:
    """Increment and return the canonical-memory epoch in the open transaction."""
    ensure_brain_meta(conn)
    conn.execute(
        "UPDATE brain_meta SET value = CAST(value AS INTEGER) + 1 "
        "WHERE key = 'memory_epoch'"
    )
    return memory_epoch(conn)


def read_memory_epoch(dbfile: str | Path) -> int:
    """Read an epoch by database path without creating a write transaction."""
    conn = connect(dbfile)
    try:
        row = conn.execute(
            "SELECT value FROM brain_meta WHERE key = 'memory_epoch'"
        ).fetchone()
        try:
            return int(row["value"]) if row is not None else 0
        except (TypeError, ValueError):
            return 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _execute_migration_statement(
    conn: sqlite3.Connection, stmt: str, *, version: int
) -> None:
    """Execute one migration statement, guarding additive column changes.

    SQLite has no portable ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``.
    Inspecting ``table_info`` before the narrow additive form keeps migration
    0012 restartable if a manually-created database already has some columns.
    """
    del version  # reserved for future migration-specific guards
    match = re.match(
        r"^\s*ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\b",
        stmt,
        re.IGNORECASE,
    )
    if match:
        table, column = match.groups()
        existing = {
            str(row["name"]).casefold()
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column.casefold() in existing:
            return
    conn.execute(stmt)


def apply_migration(conn: sqlite3.Connection, path: Path, version: int, applied_at: str) -> None:
    script = path.read_text(encoding="utf-8")
    statements = split_statements(script)
    if not statements:
        raise MigrationError(f"Migration file {path.name} contains no statements")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for stmt in statements:
            _execute_migration_statement(conn, stmt, version=version)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def migrate(dbfile: str | Path, migrations_dir: Path | None = None) -> list[int]:
    """Apply all pending migrations. Returns the versions applied (empty if current)."""
    from datetime import datetime

    conn = connect(dbfile)
    try:
        ensure_brain_meta(conn)
        conn.commit()
        applied = current_version(conn)
        out: list[int] = []
        files = migration_files(migrations_dir)
        for path in files:
            version = int(path.name[:4])
            if version <= applied:
                continue
            apply_migration(conn, path, version, datetime.now(UTC).isoformat())
            out.append(version)
        # Migration 0012 was already marked applied by some installations
        # before its additive origin extension shipped. Replay only its
        # guarded ALTER statements so those databases converge without a
        # version bump or destructive table rewrite.
        extension = next((p for p in files if p.name.startswith("0012_")), None)
        if extension is not None and applied >= 12:
            statements = split_statements(extension.read_text(encoding="utf-8"))
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in statements:
                    _execute_migration_statement(conn, stmt, version=12)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return out
    finally:
        conn.close()


def pending_migrations(dbfile: str | Path, migrations_dir: Path | None = None) -> list[int]:
    conn = connect(dbfile)
    try:
        applied = current_version(conn)
        return [
            int(p.name[:4]) for p in migration_files(migrations_dir) if int(p.name[:4]) > applied
        ]
    finally:
        conn.close()
