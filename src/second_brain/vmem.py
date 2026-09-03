"""
Context Virtual Memory (VMem) & Transient Indexed Session Memory.

Plan §6: Phase 3 — Transient Indexed Session Memory -> Context Virtual Memory.
Upgrades session memory into a paged virtual context with explicit residency states,
hot working set admission/eviction, deterministic compaction recovery, and JIT fault-in.

Residency States (§6.3):
- STORED: Preserved in session storage
- RESIDENT: Active in model-visible context
- EVICTED: Removed from active context to preserve budget (recoverable by ref)
- FAULTED_IN: Paged back into active context upon demand
- SUPERSEDED: Replaced by a newer version
- PURGED: Cleaned up upon retention expiration
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import artifacts, contracts, db, decisions, ledger, semantic, working_set
from .errors import BrainError
from .paths import db_path as _control_db_path

logger = logging.getLogger(__name__)

DEFAULT_HOT_CONTEXT_BUDGET_TOKENS = 1500
MAX_REF_TABLE_ENTRIES = 25

# Coverage-before-reclaim (Deep Upgrade Plan U4 §5.3-5.7).
DURABILITY_DIRTY = "DIRTY"
DURABILITY_CLEAN = "CLEAN"


class ResidencyState(StrEnum):
    STORED = "STORED"
    RESIDENT = "RESIDENT"
    EVICTED = "EVICTED"
    FAULTED_IN = "FAULTED_IN"
    SUPERSEDED = "SUPERSEDED"
    PURGED = "PURGED"


class SessionObjectKind(StrEnum):
    WORKER_FINDING = "WORKER_FINDING"
    TEST_EVIDENCE = "TEST_EVIDENCE"
    LOG_EXCERPT = "LOG_EXCERPT"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    CODE_REGION = "CODE_REGION"
    DECISION = "DECISION"
    BLOCKER = "BLOCKER"
    RESEARCH_RESULT = "RESEARCH_RESULT"
    GENERIC = "GENERIC"

class RecoveryClass(StrEnum):
    EXACT_ARTIFACT = "EXACT_ARTIFACT"
    CANONICAL_STATE = "CANONICAL_STATE"
    DISPOSABLE_DERIVED = "DISPOSABLE_DERIVED"


# Never allowed to be marked durability=CLEAN via DISPOSABLE_DERIVED coverage
# (plan U4 §5.4): these kinds always carry material session truth.
_MATERIAL_KINDS = frozenset(
    {SessionObjectKind.DECISION, SessionObjectKind.BLOCKER, SessionObjectKind.WORKER_FINDING}
)

# DISPOSABLE_DERIVED coverage additionally requires an explicit
# ``metadata["derived_kind"]`` tag naming one of these low-value, easily
# reproduced kinds (plan U4 §5.4) -- never inferred from `SessionObjectKind`.
_DISPOSABLE_DERIVED_TAGS = frozenset({"DIRECTORY_LISTING", "SEARCH_OUTPUT", "SUPERSEDED_RESULT"})


_VMEM_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_vmem (
    obj_id TEXT PRIMARY KEY,
    internal_session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    token_estimate INTEGER NOT NULL,
    residency_state TEXT NOT NULL,
    priority_score REAL NOT NULL DEFAULT 1.0,
    pinned INTEGER NOT NULL DEFAULT 0,
    access_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    segment_id TEXT,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vmem_residency
    ON session_vmem (internal_session_id, residency_state);
CREATE INDEX IF NOT EXISTS idx_vmem_kind
    ON session_vmem (internal_session_id, kind);
CREATE TABLE IF NOT EXISTS ledger_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Coverage-before-reclaim additive columns (plan U4 §5.3), applied via the
# SAME guarded PRAGMA-table_info-then-ALTER convention already used by
# db.py's migration 0012 and gardener.py's skill_roi_ledger extension --
# never a destructive rewrite, always idempotent on reopen.
_VMEM_ADDITIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("durability", "TEXT NOT NULL DEFAULT 'DIRTY'"),
    ("recovery_class", "TEXT"),
    ("covered_at", "TEXT"),
)


@dataclass
class SessionObject:
    """A transient session object stored in Context Virtual Memory."""
    obj_id: str
    session_id: str
    kind: SessionObjectKind
    title: str
    summary: str
    content_sha256: str
    token_estimate: int
    residency_state: ResidencyState
    priority_score: float = 1.0
    pinned: bool = False
    access_count: int = 1
    created_at: str = ""
    last_accessed_at: str = ""
    segment_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    durability: str = DURABILITY_DIRTY
    recovery_class: str | None = None
    covered_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "obj_id": self.obj_id,
            "session_id": self.session_id,
            "kind": self.kind.value,
            "title": self.title,
            "summary": self.summary,
            "content_sha256": self.content_sha256,
            "token_estimate": self.token_estimate,
            "residency_state": self.residency_state.value,
            "priority_score": round(self.priority_score, 2),
            "pinned": self.pinned,
            "access_count": self.access_count,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
            "segment_id": self.segment_id,
            "metadata": self.metadata,
            "durability": self.durability,
            "recovery_class": self.recovery_class,
            "covered_at": self.covered_at,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _estimate_tokens(text: str, home: Path | str | None = None) -> int:
    return contracts.estimate_tokens(text, home=home)


def _compute_base_priority(kind: SessionObjectKind, pinned: bool) -> float:
    if pinned:
        return 1000.0
    if kind in (SessionObjectKind.DECISION, SessionObjectKind.BLOCKER):
        return 100.0
    if kind in (
        SessionObjectKind.WORKER_FINDING,
        SessionObjectKind.TEST_EVIDENCE,
        SessionObjectKind.CODE_REGION,
        SessionObjectKind.RESEARCH_RESULT,
    ):
        return 50.0
    return 10.0


def _load_economics_parameters(home: Path | str) -> dict[str, float | int]:
    """Read cache pricing multipliers and cost model parameters from
    `config/v2.toml [economics]` or provider table if present; fallback to standard defaults."""
    path = Path(home) / "config" / "v2.toml"
    cache_read = 0.10
    cache_write = 1.25
    fault_in_turn_cost_tokens = 50
    default_remaining_turns = 8
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raw = {}

    section = raw.get("economics") if isinstance(raw, dict) else None
    if isinstance(section, dict):
        cr = section.get("cache_read")
        if isinstance(cr, (int, float)) and not isinstance(cr, bool):
            cache_read = float(cr)
        cw = section.get("cache_write")
        if isinstance(cw, (int, float)) and not isinstance(cw, bool):
            cache_write = float(cw)
        fc = section.get("fault_in_turn_cost_tokens")
        if isinstance(fc, (int, float)) and not isinstance(fc, bool):
            fault_in_turn_cost_tokens = int(fc)
        rt = section.get("default_remaining_turns")
        if isinstance(rt, (int, float)) and not isinstance(rt, bool):
            default_remaining_turns = int(rt)

    # Provider table override if present: config/v2.toml [providers.<id>]
    providers = raw.get("providers") if isinstance(raw, dict) else None
    if isinstance(providers, dict):
        for _, pcfg in providers.items():
            if isinstance(pcfg, dict):
                pcr = pcfg.get("cache_read")
                if isinstance(pcr, (int, float)) and not isinstance(pcr, bool):
                    cache_read = float(pcr)
                pcw = pcfg.get("cache_write")
                if isinstance(pcw, (int, float)) and not isinstance(pcw, bool):
                    cache_write = float(pcw)

    return {
        "cache_read": cache_read,
        "cache_write": cache_write,
        "fault_in_turn_cost_tokens": fault_in_turn_cost_tokens,
        "default_remaining_turns": default_remaining_turns,
    }


def remaining_turns_estimate(
    home: Path | str,
    session_id: str,
    default_turns: int = 8,
) -> int:
    """Resolve remaining turns estimate from session telemetry or task class,
    falling back to default_remaining_turns."""
    internal_id = ledger.internal_session_id(session_id)
    sdir = Path(home) / "state" / "sessions" / internal_id
    for fname in ("routing.json", "active-state.json", "manifest.json"):
        fpath = sdir / fname
        if fpath.exists():
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    rt = data.get("remaining_turns")
                    if isinstance(rt, (int, float)) and not isinstance(rt, bool) and rt > 0:
                        return int(rt)
                    task_class = data.get("task_class")
                    if isinstance(task_class, str):
                        tpath = Path(home) / "state" / "telemetry" / "task_classes.json"
                        if tpath.exists():
                            tdata = json.loads(tpath.read_text(encoding="utf-8"))
                            if isinstance(tdata, dict) and task_class in tdata:
                                med = tdata[task_class].get("median_remaining_turns")
                                if isinstance(med, (int, float)) and med > 0:
                                    return int(med)
            except Exception:
                pass
    return default_turns

class VMemStore:
    """Context Virtual Memory manager for a session."""

    def __init__(self, home: Path | str, session_id: str) -> None:
        self.home = Path(home)
        self.session_id = session_id
        self.internal_id = ledger.internal_session_id(session_id)
        self._sdir = self.home / "state" / "sessions" / self.internal_id
        self._sdir.mkdir(parents=True, exist_ok=True)
        self._dbfile = self._sdir / "ledger.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_VMEM_SCHEMA)
            existing_columns = {
                str(row[1]).casefold()
                for row in conn.execute("PRAGMA table_info(session_vmem)").fetchall()
            }
            for column, ddl in _VMEM_ADDITIVE_COLUMNS:
                if column.casefold() not in existing_columns:
                    conn.execute(f"ALTER TABLE session_vmem ADD COLUMN {column} {ddl}")
            conn.commit()

    def store_object(
        self,
        kind: SessionObjectKind | str,
        title: str,
        content: str,
        summary: str = "",
        pinned: bool = False,
        segment_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact_ref: str | None = None,
    ) -> SessionObject:
        """Store a transient session object with content-addressed backing."""
        if isinstance(kind, str):
            try:
                kind = SessionObjectKind(kind.upper())
            except ValueError:
                kind = SessionObjectKind.GENERIC

        # Backing store exact bytes, or reference a preserve-first artifact.
        if artifact_ref is not None:
            raw_bytes = artifacts.expand(self.home, artifact_ref)
            actual_sha = hashlib.sha256(raw_bytes).hexdigest()
            if actual_sha != artifact_ref:
                raise BrainError(
                    f"VMem artifact reference mismatch: expected {artifact_ref}, got {actual_sha}"
                )
            content_sha = artifact_ref
        else:
            stored_artifact = artifacts.store_text(
                self.home,
                content,
                kind=kind.value.lower(),
                tool="vmem",
                session=self.session_id,
            )
            content_sha = stored_artifact["hash"]
        obj_id = f"obj-{content_sha[:12]}"
        now = _now()
        tokens = _estimate_tokens(content, self.home)
        base_priority = _compute_base_priority(kind, pinned)
        meta_dict = metadata or {}
        meta_json = json.dumps(meta_dict)

        obj = SessionObject(
            obj_id=obj_id,
            session_id=self.session_id,
            kind=kind,
            title=title,
            summary=summary or title,
            content_sha256=content_sha,
            token_estimate=tokens,
            residency_state=ResidencyState.RESIDENT,
            priority_score=base_priority,
            pinned=pinned,
            access_count=1,
            created_at=now,
            last_accessed_at=now,
            segment_id=segment_id,
            metadata=meta_dict,
        )

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                """
                INSERT INTO session_vmem (
                    obj_id, internal_session_id, kind, title, summary,
                    content_sha256, token_estimate, residency_state,
                    priority_score, pinned, access_count, created_at,
                    last_accessed_at, segment_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(obj_id) DO UPDATE SET
                    residency_state=excluded.residency_state,
                    access_count=access_count + 1,
                    last_accessed_at=excluded.last_accessed_at,
                    pinned=MAX(pinned, excluded.pinned)
                """,
                (
                    obj.obj_id,
                    self.internal_id,
                    obj.kind.value,
                    obj.title,
                    obj.summary,
                    obj.content_sha256,
                    obj.token_estimate,
                    obj.residency_state.value,
                    obj.priority_score,
                    1 if obj.pinned else 0,
                    obj.access_count,
                    obj.created_at,
                    obj.last_accessed_at,
                    obj.segment_id,
                    meta_json,
                ),
            )
            conn.commit()

        return obj

    def _row_to_session_object(self, r: sqlite3.Row) -> SessionObject:
        return SessionObject(
            obj_id=r["obj_id"],
            session_id=self.session_id,
            kind=SessionObjectKind(r["kind"]),
            title=r["title"],
            summary=r["summary"],
            content_sha256=r["content_sha256"],
            token_estimate=r["token_estimate"],
            residency_state=ResidencyState(r["residency_state"]),
            priority_score=r["priority_score"],
            pinned=bool(r["pinned"]),
            access_count=r["access_count"],
            created_at=r["created_at"],
            last_accessed_at=r["last_accessed_at"],
            segment_id=r["segment_id"],
            metadata=json.loads(r["metadata_json"] or "{}"),
            durability=r["durability"],
            recovery_class=r["recovery_class"],
            covered_at=r["covered_at"],
        )

    def list_objects(
        self,
        residency_state: ResidencyState | str | None = None,
        kind: SessionObjectKind | str | None = None,
    ) -> list[SessionObject]:
        """List session objects, optionally filtered by residency state or kind."""
        query = "SELECT * FROM session_vmem WHERE internal_session_id = ?"
        params: list[Any] = [self.internal_id]

        if residency_state is not None:
            state_val = (
                residency_state.value
                if isinstance(residency_state, ResidencyState)
                else str(residency_state)
            )
            query += " AND residency_state = ?"
            params.append(state_val)

        if kind is not None:
            kind_val = kind.value if isinstance(kind, SessionObjectKind) else str(kind)
            query += " AND kind = ?"
            params.append(kind_val)

        query += " ORDER BY pinned DESC, priority_score DESC, last_accessed_at DESC"

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [self._row_to_session_object(r) for r in rows]

    def get_object(self, obj_id: str) -> SessionObject | None:
        """Get object by ID."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                "SELECT * FROM session_vmem WHERE internal_session_id = ? AND obj_id = ?",
                (self.internal_id, obj_id),
            ).fetchone()

        if not r:
            return None

        return self._row_to_session_object(r)

    def _verify_and_load(self, obj_id: str) -> tuple[SessionObject, str]:
        """Read-only verify+load step (RC4 Part D safety pass): confirm the
        object exists and its OWN stored VMem backing artifact is present and
        intact. Raises `BrainError` on any failure. Performs NO DB write —
        callers must not assume any mutation has happened after this returns.

        Hash-verifies the loaded bytes against `obj.content_sha256` (belt and
        braces on top of `artifacts.expand`'s own path-by-hash lookup) so
        silent on-disk bit-rot of this object's own backing blob is caught
        here, at verify time, rather than surfacing later as a confusing
        downstream JSON/decode error.
        """
        obj = self.get_object(obj_id)
        if not obj:
            raise BrainError(f"Session object not found: {obj_id}")

        raw_bytes = artifacts.expand(self.home, obj.content_sha256)
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        if actual_sha != obj.content_sha256:
            raise BrainError(
                f"VMem backing artifact corrupt for {obj_id}: expected sha256 "
                f"{obj.content_sha256}, got {actual_sha}"
            )
        content = raw_bytes.decode("utf-8", errors="replace")
        return obj, content

    def _mutate_fault_in(self, obj: SessionObject) -> SessionObject:
        """The ONE DB write of the fault-in path (RC4 Part D safety pass):
        residency EVICTED->FAULTED_IN (unchanged otherwise), access_count++,
        priority_score boosted. Callers must only invoke this AFTER every
        read-only verification/resolution step for the requested recovery
        has already succeeded — this method itself does not verify anything."""
        now = _now()
        new_state = (
            ResidencyState.FAULTED_IN
            if obj.residency_state == ResidencyState.EVICTED
            else obj.residency_state
        )
        new_count = obj.access_count + 1
        new_priority = obj.priority_score + 5.0  # Boost priority on page-in

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                """
                UPDATE session_vmem
                SET residency_state = ?, access_count = ?, last_accessed_at = ?, priority_score = ?
                WHERE internal_session_id = ? AND obj_id = ?
                """,
                (new_state.value, new_count, now, new_priority, self.internal_id, obj.obj_id),
            )
            conn.commit()

        obj.residency_state = new_state
        obj.access_count = new_count
        obj.last_accessed_at = now
        obj.priority_score = new_priority
        return obj

    def fault_in(self, obj_id: str) -> tuple[SessionObject, str]:
        """
        Page an evicted or stored object back into active context (§6.5).
        Transitions state to FAULTED_IN, updates access counters, and returns
        raw content. EXISTING external contract preserved unchanged for the
        `page` CLI: verify+load (read-only), then mutate, then return. This
        simple caller has no deeper resolution step, so verify-then-mutate is
        already safe/correct for it (see `resolve_object` for the version
        used where a deeper durable-source resolution must succeed FIRST).
        """
        obj, content = self._verify_and_load(obj_id)
        obj = self._mutate_fault_in(obj)
        return obj, content

    def claim_pages(self, requests: list[dict[str, Any]]) -> list[str]:
        """
        Proactive (pre-compaction) paging claim (RC4 proactive-paging-repair
        pass, Defect B). Prime's own context-paging pass
        (`context-paging.ts` `pageContext`, TS side) needs to be able to
        cause the RESIDENT/FAULTED_IN -> EVICTED transition ITSELF, before a
        real compaction event ever runs `prepare_compaction()` — Pilot 3
        (outputs/reports/rc4/13-real-prime-pilot-3.md) found that objects
        only ever became EVICTED at the SAME moment Prime's own compaction
        removed the corresponding live message from context entirely, so a
        pager that only ever looked for already-EVICTED objects could never
        find a real match.

        For EACH requested `{"obj_id": ..., "kind": ...}` dict (malformed
        entries -- missing/non-string obj_id or kind -- are silently
        skipped: never claimed, never an error; this is a small, bounded,
        internal claim primitive, not a public-input validator), performs
        ONE atomic, single-statement compare-and-set UPDATE scoped to
        `internal_session_id` AND `obj_id` AND `kind` (a kind mismatch --
        the request's kind does not match the object's ACTUAL stored kind
        -- never claims anything) AND `residency_state IN ('RESIDENT',
        'FAULTED_IN')` AND `pinned = 0`.

        The UPDATE's own WHERE clause -- never a prior `list_objects()`
        result -- is the single source of truth for whether the object was
        STILL claimable at the moment of the write, checked via the
        statement's own affected-row count (`cursor.rowcount`). This makes
        the method correct under concurrent/racing claims for the same
        obj_id: SQLite serializes writers at the connection/file level, so
        only the FIRST UPDATE that actually matches wins; every later
        UPDATE attempting the same obj_id then finds the row already
        EVICTED, its WHERE clause no longer matches, and `rowcount` is 0 --
        deterministic, safe, idempotent, no error either way.

        Reuses the EXISTING `session_vmem` table/connection pattern already
        used by `evict_to_budget`/`prepare_compaction`/`_mutate_fault_in` --
        no new table, no new subsystem.

        Returns exactly the obj_ids ACTUALLY transitioned to EVICTED by
        THIS call, in request order.
        """
        claimed: list[str] = []
        if not requests:
            return claimed

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            for req in requests:
                obj_id = req.get("obj_id") if isinstance(req, dict) else None
                kind = req.get("kind") if isinstance(req, dict) else None
                if (
                    not isinstance(obj_id, str)
                    or not obj_id
                    or not isinstance(kind, str)
                    or not kind
                ):
                    continue
                cur = conn.execute(
                    """
                    UPDATE session_vmem
                    SET residency_state = ?
                    WHERE internal_session_id = ?
                      AND obj_id = ?
                      AND kind = ?
                      AND residency_state IN (?, ?)
                      AND pinned = 0
                    """,
                    (
                        ResidencyState.EVICTED.value,
                        self.internal_id,
                        obj_id,
                        kind,
                        ResidencyState.RESIDENT.value,
                        ResidencyState.FAULTED_IN.value,
                    ),
                )
                if cur.rowcount == 1:
                    claimed.append(obj_id)
            conn.commit()

        return claimed

    def _resolve_recovery_class(self, obj: SessionObject) -> str:
        """The recovery_class governing coverage for `obj` (plan U4 §5.3):
        an explicit `metadata["recovery_class"]` hint set at store time,
        else EXACT_ARTIFACT -- every session object is already
        content-addressed and artifact-backed at `store_object()` time, so
        EXACT_ARTIFACT is the default, trivially-satisfiable coverage path
        as long as its own backing artifact stays intact."""
        explicit = obj.metadata.get("recovery_class") if isinstance(obj.metadata, dict) else None
        if explicit in (
            RecoveryClass.EXACT_ARTIFACT.value,
            RecoveryClass.CANONICAL_STATE.value,
            RecoveryClass.DISPOSABLE_DERIVED.value,
        ):
            return explicit
        return RecoveryClass.EXACT_ARTIFACT.value

    def _canonical_state_exists(self, obj: SessionObject) -> bool:
        """CANONICAL_STATE coverage (plan U4 §5.3): true iff
        `metadata["canonical_ref"]` (`{"type": "capsule"|"requirement"|
        "memory", "id": ...}`) still resolves to a live capsule,
        requirement, or memory row -- the durable source this object's
        content is a transient reflection of."""
        ref = obj.metadata.get("canonical_ref") if isinstance(obj.metadata, dict) else None
        if not isinstance(ref, dict):
            return False
        ref_type = ref.get("type")
        if ref_type == "capsule":
            try:
                working_set.show_capsule(self.home, self.session_id)
                return True
            except BrainError:
                return False
        if ref_type == "requirement":
            req_id = ref.get("id")
            if not isinstance(req_id, str) or not req_id:
                return False
            try:
                entries = working_set.show_requirements(self.home, self.session_id)
            except BrainError:
                return False
            return any(entry.get("id") == req_id for entry in entries)
        if ref_type == "memory":
            memory_id = ref.get("id")
            if not isinstance(memory_id, str) or not memory_id:
                return False
            try:
                semantic.show_memory(self.home, memory_id)
                return True
            except BrainError:
                return False
        return False

    def _check_coverage(self, obj: SessionObject, recovery_class: str) -> bool:
        if recovery_class == RecoveryClass.EXACT_ARTIFACT.value:
            try:
                raw = artifacts.expand(self.home, obj.content_sha256)
            except BrainError:
                return False
            return hashlib.sha256(raw).hexdigest() == obj.content_sha256
        if recovery_class == RecoveryClass.CANONICAL_STATE.value:
            return self._canonical_state_exists(obj)
        if recovery_class == RecoveryClass.DISPOSABLE_DERIVED.value:
            # Never allowed for material kinds, regardless of any metadata
            # hint (plan U4 §5.4) -- decisions/blockers/worker findings are
            # never disposable.
            if obj.kind in _MATERIAL_KINDS:
                return False
            derived_kind = (
                obj.metadata.get("derived_kind") if isinstance(obj.metadata, dict) else None
            )
            return derived_kind in _DISPOSABLE_DERIVED_TAGS
        return False

    def cover(self, obj: SessionObject) -> bool:
        """Coverage check (plan U4 §5.3): verify `obj`'s recovery_class
        contract. Success marks `durability=CLEAN` (mutating both the DB
        row and `obj` in place) and returns True. Failure leaves the
        object completely untouched -- still resident, still DIRTY, never
        destroyed."""
        recovery_class = self._resolve_recovery_class(obj)
        if not self._check_coverage(obj, recovery_class):
            return False
        now = _now()
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                """
                UPDATE session_vmem
                SET durability = ?, recovery_class = ?, covered_at = ?
                WHERE internal_session_id = ? AND obj_id = ?
                """,
                (DURABILITY_CLEAN, recovery_class, now, self.internal_id, obj.obj_id),
            )
            conn.commit()
        obj.durability = DURABILITY_CLEAN
        obj.recovery_class = recovery_class
        obj.covered_at = now
        return True

    def _advance_watermark(self, conn: sqlite3.Connection) -> int:
        """Advance `ledger_meta.durable_through_seq` (plan U4 §5.5) to the
        largest `session_vmem.rowid` such that EVERY row up to and
        including it is durability=CLEAN -- a cumulative-ack watermark
        over this session's own object insertion order. A single DIRTY
        row halts the advance right before it; the watermark itself never
        moves backward."""
        row = conn.execute(
            "SELECT value FROM ledger_meta WHERE key = 'durable_through_seq'"
        ).fetchone()
        current = int(row[0]) if row and row[0] is not None else 0

        rows = conn.execute(
            "SELECT rowid, durability FROM session_vmem "
            "WHERE internal_session_id = ? ORDER BY rowid",
            (self.internal_id,),
        ).fetchall()

        watermark = current
        for rowid, durability in rows:
            if rowid <= current:
                continue
            if durability != DURABILITY_CLEAN:
                break
            watermark = rowid

        if watermark > current:
            conn.execute(
                "INSERT INTO ledger_meta (key, value) VALUES ('durable_through_seq', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(watermark),),
            )
        return watermark

    def get_durable_through_seq(self) -> int:
        """The current `durable_through_seq` watermark (plan U4 §5.5):
        every `session_vmem` row with rowid <= this value is
        durability=CLEAN."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            row = conn.execute(
                "SELECT value FROM ledger_meta WHERE key = 'durable_through_seq'"
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _append_reclaim_manifest(self, rows: list[dict[str, Any]]) -> None:
        """Append one line per committed reclaim to `reclaim_manifest.jsonl`
        under this session's own directory (plan U4 §5.5) -- same
        per-session jsonl-append convention used elsewhere (e.g.
        autoinject.py's per-session telemetry mirror)."""
        path = self._sdir / "reclaim_manifest.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(contracts.canonical_json(row) + "\n")

    def _reclaim(self, candidates: list[SessionObject], reason: str) -> list[SessionObject]:
        """The COVERAGE -> COMMIT -> VERIFY tail of the four-phase reclaim
        flow (plan U4 §5.5); PREPARE (victim selection) is the caller's
        own responsibility. COVERAGE: `cover()` each candidate --
        uncovered candidates are left completely alone (still resident,
        still DIRTY). COMMIT: one atomic CAS UPDATE per covered candidate,
        scoped to `durability='CLEAN'` on top of `claim_pages`'s existing
        residency_state/pinned CAS guard -- a lost race (already claimed
        by a concurrent `claim_pages` call) is silently skipped, never an
        error. VERIFY: re-read each committed row, append one
        `reclaim_manifest.jsonl` row, then advance `durable_through_seq`
        over the resulting contiguous CLEAN prefix. Returns the objects
        THIS call actually evicted."""
        covered = [obj for obj in candidates if self.cover(obj)]

        evicted: list[SessionObject] = []
        manifest_rows: list[dict[str, Any]] = []
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            for obj in covered:
                cur = conn.execute(
                    """
                    UPDATE session_vmem
                    SET residency_state = ?
                    WHERE internal_session_id = ?
                      AND obj_id = ?
                      AND residency_state IN (?, ?)
                      AND pinned = 0
                      AND durability = ?
                    """,
                    (
                        ResidencyState.EVICTED.value,
                        self.internal_id,
                        obj.obj_id,
                        ResidencyState.RESIDENT.value,
                        ResidencyState.FAULTED_IN.value,
                        DURABILITY_CLEAN,
                    ),
                )
                if cur.rowcount != 1:
                    continue  # lost the CAS race, or no longer eligible -- skip, no error

                row = conn.execute(
                    "SELECT rowid FROM session_vmem WHERE internal_session_id = ? "
                    "AND obj_id = ? AND residency_state = ? AND durability = ?",
                    (
                        self.internal_id,
                        obj.obj_id,
                        ResidencyState.EVICTED.value,
                        DURABILITY_CLEAN,
                    ),
                ).fetchone()
                if row is None:
                    continue  # VERIFY failed defensively: never fabricate a manifest row

                obj.residency_state = ResidencyState.EVICTED
                evicted.append(obj)
                manifest_rows.append(
                    {
                        "obj_id": obj.obj_id,
                        "sha": obj.content_sha256,
                        "recovery_class": obj.recovery_class,
                        "seq": row["rowid"],
                        "reason": reason,
                    }
                )

            self._advance_watermark(conn)
            conn.commit()

        if manifest_rows:
            self._append_reclaim_manifest(manifest_rows)

        return evicted


    def evict_to_budget(
        self,
        max_tokens: int = DEFAULT_HOT_CONTEXT_BUDGET_TOKENS,
        pin_recent_messages: int = 0,
        remaining_turns: int | None = None,
    ) -> list[SessionObject]:
        """
        Cache-priced cost-model eviction (plan T2.1, Deep Upgrade Plan U4 §5.3-5.7):
        Net benefit = benefit - cost for each unpinned resident candidate:
          R = remaining_turns_estimate(session) or default_remaining_turns
          suffix_o = sum(tokens of resident objects created after o)
          benefit = o.tokens * R * cache_read_multiplier
          cost = suffix_o * (cache_write_multiplier - cache_read_multiplier)
                 + p_fault(o) * (o.tokens + fault_in_turn_cost_tokens)
          p_fault = 0.5 if kind in (DECISION, BLOCKER) else 0.2 if access_count > 1 else 0.05
          net = benefit - cost

        Candidates with net > 0 are sorted descending by net and evicted until under budget.
        If still over budget and no candidates have net > 0, fallback to old sort order
        (priority_score, access_count, -token_estimate) and log forced_eviction=1.
        Under budget slack: do not evict.
        Record decisions(kind="eviction", propensity=1.0) with chosen and top 5 alternatives.
        Preserves T2.0 coverage-before-reclaim four-phase flow via self._reclaim.
        """
        resident_objects = self.list_objects()
        resident_active = [
            o for o in resident_objects
            if o.residency_state in (ResidencyState.RESIDENT, ResidencyState.FAULTED_IN)
        ]

        total_tokens = sum(o.token_estimate for o in resident_active)
        if total_tokens <= max_tokens:
            return []

        # Load economics configuration
        econ = _load_economics_parameters(self.home)
        cache_read = float(econ["cache_read"])
        cache_write = float(econ["cache_write"])
        fault_turn_cost = int(econ["fault_in_turn_cost_tokens"])
        default_r = int(econ["default_remaining_turns"])

        r_turns = (
            remaining_turns
            if remaining_turns is not None and remaining_turns > 0
            else remaining_turns_estimate(self.home, self.session_id, default_turns=default_r)
        )

        # Determine creation order using rowid from SQLite
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT rowid, obj_id FROM session_vmem "
                "WHERE internal_session_id = ? "
                "ORDER BY rowid ASC",
                (self.internal_id,),
            ).fetchall()
        creation_seq: dict[str, int] = {r["obj_id"]: r["rowid"] for r in rows}

        # Order resident objects by creation sequence
        resident_by_creation = sorted(
            resident_active,
            key=lambda o: creation_seq.get(o.obj_id, 0),
        )

        # Suffix invalidation tokens: sum of tokens of resident objects created AFTER o
        suffix_map: dict[str, int] = {}
        running_suffix = 0
        for o in reversed(resident_by_creation):
            suffix_map[o.obj_id] = running_suffix
            running_suffix += o.token_estimate

        # Identify candidate pool: resident, unpinned, not within pin_recent_messages
        all_unpinned = [o for o in resident_active if not o.pinned]
        if pin_recent_messages > 0:
            pinned_recent_ids = {
                o.obj_id for o in resident_by_creation[-pin_recent_messages:]
            }
            candidates = [o for o in all_unpinned if o.obj_id not in pinned_recent_ids]
        else:
            candidates = all_unpinned

        if not candidates:
            return []

        # Compute cost-model net score for each candidate
        net_map: dict[str, float] = {}
        for o in candidates:
            if o.kind in (
                SessionObjectKind.DECISION,
                SessionObjectKind.BLOCKER,
                "DECISION",
                "BLOCKER",
            ):
                p_fault = 0.5
            elif o.access_count > 1:
                p_fault = 0.2
            else:
                p_fault = 0.05

            tok = o.token_estimate
            suf = suffix_map.get(o.obj_id, 0)
            benefit = tok * r_turns * cache_read
            cost = suf * (cache_write - cache_read) + p_fault * (tok + fault_turn_cost)
            net_map[o.obj_id] = benefit - cost

        # Step 1: Candidates with net > 0 sorted in descending net order
        positive_candidates = sorted(
            [o for o in candidates if net_map[o.obj_id] > 0],
            key=lambda o: (
                -net_map[o.obj_id],
                o.priority_score,
                o.access_count,
                -o.token_estimate,
            ),
        )

        victims: list[SessionObject] = []
        running_total = total_tokens
        for obj in positive_candidates:
            if running_total <= max_tokens:
                break
            victims.append(obj)
            running_total -= obj.token_estimate

        # Step 2: If no candidates with net > 0 or still over budget, fallback to old sort order
        forced_eviction = 0
        if running_total > max_tokens:
            forced_eviction = 1
            logger.warning(
                "forced_eviction=1 session=%s over_budget=%d tokens_remaining=%d",
                self.session_id,
                running_total - max_tokens,
                running_total,
            )
            fallback_candidates = sorted(
                [o for o in candidates if o not in victims],
                key=lambda o: (
                    o.priority_score,
                    o.access_count,
                    -o.token_estimate,
                    creation_seq.get(o.obj_id, 0),
                ),
            )
            for obj in fallback_candidates:
                if running_total <= max_tokens:
                    break
                victims.append(obj)
                running_total -= obj.token_estimate

        # Step 3: Record decision
        unchosen = [o for o in candidates if o not in victims]
        unchosen_sorted = sorted(
            unchosen,
            key=lambda o: (
                -net_map.get(o.obj_id, 0.0),
                o.priority_score,
                o.access_count,
            ),
        )
        alternatives = [
            {
                "obj_id": o.obj_id,
                "kind": o.kind.value,
                "net": round(net_map.get(o.obj_id, 0.0), 3),
            }
            for o in unchosen_sorted[:5]
        ]
        chosen = [
            {
                "obj_id": o.obj_id,
                "kind": o.kind.value,
                "net": round(net_map.get(o.obj_id, 0.0), 3),
            }
            for o in victims
        ]
        # Resolve rollout stage from config/v2.toml [rollout] brainstem or default SHADOW
        rollout_stage = "SHADOW"
        try:
            v2_raw = tomllib.loads(
                (self.home / "config" / "v2.toml").read_text(encoding="utf-8")
            )
            stage_val = (
                (v2_raw.get("rollout") or {}).get("brainstem", "SHADOW")
                if isinstance(v2_raw, dict)
                else "SHADOW"
            )
            if stage_val in decisions._ROLLOUT_STAGES:
                rollout_stage = stage_val
        except Exception:
            pass

        try:
            decisions.record(
                self.home,
                kind="eviction",
                session_id=self.session_id,
                task_id=None,
                chosen=chosen,
                alternatives=alternatives,
                propensity=1.0,
                randomized=False,
                policy_version="v2.1",
                stage=rollout_stage,
                inputs={
                    "max_tokens": max_tokens,
                    "resident_tokens_before": total_tokens,
                    "candidate_count": len(candidates),
                    "forced_eviction": forced_eviction,
                    "remaining_turns": r_turns,
                },
            )
        except Exception:
            logger.debug("Eviction decision recording failed", exc_info=True)

        self.last_eviction_telemetry = {
            "forced_eviction": forced_eviction,
            "chosen_count": len(victims),
            "candidate_count": len(candidates),
            "resident_tokens_before": total_tokens,
            "max_tokens": max_tokens,
        }

        reclaim_reason = (
            "evict_to_budget:forced_eviction" if forced_eviction else "evict_to_budget"
        )
        return self._reclaim(victims, reason=reclaim_reason)

    def render_hot_context(
        self,
        max_tokens: int = DEFAULT_HOT_CONTEXT_BUDGET_TOKENS,
    ) -> dict[str, Any]:
        """
        Render the minimal hot context working set (§6.4).
        Enforces token budget, includes hot items, and indexes cold items by compact ref.
        """
        self.evict_to_budget(max_tokens=max_tokens)
        all_objs = self.list_objects()

        resident_objs = [
            o for o in all_objs
            if o.residency_state in (ResidencyState.RESIDENT, ResidencyState.FAULTED_IN)
        ]
        evicted_objs = [
            o for o in all_objs
            if o.residency_state == ResidencyState.EVICTED
        ]

        # Load active state capsule if present
        capsule_data = {}
        with contextlib.suppress(Exception):
            capsule_data = working_set.show_capsule(self.home, self.session_id)

        # Build prompt sections
        lines: list[str] = ["[SECOND_BRAIN_HOT_CONTEXT]"]

        if capsule_data:
            obj = capsule_data.get("objective", "")
            if obj:
                lines.append(f"Objective: {obj}")
            decisions = capsule_data.get("decisions_this_session", [])
            if decisions:
                lines.append(f"Active Decisions: {', '.join(decisions[-5:])}")
            questions = capsule_data.get("open_questions", [])
            if questions:
                lines.append(f"Blockers/Questions: {', '.join(questions[-5:])}")

        if resident_objs:
            lines.append("\n--- Resident Working State ---")
            for ro in resident_objs:
                lines.append(f"- [{ro.kind.value}] {ro.title}: {ro.summary} (ref: {ro.obj_id})")

        if evicted_objs:
            lines.append("\n--- Cold Indexed Refs (Recoverable via /brain-get-ref <id>) ---")
            for eo in evicted_objs[:MAX_REF_TABLE_ENTRIES]:
                ref_line = (
                    f"- [Ref: {eo.obj_id}] ({eo.kind.value}) {eo.title} (~{eo.token_estimate}t)"
                )
                lines.append(ref_line)

        rendered_text = "\n".join(lines)
        return {
            "session_id": self.session_id,
            "resident_count": len(resident_objs),
            "evicted_count": len(evicted_objs),
            "resident_tokens": sum(o.token_estimate for o in resident_objs),
            "rendered_text": rendered_text,
            "resident_objects": [o.to_dict() for o in resident_objs],
            "evicted_refs": [
                {
                    "obj_id": o.obj_id,
                    "kind": o.kind.value,
                    "title": o.title,
                    "tokens": o.token_estimate,
                }
                for o in evicted_objs[:MAX_REF_TABLE_ENTRIES]
            ],
        }

    def prepare_compaction(self) -> dict[str, Any]:
        """
        Compaction barrier interaction (§6.7), now coverage-gated (plan U4
        §5.5-5.7): unpinned resident items go through the same PREPARE ->
        COVERAGE -> COMMIT -> VERIFY reclaim as `evict_to_budget`. Pinned
        items are NEVER evicted, but a coverage sweep still runs over them
        -- a real host-level compaction can discard live context this
        method never touches, so `cancel` reports True (Python-side
        contract only; Prime TS wiring is a later task) whenever ANY
        pinned or material (DECISION/BLOCKER/WORKER_FINDING) object is
        still resident and DIRTY after VERIFY -- i.e. still at risk of
        unrecoverable loss.
        """
        all_objs = self.list_objects()
        resident_all = [
            o for o in all_objs
            if o.residency_state in (ResidencyState.RESIDENT, ResidencyState.FAULTED_IN)
        ]
        pinned_resident = [o for o in resident_all if o.pinned]
        unpinned_victims = [o for o in resident_all if not o.pinned]

        # COVERAGE sweep on pinned objects: never evicted, but their
        # durability must still be known for the cancel contract below.
        for obj in pinned_resident:
            self.cover(obj)

        evicted = self._reclaim(unpinned_victims, reason="prepare_compaction")

        # VERIFY: re-read every still-resident pinned/material object.
        still_resident = [
            o for o in self.list_objects()
            if o.residency_state in (ResidencyState.RESIDENT, ResidencyState.FAULTED_IN)
        ]
        dirty_material_or_pinned = [
            o for o in still_resident
            if (o.pinned or o.kind in _MATERIAL_KINDS) and o.durability != DURABILITY_CLEAN
        ]

        return {
            "session_id": self.session_id,
            "evicted_at_compaction": len(evicted),
            "pinned_preserved": len([o for o in all_objs if o.pinned]),
            "cancel": bool(dirty_material_or_pinned),
            "timestamp": _now(),
        }

    def resume_after_compaction(
        self,
        max_tokens: int = DEFAULT_HOT_CONTEXT_BUDGET_TOKENS,
    ) -> str:
        """
        Resume post-compaction using compact hot state + on-demand cold refs (§6.7).
        """
        hot_context = self.render_hot_context(max_tokens=max_tokens)
        return hot_context["rendered_text"]


