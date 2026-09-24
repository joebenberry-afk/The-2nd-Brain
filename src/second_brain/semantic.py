"""Semantic memory cortex (plan §13/§47-49, Phase 10 §106).

Manual curation first. A memory is an immutable-per-version markdown file under
``memory/semantic/`` (frontmatter + body) plus rows in the ``memories``,
``memory_sources`` and ``memory_versions`` tables.

Evidence grades are strictly ordered (INFERRED < OBSERVED < TESTED < VERIFIED)
and only move one step up per curation; REJECTED is reachable from anywhere and
HISTORICAL only as a downgrade. The grade is never changed silently — curate is
the only mutation path, and show_memory always surfaces the stored grade.

VERIFIED is authority rather than a label (it drives retrieval trust, admission
confidence, promotion and protected-memory treatment), so it is the one grade a
caller cannot claim: add_memory and curate refuse it with
``VERIFIED_REQUIRES_ATTESTATION`` unless an independent attestation vouches for
it (SEC-AUTH-02). No issuer ships in this build, so that path is unavailable by
design rather than faked; unprivileged grades are unaffected.

Superseding writes a new versioned file (``<id>__v<N>.md`` for N>=2) and keeps
every previous file, so history is preserved.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from dataclasses import field as _field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from . import db, decisions
from .contracts import canonical_json, estimate_tokens
from .errors import BrainError
from .v2_policy import RolloutStage, load_policy

_LOG = logging.getLogger("second_brain.semantic")

GRADES: tuple[str, ...] = ("OBSERVED", "TESTED", "VERIFIED", "INFERRED", "HISTORICAL", "REJECTED")
STATUSES: tuple[str, ...] = ("candidate", "current", "labile", "superseded", "archived")
SCOPES: tuple[str, ...] = ("project", "domain", "global")
SOURCE_KINDS: tuple[str, ...] = ("evidence", "episode", "test", "decision", "import")
ORIGIN_CLASSES: tuple[str, ...] = (
    "USER_AUTHORED",
    "LOCAL_REPO",
    "TRUSTED_TEST",
    "TOOL_OBSERVATION",
    "EXTERNAL_WEB",
    "MODEL_INFERENCE",
    "IMPORTED_FOREIGN",
)
AUTHORITY_CEILINGS: tuple[str, ...] = ("advisory", "project_rule", "policy")
_AUTHORITY_RANK = {"advisory": 0, "project_rule": 1, "policy": 2}
_PROJECT_RULE_ORIGINS = frozenset({"USER_AUTHORED", "LOCAL_REPO", "TRUSTED_TEST"})

# ---------------------------------------------------------------------------
# SEC-AUTH-02 (fail closed): requested grade != effective grade.
#
# VERIFIED is authority, not a label: it drives retrieval trust, admission
# confidence, promotion and protected-memory treatment. A caller-supplied
# `--grade VERIFIED` (or a curate request) is therefore a REQUEST only, and is
# refused unless an independent attestation vouches for it. The issuer registry
# is empty by construction in this build (no signer, no host-held token) and is
# deliberately NOT selectable through an environment variable, repo/Brain-home
# config, model setting or CLI flag, so the positive path is unavailable rather
# than faked. Unprivileged grades are unaffected.
# ---------------------------------------------------------------------------
VERIFIED_REQUIRES_ATTESTATION = "VERIFIED_REQUIRES_ATTESTATION"
VERIFIED_ATTESTATION_ISSUERS: dict[str, Callable[[dict], bool]] = {}


def verified_attested(attestation: dict | None) -> bool:
    """True only for an attestation vouched for by a registered independent issuer.

    Malformed, unregistered or raising attestations are False: the default is
    always "no authority".
    """
    if not isinstance(attestation, dict):
        return False
    issuer = attestation.get("issuer")
    validator = VERIFIED_ATTESTATION_ISSUERS.get(issuer) if isinstance(issuer, str) else None
    if validator is None:
        return False
    try:
        return bool(validator(attestation))
    except Exception:
        return False


def _require_verified_attestation(grade: str, attestation: dict | None, *, operation: str) -> None:
    """Fail closed on an unattested VERIFIED grade claim; never downgrade silently."""
    if grade != "VERIFIED" or verified_attested(attestation):
        return
    raise BrainError(
        f"{VERIFIED_REQUIRES_ATTESTATION}: {operation} cannot write grade VERIFIED from a "
        "caller-supplied claim; an independent attestation from a registered issuer is "
        "required and none is available"
    )


# ---------------------------------------------------------------------------
# SEC-AUTH-02 producer guard (fail closed): the authority ceiling is not
# caller-mintable either.
#
# `origin_class` (USER_AUTHORED / LOCAL_REPO / TRUSTED_TEST), `origin_root_sha`
# and the stored `authority_ceiling` are all supplied by the caller that wants
# the authority, so they are self-description, not evidence: nothing a producer
# can reach raises a memory above `advisory` by reporting its own
# trustworthiness. Elevation is effective only with an attestation from an
# issuer the caller cannot act as. That registry is empty by construction in
# this build (no signer, no host-held token) and is deliberately NOT selectable
# through an environment variable, repo/Brain-home config, model setting or CLI
# flag, so the positive path is unavailable rather than faked: `_validate_origin`
# always writes `advisory`, and `effective_authority_ceiling` always resolves to
# `advisory`. Authority consumers MUST read the ceiling through that helper, not
# the raw column -- a legacy row, an edited database or an imported backup can
# carry an elevated value that no issuer granted.
# ---------------------------------------------------------------------------
AUTHORITY_ATTESTATION_ISSUERS: dict[str, Callable[[dict], bool]] = {}


def authority_attested(attestation: dict | None) -> bool:
    """True only for an attestation vouched for by a registered independent issuer.

    Malformed, unregistered or raising attestations are False: the default is
    always "no authority".
    """
    if not isinstance(attestation, dict):
        return False
    issuer = attestation.get("issuer")
    validator = AUTHORITY_ATTESTATION_ISSUERS.get(issuer) if isinstance(issuer, str) else None
    if validator is None:
        return False
    try:
        return bool(validator(attestation))
    except Exception:
        return False


def effective_authority_ceiling(row: dict) -> str:
    """The authority a stored memory actually holds, whatever the row claims.

    A stored ceiling above `advisory` is effective only when the row carries an
    attestation from a registered independent issuer, and no writer in this build
    can produce one, so every row resolves to `advisory`. Policy-lane admission
    and retrieval-holdout eligibility MUST read this instead of the raw column.
    """
    claimed = row.get("authority_ceiling")
    if not isinstance(claimed, str) or _AUTHORITY_RANK.get(claimed, 0) <= 0:
        return "advisory"
    return claimed if authority_attested(row.get("authority_attestation")) else "advisory"

def effective_evidence_grade(row: dict) -> str:
    """Grade that may affect trust. Stored VERIFIED is a claim unless attested."""
    grade = str(row.get("evidence_grade") or "")
    if grade != "VERIFIED" or verified_attested(row.get("grade_attestation")):
        return grade
    return "TESTED"


class CandidateTrigger(StrEnum):
    """Evidence-only reasons that can open the earned-memory gate."""

    CORRECTION = "CORRECTION"
    REGRESSION = "REGRESSION"
    REPETITION = "REPETITION"
    SUBTLETY = "SUBTLETY"
    SEVERITY = "SEVERITY"
    INDEPENDENT_EVIDENCE = "INDEPENDENT_EVIDENCE"
    CROSS_SESSION_REUSE = "CROSS_SESSION_REUSE"


CANDIDATE_TRIGGERS: tuple[str, ...] = tuple(item.value for item in CandidateTrigger)
_CORRECTION_EVENTS = frozenset(
    {
        "result_correction_requested",
        "result_corrected",
        "hermes_worker_result_correction_requested",
        "hermes_worker_result_corrected",
    }
)
_FAILURE_EVENTS = frozenset(
    {"task_failed", "worker_failed", "test_observed", "model_invocation_failed"}
)
_SHA_FIELDS = (
    "record_hash",
    "evidence_hash",
    "correction_sha256",
    "original_result_sha256",
    "result_sha256",
    "artifact_sha256",
)
_CANDIDATE_EVENT_LIMIT = 16
_CANDIDATE_REF_LIMIT = 256


def _admission_stage(home: Path) -> RolloutStage:
    """Only an absent legacy policy may default to SHADOW."""
    try:
        (home / "config" / "v2.toml").lstat()
    except FileNotFoundError:
        return RolloutStage.SHADOW
    return load_policy(home).rollout["admission"]


_EARNED_MEMORY_POLICY_VERSION = "earned-memory-v1"

# Rank for upgrade/downgrade decisions; HISTORICAL/REJECTED sit below everything.
_GRADE_RANK = {
    "INFERRED": 0,
    "OBSERVED": 1,
    "TESTED": 2,
    "VERIFIED": 3,
    "HISTORICAL": -1,
    "REJECTED": -2,
}
_UPGRADE_CHAIN = ("INFERRED", "OBSERVED", "TESTED", "VERIFIED")

FRONTMATTER_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "scope",
    "project",
    "status",
    "grade",
    "version",
    "created_at",
)
DEFAULT_STRENGTH = 0.5
DEFAULT_STABILITY = 0.5
ID_RETRIES = 5


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _semantic_dir(home: Path) -> Path:
    return Path(home) / "memory" / "semantic"


def _v1_path(home: Path, memory_id: str) -> Path:
    return _semantic_dir(home) / f"{memory_id}.md"


def _version_path(home: Path, memory_id: str, version: int) -> Path:
    if version <= 1:
        return _v1_path(home, memory_id)
    return _semantic_dir(home) / f"{memory_id}__v{version}.md"


def _dbfile(home: Path) -> Path:
    return db.db_path(home)


def _ensure_migrated(home: Path) -> None:
    db.ensure_migrated(_dbfile(home))


def _version_created_at(home: Path, memory_id: str, version: int, fallback: str) -> str:
    """Original created_at of a version being retired (v1 = row's created_at)."""
    if version <= 1:
        return fallback
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute(
            "SELECT created_at FROM memory_versions WHERE memory_id = ? AND version = ?",
            (memory_id, version),
        ).fetchone()
        return row["created_at"] if row is not None else fallback
    finally:
        conn.close()


def capture_evidence(repo_root: Path | str, specification: str) -> dict:
    """Capture a bounded path/range fingerprint from a local git repository."""
    if not isinstance(specification, str) or not specification.strip():
        raise BrainError("evidence must be a non-empty path[:start-end]")
    repo = Path(repo_root).resolve()
    match = re.fullmatch(r"(.+?)(?::([0-9]+)-([0-9]+))?", specification.strip())
    if match is None:
        raise BrainError("evidence must be a path[:start-end]")
    raw_path, raw_start, raw_end = match.groups()
    candidate = Path(raw_path)
    try:
        target = (candidate if candidate.is_absolute() else repo / candidate).resolve()
        rel = target.relative_to(repo).as_posix()
    except (OSError, ValueError) as exc:
        raise BrainError("evidence path must be inside the repository") from exc
    if not target.is_file() or not rel:
        raise BrainError("evidence path does not exist")
    start = int(raw_start) if raw_start is not None else None
    end = int(raw_end) if raw_end is not None else None
    if start is not None and (start < 1 or end is None or start > end):
        raise BrainError("evidence range must be positive start-end")
    try:
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError) as exc:
        raise BrainError("evidence path is not readable UTF-8") from exc
    if end is not None and end > len(lines):
        raise BrainError("evidence range exceeds file line count")

    def git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True, timeout=5
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise BrainError("evidence git capture failed") from exc
        return result.stdout.strip()

    root_text = git("rev-parse", "--show-toplevel")
    root_path = Path(root_text).resolve()
    # Subsequent git calls must run from the repository root because ``rel``
    # is rooted there even when capture started in a nested cwd.
    repo = root_path
    # Recompute relative path if caller supplied a subdirectory as repo_root.
    try:
        rel = target.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise BrainError("evidence path is outside git repository") from exc
    selected = lines[(start or 1) - 1 : end if end is not None else len(lines)]
    try:
        origin_root_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise BrainError("evidence path is not readable") from exc
    return {
        "ref": rel,
        "kind": "evidence",
        "repo_id": str(root_path),
        "path": rel,
        "symbol": None,
        "commit_sha": git("rev-parse", "HEAD"),
        "blob_sha": git("hash-object", "--", rel),
        "range_start": start,
        "range_end": end,
        "range_sha": hashlib.sha256("".join(selected).encode("utf-8")).hexdigest()
        if start is not None
        else None,
        "verified_at": _utcnow(),
        "origin_root_sha": origin_root_sha,
    }


