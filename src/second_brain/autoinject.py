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
import json
import logging
import os
import re
import sqlite3
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import (
    db,
    decisions,
    freshness,
    governor,
    hybrid_retrieval,
    reconsolidation,
    registry,
    semantic,
    telemetry,
    working_set,
)
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
    estimate_tokens,
)
from .paths import db_path

logger = logging.getLogger(__name__)

DEFAULT_TARGET_TOKENS = 800
DEFAULT_HARD_CAP_TOKENS = 2000
DEFAULT_DELTA_TARGET_TOKENS = 400
DEFAULT_DELTA_HARD_CAP_TOKENS = 1000
_MAX_CANDIDATES = 10  # candidate ceiling for the shadow pipeline
_TELEMETRY_V = 2
_PACKET_CACHE_LIMIT = 64
_ENV_TARGET = "SECOND_BRAIN_AUTOINJECT_TARGET_TOKENS"
_ENV_CAP = "SECOND_BRAIN_AUTOINJECT_HARD_CAP_TOKENS"
_ENV_DELTA_TARGET = "SECOND_BRAIN_AUTOINJECT_DELTA_TARGET_TOKENS"
_ENV_DELTA_CAP = "SECOND_BRAIN_AUTOINJECT_DELTA_HARD_CAP_TOKENS"

# Rendered packet cache: packet_id -> (rendered text, items). Shadow phase
# keeps decisions deterministic without persisting packets to the canonical DB.
_PACKET_CACHE: dict[str, tuple[str, list[PacketItem]]] = {}
_CASCADE = hybrid_retrieval.HybridCascadeRetriever()


# ---------------------------------------------------------------------------
# Config (§6.6) and token estimation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AutoInjectConfig:
    target_tokens: int
    hard_cap_tokens: int
    delta_target_tokens: int = DEFAULT_DELTA_TARGET_TOKENS
    delta_hard_cap_tokens: int = DEFAULT_DELTA_HARD_CAP_TOKENS


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
    """config/autoinject.toml [budget] and [delta_budget] with env override;
    fail open to defaults."""
    target = DEFAULT_TARGET_TOKENS
    cap = DEFAULT_HARD_CAP_TOKENS
    delta_target = DEFAULT_DELTA_TARGET_TOKENS
    delta_cap = DEFAULT_DELTA_HARD_CAP_TOKENS
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
            delta_budget = data.get("delta_budget") or {}
            if isinstance(delta_budget, dict):
                raw_dt = delta_budget.get("target_tokens")
                raw_dc = delta_budget.get("hard_cap_tokens")
                if isinstance(raw_dt, int) and not isinstance(raw_dt, bool) and raw_dt > 0:
                    delta_target = raw_dt
                if isinstance(raw_dc, int) and not isinstance(raw_dc, bool) and raw_dc > 0:
                    delta_cap = raw_dc
        except (OSError, tomllib.TOMLDecodeError):
            logger.warning("config/autoinject.toml unreadable; using defaults (fail open)")
    target = _env_int(_ENV_TARGET, target)
    cap = _env_int(_ENV_CAP, cap)
    delta_target = _env_int(_ENV_DELTA_TARGET, delta_target)
    delta_cap = _env_int(_ENV_DELTA_CAP, delta_cap)
    if cap < 1:
        cap = DEFAULT_HARD_CAP_TOKENS
    if target < 1:
        target = DEFAULT_TARGET_TOKENS
    target = min(target, cap)
    if delta_cap < 1:
        delta_cap = DEFAULT_DELTA_HARD_CAP_TOKENS
    if delta_target < 1:
        delta_target = DEFAULT_DELTA_TARGET_TOKENS
    delta_target = min(delta_target, delta_cap)
    return AutoInjectConfig(
        target_tokens=target,
        hard_cap_tokens=cap,
        delta_target_tokens=delta_target,
        delta_hard_cap_tokens=delta_cap,
    )

def token_estimate(text: str, home: Path | str | None = None) -> int:
    return estimate_tokens(text, home=home)


