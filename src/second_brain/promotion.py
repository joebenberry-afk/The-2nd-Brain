"""Policy promotion — shadow -> candidate -> active with ALL guards (plan §119, Phase 23).

Upward adjacent promotion requires: G1 evidence (>= 1 DIRECT or CONTRIBUTORY
credit_event for the skill), G2 a frontier approve review for
``skill-<name>-promotion``, and G3 no immune rollback record for
``skill-<name>``. Skip-level moves, same-level no-ops, level mismatches, and
destination conflicts are refused. Demotion (active -> anything, or via
:func:`demote`) needs no guards but ALWAYS writes a promotion record under
``state/promotions/``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import build_identity, contracts, credit, db, decisions, frontier, immune, paths, skillforge
from .errors import BrainError
from .security.identifiers import validate_skill_name

LEVELS: tuple[str, ...] = ("shadow", "candidate", "active")
LEVEL_RANK = {"shadow": 0, "candidate": 1, "active": 2}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _skills_dir(home: Path) -> Path:
    return Path(home) / "skills"


def _skill_dir(home: Path, level: str) -> Path:
    return Path(home) / paths.SKILL_LEVEL_DIRS[level]


def _promotions_dir(home: Path) -> Path:
    return Path(home) / "state" / "promotions"


def _pending_dir(home: Path) -> Path:
    """Durable intent for publication attempts that are still in flight."""
    return _promotions_dir(home) / "pending"


class _PublicationFailure(BrainError):
    """A publication attempt that could not be completed (never silent)."""

    def __init__(self, reason: str, detail: str, *, rollback_incomplete: bool = False) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.rollback_incomplete = rollback_incomplete


def _level_of(home: Path, skill_name: str) -> str | None:
    for level in LEVELS:
        if (_skill_dir(home, level) / skill_name).is_dir():
            return level
    return None


def _count(home: Path, table: str, column: str, value: str) -> int:
    """Row count for one column equality; a missing table counts as zero."""
    import sqlite3 as _sqlite3

    from . import db

    conn = db.connect(db.db_path(home))
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()
        return int(row["n"])
    except _sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return 0
        raise
    finally:
        conn.close()


def _causal_credit_count(home: Path, skill_name: str) -> int:
    conn = db.connect(db.db_path(home))
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM credit_events "
            "WHERE subject_id = ? AND LOWER(credit_level) IN ('direct', 'contributory')",
            (skill_name,),
        ).fetchone()
        return int(row["n"]) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def _evidence_counts(home: Path, skill_name: str) -> dict:
    return {
        "credit_events": _count(home, "credit_events", "subject_id", skill_name),
        "causal_credit_events": _causal_credit_count(home, skill_name),
        "model_skill_outcomes": _count(home, "model_skill_outcomes", "skill_name", skill_name),
    }


def _frontier_verdict(home: Path, skill_name: str) -> str | None:
    return frontier.frontier_status(home, f"skill-{skill_name}-promotion").get("latest_verdict")


def _frontier_binding_current(home: Path, skill_name: str) -> bool:
    review = frontier.latest_review(home, f"skill-{skill_name}-promotion")
    if review is None or review.get("verdict") != "approve":
        return False
    binding = skillforge.artifact_binding(home, skill_name)
    return all(review.get(key) == value for key, value in binding.items())


def _last_active_version(home: Path, skill_name: str) -> int | None:
    """The version most recently promoted to active for this skill, or
    None if it has never been active. Only active-bound versions constrain
    future promotions; lifecycle moves toward active for a brand-new
    candidate need not bump a version that has no prior release."""
    records = [
        r
        for r in _read_records(home, skill_name)
        if r.get("to_level") == "active" and isinstance(r.get("resulting_version"), int)
    ]
    if not records:
        return None
    records.sort(key=lambda r: r.get("ts", ""))
    return records[-1]["resulting_version"]


AUTHORITY_MARKER = "promotion-authority.json"
# Automatic recovery must never touch a publication that a live caller may still
# be finishing, so only journals older than this are reconciled implicitly.
RECONCILE_GRACE_SECONDS = 120.0
# Journal fields reach filesystem paths; only plain identifiers are accepted.
RECORD_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _authority_marker_path(home: Path, skill_name: str) -> Path | None:
    path = skillforge.skill_path(home, skill_name)
    if path is None:
        return None
    return path.parent / AUTHORITY_MARKER


def _read_authority_marker(home: Path, skill_name: str) -> dict:
    """Authority the artifact carries itself (survives record loss)."""
    path = _authority_marker_path(home, skill_name)
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_authority_marker(
    home: Path, skill_name: str, level: str, version: int | None, promotion_id: str | None
) -> bool:
    """Carry the highest active version with the artifact itself.

    ``state/promotions`` stays the authority; this marker is what lets a
    restore that lost governance records reconstruct the baseline instead of
    treating the skill as a first-ever candidate (audit F-03). It never
    lowers a previously recorded version, and the SKILL.md content hash
    ignores sibling files, so bindings and evaluations stay valid.
    """
    path = _authority_marker_path(home, skill_name)
    if path is None:
        return False
    existing = _read_authority_marker(home, skill_name)
    # Committed records are the authority; the marker is seeded from them so a
    # recovered publication or a demotion reconstructs the version instead of
    # recording "unknown".
    committed = _last_active_version(home, skill_name)
    highest = max(
        [
            value
            for value in (existing.get("last_active_version"), version, committed)
            if isinstance(value, int) and value >= 1
        ],
        default=None,
    )
    payload = {
        "schema_version": 1,
        "skill_name": skill_name,
        "last_level": level,
        "last_active_version": highest,
        "last_promotion_id": (
            promotion_id if promotion_id is not None else existing.get("last_promotion_id")
        ),
        "updated_at": _utcnow(),
    }
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True


def _active_version_baseline(home: Path, skill_name: str) -> tuple[int | None, bool]:
    """(highest active version that can be established, active history exists).

    Committed records are authority; the artifact marker is the conservative
    reconstruction used when a restore dropped the records.
    """
    records = _read_records(home, skill_name)
    recorded = [
        r["resulting_version"]
        for r in records
        if r.get("to_level") == "active" and isinstance(r.get("resulting_version"), int)
    ]
    history_in_records = bool(recorded) or any(r.get("from_level") == "active" for r in records)
    marker = _read_authority_marker(home, skill_name)
    carried = marker.get("last_active_version")
    carried = carried if isinstance(carried, int) and carried >= 1 else None
    if carried is not None:
        return max([*recorded, carried]), True
    if recorded:
        return max(recorded), True
    # A marker that places the artifact at active is itself evidence of a prior
    # release even when its version was never recorded.
    return None, history_in_records or marker.get("last_level") == "active"


def authority_gaps(home: Path) -> list[str]:
    """Skills sitting in skills/active/ with no committed active version.

    Read-only visibility for operators and doctor: an entry here means the
    artifact is published but its promotion authority cannot be reconstructed.
    """
    active_dir = _skill_dir(home, "active")
    if not active_dir.is_dir():
        return []
    gaps = []
    for entry in sorted(active_dir.iterdir()):
        if entry.is_dir() and _last_active_version(home, entry.name) is None:
            gaps.append(entry.name)
    return gaps


def _version_check(home: Path, skill_name: str) -> tuple[bool, str | None, int | None]:
    """§119 version gate: the artifact must carry a valid positive integer
    version, and it must strictly exceed any version this skill previously
    reached active with. Missing history fails closed, never open."""
    binding_artifact = skillforge.artifact_binding(home, skill_name)
    raw = binding_artifact.get("artifact_version", "unversioned")
    if raw == "unversioned":
        return False, "version_missing", None
    try:
        candidate_version = int(raw)
    except (TypeError, ValueError):
        return False, "version_invalid", None
    if candidate_version < 1:
        return False, "version_invalid", None
    previous, had_history = _active_version_baseline(home, skill_name)
    if previous is None:
        if had_history:
            # The skill was active before but no version survived; first-release
            # authority must not be granted silently.
            return False, "history_unavailable", candidate_version
    elif candidate_version <= previous:
        return False, "version_not_incremented", candidate_version
    return True, None, candidate_version


def _guard_checks(home: Path, skill_name: str) -> tuple[dict, dict]:
    evidence = _evidence_counts(home, skill_name)
    has_evidence = _causal_credit_count(home, skill_name) >= 1
    verdict = _frontier_verdict(home, skill_name)
    rolled_back = any(
        record.get("policy_id") == f"skill-{skill_name}" for record in immune.rollback_log(home)
    )
    guards = {
        "evidence": has_evidence,
        "frontier_approved": verdict == "approve",
        "immune_clear": not rolled_back,
        "frontier_binding_current": _frontier_binding_current(home, skill_name),
    }
    details = {
        "evidence_counts": evidence,
        "frontier_verdict": verdict,
        "rolled_back": rolled_back,
        "frontier_binding_current": guards["frontier_binding_current"],
    }
    binding = skillforge.candidate_binding(home, skill_name)
    guards["bound"] = binding is not None
    if binding is not None:
        # §119 baseline-vs-candidate comparison: universal for every bound
        # candidate source (Radar, frontier-evidence, or otherwise), not
        # only Skill-Forge-originated ones.
        candidate_path = skillforge.skill_path(home, skill_name)
        if candidate_path is None:
            raise BrainError(f"No skill {skill_name!r} found under lifecycle directories")
        current_hash = skillforge.lifecycle_content_hash(candidate_path)
        evaluation_path = candidate_path.parent / "evaluation.json"
        try:
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            evaluation = {}
        evaluation_current = (
            binding.get("evaluation_state") == "passed"
            and binding.get("candidate_content_sha256") == current_hash
            and evaluation.get("status") == "passed"
            and evaluation.get("candidate_content_sha256") == current_hash
        )
        guards["evaluation"] = evaluation_current
        details["evaluation_state"] = binding.get("evaluation_state")
        details["evaluation_stale"] = (
            binding.get("evaluation_state") == "passed" and not evaluation_current
        )
        # §119 owner: explicit, bounded, persisted with the binding.
        owner = str(binding.get("owner") or "").strip()
        guards["owner"] = bool(owner)
        details["owner"] = owner or None
        details["candidate_id"] = binding.get("candidate_id")
    version_ok, version_issue, candidate_version = _version_check(home, skill_name)
    guards["version"] = version_ok
    details["version"] = candidate_version
    details["version_issue"] = version_issue
    return guards, details


def _write_record(home: Path, record: dict) -> Path:
    """Write one committed promotion record atomically.

    The name is reserved with an O_EXCL sidecar and the payload lands through a
    temporary file plus rename, so an interruption can never leave a half-written
    ``*.json`` record that would block every later promotion.
    """
    directory = _promotions_dir(home)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BrainError(
            f"Could not open the promotion record directory {directory}: {exc}"
        ) from exc
    counter = 1
    while True:
        target = directory / f"{record['skill_name']}-{counter}.json"
        reserve = target.with_name(target.name + ".reserve")
        if target.exists() or reserve.exists():
            # Never reuse a committed name: promotion history is append-only.
            counter += 1
            continue
        try:
            fd = os.open(reserve, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            counter += 1
        except OSError as exc:
            raise BrainError(f"Could not reserve promotion record {target}: {exc}") from exc
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            reserve.unlink(missing_ok=True)
        raise BrainError(f"Could not write promotion record {target}: {exc}") from exc
    # The record is committed. Failing to remove the reservation sidecar must not
    # turn a committed publication into a reported failure.
    with contextlib.suppress(OSError):
        reserve.unlink(missing_ok=True)
    return target


def _write_pending(home: Path, record: dict) -> Path:
    """Persist the intent before any visibility change (audit F-01)."""
    directory = _pending_dir(home)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BrainError(
            f"Could not open the promotion journal directory {directory}: {exc}"
        ) from exc
    target = directory / f"{record['promotion_id']}.json"
    payload = {
        "schema_version": 1,
        "skill_name": record["skill_name"],
        "from_level": record["from_level"],
        "to_level": record["to_level"],
        "promotion_id": record["promotion_id"],
        "record": record,
    }
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise BrainError(f"Could not journal promotion {record['promotion_id']}: {exc}") from exc
    return target


def _rollback_publication(home: Path, skill_name: str, from_level: str, to_level: str) -> bool:
    """Move a published skill back after a failed record write.

    The move happens first: directory membership is what makes a skill usable,
    so restoring it must not depend on a metadata write. The ``status:`` field is
    repaired afterwards, and reconciliation repairs it again if that fails.

    Returns True when the artifact is back at its original level.
    """
    source = _skill_dir(home, from_level) / skill_name
    target = _skill_dir(home, to_level) / skill_name
    if source.exists() or not target.is_dir():
        return True  # nothing was published, or it is already back
    source.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.rename(source)
    except OSError:
        return False
    skill_file = source / "SKILL.md"
    if skill_file.exists():
        with contextlib.suppress(BrainError):
            skillforge.set_status(skill_file, from_level)
    return True


def _heal_status(home: Path, skill_name: str, level: str | None) -> None:
    """Restore SKILL.md ``status:`` to the level the artifact actually sits in."""
    if level is None:
        return
    path = _skill_dir(home, level) / skill_name / "SKILL.md"
    if not path.is_file():
        return
    with contextlib.suppress(BrainError):
        if skillforge.read_metadata(path).get("status") != level:
            skillforge.set_status(path, level)


def _publish(
    home: Path, skill_name: str, from_level: str, to_level: str, record: dict
) -> tuple[Path, Path, bool, bool]:
    """Move the skill into the target level and commit its record.

    The publication is journaled first, so an interruption between the move
    and the record is recoverable instead of leaving active behavior without
    committed authority. A reported failure rolls the move back when no
    committed record exists for the publication; when one does (a concurrent
    recovery pass committed it), the publication is completed instead. On
    success the artifact also carries its active-version baseline. The last
    element reports that the record was already committed by that recovery.
    """
    try:
        pending = _write_pending(home, record)
    except Exception as exc:
        raise _PublicationFailure("journal_failed", str(exc)) from exc
    try:
        target = _move_skill(home, skill_name, from_level, to_level)
    except Exception as exc:
        pending.unlink(missing_ok=True)
        _heal_status(home, skill_name, from_level)
        reason = "destination_exists" if "already exists" in str(exc) else "move_failed"
        raise _PublicationFailure(reason, str(exc)) from exc
    recovered = False
    try:
        record_path = _write_record(home, record)
    except Exception as exc:
        committed = _committed_record_path(home, skill_name, record.get("promotion_id"))
        if committed is not None:
            # A concurrent recovery pass committed this publication's record
            # while this caller was failing. The artifact is published and the
            # publication is authorized, so the consistent outcome is to finish
            # it: promotion records are append-only, and a caller that reports
            # failure must never delete authority another writer established.
            record_path = committed
            recovered = True
        elif _rollback_publication(home, skill_name, from_level, to_level):
            pending.unlink(missing_ok=True)
            raise _PublicationFailure("record_failed", str(exc)) from exc
        else:
            # The artifact is still published, so it must not stay without
            # authority: retry the record immediately rather than waiting for
            # reconciliation.
            try:
                record_path = _write_record(home, record)
            except Exception as retry_exc:
                raise _PublicationFailure(
                    "record_failed",
                    f"{exc}; committing the record after a failed rollback also "
                    f"failed: {retry_exc}",
                    rollback_incomplete=True,
                ) from exc
    marker_written = _write_authority_marker(
        home,
        skill_name,
        to_level,
        _recovered_active_version(home, skill_name, record) if to_level == "active" else None,
        record.get("promotion_id"),
    )
    pending.unlink(missing_ok=True)
    return target, record_path, marker_written, recovered


def _reconcile_pending(home: Path, *, min_age_seconds: float = 0.0) -> list[dict]:
    """Finish or discard interrupted publication attempts (idempotent).

    - the target level holds the skill and no committed record exists -> commit
      the record and carry its authority marker (the move was journaled first);
    - the skill never reached the target level -> discard the intent and make the
      artifact's own ``status`` match where it actually sits;
    - the record is already committed -> discard the intent.

    Journals younger than ``min_age_seconds`` are reported as ``in_flight`` and
    left alone: a live caller may still be finishing the same publication, and
    committing underneath it would create a record for a publication that then
    rolls back. Journal paths are validated before use — a journal is data, not
    authority, and must never name a path outside the skill tree.
    """
    directory = _pending_dir(home)
    if not directory.is_dir():
        return []
    now = time.time()
    actions: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            age = 0.0
        if age < min_age_seconds:
            actions.append({"pending": path.name, "action": "in_flight"})
            continue
        payload: object
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            actions.append({"pending": path.name, "action": "unreadable"})
            continue
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(record, dict):
            actions.append({"pending": path.name, "action": "unreadable"})
            continue
        skill_name = record.get("skill_name")
        to_level = record.get("to_level")
        promotion_id = record.get("promotion_id")
        if (
            not isinstance(skill_name, str)
            or RECORD_TOKEN_RE.match(skill_name) is None
            or to_level not in LEVELS
            or not isinstance(promotion_id, str)
            or RECORD_TOKEN_RE.match(promotion_id) is None
        ):
            actions.append({"pending": path.name, "action": "invalid"})
            continue
        try:
            validate_skill_name(skill_name)
        except BrainError:
            actions.append({"pending": path.name, "action": "invalid"})
            continue

        current = _level_of(home, skill_name)
        if current == to_level:
            action, remove = _recover_journal(
                home, path, record, skill_name, to_level, promotion_id
            )
            actions.append(action)
            if not remove:
                continue
        else:
            _heal_status(home, skill_name, current)
            actions.append({"pending": path.name, "action": "discarded"})
        path.unlink(missing_ok=True)
    return actions


def _recovered_active_version(home: Path, skill_name: str, record: dict) -> int | None:
    """The version to bind when recovery commits an active publication.

    The artifact's own declared version is preferred over the journal's claim,
    so a forged or stale journal cannot raise the recorded baseline above what
    the published artifact actually is.
    """
    claimed = record.get("resulting_version")
    try:
        declared = skillforge.artifact_binding(home, skill_name).get("artifact_version")
    except BrainError:
        declared = None
    if isinstance(declared, int) and declared >= 1:
        return declared
    if isinstance(declared, str) and declared.isdigit() and int(declared) >= 1:
        return int(declared)
    return claimed if isinstance(claimed, int) and claimed >= 1 else None


def _committed_record_path(home: Path, skill_name: str, promotion_id: object) -> Path | None:
    """The committed record for one publication, if the store already holds it.

    A concurrent recovery pass may commit this caller's publication (it journals
    before it moves, and the journal is the same one); the record store is
    append-only, so a caller that finds the record there must complete the
    publication rather than delete authority another writer established.
    """
    if not isinstance(promotion_id, str) or not promotion_id:
        return None
    directory = _promotions_dir(home)
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob(f"{skill_name}-*.json")):
        record = _record_payload(path)
        if record is not None and record.get("promotion_id") == promotion_id:
            return path
    return None


def _record_payload(path: Path) -> dict | None:
    """The record in one store file, or None when the file is not one.

    Damage handling (quarantine) and history reading share this predicate, and
    both walk every top-level record file: the reader rejects the whole store as
    corrupt when any of them is unreadable, so quarantine must be able to see
    the same file or recovery would be blocked by an unrelated skill's damage.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _quarantine_corrupt_records(home: Path) -> list[str]:
    """Move unreadable committed records aside so recovery can continue.

    The damaged bytes are preserved under ``state/promotions/corrupt/`` for
    inspection, under a fresh name each time so later damage cannot overwrite
    earlier evidence; otherwise the record store is append-only.
    """
    directory = _promotions_dir(home)
    if not directory.is_dir():
        return []
    quarantine = directory / "corrupt"
    moved: list[str] = []
    for path in sorted(directory.glob("*.json")):
        if _record_payload(path) is not None:
            continue
        target = quarantine / path.name
        if target.exists():
            counter = 2
            while (quarantine / f"{path.stem}.{counter}{path.suffix}").exists():
                counter += 1
            target = quarantine / f"{path.stem}.{counter}{path.suffix}"
        try:
            quarantine.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
        except OSError:
            continue
        moved.append(path.name)
    return moved