def _row(home: Path, memory_id: str) -> dict | None:
    conn = db.connect(_dbfile(home))
    try:
        row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _sources(home: Path, memory_id: str) -> list[dict]:
    conn = db.connect(_dbfile(home))
    try:
        rows = conn.execute(
            "SELECT source_ref, source_kind, added_at, repo_id, path, symbol, commit_sha, "
            "blob_sha, range_start, range_end, range_sha, verified_at FROM memory_sources "
            "WHERE memory_id = ? ORDER BY id",
            (memory_id,),
        ).fetchall()
        return [
            {
                "ref": r["source_ref"],
                "kind": r["source_kind"],
                "added_at": r["added_at"],
                "repo_id": r["repo_id"],
                "path": r["path"],
                "symbol": r["symbol"],
                "commit_sha": r["commit_sha"],
                "blob_sha": r["blob_sha"],
                "range_start": r["range_start"],
                "range_end": r["range_end"],
                "range_sha": r["range_sha"],
                "verified_at": r["verified_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


_SOURCE_METADATA = (
    "repo_id",
    "path",
    "symbol",
    "commit_sha",
    "blob_sha",
    "range_start",
    "range_end",
    "range_sha",
    "verified_at",
)


def _insert_sources(
    conn: sqlite3.Connection, memory_id: str, sources: list[dict], now: str
) -> None:
    for source in sources:
        conn.execute(
            "INSERT INTO memory_sources "
            "(memory_id, source_ref, source_kind, added_at, repo_id, path, symbol, commit_sha, "
            "blob_sha, range_start, range_end, range_sha, verified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                source["ref"],
                source["kind"],
                now,
                *(source.get(key) for key in _SOURCE_METADATA),
            ),
        )


def _validate_sources(sources: list[dict] | None) -> list[dict]:
    if sources is None:
        return []
    if not isinstance(sources, list):
        raise BrainError("sources must be a list of {ref, kind} dicts or None")
    out = []
    for source in sources:
        if not isinstance(source, dict):
            raise BrainError("sources must be a list of {ref, kind} dicts or None")
        ref = source.get("ref")
        kind = source.get("kind", "evidence")
        if not isinstance(ref, str) or not ref.strip():
            raise BrainError(f"source ref must be a non-empty string: {source!r}")
        if kind not in SOURCE_KINDS:
            raise BrainError(f"source kind must be one of {', '.join(SOURCE_KINDS)}")
        clean = {"ref": ref.strip(), "kind": kind}
        for key in _SOURCE_METADATA:
            if key in source:
                clean[key] = source[key]
        start, end = clean.get("range_start"), clean.get("range_end")
        if start is not None and (
            isinstance(start, bool) or not isinstance(start, int) or start < 1
        ):
            raise BrainError("source range_start must be a positive integer or None")
        if end is not None and (isinstance(end, bool) or not isinstance(end, int) or end < 1):
            raise BrainError("source range_end must be a positive integer or None")
        if start is not None and end is not None and start > end:
            raise BrainError("source range_start must not exceed range_end")
        out.append(clean)
    return out


def _validate_origin(
    origin_class: str, origin_root_sha: str | None, attestation: dict | None = None
) -> tuple[str, str | None, str]:
    if origin_class not in ORIGIN_CLASSES:
        raise BrainError(f"origin_class must be one of {', '.join(ORIGIN_CLASSES)}")
    if origin_root_sha is not None:
        if not isinstance(origin_root_sha, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", origin_root_sha
        ):
            raise BrainError("origin_root_sha must be a 64-character hexadecimal sha256 or None")
        origin_root_sha = origin_root_sha.lower()
    # SEC-AUTH-02 producer guard: `origin_class` is the caller's own description
    # of where the memory came from, so it can never be the reason a memory
    # outranks advisory. Elevation needs an attestation from an independent
    # issuer, and none is registered, so the ceiling stays advisory.
    elevated = origin_class in _PROJECT_RULE_ORIGINS and authority_attested(attestation)
    return origin_class, origin_root_sha, "project_rule" if elevated else "advisory"


def _lane_authorized(row: dict, lane: str) -> bool:
    """Policy permission comes only from authority an independent issuer granted."""
    return lane != "policy" or effective_authority_ceiling(row) in {"project_rule", "policy"}


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _event_view(raw: object) -> tuple[str, dict, str, str] | None:
    """Normalize one ledger event or hash-bound telemetry record."""
    if isinstance(raw, dict):
        outer = raw
        nested = raw.get("payload")
        payload = dict(nested) if isinstance(nested, dict) else dict(raw)
    else:
        outer = {
            "event_id": getattr(raw, "event_id", None),
            "event_type": getattr(raw, "event_type", None),
            "internal_session_id": getattr(raw, "internal_session_id", None),
            "artifact_sha256": getattr(raw, "artifact_sha256", None),
        }
        nested = getattr(raw, "payload", None)
        if not isinstance(nested, dict):
            return None
        payload = dict(nested)

    raw_kind = outer.get("event_type") or outer.get("kind")
    kind = str(getattr(raw_kind, "value", raw_kind) or "").strip().lower()
    if not kind:
        return None
    event_id = outer.get("event_id")
    telemetry_ref = outer.get("telemetry_ref")
    if isinstance(event_id, str) and event_id.strip():
        ref = event_id.strip()
    elif (
        isinstance(telemetry_ref, str)
        and 0 < len(telemetry_ref.strip()) <= _CANDIDATE_REF_LIMIT
        and _is_sha256(outer.get("record_hash"))
    ):
        unhashed = {
            key: value
            for key, value in outer.items()
            if key not in {"telemetry_ref", "record_hash"}
        }
        expected = hashlib.sha256(canonical_json(unhashed).encode("utf-8")).hexdigest()
        if expected != str(outer["record_hash"]).lower():
            return None
        ref = telemetry_ref.strip()
    else:
        return None
    if len(ref) > _CANDIDATE_REF_LIMIT:
        raise BrainError(f"source event ref exceeds {_CANDIDATE_REF_LIMIT} characters")

    for key in ("artifact_sha256", "record_hash"):
        if key in outer and key not in payload:
            payload[key] = outer[key]
    session = str(
        outer.get("internal_session_id")
        or outer.get("session")
        or outer.get("brain_session_id")
        or outer.get("hermes_session_id")
        or ""
    ).strip()
    return kind, payload, ref, session


def _bound_evidence(payload: dict) -> bool:
    return any(_is_sha256(payload.get(field)) for field in _SHA_FIELDS)


def _signal_key(payload: dict) -> str:
    for field in (
        "signal_key",
        "fingerprint_id",
        "task_id",
        "test_id",
        "failure_code",
        "original_result_sha256",
    ):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return f"{field}:{value.strip()}"
    return ""


def _extract_candidate_evidence(
    events: Sequence[object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes, bytearray)):
        raise BrainError("events must be a sequence of ledger or telemetry records")
    if len(events) > _CANDIDATE_EVENT_LIMIT:
        raise BrainError(f"events must contain at most {_CANDIDATE_EVENT_LIMIT} records")

    views = [view for raw in events if (view := _event_view(raw)) is not None]
    refs_by_trigger: dict[str, set[str]] = {}

    def add(trigger: CandidateTrigger, *refs: str) -> None:
        refs_by_trigger.setdefault(trigger.value, set()).update(refs)

    repeated_failures: dict[str, list[tuple[str, str]]] = {}
    cross_session: dict[str, list[tuple[str, str]]] = {}
    for kind, payload, ref, session in views:
        bound = _bound_evidence(payload)
        verified = payload.get("verified") is True or payload.get("approved") is True or bound
        signal = _signal_key(payload)

        if kind in _CORRECTION_EVENTS and bound:
            add(CandidateTrigger.CORRECTION, ref)
            attempt = payload.get("correction_attempt")
            if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 2:
                add(CandidateTrigger.REPETITION, ref)
        if (
            payload.get("regression_verified") is True
            or (payload.get("regression") is True and payload.get("verified") is True)
            or (
                str(payload.get("failure_code") or "").upper() == "REGRESSION"
                and payload.get("verified") is True
            )
        ):
            add(CandidateTrigger.REGRESSION, ref)
        if payload.get("subtle") is True and verified:
            add(CandidateTrigger.SUBTLETY, ref)

        severity = str(payload.get("severity") or "").upper()
        impact = payload.get("impact_score")
        severe_impact = (
            isinstance(impact, (int, float))
            and not isinstance(impact, bool)
            and math.isfinite(float(impact))
            and float(impact) >= 8.0
            and bound
        )
        if (severity in {"HIGH", "CRITICAL"} and verified) or severe_impact:
            add(CandidateTrigger.SEVERITY, ref)

        verdict = str(payload.get("verdict") or payload.get("result") or "").upper()
        if kind == "independent_verification" and verdict == "PASS" and verified:
            add(CandidateTrigger.INDEPENDENT_EVIDENCE, ref)

        occurrence = payload.get("occurrence_count")
        if (
            isinstance(occurrence, int)
            and not isinstance(occurrence, bool)
            and occurrence >= 2
            and bound
        ):
            add(CandidateTrigger.REPETITION, ref)
        if kind in _FAILURE_EVENTS and payload.get("verified") is True and signal:
            repeated_failures.setdefault(signal, []).append((ref, session))
        if signal and session and verified:
            cross_session.setdefault(signal, []).append((ref, session))

    for observations in repeated_failures.values():
        unique_refs = sorted({ref for ref, _session in observations})
        if len(unique_refs) >= 2:
            add(CandidateTrigger.REPETITION, *unique_refs)
    for observations in cross_session.values():
        if len({session for _ref, session in observations}) >= 2:
            add(
                CandidateTrigger.CROSS_SESSION_REUSE,
                *(ref for ref, _session in observations),
            )

    triggers = tuple(sorted(refs_by_trigger))
    refs = tuple(sorted({ref for trigger_refs in refs_by_trigger.values() for ref in trigger_refs}))
    return triggers, refs


def extract_candidate_triggers(events: Sequence[object]) -> tuple[str, ...]:
    """Return normalized evidence triggers; model confidence is never a signal."""
    return _extract_candidate_evidence(events)[0]


def _candidate_row(home: Path | str, candidate_id: str) -> dict | None:
    conn = db.connect(_dbfile(Path(home)), readonly=True)
    try:
        row = conn.execute(
            "SELECT * FROM v2_candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    result = dict(row)
    result["triggers"] = json.loads(result["trigger_set_json"])
    result["source_event_refs"] = json.loads(result["source_event_refs_json"])
    return result


def evaluate_candidate(
    home: Path | str,
    title: str,
    body: str,
    *,
    events: Sequence[object],
    session_id: str,
    task_id: str | None = None,
    scope: str = "project",
    project_id: str | None = None,
    origin_class: str = "MODEL_INFERENCE",
    origin_root_sha: str | None = None,
) -> dict | None:
    """Apply the earned-memory gate and persist only a SHADOW candidate.

    The API deliberately exposes no confidence, authority, status, or rollout
    parameters. Those values are derived from the immutable T1.7 origin ceiling.
    """
    _validate_new(title, body, scope, "INFERRED")
    if not isinstance(session_id, str) or not session_id.strip():
        raise BrainError("session_id must be a non-empty string")
    origin_class, origin_root_sha, authority_ceiling = _validate_origin(
        origin_class, origin_root_sha
    )
    triggers, source_refs = _extract_candidate_evidence(events)
    if _admission_stage(Path(home)) is RolloutStage.OFF:
        return None
    identity = {
        "title": " ".join(title.strip().casefold().split()),
        "body_sha256": hashlib.sha256(body.strip().encode("utf-8")).hexdigest(),
        "scope": scope,
        "project_id": project_id,
    }
    candidate_id = (
        "candidate-" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]
    )
    inputs = {
        "candidate_id": candidate_id,
        "trigger_set": list(triggers),
        "source_event_refs": list(source_refs),
        "origin_class": origin_class,
        "authority_ceiling": authority_ceiling,
    }
    outcome = "candidate_shadowed" if triggers else "no_candidate"
    decision_ref = decisions.record(
        home,
        kind="admission",
        session_id=session_id.strip(),
        task_id=task_id,
        chosen={"outcome": outcome, "candidate_id": candidate_id if triggers else None},
        alternatives=[{"outcome": "no_candidate"}, {"outcome": "candidate_shadowed"}],
        propensity=1.0,
        randomized=False,
        policy_version=_EARNED_MEMORY_POLICY_VERSION,
        stage="SHADOW",
        inputs=inputs,
    )
    if not triggers:
        return None

    confidence = "medium" if origin_class in _PROJECT_RULE_ORIGINS else "low"
    _ensure_migrated(Path(home))
    now = _utcnow()
    conn = db.connect(_dbfile(Path(home)))
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT trigger_set_json, source_event_refs_json FROM v2_candidates "
            "WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO v2_candidates(
                    candidate_id, title, body, scope, project_id, lifecycle_state,
                    trigger_set_json, source_event_refs_json, origin_class,
                    origin_root_sha, authority_ceiling, confidence, rollout_stage,
                    decision_ref, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?, 'SHADOW', ?, ?, ?)""",
                (
                    candidate_id,
                    title.strip(),
                    body.strip(),
                    scope,
                    project_id,
                    canonical_json(list(triggers)),
                    canonical_json(list(source_refs)),
                    origin_class,
                    origin_root_sha,
                    authority_ceiling,
                    confidence,
                    decision_ref,
                    now,
                    now,
                ),
            )
        else:
            merged_triggers = sorted(set(json.loads(existing["trigger_set_json"])) | set(triggers))
            merged_refs = sorted(
                set(json.loads(existing["source_event_refs_json"])) | set(source_refs)
            )
            if len(merged_refs) > 64:
                raise BrainError("candidate source event refs exceed 64-record bound")
            if (
                canonical_json(merged_triggers) != existing["trigger_set_json"]
                or canonical_json(merged_refs) != existing["source_event_refs_json"]
            ):
                conn.execute(
                    "UPDATE v2_candidates SET trigger_set_json = ?, "
                    "source_event_refs_json = ?, decision_ref = ?, updated_at = ? "
                    "WHERE candidate_id = ?",
                    (
                        canonical_json(merged_triggers),
                        canonical_json(merged_refs),
                        decision_ref,
                        now,
                        candidate_id,
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _candidate_row(home, candidate_id)


def corroboration_count(rows: object) -> int:
    """Count independent corroboration roots, ignoring missing roots."""
    iterable = rows if isinstance(rows, Iterable) else ()
    roots: set[str] = set()
    for row in iterable:
        if not isinstance(row, dict):
            continue
        root = row.get("origin_root_sha")
        if isinstance(root, str) and root.strip():
            roots.add(root.lower())
    return len(roots)


def _validate_new(title: str, body: str, scope: str, grade: str) -> None:
    if not isinstance(title, str) or not title.strip():
        raise BrainError("title must be a non-empty string")
    if not isinstance(body, str) or not body.strip():
        raise BrainError("body must be a non-empty string")
    if scope not in SCOPES:
        raise BrainError(f"scope must be one of {', '.join(SCOPES)}")
    if grade not in GRADES:
        raise BrainError(f"grade must be one of {', '.join(GRADES)}")


def _render_file(
    memory_id: str,
    title: str,
    scope: str,
    project_id: str | None,
    status: str,
    grade: str,
    version: int,
    created_at: str,
    body: str,
) -> str:
    lines = [
        "---",
        f"id: {memory_id}",
        f"title: {title}",
        f"scope: {scope}",
        f"project: {project_id or ''}",
        f"status: {status}",
        f"grade: {grade}",
        f"version: {version}",
        f"created_at: {created_at}",
        "---",
        "",
        body.rstrip(),
        "",
    ]
    return "\n".join(lines)


def _write_file_exclusive(path: Path, data: str) -> None:
    """Write with O_CREAT|O_EXCL: fails instead of overwriting (race-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


def _write_file_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write {path}: {exc}") from exc


_FTS5_CREATE = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
    "memory_id UNINDEXED, title, summary, body, project_id, status, "
    "evidence_grade, tags, tokenize = 'unicode61')"
)
# FTS5 vocabulary is derived lazily with the index.  It is intentionally not
# part of a migration: older databases get it the first time FTS is touched.
_FTS5_VOCAB_CREATE = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_vocab USING fts5vocab(memory_fts, 'row')"
)