# ---------------------------------------------------------------------------
# Retrieval intent and candidate sources.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalIntent:
    """Structured retrieval intent (plan §6.1): task text stays ephemeral."""

    task_text: str
    project_id: str | None
    agent_id: str
    role_profile: str
    session_id: str
    branch_id: str = "main"
    is_delta: bool = False
    cwd: str | None = None
    lane: str = "semantic"

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _task_sha256(task: str) -> str:
    return hashlib.sha256((task or "").encode("utf-8")).hexdigest()

def _record_retrieval_abstention(
    home: Path, intent: RetrievalIntent, lane: str = "semantic"
) -> None:
    """Record score-gap abstention without persisting task/query content."""
    cfg = semantic.load_retrieval_config(home)
    try:
        decisions.record(
            home,
            kind="retrieval",
            session_id=intent.session_id,
            task_id=None,
            chosen={"decision": "NO_INJECTION"},
            alternatives=["INJECT"],
            propensity=1.0,
            randomized=False,
            policy_version=cfg.gate.config_version,
            stage=cfg.gate.rollout,
            inputs={
                "task_sha256": _task_sha256(intent.task_text),
                "project_id": intent.project_id or "",
                "lane": lane,
                "gate": "score_gap",
            },
        )
    except Exception:
        logger.debug("retrieval abstention decision record failed", exc_info=True)

_BUDGET_POLICY_VERSION = "v3.1"


def _budget_rollout_stage(home: Path) -> str:
    """config/v2.toml [rollout] brainstem; SHADOW default (matches the
    routing/eviction decisions(kind=...) stage-resolution pattern)."""
    stage = "SHADOW"
    try:
        v2_path = Path(home) / "config" / "v2.toml"
        if v2_path.is_file():
            v2_raw = tomllib.loads(v2_path.read_text(encoding="utf-8"))
            candidate = (v2_raw.get("rollout") or {}).get("brainstem", "SHADOW")
            if candidate in decisions._ROLLOUT_STAGES:
                stage = candidate
    except Exception:
        pass
    return stage


def _record_budget_soft(home: Path, intent: RetrievalIntent, used: int, cap: int) -> None:
    """Record the SOFT budget determination (T3.1) without persisting
    task/query content, following the exact pattern of
    `_record_retrieval_abstention`."""
    try:
        decisions.record(
            home,
            kind="budget",
            session_id=intent.session_id,
            task_id=None,
            chosen={"decision": "NO_INJECTION", "state": "SOFT"},
            alternatives=["INJECT"],
            propensity=1.0,
            randomized=False,
            policy_version=_BUDGET_POLICY_VERSION,
            stage=_budget_rollout_stage(home),
            inputs={"used": used, "cap": cap},
        )
    except Exception:
        logger.debug("budget SOFT decision record failed", exc_info=True)


# ---------------------------------------------------------------------------
# Validity gate (§6.3): hard filters BEFORE scoring. Ranking stays inside
# semantic.search_memories (reused unchanged); this gate only ADDS the
# validity dimensions the plan requires and never re-scores.
# ---------------------------------------------------------------------------