def _recover_journal(
    home: Path,
    path: Path,
    record: dict,
    skill_name: str,
    to_level: str,
    promotion_id: str,
) -> tuple[dict, bool]:
    """Commit one recovered journal. Returns (action, remove_journal).

    The version recorded for an active publication is taken from the artifact
    itself, and the record is written with that corrected value, so a journal
    cannot raise the recorded baseline above what the artifact actually is.
    """
    try:
        records = _read_records(home, skill_name)
    except BrainError:
        quarantined = _quarantine_corrupt_records(home)
        if not quarantined:
            return {"pending": path.name, "action": "records_unreadable"}, False
        try:
            records = _read_records(home, skill_name)
        except BrainError:
            return {"pending": path.name, "action": "records_unreadable"}, False
        base = {"pending": path.name, "records_quarantined": quarantined}
    else:
        base = {"pending": path.name}

    committed = any(r.get("promotion_id") == promotion_id for r in records)
    version = _recovered_active_version(home, skill_name, record) if to_level == "active" else None
    if not committed:
        recovered = {**record, "resulting_version": version} if to_level == "active" else record
        try:
            _write_record(home, recovered)
        except BrainError:
            return {**base, "action": "commit_failed"}, False
    marker_ok = _write_authority_marker(home, skill_name, to_level, version, promotion_id)
    if not marker_ok:
        # Keep the intent: a later pass retries the marker (and repairs a marker
        # that a previous pass could not write).
        return {**base, "action": "marker_failed"}, False
    return {**base, "action": "already_committed" if committed else "committed"}, True


