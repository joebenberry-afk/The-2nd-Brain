"""
Repository Intelligence: durable incremental symbol and dependency index.

Capabilities:
1. P2.4: Durable incremental AST, symbol, and module dependency index.
   - Preserves symbols, classes, functions, and import graphs in SQLite.
   - Incremental update: processes dirty files only based on SHA256/mtime.
"""

from __future__ import annotations

import ast
import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repo_files (
    file_path TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repo_symbols (
    symbol_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    docstring TEXT,
    PRIMARY KEY (symbol_name, file_path, line_number)
);
CREATE TABLE IF NOT EXISTS repo_dependencies (
    source_file TEXT NOT NULL,
    imported_module TEXT NOT NULL,
    imported_symbol TEXT,
    PRIMARY KEY (source_file, imported_module, imported_symbol)
);
CREATE INDEX IF NOT EXISTS idx_sym_name ON repo_symbols (symbol_name);
CREATE INDEX IF NOT EXISTS idx_dep_source ON repo_dependencies (source_file);
"""


class RepositoryIntelligence:
    """Durable AST, symbol, and dependency indexer for a repository (§3 P2.4)."""

    def __init__(self, home: Path | str, repo_root: Path | str) -> None:
        self.home = Path(home)
        self.repo_root = Path(repo_root)
        self._db_dir = self.home / "state" / "repo_intel"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._dbfile = self._db_dir / "repo_intel.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def index_incremental(self, extensions: tuple[str, ...] = (".py",)) -> dict[str, int]:
        """
        Scan repository and parse AST for dirty or newly added files only.
        """
        counts = {"scanned": 0, "indexed": 0, "skipped": 0}
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            known = {
                r["file_path"]: (r["content_sha256"], r["mtime"])
                for r in conn.execute("SELECT file_path, content_sha256, mtime FROM repo_files")
            }

            for p in self.repo_root.rglob("*"):
                if not p.is_file() or p.suffix not in extensions:
                    continue
                ignore_parts = ("node_modules", ".venv", "build", "dist")
                if any(part.startswith(".") or part in ignore_parts for part in p.parts):
                    continue

                rel_path = str(p.relative_to(self.repo_root))
                counts["scanned"] += 1
                stat = p.stat()
                mtime = stat.st_mtime

                if rel_path in known and abs(known[rel_path][1] - mtime) < 0.001:
                    counts["skipped"] += 1
                    continue

                # Hash check
                raw_bytes = p.read_bytes()
                content_sha = hashlib.sha256(raw_bytes).hexdigest()

                if rel_path in known and known[rel_path][0] == content_sha:
                    conn.execute(
                        "UPDATE repo_files SET mtime = ? WHERE file_path = ?",
                        (mtime, rel_path),
                    )
                    counts["skipped"] += 1
                    continue

                # Parse AST
                decoded = raw_bytes.decode("utf-8", errors="replace")
                self._parse_and_store_file(conn, rel_path, decoded, content_sha, mtime)
                counts["indexed"] += 1

            conn.commit()
        return counts

    def _parse_and_store_file(
        self,
        conn: sqlite3.Connection,
        rel_path: str,
        content: str,
        content_sha: str,
        mtime: float,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        conn.execute("DELETE FROM repo_symbols WHERE file_path = ?", (rel_path,))
        conn.execute("DELETE FROM repo_dependencies WHERE source_file = ?", (rel_path,))

        try:
            tree = ast.parse(content, filename=rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    doc = ast.get_docstring(node) or ""
                    conn.execute(
                        "INSERT OR REPLACE INTO repo_symbols "
                        "(symbol_name, file_path, kind, line_number, docstring) "
                        "VALUES (?, ?, 'function', ?, ?)",
                        (node.name, rel_path, node.lineno, doc[:200]),
                    )
                elif isinstance(node, ast.ClassDef):
                    doc = ast.get_docstring(node) or ""
                    conn.execute(
                        "INSERT OR REPLACE INTO repo_symbols "
                        "(symbol_name, file_path, kind, line_number, docstring) "
                        "VALUES (?, ?, 'class', ?, ?)",
                        (node.name, rel_path, node.lineno, doc[:200]),
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        conn.execute(
                            "INSERT OR IGNORE INTO repo_dependencies "
                            "(source_file, imported_module, imported_symbol) "
                            "VALUES (?, ?, '')",
                            (rel_path, alias.name),
                        )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for alias in node.names:
                        conn.execute(
                            "INSERT OR IGNORE INTO repo_dependencies "
                            "(source_file, imported_module, imported_symbol) "
                            "VALUES (?, ?, ?)",
                            (rel_path, mod, alias.name),
                        )
        except SyntaxError:
            pass  # Fail open on unparseable file

        conn.execute(
            "INSERT OR REPLACE INTO repo_files "
            "(file_path, content_sha256, mtime, indexed_at) "
            "VALUES (?, ?, ?, ?)",
            (rel_path, content_sha, mtime, now),
        )

    def find_symbol(self, symbol_name: str) -> list[dict[str, Any]]:
        """Query symbol definition locations across the repository."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM repo_symbols WHERE symbol_name = ? ORDER BY file_path",
                (symbol_name,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_file_dependencies(self, rel_path: str) -> list[dict[str, Any]]:
        """List modules/symbols imported by a file."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM repo_dependencies WHERE source_file = ?",
                (rel_path,),
            ).fetchall()
            return [dict(r) for r in rows]