# Keep this list literal and local to the query builder so token selection is
# deterministic and does not depend on an optional NLP package.
_QUERY_STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "aren't",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "can't",
        "cannot",
        "could",
        "couldn't",
        "did",
        "didn't",
        "do",
        "does",
        "doesn't",
        "doing",
        "don't",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "hadn't",
        "has",
        "hasn't",
        "have",
        "haven't",
        "having",
        "he",
        "he'd",
        "he'll",
        "he's",
        "her",
        "here",
        "here's",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "how's",
        "i",
        "i'd",
        "i'll",
        "i'm",
        "i've",
        "if",
        "in",
        "into",
        "is",
        "isn't",
        "it",
        "it'd",
        "it'll",
        "it's",
        "its",
        "itself",
        "let's",
        "me",
        "more",
        "most",
        "mustn't",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "ought",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "shan't",
        "she",
        "she'd",
        "she'll",
        "she's",
        "should",
        "shouldn't",
        "so",
        "some",
        "such",
        "than",
        "that",
        "that's",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "there's",
        "these",
        "they",
        "they'd",
        "they'll",
        "they're",
        "they've",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "wasn't",
        "we",
        "we'd",
        "we'll",
        "we're",
        "we've",
        "were",
        "weren't",
        "what",
        "what's",
        "when",
        "when's",
        "where",
        "where's",
        "which",
        "while",
        "who",
        "who's",
        "whom",
        "why",
        "why's",
        "will",
        "with",
        "won't",
        "would",
        "wouldn't",
        "you",
        "you'd",
        "you'll",
        "you're",
        "you've",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "able",
        "absolutely",
        "according",
        "accordingly",
        "across",
        "actually",
        "afterwards",
        "anyhow",
        "anything",
        "anyway",
        "anyways",
        "anywhere",
        "apparently",
        "appreciate",
        "appropriate",
        "aside",
        "away",
        "became",
        "become",
        "becomes",
        "becoming",
        "believe",
    ]
)

# Apply the same tokenizer to literal entries so contractions such as
# ``couldn't`` suppress their ASCII fragments (``couldn``), too.
_QUERY_STOPWORD_TOKENS = frozenset(
    fragment
    for word in _QUERY_STOPWORDS
    for fragment in re.findall(r"[a-z0-9]{3,}", word.casefold())
)


def _query_candidates(text: str) -> list[str]:
    if not isinstance(text, str) or re.search(r"[^\x00-\x7f]", text):
        return []
    return list(
        dict.fromkeys(
            token
            for token in re.findall(r"[a-z0-9]{3,}", text.casefold())
            if token not in _QUERY_STOPWORD_TOKENS
        )
    )


# Corpus statistics, not word lists: a plan term is *specific* when it names a
# small slice of the corpus (at most _SPECIFIC_TERM_DF_RATIO of its documents,
# never fewer than _SPECIFIC_TERM_MIN_DF documents so a small fixture corpus keeps
# a usable notion of rarity). No term is special-cased by its spelling.
_SPECIFIC_TERM_DF_RATIO = 0.10
_SPECIFIC_TERM_MIN_DF = 2
# A term appearing in at most two memories names one memory's own subject matter
# (an identifier, a symbol, a named fact) rather than a topic the corpus shares.
# A row whose evidence rests on a single matched plan term is held to this bar (see
# `match_evidence`): one mid-frequency word is weak evidence when the request also
# carries content terms the row cannot explain, unless that word names one memory.
_UNIQUE_TERM_MAX_DF = 2
# Body-only evidence needs two such coincidences; a single rare word in a body is
# how instruction vocabulary ("rewrite", "passive", "nothing") overlaps memories.
_UNIQUE_TERM_MIN_HITS = 2
# A term spread over more than half the corpus cannot tell two memories apart. When
# *every* plan term is that common — a young Brain home, or a request stated purely
# in the corpus's own common vocabulary — lexical specificity has nothing left to
# discriminate with, so a headline confirmation is the evidence available.
_UBIQUITOUS_TERM_DF_RATIO = 0.50


@dataclass(frozen=True)
class QueryMatchPlan:
    """The lexical term plan one search used, plus the statistics behind it.

    ``terms`` are the IDF-ranked query terms the lexical search matched against
    (empty when no term evidence exists at all). ``frequencies`` is the exact-token
    document count that drove term selection; ``breadth`` is the same count under
    the prefix matching the FTS query actually uses (``"mem"*`` also matches
    ``memory``), an upper bound, so a short term cannot look rare here while
    matching broadly there. ``distinct`` carries the exact prefix document count for
    the terms whose bound could reach the ubiquity threshold, the only measurement
    allowed to prove ubiquity. ``total_documents`` is the corpus size.
    """

    text: str
    expression: str | None = None
    terms: tuple[str, ...] = ()
    required: int = 0
    frequencies: dict[str, int] = _field(default_factory=dict)
    total_documents: int = 0
    breadth: dict[str, int] = _field(default_factory=dict)
    distinct: dict[str, int] = _field(default_factory=dict)

    def document_frequency(self, term: str) -> int:
        """Corpus document count for one plan term under the matching rule.

        Callers only ask about plan terms, which carry a measured breadth; an
        unmeasured term counts as universal, never as rare.
        """
        if term in self.breadth:
            return int(self.breadth[term])
        return int(self.frequencies.get(term, self.total_documents))

    def is_specific(self, term: str) -> bool:
        """Whether a term names a small slice of the corpus rather than the corpus."""
        return self.document_frequency(term) <= max(
            _SPECIFIC_TERM_MIN_DF,
            math.ceil(_SPECIFIC_TERM_DF_RATIO * self.total_documents),
        )

    def is_unique(self, term: str) -> bool:
        """Whether a term names essentially one memory (an identifier or named fact)."""
        return self.document_frequency(term) <= _UNIQUE_TERM_MAX_DF

    def is_ubiquitous(self, term: str) -> bool:
        """Whether a term provably spans more than half the corpus.

        Only the exact distinct prefix count can prove that: the summed vocabulary
        range is an upper bound, and a term without a measured distinct count is not
        treated as ubiquitous.
        """
        measured = self.distinct.get(term)
        if measured is None:
            return False
        return measured > _UBIQUITOUS_TERM_DF_RATIO * self.total_documents

    def has_discriminative_term(self) -> bool:
        """Whether any plan term can tell memories apart at all."""
        return any(self.is_specific(term) for term in self.terms)

    def content_terms(self) -> tuple[str, ...]:
        """The request's content tokens after the stopword filter, out-of-vocabulary included.

        ``terms`` is what the corpus could match: vocabulary-filtered, IDF-ranked and
        capped. This is what the request actually said, so a row can be judged on how
        much of the request it explains instead of on the plan's surviving subset. A
        non-ASCII request yields none (the tokenizer declines it), which only widens
        what counts as unexplained.
        """
        return tuple(_query_candidates(self.text))

    def unexplained_content_terms(self, row_tokens: Sequence[str]) -> tuple[str, ...]:
        """Content terms no token of `row_tokens` confirms, under the matching prefix rule."""
        return tuple(
            term
            for term in self.content_terms()
            if not any(token.startswith(term) for token in row_tokens)
        )


@dataclass(frozen=True)
class MatchEvidence:
    """Why one retrieved candidate row is (or is not) treated as contributing."""

    contributing: bool
    matched: tuple[str, ...] = ()
    headline_matched: tuple[str, ...] = ()
    specific_matched: tuple[str, ...] = ()
    unique_matched: tuple[str, ...] = ()
    quoted_headline: tuple[str, ...] = ()
    #: Request content terms the row does not confirm; populated only when the row
    #: matched exactly one plan term (the case the single-term guard judges).
    unexplained_terms: tuple[str, ...] = ()


def _prefix_bounds(
    term: str,
) -> tuple[str, str]:
    """Half-open vocabulary-term range covering every term that starts with `term`."""
    return term, term[:-1] + chr(ord(term[-1]) + 1)


def _prefix_document_frequencies(
    conn: sqlite3.Connection, terms: tuple[str, ...], total: int
) -> tuple[dict[str, int], dict[str, int]]:
    """Prefix match breadth per plan term: an upper bound, plus a sound ubiquity count.

    ``memory_fts_vocab.doc`` counts one exact token, so summing a prefix range over
    it measures breadth as an *upper* bound (a document holding two matching tokens
    counts twice). That direction is safe for every rarity claim — a term can only
    look broader than it is — but it must never be used to *prove* ubiquity, which
    needs a lower bound on the same measure. So the summed range is computed always
    (one cheap range scan per term), and the exact distinct document count is asked
    of the index with the same prefix expression only for terms whose upper bound
    could reach the ubiquity threshold; a term whose bound stays below it cannot be
    ubiquitous, so no index count is spent on it.

    Returns ``(breadth, distinct)``; ``distinct`` holds only the measured terms, and
    a term missing from it must not be treated as ubiquitous.
    """
    breadth: dict[str, int] = {}
    distinct: dict[str, int] = {}
    for term in terms:
        lower, upper = _prefix_bounds(term)
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(doc), 0) FROM memory_fts_vocab WHERE term >= ? AND term < ?",
                (lower, upper),
            ).fetchone()
            summed = min(int(total), int(row[0] or 0)) if row is not None else total
        except sqlite3.Error:
            continue
        breadth[term] = summed
        if summed <= _UBIQUITOUS_TERM_DF_RATIO * total:
            continue
        try:
            counted = conn.execute(
                "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?", (f'"{term}"*',)
            ).fetchone()
        except sqlite3.Error:
            continue
        if counted is not None:
            exact = min(int(total), int(counted[0] or 0))
            breadth[term] = exact  # the exact count is at least as tight
            distinct[term] = exact
    return breadth, distinct


def _plan_with_stats(
    text: str, *, k: int = 8, msm: float = 0.5, conn: sqlite3.Connection | None = None
) -> QueryMatchPlan:
    """`_query_plan` plus the document frequencies it already had to look up.

    A query with a single candidate term keeps the established single-token FTS
    path: one term, required match count 1, and no vocabulary filter — a search for
    a middle-of-word substring such as "car" must still take the FTS prefix path
    instead of falling through to the substring scan (documented divergence).
    Public `build_query` separately declines one-term input.
    """
    candidates = _query_candidates(text)
    if not candidates:
        return QueryMatchPlan(text=text)
    frequencies: dict[str, int] = {}
    total = 0
    if conn is not None:
        if not _fts_available(conn):
            return QueryMatchPlan(text=text)
        if len(candidates) == 1:
            term = candidates[0]
            try:
                row = conn.execute(
                    "SELECT doc FROM memory_fts_vocab WHERE term = ?", (term,)
                ).fetchone()
                total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            except sqlite3.Error:
                row, total = None, 0
            breadth, distinct = _prefix_document_frequencies(conn, (term,), total)
            return QueryMatchPlan(
                text=text,
                expression=f'"{term}"*',
                terms=(term,),
                required=1,
                frequencies={term: int(row[0])} if row is not None else {},
                total_documents=total,
                breadth=breadth,
                distinct=distinct,
            )
        placeholders = ",".join("?" for _ in candidates)
        try:
            rows = conn.execute(
                f"SELECT term, doc FROM memory_fts_vocab WHERE term IN ({placeholders})",
                candidates,
            ).fetchall()
            frequencies = {str(row["term"]): int(row["doc"]) for row in rows}
            total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        except sqlite3.Error:
            total = 0
        candidates = [token for token in candidates if token in frequencies]
        if not candidates:
            return QueryMatchPlan(text=text, total_documents=total)
    positions = {token: index for index, token in enumerate(candidates)}
    try:
        limit = max(1, int(k))
    except (TypeError, ValueError):
        limit = 8
    limit = min(limit, len(candidates))
    idf = {token: math.log((total + 1) / (frequencies.get(token, 0) + 1)) for token in candidates}
    selected = tuple(sorted(candidates, key=lambda token: (-idf[token], positions[token]))[:limit])
    try:
        ratio = min(1.0, max(0.0, float(msm)))
    except (TypeError, ValueError):
        ratio = 0.5
    required = math.ceil(ratio * len(selected))
    expression = "(" + " OR ".join(f'"{token}"*' for token in selected) + ")"
    breadth, distinct = (
        _prefix_document_frequencies(conn, selected, total) if conn is not None else ({}, {})
    )
    return QueryMatchPlan(
        text=text,
        expression=expression,
        terms=selected,
        required=required,
        frequencies=frequencies,
        total_documents=total,
        breadth=breadth,
        distinct=distinct,
    )


