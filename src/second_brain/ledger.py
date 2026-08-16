"""P2 temporary session ledger (plan §9, §9.10, §11.2, §14; amendment §19).

Append-only canonical session truth for ONE host session, stored under
``state/sessions/<internal_id>/`` where ``internal_id`` is the sha256 hex of
the HOST session id (never the raw host id as a path — plan §13.1). Derived
state (manifest, FTS index) is rebuildable; the ledger itself is the source.

Invariants:
- seq is contiguous (append batches must start at max(seq)+1);
- event_id unique per session; parent_event_id must reference a known event;
- object files are content-addressed and digest-verified on read;
- schema versioning per plan §14 (refuse newer; deterministic error for
  unknown older; reading never rewrites);
- replay is independent: a fresh connection validates schema/seq/objects and
  reconstructs the lineage projection, comparing against a captured
  projection to report the FIRST divergence (plan §9.10).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import semantic
from .contracts import (
    BrainLifecycleEvent,
    BrainSessionIdentity,
    LifecycleEventType,
    RequestEpoch,
    RequestFingerprint,
    SessionSegment,
    SurfaceVisibility,
    ToolOutcome,
    canonical_json,
)
from .errors import BrainError
from .security.paths import assert_safe_recursive_delete, resolve_under

LEDGER_SCHEMA_VERSION = 1

_DEFAULT_RETENTION: dict[str, Any] = {
    "inactive_grace_minutes": 10080,
    "max_single_session_bytes": 104857600,
    "max_total_session_bytes": 1073741824,
    "auto_extract_before_purge": True,
    "preserve_pinned": True,
}


def load_retention_config(home: Path | str) -> dict[str, Any]:
    """config/session-retention.toml [retention]; absent/invalid -> defaults."""
    import tomllib

    out = dict(_DEFAULT_RETENTION)
    path = Path(home) / "config" / "session-retention.toml"
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            section = data.get("retention") or {}
            for key in out:
                if key in section and isinstance(section[key], (int, float, bool)):
                    out[key] = section[key]
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return out
LEDGER_ADAPTER_NAME = "second-brain"
LEDGER_ADAPTER_VERSION = "0.1.0"
_MANIFEST = "manifest.json"
_OBJECT_DIR = "objects"
_FTS_KEYS = ("title", "summary", "file", "symbol", "task", "decision", "tool")

# Ordered in-memory upgraders for OLD versions, keyed by the version they
# upgrade FROM. Empty stub today: any unknown old version is a deterministic
# error instead of a silent guess (§14). Reading never rewrites.
UPGRADERS: dict[int, Any] = {}

_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5("
    " event_id UNINDEXED, event_type, payload_text, tokenize = 'unicode61')"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    internal_session_id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    host_session_id TEXT NOT NULL,
    project_id TEXT,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    status TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL,
    current_segment_id TEXT,
    root_parent_session_id TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    internal_session_id TEXT NOT NULL REFERENCES sessions (internal_session_id),
    host_agent_id TEXT NOT NULL,
    parent_agent_id TEXT,
    role_profile TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    internal_session_id TEXT NOT NULL REFERENCES sessions (internal_session_id),
    agent_id TEXT REFERENCES agents (agent_id),
    parent_event_id TEXT REFERENCES events (event_id),
    host_entry_id TEXT,
    host_parent_entry_id TEXT,
    segment_id TEXT,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    surface_visibility TEXT NOT NULL,
    ignorable INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL,
    artifact_sha256 TEXT,
    source_event_ids TEXT
);
CREATE TABLE IF NOT EXISTS request_epochs (
    epoch_id TEXT PRIMARY KEY,
    internal_session_id TEXT NOT NULL REFERENCES sessions (internal_session_id),
    agent_id TEXT,
    reason TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    role_profile TEXT NOT NULL,
    system_hash TEXT NOT NULL,
    tools_hash TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    host_adapter_version TEXT NOT NULL,
    start_seq INTEGER NOT NULL,
    end_seq INTEGER
);
CREATE TABLE IF NOT EXISTS request_fingerprints (
    request_id TEXT PRIMARY KEY,
    epoch_id TEXT REFERENCES request_epochs (epoch_id),
    seq INTEGER NOT NULL,
    internal_session_id TEXT NOT NULL REFERENCES sessions (internal_session_id),
    agent_id TEXT,
    role_profile TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    system_structural_hash TEXT NOT NULL,
    tool_schema_structural_hash TEXT NOT NULL,
    message_sequence_hash TEXT NOT NULL,
    model_visible_prefix_hash TEXT NOT NULL,
    prompt_affecting_config_hash TEXT NOT NULL,
    previous_request_id TEXT,
    first_divergence_category TEXT NOT NULL,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    cache_miss_tokens INTEGER
);
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    root_session_id TEXT NOT NULL,
    agent_session_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    memory_version INTEGER NOT NULL,
    canonical_hash TEXT NOT NULL,
    packet_id TEXT NOT NULL,
    delivered_event_id TEXT NOT NULL,
    delivered_at TEXT NOT NULL,
    superseded_by_delivery_id TEXT
);
CREATE TABLE IF NOT EXISTS segments (
    segment_id TEXT PRIMARY KEY,
    internal_session_id TEXT NOT NULL REFERENCES sessions (internal_session_id),
    idx INTEGER NOT NULL,
    start_seq INTEGER NOT NULL,
    end_seq INTEGER,
    started_reason TEXT NOT NULL,
    compaction_id TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS object_refs (
    sha256 TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mime TEXT,
    role TEXT NOT NULL,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def internal_session_id(host_session_id: str) -> str:
    """sha256 hex of the host session id — the ONLY path component derived
    from a host id (plan §13.1: session identifiers are not paths)."""
    return hashlib.sha256((host_session_id or "").encode("utf-8")).hexdigest()


def session_dir(home: Path | str, host_session_id: str) -> Path:
    """Prove + return ``<home>/state/sessions/<internal_id>`` (containment)."""
    root = Path(home) / "state" / "sessions"
    internal = internal_session_id(host_session_id)
    return resolve_under(root, internal, allow_missing=True)


def _contained(session_path: Path, relative: str) -> Path:
    return resolve_under(session_path, relative, allow_missing=True)


@dataclass(frozen=True)
class ProjectedContext:
    events: list[BrainLifecycleEvent] = field(default_factory=list)
    segments: list[SessionSegment] = field(default_factory=list)
    epochs: list[RequestEpoch] = field(default_factory=list)
    fingerprints: list[RequestFingerprint] = field(default_factory=list)
    first_divergence: str | None = None


class LedgerStore:
    """Append-only ledger for one session (stdlib sqlite3; db.py pragmas)."""

    def __init__(self, home: Path | str, host_session_id: str) -> None:
        self._home = Path(home)
        self._host_session_id = host_session_id
        self._internal = internal_session_id(host_session_id)
        self._dir = session_dir(home, host_session_id)
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ----------------------------------------------------------

    @property
    def session_path(self) -> Path:
        return self._dir

    @property
    def dbfile(self) -> Path:
        return self._dir / "ledger.sqlite"

    def open(self, *, create: bool = False) -> LedgerStore:
        if create:
            self._dir.mkdir(parents=True, exist_ok=True)
        dbfile = self.dbfile
        if not dbfile.exists() and not create:
            raise BrainError(f"ledger not initialized: {self._host_session_id!r}")
        conn = sqlite3.connect(dbfile)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        self._conn = conn
        if create:
            self._init_schema()
            self._write_manifest(self._init_host_artifacts)
        else:
            self._check_version()
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> LedgerStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- schema/versioning --------------------------------------------------

    _init_host_artifacts: list[dict[str, str]] | None = None

    def _init_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_FTS_DDL)
        header = {
            "schema_version": str(LEDGER_SCHEMA_VERSION),
            "brain_version": self._brain_version(),
            "adapter_name": LEDGER_ADAPTER_NAME,
            "adapter_version": LEDGER_ADAPTER_VERSION,
            "created_at": _now(),
        }
        for key, value in header.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO ledger_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
        self._conn.commit()

    @staticmethod
    def _brain_version() -> str:
        try:
            version = (Path(__file__).resolve().parent.parent.parent / "VERSION").read_text(
                encoding="utf-8"
            ).strip()
            if version:
                return version
        except OSError:
            pass
        return "0.0.0"

    def _check_version(self) -> None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            raise BrainError("ledger missing schema_version header")
        version = int(row["value"])
        if version > LEDGER_SCHEMA_VERSION:
            raise BrainError(
                f"ledger schema version {version} requires a newer runtime "
                f"(this runtime supports up to {LEDGER_SCHEMA_VERSION})"
            )
        if version < LEDGER_SCHEMA_VERSION:
            current = dict()
            for v in range(version, LEDGER_SCHEMA_VERSION):
                upgrader = UPGRADERS.get(v)
                if upgrader is None:
                    raise BrainError(
                        f"no in-memory upgrader for ledger schema version {v}"
                    )
                current = upgrader(current)
        # reading never rewrites: no DDL/DML executed on the open path

    # -- session/agent registration -----------------------------------------

    def create_session(self, identity: BrainSessionIdentity) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (internal_session_id, host, host_session_id, "
            " project_id, created_at, last_active_at, status, pinned, schema_version, "
            " current_segment_id, root_parent_session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity.internal_session_id,
                identity.host,
                identity.host_session_id,
                identity.project_id,
                identity.created_at,
                _now(),
                identity.status,
                1 if identity.pinned else 0,
                identity.schema_version,
                identity.current_segment_id,
                identity.root_parent_session_id,
            ),
        )
        self._conn.commit()

    def register_agent(self, agent: dict[str, Any]) -> None:
        assert self._conn is not None
        self._ensure_session_row()
        self._conn.execute(
            "INSERT OR REPLACE INTO agents (agent_id, internal_session_id, host_agent_id, "
            " parent_agent_id, role_profile, model, provider, created_at, ended_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent["agent_id"],
                agent["internal_session_id"],
                agent.get("host_agent_id") or agent["agent_id"],
                agent.get("parent_agent_id"),
                agent.get("role_profile") or "worker",
                agent.get("model") or "unknown",
                agent.get("provider") or "unknown",
                agent.get("created_at") or _now(),
                agent.get("ended_at"),
            ),
        )
        self._conn.commit()

    # -- events --------------------------------------------------------------

    def _ensure_session_row(self) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions (internal_session_id, host, host_session_id, "
            " project_id, created_at, last_active_at, status, pinned, schema_version, "
            " current_segment_id, root_parent_session_id) "
            "VALUES (?, 'prime', ?, '', ?, ?, 'active', 0, ?, NULL, NULL)",
            (
                self._internal,
                self._host_session_id,
                _now(),
                _now(),
                LEDGER_SCHEMA_VERSION,
            ),
        )

    def _ensure_agent_row(self, agent_id: str | None) -> None:
        if not agent_id:
            return
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR IGNORE INTO agents (agent_id, internal_session_id, host_agent_id, "
            " parent_agent_id, role_profile, model, provider, created_at, ended_at) "
            "VALUES (?, ?, ?, NULL, 'worker', 'unknown', 'unknown', ?, NULL)",
            (agent_id, self._internal, agent_id, _now()),
        )


    def append_events(self, events: list[BrainLifecycleEvent]) -> list[int]:
        """Transactional batch append. Contiguity: batch seqs must start at
        max(seq)+1. Duplicate event_id or invalid parent ref rejects the WHOLE
        batch deterministically. Missing session/agent rows are ensured
        (INSERT OR IGNORE) so event streams never fail on FK drift."""
        assert self._conn is not None
        if not events:
            return []
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._ensure_session_row()
            for event in events:
                self._ensure_agent_row(event.agent_id)
            row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
            next_seq = int(row[0]) + 1
            for i, event in enumerate(events):
                if event.seq != next_seq + i:
                    raise BrainError(
                        f"seq contiguity violated: batch starts at {events[0].seq} "
                        f"but ledger expects {next_seq}"
                    )
            batch_ids = {event.event_id for event in events}
            for event in events:
                dup = self._conn.execute(
                    "SELECT 1 FROM events WHERE event_id = ?", (event.event_id,)
                ).fetchone()
                if dup is not None:
                    raise BrainError(f"duplicate event_id: {event.event_id!r}")
                if event.parent_event_id is not None:
                    parent_in_db = self._conn.execute(
                        "SELECT 1 FROM events WHERE event_id = ?",
                        (event.parent_event_id,),
                    ).fetchone()
                    if parent_in_db is None and event.parent_event_id not in batch_ids:
                        raise BrainError(
                            f"invalid parent_event_id: {event.parent_event_id!r}"
                        )
            seqs: list[int] = []
            for event in events:
                self._conn.execute(
                    "INSERT INTO events (seq, event_id, internal_session_id, agent_id, "
                    " parent_event_id, host_entry_id, host_parent_entry_id, segment_id, "
                    " event_type, timestamp, surface_visibility, ignorable, payload_json, "
                    " artifact_sha256, source_event_ids) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.seq,
                        event.event_id,
                        event.internal_session_id,
                        event.agent_id,
                        event.parent_event_id,
                        event.host_entry_id,
                        event.host_parent_entry_id,
                        event.segment_id,
                        event.event_type.value,
                        event.timestamp,
                        event.surface_visibility.value,
                        1 if event.ignorable else 0,
                        canonical_json(event.payload),
                        event.artifact_sha256,
                        canonical_json(event.source_event_ids),
                    ),
                )
                seqs.append(event.seq)
            for event in events:
                self._conn.execute(
                    "INSERT OR REPLACE INTO events_fts (event_id, event_type, payload_text) "
                    "VALUES (?, ?, ?)",
                    (event.event_id, event.event_type.value, _payload_fts_text(event.payload)),
                )
            self._conn.commit()
            return seqs
        except Exception:
            self._conn.rollback()
            raise

    # -- objects --------------------------------------------------------------

    def add_object(self, data: bytes, *, mime: str | None = None, role: str = "artifact") -> str:
        """Content-addressed object: file <session>/objects/<sha256> + ref row."""
        assert self._conn is not None
        digest = hashlib.sha256(data).hexdigest()
        obj_dir = self._contained_path(_OBJECT_DIR)
        obj_dir.mkdir(parents=True, exist_ok=True)
        target = _contained(self._dir, f"{_OBJECT_DIR}/{digest}")
        tmp = _contained(self._dir, f"{_OBJECT_DIR}/{digest}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        self._conn.execute(
            "INSERT OR REPLACE INTO object_refs (sha256, size, mime, role, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (digest, len(data), mime, role, _now()),
        )
        self._conn.commit()
        return digest

    def read_object(self, sha256: str) -> bytes:
        """Digest-verified read: mismatch or missing file fails LOUD."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT size FROM object_refs WHERE sha256 = ?", (sha256,)
        ).fetchone()
        if row is None:
            raise BrainError(f"object not registered: {sha256[:12]}")
        path = _contained(self._dir, f"{_OBJECT_DIR}/{sha256}")
        if not path.is_file():
            raise BrainError(f"object file missing: {sha256[:12]}")
        data = path.read_bytes()
        if len(data) != int(row["size"]) or hashlib.sha256(data).hexdigest() != sha256:
            raise BrainError(f"object digest mismatch: {sha256[:12]}")
        return data

    def _contained_path(self, relative: str) -> Path:
        return _contained(self._dir, relative)

    # -- flush / integrity -----------------------------------------------------

    def flush(self) -> None:
        """Durability barrier: commit + WAL checkpoint (PASSIVE)."""
        assert self._conn is not None
        self._conn.commit()
        self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def integrity(self) -> dict[str, Any]:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS mx, COALESCE(MIN(seq), 0) AS mn, COUNT(*) AS n "
            "FROM events"
        ).fetchone()
        n = int(row["n"])
        contiguous = n == 0 or (int(row["mn"]) == 1 and int(row["mx"]) == n)
        orphans = self._conn.execute(
            "SELECT COUNT(*) FROM events e WHERE e.parent_event_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM events p WHERE p.event_id = e.parent_event_id)"
        ).fetchone()[0]
        digest_ok = True
        bad: list[str] = []
        for obj in self._conn.execute("SELECT sha256, size FROM object_refs").fetchall():
            try:
                path = _contained(self._dir, f"{_OBJECT_DIR}/{obj['sha256']}")
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != obj["sha256"]:
                    bad.append(obj["sha256"][:12])
            except OSError:
                bad.append(obj["sha256"][:12])
        if bad:
            digest_ok = False
        version = int(
            self._conn.execute(
                "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        )
        return {
            "seq_contiguous": contiguous,
            "orphan_parents": int(orphans),
            "object_digests_ok": digest_ok,
            "object_bad": bad,
            "schema_version": version,
            "event_count": n,
        }

    # -- segments ---------------------------------------------------------------

    def open_segment(self, started_reason: str = "manual") -> str:
        """Close the prior active segment (end_seq = max seq) and open a new
        one (index+1, start_seq = max seq + 1). Returns the new segment_id."""
        assert self._conn is not None
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._ensure_session_row()
            max_seq = int(
                self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]
            )
            active = self._conn.execute(
                "SELECT segment_id FROM segments WHERE active = 1"
            ).fetchone()
            if active is not None:
                self._conn.execute(
                    "UPDATE segments SET end_seq = ?, active = 0 WHERE segment_id = ?",
                    (max_seq, active["segment_id"]),
                )
            idx = int(
                self._conn.execute("SELECT COALESCE(MAX(idx), -1) FROM segments").fetchone()[0]
            ) + 1
            segment_id = f"seg-{idx + 1}"
            self._conn.execute(
                "INSERT INTO segments (segment_id, internal_session_id, idx, start_seq, "
                " end_seq, started_reason, compaction_id, active) "
                "VALUES (?, ?, ?, ?, NULL, ?, NULL, 1)",
                (segment_id, self._internal, idx, max_seq + 1, started_reason),
            )
            self._conn.commit()
            return segment_id
        except Exception:
            self._conn.rollback()
            raise

    def close_segment(self) -> dict[str, Any] | None:
        """Close the active segment at the current max seq. Returns the closed
        segment row (or None when no segment is active)."""
        assert self._conn is not None
        max_seq = int(
            self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]
        )
        row = self._conn.execute(
            "SELECT * FROM segments WHERE active = 1"
        ).fetchone()
        if row is None:
            return None
        self._conn.execute(
            "UPDATE segments SET end_seq = ?, active = 0 WHERE segment_id = ?",
            (max_seq, row["segment_id"]),
        )
        self._conn.commit()
        updated = self._conn.execute(
            "SELECT * FROM segments WHERE segment_id = ?", (row["segment_id"],)
        ).fetchone()
        return dict(updated)

    def continuation_capsule(self) -> dict[str, Any]:
        """Continuation capsule from recent events (plan §17.5/§10.4): only
        what exists in the ledger — never fabricated."""
        assert self._conn is not None
        rows = self._conn.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 500").fetchall()
        events = [_row_to_event(r) for r in rows][::-1]
        current_task: dict[str, Any] | None = None
        for e in reversed(events):
            if e.event_type is LifecycleEventType.USER_TASK and e.payload.get("task_sha256"):
                current_task = {"task_sha256": e.payload["task_sha256"], "seq": e.seq}
                break
        decisions = [
            {
                "seq": e.seq,
                "decision": e.payload.get("decision") or e.payload.get("title"),
                "rationale": e.payload.get("rationale") or e.payload.get("guidance"),
                "event_id": e.event_id,
            }
            for e in events
            if e.event_type is LifecycleEventType.DECISION and e.payload
        ]
        contradictions = [
            {
                "seq": e.seq,
                "event_id": e.event_id,
                "note": e.payload.get("summary") or e.payload.get("decision"),
            }
            for e in events
            if e.event_type is LifecycleEventType.FINDING
            and str(e.payload.get("kind") or "").lower() == "contradiction"
        ]
        worker_status: dict[str, dict[str, Any]] = {}
        for e in events:
            if e.event_type is LifecycleEventType.WORKER_REPORT:
                worker = str(e.payload.get("worker") or e.agent_id or "unknown")
                worker_status[worker] = {
                    "seq": e.seq,
                    "summary": e.payload.get("summary") or e.payload.get("conclusion"),
                    "uncertainty": e.payload.get("uncertainty"),
                }
        segments = [
            dict(r)
            for r in self._conn.execute("SELECT * FROM segments ORDER BY idx").fetchall()
        ]
        return {
            "current_task": current_task,
            "decisions": decisions,
            "contradictions": contradictions,
            "worker_status": worker_status,
            "pointers": {
                "segments": [
                    {
                        "segment_id": s["segment_id"],
                        "start_seq": s["start_seq"],
                        "end_seq": s["end_seq"],
                        "active": bool(s["active"]),
                    }
                    for s in segments
                ],
                "artifact_count": int(
                    self._conn.execute("SELECT COUNT(*) FROM object_refs").fetchone()[0]
                ),
            },
        }

    # -- FTS --------------------------------------------------------------------

    @staticmethod
    def fts_available() -> bool:
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            conn.close()
            return True
        except sqlite3.Error:
            return False

    def reindex(self) -> dict[str, int]:
        assert self._conn is not None
        self._conn.execute("DROP TABLE IF EXISTS events_fts")
        self._conn.executescript(_FTS_DDL)
        count = 0
        for row in self._conn.execute(
            "SELECT event_id, event_type, payload_json FROM events"
        ).fetchall():
            self._conn.execute(
                "INSERT OR REPLACE INTO events_fts (event_id, event_type, payload_text) "
                "VALUES (?, ?, ?)",
                (
                    row["event_id"],
                    row["event_type"],
                    _payload_fts_text(json.loads(row["payload_json"])),
                ),
            )
            count += 1
        self._conn.commit()
        return {"indexed": count}

    def search(
        self,
        query: str,
        *,
        segment: str | None = None,
        agent: str | None = None,
        event_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        assert self._conn is not None
        filters: list[str] = []
        params: list[Any] = []
        if segment is not None:
            filters.append("e.segment_id = ?")
            params.append(segment)
        if agent is not None:
            filters.append("e.agent_id = ?")
            params.append(agent)
        if event_type is not None:
            filters.append("e.event_type = ?")
            params.append(event_type)
        base = (
            "SELECT e.seq, e.event_id, e.event_type, e.timestamp, e.segment_id, "
            " e.agent_id, e.payload_json FROM events e"
        )
        if self.fts_available():
            match = _fts_match_expr(query)
            sql = (
                f"{base} JOIN events_fts f ON f.event_id = e.event_id "
                f"WHERE events_fts MATCH ?{(' AND ' + ' AND '.join(filters)) if filters else ''} "
                f"ORDER BY e.seq LIMIT ?"
            )
            params = [match, *params, limit]
        else:
            like = f"%{query}%"
            if filters:
                sql = (
                    f"{base} WHERE {' AND '.join(filters)} "
                    f"AND (e.event_type LIKE ? OR e.payload_json LIKE ?) ORDER BY e.seq LIMIT ?"
                )
            else:
                sql = (
                    f"{base} WHERE (e.event_type LIKE ? OR e.payload_json LIKE ?) "
                    f"ORDER BY e.seq LIMIT ?"
                )
            params = [like, like, *params, limit]
        rows = self._conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d.pop("payload_json"))
            out.append(d)
        return out

    # -- replay -----------------------------------------------------------------

    def replay(self, lineage: list[str]) -> ProjectedContext:
        """Independent replay (plan §9.10): fresh-connection semantics via this
        store's own connection + validation, reconstructing the root->leaf
        lineage projection. Detects seq gaps, orphan parents, object failures,
        and payload tampering (seq/payload mismatch is detected by the
        projection hash comparison in compare_projection)."""
        assert self._conn is not None
        integrity = self.integrity()
        if not integrity["seq_contiguous"]:
            raise BrainError("replay rejected: seq not contiguous")
        if integrity["orphan_parents"]:
            raise BrainError("replay rejected: orphan parent_event_id")
        if not integrity["object_digests_ok"]:
            raise BrainError(
                f"replay rejected: object digest failures {integrity['object_bad']}"
            )
        chain = _lineage_chain(self._conn, lineage)
        rows = self._conn.execute(
            f"SELECT * FROM events WHERE event_id IN ({','.join('?' for _ in chain)}) ORDER BY seq",
            list(chain),
        ).fetchall()
        events = [_row_to_event(r) for r in rows]
        segments = [
            SessionSegment.from_dict(
                {
                    "segment_id": r["segment_id"],
                    "internal_session_id": r["internal_session_id"],
                    "index": r["idx"],
                    "start_seq": r["start_seq"],
                    "end_seq": r["end_seq"],
                    "started_reason": r["started_reason"],
                    "compaction_id": r["compaction_id"],
                    "active": bool(r["active"]),
                }
            )
            for r in self._conn.execute(
                "SELECT * FROM segments ORDER BY idx"
            ).fetchall()
        ]
        epochs = [
            RequestEpoch.from_dict(dict(r))
            for r in self._conn.execute(
                "SELECT * FROM request_epochs ORDER BY start_seq"
            ).fetchall()
        ]
        fingerprints = [
            RequestFingerprint.from_dict(dict(r))
            for r in self._conn.execute(
                "SELECT * FROM request_fingerprints ORDER BY seq"
            ).fetchall()
        ]
        return ProjectedContext(
            events=events, segments=segments, epochs=epochs, fingerprints=fingerprints
        )

    # -- header ----------------------------------------------------------------

    def header(self) -> dict[str, str]:
        assert self._conn is not None
        rows = self._conn.execute("SELECT key, value FROM ledger_meta").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def _write_manifest(self, host_artifacts: list[dict[str, str]] | None = None) -> None:
        manifest = {
            "internal_id": self._internal,
            "host": "prime",
            "host_session_id": self._host_session_id,
            "created_at": _now(),
            "schema_version": LEDGER_SCHEMA_VERSION,
            "db": "ledger.sqlite",
            "host_artifacts": host_artifacts or [],
        }
        target = _contained(self._dir, _MANIFEST)
        tmp = _contained(self._dir, f"{_MANIFEST}.tmp")
        tmp.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
        os.replace(tmp, target)


