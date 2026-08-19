"""
Repository Intelligence & Driver/Worker Plane Management (Plan §3 P1.1, P1.2, P2.4, P2.6).

Capabilities:
1. P2.4: Durable incremental AST, symbol, and module dependency index.
   - Preserves symbols, classes, functions, and import graphs in SQLite.
   - Incremental update: processes dirty files only based on SHA256/mtime.
2. P1.1 / P1.2: Driver/Worker Concurrency Plane.
   - Hard-enforces worker concurrency ceiling (default max 2 concurrent workers).
   - Structured assignment packets and delta result packets.
   - Spawns recorded into session ledger.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import artifacts, telemetry
from .errors import BrainError


def _append_telemetry(home: Path, session_id: str, kind: str, payload: dict[str, Any]) -> None:
    try:
        t_dir = telemetry.telemetry_dir(home)
        t_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = (
            "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in session_id)
            or "anon"
        )
        record = {
            "v": 2,
            "kind": kind,
            "session": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
        with (t_dir / f"{safe_stem}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

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
CREATE TABLE IF NOT EXISTS worker_plane (
    worker_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    subtask TEXT NOT NULL,
    status TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    completed_at TEXT,
    result_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_sym_name ON repo_symbols (symbol_name);
CREATE INDEX IF NOT EXISTS idx_dep_source ON repo_dependencies (source_file);
CREATE INDEX IF NOT EXISTS idx_worker_status ON worker_plane (session_id, status);
"""

DEFAULT_MAX_WORKERS = 2


class WorkerStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class WorkerAssignmentPacket:
    """Minimal assignment packet for worker dispatch (§3 P1.2)."""
    worker_id: str
    session_id: str
    subtask: str
    target_files: list[str] = field(default_factory=list)
    relevant_symbols: list[str] = field(default_factory=list)
    context_capsule: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "session_id": self.session_id,
            "subtask": self.subtask,
            "target_files": self.target_files,
            "relevant_symbols": self.relevant_symbols,
            "context_capsule": self.context_capsule,
            "created_at": self.created_at,
        }


@dataclass
class WorkerResultPacket:
    """Structured result packet returned by worker to driver (§3 P1.2)."""
    worker_id: str
    session_id: str
    status: WorkerStatus
    summary: str
    findings: list[str] = field(default_factory=list)
    delta_patches: dict[str, str] = field(default_factory=dict)
    tokens_used: int = 0
    completed_at: str = ""


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


class WorkerPlaneManager:
    """Driver/Worker Plane Concurrency and Packet Broker (§3 P1.1, P1.2)."""

    def __init__(
        self,
        home: Path | str,
        session_id: str,
        max_concurrent_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        self.home = Path(home)
        self.session_id = session_id
        self.max_concurrent_workers = max_concurrent_workers
        self._dbfile = self.home / "state" / "repo_intel" / "repo_intel.sqlite"
        self._dbfile.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def active_worker_count(self) -> int:
        """Count currently running workers in this session."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM worker_plane WHERE session_id = ? AND status = ?",
                (self.session_id, WorkerStatus.RUNNING.value),
            ).fetchone()
            return int(row[0]) if row else 0

    def spawn_worker(
        self,
        subtask: str,
        *,
        target_files: list[str] | None = None,
        relevant_symbols: list[str] | None = None,
        context_capsule: str = "",
    ) -> WorkerAssignmentPacket:
        """
        Spawn a worker if under concurrency limit; raise BrainError if limit exceeded (§3 P1.1).
        """
        active = self.active_worker_count()
        if active >= self.max_concurrent_workers:
            raise BrainError(
                f"Worker concurrency ceiling reached ({active}/{self.max_concurrent_workers}). "
                "Queue or wait for running workers."
            )

        now = datetime.now(UTC).isoformat()
        digest = hashlib.sha256(f"{self.session_id}:{subtask}:{now}".encode()).hexdigest()[:12]
        worker_id = f"worker-{digest}"

        packet = WorkerAssignmentPacket(
            worker_id=worker_id,
            session_id=self.session_id,
            subtask=subtask,
            target_files=target_files or [],
            relevant_symbols=relevant_symbols or [],
            context_capsule=context_capsule,
            created_at=now,
        )

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                "INSERT INTO worker_plane "
                "(worker_id, session_id, subtask, status, assigned_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (worker_id, self.session_id, subtask, WorkerStatus.RUNNING.value, now),
            )
            conn.commit()

        # Telemetry record for worker spawn
        _append_telemetry(
            self.home,
            self.session_id,
            "worker_spawned",
            {
                "worker_id": worker_id,
                "subtask_sha": hashlib.sha256(subtask.encode()).hexdigest()[:12],
                "active_workers": active + 1,
            },
        )
        return packet

    def complete_worker(self, result: WorkerResultPacket) -> None:
        """Record worker completion and store structured findings (§3 P1.2)."""
        now = datetime.now(UTC).isoformat()
        result_json = json.dumps(
            {
                "summary": result.summary,
                "findings": result.findings,
                "delta_patches": result.delta_patches,
                "tokens_used": result.tokens_used,
            }
        )
        stored = artifacts.store_text(
            self.home, result_json, kind="worker_result", session=self.session_id
        )

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                "UPDATE worker_plane SET status = ?, completed_at = ?, result_ref = ? "
                "WHERE worker_id = ?",
                (result.status.value, now, stored["hash"], result.worker_id),
            )
            conn.commit()

        # Record worker completion in telemetry
        _append_telemetry(
            self.home,
            self.session_id,
            "worker_completed",
            {
                "worker_id": result.worker_id,
                "status": result.status.value,
                "tokens_used": result.tokens_used,
            },
        )