def _query_plan(
    text: str, *, k: int = 8, msm: float = 0.5, conn: sqlite3.Connection | None = None
) -> tuple[str | None, tuple[str, ...], int]:
    plan = _plan_with_stats(text, k=k, msm=msm, conn=conn)
    return plan.expression, plan.terms, plan.required


def build_query(
    text: str, k: int = 8, msm: float = 0.5, *, conn: sqlite3.Connection | None = None
) -> str | list:
    """Build a bounded, parameter-safe FTS5 OR query using IDF-ranked terms."""
    expression, query_terms, _required = _query_plan(text, k=k, msm=msm, conn=conn)
    if len(query_terms) < 2:
        return []
    assert expression is not None
    return expression


def query_match_plan(
    home: Path | str, text: str, *, k: int = 8, msm: float = 0.5
) -> QueryMatchPlan:
    """The lexical term plan of `text` against `home`, with corpus statistics.

    Mirrors what a lexical search of the same text would use (same vocabulary
    lookup, same single-token fallback). A plan with no terms means no lexical term
    evidence exists at all — FTS5 unavailable, a non-tokenizable query, or an
    unbuilt index — and callers must not invent a gate from it.
    """
    home_path = Path(home)
    _ensure_migrated(home_path)
    conn = db.connect(_dbfile(home_path))
    try:
        if not _fts_available(conn):
            return QueryMatchPlan(text=text)
        total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        if _fts_count(conn) <= 0 and total > 0:
            return QueryMatchPlan(text=text, total_documents=total)
        return _plan_with_stats(text, k=k, msm=msm, conn=conn)
    except sqlite3.Error:
        return QueryMatchPlan(text=text)
    finally:
        conn.close()


def _tokens(text: object) -> list[str]:
    """The tokenizer both matching and evidence use (identical to FTS prefix hits)."""
    return re.findall(r"[a-z0-9]{3,}", str(text or "").casefold())


def _row_haystack_tokens(row: dict) -> list[str]:
    haystack = " ".join(
        str(row.get(field) or "") for field in ("title", "summary", "_body", "body")
    ).casefold()
    return re.findall(r"[a-z0-9]{3,}", haystack)


def _headline_text(row: dict) -> str:
    """The memory's own statement of what it is about (title/summary)."""
    return " ".join(str(row.get(field) or "") for field in ("title", "summary"))


def _row_headline_tokens(row: dict) -> list[str]:
    """Headline = the memory's own statement of what it is about (title/summary)."""
    haystack = _headline_text(row).casefold()
    return re.findall(r"[a-z0-9]{3,}", haystack)


def _term_hit_tokens(terms: tuple[str, ...], tokens: Sequence[str]) -> tuple[str, ...]:
    """Plan terms with a prefix hit in `tokens` — the rule `_query_term_hits` counts."""
    return tuple(term for term in terms if any(value.startswith(term) for value in tokens))


def _query_term_hits(row: dict, terms: tuple[str, ...]) -> int:
    return len(_term_hit_tokens(terms, _row_haystack_tokens(row)))


# Straight quotes/backticks plus their curly counterparts (\u2018..\u201d), written as
# escapes so the pattern cannot be confused with the ASCII characters around it.
_QUOTED_SPANS = re.compile(
    "`([^`]*)`|'([^']*)'|\"([^\"]*)\"|\u2018([^\u2019]*)\u2019|\u201c([^\u201d]*)\u201d"
)


def _quoted_tokens(text: object) -> list[str]:
    """Tokens that appear inside quotes/backticks: a string mention, not a use.

    A memory whose headline documents a quoted token ('format', a symbol, an error
    id) is about that string; a request only reaches it by quoting the string too.
    """
    tokens: list[str] = []
    for span in _QUOTED_SPANS.findall(str(text or "")):
        fragment = next((part for part in span if part), "")
        tokens.extend(_tokens(fragment))
    return tokens


def match_evidence(row: dict, plan: QueryMatchPlan) -> MatchEvidence:
    """Separate "a candidate was found" from "this candidate contributes here".

    Three independent ways a match is evidence about the request rather than
    incidental keyword overlap:

    * **headline** — a *specific* plan term (one the corpus does not spread
      broadly) is confirmed by the row's own headline, the field that states what
      the memory is about, and that headline occurrence is not a quoted mention
      the request fails to quote back;
    * **unique coincidence** — two or more *near-unique* plan terms (each naming
      at most two memories) match the row anywhere;
    * **no discrimination left** — every plan term spans more than half the corpus,
      so no term can tell memories apart and a headline confirmation is all the
      evidence the corpus holds (a young Brain home, or a request stated purely in
      the corpus's common vocabulary).

    Everything else is overlap on vocabulary the request happens to share with a
    body: the live corpus produced the NB-OK-17 false injection that way, where 81
    of 116 memories satisfied 2 of the 3 surviving plan terms ('tools', 'use',
    'exactly') and none of them matched a headline.

    A headline confirmation is at its weakest when it rests on **one matched plan
    term**: a single mid-frequency word can be shared by a memory and a request that
    are about different things. Such a row must clear one of two bars:

    * the term is near-unique (``df <= 2``) — the word itself names one memory's own
      subject matter, so only that memory can be the one the request means (a short
      question such as "What does PYTHONHOME stand for?" lives here); or
    * the row confirms every other content term the request carries, including terms
      the corpus does not contain at all — the request asked for the row's own
      subject and nothing else (VG-N06: "In one sentence, what is a Python dict?
      Reply with one sentence." reached the PYTHONHOME memory on 'python' alone
      while 'dict' and 'sentence' appear nowhere in the corpus).
    """
    if not plan.terms:
        return MatchEvidence(contributing=True)
    row_tokens = _row_haystack_tokens(row)
    matched = _term_hit_tokens(plan.terms, row_tokens)
    headline_matched = _term_hit_tokens(matched, _row_headline_tokens(row))
    specific_matched = tuple(term for term in matched if plan.is_specific(term))
    unique_matched = tuple(term for term in matched if plan.is_unique(term))
    quoted = _term_hit_tokens(headline_matched, _quoted_tokens(_headline_text(row)))
    request_quotes = _term_hit_tokens(headline_matched, _quoted_tokens(plan.text))
    quoted_headline = tuple(term for term in quoted if term not in request_quotes)
    headline_evidence = any(
        term in specific_matched and term not in quoted_headline for term in headline_matched
    )
    if (
        not headline_evidence
        and not plan.has_discriminative_term()
        and all(plan.is_ubiquitous(term) for term in plan.terms)
    ):
        headline_evidence = any(term not in quoted_headline for term in headline_matched)
    contributing = headline_evidence or len(unique_matched) >= _UNIQUE_TERM_MIN_HITS
    single_term = matched[0] if len(matched) == 1 else None
    unexplained = plan.unexplained_content_terms(row_tokens) if single_term else ()
    if contributing and single_term is not None and unexplained and not plan.is_unique(single_term):
        contributing = False
    return MatchEvidence(
        contributing=contributing,
        matched=matched,
        headline_matched=headline_matched,
        specific_matched=specific_matched,
        unique_matched=unique_matched,
        quoted_headline=quoted_headline,
        unexplained_terms=unexplained,
    )


def row_contributes(row: dict, plan: QueryMatchPlan) -> bool:
    """True when the row's match is evidence about the request, not overlap."""
    return match_evidence(row, plan).contributing


def contribution_filter(rows: list[dict], plan: QueryMatchPlan) -> list[dict]:
    """Keep the rows whose lexical match is evidence about the request (PERF-01/RET-05).

    Ranking decides which candidate is best; this decides whether any candidate
    contributes at all, so retrieval and the injection decision stay separate. A
    plan without terms carries no term evidence (FTS5 unavailable, non-tokenizable
    query, linear-scan search): its rows pass through rather than being re-gated by
    a plan that does not exist.
    """
    if not plan.terms:
        return list(rows)
    return [row for row in rows if match_evidence(row, plan).contributing]


# Process-global FTS5 module availability. SQLite's FTS5 support is a
# property of the sqlite3 build, identical for every database, and cannot
# change mid-process. A single flag (not a per-path cache) avoids any hazard
# from temp-dir path reuse (review N4); the CREATE itself still runs per
# database (IF NOT EXISTS, cheap) so every new DB gets its memory_fts table.
_FTS_MODULE_CHECKED = False
_FTS_MODULE_OK = False


def _fts_available(conn: sqlite3.Connection) -> bool:
    """Whether the memory_fts and its vocabulary table are usable."""
    global _FTS_MODULE_CHECKED, _FTS_MODULE_OK
    if _FTS_MODULE_CHECKED and not _FTS_MODULE_OK:
        return False
    try:
        conn.execute(_FTS5_CREATE)
        conn.execute(_FTS5_VOCAB_CREATE)
        _FTS_MODULE_CHECKED = True
        _FTS_MODULE_OK = True
        return True
    except sqlite3.OperationalError as exc:
        if "no such module" in str(exc).lower():
            _FTS_MODULE_CHECKED = True
            _FTS_MODULE_OK = False
        # other errors: transient, do not degrade the process permanently
        return False


def _fts_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0])


def _body_text(home: Path, row: dict) -> str:
    """Markdown body (after frontmatter) of a memory file; '' when missing."""
    path = (
        Path(home) / row["body_path"] if row.get("body_path") else _v1_path(home, row["memory_id"])
    )
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if content.startswith("---\n") and "\n---" in content:
        content = content.split("\n---", 1)[1]
    return content


def _memory_file_bytes(home: Path, row: dict) -> bytes | None:
    path = (
        Path(home) / row["body_path"] if row.get("body_path") else _v1_path(home, row["memory_id"])
    )
    try:
        return path.read_bytes()
    except OSError:
        return None


def _file_hash(home: Path, row: dict) -> str:
    """sha256 of the canonical markdown file with line endings normalized to LF.

    Any content edit changes it; a checkout that only rewrites line endings
    (git core.autocrlf) does not, so such a checkout cannot silently hide the
    memory from retrieval as "stale".
    """
    data = _memory_file_bytes(home, row)
    if data is None:
        return ""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def file_hash_matches(indexed_hash: str | None, home: Path, row: dict) -> bool:
    """True when an indexed hash still describes the canonical file.

    Accepts the current LF-normalized hash and the pre-normalization raw-bytes
    hash, so an index built before normalization keeps working until the next
    reindex rewrites it.
    """
    if not indexed_hash:
        return False
    data = _memory_file_bytes(home, row)
    if data is None:
        return False
    if indexed_hash == hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest():
        return True
    return indexed_hash == hashlib.sha256(data).hexdigest()


def _index_memory_row(conn: sqlite3.Connection, home: Path, row: dict, *, file_hash: str) -> None:
    """Upsert one memory into memory_index + memory_fts (derived state)."""
    body = _body_text(home, row)
    tags = ""
    # Optional canonical extension: a comma/space separated `tags:` frontmatter
    # line (not written by the canonical writer; read if a user adds it).
    try:
        path = (
            Path(home) / row["body_path"]
            if row.get("body_path")
            else _v1_path(home, row["memory_id"])
        )
        content = path.read_text(encoding="utf-8")
        if content.startswith("---\n") and "\n---" in content:
            fm = content[4 : content.index("\n---")]
            for line in fm.splitlines():
                if line.startswith("tags:"):
                    tags = ",".join(w for w in re.split(r"[,\s]+", line[5:].strip()) if w)
                    break
    except OSError:
        pass
    conn.execute(
        """INSERT INTO memory_index
           (memory_id, title, summary, project_id, scope, status, evidence_grade,
            current_version, created_at, updated_at, body_path, tags, file_hash, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(memory_id) DO UPDATE SET
             title=excluded.title, summary=excluded.summary, project_id=excluded.project_id,
             scope=excluded.scope, status=excluded.status, evidence_grade=excluded.evidence_grade,
             current_version=excluded.current_version, created_at=excluded.created_at,
             updated_at=excluded.updated_at, body_path=excluded.body_path, tags=excluded.tags,
             file_hash=excluded.file_hash, indexed_at=excluded.indexed_at""",
        (
            row["memory_id"],
            row["title"],
            row.get("summary") or "",
            row.get("project_id"),
            row.get("scope"),
            row.get("status"),
            row.get("evidence_grade"),
            row.get("current_version"),
            row.get("created_at"),
            row.get("updated_at"),
            row.get("body_path"),
            tags,
            file_hash,
            _utcnow(),
        ),
    )
    if _fts_available(conn):
        conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (row["memory_id"],))
        conn.execute(
            "INSERT INTO memory_fts (memory_id, title, summary, body, project_id, "
            "status, evidence_grade, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["memory_id"],
                row["title"],
                row.get("summary") or "",
                body,
                row.get("project_id") or "",
                row.get("status") or "",
                row.get("evidence_grade") or "",
                tags,
            ),
        )