def replay_session(home: Path | str, host_session_id: str, lineage: list[str]) -> ProjectedContext:
    """Open fresh + replay. Independent of any live in-memory projection."""
    with LedgerStore(home, host_session_id).open() as store:
        return store.replay(lineage)


def compare_projection(captured: ProjectedContext, replayed: ProjectedContext) -> str | None:
    """First divergence between a captured and a replayed projection (plan
    §9.10): compare event streams in seq order by (event_id, payload hash,
    parent). Returns a description or None when identical."""
    a = captured.events
    b = replayed.events
    if len(a) != len(b):
        return f"event count differs: captured {len(a)} vs replayed {len(b)}"
    for _i, (ea, eb) in enumerate(zip(a, b, strict=True)):
        if ea.event_id != eb.event_id:
            return f"first divergence at seq {ea.seq}: event_id {ea.event_id!r} != {eb.event_id!r}"
        if ea.parent_event_id != eb.parent_event_id:
            return (
                f"first divergence at seq {ea.seq}: parent {ea.parent_event_id!r} "
                f"!= {eb.parent_event_id!r}"
            )
        if canonical_json(ea.payload) != canonical_json(eb.payload):
            return f"first divergence at seq {ea.seq}: payload differs"
    if [s.segment_id for s in captured.segments] != [s.segment_id for s in replayed.segments]:
        return "first divergence: segments differ"
    return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _payload_fts_text(payload: dict[str, Any]) -> str:
    parts = [str(v) for k, v in payload.items() if k in _FTS_KEYS and v is not None]
    return " ".join(parts)


