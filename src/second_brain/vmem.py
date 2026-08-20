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
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import artifacts, contracts, db, ledger, working_set
from .errors import BrainError
from .paths import db_path as _control_db_path

DEFAULT_HOT_CONTEXT_BUDGET_TOKENS = 1500
MAX_REF_TABLE_ENTRIES = 25


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
"""


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
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _estimate_tokens(text: str) -> int:
    """Deterministic token estimate: roughly 4 characters per token."""
    return max(1, len(text) // 4)


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
    ) -> SessionObject:
        """Store a transient session object with content-addressed backing."""
        if isinstance(kind, str):
            try:
                kind = SessionObjectKind(kind.upper())
            except ValueError:
                kind = SessionObjectKind.GENERIC

        # Backing store exact bytes
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
        tokens = _estimate_tokens(content)
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

        results = []
        for r in rows:
            results.append(
                SessionObject(
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
                )
            )
        return results

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
        )

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

    def evict_to_budget(
        self,
        max_tokens: int = DEFAULT_HOT_CONTEXT_BUDGET_TOKENS,
    ) -> list[SessionObject]:
        """
        Deterministic admission/eviction policy (§6.6).
        Evicts lowest-scoring unpinned items until resident tokens <= max_tokens.
        """
        resident_objects = self.list_objects()
        resident_active = [
            o for o in resident_objects
            if o.residency_state in (ResidencyState.RESIDENT, ResidencyState.FAULTED_IN)
        ]

        total_tokens = sum(o.token_estimate for o in resident_active)
        if total_tokens <= max_tokens:
            return []

        # Sort eviction candidates: unpinned first, lowest priority score, lowest access count
        candidates = sorted(
            [o for o in resident_active if not o.pinned],
            key=lambda o: (o.priority_score, o.access_count, -o.token_estimate),
        )

        evicted: list[SessionObject] = []
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            for obj in candidates:
                if total_tokens <= max_tokens:
                    break
                conn.execute(
                    """
                    UPDATE session_vmem
                    SET residency_state = ?
                    WHERE internal_session_id = ? AND obj_id = ?
                    """,
                    (ResidencyState.EVICTED.value, self.internal_id, obj.obj_id),
                )
                obj.residency_state = ResidencyState.EVICTED
                evicted.append(obj)
                total_tokens -= obj.token_estimate
            conn.commit()

        return evicted

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
        Compaction barrier interaction (§6.7).
        Snapshots working state and transitions unpinned resident items to EVICTED.
        """
        all_objs = self.list_objects()
        unpinned_residents = [
            o for o in all_objs
            if not o.pinned
            and o.residency_state in (ResidencyState.RESIDENT, ResidencyState.FAULTED_IN)
        ]

        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            for obj in unpinned_residents:
                conn.execute(
                    """
                    UPDATE session_vmem
                    SET residency_state = ?
                    WHERE internal_session_id = ? AND obj_id = ?
                    """,
                    (ResidencyState.EVICTED.value, self.internal_id, obj.obj_id),
                )
            conn.commit()

        return {
            "session_id": self.session_id,
            "evicted_at_compaction": len(unpinned_residents),
            "pinned_preserved": len([o for o in all_objs if o.pinned]),
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
