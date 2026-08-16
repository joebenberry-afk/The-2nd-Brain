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
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from .security.paths import resolve_under

LEDGER_SCHEMA_VERSION = 1
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
