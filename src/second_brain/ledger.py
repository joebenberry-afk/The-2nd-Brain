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

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import artifacts, db, semantic
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

LEDGER_SCHEMA_VERSION = 2

# T6.3 hash chain: fixed seed for the first event's prev_hash (64 zero hex
# chars — no prior row exists to derive from).
_GENESIS_HASH = "0" * 64

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
_CHAIN_ORIGIN_KEY = "hash_chain_origin"
_FTS_KEYS = ("title", "summary", "file", "symbol", "task", "task_sha256", "decision", "tool")


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
    source_event_ids TEXT,
    prev_hash TEXT
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


def _sql_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@lru_cache(maxsize=1)
def _ledger_table_shapes() -> dict[str, tuple[tuple, tuple]]:
    """Derive validation from the one owned DDL, not a second schema definition."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA)
        names = [
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        return {
            name: (
                tuple(conn.execute(f"PRAGMA table_info({_sql_name(name)})")),
                tuple(conn.execute(f"PRAGMA foreign_key_list({_sql_name(name)})")),
            )
            for name in names
        }
    finally:
        conn.close()


def _legacy_history_fingerprint(conn: sqlite3.Connection) -> str:
    """Bind original storage classes and bytes, excluding only the new chain column."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(events)") if row[1] != "prev_hash"]
    digest = hashlib.sha256(json.dumps(columns, separators=(",", ":")).encode("utf-8"))
    projection = ",".join(
        f"typeof({_sql_name(name)}),CAST({_sql_name(name)} AS BLOB)" for name in columns
    )
    for row in conn.execute(f"SELECT {projection} FROM events ORDER BY seq"):
        digest.update(b"row:")
        for index in range(0, len(row), 2):
            value = row[index + 1] or b""
            digest.update(
                row[index].encode("utf-8") + b":" + str(len(value)).encode() + b":" + value
            )
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def internal_session_id(host_session_id: str) -> str:
    """Sha256 hex of the host session id — the ONLY path component derived from a host
    id (plan §13.1: session identifiers are not paths)."""
    return hashlib.sha256((host_session_id or "").encode("utf-8")).hexdigest()


def _is_internal_session_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _resolve_under_retry(root: Path, relative: str) -> Path:
    """resolve_under with a bounded retry for the FIRST-INIT RACE.

    Reproduced under concurrent init of a brand-new session ledger: the
    session directory appears (created by a sibling process) between the
    existence check and the Windows path resolution, and the transient
    handle-open failure surfaces as an OSError-wrapped ValueError. Retrying
    a few times with a short delay lets the sibling finish; the failure is
    otherwise deterministic (bounded, never silent).
    """
    last: BaseException | None = None
    for _attempt in range(3):
        try:
            return resolve_under(root, relative, allow_missing=True)
        except (ValueError, OSError) as exc:
            last = exc
            time.sleep(0.1)
    raise last  # type: ignore[misc]


def session_dir(home: Path | str, host_session_id: str) -> Path:
    """Prove + return ``<home>/state/sessions/<internal_id>`` (containment)."""
    root = Path(home) / "state" / "sessions"
    internal = internal_session_id(host_session_id)
    return _resolve_under_retry(root, internal)