def _fts_match_expr(query: str) -> str:
    tokens = [t for t in query.lower().split() if t]
    return " AND ".join(f'"{t}"*' for t in tokens) if tokens else '""'


def _row_to_event(row: sqlite3.Row) -> BrainLifecycleEvent:
    return BrainLifecycleEvent(
        seq=int(row["seq"]),
        event_id=row["event_id"],
        internal_session_id=row["internal_session_id"],
        agent_id=row["agent_id"],
        parent_event_id=row["parent_event_id"],
        host_entry_id=row["host_entry_id"],
        host_parent_entry_id=row["host_parent_entry_id"],
        segment_id=row["segment_id"],
        event_type=LifecycleEventType(row["event_type"]),
        timestamp=row["timestamp"],
        surface_visibility=SurfaceVisibility(row["surface_visibility"]),
        ignorable=bool(row["ignorable"]),
        payload=json.loads(row["payload_json"]),
        artifact_sha256=row["artifact_sha256"],
        source_event_ids=json.loads(row["source_event_ids"]) if row["source_event_ids"] else [],
    )


def _lineage_chain(conn: sqlite3.Connection, lineage: list[str]) -> list[str]:
    """Walk parent_event_id pointers from the lineage leaf back to the root;
    returns the chain (root->leaf). Raises on a broken pointer."""
    chain: list[str] = []
    if not lineage:
        return chain
    current = lineage[-1]
    seen: set[str] = set()
    while current is not None:
        if current in seen:
            raise BrainError("replay rejected: parent cycle")
        seen.add(current)
        chain.append(current)
        row = conn.execute(
            "SELECT parent_event_id FROM events WHERE event_id = ?", (current,)
        ).fetchone()
        if row is None:
            raise BrainError(f"replay rejected: lineage event missing {current!r}")
        current = row["parent_event_id"]
    chain.reverse()
    return chain