def reconcile_publications(home: Path, *, min_age_seconds: float = 0.0) -> list[dict]:
    """Finish or discard interrupted publication attempts (idempotent).

    Operator-facing entry point for the same recovery the promotion path runs
    automatically. Unlike the automatic pass it touches journals of any age, so
    an operator can complete a publication that was interrupted seconds ago.
    """
    return _reconcile_pending(home, min_age_seconds=min_age_seconds)


def pending_publications(home: Path) -> list[str]:
    """Unreconciled journal entries (read-only visibility)."""
    directory = _pending_dir(home)
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.glob("*.json"))


def unreadable_publications(home: Path) -> list[str]:
    """Journal entries that cannot be acted on (corrupt or invalid content).

    These are integrity problems, not pending work: recovery cannot tell which
    skill the intent belonged to, so an operator must inspect them.
    """
    directory = _pending_dir(home)
    if not directory.is_dir():
        return []
    bad: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bad.append(path.name)
            continue
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(record, dict):
            bad.append(path.name)
            continue
        skill_name = record.get("skill_name")
        if (
            not isinstance(skill_name, str)
            or RECORD_TOKEN_RE.match(skill_name) is None
            or record.get("to_level") not in LEVELS
            or not isinstance(record.get("promotion_id"), str)
            or RECORD_TOKEN_RE.match(str(record.get("promotion_id"))) is None
        ):
            bad.append(path.name)
    return bad