_ARTIFACT_HANDLE_RE = re.compile(r"\[brain-artifact:sha256:([0-9a-f]{64})\]")


def _delivery_row(home: Path, delivery_id: str) -> dict[str, Any] | None:
    """Read one row from the existing, durable `deliveries` table (control DB
    `db/brain.sqlite`) — the same table/DB `autoinject.py`'s own
    `_delivered_keys` already reads. Read-only; never mutates deliveries.
    Includes `packet_id`/`root_session_id`/`branch_id` so callers can find
    every OTHER delivery row belonging to the same originally-selected
    AutoInject packet (see `_delivery_rows_for_packet`)."""
    conn = db.connect(_control_db_path(home), readonly=True)
    try:
        row = conn.execute(
            "SELECT delivery_id, memory_id, memory_version, packet_id, "
            "root_session_id, branch_id FROM deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _delivery_rows_for_packet(
    home: Path, packet_id: str, root_session_id: str, branch_id: str
) -> list[dict[str, Any]]:
    """The COMPLETE membership set of one originally-selected AutoInject
    packet (Part 2 of the RC4 safety pass): every `deliveries` row sharing
    the same `packet_id`, scoped defensively by `root_session_id`+
    `branch_id` (cheap extra safety — all three columns already live on the
    single delivery row `_resolve_research_result` starts from). Read-only.

    Ordered by `rowid` ascending: `deliveries` is an ordinary rowid table
    (its TEXT `delivery_id` PRIMARY KEY does not alias `rowid`, unlike an
    INTEGER PRIMARY KEY would), rows for one packet are inserted together in
    a single transaction by `autoinject.insert_deliveries` and are never
    deleted, so ascending `rowid` reliably reconstructs the original
    insertion/selection order of the packet without adding a new column."""
    conn = db.connect(_control_db_path(home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT delivery_id, memory_id, memory_version, packet_id, "
            "root_session_id, branch_id FROM deliveries "
            "WHERE packet_id = ? AND root_session_id = ? AND branch_id = ? "
            "ORDER BY rowid ASC",
            (packet_id, root_session_id, branch_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _show_memory_at_version(home: Path, memory_id: str, version: int) -> dict[str, Any]:
    """Delivered-version-aware counterpart to `semantic.show_memory` (RC4
    byte-exact recovery pass, Part A fallback path): resolves memory title/
    body AS THEY WERE AT `version`, not whatever the CURRENT row says. Reuses
    the existing `memory_versions` table exactly as `semantic.history()`
    already reads it -- no new memory-versioning subsystem. Returns the
    CURRENT row's data (unchanged) when `version == current_version`;
    otherwise reads the archived `memory_versions` row for `title`/
    `body_path` and loads THAT file. Other row fields (status,
    evidence_grade, scope, summary, current_version) are not versioned by
    `memory_versions` and are returned from the current row unchanged -- only
    `title`/`body` reflect the delivered version, same as `current_version`
    in the caller's item dict is deliberately kept distinct from
    `delivered_version`. Raises the same `BrainError` semantics
    `semantic.show_memory` already uses on a missing/corrupt file."""
    conn = db.connect(_control_db_path(home), readonly=True)
    try:
        row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        if row is None:
            raise BrainError(f"Unknown memory {memory_id!r}")
        row = dict(row)
        current_version = row["current_version"]
        if version == current_version:
            body_path = row["body_path"]
            resolved_row = row
        else:
            vrow = conn.execute(
                "SELECT * FROM memory_versions WHERE memory_id = ? AND version = ?",
                (memory_id, version),
            ).fetchone()
            if vrow is None:
                raise BrainError(f"No archived version {version} for memory {memory_id!r}")
            vrow = dict(vrow)
            body_path = vrow["body_path"]
            resolved_row = dict(row)
            resolved_row["title"] = vrow["title"]  # the DELIVERED version's title
    finally:
        conn.close()

    path = Path(home) / body_path if body_path else None
    if path is None or not path.exists():
        raise BrainError(f"Memory file missing for {memory_id!r} v{version}: {path}")
    body = path.read_text(encoding="utf-8")
    if not body.startswith("---\n") or "\n---" not in body:
        raise BrainError(f"Corrupt memory file {path}: missing frontmatter")
    return {"row": resolved_row, "path": str(path), "body": body}


def _resolve_research_result_from_artifact(
    packet_artifact_ref: str, packet_sha256: str, obj: SessionObject, home: Path
) -> dict[str, Any]:
    """PRIMARY path (RC4 byte-exact AutoInject recovery pass, Part A): the
    exact packet bytes the model actually saw were preserved AT ADMISSION
    TIME (TS `cliArtifactPreserver`, kind="autoinject_packet" -- the same
    preserve-then-verify machinery RTD already uses for raw tool output).
    Resolve via the SAME content-addressed artifact store
    `_resolve_tool_observation` already reads (`artifacts.expand`),
    sha256-verify the loaded bytes match `packetSha256` EXACTLY (same
    discipline as `VMemStore._verify_and_load`'s own hash check), and return
    that byte-exact text. No `semantic.show_memory`/DB lookup on this path at
    all -- current/superseded memory state is irrelevant once the packet
    itself is preserved."""
    match = _ARTIFACT_HANDLE_RE.search(packet_artifact_ref)
    sha_or_prefix = match.group(1) if match else packet_artifact_ref.strip()
    try:
        raw = artifacts.expand(home, sha_or_prefix)
    except BrainError as exc:
        return {"ok": False, "error": str(exc)}
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != packet_sha256:
        return {
            "ok": False,
            "error": (
                f"AutoInject packet artifact corrupt: expected sha256 "
                f"{packet_sha256}, got {actual_sha}"
            ),
        }
    try:
        content_text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"ok": False, "error": f"packet artifact is not valid UTF-8 text: {exc}"}
    delivery_id = obj.metadata.get("deliveryId") or obj.metadata.get("delivery_id")
    return {
        "ok": True,
        "resolution": "packet_artifact",
        "packet_artifact_ref": packet_artifact_ref,
        "packet_sha256": packet_sha256,
        "delivery_id": delivery_id,
        "content": content_text,
        "byte_exact": True,
    }


def _resolve_research_result(home: Path, obj: SessionObject, stored_content: str) -> dict[str, Any]:
    """RESEARCH_RESULT (Part D Â§2, extended by the RC4 safety pass Part 2,
    then made byte-exact by the RC4 byte-exact recovery pass Part A).

    PRIMARY path: when admission preserved the EXACT packet bytes the model
    saw (`obj.metadata["packetArtifactRef"]`/`["packetSha256"]`), resolve
    those bytes directly through the content-addressed artifact store --
    byte-exact, independent of current/superseded memory state
    (`_resolve_research_result_from_artifact`).

    FALLBACK path (older, pre-this-pass VMem objects with no
    packetArtifactRef): delivery_id -> `deliveries` -> every sibling
    delivery row sharing the SAME packet (an AutoInject packet can carry
    multiple selected memories, one `deliveries` row each) -> each row's
    DELIVERED version specifically (`_show_memory_at_version`, not whatever
    `semantic.show_memory` currently returns) -> a compact, deterministic
    reconstruction of the COMPLETE packet.

    Partial-failure semantics (fallback path): if ANY member of the packet
    fails to resolve (missing memory row, missing archived version, etc.)
    the WHOLE resolution fails clearly (`ok: False`) rather than silently
    returning an incomplete set -- consistent with Part 1's
    no-lossy-partial-success requirement."""
    packet_artifact_ref = obj.metadata.get("packetArtifactRef") or obj.metadata.get(
        "packet_artifact_ref"
    )
    packet_sha256 = obj.metadata.get("packetSha256") or obj.metadata.get("packet_sha256")
    if (
        isinstance(packet_artifact_ref, str)
        and packet_artifact_ref
        and isinstance(packet_sha256, str)
        and packet_sha256
    ):
        return _resolve_research_result_from_artifact(packet_artifact_ref, packet_sha256, obj, home)

    delivery_id = obj.metadata.get("deliveryId") or obj.metadata.get("delivery_id")
    if not isinstance(delivery_id, str) or not delivery_id:
        try:
            parsed = json.loads(stored_content)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            delivery_id = parsed.get("delivery_id")
    if not isinstance(delivery_id, str) or not delivery_id:
        return {"ok": False, "error": "no resolvable delivery_id for this RESEARCH_RESULT object"}

    delivery = _delivery_row(home, delivery_id)
    if delivery is None:
        return {"ok": False, "error": f"delivery not found: {delivery_id}"}

    packet_rows = _delivery_rows_for_packet(
        home, delivery["packet_id"], delivery["root_session_id"], delivery["branch_id"]
    )
    if not packet_rows:
        # Defensive fallback only: `delivery` itself always qualifies for its
        # own packet scope, so this should be unreachable in practice.
        packet_rows = [delivery]

    items: list[dict[str, Any]] = []
    for row in packet_rows:
        member_memory_id = row["memory_id"]
        delivered_version = row["memory_version"]
        try:
            shown = _show_memory_at_version(home, member_memory_id, delivered_version)
        except BrainError as exc:
            return {
                "ok": False,
                "error": (
                    f"packet member unresolvable (delivery {row['delivery_id']}, "
                    f"memory {member_memory_id} v{delivered_version}): {exc}"
                ),
            }
        mrow = shown["row"]
        items.append(
            {
                "delivery_id": row["delivery_id"],
                "memory_id": member_memory_id,
                "delivered_version": delivered_version,
                "current_version": mrow.get("current_version"),
                "title": mrow.get("title"),
                "status": mrow.get("status"),
                "evidence_grade": mrow.get("evidence_grade"),
                "scope": mrow.get("scope"),
                "summary": mrow.get("summary"),
                "body": shown["body"],
            }
        )

    if len(items) == 1:
        only = items[0]
        return {
            "ok": True,
            "resolution": "memory",
            "delivery_id": only["delivery_id"],
            "memory_id": only["memory_id"],
            "content": contracts.canonical_json(only),
        }

    return {
        "ok": True,
        "resolution": "memory_set",
        "delivery_id": delivery_id,
        "packet_id": delivery["packet_id"],
        "memory_ids": [it["memory_id"] for it in items],
        "delivery_ids": [it["delivery_id"] for it in items],
        "item_count": len(items),
        "content": contracts.canonical_json({"packet_id": delivery["packet_id"], "items": items}),
    }


def _resolve_tool_observation(
    home: Path, obj: SessionObject, stored_content: str
) -> dict[str, Any]:
    """TOOL_OBSERVATION (Part D §2): artifact_ref -> the existing content-
    addressed artifact store (`artifacts.expand`, the same read RTD's own
    `/brain-expand` recovery path already uses) -> the BYTE-EXACT original
    content. Decoded as UTF-8 here for the JSON/text CLI surface; RTD only
    ever preserves text-only tool output (`textFromContent` in rtd.ts never
    distills binary/image blocks), so real artifacts are always valid text."""
    artifact_ref = obj.metadata.get("artifactRef") or obj.metadata.get("artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref:
        try:
            parsed = json.loads(stored_content)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            artifact_ref = parsed.get("artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref:
        return {"ok": False, "error": "no resolvable artifact_ref for this TOOL_OBSERVATION object"}

    match = _ARTIFACT_HANDLE_RE.search(artifact_ref)
    sha_or_prefix = match.group(1) if match else artifact_ref.strip()
    try:
        raw = artifacts.expand(home, sha_or_prefix)
    except BrainError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"ok": False, "error": f"artifact content is not valid UTF-8 text: {exc}"}
    return {
        "ok": True,
        "resolution": "artifact",
        "artifact_ref": artifact_ref,
        "content": text,
        "byte_exact": True,
    }


def resolve_object(home: Path | str, session_id: str, obj_id: str) -> dict[str, Any]:
    """Explicit fault-in + durable backing resolution (Part D, extended by
    the RC4 safety pass to be TRANSACTIONAL w.r.t. recovery).

    Ordering is deliberate and load-bearing — the residency/access/priority
    DB write must be the LAST thing that happens, and only if EVERYTHING
    before it succeeded:

    1. Read-only verify+load (`VMemStore._verify_and_load`): confirm the
       object exists and its OWN small stored VMem backing artifact loads
       and hash-verifies. Raises `BrainError` on failure; no DB write.
    2. Read-only deeper resolution based on `obj.kind` through the EXISTING
       durable backing sources (Part C): RESEARCH_RESULT -> deliveries+
       memories (now resolving the COMPLETE originally-selected packet, not
       just one memory — RC4 safety pass Part 2); TOOL_OBSERVATION -> the
       content-addressed artifact store (byte-exact); anything else -> the
       raw stored content unchanged (no special resolution attempted). This
       step reports `{"ok": False, "error": ...}` on any failure — it never
       raises.
    3. ONLY if step 2 reported `ok: True`: perform the ONE DB write
       (`VMemStore._mutate_fault_in` — the same residency EVICTED-
       >FAULTED_IN transition, access_count bump, and priority boost
       `fault_in` has always done) and merge the updated object into the
       response.

    On ANY failure at steps 1-2: NO DB write happens at all — residency
    state, access_count, and priority_score are byte-for-byte unchanged from
    before the call; returns `{"ok": False, "error": "..."}`. This function
    never raises (VMemStore's own lower-level methods may still raise
    `BrainError`, same as always — this is what catches it).

    No LLM summarizer anywhere in this path — deterministic resolution only.
    """
    home = Path(home)
    try:
        store = VMemStore(home, session_id)
        obj, stored_content = store._verify_and_load(obj_id)
    except BrainError as exc:
        return {"ok": False, "error": str(exc)}

    if obj.kind == SessionObjectKind.RESEARCH_RESULT:
        result = _resolve_research_result(home, obj, stored_content)
    elif obj.kind == SessionObjectKind.TOOL_OBSERVATION:
        result = _resolve_tool_observation(home, obj, stored_content)
    else:
        # Not in scope for paging (Part B only pages RESEARCH_RESULT /
        # TOOL_OBSERVATION) — no special resolution attempted, but the CLI
        # must not crash on it: pass the raw stored content through.
        result = {"ok": True, "resolution": "raw", "content": stored_content}

    if not result.get("ok"):
        # Zero mutation: the deeper resolution failed, so the residency/
        # access/priority DB write never happens.
        return result

    try:
        obj = store._mutate_fault_in(obj)
    except (BrainError, sqlite3.Error, OSError) as exc:
        # RC4 byte-exact recovery pass Part B: the ONE DB write itself can
        # still fail (SQLite busy/locked, disk I/O error) even though every
        # read-only resolution step above already succeeded. That must not
        # be reported as a completed fault-in -- SQLite statement-level
        # atomicity plus `_mutate_fault_in`'s own `with sqlite3.connect(...)`
        # context manager already guarantee no partial row mutation occurs
        # on this exception; this handler's only job is to CATCH it and
        # report a structured failure instead of letting it propagate
        # (`resolve_object` documents itself as "never raises").
        return {"ok": False, "error": f"fault-in DB write failed: {exc}"}

    result["obj"] = obj.to_dict()
    result["obj_id"] = obj.obj_id
    result["kind"] = obj.kind.value
    return result
