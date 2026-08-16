"""P0 AutoInject pipeline — SHADOW (plan §6.1-6.8, §6.11, §6.12; Phase 0C).

Python is the control/storage authority. This module decides and records only:
it never mutates model context (the Prime/Codex adapters do that in 0D after
the SHADOW gate). Pipeline per §6.1:

    task/session event -> RetrievalIntent -> candidates (semantic.search_memories)
    -> validity gate (§6.3 hard filters) -> dedupe vs delivery ledger (§6.5)
    -> token budget (§6.6) -> NO_INJECTION | canonical BrainPacket delta.

Fail-open (§6.8): every failure path degrades to
NO_INJECTION(BRAIN_UNAVAILABLE) and never raises into the caller. Telemetry
follows SCHEMA.md v2/v3 privacy rules: counts/ids/hashes only — no task text,
no memory content, no credentials.

Observability per §6.12: every decision records task identity (sha256, not
text), candidates, selected IDs, reason, packet size, recipient, and source
versions via `brain_retrieval_attempt` / `brain_no_injection` /
`brain_packet_delivered` JSONL kinds.

Visibility semantics (P3 §0A.8/§5.2, SCHEMA.md): `brain_packet_delivered`
records are the Python PREPARED/delivery-ledger state — `model_visible` is
always False and `delivery_prepared` is always True. This module cannot
observe host insertion; the Prime host-side mode-aware
`autoinject_shadow_decision.model_visible` event is the authoritative actual
model-visibility signal.
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

from . import db, registry, semantic, telemetry
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


def _resolve_project_id(
    home: Path | str, cwd: str | None, explicit: str | None
) -> str:
    """Project resolution ladder (Phase C2 FIX 1):

    ``--project`` > Brain project registry (root containing cwd) >
    ``SECOND_BRAIN_PROJECT`` env > ``"default"``. Wrong-project hard filter
    stays downstream. Registry lookup is best-effort (fail open to next rung).
    """
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    home_path = Path(home)
    # Registry candidates: --cwd when given, else the Brain home path itself
    # (Phase C3 FIX 2: sessions without a usable cwd still resolve the
    # brain's own project before falling back to env/default).
    candidates: list[str] = []
    if cwd and str(cwd).strip():
        candidates.append(str(cwd).strip())
    candidates.append(str(home_path))
    for candidate in candidates:
        try:
            cwd_abs = os.path.abspath(candidate)
            for proj in registry.list_projects(home_path):
                root = proj.repo_path
                if root:
                    root_abs = os.path.abspath(root)
                    try:
                        if os.path.commonpath([cwd_abs, root_abs]) == root_abs:
                            return proj.id
                    except ValueError:
                        continue  # different drive
        except Exception:  # fail open: registry errors never break injection
            continue
    env_p = os.environ.get("SECOND_BRAIN_PROJECT")
    if env_p and env_p.strip():
        return env_p.strip()
    return "default"


def _search_or_fallback(home: Path | str, term: str, top_k: int) -> list[dict]:
    """OR-fallback recall (Phase C2 FIX 2): when the primary AND query returns
    zero candidates, union per-token matches (sorted token order, first-seen
    wins). Every token search runs the SAME hard filters + ranking inside
    semantic.search_memories; the union is capped at ``top_k``. Deterministic.
    """
    home_path = Path(home)
    tokens = sorted(semantic._query_tokens(term))
    seen: dict[str, dict] = {}
    for token in tokens:
        for row in semantic.search_memories(
            home_path,
            token,
            project_id=None,
            include_history=False,
            top_k=top_k,
            max_tokens=None,
        ):
            seen.setdefault(str(row.get("memory_id")), row)
    return list(seen.values())[:top_k]


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
        # P0-G9 gate (§6.3.1): unverified write-back candidates are NOT
        # current truth. Only VERIFIED/TESTED candidates may be retrieved.
        if row.get("status") == "candidate" and row.get("evidence_grade") not in (
            "VERIFIED",
            "TESTED",
        ):
            continue
        if (
            intent.project_id is None
            or row.get("scope") == "global"
            or row.get("project_id") == intent.project_id
        ):
            out.append(row)
    return out


_WORKER_ROLES = ("worker", "explorer", "verifier")


def _tags_for(home: Path | str, memory_ids: list[str]) -> dict[str, set[str]]:
    """Tags from the optional `tags:` frontmatter extension (memory_index.tags).

    The canonical writer never emits tags; a user/agent may add
    ``tags: worker`` to a memory file, and the indexer (semantic.index_memory)
    mirrors it into memory_index + memory_fts. Absent tags -> empty set.
    """
    ids = [mid for mid in memory_ids if mid]
    if not ids:
        return {}
    home = Path(home)
    conn = db.connect(db_path(home), readonly=True)
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT memory_id, tags FROM memory_index WHERE memory_id IN ({placeholders})",
            ids,
        ).fetchall()
        return {
            str(r["memory_id"]): {t for t in str(r["tags"] or "").split(",") if t} for r in rows
        }
    finally:
        conn.close()


def _role_filter(home: Path | str, rows: list[dict], role_profile: str) -> list[dict]:
    """P0-G7 worker-specific packets (hard filter, §6.3.1).

    Rule (documented, no invented metadata): a role keeps memories tagged
    with exactly its own tag OR untagged task-relevant memories. Memories
    tagged with another role are excluded — a worker never receives the
    parent's orchestrator-tagged memory and vice versa. Roles:
    orchestrator -> "orchestrator" tag; worker family (worker/explorer/
    verifier) -> their own tag. Unknown/control roles get no filter.
    """
    if not rows:
        return rows
    if role_profile == "orchestrator":
        wanted = {"orchestrator"}
    elif role_profile in _WORKER_ROLES:
        wanted = {role_profile}
    else:
        return rows
    tags = _tags_for(home, [str(r.get("memory_id")) for r in rows])
    out: list[dict] = []
    for row in rows:
        row_tags = tags.get(str(row.get("memory_id")) or "", set())
        if not row_tags or row_tags & wanted:
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

    query_mode = "and"
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
        if not rows:
            # FIX 2: AND returned zero -> OR-fallback union through the same
            # hard filters + ranking (precision-first primary path unchanged).
            query_mode = "or_fallback"
            rows = _search_or_fallback(home, intent.task_text, _MAX_CANDIDATES)
    except Exception as exc:  # fail-open contract (§6.8)
        logger.warning("AutoInject retrieval failed (fail-open): %s", exc)
        _append_telemetry(
            home,
            intent.session_id,
            "brain_retrieval_attempt",
            {
                "task_sha256": _task_sha256(intent.task_text),
                "candidate_count": 0,
                "recipient": intent.agent_id,
                "role_profile": intent.role_profile,
                "project_id": intent.project_id,
                "query_mode": query_mode,
            },
        )
        return decision(NoInjectionReason.BRAIN_UNAVAILABLE)

    _append_telemetry(
        home,
        intent.session_id,
        "brain_retrieval_attempt",
        {
            "task_sha256": _task_sha256(intent.task_text),
            "candidate_count": len(rows),
            "recipient": intent.agent_id,
            "role_profile": intent.role_profile,
            "project_id": intent.project_id,
            "query_mode": query_mode,
        },
    )
    candidate_ids = [str(r.get("memory_id")) for r in rows if r.get("memory_id")]
    if not rows:
        # FIX 3: NO_RELEVANT_MEMORY fires only when BOTH query modes are empty;
        # candidates that existed but were filtered get their specific reason.
        return decision(NoInjectionReason.NO_RELEVANT_MEMORY)
    valid = _valid_candidates(intent, rows)
    if not valid:
        return decision(NoInjectionReason.WRONG_PROJECT, candidate_ids=candidate_ids)
    role_rows = _role_filter(home, valid, intent.role_profile)
    if not role_rows:
        return decision(
            NoInjectionReason.NO_RELEVANT_MEMORY,
            candidate_ids=candidate_ids,
            selected_ids=[],  # nothing passed the role filter -> nothing selected
        )

    try:
        delivered = _delivered_keys(home, intent.session_id, intent.branch_id)
    except sqlite3.Error as exc:  # fail-open (§6.8)
        logger.warning("AutoInject ledger read failed (fail-open): %s", exc)
        return decision(NoInjectionReason.BRAIN_UNAVAILABLE, candidate_ids=candidate_ids)

    items = _build_items(home, role_rows)
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
        cwd: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> BrainInjectionDecision:
        """Decision + ledger/telemetry record. Never raises.

        ``cwd`` feeds project resolution (FIX 1): explicit project_id wins,
        then a registered project whose root contains cwd, then env, then
        "default". The retrieval-attempt telemetry (with query_mode) is
        recorded inside the module pipeline."""
        del context  # reserved for 0D adapter integration
        effective_session = session_id or (
            self._session.host_session_id if self._session is not None else "anon"
        )
        effective_project = _resolve_project_id(self._home, cwd, project_id)
        intent = RetrievalIntent(
            task_text=task,
            project_id=effective_project,
            agent_id=agent_id,
            role_profile=role_profile,
            session_id=effective_session,
            branch_id=branch_id,
        )
        decision = prepare_injection(self._home, intent)
        self._last_delivery_ids = []
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
                    # The Python pipeline only PREPARES deliveries; actual
                    # model-visible injection happens via the host adapter's
                    # custom-message path (shadow semantics, SCHEMA.md).
                    # P3 §0A.8/§5.2: delivery_prepared makes the
                    # prepared/ledger semantics explicit; model_visible stays
                    # False because Python cannot observe host insertion (the
                    # host's autoinject_shadow_decision.model_visible is the
                    # authoritative mode-aware visibility signal).
                    "model_visible": False,
                    "delivery_prepared": True,
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

    def writeback_candidate(
        self,
        *,
        session_id: str,
        project_id: str,
        title: str,
        observation: str,
        guidance: str = "",
        evidence: list[dict] | None = None,
    ) -> str:
        """P0-G9 write-back: create a CANDIDATE memory (never promoted to truth).

        Uses semantic.add_memory with default status ``candidate`` and grade
        ``OBSERVED``; provenance points at the session (first source) plus any
        caller-supplied evidence refs. The validity gate (§6.3.1) keeps
        unverified candidates OUT of retrieval; only after curation to
        VERIFIED/TESTED does the candidate become retrievable (G10). Raises
        BrainError on invalid input — the CLI applies fail-open.
        """
        sources: list[dict] = [{"ref": f"session:{session_id}", "kind": "episode"}]
        for item in evidence or []:
            if isinstance(item, dict) and item.get("ref"):
                sources.append(
                    {
                        "ref": str(item["ref"]),
                        "kind": str(item.get("kind") or "evidence"),
                    }
                )
        memory_id = semantic.add_memory(
            self._home,
            title,
            observation,
            scope="project",
            project_id=project_id,
            grade="OBSERVED",
            sources=sources,
            summary=guidance or None,
        )
        _append_telemetry(
            self._home,
            session_id,
            "writeback_candidate",
            {
                "memory_id": memory_id,
                "project_id": project_id,
                "status": "candidate",
                "session_sha256": _task_sha256(session_id),
            },
        )
        return memory_id
