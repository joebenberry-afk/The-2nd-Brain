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
import random
import re
import sqlite3
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import (
    db,
    decisions,
    freshness,
    governor,
    hybrid_retrieval,
    ledger,
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
from .errors import BrainError
from .paths import db_path
from .security.identifiers import validate_project_id

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
    """config/autoinject.toml [budget] and [delta_budget] with env override; fail open
    to defaults."""
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


class TaskClass(StrEnum):
    TRIVIAL = "trivial"
    NAVIGATION = "navigation"
    IMPLEMENTATION = "implementation"
    DEBUGGING = "debugging"
    VERIFICATION = "verification"
    EXPLORATION = "exploration"
    HIGH_RISK = "high_risk"
    CONTINUATION = "continuation"


def classify_task(task_or_hash: str, *, risk_class: str | None = None) -> TaskClass:
    """Classify retrieval-holdout tasks without selecting an agent or model."""
    if isinstance(task_or_hash, TaskClass):
        return task_or_hash
    text = str(task_or_hash).strip()
    lower = text.lower()
    for item in TaskClass:
        if lower == item.value:
            return item
    if risk_class in ("HIGH", "CRITICAL"):
        return TaskClass.HIGH_RISK
    classes = tuple(TaskClass)
    if len(text) == 16 and all(c in "0123456789abcdefABCDEF" for c in text):
        return classes[int(text, 16) % len(classes)]
    signals = (
        (TaskClass.CONTINUATION, ("continue", "continuation", "resume", "pick up")),
        (
            TaskClass.VERIFICATION,
            ("verify", "verification", "check", "assert", "audit", "lint", "gate"),
        ),
        (
            TaskClass.DEBUGGING,
            ("debug", "debugging", "fix", "bug", "error", "failure", "trace", "issue", "crash"),
        ),
        (
            TaskClass.NAVIGATION,
            ("navigate", "navigation", "find", "search", "locate", "where", "list", "grep", "glob"),
        ),
        (
            TaskClass.EXPLORATION,
            ("explore", "exploration", "investigate", "research", "survey", "discover"),
        ),
        (
            TaskClass.HIGH_RISK,
            ("critical", "high risk", "security", "permission", "drop table", "destroy", "root"),
        ),
        (
            TaskClass.TRIVIAL,
            ("trivial", "summarize", "summary", "readme", "ping", "hello", "echo", "typo"),
        ),
    )
    for task_class, words in signals:
        if any(word in lower for word in words):
            return task_class
    return TaskClass.IMPLEMENTATION


_ROLLOUT_STAGE_RANKS: dict[str, int] = {
    "OFF": 0,
    "SHADOW": 1,
    "ADVISORY": 2,
    "CANARY": 3,
    "ACTIVE": 4,
}


def _retrieval_holdout_stage(home: Path | str) -> str:
    """Read rollout stage for retrieval_holdout.

    Checks SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE env var first, then config/v2.toml
    [rollout] retrieval_holdout, defaulting to 'SHADOW'.
    """
    env_stage = os.environ.get("SECOND_BRAIN_RETRIEVAL_HOLDOUT_STAGE")
    if env_stage and env_stage in decisions._ROLLOUT_STAGES:
        return env_stage
    stage = "SHADOW"
    try:
        v2_path = Path(home) / "config" / "v2.toml"
        if v2_path.is_file():
            v2_raw = tomllib.loads(v2_path.read_text(encoding="utf-8"))
            candidate = (v2_raw.get("rollout") or {}).get("retrieval_holdout", "SHADOW")
            if candidate in decisions._ROLLOUT_STAGES:
                stage = candidate
    except Exception:
        pass
    return stage


def _retrieval_holdout_epsilon(home: Path | str) -> float:
    """Read holdout epsilon rate.

    Checks SECOND_BRAIN_HOLDOUT_EPSILON env var, then config/v2.toml or
    config/retrieval.toml [retrieval_holdout] epsilon, defaulting to 0.1.
    """
    env_eps = os.environ.get("SECOND_BRAIN_HOLDOUT_EPSILON")
    if env_eps is not None:
        try:
            val = float(env_eps)
            if 0.0 <= val <= 1.0:
                return val
        except (ValueError, TypeError):
            pass
    try:
        v2_path = Path(home) / "config" / "v2.toml"
        if v2_path.is_file():
            v2_raw = tomllib.loads(v2_path.read_text(encoding="utf-8"))
            candidate = (v2_raw.get("retrieval_holdout") or {}).get("epsilon")
            if candidate is not None:
                val = float(candidate)
                if 0.0 <= val <= 1.0:
                    return val
    except Exception:
        pass
    try:
        retrieval_path = Path(home) / "config" / "retrieval.toml"
        if retrieval_path.is_file():
            ret_raw = tomllib.loads(retrieval_path.read_text(encoding="utf-8"))
            candidate = (ret_raw.get("retrieval_holdout") or {}).get("epsilon")
            if candidate is not None:
                val = float(candidate)
                if 0.0 <= val <= 1.0:
                    return val
    except Exception:
        pass
    return 0.1


# ---------------------------------------------------------------------------
# Validity gate (§6.3): hard filters BEFORE scoring. Ranking stays inside
# semantic.search_memories (reused unchanged); this gate only ADDS the
# validity dimensions the plan requires and never re-scores.
# ---------------------------------------------------------------------------

_MANIFEST_WALK_MAX_LEVELS = 64


def _project_ancestors(cwd_path: Path) -> list[Path]:
    """Candidate project roots, stopping at the nearest Git repository boundary."""
    ancestors = []
    current = cwd_path
    for _ in range(_MANIFEST_WALK_MAX_LEVELS):
        ancestors.append(current)
        # A linked worktree uses a .git file. Even a broken marker must not
        # allow identity from an unrelated enclosing repository to leak in.
        if os.path.lexists(current / ".git"):
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return ancestors


def resolve_project(
    home: Path | str, cwd: str | None = None, explicit: str | None = None
) -> dict[str, str]:
    """Resolve one canonical project identity for every adapter surface."""
    if explicit is not None and str(explicit).strip():
        return {
            "project_id": validate_project_id(explicit),
            "resolution": "explicit",
            "repo_root": str(Path(cwd).resolve()) if cwd else "",
            "confidence": "high",
        }

    home_path = Path(home)
    cwd_path = Path(cwd).resolve() if cwd and str(cwd).strip() else None
    if cwd_path is not None:
        ancestors = _project_ancestors(cwd_path)
        try:
            for manifest_root in ancestors:
                manifest_id = registry.detect_explicit_id(str(manifest_root))
                if manifest_id:
                    return {
                        "project_id": validate_project_id(manifest_id),
                        "resolution": "manifest",
                        "repo_root": str(manifest_root),
                        "confidence": "high",
                    }
        except BrainError:
            raise
        except Exception:
            pass
        try:
            matches = []
            for project in registry.list_projects(home_path):
                if not project.repo_path:
                    continue
                root = Path(project.repo_path).resolve()
                if root not in ancestors:
                    continue
                matches.append((len(root.parts), project, root))
            if matches:
                _, project, root = max(matches, key=lambda item: item[0])
                return {
                    "project_id": validate_project_id(project.id),
                    "resolution": "registry_path",
                    "repo_root": str(root),
                    "confidence": "high",
                }
        except BrainError:
            raise
        except Exception:
            pass

        try:
            remote = registry.detect_git_remote(str(cwd_path))
            if remote:
                identity = registry.remote_identity(remote)
                for project in registry.list_projects(home_path):
                    if (
                        project.git_remote
                        and registry.remote_identity(project.git_remote) == identity
                    ):
                        return {
                            "project_id": validate_project_id(project.id),
                            "resolution": "git_remote",
                            "repo_root": str(cwd_path),
                            "confidence": "medium",
                        }
        except BrainError:
            raise
        except Exception:
            pass
    else:
        try:
            home_root = home_path.resolve()
            for project in registry.list_projects(home_path):
                if not project.repo_path:
                    continue
                root = Path(project.repo_path).resolve()
                try:
                    home_root.relative_to(root)
                except ValueError:
                    continue
                return {
                    "project_id": validate_project_id(project.id),
                    "resolution": "registry_path",
                    "repo_root": str(root),
                    "confidence": "high",
                }
        except BrainError:
            raise
        except Exception:
            pass

    env_project = os.environ.get("SECOND_BRAIN_PROJECT")
    if env_project and env_project.strip():
        return {
            "project_id": validate_project_id(env_project),
            "resolution": "env",
            "repo_root": str(cwd_path) if cwd_path else "",
            "confidence": "medium",
        }
    return {
        "project_id": "default",
        "resolution": "default",
        "repo_root": str(cwd_path) if cwd_path else "",
        "confidence": "low",
    }


def _resolve_project_id(home: Path | str, cwd: str | None, explicit: str | None) -> str:
    return resolve_project(home, cwd, explicit)["project_id"]


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


_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_SENTENCE_BREAK = re.compile(r"(?<=[.?!])\s+|\n+")
_LEADING_LABEL = re.compile(r"^[A-Za-z][A-Za-z ]{0,20}:\s+")
_MAX_FOCUS_QUESTIONS = 3


def _focused_query_text(text: str, project_id: str | None) -> str | None:
    """Deterministic task focus for instruction-heavy prompts (RET-02).

    Keeps only explicit question sentences (outside fenced code), drops a leading
    label such as ``Question:`` and the resolved project's own name tokens: the
    project scope filter already encodes that identity, so as query terms they
    only raise the lexical match requirement. Exact symbols inside the question
    are kept verbatim. Returns None when there is no question or nothing
    distinct from ``text`` remains.
    """
    prose = _FENCED_CODE.sub(" ", text)
    questions = [
        _LEADING_LABEL.sub("", sentence.strip())
        for sentence in _SENTENCE_BREAK.split(prose)
        if sentence.strip().endswith("?") and len(sentence.split()) >= 3
    ][:_MAX_FOCUS_QUESTIONS]
    if not questions:
        return None
    focus = " ".join(questions)
    if project_id and project_id not in ("default", "unknown"):
        names = sorted({t for t in re.split(r"[^a-z0-9]+", project_id.casefold()) if len(t) >= 3})
        if names:
            pattern = r"\b(?:" + "|".join(map(re.escape, names)) + r")\b"
            focus = re.sub(pattern, " ", focus, flags=re.IGNORECASE)
    focus = " ".join(focus.split())
    if not focus or focus.casefold() == " ".join(text.split()).casefold():
        return None
    return focus


def _valid_candidates(intent: RetrievalIntent, rows: list[dict]) -> list[dict]:
    """Apply the literal corpus admission policy before ranking/rendering.

    Missing or unknown metadata is rejected rather than assigned a default. Domain
    memories are usable when their project is known and matches, or when either side
    explicitly has no project identity; global memories are always eligible.
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
            raw_row_project = row.get("project_id")
            row_project = str(raw_row_project or "").strip()
            intent_project = str(intent.project_id or "").strip()
            row_unknown = row_project.lower() in unknown_projects
            intent_unknown = intent_project.lower() in unknown_projects
            if scope == "project":
                scope_ok = (
                    bool(intent_project)
                    and not intent_unknown
                    and bool(row_project)
                    and not row_unknown
                    and row_project == intent_project
                )
            else:
                scope_ok = (
                    intent_unknown
                    or row_unknown
                    or (row_project == intent_project and bool(row_project))
                )
        if not scope_ok:
            continue
        if not semantic._lane_authorized(row, intent.lane):
            # Missing authority metadata must not enter policy context.
            continue
        # Delta injection remains intentionally strict: only current,
        # high-confidence truth can be introduced mid-session.
        if intent.is_delta and (status != "current" or grade not in {"VERIFIED", "TESTED"}):
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

    Rule (documented, no invented metadata): a role keeps memories tagged with exactly
    its own tag OR untagged task-relevant memories. Memories tagged with another role
    are excluded — a worker never receives the parent's orchestrator-tagged memory and
    vice versa. Roles: orchestrator -> "orchestrator" tag; worker family
    (worker/explorer/ verifier) -> their own tag. Unknown/control roles get no filter.
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


def _build_items(home: Path | str, rows: list[dict], *, lane: str = "semantic") -> list[PacketItem]:
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
        conflicting = (contradiction_ids & admitted_ids) if lane == "policy" else contradiction_ids
        contradicted = bool(conflicting) or (row.get("_freshness_state") == freshness.CONTRADICTED)
        status, confidence = _grade_confidence(
            semantic.effective_evidence_grade(row), row.get("strength"), contradicted
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
                authority=semantic.effective_authority_ceiling(row),
            )
        )
    return items


# ---------------------------------------------------------------------------
# Canonical hashing + delivery ledger dedupe (§6.5).
# ---------------------------------------------------------------------------


def item_canonical_hash(item: PacketItem) -> str:
    """Sha256 of the canonical ITEM block (fixed order/labels/whitespace).

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

    Idempotent per lineage+item (INSERT OR IGNORE). When an item supersedes a previously
    delivered version, the old row's pointer is updated — the host message itself is
    never rewritten (§6.5). Raises on DB error; the caller applies fail-open.
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
            authority=i.authority,
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
    decision: BrainInjectionDecision,
    packet: str | None,
    delivery_id: str | None,
    project: dict[str, str] | None = None,
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
        "project_id": (project or {}).get("project_id"),
        "project_resolution": (project or {}).get("resolution"),
    }