def resolve_root_parent_session_id(home: Path | str, parent_host_session_id: str) -> str:
    """Resolve a HOST parent to its canonical internal root without writes."""
    if not parent_host_session_id:
        raise BrainError("parent host session id must not be empty")
    parent_internal = internal_session_id(parent_host_session_id)
    dbfile = _resolve_under_retry(session_dir(home, parent_host_session_id), "ledger.sqlite")
    if not dbfile.is_file():
        raise BrainError(f"parent ledger not initialized for {parent_host_session_id!r}")
    try:
        conn = sqlite3.connect(f"{dbfile.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT host_session_id, root_parent_session_id "
                "FROM sessions WHERE internal_session_id = ?",
                (parent_internal,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BrainError(f"parent ledger unreadable for {parent_host_session_id!r}: {exc}") from exc
    if row is None or row["host_session_id"] != parent_host_session_id:
        raise BrainError(f"parent ledger is not owned by host session {parent_host_session_id!r}")
    root = row["root_parent_session_id"]
    if root is None:
        return parent_internal
    if not _is_internal_session_id(root):
        raise BrainError(f"parent ledger has invalid canonical root for {parent_host_session_id!r}")
    return root


def _contained(session_path: Path, relative: str) -> Path:
    return _resolve_under_retry(session_path, relative)


@dataclass(frozen=True)
class ProjectedContext:
    events: list[BrainLifecycleEvent] = field(default_factory=list)
    segments: list[SessionSegment] = field(default_factory=list)
    epochs: list[RequestEpoch] = field(default_factory=list)
    fingerprints: list[RequestFingerprint] = field(default_factory=list)
    first_divergence: str | None = None


class LedgerStore:
    """Append-only ledger for one session (stdlib sqlite3; db.py pragmas)."""

    def __init__(self, home: Path | str, host_session_id: str, *, host: str | None = None) -> None:
        self._home = Path(home)
        self._host_session_id = host_session_id
        self._internal = internal_session_id(host_session_id)
        self._dir = session_dir(home, host_session_id)
        self._conn: sqlite3.Connection | None = None
        self._host = host

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
        conn = sqlite3.connect(dbfile, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # P3-E fix (burst resilience): busy_timeout must be in effect BEFORE
        # any other statement — under a spawn burst, concurrent first-open of
        # a fresh ledger observed "database is locked" here. Ordinary
        # statements then wait instead of failing (P3 §24.8: zero recurrence
        # of ledger error classes).
        conn.execute("PRAGMA busy_timeout=5000")
        # journal_mode=WAL is a schema-level change sqlite does NOT reliably
        # subject to the busy handler (reproduced: OperationalError 'database
        # is locked' on concurrent init of the same fresh ledger). Bounded
        # retry keeps first-init atomic without a lock service.
        journal_error: sqlite3.OperationalError | None = None
        for _attempt in range(3):
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                journal_error = exc
                time.sleep(0.1)
        else:
            raise journal_error  # type: ignore[misc]
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._conn = conn
        try:
            if create:
                self._init_schema()
            else:
                self._check_version()
            if create or self._migration_manifest_pending():
                self._write_manifest(self._init_host_artifacts)
            return self
        except BaseException:
            self.close()
            raise

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
        self._prepare_schema(create=True)

    @staticmethod
    def _brain_version() -> str:
        try:
            version = (
                (Path(__file__).resolve().parent.parent.parent / "VERSION")
                .read_text(encoding="utf-8")
                .strip()
            )
            if version:
                return version
        except OSError:
            pass
        return "0.0.0"

    def _check_version(self) -> None:
        self._prepare_schema(create=False)

    def _schema_state(self) -> str:
        assert self._conn is not None
        tables = {
            row[0]: row[1]
            for row in self._conn.execute(
                "SELECT name,type FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        shapes = _ledger_table_shapes()
        header = None
        if tables.get("ledger_meta") == "table":
            meta_columns = tuple(
                tuple(row) for row in self._conn.execute("PRAGMA table_info(ledger_meta)")
            )
            if meta_columns != shapes["ledger_meta"][0]:
                raise BrainError("ledger schema unsupported: malformed application metadata")
            header = self._conn.execute(
                "SELECT value FROM ledger_meta WHERE key='schema_version'"
            ).fetchone()
        if header is None:
            unknown = set(tables) - set(shapes)
            unknown = {name for name in unknown if not name.startswith(("sqlite_", "events_fts"))}
            if unknown:
                raise BrainError("ledger schema unsupported: unidentified existing tables")
            for name in set(tables) & set(shapes):
                if self._conn.execute(f"SELECT 1 FROM {_sql_name(name)} LIMIT 1").fetchone():
                    raise BrainError("ledger missing schema_version header with existing data")
            return "uninitialized"
        try:
            version = int(header[0])
        except (TypeError, ValueError) as exc:
            raise BrainError("ledger schema version is malformed") from exc
        if version not in (1, LEDGER_SCHEMA_VERSION):
            raise BrainError(
                f"ledger schema {version} unsupported; runtime requires {LEDGER_SCHEMA_VERSION}"
            )
        current = legacy = True
        for name, (columns, foreign_keys) in shapes.items():
            actual = (
                tuple(
                    tuple(row)
                    for row in self._conn.execute(f"PRAGMA table_info({_sql_name(name)})")
                ),
                tuple(
                    tuple(row)
                    for row in self._conn.execute(f"PRAGMA foreign_key_list({_sql_name(name)})")
                ),
            )
            current = current and tables.get(name) == "table" and actual == (columns, foreign_keys)
            prior_columns = tuple(
                row for row in columns if not (name == "events" and row[1] == "prev_hash")
            )
            legacy = (
                legacy and tables.get(name) == "table" and actual == (prior_columns, foreign_keys)
            )
        if current and version == LEDGER_SCHEMA_VERSION:
            malformed = self._conn.execute(
                "SELECT seq FROM events WHERE typeof(prev_hash) != 'text' "
                "OR length(prev_hash) != 64 OR prev_hash GLOB '*[^0-9a-f]*' LIMIT 1"
            ).fetchone()
            if malformed is not None:
                raise BrainError("ledger hash chain is missing or malformed; refusing repair")
            self._chain_origin()
            return "current"
        if legacy:
            recorded_integrity = self._conn.execute(
                "SELECT key FROM ledger_meta WHERE key IN (?, 'last_verified_seq')",
                (_CHAIN_ORIGIN_KEY,),
            ).fetchone()
            triggers = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchone()
            if recorded_integrity is not None or triggers is not None:
                raise BrainError(
                    "ledger legacy transition unsupported: existing integrity state or triggers"
                )
            return "legacy"
        raise BrainError(
            f"ledger schema {version} has an unsupported layout; preserve it before maintenance"
        )

    @staticmethod
    def _valid_chain_hash(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value)
        )

    def _prepare_schema(self, *, create: bool) -> None:
        assert self._conn is not None
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # Inspect one stable schema under the existing SQLite writer lock.
            state = self._schema_state()
            if state == "legacy":
                self._migrate_legacy_chain()
            elif state == "uninitialized":
                if not create:
                    raise BrainError("ledger not initialized (schema not ready)")
                for statement in db.split_statements(_SCHEMA):
                    self._conn.execute(statement)
                self._conn.execute(_FTS_DDL)
                header = {
                    "schema_version": str(LEDGER_SCHEMA_VERSION),
                    "brain_version": self._brain_version(),
                    "adapter_name": LEDGER_ADAPTER_NAME,
                    "adapter_version": LEDGER_ADAPTER_VERSION,
                    "created_at": _now(),
                }
                self._conn.executemany(
                    "INSERT INTO ledger_meta (key,value) VALUES (?,?)", header.items()
                )
                if self._schema_state() != "current":
                    raise BrainError("ledger initialization did not produce the supported schema")
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def _preserve_legacy_snapshot(self) -> tuple[str, int]:
        """Snapshot committed pre-transition state while our write reservation excludes writers."""
        objects = self._contained_path(_OBJECT_DIR)
        objects.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".legacy-snapshot-", suffix=".sqlite", dir=objects)
        os.close(fd)
        temporary = Path(name)
        source = sqlite3.connect(self.dbfile.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        target = sqlite3.connect(temporary)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        payload = temporary.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        destination = _contained(self._dir, f"{_OBJECT_DIR}/{digest}")
        if destination.exists():
            if destination.read_bytes() != payload:
                raise BrainError("legacy snapshot object conflicts with retained data")
            temporary.unlink()
        else:
            os.replace(temporary, destination)
        return digest, len(payload)

    def _migrate_legacy_chain(self) -> None:
        assert self._conn is not None and self._conn.in_transaction
        count, first, last = self._conn.execute(
            "SELECT COUNT(*),COALESCE(MIN(seq),0),COALESCE(MAX(seq),0) FROM events"
        ).fetchone()
        if count and (first != 1 or last != count):
            raise BrainError("legacy ledger has noncontiguous history; refusing transition")
        if self._conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BrainError("legacy ledger has foreign-key violations; refusing transition")
        objects_ok, _ = self._verify_object_digests()
        if not objects_ok:
            raise BrainError("legacy ledger object evidence is unavailable or corrupted")
        before = _legacy_history_fingerprint(self._conn)
        snapshot_hash, snapshot_size = self._preserve_legacy_snapshot()
        derived_at = _now()
        self._conn.execute("ALTER TABLE events ADD COLUMN prev_hash TEXT")
        running = _GENESIS_HASH
        for row in self._conn.execute("SELECT seq,payload_json FROM events ORDER BY seq"):
            if not isinstance(row["payload_json"], str):
                raise BrainError("legacy event payload is not text; refusing reinterpretation")
            running = hashlib.sha256((running + row["payload_json"]).encode("utf-8")).hexdigest()
            self._conn.execute("UPDATE events SET prev_hash=? WHERE seq=?", (running, row["seq"]))
        if _legacy_history_fingerprint(self._conn) != before:
            raise BrainError("legacy transition changed original event storage")
        self._conn.execute(
            "INSERT OR IGNORE INTO object_refs (sha256,size,mime,role,added_at) VALUES (?,?,?,?,?)",
            (
                snapshot_hash,
                snapshot_size,
                "application/vnd.sqlite3",
                "legacy-ledger-snapshot",
                derived_at,
            ),
        )
        origin = {
            "format_version": 1,
            "origin": "derived_legacy_backfill",
            "legacy_through_seq": last,
            "legacy_history_sha256": before,
            "source_snapshot_sha256": snapshot_hash,
            "derived_at": derived_at,
            "pre_migration_authenticity_verified": False,
        }
        self._conn.execute(
            "INSERT INTO ledger_meta (key,value) VALUES (?,?)",
            (_CHAIN_ORIGIN_KEY, canonical_json(origin)),
        )
        self._conn.execute(
            "UPDATE ledger_meta SET value=? WHERE key='schema_version'",
            (str(LEDGER_SCHEMA_VERSION),),
        )

    def _chain_origin(self) -> dict[str, Any] | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM ledger_meta WHERE key=?", (_CHAIN_ORIGIN_KEY,)
        ).fetchone()
        if row is None:
            return None
        try:
            origin = json.loads(row[0])
        except (TypeError, ValueError) as exc:
            raise BrainError("ledger hash-chain origin is malformed") from exc
        if (
            not isinstance(origin, dict)
            or origin.get("format_version") != 1
            or origin.get("origin") != "derived_legacy_backfill"
            or type(origin.get("legacy_through_seq")) is not int
            or origin["legacy_through_seq"] < 0
            or not self._valid_chain_hash(origin.get("legacy_history_sha256"))
            or not self._valid_chain_hash(origin.get("source_snapshot_sha256"))
            or not isinstance(origin.get("derived_at"), str)
            or origin.get("pre_migration_authenticity_verified") is not False
        ):
            raise BrainError(
                "ledger hash-chain origin is unsupported; no historical authenticity inferred"
            )
        return origin

    def _migration_manifest_pending(self) -> bool:
        if self._chain_origin() is None:
            return False
        target = _contained(self._dir, _MANIFEST)
        if not target.exists():
            return True
        try:
            manifest = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BrainError(
                "migrated ledger manifest is unreadable; preserve it before repair"
            ) from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") not in (
            1,
            LEDGER_SCHEMA_VERSION,
        ):
            raise BrainError("migrated ledger manifest has an unsupported schema")
        return manifest["schema_version"] != LEDGER_SCHEMA_VERSION

    # -- session/agent registration -----------------------------------------

    def create_session(self, identity: BrainSessionIdentity) -> None:
        """Create once; repeated registration preserves the durable identity."""
        assert self._conn is not None
        if (
            identity.internal_session_id != self._internal
            or identity.host_session_id != self._host_session_id
        ):
            raise BrainError(f"session identity does not own ledger {self._host_session_id!r}")
        incoming_root = identity.root_parent_session_id
        if incoming_root is not None and not _is_internal_session_id(incoming_root):
            raise BrainError(f"invalid canonical root parent for session {self._host_session_id!r}")
        if incoming_root == self._internal:
            raise BrainError(f"root parent cannot be the session itself: {self._host_session_id!r}")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            existing = self._conn.execute(
                "SELECT host_session_id, root_parent_session_id "
                "FROM sessions WHERE internal_session_id = ?",
                (self._internal,),
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    "INSERT INTO sessions (internal_session_id, host, host_session_id, "
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
                        incoming_root,
                    ),
                )
            else:
                if existing["host_session_id"] != identity.host_session_id:
                    raise BrainError(f"conflicting session identity for {self._host_session_id!r}")
                existing_root = existing["root_parent_session_id"]
                if (
                    existing_root is not None
                    and incoming_root is not None
                    and existing_root != incoming_root
                ):
                    raise BrainError(
                        f"conflicting root parent for session {self._host_session_id!r}"
                    )
                self._conn.execute(
                    "UPDATE sessions SET last_active_at = ?, "
                    "root_parent_session_id = COALESCE(root_parent_session_id, ?), "
                    "project_id = CASE WHEN project_id = '' THEN ? ELSE project_id END "
                    "WHERE internal_session_id = ?",
                    (_now(), incoming_root, identity.project_id, self._internal),
                )
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

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
        if self._host is not None:
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions (internal_session_id, host, host_session_id, "
                " project_id, created_at, last_active_at, status, pinned, schema_version, "
                " current_segment_id, root_parent_session_id) "
                "VALUES (?, ?, ?, '', ?, ?, 'active', 0, ?, NULL, NULL)",
                (
                    self._internal,
                    self._host,
                    self._host_session_id,
                    _now(),
                    _now(),
                    LEDGER_SCHEMA_VERSION,
                ),
            )
            return
        existing = self._conn.execute(
            "SELECT 1 FROM sessions WHERE internal_session_id = ?",
            (self._internal,),
        ).fetchone()
        if existing is None:
            raise BrainError(
                f"ledger session {self._host_session_id!r} requires an explicit "
                "host for first-time initialization"
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
        """Transactional batch append.

        Contiguity: batch seqs must start at
        max(seq)+1. Duplicate event_id or invalid parent ref rejects the WHOLE
        batch deterministically. Missing session/agent rows are ensured
        (INSERT OR IGNORE) so event streams never fail on FK drift.
        """
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
                # T-G6-F1: seq<=0 (host mirrors) auto-assigns; explicit seqs
                # must stay contiguous with the ledger.
                if event.seq > 0 and event.seq != next_seq + i:
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
                        raise BrainError(f"invalid parent_event_id: {event.parent_event_id!r}")
            seqs: list[int] = []
            prior_row_hash = self._conn.execute(
                "SELECT prev_hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            running_prev_hash = prior_row_hash[0] if prior_row_hash is not None else _GENESIS_HASH
            for insert_index, event in enumerate(events):
                effective_seq = event.seq if event.seq > 0 else next_seq + insert_index
                payload_canonical = canonical_json(event.payload)
                event_prev_hash = hashlib.sha256(
                    (running_prev_hash + payload_canonical).encode("utf-8")
                ).hexdigest()
                self._conn.execute(
                    "INSERT INTO events (seq, event_id, internal_session_id, agent_id, "
                    " parent_event_id, host_entry_id, host_parent_entry_id, segment_id, "
                    " event_type, timestamp, surface_visibility, ignorable, payload_json, "
                    " artifact_sha256, source_event_ids, prev_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        effective_seq,
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
                        payload_canonical,
                        event.artifact_sha256,
                        canonical_json(event.source_event_ids),
                        event_prev_hash,
                    ),
                )
                seqs.append(effective_seq)
                running_prev_hash = event_prev_hash
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

    def _verify_object_digests(self) -> tuple[bool, list[str]]:
        """Full digest re-verification of every object_refs row (session- scoped; used
        by replay(), not by integrity()/checkpoint_ledger's hot path — see integrity()'s
        docstring)."""
        bad: list[str] = []
        assert self._conn is not None
        for obj in self._conn.execute("SELECT sha256, size FROM object_refs").fetchall():
            try:
                path = _contained(self._dir, f"{_OBJECT_DIR}/{obj['sha256']}")
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != obj["sha256"]:
                    bad.append(obj["sha256"][:12])
            except OSError:
                bad.append(obj["sha256"][:12])
        return (not bad, bad)

    def integrity(self) -> dict[str, Any]:
        """Seq contiguity, orphan parents, schema version, and an incremental hash-chain
        check (plan T6.3): verification resumes from
        ``ledger_meta['last_verified_seq']`` (default 0) rather than re-hashing every
        event on every call.

        Object payloads are NOT
        re-hashed here — ``read_object()`` digest-verifies on every read,
        and ``replay()`` separately full-verifies every object_refs row
        before returning a projection; re-hashing all objects on every
        integrity()/checkpoint_ledger() call was the eager cost this
        rewrite removes.
        """
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
        version = int(
            self._conn.execute(
                "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        )

        last_verified_row = self._conn.execute(
            "SELECT value FROM ledger_meta WHERE key = 'last_verified_seq'"
        ).fetchone()
        last_verified_seq = int(last_verified_row[0]) if last_verified_row is not None else 0
        seed_row = self._conn.execute(
            "SELECT prev_hash FROM events WHERE seq = ?", (last_verified_seq,)
        ).fetchone()
        running_prev_hash = seed_row[0] if seed_row is not None else _GENESIS_HASH

        hash_chain_ok = True
        hash_chain_break_seq: int | None = None
        verified_through = last_verified_seq
        for erow in self._conn.execute(
            "SELECT seq, payload_json, prev_hash FROM events WHERE seq > ? ORDER BY seq ASC",
            (last_verified_seq,),
        ):
            expected = hashlib.sha256(
                (running_prev_hash + erow["payload_json"]).encode("utf-8")
            ).hexdigest()
            if expected != erow["prev_hash"]:
                hash_chain_ok = False
                hash_chain_break_seq = int(erow["seq"])
                break
            running_prev_hash = erow["prev_hash"]
            verified_through = int(erow["seq"])

        if hash_chain_ok:
            self._conn.execute(
                "INSERT OR REPLACE INTO ledger_meta (key, value) VALUES ('last_verified_seq', ?)",
                (str(verified_through),),
            )
            self._conn.commit()

        return {
            "seq_contiguous": contiguous,
            "orphan_parents": int(orphans),
            "objects_verified_on_read_only": True,
            "schema_version": version,
            "event_count": n,
            "hash_chain_ok": hash_chain_ok,
            "hash_chain_verified_through_seq": verified_through,
            "hash_chain_break_seq": hash_chain_break_seq,
            "hash_chain_origin": self._chain_origin(),
        }

    # -- segments ---------------------------------------------------------------

    def open_segment(self, started_reason: str = "manual") -> str:
        """Close the prior active segment (end_seq = max seq) and open a new one
        (index+1, start_seq = max seq + 1).

        Returns the new segment_id.
        """
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
            idx = (
                int(self._conn.execute("SELECT COALESCE(MAX(idx), -1) FROM segments").fetchone()[0])
                + 1
            )
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
        """Close the active segment at the current max seq.

        Returns the closed segment row (or None when no segment is active).
        """
        assert self._conn is not None
        max_seq = int(self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0])
        row = self._conn.execute("SELECT * FROM segments WHERE active = 1").fetchone()
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
        """Continuation capsule from recent events (plan §17.5/§10.4): only what exists
        in the ledger — never fabricated."""
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
            dict(r) for r in self._conn.execute("SELECT * FROM segments ORDER BY idx").fetchall()
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
                "ORDER BY e.seq LIMIT ?"
            )
            params = [match, *params, limit]
        else:
            like = f"%{query}%"
            if filters:
                sql = (
                    f"{base} WHERE {' AND '.join(filters)} "
                    "AND (e.event_type LIKE ? OR e.payload_json LIKE ?) ORDER BY e.seq LIMIT ?"
                )
            else:
                sql = (
                    f"{base} WHERE (e.event_type LIKE ? OR e.payload_json LIKE ?) "
                    "ORDER BY e.seq LIMIT ?"
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
        """Independent replay (plan §9.10): fresh-connection semantics via this store's
        own connection + validation, reconstructing the root->leaf lineage projection.

        Detects seq gaps, orphan parents, object failures, and payload tampering
        (seq/payload mismatch is detected by the projection hash comparison in
        compare_projection).
        """
        assert self._conn is not None
        integrity = self.integrity()
        if not integrity["seq_contiguous"]:
            raise BrainError("replay rejected: seq not contiguous")
        if integrity["orphan_parents"]:
            raise BrainError("replay rejected: orphan parent_event_id")
        digests_ok, bad_objects = self._verify_object_digests()
        if not digests_ok:
            raise BrainError(f"replay rejected: object digest failures {bad_objects}")
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
            for r in self._conn.execute("SELECT * FROM segments ORDER BY idx").fetchall()
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
        host = self._host
        target = _contained(self._dir, _MANIFEST)
        existing_manifest: dict[str, Any] = {}
        if target.exists():
            try:
                existing_manifest = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise BrainError(
                    "ledger manifest unreadable; preserve it before maintenance"
                ) from exc
            if not isinstance(existing_manifest, dict):
                raise BrainError("ledger manifest must be an object")
        if host is None:
            existing_host = existing_manifest.get("host")
            if isinstance(existing_host, str) and existing_host:
                host = existing_host
        if host is None:
            raise BrainError(
                f"ledger session {self._host_session_id!r} requires an explicit "
                "host for first-time initialization"
            )
        manifest = {
            **existing_manifest,
            "internal_id": self._internal,
            "host": host,
            "host_session_id": self._host_session_id,
            "created_at": existing_manifest.get("created_at", _now()),
            "schema_version": LEDGER_SCHEMA_VERSION,
            "db": "ledger.sqlite",
            "host_artifacts": (
                host_artifacts
                if host_artifacts is not None
                else existing_manifest.get("host_artifacts", [])
            ),
        }
        # P3-E fix: a FIXED tmp name collided under concurrent init of the
        # same fresh session. Readers can also briefly deny replacement on
        # Windows; retry only those errors, without removing the destination.
        fd, tmp_name = tempfile.mkstemp(prefix=f"{_MANIFEST}.tmp.", dir=self._dir, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(canonical_json(manifest) + "\n")
            for attempt in range(4):
                try:
                    os.replace(Path(tmp_name), target)
                    break
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) not in (5, 32) or attempt == 3:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise


def replay_session(home: Path | str, host_session_id: str, lineage: list[str]) -> ProjectedContext:
    """Open fresh + replay.

    Independent of any live in-memory projection.
    """
    with LedgerStore(home, host_session_id).open() as store:
        return store.replay(lineage)


def compare_projection(captured: ProjectedContext, replayed: ProjectedContext) -> str | None:
    """First divergence between a captured and a replayed projection (plan §9.10):
    compare event streams in seq order by (event_id, payload hash, parent).

    Returns a description or None when identical.
    """
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
    """Walk parent_event_id pointers from the lineage leaf back to the root; returns the
    chain (root->leaf).

    Raises on a broken pointer.
    """
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

    REQUESTED + no TOOL_STARTED -> TOOL_NOT_STARTED TOOL_STARTED  + no result    ->
    TOOL_OUTCOME_UNKNOWN (verify-before-retry) TOOL_STARTED  + result       -> COMPLETE
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
            dict(r) for r in store._conn.execute("SELECT * FROM segments ORDER BY idx").fetchall()
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
        rows = store._conn.execute(f"SELECT * FROM events{where} ORDER BY seq", params).fetchall()
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

            def matches_decision(e: BrainLifecycleEvent) -> bool:
                if decision is None:
                    return True
                if e.event_id == decision:
                    return True
                # T-G6-F2: match payload decision_id too (event_id first)
                payload_id = e.payload.get("decision_id")
                if payload_id is not None and str(payload_id) == decision:
                    return True
                return isinstance(payload_id, str) and decision in payload_id

            decisions = [
                e
                for e in events
                if e.event_type in (LifecycleEventType.DECISION, LifecycleEventType.FINDING)
                and matches_decision(e)
            ]
            content = {
                "level": 2,
                "evidence_packets": [
                    {
                        "event_id": e.event_id,
                        "seq": e.seq,
                        "decision": (
                            e.payload.get("decision")
                            or e.payload.get("title")
                            or e.payload.get("summary")
                        ),
                        "rationale": (
                            e.payload.get("rationale")
                            or e.payload.get("guidance")
                            or e.payload.get("observation")
                        ),
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

    Returns {ok, integrity, closed_segment?}. Never raises.
    """
    try:
        store.flush()
        integrity = store.integrity()
        ok = bool(
            integrity["seq_contiguous"]
            and integrity["orphan_parents"] == 0
            and integrity["hash_chain_ok"]
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
            raise SessionLifecycleError(f"invalid transition {current!r} -> {status!r}")
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
        """Detect interrupted compaction brackets, unclosed segments, and tool crash
        states; append ONE recovery finding event when an interrupted compaction is
        found.

        Returns the report (no fabrication).
        """
        with LedgerStore(self._home, self._host_session_id).open() as store:
            assert store._conn is not None
            rows = store._conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
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
                for r in store._conn.execute("SELECT * FROM segments WHERE active = 1").fetchall()
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
                next_seq = (
                    int(
                        store._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[
                            0
                        ]
                    )
                    + 1
                )
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
                origin_class="TOOL_OBSERVATION",
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
                raise SessionLifecycleError(f"extraction failed ({exc}); refusing purge") from exc
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
        artifacts.remove_refs_by_owner_suffix(self._home, f":{self._internal}")
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
