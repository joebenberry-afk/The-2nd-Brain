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
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import artifacts, ledger, working_set
from .errors import BrainError

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

    def fault_in(self, obj_id: str) -> tuple[SessionObject, str]:
        """
        Page an evicted or stored object back into active context (§6.5).
        Transitions state to FAULTED_IN, updates access counters, and returns raw content.
        """
        obj = self.get_object(obj_id)
        if not obj:
            raise BrainError(f"Session object not found: {obj_id}")

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
                (new_state.value, new_count, now, new_priority, self.internal_id, obj_id),
            )
            conn.commit()

        obj.residency_state = new_state
        obj.access_count = new_count
        obj.last_accessed_at = now
        obj.priority_score = new_priority

        raw_bytes = artifacts.expand(self.home, obj.content_sha256)
        content = raw_bytes.decode("utf-8", errors="replace")
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