def _resolve_project_id(
    home: Path | str, cwd: str | None, explicit: str | None
) -> str:
    """Project resolution ladder:

    1. explicit `--project` argument;
    2. cwd-based detection if cwd is provided:
       a. explicit `.brain/project.toml` manifest (registry.detect_explicit_id);
       b. registered project whose repo_path contains cwd (registry.list_projects);
       c. git remote match against registered projects (registry.detect_git_remote);
    3. if cwd is absent/empty: check if brain home path is a registered project;
    4. `SECOND_BRAIN_PROJECT` environment variable;
    5. "default" (unresolved safe fallback).

    Registry lookup is best-effort (fail open to next rung).
    When cwd is explicitly provided, never silently falls back to brain home path.
    """
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    home_path = Path(home)
    if cwd and str(cwd).strip():
        cwd_str = str(cwd).strip()
        # 2a. Manifest detection
        try:
            manifest_id = registry.detect_explicit_id(cwd_str)
            if manifest_id:
                return manifest_id
        except Exception:
            pass
        # 2b. Repo path match
        try:
            cwd_abs = os.path.abspath(cwd_str)
            for proj in registry.list_projects(home_path):
                root = proj.repo_path
                if root:
                    root_abs = os.path.abspath(root)
                    try:
                        if os.path.commonpath([cwd_abs, root_abs]) == root_abs:
                            return proj.id
                    except ValueError:
                        continue  # different drive
        except Exception:
            pass
        # 2c. Git remote match
        try:
            remote = registry.detect_git_remote(cwd_str)
            if remote:
                norm_rem = registry.remote_identity(remote)
                for proj in registry.list_projects(home_path):
                    if proj.git_remote and (
                        proj.git_remote.strip().lower() == remote.strip().lower()
                        or registry.remote_identity(proj.git_remote) == norm_rem
                    ):
                        return proj.id
        except Exception:
            pass
    else:
        # 3. If cwd is absent/empty: check if brain home path itself is registered
        try:
            home_abs = os.path.abspath(str(home_path))
            for proj in registry.list_projects(home_path):
                root = proj.repo_path
                if root:
                    root_abs = os.path.abspath(root)
                    try:
                        if os.path.commonpath([home_abs, root_abs]) == root_abs:
                            return proj.id
                    except ValueError:
                        continue
        except Exception:
            pass

    env_p = os.environ.get("SECOND_BRAIN_PROJECT")
    if env_p and env_p.strip():
        return env_p.strip()
    return "default"




def _retrieval_query_text(home: Path, intent: RetrievalIntent) -> str:
    """Use active capsule intent when available; otherwise use task text."""
    try:
        capsule = working_set.show_capsule(home, intent.session_id)
    except Exception:
        capsule = None
    if capsule:
        parts = [
            value.strip()
            for value in (capsule.get("objective"), capsule.get("next_action"))
            if isinstance(value, str) and value.strip()
        ]
        if parts:
            return " ".join(parts)
    return intent.task_text

def _valid_candidates(intent: RetrievalIntent, rows: list[dict]) -> list[dict]:
    """Apply the literal corpus admission policy before ranking/rendering.

    Missing or unknown metadata is rejected rather than assigned a default.
    Domain memories are usable when their project is known and matches, or
    when either side explicitly has no project identity; global memories are
    always eligible.
    """
    allowed_statuses = {"current", "candidate", "labile"}
    allowed_grades = {"VERIFIED", "TESTED", "OBSERVED"}
    unknown_projects = {"", "default", "unknown"}
    out: list[dict] = []
    for row in rows:
        status = row.get("status")
        grade = row.get("evidence_grade")
        scope = row.get("scope")
        if (
            not isinstance(status, str)
            or status not in allowed_statuses
            or not isinstance(grade, str)
            or grade not in allowed_grades
            or not isinstance(scope, str)
            or scope not in {"project", "domain", "global"}
        ):
            continue
        if scope == "global":
            scope_ok = True
        else:
            if "project_id" not in row:
                continue
            row_project = row.get("project_id")
            row_project = str(row_project or "").strip().lower()
            intent_project = str(intent.project_id or "").strip().lower()
            if scope == "project":
                scope_ok = (
                    bool(intent_project)
                    and intent_project not in unknown_projects
                    and bool(row_project)
                    and row_project == intent_project
                )
            else:
                scope_ok = (
                    (intent_project in unknown_projects)
                    or (row_project in unknown_projects)
                    or (row_project == intent_project and bool(row_project))
                )
        if not scope_ok:
            continue
        if intent.lane == "policy":
            # Policy context is a hard authority boundary. Missing or
            # unknown metadata is rejected rather than defaulted.
            if row.get("authority_ceiling") not in {"project_rule", "policy"}:
                continue
        # Delta injection remains intentionally strict: only current,
        # high-confidence truth can be introduced mid-session.
        if intent.is_delta and (
            status != "current" or grade not in {"VERIFIED", "TESTED"}
        ):
            continue
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
    """Map admitted evidence grades to their fixed packet confidence."""
    del strength  # admission confidence is grade-based, never fabricated
    if contradicted:
        return MemoryItemStatus.CONTRADICTED, Confidence.LOW
    if grade in {"VERIFIED", "TESTED"}:
        return MemoryItemStatus.CURRENT, Confidence.HIGH
    if grade == "OBSERVED":
        return MemoryItemStatus.UNCERTAIN, Confidence.LOW
    # This is unreachable after _valid_candidates; keep malformed direct
    # callers conservative rather than manufacturing medium confidence.
    return MemoryItemStatus.UNCERTAIN, Confidence.LOW