def classify_tool_outcome(events: Iterable[BrainLifecycleEvent]) -> dict[str, dict[str, Any]]:
    """Plan §11.2 tool crash states per tool-call id.

    REQUESTED + no TOOL_STARTED -> TOOL_NOT_STARTED
    TOOL_STARTED  + no result    -> TOOL_OUTCOME_UNKNOWN (verify-before-retry)
    TOOL_STARTED  + result       -> COMPLETE
    """
    per_tool: dict[str, dict[str, Any]] = {}
    for event in events:
        tool_id = str(event.payload.get("tool_call_id") or event.payload.get("tool") or "")
        if not tool_id:
            continue
        entry = per_tool.setdefault(
            tool_id, {"state": ToolOutcome.REQUESTED, "started": False, "result": False}
        )
        if event.event_type is LifecycleEventType.TOOL_REQUESTED:
            entry["state"] = ToolOutcome.REQUESTED
        elif event.event_type is LifecycleEventType.TOOL_STARTED:
            entry["started"] = True
        elif event.event_type is LifecycleEventType.TOOL_COMPLETED:
            entry["result"] = True
    out: dict[str, dict[str, Any]] = {}
    for tool_id, entry in per_tool.items():
        if entry["result"]:
            state = ToolOutcome.COMPLETE
        elif entry["started"]:
            state = ToolOutcome.TOOL_OUTCOME_UNKNOWN
        else:
            state = ToolOutcome.TOOL_NOT_STARTED
        guidance = ""
        if state is ToolOutcome.TOOL_OUTCOME_UNKNOWN:
            guidance = (
                "The tool began, but no durable result was recorded. "
                "Its external outcome is unknown. Do not blindly retry a "
                "side-effectful operation. Verify external state first."
            )
        elif state is ToolOutcome.TOOL_NOT_STARTED:
            guidance = (
                "Tool call was requested but no durable start was recorded. "
                "Retry only if it is still needed."
            )
        out[tool_id] = {"state": state.value, "guidance": guidance}
    return out

