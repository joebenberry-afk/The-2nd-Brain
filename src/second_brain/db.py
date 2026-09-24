"""SQLite control database: connection defaults and migration framework.

Plan §8: WAL, foreign_keys=ON, synchronous=NORMAL.
Plan §9: migrations from day one; schema_version table records applied versions.
Migrations are atomic per file: all statements of one migration apply inside a
single transaction, then its version row is committed. Re-running applies only
pending migrations (idempotent).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from datetime import UTC
from pathlib import Path

from .errors import MigrationError
from .paths import db_path  # noqa: F401  (re-export; used as db.db_path)

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

#: The journal-mode transition is retried this many times, then left alone.
_WAL_ATTEMPTS = 20
_WAL_RETRY_SECONDS = 0.05


def ensure_wal(conn: sqlite3.Connection, *, required: bool) -> None:
    """Put the database into WAL, waiting out a concurrent first open.

    SQLite answers SQLITE_BUSY *immediately* when the journal-mode transition cannot take the
    exclusive lock it needs: the busy timeout does not defer it, because the two connections may be
    converting from different modes. Concurrent first opens of the same fresh database therefore
    failed with "database is locked" (measured on the shared control database: 14 crashes in 200
    concurrent opens). The transition is retried in bounded steps, and ``required`` decides what a
    caller does when even those do not win it: the ledger's append guarantees need WAL, while the
    control database only loses a tuning choice.
    """
    error: sqlite3.OperationalError | None = None
    for attempt in range(_WAL_ATTEMPTS):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            error = exc
            if attempt != _WAL_ATTEMPTS - 1:
                time.sleep(_WAL_RETRY_SECONDS)
    if required:
        raise error  # type: ignore[misc]
    logger.debug("WAL transition unavailable; keeping the current journal mode")

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
    # The busy timeout is set before the first locking statement, so every wait below has a policy.
    conn.execute("PRAGMA busy_timeout=5000")
    if not readonly:
        ensure_wal(conn, required=False)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
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
    conn.execute("CREATE TABLE IF NOT EXISTS brain_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO brain_meta(key, value) VALUES ('memory_epoch', '0')")


def memory_epoch(conn: sqlite3.Connection) -> int:
    """Read the current canonical-memory epoch from an open connection."""
    ensure_brain_meta(conn)
    row = conn.execute("SELECT value FROM brain_meta WHERE key = 'memory_epoch'").fetchone()
    try:
        return int(row["value"]) if row is not None else 0
    except (TypeError, ValueError):
        return 0


def bump_memory_epoch(conn: sqlite3.Connection) -> int:
    """Increment and return the canonical-memory epoch in the open transaction."""
    ensure_brain_meta(conn)
    conn.execute(
        "UPDATE brain_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'memory_epoch'"
    )
    return memory_epoch(conn)


def read_memory_epoch(dbfile: str | Path) -> int:
    """Read an epoch by database path without creating a write transaction."""
    conn = connect(dbfile)
    try:
        row = conn.execute("SELECT value FROM brain_meta WHERE key = 'memory_epoch'").fetchone()
        try:
            return int(row["value"]) if row is not None else 0
        except (TypeError, ValueError):
            return 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _execute_migration_statement(conn: sqlite3.Connection, stmt: str, *, version: int) -> None:
    """Execute one migration statement, guarding additive column changes.

    SQLite has no portable ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``.
    Inspecting ``table_info`` before the narrow additive form keeps migration
    0012 restartable if a manually-created database already has some columns.
    """
    del version  # reserved for future migration-specific guards
    clean_stmt = re.sub(r"--[^\n]*\n?", "", stmt).strip()
    clean_stmt = re.sub(r"/\*.*?\*/", "", clean_stmt, flags=re.DOTALL).strip()
    match = re.match(
        r"^\s*ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+(?:COLUMN\s+)?"
        r"([A-Za-z_][A-Za-z0-9_]*)\b",
        clean_stmt,
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


def apply_migration(conn: sqlite3.Connection, path: Path, version: int, applied_at: str) -> bool:
    script = path.read_text(encoding="utf-8")
    statements = split_statements(script)
    if not statements:
        raise MigrationError(f"Migration file {path.name} contains no statements")
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Another process may have migrated after our caller read the version.
        if current_version(conn) >= version:
            conn.commit()
            return False
        if version == 24:
            # Old path-derived identities cannot be rebound from today's paths:
            # a rename/replacement may have occurred and live callbacks bind the
            # old key. Require explicit reconciliation, never choose a winner.
            unresolved = conn.execute(
                "SELECT task_id FROM worker_tasks WHERE "
                "writer_ownership IN ('held','quarantined') OR "
                "(access_intent='mutating' AND "
                "(writer_ownership IS NULL OR writer_ownership!='released')) OR "
                "(access_intent IS NULL AND state NOT IN "
                "('COMPLETED','CANCELED','FAILED','REJECTED')) LIMIT 1"
            ).fetchone()
            if unresolved is not None:
                raise MigrationError(
                    "Cannot migrate physical worktree ownership with unresolved "
                    "historical holders; reconcile exact-attempt cleanup first"
                )
        for stmt in statements:
            _execute_migration_statement(conn, stmt, version=version)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        conn.commit()
        return True
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
            if apply_migration(conn, path, version, datetime.now(UTC).isoformat()):
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


#: Database files this process observed at the migration head, by path -> file identity.
_AT_HEAD: dict[str, tuple[int, int, int, int]] = {}


def _file_identity(path: Path) -> tuple[int, int, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def ensure_migrated(dbfile: str | Path) -> None:
    """Apply pending migrations, skipping the check for an unchanged file already seen at head.

    Migration files cannot change while a process runs and other processes only advance the
    schema, so a file whose identity is unchanged since it was at head is still at head. This
    keeps per-row callers on the retrieval path from reopening the database and re-listing the
    migrations directory. Restores call `forget_migration_state`.
    """
    path = Path(dbfile)
    key = os.path.abspath(path)
    identity = _file_identity(path)
    if identity is not None and _AT_HEAD.get(key) == identity:
        return
    if pending_migrations(path):
        migrate(path)
    identity = _file_identity(path)
    if identity is not None:
        _AT_HEAD[key] = identity


def forget_migration_state() -> None:
    """Drop every cached at-head observation (after a database file is replaced in place)."""
    _AT_HEAD.clear()
