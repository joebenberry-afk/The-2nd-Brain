"""Frontier memory — manual review gate for risky policy changes (plan §117, Phase 21).

A change is CLEARED only by an 'approve' verdict. Reviews live under
``frontier/<change_id>.md`` (first review) with re-reviews as
``frontier/<change_id>-<n>.md`` (latest verdict wins) — except that 'reject'
is FINAL: no further review is possible for that change_id. Holds for changes
awaiting review are recorded under ``frontier/pending/<change_id>.hold`` so a
high-risk change without approval can never be activated (gate_check).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .errors import BrainError

RISKS: tuple[str, ...] = ("low", "medium", "high")
VERDICTS: tuple[str, ...] = ("approve", "reject", "request_changes")
FINAL_VERDICT = "reject"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _frontier_dir(home: Path) -> Path:
    return Path(home) / "frontier"


def _pending_dir(home: Path) -> Path:
    return _frontier_dir(home) / "pending"


def _review_sort_key(path: Path) -> tuple[int, int]:
    """Base review sorts first; sequence files by their -N number."""
    parts = path.stem.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return (1, int(parts[1]))
    return (0, 0)


def _review_files(home: Path, change_id: str) -> list[Path]:
    directory = _frontier_dir(home)
    if not directory.is_dir():
        return []
    names = [p for p in directory.glob(f"{change_id}*.md")]
    return sorted(names, key=_review_sort_key)


def _hold_path(home: Path, change_id: str) -> Path:
    return _pending_dir(home) / f"{change_id}.hold"


def _read_review(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrainError(f"Corrupt frontier review {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BrainError(f"Corrupt frontier review {path}: not a JSON object")
    return data


def _reserve_exclusive(path: Path) -> int | None:
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def _next_review_target(home: Path, change_id: str) -> Path:
    """First review -> <change_id>.md; re-reviews -> <change_id>-<n>.md."""
    base = _frontier_dir(home) / f"{change_id}.md"
    if not base.exists():
        return base
    counter = 2
    while True:
        candidate = _frontier_dir(home) / f"{change_id}-{counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1


def frontier_review(
    home: Path,
    change_id: str,
    summary: str,
    risk: str,
    reviewer: str,
    verdict: str,
    notes: str = "",
) -> Path:
    """Record one review. 'reject' is final: re-reviewing a rejected change
    raises BrainError. All other verdicts may be superseded by a later review
    (``<change_id>-<n>.md`` sequence); the latest verdict wins."""
    for name, value in (("change_id", change_id), ("summary", summary), ("reviewer", reviewer)):
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"{name} must be a non-empty string")
    if risk not in RISKS:
        raise BrainError(f"risk must be one of {', '.join(RISKS)}")
    if verdict not in VERDICTS:
        raise BrainError(f"verdict must be one of {', '.join(VERDICTS)}")
    if not isinstance(notes, str):
        raise BrainError("notes must be a string")

    existing = _review_files(home, change_id)
    if existing:
        latest = _read_review(existing[-1])
        if latest.get("verdict") == FINAL_VERDICT:
            raise BrainError(
                f"Change {change_id!r} was rejected and cannot be re-reviewed (final verdict)"
            )
    target = _next_review_target(home, change_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "change_id": change_id,
        "summary": summary,
        "risk": risk,
        "reviewer": reviewer,
        "verdict": verdict,
        "notes": notes,
        "reviewed_at": _utcnow(),
    }
    fd = _reserve_exclusive(target)
    if fd is None:  # race: someone else created it; retry on the next name
        target = _next_review_target(home, change_id)
        fd = _reserve_exclusive(target)
        if fd is None:
            raise BrainError(f"Could not reserve a review file for {change_id!r}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise BrainError(f"Could not write frontier review {target}: {exc}") from exc
    return target


def _latest_verdict(home: Path, change_id: str) -> dict | None:
    files = _review_files(home, change_id)
    if not files:
        return None
    return _read_review(files[-1])


def frontier_status(home: Path, change_id: str | None = None) -> dict:
    """Change_id=None: verdict/risk counts over LATEST verdicts + pending holds.
    Change_id given: the full review sequence for that change."""
    directory = _frontier_dir(home)
    if change_id is not None:
        files = _review_files(home, change_id)
        latest = _latest_verdict(home, change_id)
        return {
            "change_id": change_id,
            "reviews": [_read_review(path) for path in files],
            "latest_verdict": latest.get("verdict") if latest is not None else None,
        }
    change_ids = (
        sorted({_change_id_from_name(path.name) for path in directory.glob("*.md")})
        if directory.is_dir()
        else []
    )
    counts = {"total": 0, "approved": 0, "rejected": 0, "request_changes": 0}
    by_risk: dict[str, int] = {risk: 0 for risk in RISKS}
    count_key = {"approve": "approved", "reject": "rejected", "request_changes": "request_changes"}
    for cid in change_ids:
        latest = _latest_verdict(home, cid)
        if latest is None:
            continue
        counts["total"] += 1
        counts[count_key[latest["verdict"]]] += 1
        by_risk[latest["risk"]] = by_risk.get(latest["risk"], 0) + 1
    pending = _pending_dir(home)
    held = sorted(p.stem for p in pending.glob("*.hold")) if pending.is_dir() else []
    pending_high_risk = [cid for cid in held if _latest_verdict(home, cid) is None]
    return {**counts, "by_risk": by_risk, "pending_high_risk": pending_high_risk}


def _change_id_from_name(name: str) -> str:
    """'change-2.md' -> 'change'; '<id>.md' -> '<id>' (reviews never embed '-'+digits)."""
    stem = name[:-3]
    parts = stem.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return stem


def require_review(
    home: Path,
    change_id: str,
    summary: str,
    risk: str = "high",
    reviewer: str = "",
) -> Path | None:
    """No-op (returns the latest review path) when a review exists. Otherwise
    records a pending hold; high-risk returns None (hard gate), other risks
    return the hold path as a draft-only marker."""
    if not isinstance(change_id, str) or not change_id.strip():
        raise BrainError("change_id must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise BrainError("summary must be a non-empty string")
    if risk not in RISKS:
        raise BrainError(f"risk must be one of {', '.join(RISKS)}")
    if not isinstance(reviewer, str):
        raise BrainError("reviewer must be a string")
    latest = _latest_verdict(home, change_id)
    if latest is not None:
        files = _review_files(home, change_id)
        return files[-1]
    hold = _hold_path(home, change_id)
    hold.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "change_id": change_id,
        "summary": summary,
        "risk": risk,
        "reviewer": reviewer,
        "created_at": _utcnow(),
    }
    with hold.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return None if risk == "high" else hold


def gate_check(home: Path, change_id: str) -> dict:
    """{ok, missing}: cleared only by a latest verdict of 'approve'. A reject
    is permanently blocked; request_changes and no-review are blocked."""
    latest = _latest_verdict(home, change_id)
    if latest is None:
        return {"ok": False, "missing": ["no review"]}
    verdict = latest["verdict"]
    if verdict == "approve":
        return {"ok": True, "missing": []}
    if verdict == "reject":
        return {"ok": False, "missing": ["rejected (final)"]}
    return {"ok": False, "missing": [f"latest verdict is {verdict!r}; approve required"]}


def list_pending(home: Path) -> list[str]:
    """Hold change-ids that STILL await review (a review clears the hold from
    the pending list, even though the .hold file itself is kept on disk)."""
    pending = _pending_dir(home)
    if not pending.is_dir():
        return []
    return sorted(p.stem for p in pending.glob("*.hold") if _latest_verdict(home, p.stem) is None)
