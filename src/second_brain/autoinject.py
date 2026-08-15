"""P0 AutoInject pipeline — SHADOW (plan §6.1-6.8, §6.11, §6.12; Phase 0C).

Python is the control/storage authority. This module decides and records only:
it never mutates model context (the Prime/Codex adapters do that in 0D after
the SHADOW gate). Pipeline per §6.1:

    task/session event -> RetrievalIntent -> candidates (semantic.search_memories)
    -> validity gate (§6.3 hard filters) -> dedupe vs delivery ledger (§6.5)
    -> token budget (§6.6) -> NO_INJECTION | canonical BrainPacket delta.

Fail-open (§6.8): every failure path degrades to
NO_INJECTION(BRAIN_UNAVAILABLE) and never raises into the caller. Telemetry
follows SCHEMA.md v2 privacy rules: counts/ids/hashes only — no task text,
no memory content, no credentials.

Observability per §6.12: every decision records task identity (sha256, not
text), candidates, selected IDs, reason, packet size, recipient, and source
versions via `brain_retrieval_attempt` / `brain_no_injection` /
`brain_packet_delivered` JSONL kinds.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import re
import sqlite3
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db, semantic, telemetry
from .contracts import (
    BrainInjectionDecision,
    BrainLifecycleEvent,
    BrainPacket,
    BrainSessionIdentity,
    Confidence,
    InjectionDecision,
    MemoryItemStatus,
    NoInjectionReason,
    PacketItem,
    canonical_json,
)
from .paths import db_path

logger = logging.getLogger(__name__)

DEFAULT_TARGET_TOKENS = 800
DEFAULT_HARD_CAP_TOKENS = 2000
_MAX_CANDIDATES = 10  # candidate ceiling for the shadow pipeline
_TELEMETRY_V = 2
_PACKET_CACHE_LIMIT = 64
_ENV_TARGET = "SECOND_BRAIN_AUTOINJECT_TARGET_TOKENS"
_ENV_CAP = "SECOND_BRAIN_AUTOINJECT_HARD_CAP_TOKENS"

# Rendered packet cache: packet_id -> (rendered text, items). Shadow phase
# keeps decisions deterministic without persisting packets to the canonical DB.
_PACKET_CACHE: dict[str, tuple[str, list[PacketItem]]] = {}


# ---------------------------------------------------------------------------
# Config (§6.6) and token estimation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AutoInjectConfig:
    target_tokens: int
    hard_cap_tokens: int


def _env_int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using %d", name, raw, fallback)
        return fallback


def load_config(home: Path | str) -> AutoInjectConfig:
    """config/autoinject.toml [budget] with env override; fail open to defaults."""
    target = DEFAULT_TARGET_TOKENS
    cap = DEFAULT_HARD_CAP_TOKENS
    path = Path(home) / "config" / "autoinject.toml"
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            budget = data.get("budget") or {}
            if isinstance(budget, dict):
                raw_t = budget.get("target_tokens")
                raw_c = budget.get("hard_cap_tokens")
                if isinstance(raw_t, int) and not isinstance(raw_t, bool) and raw_t > 0:
                    target = raw_t
                if isinstance(raw_c, int) and not isinstance(raw_c, bool) and raw_c > 0:
                    cap = raw_c
        except (OSError, tomllib.TOMLDecodeError):
            logger.warning("config/autoinject.toml unreadable; using defaults (fail open)")
    target = _env_int(_ENV_TARGET, target)
    cap = _env_int(_ENV_CAP, cap)
    if cap < 1:
        cap = DEFAULT_HARD_CAP_TOKENS
    if target < 1:
        target = DEFAULT_TARGET_TOKENS
    target = min(target, cap)
    return AutoInjectConfig(target_tokens=target, hard_cap_tokens=cap)


def token_estimate(text: str) -> int:
    """Rough token estimate: 4 chars per token (stdlib-only, §6.6)."""
    return max(1, len(text or "") // 4)


# ---------------------------------------------------------------------------
# Retrieval intent and candidate sources.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalIntent:
    """Structured retrieval intent (plan §6.1): task text stays ephemeral.

    ``task_text`` is used only to query; it is never persisted to the
    canonical DB or telemetry (only its sha256 is recorded).
    """

    task_text: str
    project_id: str | None
    agent_id: str
    role_profile: str
    session_id: str
    branch_id: str = "main"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _task_sha256(task: str) -> str:
    return hashlib.sha256((task or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Validity gate (§6.3): hard filters BEFORE scoring. Ranking stays inside
# semantic.search_memories (reused unchanged); this gate only ADDS the
# validity dimensions the plan requires and never re-scores.
# ---------------------------------------------------------------------------


def _valid_candidates(intent: RetrievalIntent, rows: list[dict]) -> list[dict]:
    """§6.3.1 hard filters: wrong project (unless global scope); superseded /
    archived / REJECTED never presented as current (defensive re-check — the
    shared search already excludes them); condition compatibility is
    represented via status/scope, which the search filters enforce."""
    out: list[dict] = []
    for row in rows:
        if row.get("status") in ("superseded", "archived"):
            continue
        if row.get("evidence_grade") == "REJECTED":
            continue
        if (
            intent.project_id is None
            or row.get("scope") == "global"
            or row.get("project_id") == intent.project_id
        ):
            out.append(row)
    return out


def _grade_confidence(
    grade: str | None, strength: float | None, contradicted: bool
) -> tuple[MemoryItemStatus, Confidence]:
    """Provenance/validation strength -> status + confidence (§6.3.2)."""
    mapping: dict[str, Confidence] = {
        "VERIFIED": Confidence.HIGH,
        "TESTED": Confidence.HIGH,
        "OBSERVED": Confidence.MEDIUM,
        "INFERRED": Confidence.LOW,
        "HISTORICAL": Confidence.LOW,
    }
    confidence = mapping.get(grade or "", Confidence.MEDIUM)
    if contradicted:
        return MemoryItemStatus.CONTRADICTED, Confidence.LOW
    if grade == "HISTORICAL":
        return MemoryItemStatus.UNCERTAIN, confidence
    if strength is not None and strength < 0.5:
        demote = {
            Confidence.HIGH: Confidence.MEDIUM,
            Confidence.MEDIUM: Confidence.LOW,
        }
        confidence = demote.get(confidence, confidence)
    if confidence is Confidence.LOW:
        return MemoryItemStatus.UNCERTAIN, confidence
    return MemoryItemStatus.CURRENT, confidence


def _canonical_line(text: str | None) -> str:
    """Collapse whitespace to single spaces (the packet format is fixed-line;
    memory bodies may carry surrounding blank lines / markdown newlines)."""
    return " ".join((text or "").split())


def _build_items(home: Path | str, rows: list[dict]) -> list[PacketItem]:
    """Rows (already validity-gated, search-ranked) -> canonical packet items."""
    home = Path(home)
    items: list[PacketItem] = []
    for row in rows:
        memory_id = str(row.get("memory_id") or "")
        version = int(row.get("current_version") or 1)
        contradicted = bool(row.get("contradiction_with"))
        status, confidence = _grade_confidence(
            row.get("evidence_grade"), row.get("strength"), contradicted
        )
        body = row.get("_body") or semantic._body_text(home, row)
        supersedes: tuple[str, int] | None = None
        if version > 1:
            supersedes = (memory_id, version - 1)  # §6.4/6.5: new delta supersedes old
        items.append(
            PacketItem(
                memory_id=memory_id,
                version=version,
                status=status,
                confidence=confidence,
                title=_canonical_line(row.get("title")),
                observation=_canonical_line(body),
                guidance=_canonical_line(row.get("summary")),
                evidence=f"brain://{memory_id}/{version}",
                supersedes=supersedes,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Canonical hashing + delivery ledger dedupe (§6.5).
# ---------------------------------------------------------------------------


def item_canonical_hash(item: PacketItem) -> str:
    """sha256 of the canonical ITEM block (fixed order/labels/whitespace).

    This is the per-item dedupe key stored in ``deliveries.canonical_hash``:
    identical memory content always produces the identical hash, and any
    content change (even without a version bump) changes it.
    """
    lines: list[str] = []
    if item.supersedes is not None:
        old_id, old_ver = item.supersedes
        lines.append(f"UPDATE {item.memory_id} v{item.version} supersedes {old_id} v{old_ver}")
    lines.extend(
        [
            f"ITEM {item.memory_id}@{item.version}",
            f"status: {item.status.value}",
            f"confidence: {item.confidence.value}",
            f"title: {item.title}",
            f"observation: {item.observation}",
            f"guidance: {item.guidance}",
            f"evidence: {item.evidence}",
        ]
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _delivered_keys(home: Path | str, session_id: str, branch_id: str) -> set[tuple[str, int, str]]:
    home = Path(home)
    conn = db.connect(db_path(home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT memory_id, memory_version, canonical_hash FROM deliveries "
            "WHERE root_session_id = ? AND branch_id = ?",
            (session_id, branch_id),
        ).fetchall()
        return {(r["memory_id"], int(r["memory_version"]), r["canonical_hash"]) for r in rows}
    finally:
        conn.close()


def insert_deliveries(
    home: Path | str, intent: RetrievalIntent, decision: BrainInjectionDecision
) -> list[str]:
    """Persist one delivery row per selected item. Returns delivery_ids.

    Idempotent per lineage+item (INSERT OR IGNORE). When an item supersedes
    a previously delivered version, the old row's pointer is updated — the
    host message itself is never rewritten (§6.5). Raises on DB error; the
    caller applies fail-open.
    """
    home = Path(home)
    cached = _PACKET_CACHE.get(decision.packet_ref or "")
    if cached is None:
        raise RuntimeError(f"no cached packet for {decision.packet_ref!r}")
    _text, items = cached
    conn = db.connect(db_path(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        delivery_ids: list[str] = []
        for item in items:
            digest = hashlib.sha256(
                f"{intent.session_id}|{intent.branch_id}|{item.memory_id}|{item.version}".encode()
            ).hexdigest()
            delivery_id = f"del-{digest[:24]}"
            conn.execute(
                "INSERT OR IGNORE INTO deliveries "
                "(delivery_id, root_session_id, agent_session_id, branch_id, memory_id, "
                " memory_version, canonical_hash, packet_id, delivered_event_id, "
                " delivered_at, superseded_by_delivery_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    delivery_id,
                    intent.session_id,
                    intent.agent_id,
                    intent.branch_id,
                    item.memory_id,
                    item.version,
                    item_canonical_hash(item),
                    decision.packet_ref,
                    f"ev-{delivery_id}",
                    _now(),
                ),
            )
            delivery_ids.append(delivery_id)
            if item.supersedes is not None:
                old_id, old_ver = item.supersedes
                conn.execute(
                    "UPDATE deliveries SET superseded_by_delivery_id = ? "
                    "WHERE root_session_id = ? AND branch_id = ? AND memory_id = ? "
                    "AND memory_version = ? AND superseded_by_delivery_id IS NULL",
                    (delivery_id, intent.session_id, intent.branch_id, old_id, old_ver),
                )
        conn.commit()
        return delivery_ids
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Packet assembly, budget (§6.6), and the decision.
# ---------------------------------------------------------------------------


def _packet_id(items: list[PacketItem]) -> str:
    digest = hashlib.sha256(
        "\n".join(f"{i.memory_id}@{i.version}" for i in items).encode("utf-8")
    ).hexdigest()
    return f"pkt-{digest[:16]}"


def _render_packet_text(items: list[PacketItem], project: str | None) -> str:
    pkt = BrainPacket(
        packet_id=_packet_id(items),
        project=project or "global",
        scope="task",
        authority="advisory",
        items=items,
    )
    return pkt.render()


def _ids_only(items: list[PacketItem]) -> list[PacketItem]:
    """§6.6 pressure step 2: IDs/title/evidence only (observation/guidance dropped)."""
    return [
        PacketItem(
            memory_id=i.memory_id,
            version=i.version,
            status=i.status,
            confidence=i.confidence,
            title=i.title,
            observation="",
            guidance="",
            evidence=i.evidence,
            supersedes=i.supersedes,
        )
        for i in items
    ]


def _fit_budget(
    items: list[PacketItem], project: str | None, config: AutoInjectConfig
) -> tuple[list[PacketItem], bool] | None:
    """§6.6: drop low-value tail toward target; then IDs-only; then None
    (caller emits NO_INJECTION(CONTEXT_PRESSURE)). Never exceeds hard cap."""
    def est(candidate: list[PacketItem]) -> int:
        return token_estimate(_render_packet_text(candidate, project))

    best = list(items)
    while len(best) > 1 and est(best) > config.target_tokens:
        best = best[:-1]  # ranked best-first; tail = lowest value
    if est(best) <= config.hard_cap_tokens:
        return best, False
    ids = _ids_only(best)
    if est(ids) <= config.hard_cap_tokens:
        return ids, True
    return None


def _cache_packet(packet_id: str, text: str, items: list[PacketItem]) -> None:
    _PACKET_CACHE[packet_id] = (text, items)
    while len(_PACKET_CACHE) > _PACKET_CACHE_LIMIT:
        _PACKET_CACHE.pop(next(iter(_PACKET_CACHE)))


def render_packet(decision: BrainInjectionDecision) -> str | None:
    """Rendered canonical packet for an INJECT decision (or None)."""
    cached = _PACKET_CACHE.get(decision.packet_ref or "")
    return cached[0] if cached is not None else None


def prepare_injection(
    home: Path | str,
    intent: RetrievalIntent,
    *,
    config: AutoInjectConfig | None = None,
) -> BrainInjectionDecision:
    """SHADOW decision pipeline. NEVER raises: every failure degrades to
    NO_INJECTION(BRAIN_UNAVAILABLE) (§6.8). No model-visible mutation."""
    home = Path(home)
    cfg = config or load_config(home)
    empty = BrainInjectionDecision(
        decision=InjectionDecision.NO_INJECTION,
        reason=None,
        candidate_ids=[],
        selected_ids=[],
        packet_ref=None,
        packet_token_size=None,
        recipient=intent.agent_id,
    )

    def decision(
        reason: NoInjectionReason,
        *,
        candidate_ids: list[str] | None = None,
        selected_ids: list[str] | None = None,
    ) -> BrainInjectionDecision:
        return dataclasses.replace(
            empty,
            reason=reason,
            candidate_ids=list(candidate_ids) if candidate_ids is not None else [],
            selected_ids=list(selected_ids) if selected_ids is not None else [],
        )

    try:
        db.migrate(db_path(home))
        rows = semantic.search_memories(
            home,
            intent.task_text,
            project_id=None,  # project/global filtering happens in the gate below
            include_history=False,
            top_k=_MAX_CANDIDATES,
            max_tokens=None,
        )
    except Exception as exc:  # fail-open contract (§6.8)
        logger.warning("AutoInject retrieval failed (fail-open): %s", exc)
        return decision(NoInjectionReason.BRAIN_UNAVAILABLE)

    candidate_ids = [str(r.get("memory_id")) for r in rows if r.get("memory_id")]
    if not rows:
        return decision(NoInjectionReason.NO_RELEVANT_MEMORY)
    valid = _valid_candidates(intent, rows)
    if not valid:
        return decision(NoInjectionReason.WRONG_PROJECT, candidate_ids=candidate_ids)

    try:
        delivered = _delivered_keys(home, intent.session_id, intent.branch_id)
    except sqlite3.Error as exc:  # fail-open (§6.8)
        logger.warning("AutoInject ledger read failed (fail-open): %s", exc)
        return decision(NoInjectionReason.BRAIN_UNAVAILABLE, candidate_ids=candidate_ids)

    items = _build_items(home, valid)
    fresh = [
        item
        for item in items
        if (item.memory_id, item.version, item_canonical_hash(item)) not in delivered
    ]
    if not fresh:
        return decision(
            NoInjectionReason.ALREADY_DELIVERED,
            candidate_ids=candidate_ids,
            selected_ids=[i.memory_id for i in items],
        )

    # Contradiction policy (§6.3/P0-G4): a contradicted top candidate is
    # withheld rather than silently presented; non-top ones stay labeled.
    if fresh[0].status is MemoryItemStatus.CONTRADICTED:
        return decision(
            NoInjectionReason.CONTRADICTORY_UNRESOLVED,
            candidate_ids=candidate_ids,
            selected_ids=[i.memory_id for i in fresh],
        )

    fit = _fit_budget(fresh, intent.project_id, cfg)
    if fit is None:
        return decision(
            NoInjectionReason.CONTEXT_PRESSURE,
            candidate_ids=candidate_ids,
            selected_ids=[i.memory_id for i in fresh],
        )
    selected, ids_only = fit
    del ids_only  # shadow phase: caller sees the same canonical shape either way
    text = _render_packet_text(selected, intent.project_id)
    packet_id = _packet_id(selected)
    _cache_packet(packet_id, text, selected)
    return dataclasses.replace(
        empty,
        decision=InjectionDecision.INJECT,
        reason=None,
        candidate_ids=candidate_ids,
        selected_ids=[i.memory_id for i in selected],
        packet_ref=packet_id,
        packet_token_size=token_estimate(text),
    )


# ---------------------------------------------------------------------------
# Telemetry (§6.12, SCHEMA.md v2): privacy-safe JSONL, best-effort.
# ---------------------------------------------------------------------------


def _sanitize_stem(session: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]", "-", session or "")
    if stem:
        return stem
    return f"anon-{_task_sha256(session or '')[:12]}"


def _append_telemetry(home: Path | str, session: str, kind: str, extra: dict[str, Any]) -> None:
    try:
        tdir = telemetry.telemetry_dir(Path(home))
        tdir.mkdir(parents=True, exist_ok=True)
        record = {"v": _TELEMETRY_V, "ts": _now(), "kind": kind, "session": session, **extra}
        with open(tdir / f"{_sanitize_stem(session)}.jsonl", "a", encoding="utf-8") as f:
            f.write(canonical_json(record) + "\n")
    except OSError as exc:
        logger.warning("AutoInject telemetry append failed (ignored): %s", exc)


# ---------------------------------------------------------------------------
# BrainLifecycle control adapter (§6.9).
# ---------------------------------------------------------------------------


class BrainLifecycle:
    """Control/storage adapter for the AutoInject pipeline (§6.9).

    SHADOW: ``prepare_injection`` decides + records only. Fail-open: it never
    raises; ledger/telemetry write failures are logged and ignored.
    """

    def __init__(self, home: Path | str, session: BrainSessionIdentity | None = None) -> None:
        self._home = Path(home)
        self._session = session
        self._last_delivery_ids: list[str] = []

    @property
    def last_delivery_ids(self) -> list[str]:
        return list(self._last_delivery_ids)

    def start_session(self, identity: BrainSessionIdentity) -> BrainSessionIdentity:
        self._session = identity
        _append_telemetry(
            self._home,
            identity.host_session_id,
            "session_started",
            {"host": identity.host, "host_session_id": identity.host_session_id},
        )
        return identity

    def prepare_injection(
        self,
        task: str,
        *,
        project_id: str | None = None,
        agent_id: str = "driver",
        role_profile: str = "orchestrator",
        session_id: str | None = None,
        branch_id: str = "main",
        context: dict[str, Any] | None = None,
    ) -> BrainInjectionDecision:
        """Shadow decision + ledger/telemetry record. Never raises."""
        del context  # reserved for 0D adapter integration
        effective_session = session_id or (
            self._session.host_session_id if self._session is not None else "anon"
        )
        intent = RetrievalIntent(
            task_text=task,
            project_id=project_id,
            agent_id=agent_id,
            role_profile=role_profile,
            session_id=effective_session,
            branch_id=branch_id,
        )
        decision = prepare_injection(self._home, intent)
        self._last_delivery_ids = []
        _append_telemetry(
            self._home,
            effective_session,
            "brain_retrieval_attempt",
            {
                "task_sha256": _task_sha256(task),
                "candidate_count": len(decision.candidate_ids),
                "recipient": agent_id,
                "role_profile": role_profile,
                "project_id": project_id,
            },
        )
        if decision.decision is InjectionDecision.INJECT:
            packet_text = render_packet(decision)
            try:
                self._last_delivery_ids = insert_deliveries(self._home, intent, decision)
            except Exception as exc:  # fail-open (§6.8)
                logger.warning("AutoInject ledger write failed (fail-open): %s", exc)
            _append_telemetry(
                self._home,
                effective_session,
                "brain_packet_delivered",
                {
                    "packet_id": decision.packet_ref,
                    "item_count": len(decision.selected_ids),
                    "packet_tokens": decision.packet_token_size,
                    "delivery_count": len(self._last_delivery_ids),
                    "canonical_packet_hash": (
                        hashlib.sha256(packet_text.encode("utf-8")).hexdigest()
                        if packet_text is not None
                        else None
                    ),
                },
            )
        else:
            _append_telemetry(
                self._home,
                effective_session,
                "brain_no_injection",
                {
                    "reason": decision.reason.value if decision.reason is not None else None,
                    "candidate_count": len(decision.candidate_ids),
                },
            )
        return decision

    def record_event(self, event: BrainLifecycleEvent) -> None:
        """Record one structured lifecycle event (privacy-safe, best-effort)."""
        _append_telemetry(
            self._home,
            event.internal_session_id,
            event.event_type.value,
            {
                "seq": event.seq,
                "event_id": event.event_id,
                "surface_visibility": event.surface_visibility.value,
                "ignorable": event.ignorable,
                "payload": event.payload,
                "artifact_sha256": event.artifact_sha256,
            },
        )

    def finalize_session(self) -> None:
        if self._session is not None:
            _append_telemetry(
                self._home,
                self._session.host_session_id,
                "session_finalized",
                {"internal_session_id": self._session.internal_session_id},
            )