def _index_memory(home: Path, memory_id: str) -> bool:
    """Index one memory (derived state). False when the memory is unknown."""
    row = _row(home, memory_id)
    if row is None:
        return False
    file_hash = _file_hash(home, row)
    conn = db.connect(_dbfile(home))
    try:
        _index_memory_row(conn, home, row, file_hash=file_hash)
        db.bump_memory_epoch(conn)
        conn.commit()
        return True
    finally:
        conn.close()


def _safe_index(home: Path, memory_id: str) -> None:
    """Lifecycle hook: index failures must never break memory curation.

    The index is derived and rebuildable (`reindex_all`); fail open.
    """
    try:
        _index_memory(home, memory_id)
    except (sqlite3.Error, OSError, BrainError) as exc:
        # Derived index: fail open, but stay observable (F4).
        _LOG.warning("memory index update failed for %s: %s", memory_id, exc)


def index_memory(home: Path, memory_id: str) -> bool:
    """Public: (re)index one memory into the derived SQLite index."""
    _ensure_migrated(home)
    return _index_memory(home, memory_id)


def reindex_all(home: Path) -> dict:
    """Full rebuild of the derived memory index (idempotent, incremental).

    Skips memories whose canonical file hash is unchanged; purges index rows
    whose files no longer exist. Returns {"indexed", "skipped", "purged"}.
    """
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    counts = {"indexed": 0, "skipped": 0, "purged": 0}
    try:
        fts_ok = _fts_available(conn)  # F1: availability derived once
        db_rows = {r["memory_id"]: dict(r) for r in conn.execute("SELECT * FROM memories")}
        for memory_id, row in db_rows.items():
            hash_now = _file_hash(home, row)
            if not hash_now:
                # canonical file missing -> derived row is stale, purge it
                if fts_ok:
                    conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
                conn.execute("DELETE FROM memory_index WHERE memory_id = ?", (memory_id,))
                counts["purged"] += 1
                continue
            prev = conn.execute(
                "SELECT file_hash FROM memory_index WHERE memory_id = ?", (memory_id,)
            ).fetchone()
            if prev is not None and prev["file_hash"] == hash_now:
                counts["skipped"] += 1
                continue
            _index_memory_row(conn, home, row, file_hash=hash_now)
            counts["indexed"] += 1
        # safety net: index rows whose memory row disappeared entirely
        indexed_ids = {r["memory_id"] for r in conn.execute("SELECT memory_id FROM memory_index")}
        for memory_id in indexed_ids - set(db_rows):
            if fts_ok:
                conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            conn.execute("DELETE FROM memory_index WHERE memory_id = ?", (memory_id,))
            counts["purged"] += 1
        db.bump_memory_epoch(conn)
        conn.commit()
        return counts
    finally:
        conn.close()


def add_memory(
    home: Path,
    title: str,
    body: str,
    *,
    scope: str = "project",
    project_id: str | None = None,
    grade: str = "OBSERVED",
    sources: list[dict] | None = None,
    summary: str | None = None,
    origin_class: str = "MODEL_INFERENCE",
    origin_root_sha: str | None = None,
    attestation: dict | None = None,
) -> str:
    """Create a semantic memory with immutable write-time origin authority.

    ``grade`` is a request: VERIFIED needs ``attestation`` from an independent
    issuer and is refused with ``VERIFIED_REQUIRES_ATTESTATION`` otherwise
    (SEC-AUTH-02). No issuer is registered in this build.

    ``origin_class`` is self-description too: it cannot raise the authority
    ceiling above ``advisory``, which likewise needs an independent attestation
    (registered issuers: none), so an unattested memory is always advisory.
    """
    _validate_new(title, body, scope, grade)
    _require_verified_attestation(grade, attestation, operation="add_memory")
    clean_sources = _validate_sources(sources)
    origin_class, origin_root_sha, authority_ceiling = _validate_origin(
        origin_class, origin_root_sha, attestation
    )
    if summary is not None and not isinstance(summary, str):
        raise BrainError("summary must be a string or None")
    _ensure_migrated(home)

    now = _utcnow()
    memory_id: str | None = None
    path: Path | None = None
    # Exclusive create (O_CREAT|O_EXCL): a concurrent same-id writer can never
    # overwrite our file; DB-failure cleanup below only ever removes OUR file.
    for _ in range(ID_RETRIES):
        candidate = "mem-" + secrets.token_hex(6)
        cand_path = _v1_path(home, candidate)
        if cand_path.exists() or _row(home, candidate) is not None:
            continue
        content = _render_file(
            candidate, title, scope, project_id, "candidate", grade, 1, now, body
        )
        try:
            _write_file_exclusive(cand_path, content)
        except FileExistsError:
            continue
        memory_id = candidate
        path = cand_path
        break
    if memory_id is None or path is None:
        raise BrainError("Could not allocate a unique memory id after 5 attempts")

    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            """INSERT INTO memories
               (memory_id, title, scope, project_id, status, evidence_grade,
                current_version, created_at, updated_at, last_verified_at,
                strength, stability, summary, body_path,
                origin_class, origin_root_sha, authority_ceiling)
               VALUES (?, ?, ?, ?, 'candidate', ?, 1, ?, ?, NULL, ?, ?, ?, ?,
                       ?, ?, ?)""",
            (
                memory_id,
                title,
                scope,
                project_id,
                grade,
                now,
                now,
                DEFAULT_STRENGTH,
                DEFAULT_STABILITY,
                summary,
                str(path.relative_to(home)),
                origin_class,
                origin_root_sha,
                authority_ceiling,
            ),
        )
        _insert_sources(conn, memory_id, clean_sources, now)
        db.bump_memory_epoch(conn)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        with contextlib.suppress(OSError):
            path.unlink()  # no orphans
        raise BrainError(f"Could not insert memory {memory_id}: {exc}") from exc
    finally:
        conn.close()
    _safe_index(home, memory_id)
    return memory_id


def _check_grade_transition(current: str, new: str) -> None:
    """One-step upgrade, same grade, REJECTED anywhere, HISTORICAL downgrade only."""
    if new == current or new == "REJECTED":
        return
    if new == "HISTORICAL" and _GRADE_RANK[new] < _GRADE_RANK[current]:
        return
    if (
        current in _UPGRADE_CHAIN
        and new in _UPGRADE_CHAIN
        and _GRADE_RANK[new] == _GRADE_RANK[current] + 1
    ):
        return
    raise BrainError(
        f"Grade transition {current} -> {new} not allowed "
        "(one-step upgrades only; downgrades only to REJECTED/HISTORICAL)"
    )


def _sync_file_metadata(home: Path, path: str, *, grade: str, status: str) -> None:
    """Rewrite a memory file's frontmatter grade/status lines; body preserved."""
    p = Path(home) / path
    with p.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    if not text.startswith("---"):
        raise BrainError(f"Corrupt memory file (missing frontmatter): {p}")
    fm_end = text.find("\n---\n")
    if fm_end == -1:
        raise BrainError(f"Corrupt memory file (unterminated frontmatter): {p}")
    fm = text[:fm_end]  # "---\nid: ...\ncreated_at: ..."
    rest = text[fm_end + 1 :]  # "---\n<body>" (closing fence kept)
    fm_lines = []
    for line in fm.splitlines():
        if line.startswith("grade:"):
            fm_lines.append(f"grade: {grade}")
        elif line.startswith("status:"):
            fm_lines.append(f"status: {status}")
        else:
            fm_lines.append(line)
    new_text = "\n".join(fm_lines) + "\n" + rest
    _write_file_atomic(p, new_text)


def curate(
    home: Path,
    memory_id: str,
    *,
    grade: str | None = None,
    status: str | None = None,
    sources: list[dict] | None = None,
    verify: bool = True,
    authority_ceiling: str | None = None,
    attestation: dict | None = None,
) -> dict:
    """Curate one memory; authority may only move toward advisory.

    A ``grade`` of VERIFIED is a request: it needs ``attestation`` from an
    independent issuer and is refused with ``VERIFIED_REQUIRES_ATTESTATION``
    otherwise (SEC-AUTH-02). No issuer is registered in this build.
    """
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    if grade is not None:
        if grade not in GRADES:
            raise BrainError(f"grade must be one of {', '.join(GRADES)}")
        _require_verified_attestation(grade, attestation, operation="curate")
        _check_grade_transition(row["evidence_grade"], grade)
    if status is not None and status not in STATUSES:
        raise BrainError(f"status must be one of {', '.join(STATUSES)}")
    new_ceiling = row.get("authority_ceiling") or "advisory"
    if authority_ceiling is not None:
        if authority_ceiling not in AUTHORITY_CEILINGS:
            raise BrainError(f"authority_ceiling must be one of {', '.join(AUTHORITY_CEILINGS)}")
        if _AUTHORITY_RANK[authority_ceiling] > _AUTHORITY_RANK[new_ceiling]:
            raise BrainError("authority_ceiling may only be lowered")
        new_ceiling = authority_ceiling
    clean_sources = _validate_sources(sources)

    now = _utcnow()
    new_grade = grade if grade is not None else row["evidence_grade"]
    new_status = status if status is not None else row["status"]
    last_verified = row["last_verified_at"]
    if new_grade == "VERIFIED" and verify:
        last_verified = now

    conn = db.connect(_dbfile(home))
    try:
        conn.execute(
            "UPDATE memories SET evidence_grade = ?, status = ?, updated_at = ?, "
            "last_verified_at = ?, authority_ceiling = ? WHERE memory_id = ?",
            (new_grade, new_status, now, last_verified, new_ceiling, memory_id),
        )
        _insert_sources(conn, memory_id, clean_sources, now)
        db.bump_memory_epoch(conn)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not curate memory {memory_id}: {exc}") from exc
    finally:
        conn.close()
    # Files are canonical (plan §7): keep the frontmatter in sync.
    if grade is not None or status is not None:
        _sync_file_metadata(home, row["body_path"], grade=new_grade, status=new_status)
    _safe_index(home, memory_id)  # derived index follows the canonical file
    return _row(home, memory_id) or {}


def list_memories(
    home: Path,
    scope: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    grade: str | None = None,
) -> list[dict]:
    """Memory rows, most recently updated first."""
    query = "SELECT * FROM memories WHERE 1=1"
    params: list[object] = []
    for field, value in (
        ("scope", scope),
        ("project_id", project_id),
        ("status", status),
        ("evidence_grade", grade),
    ):
        if value is not None:
            query += f" AND {field} = ?"
            params.append(value)
    query += " ORDER BY updated_at DESC, memory_id"
    conn = db.connect(_dbfile(home))
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def show_memory(home: Path, memory_id: str) -> dict:
    """The DB row (incl. stored evidence_grade), file path, and body."""
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    path = Path(home) / row["body_path"] if row["body_path"] else _v1_path(home, memory_id)
    if not path.exists():
        raise BrainError(f"Memory file missing for {memory_id!r}: {path}")
    body = path.read_text(encoding="utf-8")
    if not body.startswith("---\n") or "\n---" not in body:
        raise BrainError(f"Corrupt memory file {path}: missing frontmatter")
    return {"row": row, "path": str(path), "body": body}


def supersede(
    home: Path,
    memory_id: str,
    *,
    new_title: str | None = None,
    new_body: str,
    change_note: str,
    new_sources: list[dict] | None = None,
) -> int:
    """Create the next immutable version; every previous version is preserved."""
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    if not isinstance(new_body, str) or not new_body.strip():
        raise BrainError("new_body must be a non-empty string")
    if not isinstance(change_note, str) or not change_note.strip():
        raise BrainError("change_note must be a non-empty string")
    if new_title is not None and (not isinstance(new_title, str) or not new_title.strip()):
        raise BrainError("new_title must be a non-empty string or None")
    clean_sources = _validate_sources(new_sources)

    old_version = int(row["current_version"])
    title = new_title if new_title is not None else row["title"]
    new_path: Path | None = None
    wrote_file = False
    conn = db.connect(_dbfile(home))
    try:
        conn.execute("BEGIN IMMEDIATE")
        max_row = conn.execute(
            "SELECT MAX(version) AS max_version FROM memory_versions WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        max_history_version = int(max_row["max_version"] or 0) if max_row else 0
        new_version = max(old_version, max_history_version) + 1
        if old_version <= 1:
            retired_created_at = row["created_at"]
        else:
            retired = conn.execute(
                "SELECT created_at FROM memory_versions WHERE memory_id = ? AND version = ?",
                (memory_id, old_version),
            ).fetchone()
            retired_created_at = retired["created_at"] if retired is not None else row["created_at"]
        now = _utcnow()
        new_path = _version_path(home, memory_id, new_version)
        if new_path.exists():
            raise BrainError(f"Version path already exists for {memory_id} v{new_version}")
        content = _render_file(
            memory_id,
            title,
            row["scope"],
            row["project_id"],
            row["status"],
            row["evidence_grade"],
            new_version,
            row["created_at"],
            new_body,
        )
        _write_file_atomic(new_path, content)
        wrote_file = True

        conn.execute(
            "INSERT INTO memory_versions "
            "(memory_id, version, created_at, title, body_path, change_note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                old_version,
                retired_created_at,
                row["title"],
                row["body_path"],
                change_note,
            ),
        )
        conn.execute(
            "UPDATE memories SET title = ?, current_version = ?, updated_at = ?, "
            "body_path = ? WHERE memory_id = ?",
            (title, new_version, now, str(new_path.relative_to(home)), memory_id),
        )
        _insert_sources(conn, memory_id, clean_sources, now)
        db.bump_memory_epoch(conn)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if wrote_file and new_path is not None:
            with contextlib.suppress(OSError):
                new_path.unlink()
        if isinstance(exc, BrainError):
            raise
        if isinstance(exc, sqlite3.Error):
            raise BrainError(f"Could not supersede memory {memory_id}: {exc}") from exc
        raise
    finally:
        conn.close()
    _safe_index(home, memory_id)  # derived index follows the new version file
    return new_version


