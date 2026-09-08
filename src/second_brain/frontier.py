"""Frontier memory — manual review gate for risky policy changes (plan §117, Phase 21).

A change is CLEARED only by an 'approve' verdict. Reviews live under
``frontier/<change_id>.md`` (first review) with re-reviews as
``frontier/<change_id>-<n>.md`` (latest verdict wins) — except that 'reject'
is FINAL: no further review is possible for that change_id. Holds for changes
awaiting review are recorded under ``frontier/pending/<change_id>.hold`` so a
high-risk change without approval can never be activated (gate_check).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import artifacts, contracts, db, decisions
from .errors import BrainError
from .security.identifiers import validate_frontier_id

RISKS: tuple[str, ...] = ("low", "medium", "high")
VERDICTS: tuple[str, ...] = ("approve", "reject", "request_changes")
FINAL_VERDICT = "reject"


def _valid_change_id(change_id: str) -> str:
    """Change ids are simple identifiers (SEC-04) and must NOT end in
    '-<digits>' (that suffix is reserved for review sequence files)."""
    change_id = validate_frontier_id(change_id)
    if re.fullmatch(r".*-\d+", change_id):
        raise BrainError(
            f"change_id {change_id!r} ends in '-<digits>' which is reserved "
            "for review sequence files"
        )
    return change_id


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
    """Review files for one change id: ``<id>.md`` plus ``<id>-<n>.md``.

    Never interpolates the id into a glob pattern (SEC-04): candidate names
    are matched exactly against the validated identifier.
    """
    directory = _frontier_dir(home)
    if not directory.is_dir():
        return []
    names: list[Path] = []
    base = directory / f"{change_id}.md"
    if base.is_file():
        names.append(base)
    prefix = change_id + "-"
    for path in directory.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name.startswith(prefix) and name.endswith(".md"):
            sequence = name[len(prefix) : -len(".md")]
            if sequence.isdigit():
                names.append(path)
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


def latest_review(home: Path, change_id: str) -> dict | None:
    """Return the latest review record for callers that need its binding."""
    return _latest_verdict(home, _valid_change_id(change_id))


def frontier_review(
    home: Path,
    change_id: str,
    summary: str,
    risk: str,
    reviewer: str,
    verdict: str,
    notes: str = "",
    *,
    artifact_path: str | None = None,
    artifact_sha256: str | None = None,
    artifact_version: str | None = None,
    eval_manifest_sha256: str | None = None,
) -> Path:
    """Record one review. 'reject' is final: re-reviewing a rejected change
    raises BrainError. All other verdicts may be superseded by a later review
    (``<change_id>-<n>.md`` sequence); the latest verdict wins."""
    change_id = _valid_change_id(change_id)
    for name, value in (("summary", summary), ("reviewer", reviewer)):
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"{name} must be a non-empty string")
    if risk not in RISKS:
        raise BrainError(f"risk must be one of {', '.join(RISKS)}")
    if verdict not in VERDICTS:
        raise BrainError(f"verdict must be one of {', '.join(VERDICTS)}")
    if not isinstance(notes, str):
        raise BrainError("notes must be a string")

    if change_id.startswith("skill-") and change_id.endswith("-promotion"):
        from . import skillforge

        name = change_id[len("skill-") : -len("-promotion")]
        binding = skillforge.artifact_binding(home, name)
        artifact_path = artifact_path or binding["artifact_path"]
        artifact_sha256 = artifact_sha256 or binding["artifact_sha256"]
        artifact_version = artifact_version or binding["artifact_version"]
        eval_manifest_sha256 = eval_manifest_sha256 or binding["eval_manifest_sha256"]

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
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha256,
        "artifact_version": artifact_version,
        "eval_manifest_sha256": eval_manifest_sha256,
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
        # SEC-04: change_id reaches filesystem paths here; validate before
        # use (mirrors latest_review). A hostile id must never influence
        # which file outside frontier/ is read.
        change_id = _valid_change_id(change_id)
        files = _review_files(home, change_id)
        latest = _latest_verdict(home, change_id)
        return {
            "change_id": change_id,
            "reviews": [_read_review(path) for path in files],
            "latest_verdict": latest.get("verdict") if latest is not None else None,
        }
    change_ids = []
    if directory.is_dir():
        for path in directory.glob("*.md"):
            cid = _change_id_from_name(path.name)
            try:
                _valid_change_id(cid)
            except BrainError:
                continue  # legacy/hostile file name is not treated as a change
            change_ids.append(cid)
        change_ids = sorted(set(change_ids))
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
    held = []
    if pending.is_dir():
        for path in pending.glob("*.hold"):
            try:
                cid = validate_frontier_id(path.stem)
            except BrainError:
                continue  # legacy/hostile hold names are not treated as changes
            held.append(cid)
    held = sorted(held)
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
    change_id = _valid_change_id(change_id)
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
    change_id = _valid_change_id(change_id)
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
    held = []
    for path in pending.glob("*.hold"):
        try:
            cid = validate_frontier_id(path.stem)
        except BrainError:
            continue  # legacy/hostile hold names are ignored for the gate
        if _latest_verdict(home, cid) is None:
            held.append(cid)
    return sorted(held)


def _dbfile(home: Path) -> Path:
    return db.db_path(home)


def _ensure_migrated(home: Path) -> None:
    if db.pending_migrations(_dbfile(home)):
        db.migrate(_dbfile(home))


def create_frontier_item(
    home: Path | str,
    unknown: str,
    decision_ref: str,
    *,
    stake_tokens: float | None = None,
    p_flip: float | None = None,
    expected_cost: float | None = None,
    experiments: list[dict[str, Any]] | None = None,
    scope: str = "project",
    why_matters: str = "",
    evidence_refs: list[str] | None = None,
    status: str = "OPEN",
    confidence: float | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Create a decision-linked operational knowledge frontier item.

    Rule 1: Frontier items must represent uncertainty that could change an actual Brain decision.
    Rule 2: Items without decision_ref are strictly rejected.
    Rule 3: priority = stake_tokens * p_flip / expected_cost.
    Unknown numeric inputs stay null and cannot outrank measured items.
    """
    home_p = Path(home)
    _ensure_migrated(home_p)

    if not decision_ref or not str(decision_ref).strip():
        raise BrainError(
            "Frontier item requires a valid non-empty decision_ref "
            "linking to an operational decision"
        )

    if not unknown or not str(unknown).strip():
        raise BrainError("Frontier item requires a non-empty unknown description")

    status_upper = str(status).strip().upper()
    if status_upper not in ("OPEN", "INVESTIGATING", "CLOSED", "EXPIRED"):
        raise BrainError(f"Invalid frontier item status {status!r}")

    # Unknown measurements stay null; malformed measurements are not estimates.
    for name, value in (
        ("stake_tokens", stake_tokens),
        ("p_flip", p_flip),
        ("expected_cost", expected_cost),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise BrainError(f"{name} must be a finite non-negative number or None")
    stake_val = float(stake_tokens) if stake_tokens is not None else None
    p_flip_val = float(p_flip) if p_flip is not None else None
    cost_val = float(expected_cost) if expected_cost is not None else None

    if p_flip_val is not None and not (0.0 <= p_flip_val <= 1.0):
        raise BrainError("p_flip must be between 0.0 and 1.0")

    if stake_val is not None and p_flip_val is not None and cost_val is not None and cost_val > 0:
        priority: float | None = round((stake_val * p_flip_val) / cost_val, 4)
    else:
        priority = None

    now = _utcnow()
    identity_str = f"{decision_ref}:{unknown}:{scope}"
    frontier_id = "front-" + hashlib.sha256(identity_str.encode("utf-8")).hexdigest()[:24]

    experiments_list = list(experiments or [])
    evidence_list = list(evidence_refs or [])

    prov_hash = hashlib.sha256(
        contracts.canonical_json(
            {
                "decision_ref": decision_ref,
                "unknown": unknown,
                "priority": priority,
            }
        ).encode("utf-8")
    ).hexdigest()

    conn = db.connect(_dbfile(home_p))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT OR REPLACE INTO v2_frontier_items(
                frontier_id, decision_ref, unknown, why_matters, scope,
                stake_tokens, p_flip, expected_cost, priority,
                experiments_json, evidence_refs_json, status, confidence,
                provenance_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                frontier_id,
                decision_ref,
                unknown.strip(),
                why_matters.strip(),
                scope.strip(),
                stake_val,
                p_flip_val,
                cost_val,
                priority,
                contracts.canonical_json(experiments_list),
                contracts.canonical_json(evidence_list),
                status_upper,
                confidence,
                prov_hash,
                now,
                now,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not persist frontier item: {exc}") from exc
    finally:
        conn.close()

    dec_ref = decisions.record(
        home_p,
        kind="frontier",
        session_id=session_id or f"sess-{frontier_id}",
        task_id=task_id or f"task-{frontier_id}",
        chosen={
            "action": "create_frontier_item",
            "frontier_id": frontier_id,
            "priority": priority,
            "status": status_upper,
        },
        alternatives=[{"action": "no_frontier_item"}],
        propensity=1.0,
        randomized=False,
        policy_version="v7.8",
        stage="SHADOW",
        inputs={
            "decision_ref": decision_ref,
            "stake_tokens": stake_val,
            "p_flip": p_flip_val,
            "expected_cost": cost_val,
            "priority": priority,
        },
    )

    return {
        "frontier_id": frontier_id,
        "decision_ref": decision_ref,
        "unknown": unknown.strip(),
        "why_matters": why_matters.strip(),
        "scope": scope.strip(),
        "stake_tokens": stake_val,
        "p_flip": p_flip_val,
        "expected_cost": cost_val,
        "priority": priority,
        "experiments": experiments_list,
        "evidence_refs": evidence_list,
        "status": status_upper,
        "confidence": confidence,
        "decision_logged_ref": dec_ref,
        "provenance_hash": prov_hash,
        "created_at": now,
        "updated_at": now,
    }


def get_frontier_item(home: Path | str, frontier_id: str) -> dict[str, Any] | None:
    home_p = Path(home)
    _ensure_migrated(home_p)
    conn = db.connect(_dbfile(home_p), readonly=True)
    try:
        row = conn.execute(
            "SELECT * FROM v2_frontier_items WHERE frontier_id = ?", (frontier_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    res = dict(row)
    res["experiments"] = json.loads(res["experiments_json"])
    res["evidence_refs"] = json.loads(res["evidence_refs_json"])
    return res


def list_frontier_items(home: Path | str, *, status: str | None = None) -> list[dict[str, Any]]:
    """List operational frontier items.

    Measured items with calculated priority always sort first in descending order.
    Items with unknown cost (null priority) sort last.
    """
    home_p = Path(home)
    _ensure_migrated(home_p)
    conn = db.connect(_dbfile(home_p), readonly=True)
    try:
        sql = "SELECT * FROM v2_frontier_items WHERE 1=1"
        params: list[Any] = []
        if status is not None:
            sql += " AND status = ?"
            params.append(str(status).strip().upper())
        sql += " ORDER BY (priority IS NOT NULL) DESC, priority DESC, created_at DESC"
        rows = conn.execute(sql, params).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["experiments"] = json.loads(d["experiments_json"])
            d["evidence_refs"] = json.loads(d["evidence_refs_json"])
            items.append(d)
        return items
    finally:
        conn.close()


def _require_replayable_decision(conn: sqlite3.Connection, ref: Any) -> None:
    """Resolve decision:<id>[:<kind>[:<choice>]] against durable replay inputs."""
    parts = ref.split(":") if isinstance(ref, str) else []
    if (
        len(parts) not in (2, 3, 4)
        or parts[0] != "decision"
        or any(not part.strip() for part in parts[1:])
    ):
        raise BrainError(f"Invalid decision evidence reference {ref!r}")
    row = conn.execute("SELECT * FROM decisions WHERE decision_id = ?", (parts[1],)).fetchone()
    if row is None:
        raise BrainError(f"Unknown decision evidence reference {ref!r}")
    if len(parts) >= 3 and parts[2] != row["kind"]:
        raise BrainError(f"Decision evidence kind does not match ledger: {ref!r}")
    try:
        inputs = json.loads(row["inputs_json"])
        json.loads(row["chosen_json"])
        json.loads(row["alternatives_json"])
    except (TypeError, ValueError) as exc:
        raise BrainError(f"Decision evidence is not replayable: {ref!r}") from exc
    expected_id = hashlib.sha256(
        (contracts.canonical_json(inputs) + row["session_id"] + row["kind"]).encode("utf-8")
    ).hexdigest()[:24]
    if (
        inputs is None
        or contracts.stable_content_hash(inputs) != row["inputs_hash"]
        or expected_id != row["decision_id"]
    ):
        raise BrainError(f"Decision evidence replay identity mismatch: {ref!r}")


def choose_cheapest_experiment(home: Path | str, frontier_id: str) -> dict[str, Any]:
    """Select the cheapest eligible, discriminating experiment."""
    item = get_frontier_item(home, frontier_id)
    if item is None:
        raise BrainError(f"Unknown frontier item {frontier_id!r}")
    if item.get("status") not in {"OPEN", "INVESTIGATING"}:
        raise BrainError("Frontier item is not eligible for experiment selection")

    evidence_refs = item.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise BrainError("Frontier item requires current evidence before experiment selection")
    home_p = Path(home)
    conn = db.connect(_dbfile(home_p), readonly=True)
    try:
        _require_replayable_decision(conn, item.get("decision_ref"))
        for ref in evidence_refs:
            artifact_hash = artifacts.parse_ref(ref)
            if artifact_hash is None:
                _require_replayable_decision(conn, ref)
            else:
                payload = artifacts.expand(home_p, artifact_hash)
                if hashlib.sha256(payload).hexdigest() != artifact_hash:
                    raise BrainError(f"Artifact evidence identity mismatch: {ref!r}")
    finally:
        conn.close()

    experiments = item.get("experiments", [])

    eligible: list[tuple[float, dict[str, Any]]] = []
    for experiment in experiments:
        if not isinstance(experiment, dict):
            continue
        risk = experiment.get("risk", "low")
        if not isinstance(risk, str) or risk.strip().lower() not in {"low", "medium"}:
            continue
        condition = experiment.get("decision_flip_condition")
        if not isinstance(condition, str) or not condition.strip():
            continue
        gain = experiment.get("expected_information_gain")
        if (
            isinstance(gain, bool)
            or not isinstance(gain, (int, float))
            or not math.isfinite(float(gain))
            or float(gain) <= 0
        ):
            continue
        cost = experiment.get("cost")
        if cost == "local":
            numeric_cost = 0.0
        elif (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost < 0
        ):
            continue
        else:
            numeric_cost = float(cost)
        if experiment.get("executable_locally", cost == "local") is not True:
            continue
        eligible.append((numeric_cost, experiment))

    if not eligible:
        raise BrainError("Frontier item has no eligible discriminating experiment")
    return min(eligible, key=lambda entry: entry[0])[1]