def _move_skill(home: Path, skill_name: str, from_level: str, to_level: str) -> Path:
    # SEC-03: skill names reach filesystem moves; only validated identifiers.
    skill_name = validate_skill_name(skill_name)
    source = _skill_dir(home, from_level) / skill_name
    target = _skill_dir(home, to_level) / skill_name
    if not source.is_dir():
        raise BrainError(f"No skill {skill_name!r} under skills/{from_level}/")
    if target.exists():
        raise BrainError(f"Destination already exists: {target}")
    skill_file = source / "SKILL.md"
    old_status = skillforge.read_metadata(skill_file).get("status") if skill_file.exists() else None
    if skill_file.exists():
        skillforge.set_status(skill_file, to_level)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)  # atomic within the Brain home
    except OSError as exc:
        # Restore the metadata too: a failed move must not leave the artifact
        # claiming a level it is not in.
        if skill_file.exists() and old_status:
            skillforge.set_status(skill_file, old_status)
        raise BrainError(f"Could not move skill {skill_name!r}: {exc}") from exc
    return target


def _validate_levels(from_level: str, to_level: str) -> None:
    for name, value in (("from_level", from_level), ("to_level", to_level)):
        if value not in LEVELS:
            raise BrainError(f"{name} must be one of {', '.join(LEVELS)}")


def promote(
    home: Path,
    skill_name: str,
    from_level: str,
    to_level: str,
    session_id: str = "",
) -> dict:
    """Promote (or demote) a skill with all guards. Refusals return
    {promoted: False, reason}; never mutates on refusal."""
    skill_name = validate_skill_name(skill_name)
    if not isinstance(session_id, str):
        raise BrainError("session_id must be a string")
    _validate_levels(from_level, to_level)
    _reconcile_pending(home, min_age_seconds=RECONCILE_GRACE_SECONDS)
    actual = _level_of(home, skill_name)
    if actual is None:
        raise BrainError(f"No skill {skill_name!r} found under skills/")
    if actual != from_level:
        return {"promoted": False, "reason": "level_mismatch", "actual_level": actual}
    if to_level == from_level:
        return {"promoted": False, "reason": "already_at_level", "level": from_level}
    if LEVEL_RANK[to_level] > LEVEL_RANK[from_level] + 1:
        return {"promoted": False, "reason": "skip_level"}

    demotion = LEVEL_RANK[to_level] < LEVEL_RANK[from_level]
    guards = None
    details = {
        "evidence_counts": {
            "credit_events": 0,
            "causal_credit_events": 0,
            "model_skill_outcomes": 0,
        },
        "frontier_verdict": None,
        "rolled_back": False,
    }
    if not demotion:
        guards, details = _guard_checks(home, skill_name)
        if guards.get("evaluation") is False:
            reason = (
                "evaluation_stale" if details.get("evaluation_stale") else "evaluation_not_proven"
            )
            return {"promoted": False, "reason": reason, **details}
        if not guards["evidence"]:
            return {"promoted": False, "reason": "no_evidence", **details}
        if not guards["frontier_approved"]:
            return {"promoted": False, "reason": "frontier_not_approved", **details}
        if not guards["frontier_binding_current"]:
            return {"promoted": False, "reason": "frontier_stale", **details}
        if guards["immune_clear"] is False:
            return {"promoted": False, "reason": "rolled_back", **details}
        if not guards["bound"]:
            return {"promoted": False, "reason": "no_promotion_binding", **details}
        if not guards.get("owner", False):
            return {"promoted": False, "reason": "no_owner", **details}
        if not guards["version"]:
            return {
                "promoted": False,
                "reason": details.get("version_issue") or "version_invalid",
                **details,
            }

        if to_level == "active":
            ready = skillforge.validate_execution_ready(
                _skill_dir(home, from_level) / skill_name / "SKILL.md"
            )
            if not ready["ok"]:
                return {
                    "promoted": False,
                    "reason": "execution_not_ready",
                    "validation": ready,
                    **details,
                }

    ts = _utcnow()
    promotion_id = (
        "promotion-" + hashlib.sha256(f"{skill_name}|{ts}|{session_id}".encode()).hexdigest()[:16]
    )
    record = {
        "promotion_id": promotion_id,
        "skill_name": skill_name,
        "from_level": from_level,
        "to_level": to_level,
        "ts": ts,
        "session_id": session_id,
        "guards": guards,
        "frontier_verdict": details["frontier_verdict"],
        "evidence_counts": details["evidence_counts"],
        "owner": details.get("owner"),
        "candidate_id": details.get("candidate_id"),
        "baseline_comparison": details.get("evaluation_state"),
        "rollback_clear": not details.get("rolled_back", False),
        "resulting_version": details.get("version") if not demotion else None,
        "reason": "demoted-via-promote" if demotion else None,
    }
    try:
        target, record_path, marker_written, record_recovered = _publish(
            home, skill_name, from_level, to_level, record
        )
    except _PublicationFailure as exc:
        result: dict[str, Any] = {
            "promoted": False,
            "reason": exc.reason,
            "detail": exc.detail,
        }
        if exc.rollback_incomplete:
            result["rollback"] = "incomplete"
            result["pending_record"] = str(_pending_dir(home))
        return result
    return {
        "promoted": True,
        "from_level": from_level,
        "to_level": to_level,
        "record": record,
        "record_path": str(record_path),
        "target": str(target),
        "authority_marker": "written" if marker_written else "unavailable",
        "record_recovered": record_recovered,
    }