def revert_supersede(
    home: Path | str,
    memory_id: str,
    *,
    target_version: int | None = None,
    session_id: str | None = None,
) -> int:
    """Revert a memory's active version to a prior version without deleting history."""
    from . import reconsolidation

    return reconsolidation.revert_supersede(
        home, memory_id, target_version=target_version, session_id=session_id
    )


def history(home: Path, memory_id: str) -> list[dict]:
    """All versions (oldest first) with paths and change notes."""
    row = _row(home, memory_id)
    if row is None:
        raise BrainError(f"Unknown memory {memory_id!r}")
    conn = db.connect(_dbfile(home))
    try:
        versions = [
            dict(r)
            for r in conn.execute(
                "SELECT memory_id, version, created_at, title, body_path, change_note "
                "FROM memory_versions WHERE memory_id = ? ORDER BY version",
                (memory_id,),
            ).fetchall()
        ]
    finally:
        conn.close()
    current = {
        "memory_id": memory_id,
        "version": row["current_version"],
        "created_at": row["updated_at"],
        "title": row["title"],
        "body_path": row["body_path"],
        "change_note": None,  # the current version has no change note
    }
    versions.append(current)
    return versions


def contradictions(home: Path, scope: str = "project") -> list[dict]:
    """Same-title (case-insensitive) memories with different body hashes where
    neither side is REJECTED/ARCHIVED. Deterministic pair order."""
    by_title: dict[str, list[dict]] = {}
    for row in list_memories(home, scope=scope):
        key = row["title"].strip().lower()
        if row["evidence_grade"] == "REJECTED" or row["status"] == "archived":
            continue
        by_title.setdefault(key, []).append(row)
    pairs: list[dict] = []
    for title, entries in sorted(by_title.items()):
        entries.sort(key=lambda r: r["memory_id"])
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                hash_a = _body_hash(home, a)
                hash_b = _body_hash(home, b)
                if hash_a is None or hash_b is None:
                    continue
                if hash_a != hash_b:
                    pairs.append(
                        {
                            "title": title,
                            "memory_id_a": a["memory_id"],
                            "memory_id_b": b["memory_id"],
                        }
                    )
    return pairs


def _body_hash(home: Path, row: dict) -> str | None:
    """Hash only the body (frontmatter carries per-file timestamps, so the
    whole-file hash would differ even for identical bodies)."""
    path = Path(home) / row["body_path"] if row["body_path"] else _v1_path(home, row["memory_id"])
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if content.startswith("---\n") and "\n---" in content:
        content = content.split("\n---", 1)[1]
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_DEDUPE_STATUS_RANK = {"current": 4, "labile": 3, "candidate": 2, "archived": 1, "superseded": 0}
_DEDUPE_GRADE_RANK = {
    "VERIFIED": 4,
    "TESTED": 3,
    "OBSERVED": 2,
    "INFERRED": 1,
    "HISTORICAL": 0,
    "REJECTED": -1,
}
_BODY_SIMILARITY_THRESHOLD = 0.8
# Bodies shorter than this are too small for reliable similarity; title
# equality remains the primary family signal.
_BODY_MIN_TOKENS = 6


def _norm_title(title: str) -> str:
    """Deterministic family key: lowercase alphanumeric runs joined by spaces."""
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))