def prepare_injection(
    home: Path | str,
    intent: RetrievalIntent,
    *,
    config: AutoInjectConfig | None = None,
    retrieval_text: str | None = None,
    seed: Any = None,
    random_fn: Callable[[], float] | None = None,
) -> BrainInjectionDecision:
    """Decision pipeline.

    NEVER raises: every failure degrades to
    NO_INJECTION(BRAIN_UNAVAILABLE) (§6.8). No model-visible mutation.
    """
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

    query_mode = "idf"
    query_text = (
        retrieval_text if retrieval_text is not None else _retrieval_query_text(home, intent)
    )
    focused_text = _focused_query_text(query_text, intent.project_id)
    proj_filter = (
        intent.project_id
        if intent.project_id and intent.project_id not in ("default", "unknown")
        else None
    )
    unscoped_candidates: list[dict] = []
    try:
        db.migrate(db_path(home))

        def retrieve_rows(text: str) -> tuple[hybrid_retrieval.CascadeResult, list[dict]]:
            # Primary search: Hybrid Multi-Tier Cascade Retrieval (Tiers 0-4)
            result = _CASCADE.retrieve(
                home,
                text,
                project_id=proj_filter,
                top_k=_MAX_CANDIDATES,
                lane=intent.lane,
            )
            if result.retrieval_error:
                raise RuntimeError("semantic retrieval unavailable")
            found = [
                m.raw_row if m.raw_row else (semantic._row(home, m.memory_id) or {})
                for m in result.matches
            ]

            # The semantic project prefilter excludes domain memories whose
            # project is unknown. Supplement known-project searches with the
            # unscoped result; _valid_candidates remains the security boundary.
            if proj_filter is not None:
                unscoped_cascade = _CASCADE.retrieve(
                    home,
                    text,
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
                seen_ids = {str(row.get("memory_id")) for row in found}
                found.extend(
                    row
                    for row in supplement
                    if row.get("memory_id") and str(row["memory_id"]) not in seen_ids
                )
            return result, found

        # The full query runs first so every case it already answers is unchanged;
        # the focused question query is tried only when it returns nothing.
        cascade_res, rows = retrieve_rows(query_text)
        if not rows and focused_text is not None:
            cascade_res, rows = retrieve_rows(focused_text)
            if rows:
                query_mode = "idf_focused"
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

    # Filter candidate items by need-cost ROI: skip if P_need * value < token_cost_ratio
    row_by_id = {str(r.get("memory_id") or ""): r for r in role_rows}
    retained_fresh: list[PacketItem] = []
    for item in fresh:
        row = row_by_id.get(item.memory_id, {})
        p_need = row.get("_p_need")
        if p_need is None and home is not None:
            try:
                from . import reconsolidation

                b = reconsolidation.compute_base_level_activation(Path(home), item.memory_id)
                if b <= -10.0:
                    p_need = 0.5
                else:
                    p_need = reconsolidation.compute_p_need(Path(home), item.memory_id)
            except Exception:
                p_need = 0.5
        if p_need is None:
            p_need = 0.5
        p_need = float(p_need)

        try:
            w = semantic._DEFAULT_RETRIEVAL_CONFIG.weights
            trust = semantic._trust_score(row, w) if row else 1.0
        except Exception:
            trust = 1.0

        if row.get("_bm25_normalized") is not None:
            relevance = float(row["_bm25_normalized"])
        elif row.get("_score") is not None:
            relevance = float(row["_score"])
        elif row.get("_bm25") is not None:
            relevance = float(row["_bm25"])
        else:
            relevance = 1.0

        value = float(trust) * float(relevance)
        item_text = _render_packet_text([item], intent.project_id, lane=intent.lane)
        item_tokens = token_estimate(item_text, home=home)
        target_tokens = max(1, active_budget.target_tokens)
        token_cost_ratio = item_tokens / target_tokens

        if p_need * value < token_cost_ratio:
            continue
        retained_fresh.append(item)

    fresh = retained_fresh
    if not fresh:
        return decision(
            NoInjectionReason.CONTEXT_PRESSURE,
            candidate_ids=candidate_ids,
            selected_ids=[],
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

    # T5.2: Retrieval injection holdout
    stage = _retrieval_holdout_stage(home)
    stage_rank = _ROLLOUT_STAGE_RANKS.get(stage, 0)
    is_stage_eligible = stage_rank >= _ROLLOUT_STAGE_RANKS["CANARY"]

    t_class_val = classify_task(
        intent.task_text or "", risk_class=getattr(intent, "risk_class", None)
    ).value
    is_class_eligible = t_class_val in {"trivial", "navigation", "implementation"} and getattr(
        intent, "risk_class", None
    ) not in ("HIGH", "CRITICAL")

    # Authority gate: a caller-minted ceiling is not authority, so only rows whose
    # *effective* ceiling is advisory may enter the holdout. Otherwise a memory
    # could exempt itself from measurement by claiming project_rule.
    is_authority_eligible = intent.lane != "policy" and all(
        (getattr(item, "authority", "advisory") == "advisory")
        and semantic.effective_authority_ceiling(row_by_id.get(item.memory_id, {})) == "advisory"
        for item in selected
    )

    if is_stage_eligible and is_class_eligible and is_authority_eligible and selected:
        epsilon = _retrieval_holdout_epsilon(home)
        if random_fn is not None:
            rand_val = random_fn()
            holdout_triggered = (
                (rand_val < epsilon) if isinstance(rand_val, (int, float)) else bool(rand_val)
            )
        elif seed is not None:
            holdout_triggered = random.Random(seed).random() < epsilon
        else:
            holdout_triggered = random.random() < epsilon

        if holdout_triggered:
            withheld = selected[0]
            delivered = selected[1:]
            withheld_id = withheld.memory_id
            delivered_ids = [i.memory_id for i in delivered]

            try:
                decisions.record(
                    home,
                    kind="retrieval",
                    session_id=intent.session_id,
                    task_id=None,
                    chosen=delivered_ids,
                    alternatives=[withheld_id],
                    propensity=epsilon,
                    randomized=True,
                    policy_version="v5.2",
                    stage=stage,
                    inputs={
                        "task_sha256": _task_sha256(intent.task_text),
                        "withheld_id": withheld_id,
                        "task_class": t_class_val,
                    },
                )
            except Exception:
                logger.debug("retrieval holdout decision record failed", exc_info=True)

            if not delivered:
                return decision(
                    NoInjectionReason.HOLDOUT,
                    candidate_ids=candidate_ids,
                    selected_ids=[],
                )

            selected = delivered
        else:
            try:
                decisions.record(
                    home,
                    kind="retrieval",
                    session_id=intent.session_id,
                    task_id=None,
                    chosen=[i.memory_id for i in selected],
                    alternatives=[],
                    propensity=1.0 - epsilon,
                    randomized=True,
                    policy_version="v5.2",
                    stage=stage,
                    inputs={
                        "task_sha256": _task_sha256(intent.task_text),
                        "withheld_id": None,
                        "task_class": t_class_val,
                    },
                )
            except Exception:
                logger.debug("retrieval delivery decision record failed", exc_info=True)

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


def _append_telemetry(home: Path | str, session: str, kind: str, extra: dict[str, Any]) -> bool:
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


def _session_started_marker_path(home: Path | str, host_session_id: str) -> Path | None:
    try:
        return ledger.session_dir(home, host_session_id) / "session-started.marker"
    except Exception:
        return None


def _has_session_started(home: Path | str, host_session_id: str) -> bool:
    """O(1) idempotency check: has a durable marker for this host_session_id already
    been written?

    Replaces a prior full JSONL-telemetry-file scan
    (re-reading the whole growing per-session file on every call) with a
    single ``Path.exists()``. Fails open (returns False, i.e. "allow the
    write") on any read error so a corrupt/unreadable state directory never
    blocks lifecycle telemetry.
    """
    try:
        marker = _session_started_marker_path(home, host_session_id)
        return marker is not None and marker.exists()
    except OSError:
        return False


def _mark_session_started(home: Path | str, host_session_id: str) -> None:
    """Create the durable marker checked by `_has_session_started`.

    Never
    raises: a marker-write failure only means the next call re-scans the
    (fail-open) idempotency check, never blocks lifecycle telemetry.
    """
    try:
        marker = _session_started_marker_path(home, host_session_id)
        if marker is None:
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# BrainLifecycle control adapter (§6.9).
# ---------------------------------------------------------------------------


def _feedback_exists(home: Path | str, table: str, memory_id: str, session_id: str) -> bool:
    """Check one session-bound feedback row without exposing its contents."""
    if table not in {"memory_retrievals", "memory_activations"}:
        return False
    conn = db.connect(db_path(Path(home)), readonly=True)
    try:
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE memory_id = ? AND session_id = ? LIMIT 1",
            (memory_id, session_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _record_delivery_feedback(home: Path | str, memory_ids: list[str], session_id: str) -> None:
    """Record one retrieval per delivered memory, best-effort and idempotently."""
    for memory_id in dict.fromkeys(memory_ids):
        try:
            if not _feedback_exists(home, "memory_retrievals", memory_id, session_id):
                reconsolidation.record_retrieval(
                    Path(home), memory_id, session_id=session_id, idempotent=True
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
    conn = db.connect(db_path(Path(home)), readonly=True)
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
            recorded = _append_telemetry(
                self._home,
                identity.host_session_id,
                "session_started",
                {"host": identity.host, "host_session_id": identity.host_session_id},
            )
            if recorded:
                _mark_session_started(self._home, identity.host_session_id)
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
        seed: Any = None,
        random_fn: Callable[[], float] | None = None,
    ) -> BrainInjectionDecision:
        """Decision + ledger/telemetry record. Never raises.

        ``cwd`` feeds project resolution: explicit project_id wins,
        then a registered project whose root contains cwd, then env, then
        "default". The retrieval-attempt telemetry (with query_mode and is_delta) is
        recorded inside the module pipeline.
        """
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
        decision = prepare_injection(
            self._home,
            intent,
            seed=seed,
            random_fn=random_fn,
        )
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
                _record_delivery_feedback(self._home, decision.selected_ids, effective_session)
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
        acceptance_passed: bool | None = None,
        tokens_total: int | None = None,
    ) -> None:
        feedback_session = (
            session_id
            or self._feedback_session_id
            or (self._session.host_session_id if self._session is not None else None)
        )
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

            # T5.2: Record outcomes for pending retrieval decisions
            try:
                dbfile = db.db_path(Path(self._home))
                if acceptance_passed is not None and dbfile.is_file():
                    conn = db.connect(dbfile)
                    try:
                        rows = conn.execute(
                            "SELECT decision_id FROM decisions WHERE session_id = ? AND kind ="
                            " 'retrieval' AND outcome_json IS NULL",
                            (feedback_session,),
                        ).fetchall()
                        decision_ids = [str(r[0]) for r in rows if r and r[0]]
                    finally:
                        conn.close()

                    if decision_ids:
                        actual_tokens = tokens_total
                        if actual_tokens is None:
                            try:
                                actual_tokens = governor._session_total_tokens(
                                    Path(self._home), feedback_session
                                )
                            except (OSError, ValueError):
                                logger.debug(
                                    "session usage unavailable for retrieval outcome", exc_info=True
                                )
                        reward = 1.0 if acceptance_passed else 0.0
                        outcome = {
                            "acceptance_passed": bool(acceptance_passed),
                            "tokens_total": actual_tokens,
                        }
                        for dec_id in decision_ids:
                            try:
                                decisions.record_outcome(self._home, dec_id, outcome, reward)
                            except Exception:
                                logger.debug(
                                    "Failed to record outcome for decision %s",
                                    dec_id,
                                    exc_info=True,
                                )
            except Exception:
                logger.debug("retrieval decision finalization failed", exc_info=True)
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