def demote(home: Path, skill_name: str, to_level: str, reason: str) -> dict:
    """Demote a skill to a lower level. No guards, but always records."""
    skill_name = validate_skill_name(skill_name)
    if not isinstance(reason, str) or not reason.strip():
        raise BrainError("reason must be a non-empty string")
    if to_level not in LEVELS:
        raise BrainError(f"to_level must be one of {', '.join(LEVELS)}")
    actual = _level_of(home, skill_name)
    if actual is None:
        raise BrainError(f"No skill {skill_name!r} found under skills/")
    if LEVEL_RANK[to_level] >= LEVEL_RANK[actual]:
        return {"demoted": False, "reason": "not_a_demote", "actual_level": actual}
    _reconcile_pending(home, min_age_seconds=RECONCILE_GRACE_SECONDS)
    ts = _utcnow()
    record = {
        "promotion_id": "demotion-"
        + hashlib.sha256(f"{skill_name}|{actual}|{to_level}|{ts}".encode()).hexdigest()[:16],
        "skill_name": skill_name,
        "from_level": actual,
        "to_level": to_level,
        "ts": ts,
        "session_id": "",
        "guards": None,
        "frontier_verdict": None,
        "evidence_counts": {
            "credit_events": 0,
            "causal_credit_events": 0,
            "model_skill_outcomes": 0,
        },
        "reason": reason,
    }
    try:
        target, record_path, marker_written, record_recovered = _publish(
            home, skill_name, actual, to_level, record
        )
    except _PublicationFailure as exc:
        result: dict[str, Any] = {
            "demoted": False,
            "reason": exc.reason,
            "detail": exc.detail,
        }
        if exc.rollback_incomplete:
            result["rollback"] = "incomplete"
            result["pending_record"] = str(_pending_dir(home))
        return result
    return {
        "demoted": True,
        "from_level": actual,
        "to_level": to_level,
        "record": record,
        "record_path": str(record_path),
        "target": str(target),
        "authority_marker": "written" if marker_written else "unavailable",
        "record_recovered": record_recovered,
    }


def _read_records(home: Path, skill_name: str | None = None) -> list[dict]:
    directory = _promotions_dir(home)
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        record = _record_payload(path)
        if record is None:
            raise BrainError(f"Corrupt promotion record {path}: not a readable JSON object")
        if skill_name is None or record.get("skill_name") == skill_name:
            records.append(record)
    records.sort(key=lambda r: (r.get("ts", ""), r.get("skill_name", "")))
    return records


def promotion_status(home: Path, skill_name: str | None = None) -> dict:
    """Current level per skill + promotion history records.

    Also reports governance visibility (read-only): skills published to
    active without committed authority, and unreconciled publication
    journal entries.
    """
    levels: dict[str, str] = {}
    for level in LEVELS:
        directory = _skill_dir(home, level)
        if directory.is_dir():
            for entry in sorted(directory.iterdir()):
                if entry.is_dir():
                    levels[entry.name] = level
    gaps = authority_gaps(home)
    pending = pending_publications(home)
    if skill_name is not None:
        return {
            "skill_name": skill_name,
            "level": levels.get(skill_name),
            "records": [r for r in _read_records(home, skill_name)],
            "authority_gaps": [name for name in gaps if name == skill_name],
            "pending_publications": pending,
        }
    return {
        "skills": levels,
        "records": _read_records(home),
        "authority_gaps": gaps,
        "pending_publications": pending,
    }


def is_active(home: Path, skill_name: str) -> bool:
    skill_name = validate_skill_name(skill_name)
    return (_skills_dir(home) / "active" / skill_name).is_dir()


ROLLOUT_STAGES: tuple[str, ...] = ("OFF", "SHADOW", "ADVISORY", "CANARY", "ACTIVE")
STAGE_RANKS: dict[str, int] = {
    "OFF": 0,
    "SHADOW": 1,
    "ADVISORY": 2,
    "CANARY": 3,
    "ACTIVE": 4,
}


def _ensure_v2_migrated(home: Path) -> None:
    dbfile = db.db_path(home)
    if db.pending_migrations(dbfile):
        db.migrate(dbfile)


def get_feature_stage(home: Path | str, feature: str) -> str:
    home_p = Path(home)
    _ensure_v2_migrated(home_p)
    conn = db.connect(db.db_path(home_p), readonly=True)
    try:
        row = conn.execute(
            "SELECT to_stage FROM v2_rollout_events WHERE feature = ? "
            "ORDER BY created_at DESC, event_id DESC LIMIT 1",
            (feature,),
        ).fetchone()
        if row is not None:
            return str(row["to_stage"])
    finally:
        conn.close()
    return "OFF"