def _body_tokens(body: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (body or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _same_fact(row_a: dict, row_b: dict) -> bool:
    """Phase 8 family link: same normalized title OR near-identical bodies.

    Deterministic and file-free (the FTS hot path must not read canonical
    files). Exact-body copies are covered by a Jaccard of 1.0.
    """
    title_a, title_b = _norm_title(row_a.get("title") or ""), _norm_title(row_b.get("title") or "")
    if title_a and title_a == title_b:
        return True
    body_a = _body_tokens(_body_text_for_dedupe(row_a))
    body_b = _body_tokens(_body_text_for_dedupe(row_b))
    if len(body_a) < _BODY_MIN_TOKENS or len(body_b) < _BODY_MIN_TOKENS:
        return False
    return _jaccard(body_a, body_b) >= _BODY_SIMILARITY_THRESHOLD


def _body_text_for_dedupe(row: dict) -> str:
    """Body text attached by the search paths (FTS: f.body AS _body, file-free;
    linear: the already-read file body). '' when unavailable."""
    return str(row.get("_body") or row.get("body") or "")


def _dedupe_representative_key(row: dict) -> tuple:
    """Canonical-first representative: highest current_version, then status
    (current > labile > candidate > archived > superseded), then newest
    updated_at, then highest evidence grade, then memory_id (deterministic).
    """
    status_key = str(row.get("status") or "")
    grade_key = effective_evidence_grade(row)
    return (
        row.get("current_version") or 1,
        _DEDUPE_STATUS_RANK.get(status_key, 0),
        row.get("updated_at") or "",
        _DEDUPE_GRADE_RANK.get(grade_key, 0),
        row.get("memory_id") or "",
    )


_DEDUPE_BODY_SCAN_LIMIT = 200


def _dedupe_family(members: list[dict]) -> list[dict]:
    """Union-find over `members`; one representative per same-fact component.

    Deterministic and bounded: family features (normalized title, body token
    set) are computed ONCE per row; title-equality families are formed in
    O(n); the pairwise body-Jaccard scan (O(n^2)) only runs when the result
    set is small (<= _DEDUPE_BODY_SCAN_LIMIT) so hot-path latency stays
    bounded for broad queries (documented work guard).
    """
    if len(members) <= 1:
        return list(members)
    n = len(members)
    parent = list(range(n))
    titles = [_norm_title(m.get("title") or "") for m in members]
    tokens = [_body_tokens(_body_text_for_dedupe(m)) for m in members]

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    by_title: dict[str, list[int]] = {}
    for i, title in enumerate(titles):
        if title:
            by_title.setdefault(title, []).append(i)
    for group in by_title.values():
        for i in group[1:]:
            union(group[0], i)

    if n <= _DEDUPE_BODY_SCAN_LIMIT:
        for i in range(n):
            for j in range(i + 1, n):
                ti, tj = tokens[i], tokens[j]
                if (
                    len(ti) >= _BODY_MIN_TOKENS
                    and len(tj) >= _BODY_MIN_TOKENS
                    and _jaccard(ti, tj) >= _BODY_SIMILARITY_THRESHOLD
                ):
                    union(i, j)

    components: dict[int, list[dict]] = {}
    for i, row in enumerate(members):
        components.setdefault(find(i), []).append(row)
    return [max(comp, key=_dedupe_representative_key) for comp in components.values()]


def _dedupe_rows(
    rows: list[dict], *, project_id: str | None, include_duplicates: bool
) -> list[dict]:
    """Phase 8: post-filter, pre-budget dedupe (shared by FTS + fallback).

    Families: supersede/near-duplicate groups via `_same_fact`. Scope rule:
    when a project context is supplied, global/domain-scope rows are treated
    as a DISTINCT bucket (comparison may be required); otherwise everything
    dedupes by family. `include_duplicates=True` returns all rows untouched
    (comparison-required exception). Representatives keep their original
    rank order.
    """
    if include_duplicates or len(rows) <= 1:
        return list(rows)

    def bucket(row: dict) -> str:
        if project_id is not None and row.get("scope") in ("global", "domain"):
            return "other"
        return "same"

    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(bucket(row), []).append(row)
    out: list[dict] = []
    for members in buckets.values():
        out.extend(_dedupe_family(members))
    rank = {id(row): i for i, row in enumerate(rows)}
    out.sort(key=lambda row: rank[id(row)])
    return out


# ---------------------------------------------------------------------------
# Phase 9 deterministic ranking (plan §PHASE 9)
#
#   score = relevance * trust * scope_match * freshness
#           * decision_value * negative_transfer_factor
#           - token_cost_penalty
#
# All terms are bounded so no single term can zero or explode the score.
# Weights are HARDCODED constants (TODO Phase 12: wire config/retrieval.toml;
# not wired yet by design). No model calls, no embeddings. The scorer is
# shared verbatim by the FTS path and the linear fallback.
# ---------------------------------------------------------------------------
_SCORE_TERMS = frozenset({"trust", "scope", "freshness", "decision", "negative", "token"})
_GRADE_SCORE = {
    "VERIFIED": 1.0,
    "TESTED": 0.9,
    "OBSERVED": 0.8,
    "INFERRED": 0.7,
    "HISTORICAL": 0.6,
    "REJECTED": 0.5,
}
_STATUS_SCORE = {
    "current": 1.0,
    "labile": 0.95,
    "candidate": 0.9,
    "archived": 0.8,
    "superseded": 0.8,
}
_TITLE_BOOST_EXACT = 0.15
_TITLE_BOOST_PARTIAL = 0.05
_RELEVANCE_CAP = 1.25
_FRESHNESS_HALFLIFE_DAYS = 180.0
_FRESHNESS_MAX_PENALTY = 0.2
_DECISION_BOOST_PER_HIT = 0.1
_DECISION_BOOST_CAP = 0.5
_NEGATIVE_PENALTY_PER_CONTRADICTION = 0.1
_NEGATIVE_PENALTY_CAP = 0.3
_TOKEN_FREE_LIMIT = 400
_TOKEN_PENALTY_CAP = 0.25
_TOKEN_PENALTY_SATURATION = 2000


def _score_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _query_tokens(term: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", term.lower()))


_BM25_RELEVANCE_SCALE = 10.0

# ---------------------------------------------------------------------------
# Phase 11/12 — retrieval budget + config wiring
# ---------------------------------------------------------------------------

# Context-size assumption (tokens) for the retrieval budget ceiling. The plan
# wires this from config later; the ceiling itself is
# `reserve.retrieved_memory_pct_max` percent of this window.
_CONTEXT_WINDOW_TOKENS = 200_000

# Plan default: 1-3 retrieved memories. Configurable via
# config/retrieval.toml [scoring].max_results (Phase 12).
_DEFAULT_TOP_K = 3


@dataclass(frozen=True)
class RetrievalWeights:
    """Phase 12: every hardcoded weight consumed by `_score_row` and its
    helpers, overridable from config/retrieval.toml [scoring.weights].
    Absent/invalid keys keep the hardcoded defaults (behavior unchanged)."""

    title_boost_exact: float = _TITLE_BOOST_EXACT
    title_boost_partial: float = _TITLE_BOOST_PARTIAL
    relevance_cap: float = _RELEVANCE_CAP
    bm25_relevance_scale: float = _BM25_RELEVANCE_SCALE
    grade_scores: dict[str, float] = _field(default_factory=lambda: dict(_GRADE_SCORE))
    status_scores: dict[str, float] = _field(default_factory=lambda: dict(_STATUS_SCORE))
    freshness_half_life_days: float = _FRESHNESS_HALFLIFE_DAYS
    freshness_max_penalty: float = _FRESHNESS_MAX_PENALTY
    decision_boost_per_hit: float = _DECISION_BOOST_PER_HIT
    decision_boost_cap: float = _DECISION_BOOST_CAP
    negative_penalty_per_contradiction: float = _NEGATIVE_PENALTY_PER_CONTRADICTION
    negative_penalty_cap: float = _NEGATIVE_PENALTY_CAP
    token_free_limit: int = _TOKEN_FREE_LIMIT
    token_penalty_cap: float = _TOKEN_PENALTY_CAP
    token_penalty_saturation: int = _TOKEN_PENALTY_SATURATION


@dataclass(frozen=True)
class RetrievalGate:
    """Abstention thresholds and rollout policy for ranked retrieval."""

    abs_floor: float = 0.55
    gap_min: float = 0.08
    rollout: str = "SHADOW"
    lane_floors: dict[str, float] = _field(
        default_factory=lambda: {
            "policy": 0.80,
            "active_state": 0.55,
            "semantic": 0.55,
            "repo": 0.55,
            "decision": 0.55,
            "skill": 0.55,
        }
    )
    config_version: str = "1"


@dataclass(frozen=True)
class RetrievalConfig:
    """Effective retrieval policy for one search: result cap, token budget,
    scoring weights, and abstention gate."""

    top_k: int = _DEFAULT_TOP_K
    max_tokens: int | None = None
    weights: RetrievalWeights = _field(default_factory=RetrievalWeights)
    gate: RetrievalGate = _field(default_factory=RetrievalGate)


_DEFAULT_RETRIEVAL_CONFIG = RetrievalConfig()


def _coerce_float(value: object, fallback: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    result = float(value)
    return result if math.isfinite(result) else fallback


def _coerce_int(value: object, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value


def _coerce_scores(value: object, fallback: dict[str, float]) -> dict[str, float]:
    if not isinstance(value, dict):
        return dict(fallback)
    out = dict(fallback)
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, (int, float)) and not isinstance(item, bool):
            score = float(item)
            if math.isfinite(score):
                out[key] = score
    return out


def load_retrieval_config(home: Path) -> RetrievalConfig:
    """Read retrieval limits, scoring weights, and the abstention gate."""
    weights = RetrievalWeights()
    gate = RetrievalGate()
    top_k = _DEFAULT_TOP_K
    budget_pct: float | None = None

    rpath = Path(home) / "config" / "retrieval.toml"
    if rpath.is_file():
        try:
            raw = tomllib.loads(rpath.read_text(encoding="utf-8"))
            version = str(raw.get("schema_version", gate.config_version))
            scoring = raw.get("scoring") or {}
            if isinstance(scoring, dict):
                raw_k = scoring.get("max_results")
                if isinstance(raw_k, int) and not isinstance(raw_k, bool) and raw_k > 0:
                    top_k = raw_k
                w = scoring.get("weights")
                if isinstance(w, dict):

                    def _f(key: str, fallback: float) -> float:
                        value = _coerce_float(w.get(key), fallback)
                        if key == "freshness_half_life_days" and value <= 0:
                            return fallback
                        return value

                    token_free_limit = _coerce_int(
                        w.get("token_free_limit"), weights.token_free_limit
                    )
                    token_saturation = _coerce_int(
                        w.get("token_penalty_saturation"), weights.token_penalty_saturation
                    )
                    if token_free_limit <= 0 or token_saturation <= token_free_limit:
                        token_free_limit = weights.token_free_limit
                        token_saturation = weights.token_penalty_saturation

                    weights = RetrievalWeights(
                        title_boost_exact=_f("title_boost_exact", weights.title_boost_exact),
                        title_boost_partial=_f("title_boost_partial", weights.title_boost_partial),
                        relevance_cap=_f("relevance_cap", weights.relevance_cap),
                        bm25_relevance_scale=_f(
                            "bm25_relevance_scale", weights.bm25_relevance_scale
                        ),
                        grade_scores=_coerce_scores(w.get("grade_scores"), weights.grade_scores),
                        status_scores=_coerce_scores(w.get("status_scores"), weights.status_scores),
                        freshness_half_life_days=_f(
                            "freshness_half_life_days", weights.freshness_half_life_days
                        ),
                        freshness_max_penalty=_f(
                            "freshness_max_penalty", weights.freshness_max_penalty
                        ),
                        decision_boost_per_hit=_f(
                            "decision_boost_per_hit", weights.decision_boost_per_hit
                        ),
                        decision_boost_cap=_f("decision_boost_cap", weights.decision_boost_cap),
                        negative_penalty_per_contradiction=_f(
                            "negative_penalty_per_contradiction",
                            weights.negative_penalty_per_contradiction,
                        ),
                        negative_penalty_cap=_f(
                            "negative_penalty_cap", weights.negative_penalty_cap
                        ),
                        token_free_limit=token_free_limit,
                        token_penalty_cap=_f("token_penalty_cap", weights.token_penalty_cap),
                        token_penalty_saturation=token_saturation,
                    )
            raw_gate = raw.get("gate") or {}
            if isinstance(raw_gate, dict):
                metadata = raw_gate.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = raw_gate
                calibrated = all(
                    isinstance(metadata.get(key), str) and metadata[key].strip()
                    for key in ("source", "reason", "version", "effective")
                )
                abs_floor = _coerce_float(raw_gate.get("abs_floor"), gate.abs_floor)
                gap_min = _coerce_float(raw_gate.get("gap_min"), gate.gap_min)
                if not calibrated:
                    abs_floor, gap_min = gate.abs_floor, gate.gap_min
                else:
                    if not 0.0 <= abs_floor <= 1.0:
                        abs_floor = gate.abs_floor
                    if not 0.0 <= gap_min <= 1.0:
                        gap_min = gate.gap_min
                floors = dict(gate.lane_floors)
                raw_floors = raw_gate.get("lane_floors")
                if isinstance(raw_floors, dict):
                    for lane, floor in raw_floors.items():
                        if (
                            lane in floors
                            and isinstance(floor, (int, float))
                            and not isinstance(floor, bool)
                        ) and 0.0 <= float(floor) <= 1.0:
                            floors[lane] = float(floor)
                rollout = raw_gate.get("rollout", gate.rollout)
                if rollout not in {"OFF", "SHADOW", "ADVISORY", "CANARY", "ACTIVE"}:
                    rollout = gate.rollout
                gate = RetrievalGate(
                    abs_floor=abs_floor,
                    gap_min=gap_min,
                    rollout=rollout,
                    lane_floors=floors,
                    config_version=version,
                )
        except (OSError, tomllib.TOMLDecodeError):
            pass  # fail open: unreadable config keeps defaults

    cpath = Path(home) / "config" / "context.toml"
    if cpath.is_file():
        try:
            reserve = tomllib.loads(cpath.read_text(encoding="utf-8")).get("reserve") or {}
            pct = reserve.get("retrieved_memory_pct_max")
            if isinstance(pct, (int, float)) and not isinstance(pct, bool) and 0 <= pct <= 100:
                budget_pct = float(pct)
        except (OSError, tomllib.TOMLDecodeError):
            pass

    max_tokens = (
        round(budget_pct / 100.0 * _CONTEXT_WINDOW_TOKENS) if budget_pct is not None else None
    )
    return RetrievalConfig(top_k=top_k, max_tokens=max_tokens, weights=weights, gate=gate)


def _estimate_retrieval_tokens(row: dict, home: Path | str | None = None) -> int:
    return estimate_tokens(_body_text_for_dedupe(row), home=home)


def _apply_budget(
    rows: list[dict], top_k: int | None, max_tokens: int | None, home: Path | str | None = None
) -> list[dict]:
    """Phase 11: cap the ranked result set. `top_k` keeps only the N
    highest-value rows; `max_tokens` trims the LOWEST-value rows (ranked
    best-first, so the tail is dropped) while always keeping at least the
    best row. Deterministic; never reorders."""
    if top_k is not None and top_k > 0:
        rows = rows[:top_k]
    if max_tokens is None:
        return rows
    if max_tokens <= 0:
        return rows[:1]  # zero ceiling: only the best row may be returned
    kept: list[dict] = []
    total = 0
    for row in rows:
        cost = _estimate_retrieval_tokens(row, home=home)
        if kept and total + cost > max_tokens:
            continue
        kept.append(row)
        total += cost
    return kept


def _contradiction_map(rows: list[dict]) -> dict[str, set[str]]:
    """Phase 10: conflict pairs among the PRE-dedupe candidates. Same-title
    (case-insensitive) rows with different body text conflict. Mirrors the
    quality rule of `contradictions()`: REJECTED/archived sides never
    conflict. File-free (uses the _body attached by the search paths); a row
    with unavailable body text cannot be a conflict side. Returns
    {memory_id: {conflicting memory_ids}} — computed BEFORE dedupe so the
    marker survives family collapse (dedupe must not silently pick one)."""
    by_title: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("evidence_grade") == "REJECTED" or row.get("status") == "archived":
            continue
        key = str(row.get("title") or "").strip().lower()
        if key:
            by_title.setdefault(key, []).append(row)
    conflicts: dict[str, set[str]] = {}
    for entries in by_title.values():
        entries.sort(key=lambda r: str(r.get("memory_id") or ""))
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                body_a = _body_text_for_dedupe(a).strip()
                body_b = _body_text_for_dedupe(b).strip()
                if body_a and body_b and body_a != body_b:
                    conflicts.setdefault(a["memory_id"], set()).add(b["memory_id"])
                    conflicts.setdefault(b["memory_id"], set()).add(a["memory_id"])
    return conflicts


def _attach_contradictions(rows: list[dict], conflicts: dict[str, set[str]]) -> list[dict]:
    """Attach deterministic `contradiction_with` markers (sorted ids) to the
    returned rows from a pre-dedupe conflict map. Rows trimmed by the budget
    or collapsed by dedupe keep their markers on the surviving row."""
    for row in rows:
        ids = conflicts.get(str(row.get("memory_id") or ""))
        if ids:
            row["contradiction_with"] = sorted(ids)
    return rows


def _relevance_score(
    row: dict, query_tokens: set[str], bm25_best: float | None, weights: RetrievalWeights
) -> float:
    """FTS path: raw bm25 normalized exponentially against the best match in
    the result set. SQLite's bm25 ranks lower (more-negative) values first,
    so the reference must be the minimum raw value and the penalty grows as
    a row moves above that best value.

    Linear path: token-overlap ratio. Title/body boosts are small and
    deterministic. Bounded [0, _RELEVANCE_CAP]."""
    title_tokens = _score_tokens(row.get("title") or "")
    body_tokens = _score_tokens(_body_text_for_dedupe(row))
    raw = row.get("_bm25")
    scale = weights.bm25_relevance_scale
    if (
        isinstance(scale, bool)
        or not isinstance(scale, (int, float))
        or not math.isfinite(float(scale))
        or scale <= 0
    ):
        scale = _BM25_RELEVANCE_SCALE
    if (
        bm25_best is not None
        and isinstance(raw, (int, float))
        and not isinstance(raw, bool)
        and math.isfinite(float(raw))
    ):
        base = math.exp(-(float(raw) - bm25_best) / scale)
    elif not query_tokens:
        base = 1.0
    else:
        hay = title_tokens | body_tokens | _score_tokens(row.get("summary") or "")
        base = len(query_tokens & hay) / len(query_tokens)
    in_title = query_tokens & title_tokens
    if query_tokens and in_title == query_tokens:
        base += weights.title_boost_exact
    elif len(in_title) >= max(1, len(query_tokens) // 2):
        base += weights.title_boost_partial
    return min(weights.relevance_cap, base)


def _trust_score(row: dict, weights: RetrievalWeights) -> float:
    """Evidence grade * status, both bounded; REJECTED/superseded rows are
    normally filtered before ranking."""
    return weights.grade_scores.get(effective_evidence_grade(row), 0.8) * (
        weights.status_scores.get(str(row.get("status") or ""), 0.9)
    )


def _scope_match_score(row: dict, project_id: str | None) -> float:
    """Exact project match > global/domain when a project context is given;
    neutral otherwise."""
    if project_id is None:
        return 1.0
    return 0.9 if row.get("scope") in ("global", "domain") else 1.0


def _freshness_score(updated_at: object, weights: RetrievalWeights) -> float:
    """Gentle linear decay 1.0 -> 0.8 over 180 days; never below 0.8 so a
    stale-but-right memory stays findable (relevance dominates)."""
    try:
        dt = datetime.fromisoformat(str(updated_at))
        days = max(0.0, (datetime.now(UTC) - dt).total_seconds() / 86400.0)
    except (TypeError, ValueError):
        return 0.9
    return 1.0 - weights.freshness_max_penalty * min(1.0, days / weights.freshness_half_life_days)


def _decision_value_score(row: dict, weights: RetrievalWeights) -> float:
    """Memories that resolved past decisions (successful retrievals) rank
    higher. Bounded by decision_boost_cap."""
    hits = int(row.get("successful_retrieval_count") or 0)
    cap_hits = (
        int(weights.decision_boost_cap / weights.decision_boost_per_hit)
        if weights.decision_boost_per_hit > 0
        else 0
    )
    return 1.0 + weights.decision_boost_per_hit * min(hits, max(1, cap_hits))


def _negative_transfer_score(row: dict, weights: RetrievalWeights) -> float:
    """Contradicted memories are a negative-transfer risk. Bounded by
    negative_penalty_cap."""
    contradictions = int(row.get("contradiction_count") or 0)
    cap_count = (
        int(weights.negative_penalty_cap / weights.negative_penalty_per_contradiction)
        if weights.negative_penalty_per_contradiction > 0
        else 0
    )
    return 1.0 - weights.negative_penalty_per_contradiction * min(contradictions, max(1, cap_count))


def _token_cost_penalty(
    row: dict, weights: RetrievalWeights, home: Path | str | None = None
) -> float:
    """Gentle log-shaped per-token ROI penalty on very long bodies; never
    zeroes the score (max token_penalty_cap subtracted)."""
    n = estimate_tokens(_body_text_for_dedupe(row), home=home)
    if n <= weights.token_free_limit:
        return 0.0
    return weights.token_penalty_cap * min(
        1.0,
        math.log2(n / weights.token_free_limit)
        / math.log2(weights.token_penalty_saturation / weights.token_free_limit),
    )


def _score_row(
    row: dict,
    query_tokens: set[str],
    bm25_best: float | None,
    project_id: str | None,
    score_terms: frozenset[str],
    weights: RetrievalWeights | None = None,
    home: Path | str | None = None,
) -> float:
    w = weights if weights is not None else _DEFAULT_RETRIEVAL_CONFIG.weights
    score = _relevance_score(row, query_tokens, bm25_best, w)
    row["_relevance"] = score
    if "trust" in score_terms:
        score *= _trust_score(row, w)
    if "scope" in score_terms:
        score *= _scope_match_score(row, project_id)
    if "decision" in score_terms:
        score *= _decision_value_score(row, w)
    if "freshness" in score_terms or "decision" in score_terms:
        p_need = row.get("_p_need")
        if p_need is None and home is not None:
            try:
                from . import reconsolidation

                b = reconsolidation.compute_base_level_activation(
                    Path(home), row.get("memory_id", "")
                )
                p_need = 0.5 if b <= -10.0 else reconsolidation.p_need_from_activation(b)
            except Exception:
                p_need = 0.5
        if p_need is None:
            p_need = 0.5
        row["_p_need"] = float(p_need)
        score *= 0.5 + float(p_need)
    if "negative" in score_terms:
        score *= _negative_transfer_score(row, w)
    if "token" in score_terms:
        score -= _token_cost_penalty(row, w, home=home)
    return score


def _rank_rows(
    rows: list[dict],
    term: str,
    *,
    project_id: str | None,
    score_terms: frozenset[str],
    weights: RetrievalWeights | None = None,
    home: Path | str | None = None,
) -> list[dict]:
    query_tokens = _query_tokens(term)
    bm25_values = [r.get("_bm25") for r in rows]
    # SQLite FTS5's bm25() is ordered ascending: the strongest match is the
    # most-negative value, not the numerically largest value.
    bm25_best = (
        min(float(v) for v in bm25_values if v is not None)
        if any(v is not None for v in bm25_values)
        else None
    )
    w = weights if weights is not None else _DEFAULT_RETRIEVAL_CONFIG.weights
    if home is not None and ("freshness" in score_terms or "decision" in score_terms):
        from . import reconsolidation

        # One connection for every row's activation history instead of one per row.
        pending = [str(r.get("memory_id") or "") for r in rows if r.get("_p_need") is None]
        try:
            activations = reconsolidation.base_level_activations(Path(home), pending)
        except Exception:
            activations = {}
        for r in rows:
            b = activations.get(str(r.get("memory_id") or ""))
            if r.get("_p_need") is None and b is not None:
                r["_p_need"] = 0.5 if b <= -10.0 else reconsolidation.p_need_from_activation(b)
    scored = []
    for index, row in enumerate(rows):
        row["_bm25"] = row.get("_bm25")
        row["_score"] = _score_row(
            row, query_tokens, bm25_best, project_id, score_terms, w, home=home
        )
        scored.append((row, index))
    scored.sort(key=lambda item: (-item[0]["_score"], item[1], item[0].get("memory_id") or ""))
    return [item[0] for item in scored]


def search_memories(
    home: Path,
    term: str,
    *,
    project_id: str | None = None,
    include_history: bool = False,
    include_duplicates: bool = False,
    score_terms: frozenset[str] | None = None,
    top_k: int | None = None,
    max_tokens: int | None = None,
    history_omissions: list[dict] | None = None,
) -> list[dict]:
    """Search semantic memories (plan Phase 6 + Phase 7 hard filters).

    An optional bounded diagnostic sink receives withheld history identities
    from this same search, before active ranking, contradictions, or budgets.

    Primary path: SQLite FTS5 (word/prefix tokens, bm25-ranked) over the
    derived memory_fts index. Falls back to the previous linear Markdown
    substring scan when FTS5 is unavailable or the index has not been built
    (missing/empty memory_fts) — fail open, never error. Both paths apply
    the SAME hard filters (Phase 7).

    Phase 7 hard filters (applied BEFORE ranking, as SQL WHERE on the FTS
    path / shared predicate on the fallback path):
      - evidence grade REJECTED: always excluded (rejected != historical).
      - status archived: excluded unless `include_history`.
      - status superseded: excluded unless `include_history` (review N1: ALL
        superseded rows are excluded by default; memory_versions already
        preserves version history, so no carve-out is needed).
      - project_id given: only memories of that project (global/None keeps
        everything).

    Phase 10 (contradiction surfacing): returned rows that share a title with
    a different-body result row carry `contradiction_with: [memory_id, ...]`.

    Phase 11 (retrieval budget): after ranking, the result set is capped to
    `top_k` rows and trimmed to the `max_tokens` token ceiling (lowest-value
    rows dropped first; at least the best row is kept).

    Phase 12 (config wiring): `top_k`/`max_tokens`/scoring weights default to
    config/retrieval.toml ([scoring].max_results, [scoring.weights]) and
    config/context.toml ([reserve].retrieved_memory_pct_max as a percent of
    the _CONTEXT_WINDOW_TOKENS assumption); explicit arguments override the
    config; absent/invalid config falls back to hardcoded defaults.

    Known divergence: FTS5 matches word prefixes, so a substring in the
    middle of a word (e.g. "arc" inside "sidecar") matches the linear
    scan but not FTS5.
    """
    if not isinstance(term, str) or not term.strip():
        raise BrainError("term must be a non-empty string")
    terms = score_terms if score_terms is not None else _SCORE_TERMS
    cfg = load_retrieval_config(home)
    eff_top_k = top_k if top_k is not None else cfg.top_k
    eff_max_tokens = max_tokens if max_tokens is not None else cfg.max_tokens
    _ensure_migrated(home)
    conn = db.connect(_dbfile(home))
    try:
        if _fts_available(conn):
            plan = _plan_with_stats(term, conn=conn)
            total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            indexed = _fts_count(conn)
            if plan.expression is not None and (indexed > 0 or total == 0):
                return _search_fts(
                    conn,
                    plan.expression,
                    term,
                    query_terms=plan.terms,
                    msm_required=plan.required,
                    project_id=project_id,
                    include_history=include_history,
                    include_duplicates=include_duplicates,
                    score_terms=terms,
                    weights=cfg.weights,
                    top_k=eff_top_k,
                    max_tokens=eff_max_tokens,
                    home=home,
                    history_omissions=history_omissions,
                )
            # Empty/small/non-ASCII queries and an unbuilt index use the
            # existing linear fallback.
    except sqlite3.Error:
        pass  # FTS path broken for any reason -> linear fallback below
    finally:
        conn.close()
    return _search_linear(
        home,
        term,
        project_id=project_id,
        include_history=include_history,
        include_duplicates=include_duplicates,
        score_terms=terms,
        weights=cfg.weights,
        top_k=eff_top_k,
        max_tokens=eff_max_tokens,
        history_omissions=history_omissions,
    )


def _filter_sql(project_id: str | None, include_history: bool) -> tuple[str, list[object]]:
    """Phase 7 hard-filter WHERE clause (shared by the FTS query).

    Cheap SQL: no post-hoc python filtering of the result set.
    """
    clauses = ["m.evidence_grade != 'REJECTED'"]
    params: list[object] = []
    if not include_history:
        # archived + superseded excluded outright (review N1); memory_versions
        # preserves history, so no superseded row is kept by default
        clauses.append("m.status NOT IN ('archived', 'superseded')")
    if project_id is not None:
        clauses.append(
            "(m.project_id = ? OR m.scope = 'global' OR "
            "(m.scope = 'domain' AND "
            "(m.project_id IS NULL OR lower(trim(m.project_id)) IN ('', 'default', 'unknown'))))"
        )
        params.append(project_id)
    return " AND ".join(clauses), params


def _project_matches(row: dict, project_id: str | None) -> bool:
    if project_id is None:
        return True
    raw_project = row.get("project_id")
    sentinel = str(raw_project or "").strip().lower()
    return bool(
        raw_project == project_id
        or row.get("scope") == "global"
        or (row.get("scope") == "domain" and sentinel in {"", "default", "unknown"})
    )


def _row_passes_filters(row: dict, *, project_id: str | None, include_history: bool) -> bool:
    """Same Phase 7 filter semantics for the linear fallback path."""
    if row.get("evidence_grade") == "REJECTED":
        return False
    status = row.get("status")
    if status in ("archived", "superseded") and not include_history:
        return False
    return _project_matches(row, project_id)


_HISTORY_OMISSION_LIMIT = 256


def _history_omission(row: dict) -> dict:
    status = row.get("status")
    return {
        "memory_id": row.get("memory_id"),
        "status": status,
        "reason": "ARCHIVED_HISTORY" if status == "archived" else "SUPERSEDED_HISTORY",
    }


def _partition_history(
    rows: list[dict], include_history: bool, omissions: list[dict] | None
) -> list[dict]:
    if include_history or omissions is None:
        return rows
    active = []
    for row in rows:
        if row.get("status") not in {"archived", "superseded"}:
            active.append(row)
        elif len(omissions) < _HISTORY_OMISSION_LIMIT - 1:
            omissions.append(_history_omission(row))
        elif omissions and omissions[-1].get("reason") == "HISTORY_DIAGNOSTICS_TRUNCATED":
            omissions[-1]["truncated_count"] += 1
        else:
            omissions.append({"reason": "HISTORY_DIAGNOSTICS_TRUNCATED", "truncated_count": 1})
    return active


def _search_fts(
    conn: sqlite3.Connection,
    match_expr: str,
    term: str,
    query_terms: tuple[str, ...] = (),
    msm_required: int | None = None,
    *,
    project_id: str | None = None,
    include_history: bool = False,
    include_duplicates: bool = False,
    score_terms: frozenset[str] = _SCORE_TERMS,
    weights: RetrievalWeights | None = None,
    top_k: int | None = None,
    max_tokens: int | None = None,
    home: Path | str | None = None,
    history_omissions: list[dict] | None = None,
) -> list[dict]:
    """FTS5 query: quoted prefix tokens per word, hard filters (Phase 7),
    dedupe (Phase 8), then deterministic ranking (Phase 9) — post-filter,
    pre-budget.

    TODO(Phase 11): top_k / token budget trimming.
    """
    where, params = _filter_sql(project_id, include_history or history_omissions is not None)
    # _body is always selected: Phase 8 dedupe and Phase 10 contradiction
    # surfacing both need the clean body text (comparison path included).
    rows = conn.execute(
        "SELECT m.*, f.body AS _body, bm25(memory_fts) AS _bm25, "
        "i.file_hash AS _indexed_file_hash FROM memory_fts f "
        "JOIN memories m ON m.memory_id = f.memory_id "
        "JOIN memory_index i ON i.memory_id = m.memory_id "
        "AND i.current_version = m.current_version "
        f"WHERE memory_fts MATCH ? AND {where} ORDER BY bm25(memory_fts), m.memory_id",
        [match_expr, *params],
    ).fetchall()
    current_rows = []
    canonical_home = Path(home) if home is not None else None
    for indexed in rows:
        row = dict(indexed)
        indexed_hash = row.pop("_indexed_file_hash")
        if canonical_home is None or (
            file_hash_matches(indexed_hash, canonical_home, row)
        ):
            row["file_hash"] = indexed_hash
            current_rows.append(row)
    rows = current_rows
    if query_terms:
        required = msm_required if msm_required is not None else math.ceil(0.5 * len(query_terms))
        rows = [row for row in rows if _query_term_hits(row, query_terms) >= required]
    rows = _partition_history(rows, include_history, history_omissions)
    # Phase 10: conflict map BEFORE dedupe (family collapse must not hide a
    # conflicting sibling; the surviving row carries the marker).
    conflicts = _contradiction_map(rows)
    rows = _dedupe_rows(rows, project_id=project_id, include_duplicates=include_duplicates)
    # review N-D: only tokenize bodies for bounded result sets (the pairwise
    # body scan is already guarded; ranking falls back to title/summary
    # signals and zero token penalty for broad queries)
    if len(rows) > _DEDUPE_BODY_SCAN_LIMIT:
        for row in rows:
            row.pop("_body", None)
    ranked = _rank_rows(
        rows, term, project_id=project_id, score_terms=score_terms, weights=weights, home=home
    )
    return _attach_contradictions(_apply_budget(ranked, top_k, max_tokens, home=home), conflicts)


def _search_linear(
    home: Path,
    term: str,
    *,
    project_id: str | None = None,
    include_history: bool = False,
    include_duplicates: bool = False,
    score_terms: frozenset[str] = _SCORE_TERMS,
    weights: RetrievalWeights | None = None,
    top_k: int | None = None,
    max_tokens: int | None = None,
    history_omissions: list[dict] | None = None,
) -> list[dict]:
    """Previous linear Markdown scan — FALLBACK when FTS5/index unavailable.

    Applies the same Phase 7 filters, Phase 8 dedupe, and Phase 9 scoring
    (shared scorer) so the fallback cannot regress any of them.

    Matching is FTS-consistent: tokenizable queries match when EVERY query
    token is present (plain substring per token — keeps the documented
    middle-of-word divergence from FTS prefix matching). Queries with no
    tokenizable characters (symbols, non-ASCII) keep the legacy verbatim
    whole-string substring rule so punctuation searches still work.
    """
    needle = term.lower()
    query_tokens = _query_tokens(term)
    out = []
    for row in list_memories(home):
        if not _row_passes_filters(
            row,
            project_id=project_id,
            include_history=include_history or history_omissions is not None,
        ):
            continue
        title = (row.get("title") or "").lower()
        summary = (row.get("summary") or "").lower()
        # Clean body (frontmatter stripped) — identical input to the FTS
        # path's dedupe/scoring so the fallback cannot diverge (e.g. a
        # frontmatter-polluted Jaccard failing the family threshold).
        body = _body_text(home, row).lower()
        if query_tokens:
            hay = f"{title} {summary} {body}"
            if not all(token in hay for token in query_tokens):
                continue
        elif needle in title or needle in summary or needle in body:
            pass
        else:
            continue
        row = dict(row)
        row["_body"] = body
        if history_omissions is not None:
            row["file_hash"] = _file_hash(home, row)
        out.append(row)
    out = _partition_history(out, include_history, history_omissions)
    conflicts = _contradiction_map(out)
    rows = _dedupe_rows(out, project_id=project_id, include_duplicates=include_duplicates)
    ranked = _rank_rows(
        rows, term, project_id=project_id, score_terms=score_terms, weights=weights, home=home
    )
    return _attach_contradictions(_apply_budget(ranked, top_k, max_tokens, home=home), conflicts)