def _canonical_line(text: str | None) -> str:
    """Collapse whitespace to the packet's deterministic one-line format."""
    return " ".join((text or "").split())


def _build_items(
    home: Path | str, rows: list[dict], *, lane: str = "semantic"
) -> list[PacketItem]:
    """Rows (already validity-gated, search-ranked) -> canonical packet items.

    Policy lane (§T1.7): a contradiction from a memory that did not itself
    clear the policy admission gate (lower authority_ceiling, excluded from
    ``rows``) is rendered via ``contradicts`` but never flips this item's
    status to CONTRADICTED/withholds it -- only contradictions between two
    memories that both cleared admission are treated as unresolved conflicts.
    """
    home = Path(home)
    admitted_ids = {str(r.get("memory_id") or "") for r in rows}
    items: list[PacketItem] = []
    for row in rows:
        memory_id = str(row.get("memory_id") or "")
        version = int(row.get("current_version") or 1)
        contradiction_ids = {str(i) for i in (row.get("contradiction_with") or [])}
        conflicting = (
            (contradiction_ids & admitted_ids) if lane == "policy" else contradiction_ids
        )
        contradicted = bool(conflicting) or (row.get("_freshness_state") == freshness.CONTRADICTED)
        status, confidence = _grade_confidence(
            row.get("evidence_grade"), row.get("strength"), contradicted
        )
        body = row.get("_body") or semantic._body_text(home, row)
        supersedes: tuple[str, int] | None = None
        if version > 1:
            supersedes = (memory_id, version - 1)
        evidence = f"brain://{memory_id}/{version}"
        verified = row.get("_verified_evidence")
        if isinstance(verified, str) and verified:
            evidence += f" {verified}"
        contradictions = ()
        if lane == "policy":
            contradictions = tuple(sorted(contradiction_ids))
        items.append(
            PacketItem(
                memory_id=memory_id,
                version=version,
                status=status,
                confidence=confidence,
                title=_canonical_line(row.get("title")),
                observation=_canonical_line(body),
                guidance=_canonical_line(row.get("summary")),
                evidence=evidence,
                supersedes=supersedes,
                freshness=str(row.get("_freshness_state") or freshness.UNKNOWN),
                contradicts=contradictions,
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
            f"freshness: {item.freshness}",
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
def _render_packet_text(
    items: list[PacketItem], project: str | None, *, lane: str = "semantic"
) -> str:
    pkt = BrainPacket(
        packet_id=_packet_id(items),
        project=project or "global",
        scope="task",
        authority="policy" if lane == "policy" else "advisory",
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
            freshness=i.freshness,
            contradicts=i.contradicts,
        )
        for i in items
    ]

def _fit_budget(
    items: list[PacketItem],
    project: str | None,
    config: AutoInjectConfig,
    home: Path | str | None = None,
    *,
    lane: str = "semantic",
) -> tuple[list[PacketItem], bool] | None:
    """§6.6: fit packets within target and hard token budgets."""
    def est(candidate: list[PacketItem]) -> int:
        return token_estimate(_render_packet_text(candidate, project, lane=lane), home=home)

    best = list(items)
    while len(best) > 1 and est(best) > config.target_tokens:
        best = best[:-1]
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


def shadow_output(
    decision: BrainInjectionDecision, packet: str | None, delivery_id: str | None
) -> dict:
    """Deterministic one-object JSON shape shared by shadow + codex-shadow."""
    return {
        "decision": decision.decision.value,
        "reason": decision.reason.value if decision.reason is not None else None,
        "packet": packet,
        "packet_tokens": decision.packet_token_size,
        "candidate_ids": decision.candidate_ids,
        "selected_ids": decision.selected_ids,
        "delivery_id": delivery_id,
    }


def prepare_injection(
    home: Path | str,
    intent: RetrievalIntent,
    *,
    config: AutoInjectConfig | None = None,
    retrieval_text: str | None = None,
) -> BrainInjectionDecision:
    """Decision pipeline. NEVER raises: every failure degrades to
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

    # T3.1: SOFT budget check, after intent validation (the `empty`/
    # `decision` scaffolding above), before any retrieval work begins.
    budget = governor.check_budget(home, intent.session_id, intent.role_profile)
    if budget.get("state") == "SOFT":
        _record_budget_soft(home, intent, budget.get("used", 0), budget.get("cap", 0))
        return decision(NoInjectionReason.BUDGET_SOFT)

    query_mode = "idf"
    query_text = (
        retrieval_text if retrieval_text is not None else _retrieval_query_text(home, intent)
    )
    proj_filter = (
        intent.project_id
        if intent.project_id and intent.project_id not in ("default", "unknown")
        else None
    )
    unscoped_candidates: list[dict] = []
    try:
        db.migrate(db_path(home))
        # Primary search: Hybrid Multi-Tier Cascade Retrieval (Tiers 0-4)
        cascade_res = _CASCADE.retrieve(
            home,
            query_text,
            project_id=proj_filter,
            top_k=_MAX_CANDIDATES,
            lane=intent.lane,
        )
        if cascade_res.retrieval_error:
            raise RuntimeError("semantic retrieval unavailable")
        rows = [
            m.raw_row if m.raw_row else (semantic._row(home, m.memory_id) or {})
            for m in cascade_res.matches
        ]

        # The semantic project prefilter excludes domain memories whose
        # project is unknown. Supplement known-project searches with the
        # unscoped result; _valid_candidates remains the security boundary.
        if proj_filter is not None:
            unscoped_cascade = _CASCADE.retrieve(
                home,
                query_text,
                project_id=None,
                top_k=_MAX_CANDIDATES,
                lane=intent.lane,
            )
            if unscoped_cascade.retrieval_error:
                raise RuntimeError("semantic retrieval unavailable")
            supplement = [
                m.raw_row if m.raw_row else (semantic._row(home, m.memory_id) or {})
                for m in unscoped_cascade.matches
            ]
            seen_ids = {str(row.get("memory_id")) for row in rows}
            rows.extend(
                row
                for row in supplement
                if row.get("memory_id") and str(row["memory_id"]) not in seen_ids
            )
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
                "is_delta": intent.is_delta,
            },
        )
        return decision(NoInjectionReason.BRAIN_UNAVAILABLE)

    candidate_ids = [
        str(r.get("memory_id"))
        for r in (rows if rows else unscoped_candidates)
        if r.get("memory_id")
    ]

    _append_telemetry(
        home,
        intent.session_id,
        "brain_retrieval_attempt",
        {
            "task_sha256": _task_sha256(intent.task_text),
            "candidate_count": len(rows) if rows else len(unscoped_candidates),
            "eligible_count": len(rows),
            "recipient": intent.agent_id,
            "role_profile": intent.role_profile,
            "project_id": intent.project_id,
            "query_mode": query_mode,
            "is_delta": intent.is_delta,
        },
    )

    if not rows:
        if unscoped_candidates:
            return decision(NoInjectionReason.WRONG_PROJECT, candidate_ids=candidate_ids)
        return decision(NoInjectionReason.NO_RELEVANT_MEMORY)

    admitted = _valid_candidates(intent, rows)
    if not admitted:
        return decision(NoInjectionReason.WRONG_PROJECT, candidate_ids=candidate_ids)
    fresh_valid: list[dict] = []
    for row in admitted:
        try:
            memory_id = str(row.get("memory_id") or "")
            source_rows = semantic._sources(home, memory_id)
            source = next((item for item in source_rows if item.get("path")), None)
            repo_root = (source or {}).get("repo_id") or intent.cwd or home
            freshness_result = freshness.resolve(home, memory_id, repo_root)
            state = freshness_result.get("state", freshness.UNKNOWN)
            if state in {freshness.STALE, freshness.SOURCE_MISSING}:
                continue
            enriched = dict(row)
            enriched["_freshness_state"] = state
            if state == freshness.VERIFIED_CURRENT:
                verified_source = freshness.current_source(home, memory_id, repo_root)
                verified_source = verified_source or source
                if verified_source is not None:
                    path = verified_source.get("path")
                    blob = verified_source.get("blob_sha")
                    verified_at = verified_source.get("verified_at")
                    if path and blob and verified_at:
                        enriched["_verified_evidence"] = (
                            f"Evidence: {path}@{str(blob)[:12]} unchanged since {verified_at}"
                        )
            fresh_valid.append(enriched)
        except Exception as exc:
            logger.warning("AutoInject freshness failed (fail-open): %s", exc)
            return decision(
                NoInjectionReason.BRAIN_UNAVAILABLE,
                candidate_ids=candidate_ids,
                selected_ids=[],
            )
    valid = fresh_valid
    if not valid:
        return decision(
            NoInjectionReason.NO_RELEVANT_MEMORY,
            candidate_ids=candidate_ids,
            selected_ids=[],
        )
    role_rows = _role_filter(home, valid, intent.role_profile)
    if not role_rows:
        return decision(
            NoInjectionReason.NO_RELEVANT_MEMORY,
            candidate_ids=candidate_ids,
            selected_ids=[],
        )

    if cascade_res.reason == "LOW_CONFIDENCE":
        _record_retrieval_abstention(home, intent)
        return decision(
            NoInjectionReason.LOW_CONFIDENCE,
            candidate_ids=candidate_ids,
            selected_ids=[],
        )

    try:
        delivered = _delivered_keys(home, intent.session_id, intent.branch_id)
    except sqlite3.Error as exc:  # fail-open (§6.8)
        logger.warning("AutoInject ledger read failed (fail-open): %s", exc)
        return decision(NoInjectionReason.BRAIN_UNAVAILABLE, candidate_ids=candidate_ids)

    items = _build_items(home, role_rows, lane=intent.lane)
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

    # Budget gate: delta injection uses delta budget; startup uses base budget
    active_budget = (
        AutoInjectConfig(
            target_tokens=cfg.delta_target_tokens,
            hard_cap_tokens=cfg.delta_hard_cap_tokens,
        )
        if intent.is_delta
        else cfg
    )

    fit = _fit_budget(fresh, intent.project_id, active_budget, home=home, lane=intent.lane)
    if fit is None:
        return decision(
            NoInjectionReason.CONTEXT_PRESSURE,
            candidate_ids=candidate_ids,
            selected_ids=[i.memory_id for i in fresh],
        )
    selected, ids_only = fit
    del ids_only  # shadow phase: caller sees the same canonical shape either way
    text = _render_packet_text(selected, intent.project_id, lane=intent.lane)
    packet_id = _packet_id(selected)
    _cache_packet(packet_id, text, selected)
    return dataclasses.replace(
        empty,
        decision=InjectionDecision.INJECT,
        reason=None,
        candidate_ids=candidate_ids,
        selected_ids=[i.memory_id for i in selected],
        packet_ref=packet_id,
        packet_token_size=token_estimate(text, home=home),
    )


# ---------------------------------------------------------------------------
# Telemetry (§6.12, SCHEMA.md v2): privacy-safe JSONL, best-effort.
# ---------------------------------------------------------------------------


def _sanitize_stem(session: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]", "-", session or "")
    if stem:
        return stem
    return f"anon-{_task_sha256(session or '')[:12]}"


def _append_telemetry(
    home: Path | str, session: str, kind: str, extra: dict[str, Any]
) -> bool:
    try:
        tdir = telemetry.telemetry_dir(Path(home))
        tdir.mkdir(parents=True, exist_ok=True)
        record = {
            "v": telemetry.KIND_SCHEMA_VERSION.get(kind, _TELEMETRY_V),
            "ts": _now(),
            "kind": kind,
            "session": session,
            **extra,
        }
        with open(tdir / f"{_sanitize_stem(session)}.jsonl", "a", encoding="utf-8") as f:
            f.write(canonical_json(record) + "\n")
        return True
    except OSError as exc:
        logger.warning("AutoInject telemetry append failed (ignored): %s", exc)
        return False


def _has_session_started(home: Path | str, host_session_id: str) -> bool:
    """Best-effort idempotency check: has a session_started record already
    been appended for this host_session_id? Reuses the same per-session
    telemetry file _append_telemetry writes to -- no separate registry.
    Fails open (returns False, i.e. "allow the write") on any read error so
    a corrupt/unreadable file never blocks lifecycle telemetry."""
    try:
        path = telemetry.telemetry_dir(Path(home)) / f"{_sanitize_stem(host_session_id)}.jsonl"
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") == "session_started":
                return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# BrainLifecycle control adapter (§6.9).
# ---------------------------------------------------------------------------



def _feedback_exists(
    home: Path | str, table: str, memory_id: str, session_id: str
) -> bool:
    """Check one session-bound feedback row without exposing its contents."""
    if table not in {"memory_retrievals", "memory_activations"}:
        return False
    conn = db.connect(db_path(home), readonly=True)
    try:
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE memory_id = ? AND session_id = ? LIMIT 1",
            (memory_id, session_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _record_delivery_feedback(
    home: Path | str, memory_ids: list[str], session_id: str
) -> None:
    """Record one retrieval per delivered memory, best-effort and idempotently."""
    for memory_id in dict.fromkeys(memory_ids):
        try:
            if not _feedback_exists(home, "memory_retrievals", memory_id, session_id):
                reconsolidation.record_retrieval(
                    home, memory_id, session_id=session_id, idempotent=True
                )
        except Exception:
            logger.debug("retrieval feedback failed", exc_info=True)


def _mention_text(value: object) -> str:
    """Extract only tool-call argument text for deterministic ID matching."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_mention_text(item) for item in value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("args", "arguments", "input", "command", "query"):
            if key in value:
                parts.append(_mention_text(value[key]))
        if parts:
            return "\n".join(parts)
        return "\n".join(_mention_text(item) for item in value.values())
    return ""


def _record_activation_feedback(
    home: Path | str,
    memory_ids: list[str],
    session_id: str,
    tool_call_args: object,
    final_message: object,
) -> None:
    """Record correct activation for delivered IDs mentioned by the host."""
    tool_text = _mention_text(tool_call_args)
    final_text = final_message if isinstance(final_message, str) else ""
    for memory_id in dict.fromkeys(memory_ids):
        if memory_id not in tool_text and memory_id not in final_text:
            continue
        try:
            if not _feedback_exists(home, "memory_activations", memory_id, session_id):
                reconsolidation.record_activation(
                    home,
                    memory_id,
                    "correct",
                    session_id=session_id,
                    idempotent=True,
                )
        except Exception:
            logger.debug("activation feedback failed", exc_info=True)

def _delivered_memory_ids(home: Path | str, session_id: str) -> list[str]:
    conn = db.connect(db_path(home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT memory_id FROM deliveries WHERE root_session_id = ?",
            (session_id,),
        ).fetchall()
        return [str(row["memory_id"]) for row in rows if row["memory_id"]]
    finally:
        conn.close()



class BrainLifecycle:
    """Control/storage adapter for the AutoInject pipeline (§6.9).

    SHADOW: ``prepare_injection`` decides + records only. Fail-open: it never
    raises; ledger/telemetry write failures are logged and ignored.
    """

    def __init__(self, home: Path | str, session: BrainSessionIdentity | None = None) -> None:
        self._home = Path(home)
        self._session = session
        self._feedback_session_id: str | None = (
            session.host_session_id if session is not None else None
        )
        self._last_delivery_ids: list[str] = []

    @property
    def last_delivery_ids(self) -> list[str]:
        return list(self._last_delivery_ids)

    def start_session(self, identity: BrainSessionIdentity) -> BrainSessionIdentity:
        """Idempotent per host_session_id: the first call for a given Claude
        Code / harness session records session_started once; every later
        call for the same host_session_id (repeat SessionStart on resume/
        clear/compact/fork, or the start_session() side effect inside
        PreCompact/Stop) attaches to that same identity without appending a
        duplicate record."""
        self._session = identity
        if not _has_session_started(self._home, identity.host_session_id):
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
        is_delta: bool = False,
        context: dict[str, Any] | None = None,
        lane: str = "semantic",
    ) -> BrainInjectionDecision:
        """Decision + ledger/telemetry record. Never raises.

        ``cwd`` feeds project resolution: explicit project_id wins,
        then a registered project whose root contains cwd, then env, then
        "default". The retrieval-attempt telemetry (with query_mode and is_delta) is
        recorded inside the module pipeline."""
        del context  # reserved for 0D adapter integration
        effective_session = session_id or (
            self._session.host_session_id if self._session is not None else "anon"
        )
        self._feedback_session_id = effective_session
        effective_project = _resolve_project_id(self._home, cwd, project_id)
        intent = RetrievalIntent(
            task_text=task,
            project_id=effective_project,
            agent_id=agent_id,
            role_profile=role_profile,
            session_id=effective_session,
            branch_id=branch_id,
            is_delta=is_delta,
            cwd=cwd,
            lane=lane,
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
                    "project_id": effective_project,
                    "is_delta": is_delta,
                    "selected_ids": decision.selected_ids,
                },
            )
            if self._last_delivery_ids:
                _record_delivery_feedback(
                    self._home, decision.selected_ids, effective_session
                )
        else:
            _append_telemetry(
                self._home,
                effective_session,
                "brain_no_injection",
                {
                    "reason": decision.reason.value if decision.reason is not None else None,
                    "candidate_count": len(decision.candidate_ids),
                    "project_id": effective_project,
                    "is_delta": is_delta,
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

    def finalize_session(
        self,
        *,
        tool_call_args: object = None,
        final_message: object = None,
        session_id: str | None = None,
    ) -> None:
        feedback_session = session_id or self._feedback_session_id
        if feedback_session:
            try:
                delivered = _delivered_memory_ids(self._home, feedback_session)
                _record_activation_feedback(
                    self._home,
                    delivered,
                    feedback_session,
                    tool_call_args,
                    final_message,
                )
            except Exception:
                logger.debug("activation feedback lookup failed", exc_info=True)
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
        caller-supplied evidence refs. The validity gate (§6.3.1) admits
        OBSERVED candidates as low-confidence context; curation to VERIFIED/
        TESTED upgrades the rendered confidence to HIGH. Raises
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
            origin_class="MODEL_INFERENCE",
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



AUTOINJECT_MODE_OFF_VALUES = {"off", "0", "false", "no"}
AUTOINJECT_MODE_ACTIVE_VALUES = {"advisory", "active", "1", "true", "yes"}
DEFAULT_AUTOINJECT_MODE = "shadow"


def mode_from_autoinject_toml(text: str) -> str | None:
    """Read `[autoinject] mode` from config/autoinject.toml text (tiny parser).

    Mirrors Prime autoinject.ts `modeFromAutoinjectToml`. Returns None when
    the key is absent/invalid (absent => default).
    """
    in_autoinject = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_autoinject = line.startswith("[autoinject]")
            continue
        if not in_autoinject or line == "" or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        if key.strip() != "mode":
            continue
        value = rest.split("#")[0].strip().strip('"').lower()
        if value in AUTOINJECT_MODE_OFF_VALUES:
            return "off"
        if value in AUTOINJECT_MODE_ACTIVE_VALUES:
            return value
        if value == "shadow":
            return "shadow"
        return None
    return None


def resolve_autoinject_mode(home: Path | str, env: dict[str, str] | None = None) -> str:
    """Canonical AutoInject mode resolution (plan §11 / §22).

    Precedence: SECOND_BRAIN_AUTOINJECT_* env override > config/autoinject.toml
    [autoinject] mode > default "shadow". No second hierarchy.
    """
    env_map = env if env is not None else os.environ
    env_raw = (env_map.get("SECOND_BRAIN_AUTOINJECT_MODE", "") or "").strip().lower()
    mode: str | None = None
    if env_raw:
        if env_raw in AUTOINJECT_MODE_OFF_VALUES:
            mode = "off"
        elif env_raw in AUTOINJECT_MODE_ACTIVE_VALUES:
            mode = env_raw
        elif env_raw == "shadow":
            mode = "shadow"
    if mode is not None:
        return mode
    path = Path(home) / "config" / "autoinject.toml"
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        file_mode = mode_from_autoinject_toml(text)
        if file_mode is not None:
            return file_mode
    return DEFAULT_AUTOINJECT_MODE