def _contained_evidence_file(home: Path, ref: object) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    raw = Path(ref)
    if ".." in raw.parts:
        return None
    root = home.resolve()
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _credit_observation(home: Path, feature: str, observation_id: str | None) -> dict[str, Any]:
    if not isinstance(observation_id, str) or not observation_id:
        raise BrainError("Promotion to ACTIVE requires a persisted credit observation")
    conn = db.connect(db.db_path(home), readonly=True)
    try:
        row = conn.execute(
            """SELECT o.*, i.intervention_type, i.target_ref, i.expected_json,
                      i.baseline_ref, i.provenance_hash AS intervention_provenance_hash
               FROM v2_observations AS o
               JOIN v2_interventions AS i ON i.intervention_id = o.intervention_id
               WHERE o.observation_id = ?""",
            (observation_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise BrainError("Promotion credit observation is missing")

    try:
        expected = json.loads(row["expected_json"])
        observed = json.loads(row["observed_json"])
        prediction_error = json.loads(row["prediction_error_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise BrainError("Promotion credit observation is malformed") from exc
    if (
        not isinstance(expected, dict)
        or not isinstance(observed, dict)
        or not isinstance(prediction_error, dict)
    ):
        raise BrainError("Promotion credit observation is malformed")

    intervention = {
        "intervention_type": row["intervention_type"],
        "target_ref": row["target_ref"],
        "baseline_ref": row["baseline_ref"],
    }
    expected_intervention_hash = hashlib.sha256(
        contracts.canonical_json({"intervention": intervention, "expected": expected}).encode(
            "utf-8"
        )
    ).hexdigest()
    if row["intervention_provenance_hash"] != expected_intervention_hash:
        raise BrainError("Promotion credit intervention provenance is tampered")
    if row["target_ref"] != f"policy:{feature}":
        raise BrainError("Promotion credit observation is bound to a different feature")

    expected_observation_hash = hashlib.sha256(
        contracts.canonical_json({"obs": observed, "pred_err": prediction_error}).encode("utf-8")
    ).hexdigest()
    if row["provenance_hash"] != expected_observation_hash:
        raise BrainError("Promotion credit observation provenance is tampered")

    credit_evidence = observed.get("_credit_evidence")
    if not isinstance(credit_evidence, dict):
        raise BrainError("Promotion credit has no authenticated normalized evidence")
    derived_credit = str(credit.classify_credit(credit_evidence))
    if row["credit_class"] != derived_credit:
        raise BrainError("Promotion credit class is tampered")
    return {
        **dict(row),
        "observed": observed,
        "derived_credit_class": derived_credit,
    }


def _require_eligible_credit_evidence(
    home: Path, feature: str, observation: dict[str, Any]
) -> dict[str, Any]:
    metadata = observation["observed"].get("_evidence")
    if not isinstance(metadata, dict):
        raise BrainError("Promotion credit evidence has no independently resolvable provenance")
    if (
        metadata.get("classification") != "observed"
        or metadata.get("qualification_eligible") is not True
    ):
        raise BrainError("Simulated or unresolved credit evidence cannot authorize promotion")
    if (
        metadata.get("feature") != feature
        or metadata.get("target_ref") != observation["target_ref"]
        or not isinstance(metadata.get("source_commit"), str)
        or not isinstance(metadata.get("source_tree_sha256"), str)
        or not isinstance(metadata.get("config_sha256"), str)
    ):
        raise BrainError("Promotion credit evidence is bound to different production inputs")
    path = _contained_evidence_file(home, metadata.get("path"))
    expected_hash = metadata.get("sha256")
    if path is None or not path.is_file() or not isinstance(expected_hash, str):
        raise BrainError("Promotion credit evidence is unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise BrainError("Promotion credit evidence is stale or tampered")
    return metadata


def _qualification_process(
    home: Path, path: Path, records_path: Path | None = None
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    repo = Path(__file__).resolve().parents[2]
    verifier = repo / "scripts" / "verify_qualification.py"
    command = [
        sys.executable,
        str(verifier),
        "--home",
        str(home),
        "--manifest",
        str(path),
        "--json",
    ]
    if records_path is not None:
        command.extend(["--records", str(records_path)])
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    try:
        process = subprocess.run(
            command,
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrainError(f"Independent qualification verifier could not run: {exc}") from exc
    try:
        report = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise BrainError(
            "Independent qualification verifier produced no valid process artifact"
        ) from exc
    if not isinstance(report, dict):
        raise BrainError("Independent qualification verifier report must be an object")
    return process, report


def _run_independent_qualification(
    home: Path,
    manifest_ref: str | Path | None,
    credit_evidence: dict[str, Any],
) -> dict[str, Any]:
    path = _contained_evidence_file(home, str(manifest_ref) if manifest_ref is not None else None)
    if path is None or not path.is_file():
        raise BrainError("Promotion to ACTIVE requires a contained qualification manifest")
    repo = Path(__file__).resolve().parents[2]
    verifier = repo / "scripts" / "verify_qualification.py"
    verifier_hash = hashlib.sha256(verifier.read_bytes()).hexdigest()
    manifest_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    process, report = _qualification_process(home, path)

    expected_manifest_path = str(path.resolve())
    expected_binding = {
        key: credit_evidence[key]
        for key in (
            "path",
            "sha256",
            "feature",
            "source_commit",
            "source_tree_sha256",
            "config_sha256",
        )
    }
    validated_bindings = report.get("validated_evidence_bindings")
    if (
        process.returncode != 0
        or report.get("ok") is not True
        or report.get("qualification_status") != "QUALIFIED"
        or report.get("records_path") is not None
        or report.get("verifier") != "scripts/verify_qualification.py"
        or report.get("verifier_sha256") != verifier_hash
        or report.get("manifest_path") != expected_manifest_path
        or report.get("manifest_sha256") != manifest_hash
        or report.get("source_commit") != credit_evidence["source_commit"]
        or report.get("source_tree_sha256") != credit_evidence["source_tree_sha256"]
        or report.get("config_sha256") != credit_evidence["config_sha256"]
        or not isinstance(report.get("scope"), list)
        or not report["scope"]
        or not isinstance(validated_bindings, list)
        or expected_binding not in validated_bindings
    ):
        raise BrainError(
            "Independent qualification verifier did not pass the exact credit evidence binding"
        )
    return {
        "exit_code": process.returncode,
        "artifact_sha256": hashlib.sha256(process.stdout.encode("utf-8")).hexdigest(),
        "verifier": report["verifier"],
        "verifier_sha256": verifier_hash,
        "source_commit": report["source_commit"],
        "source_tree_sha256": report["source_tree_sha256"],
        "config_sha256": report["config_sha256"],
        "scope": report["scope"],
        "validated_evidence_binding": expected_binding,
        "manifest_path": expected_manifest_path,
        "manifest_sha256": manifest_hash,
    }


def record_qualification(
    home: Path | str, manifest_ref: str | Path, records_ref: str | Path
) -> dict[str, Any]:
    """Atomically record independently accepted complete rows; never authorize ACTIVE.

    Both inputs must be existing files contained in home. Exact repeats are
    idempotent; any different existing ledger refuses the entire operation.
    """
    home = Path(home).resolve()
    manifest_path = _contained_evidence_file(home, str(manifest_ref))
    records_path = _contained_evidence_file(home, str(records_ref))
    if (
        manifest_path is None
        or not manifest_path.is_file()
        or records_path is None
        or not records_path.is_file()
    ):
        raise BrainError("Recording requires contained manifest and records files")
    repo = Path(__file__).resolve().parents[2]
    verifier = repo / "scripts" / "verify_qualification.py"
    columns = (
        "qualification_id",
        "phase",
        "requirement",
        "status",
        "evidence_json",
        "source_commit",
        "artifact_hash",
        "created_at",
    )
    try:
        manifest_bytes = manifest_path.read_bytes()
        records_bytes = records_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        records = json.loads(records_bytes)
        if not isinstance(manifest, dict) or not isinstance(records, list) or not records:
            raise ValueError("manifest object and complete records list required")
        if any(
            not isinstance(row, dict)
            or set(row) != set(columns)
            or any(not isinstance(value, str) or not value for value in row.values())
            for row in records
        ):
            raise ValueError("complete string-valued qualification rows required")
        if len({row["qualification_id"] for row in records}) != len(records):
            raise ValueError("duplicate qualification_id")

        # Snapshot all referenced files, including artifacts' raw provenance.
        # Keep lexical paths so replacement of a symlink is detected as well.
        files: dict[Path, tuple[Path, str]] = {}

        def snapshot(path: Path) -> None:
            resolved = path.resolve()
            resolved.relative_to(home)
            payload = path.read_bytes()
            binding = (resolved, hashlib.sha256(payload).hexdigest())
            if path in files:
                if files[path] != binding:
                    raise ValueError("evidence changed while collecting bindings")
                return
            files[path] = binding
            try:
                value = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return
            visit(value)

        def visit(value: object) -> None:
            if isinstance(value, dict):
                if isinstance(value.get("path"), str) and "sha256" in value:
                    ref = Path(value["path"])
                    if ref.is_absolute() or ".." in ref.parts:
                        raise ValueError("evidence references must be contained relative paths")
                    snapshot(home / ref)
                for key, item in value.items():
                    if key == "evidence_json" and isinstance(item, str):
                        visit(json.loads(item))
                    else:
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        source_commit = build_identity.git_sha(repo)
        snapshot(manifest_path)
        snapshot(records_path)
        authority_ref = manifest.get("authority")
        if not isinstance(authority_ref, str):
            raise ValueError("manifest authority required")
        authority_path = (repo / authority_ref).resolve()
        authority_path.relative_to(repo.resolve())
        authority_hash = hashlib.sha256(authority_path.read_bytes()).hexdigest()
        verifier_hash = hashlib.sha256(verifier.read_bytes()).hexdigest()
        source_hash = build_identity.source_tree_fingerprint(repo)
        config_hash = build_identity.configuration_fingerprint(home)
        if not source_commit or not source_hash or not config_hash:
            raise ValueError("current source/config bindings unavailable")

        def stable() -> bool:
            return (
                _contained_evidence_file(home, str(manifest_ref)) == manifest_path
                and _contained_evidence_file(home, str(records_ref)) == records_path
                and manifest_path.read_bytes() == manifest_bytes
                and records_path.read_bytes() == records_bytes
                and hashlib.sha256(verifier.read_bytes()).hexdigest() == verifier_hash
                and (repo / authority_ref).resolve() == authority_path
                and hashlib.sha256(authority_path.read_bytes()).hexdigest() == authority_hash
                and build_identity.git_sha(repo) == source_commit
                and build_identity.source_tree_fingerprint(repo) == source_hash
                and build_identity.configuration_fingerprint(home) == config_hash
                and all(
                    path.resolve() == resolved
                    and hashlib.sha256(path.read_bytes()).hexdigest() == digest
                    for path, (resolved, digest) in files.items()
                )
            )

        def accept_candidate() -> dict[str, Any]:
            process, report = _qualification_process(home, manifest_path, records_path)
            if (
                process.returncode != 0
                or report.get("ok") is not True
                or report.get("qualification_status") != "READY_TO_RECORD"
                or report.get("verifier") != "scripts/verify_qualification.py"
                or report.get("verifier_sha256") != verifier_hash
                or report.get("manifest_path") != str(manifest_path)
                or report.get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest()
                or report.get("records_path") != str(records_path)
                or report.get("records_sha256") != hashlib.sha256(records_bytes).hexdigest()
                or report.get("records_content_sha256")
                != hashlib.sha256(contracts.canonical_json(records).encode("utf-8")).hexdigest()
                or report.get("manifest_content_sha256")
                != hashlib.sha256(contracts.canonical_json(manifest).encode("utf-8")).hexdigest()
                or report.get("source_commit") != manifest.get("source_commit")
                or report.get("current_source_commit") != source_commit
                or report.get("source_tree_sha256") != source_hash
                or report.get("config_sha256") != config_hash
                or report.get("validated_evidence_bindings") != []
            ):
                raise BrainError("Independent candidate qualification was not accepted")
            return report

        # Reject independently before opening any writable connection. Repeat
        # under a write reservation so causal observations cannot change.
        accept_candidate()
        if not stable():
            raise BrainError("Qualification files or bindings changed before recording")
        if not db.db_path(home).is_file():
            raise ValueError("existing migrated database required")
        conn = db.connect(db.db_path(home))
        try:
            conn.execute("BEGIN IMMEDIATE")
            report = accept_candidate()
            existing = [
                dict(row)
                for row in conn.execute(
                    f"SELECT {', '.join(columns)} FROM v2_qualification"
                ).fetchall()
            ]
            by_id = {row["qualification_id"]: row for row in records}
            if any(by_id.get(row["qualification_id"]) != row for row in existing):
                raise BrainError("Conflicting existing qualification records; refusing overwrite")
            existing_ids = {row["qualification_id"] for row in existing}
            additions = [row for row in records if row["qualification_id"] not in existing_ids]
            conn.executemany(
                f"INSERT INTO v2_qualification ({', '.join(columns)}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [tuple(row[column] for column in columns) for row in additions],
            )
            if not stable():
                raise BrainError("Qualification files or bindings changed before commit")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise BrainError(f"Qualification recording refused: {exc}") from exc
    return {
        "status": "RECORDED",
        "inserted": len(additions),
        "record_count": len(records),
        "manifest_sha256": report["manifest_sha256"],
        "records_sha256": report["records_sha256"],
    }


def transition_rollout_stage(
    home: Path | str,
    feature: str,
    to_stage: str,
    *,
    reason: str,
    evidence_refs: list[str] | None = None,
    actor: str = "system",
    credit_observation_id: str | None = None,
    qualification_manifest: str | Path | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Transition a feature's rollout stage with strict invariant enforcement.

    Rule 1: Stages must progress adjacent: OFF -> SHADOW -> ADVISORY -> CANARY -> ACTIVE.
            Skipping stages (e.g. SHADOW -> ACTIVE) is strictly forbidden.
    Rule 2: Promotion to ACTIVE independently resolves persisted causal credit
            and runs the canonical qualification verifier against a bound manifest.
    Rule 3: Negative or regressed evidence refuses promotion and holds or demotes the candidate.
    Rule 4: Demotion and rollback write full audit records and preserve all history.
    """
    home_p = Path(home)
    _ensure_v2_migrated(home_p)

    target_stage = str(to_stage).strip().upper()
    if target_stage not in STAGE_RANKS:
        raise BrainError(f"Invalid rollout stage {to_stage!r}")

    current_stage = get_feature_stage(home_p, feature)
    current_rank = STAGE_RANKS[current_stage]
    target_rank = STAGE_RANKS[target_stage]

    credit_class: str | None = None
    verifier_process: dict[str, Any] | None = None
    observation: dict[str, Any] | None = None

    # Check for skip-stage attempts before resolving promotion evidence.
    if target_rank > current_rank and target_rank > current_rank + 1:
        raise BrainError(
            f"Cannot skip rollout stages: attempted {current_stage} -> {target_stage}. "
            "Must advance sequentially (OFF -> SHADOW -> ADVISORY -> CANARY -> ACTIVE)."
        )

    if target_rank > current_rank and target_stage == "ACTIVE":
        observation = _credit_observation(home_p, feature, credit_observation_id)
        credit_class = str(observation["derived_credit_class"])

        # Negative evidence may safely refuse promotion even when it is simulated;
        # positive evidence must meet the stronger production eligibility boundary.
        if credit_class == "UNRELATED_NEGATIVE":
            demote_target = "SHADOW" if current_stage in ("CANARY", "ADVISORY") else "OFF"
            event_id = (
                "event-"
                + hashlib.sha256(
                    f"{feature}:{current_stage}:{demote_target}:{_utcnow()}".encode()
                ).hexdigest()[:24]
            )
            evidence_list = [
                *(evidence_refs or ()),
                f"observation:{credit_observation_id}",
                "credit:UNRELATED_NEGATIVE",
            ]
            now = _utcnow()

            conn = db.connect(db.db_path(home_p))
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """INSERT INTO v2_rollout_events(
                        event_id, feature, from_stage, to_stage, reason,
                        evidence_refs_json, actor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id,
                        feature,
                        current_stage,
                        demote_target,
                        f"PROMOTION_REFUSED_NEGATIVE_EFFECT: {reason}",
                        contracts.canonical_json(evidence_list),
                        actor,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            decisions.record(
                home_p,
                kind="learning",
                session_id=session_id or f"rollout-{event_id}",
                task_id=task_id or f"task-{event_id}",
                chosen={
                    "action": "demote_feature",
                    "feature": feature,
                    "from_stage": current_stage,
                    "to_stage": demote_target,
                },
                alternatives=[{"action": "promote"}],
                propensity=1.0,
                randomized=False,
                policy_version="v7.9",
                stage=demote_target,
                inputs={
                    "feature": feature,
                    "credit_observation_id": credit_observation_id,
                    "credit_class": credit_class,
                    "reason": reason,
                },
            )

            return {
                "event_id": event_id,
                "feature": feature,
                "from_stage": current_stage,
                "to_stage": demote_target,
                "status": "HELD",
                "promotion_refused": True,
                "reason": (
                    "Promotion refused due to negative effect; "
                    f"candidate demoted to {demote_target}"
                ),
                "evidence_refs": evidence_list,
                "created_at": now,
            }

        if credit_class not in ("DIRECT", "CONTRIBUTORY"):
            raise BrainError(
                "Promotion to ACTIVE requires independently resolved causal credit "
                f"DIRECT or CONTRIBUTORY (got {credit_class!r})"
            )
        credit_evidence = _require_eligible_credit_evidence(home_p, feature, observation)
        verifier_process = _run_independent_qualification(
            home_p, qualification_manifest, credit_evidence
        )
    now = _utcnow()
    event_id = (
        "event-"
        + hashlib.sha256(f"{feature}:{current_stage}:{target_stage}:{now}".encode()).hexdigest()[
            :24
        ]
    )
    evidence_list = list(evidence_refs or [])
    if observation is not None:
        evidence_list.append(f"observation:{credit_observation_id}")
    if verifier_process is not None:
        evidence_list.append(f"verifier-result:sha256:{verifier_process['artifact_sha256']}")

    conn = db.connect(db.db_path(home_p))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO v2_rollout_events(
                event_id, feature, from_stage, to_stage, reason,
                evidence_refs_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                feature,
                current_stage,
                target_stage,
                reason,
                contracts.canonical_json(evidence_list),
                actor,
                now,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record rollout event: {exc}") from exc
    finally:
        conn.close()

    decisions.record(
        home_p,
        kind="learning",
        session_id=session_id or f"rollout-{event_id}",
        task_id=task_id or f"task-{event_id}",
        chosen={
            "action": "transition_stage",
            "feature": feature,
            "from_stage": current_stage,
            "to_stage": target_stage,
        },
        alternatives=[],
        propensity=1.0,
        randomized=False,
        policy_version="v7.9",
        stage=target_stage,
        inputs={
            "feature": feature,
            "credit_observation_id": credit_observation_id,
            "credit_class": credit_class,
            "verifier_process": verifier_process,
            "reason": reason,
        },
    )

    return {
        "event_id": event_id,
        "feature": feature,
        "from_stage": current_stage,
        "to_stage": target_stage,
        "status": "PROMOTED"
        if target_rank > current_rank
        else ("DEMOTED" if target_rank < current_rank else "MAINTAINED"),
        "promotion_refused": False,
        "reason": reason,
        "evidence_refs": evidence_list,
        "created_at": now,
    }


def list_rollout_events(home: Path | str, feature: str | None = None) -> list[dict[str, Any]]:
    home_p = Path(home)
    _ensure_v2_migrated(home_p)
    conn = db.connect(db.db_path(home_p), readonly=True)
    try:
        sql = "SELECT * FROM v2_rollout_events WHERE 1=1"
        params: list[Any] = []
        if feature is not None:
            sql += " AND feature = ?"
            params.append(feature)
        sql += " ORDER BY created_at ASC, event_id ASC"
        rows = conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["evidence_refs"] = json.loads(d["evidence_refs_json"])
            results.append(d)
        return results
    finally:
        conn.close()
