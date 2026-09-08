"""Bounded Simplification Review contract and project debt linkage."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import ledger
from .autoinject import _append_telemetry
from .contracts import (
    BrainLifecycleEvent,
    LifecycleEventType,
    SimplificationReviewOutcome,
    SurfaceVisibility,
    canonical_json,
)
from .errors import BrainError

DEBT_HEADER = "| ID | Debt | Why deferred | Revisit trigger | Status | Evidence | Updated |"
DEBT_SEPARATOR = "|------|------|--------------|-----------------|--------|----------|---------|"
DEBT_ID_RE = re.compile(r"^DEBT-[0-9a-f]{16}$")
MAX_HASHES = 16
MAX_METRICS = 16


SimplificationOutcome = SimplificationReviewOutcome


def _is_hex(value: str) -> bool:
    return all(char in "0123456789abcdefABCDEF" for char in value)


@dataclass(frozen=True)
class SimplificationReview:
    review_id: str
    project_id: str
    task_id: str
    session_id: str
    outcome: SimplificationOutcome
    reason_code: str
    affected_hashes: list[str] = field(default_factory=list)
    changed_hashes: list[str] = field(default_factory=list)
    deferred_hashes: list[str] = field(default_factory=list)
    debt_ref: str | None = None
    verification: str = "passed"
    metrics: dict[str, int | float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("review_id", "project_id", "task_id", "session_id", "reason_code"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 256:
                raise BrainError(f"invalid simplification review {name}")
        if not isinstance(self.outcome, SimplificationOutcome):
            raise BrainError("invalid simplification review outcome")
        if self.verification not in {"passed", "failed", "blocked", "not_run"}:
            raise BrainError("invalid simplification review verification")
        for name in ("affected_hashes", "changed_hashes", "deferred_hashes"):
            values = getattr(self, name)
            if not isinstance(values, list) or len(values) > MAX_HASHES:
                raise BrainError(f"invalid simplification review {name}")
            if any(
                not isinstance(item, str) or len(item) != 64 or not _is_hex(item) for item in values
            ):
                raise BrainError(f"invalid simplification review {name}")
        if self.debt_ref is not None and not DEBT_ID_RE.fullmatch(self.debt_ref):
            raise BrainError("invalid simplification debt reference")
        if not isinstance(self.metrics, dict) or len(self.metrics) > MAX_METRICS:
            raise BrainError("invalid simplification review metrics")
        for key, value in self.metrics.items():
            if not isinstance(key, str) or len(key) > 64 or not isinstance(value, (int, float)):
                raise BrainError("invalid simplification review metric")
            if isinstance(value, float) and not math.isfinite(value):
                raise BrainError("invalid simplification review metric")

    def bounded(
        self, *, debt_ref: str | None = None, debt_status: str | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "review_id": self.review_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "affected_hashes": list(self.affected_hashes),
            "changed_hashes": list(self.changed_hashes),
            "deferred_hashes": list(self.deferred_hashes),
            "debt_ref": debt_ref or self.debt_ref,
            "verification": self.verification,
            "metrics": dict(self.metrics),
        }
        if debt_status is not None:
            result["debt_status"] = debt_status
        return result


def canonical_task_body_sha256(task: str) -> str:
    if not isinstance(task, str) or not task.strip():
        raise BrainError("task body must be non-empty")
    return hashlib.sha256(task.strip().encode("utf-8")).hexdigest()


def _debt_id(review: SimplificationReview) -> str:
    identity = {
        "project_id": review.project_id,
        "affected_hashes": sorted(review.affected_hashes),
        "reason_code": review.reason_code,
    }
    return f"DEBT-{hashlib.sha256(canonical_json(identity).encode()).hexdigest()[:16]}"


def _debt_path(project_root: Path) -> Path:
    return project_root / "simplification-debt.md"


def _ensure_debt_table(path: Path) -> str:
    if not path.exists():
        return (
            "# Simplification Debt\n\n"
            "Valid deferred simplifications. Do not re-discover them repeatedly.\n\n"
            + DEBT_HEADER
            + "\n"
            + DEBT_SEPARATOR
            + "\n"
        )
    text = path.read_text(encoding="utf-8")
    if DEBT_HEADER not in text or DEBT_SEPARATOR not in text:
        raise BrainError(f"corrupt simplification-debt.md: {path}")
    return text


def _split_row(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def _upsert_debt(path: Path, review: SimplificationReview, debt_ref: str, status: str) -> None:
    text = _ensure_debt_table(path)
    lines = text.splitlines()
    row = [
        debt_ref,
        ", ".join(review.affected_hashes),
        review.reason_code,
        "future qualified cleanup review",
        status,
        ", ".join(review.deferred_hashes or review.changed_hashes),
        datetime.now(UTC).isoformat(),
    ]
    replaced = False
    output: list[str] = []
    for line in lines:
        parts = _split_row(line) if line.startswith("|") else []
        if parts and parts[0] == debt_ref and len(parts) >= 7:
            row[1] = row[1] or parts[1]
            row[2] = parts[2] if status == "resolved" else (row[2] or parts[2])
            row[3] = parts[3]
            row[5] = row[5] or parts[5]
            output.append("| " + " | ".join(row) + " |")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append("| " + " | ".join(row) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _record_ledger_event(
    home: Path, review: SimplificationReview, payload: dict[str, Any]
) -> str | None:
    event_id = f"simplification-review-{review.review_id}-{review.outcome.value}"
    event = BrainLifecycleEvent(
        seq=0,
        event_id=event_id,
        internal_session_id=ledger.internal_session_id(review.session_id),
        agent_id="simplification-review",
        event_type=LifecycleEventType.SIMPLIFICATION_REVIEW,
        timestamp=datetime.now(UTC).isoformat(),
        surface_visibility=SurfaceVisibility.BOOKKEEPING,
        ignorable=False,
        payload=payload,
    )
    try:
        with ledger.LedgerStore(home, review.session_id, host="prime").open(create=True) as store:
            store.append_events([event])
        return event_id
    except BrainError:
        return None


def record_review(home: Path, project_root: Path, review: SimplificationReview) -> dict[str, Any]:
    """Persist one bounded review, updating debt only for defer/resolve."""
    home = Path(home)
    project_root = Path(project_root)
    debt_ref = review.debt_ref
    debt_status: str | None = None
    if (
        review.outcome in {SimplificationOutcome.SIMPLIFY, SimplificationOutcome.REUSE}
        and review.verification != "passed"
    ):
        raise BrainError("verification must pass before accepting simplification or reuse")
    if review.outcome is SimplificationOutcome.DEFER:
        debt_ref = debt_ref or _debt_id(review)
        _upsert_debt(_debt_path(project_root), review, debt_ref, "deferred")
        debt_status = "deferred"
    elif review.outcome is SimplificationOutcome.SIMPLIFY and debt_ref is not None:
        _upsert_debt(_debt_path(project_root), review, debt_ref, "resolved")
        debt_status = "resolved"
    result = review.bounded(debt_ref=debt_ref, debt_status=debt_status)
    result["ledger_event_id"] = _record_ledger_event(home, review, result)
    _append_telemetry(home, review.session_id, "simplification_review", result)
    return result