# ---------------------------------------------------------------------------
# Segments, checkpoint barrier, continuation capsule, rehydration (plan
# §10.2/§10.3/§17.5, amendment §19.4; Phase G/T-G4).
# ---------------------------------------------------------------------------


def _rehydration_id(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


class SegmentError(BrainError):
    """Segment lifecycle violation."""


class LedgerRehydrator:
    """Level 1-4 rehydration with stable rehydration_id dedupe."""

    def __init__(self, store: LedgerStore) -> None:
        self._store = store
        self._seen: set[str] = set()

    def rehydrate(
        self,
        level: int,
        *,
        segment: str | None = None,
        decision: str | None = None,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> dict[str, Any]:
        store = self._store
        assert store._conn is not None
        segments = [
            dict(r)
            for r in store._conn.execute("SELECT * FROM segments ORDER BY idx").fetchall()
        ]
        event_where: list[str] = []
        params: list[Any] = []
        if segment is not None:
            event_where.append("segment_id = ?")
            params.append(segment)
        if from_seq is not None:
            event_where.append("seq >= ?")
            params.append(from_seq)
        if to_seq is not None:
            event_where.append("seq <= ?")
            params.append(to_seq)
        where = f" WHERE {' AND '.join(event_where)}" if event_where else ""
        rows = store._conn.execute(
            f"SELECT * FROM events{where} ORDER BY seq", params
        ).fetchall()
        events = [_row_to_event(r) for r in rows]

        if level == 1:
            content: dict[str, Any] = {
                "level": 1,
                "pointer": {
                    "session": store._host_session_id,
                    "segments": [
                        {
                            "segment_id": s["segment_id"],
                            "index": s["idx"],
                            "start_seq": s["start_seq"],
                            "end_seq": s["end_seq"],
                            "active": bool(s["active"]),
                        }
                        for s in segments
                    ],
                    "event_range": (
                        {"from": events[0].seq, "to": events[-1].seq} if events else None
                    ),
                },
                "citation": f"segments/{segment or 'all'}/events",
            }
        elif level == 2:
            decisions = [
                e
                for e in events
                if e.event_type
                in (LifecycleEventType.DECISION, LifecycleEventType.FINDING)
                and (decision is None or e.event_id == decision)
            ]
            content = {
                "level": 2,
                "evidence_packets": [
                    {
                        "event_id": e.event_id,
                        "seq": e.seq,
                        "decision": e.payload.get("decision")
                        or e.payload.get("title")
                        or e.payload.get("summary"),
                        "rationale": e.payload.get("rationale")
                        or e.payload.get("guidance")
                        or e.payload.get("observation"),
                        "evidence_refs": e.source_event_ids or [],
                        "segment_id": e.segment_id,
                    }
                    for e in decisions
                ],
            }
        elif level == 3:
            artifacts: list[dict[str, Any]] = []
            for e in events:
                if not e.artifact_sha256:
                    continue
                try:
                    data = store.read_object(e.artifact_sha256)
                    artifacts.append(
                        {
                            "event_id": e.event_id,
                            "sha256": e.artifact_sha256,
                            "size": len(data),
                            "excerpt": data[:2000].decode("utf-8", errors="replace"),
                            "digest_verified": True,
                        }
                    )
                except BrainError as exc:
                    artifacts.append(
                        {
                            "event_id": e.event_id,
                            "sha256": e.artifact_sha256,
                            "digest_verified": False,
                            "error": str(exc),
                        }
                    )
            content = {
                "level": 3,
                "events": [
                    {
                        "seq": e.seq,
                        "event_id": e.event_id,
                        "event_type": e.event_type.value,
                        "timestamp": e.timestamp,
                        "segment_id": e.segment_id,
                        "agent_id": e.agent_id,
                        "parent_event_id": e.parent_event_id,
                        "payload": e.payload,
                        "source_event_ids": e.source_event_ids,
                    }
                    for e in events
                ],
                "artifacts": artifacts,
            }
        elif level == 4:
            content = {
                "level": 4,
                "session": store._host_session_id,
                "segments": segments,
                "agents": [
                    dict(r)
                    for r in store._conn.execute(
                        "SELECT * FROM agents ORDER BY created_at"
                    ).fetchall()
                ],
                "epochs": [
                    dict(r)
                    for r in store._conn.execute(
                        "SELECT * FROM request_epochs ORDER BY start_seq"
                    ).fetchall()
                ],
                "events": [
                    {
                        "seq": e.seq,
                        "event_id": e.event_id,
                        "event_type": e.event_type.value,
                        "timestamp": e.timestamp,
                        "segment_id": e.segment_id,
                        "agent_id": e.agent_id,
                        "parent_event_id": e.parent_event_id,
                        "surface_visibility": e.surface_visibility.value,
                        "ignorable": e.ignorable,
                        "payload": e.payload,
                        "artifact_sha256": e.artifact_sha256,
                        "source_event_ids": e.source_event_ids,
                    }
                    for e in events
                ],
            }
        else:
            raise BrainError(f"unknown rehydration level: {level}")

        rid = _rehydration_id(content)
        if rid in self._seen or rid in self._manifest_rehydrations():
            return {"rehydration_id": rid, "deduplicated": True}
        self._seen.add(rid)
        self._note_rehydration(rid)
        content["rehydration_id"] = rid
        return content

    def _manifest_rehydrations(self) -> set[str]:
        try:
            manifest = json.loads(
                (self._store.session_path / "manifest.json").read_text(encoding="utf-8")
            )
            return set(manifest.get("rehydrations", []))
        except (OSError, ValueError):
            return set()

    def _note_rehydration(self, rid: str) -> None:
        try:
            path = self._store.session_path / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            ids = list(manifest.get("rehydrations", []))
            ids.append(rid)
            manifest["rehydrations"] = ids[-100:]
            tmp = self._store.session_path / "manifest.json.tmp"
            tmp.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except (OSError, ValueError):
            pass  # dedupe note is best-effort; in-memory set still guards


def checkpoint_ledger(store: LedgerStore) -> dict[str, Any]:
    """Pre-compaction durability barrier (plan §10.2): flush + integrity.
    Returns {ok, integrity, closed_segment?}. Never raises."""
    try:
        store.flush()
        integrity = store.integrity()
        ok = bool(
            integrity["seq_contiguous"]
            and integrity["orphan_parents"] == 0
            and integrity["object_digests_ok"]
        )
        return {"ok": ok, "durability": "flushed", "integrity": integrity}
    except Exception as exc:  # fail open to a failure flag, never raise
        return {"ok": False, "durability": "failed", "error": str(exc)}

# ---------------------------------------------------------------------------
# Session lifecycle: crash recovery, retention, finalization, purge
# (plan §11.3, §12, §13.3, §17.6/§17.7; amendment §19.4; Phase G/T-G5).
# ---------------------------------------------------------------------------

SESSION_STATUSES = (
    "active",
    "inactive_grace",
    "finalizing",
    "extracted",
    "purged",
    "degraded",
)
# Allowed transitions (order + special cases); PINNED is the sessions.pinned
# flag, orthogonal to status.
_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "active": ("inactive_grace", "finalizing", "degraded"),
    "inactive_grace": ("finalizing", "active", "degraded"),
    "finalizing": ("extracted", "active", "degraded"),
    "extracted": ("purged",),
    "degraded": ("active", "inactive_grace", "finalizing"),
}


class SessionLifecycleError(BrainError):
    """Invalid session status transition or purge precondition."""


def _load_manifest(session_path: Path) -> dict[str, Any]:
    try:
        return json.loads((session_path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BrainError(f"manifest unreadable for {session_path.name}: {exc}") from exc


def _write_manifest_status(session_path: Path, status: str) -> None:
    manifest = _load_manifest(session_path)
    manifest["status"] = status
    tmp = session_path / "manifest.json.tmp"
    tmp.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    os.replace(tmp, session_path / "manifest.json")


def _write_manifest_pinned(session_path: Path, pinned: bool) -> None:
    manifest = _load_manifest(session_path)
    manifest["pinned"] = pinned
    tmp = session_path / "manifest.json.tmp"
    tmp.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    os.replace(tmp, session_path / "manifest.json")


class SessionLifecycle:
    """Recovery + retention + finalization + purge for one session ledger."""

    def __init__(self, home: Path | str, host_session_id: str) -> None:
        self._home = Path(home)
        self._host_session_id = host_session_id
        self._internal = internal_session_id(host_session_id)
        self._dir = session_dir(home, host_session_id)

    @property
    def session_path(self) -> Path:
        return self._dir

    # -- status -------------------------------------------------------------

    def mark_status(self, status: str) -> None:
        if status not in SESSION_STATUSES:
            raise SessionLifecycleError(f"unknown session status {status!r}")
        current = self.status()
        if status != current and status not in _STATUS_TRANSITIONS.get(current, ()):
            raise SessionLifecycleError(
                f"invalid transition {current!r} -> {status!r}"
            )
        with LedgerStore(self._home, self._host_session_id).open() as store:
            assert store._conn is not None
            store._conn.execute(
                "UPDATE sessions SET status = ? WHERE internal_session_id = ?",
                (status, self._internal),
            )
            store._conn.commit()
        _write_manifest_status(self._dir, status)

    def status(self) -> str:
        manifest = _load_manifest(self._dir)
        return str(manifest.get("status") or "active")

    def pin(self, pinned: bool) -> None:
        with LedgerStore(self._home, self._host_session_id).open() as store:
            assert store._conn is not None
            store._conn.execute(
                "UPDATE sessions SET pinned = ? WHERE internal_session_id = ?",
                (1 if pinned else 0, self._internal),
            )
            store._conn.commit()
        _write_manifest_pinned(self._dir, pinned)

    def is_pinned(self) -> bool:
        return bool(_load_manifest(self._dir).get("pinned"))

    # -- crash recovery (plan §11.3, §17.6) ---------------------------------

    def recover_report(self) -> dict[str, Any]:
        """Detect interrupted compaction brackets, unclosed segments, and
        tool crash states; append ONE recovery finding event when an
        interrupted compaction is found. Returns the report (no fabrication).
        """
        with LedgerStore(self._home, self._host_session_id).open() as store:
            assert store._conn is not None
            rows = store._conn.execute(
                "SELECT * FROM events ORDER BY seq"
            ).fetchall()
            events = [_row_to_event(r) for r in rows]
            starts = [e for e in events if e.event_type is LifecycleEventType.COMPACTION_STARTED]
            completions = {
                e.parent_event_id
                for e in events
                if e.event_type is LifecycleEventType.COMPACTION_COMPLETED
            }
            closed_by_recovery = {
                e.parent_event_id
                for e in events
                if e.event_type is LifecycleEventType.FINDING
                and str(e.payload.get("kind") or "") == "recovery"
            }
            unclosed = [
                e
                for e in starts
                if e.event_id not in completions and e.event_id not in closed_by_recovery
            ]
            unclosed_segments = [
                dict(r)
                for r in store._conn.execute(
                    "SELECT * FROM segments WHERE active = 1"
                ).fetchall()
            ]
            tools = classify_tool_outcome(events)
            outcome_unknown = [
                {"tool": t, "guidance": d["guidance"]}
                for t, d in tools.items()
                if d["state"] == ToolOutcome.TOOL_OUTCOME_UNKNOWN.value
            ]
            not_started = [
                {"tool": t, "guidance": d["guidance"]}
                for t, d in tools.items()
                if d["state"] == ToolOutcome.TOOL_NOT_STARTED.value
            ]
            wal_exists = (self._dir / "ledger.sqlite-wal").is_file()
            if unclosed:
                # explicit recovery event (plan §11.3)
                next_seq = int(
                    store._conn.execute(
                        "SELECT COALESCE(MAX(seq), 0) FROM events"
                    ).fetchone()[0]
                ) + 1
                store.append_events(
                    [
                        BrainLifecycleEvent(
                            seq=next_seq,
                            event_id=f"recovery-{_now()}",
                            internal_session_id=self._internal,
                            agent_id="unknown",
                            parent_event_id=unclosed[-1].event_id,
                            event_type=LifecycleEventType.FINDING,
                            timestamp=_now(),
                            surface_visibility=SurfaceVisibility.RAW_ONLY,
                            ignorable=False,
                            payload={
                                "kind": "recovery",
                                "note": f"interrupted compaction {unclosed[-1].event_id}",
                            },
                        )
                    ]
                )
            return {
                "unclosed_compaction": [e.event_id for e in unclosed],
                "unclosed_segments": [s["segment_id"] for s in unclosed_segments],
                "tool_outcome_unknown": outcome_unknown,
                "tool_not_started": not_started,
                "wal_recovered": wal_exists,
            }

    # -- finalization/extraction (plan §12.2) --------------------------------

    def extract_durable(self, *, project_id: str | None = None) -> list[str]:
        """Writeback-style durable extraction: create CANDIDATE memories from
        continuation-capsule decisions/findings ONLY (never raw events), with
        provenance pointers. Returns memory ids; raises on failure (caller
        must verify before purge)."""
        with LedgerStore(self._home, self._host_session_id).open() as store:
            assert store._conn is not None
            capsule = store.continuation_capsule()
        created: list[str] = []
        for decision in capsule.get("decisions", []):
            title = str(decision.get("decision") or "Extracted decision")
            body = str(decision.get("rationale") or title)
            if not title.strip() or (
                title == "Extracted decision" and not decision.get("decision")
            ):
                continue
            mid = semantic.add_memory(
                self._home,
                title[:200],
                body[:2000],
                scope="project",
                project_id=project_id or "default",
                grade="OBSERVED",
                sources=[
                    {"ref": f"session:{self._host_session_id}", "kind": "episode"},
                    {"ref": f"ledger:{decision.get('event_id')}", "kind": "evidence"},
                ],
                summary="Extracted at session finalization (plan §12.2)",
            )
            created.append(mid)
        return created

    # -- purge (plan §13.3/§13.4, §17.7) -------------------------------------

    def purge(
        self,
        *,
        inactive: bool = False,
        dry_run: bool = False,
        retention: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        retention = retention or {}
        auto_extract = bool(retention.get("auto_extract_before_purge", True))
        preserve_pinned = bool(retention.get("preserve_pinned", True))

        if not self._dir.is_dir():
            raise SessionLifecycleError(f"session ledger missing: {self._host_session_id!r}")
        manifest = _load_manifest(self._dir)
        if manifest.get("internal_id") != self._internal:
            raise SessionLifecycleError("manifest identity mismatch: refusing purge")
        if manifest.get("host_session_id") != self._host_session_id:
            raise SessionLifecycleError("manifest host identity mismatch: refusing purge")
        status = self.status()
        pinned = self.is_pinned()
        if preserve_pinned and pinned:
            raise SessionLifecycleError("pinned session: refusing purge")
        allowed = status in ("finalizing", "extracted") or (inactive and status == "inactive_grace")
        if not allowed:
            raise SessionLifecycleError(
                f"session status {status!r} not purgeable (need finalizing/extracted or --inactive)"
            )

        extracted_ids: list[str] = []
        if auto_extract and status != "extracted":
            if dry_run:
                return {
                    "dry_run": True,
                    "action": "extract+purge",
                    "status": status,
                    "extract": True,
                    "reason": "auto_extract_before_purge",
                }
            if status in ("active", "inactive_grace"):
                self.mark_status("finalizing")  # state machine path to extraction
            try:
                extracted_ids = self.extract_durable()
            except Exception as exc:  # extraction failure must block purge
                raise SessionLifecycleError(
                    f"extraction failed ({exc}); refusing purge"
                ) from exc
            if not extracted_ids and self._has_decisions():
                raise SessionLifecycleError("extraction produced no memories: refusing purge")
            self.mark_status("extracted")

        if dry_run:
            return {
                "dry_run": True,
                "action": "purge",
                "status": status,
                "extracted": extracted_ids,
            }

        # safety (plan §13.3): strict containment + identity + symlink policy
        target = assert_safe_recursive_delete(
            self._dir,
            required_parent=self._home / "state" / "sessions",
            forbidden_roots=(self._home,),
            expected_name=self._internal,
        )
        shutil.rmtree(target)

        receipt_id = f"purge-{_now()}"
        self._write_receipt(
            receipt_id,
            status_before=status,
            extracted_ids=extracted_ids,
            reason="retention" if not inactive else "user-inactive",
        )
        return {
            "purged": self._host_session_id,
            "receipt_id": receipt_id,
            "extracted_memory_ids": extracted_ids,
        }

    def _has_decisions(self) -> bool:
        try:
            with LedgerStore(self._home, self._host_session_id).open() as store:
                assert store._conn is not None
                row = store._conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type IN ('decision', 'finding')"
                ).fetchone()
                return int(row[0]) > 0
        except BrainError:
            return False

    def _write_receipt(
        self, receipt_id: str, *, status_before: str, extracted_ids: list[str], reason: str
    ) -> None:
        from . import db as db_mod

        home_path = Path(self._home)
        db_mod.migrate(db_mod.db_path(home_path))
        conn = db_mod.connect(db_mod.db_path(home_path))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO purge_receipts (receipt_id, internal_session_id, "
                " host_session_id, status_before, extracted_memory_ids, purged_at, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt_id,
                    self._internal,
                    self._host_session_id,
                    status_before,
                    canonical_json(extracted_ids),
                    _now(),
                    reason,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def list_sessions(home: Path | str) -> list[dict[str, Any]]:
    """All session ledgers from manifests + canonical purge receipts."""
    from . import db as db_mod

    root = Path(home) / "state" / "sessions"
    out: list[dict[str, Any]] = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not (child / "manifest.json").is_file():
                continue
            try:
                manifest = _load_manifest(child)
            except BrainError:
                continue
            out.append(
                {
                    "host_session_id": manifest.get("host_session_id"),
                    "internal_id": manifest.get("internal_id"),
                    "status": manifest.get("status") or "active",
                    "pinned": bool(manifest.get("pinned")),
                    "created_at": manifest.get("created_at"),
                }
            )
    try:
        home_path = Path(home)
        db_mod.migrate(db_mod.db_path(home_path))
        conn = db_mod.connect(db_mod.db_path(home_path), readonly=True)
        try:
            for r in conn.execute(
                "SELECT host_session_id, internal_session_id, status_before, purged_at, "
                " extracted_memory_ids FROM purge_receipts ORDER BY purged_at"
            ).fetchall():
                out.append(
                    {
                        "host_session_id": r["host_session_id"],
                        "internal_id": r["internal_session_id"],
                        "status": "purged",
                        "pinned": False,
                        "created_at": r["purged_at"],
                        "purged": True,
                        "status_before": r["status_before"],
                        "extracted_memory_ids": json.loads(r["extracted_memory_ids"]),
                    }
                )
        finally:
            conn.close()
    except BrainError:
        pass
    return out


def select_oldest_inactive_unpinned(home: Path | str) -> str | None:
    """Storage pressure (plan §17.7): oldest inactive_grace, unpinned session."""
    candidates = [
        s
        for s in list_sessions(home)
        if s.get("status") == "inactive_grace" and not s.get("pinned") and s.get("host_session_id")
    ]
    candidates.sort(key=lambda s: s.get("created_at") or "")
    return candidates[0]["host_session_id"] if candidates else None
