"""Operator-facing recovery for worker attempts whose host never reported settlement.

Recovery works on the same authoritative ownership row that admission writes; it
never fabricates a settlement receipt, deletes a row, or rewrites the historical
outcome. The lifecycle protocol's release transition is reproduced here with the
same rule - ownership becomes ``released`` only when the executor is known to have
settled and cleanup is known to have completed - but the knowledge must come from
recorded evidence bound to *this* attempt and host generation:

* a live-host case supplies the host's own settlement observation (a missed
  receipt the callback token no longer authenticates), or
* a post-interruption case supplies a recorded quiescence attestation, which
  states how the resource was observed to be quiescent.

Lease expiry, a missing job row, a requested kill, and a bare unlock request are
never sufficient. Anything less keeps protection intact and returns the exact
unresolved condition with the supported next action.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .worker_protocol import _worker_db, reap  # same package: share the durable store

RECOVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS worker_recovery_events(
  event_id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL,
  host_generation TEXT,
  kind TEXT NOT NULL,
  resource TEXT,
  method TEXT,
  actor TEXT,
  payload_sha256 TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
)
"""

RELEASED = "released"


class RecoveryError(RuntimeError):
    """Raised when a recovery request is not supported by recorded evidence."""

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or {}


def _now(value: datetime | str | None = None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    if isinstance(value, str):
        return value
    return value.astimezone(UTC).isoformat()


def _db(home: Path | str | None) -> Path:
    return _worker_db(home if home is not None else Path.cwd())


def _connect(home: Path | str | None, *, write: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(_db(home))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute(RECOVERY_SCHEMA)
    if write:
        # Only short state transitions take the write lock: competing recovery
        # writers are excluded, and nothing external runs inside the transaction.
        conn.execute("BEGIN IMMEDIATE")
    return conn


def _rows(
    conn: sqlite3.Connection, *, project_id: str | None, task_id: str | None, attempt_id: str | None
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if task_id:
        clauses.append("task_id = ?")
        params.append(task_id)
    if attempt_id:
        clauses.append("attempt_id = ?")
        params.append(attempt_id)
    if not clauses:
        raise RecoveryError("SELECTOR_REQUIRED", "supply project_id, task_id or attempt_id")
    sql = "SELECT * FROM worker_tasks WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def unresolved_conditions(row: dict[str, Any], attestations: list[dict[str, Any]]) -> list[str]:
    """What still prevents release, in the order the release rule evaluates it."""
    conditions: list[str] = []
    if row.get("logical_outcome") in (None, "unresolved"):
        conditions.append("no accepted outcome recorded for this attempt")
    if not row.get("executor_settled"):
        conditions.append("executor settlement is not established by an authoritative receipt")
    if not row.get("cleanup_complete"):
        resources = sorted({a["resource"] for a in attestations if a.get("resource")})
        conditions.append(
            "cleanup completion is not established for: "
            + (", ".join(resources) if resources else "the attempt's owned resources")
        )
    return conditions


def _attestations(conn: sqlite3.Connection, attempt_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM worker_recovery_events WHERE attempt_id "
            "= ? AND kind = 'quiescence' ORDER BY recorded_at DESC",
            (attempt_id,),
        )
    ]


def inspect_attempt(
    home: Path | str | None = None,
    *,
    project_id: str | None = None,
    task_id: str | None = None,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    """Read-only view: ownership, binding, receipts and the exact unresolved condition."""
    with _connect(home) as conn:
        rows = _rows(conn, project_id=project_id, task_id=task_id, attempt_id=attempt_id)
        if not rows:
            raise RecoveryError("ATTEMPT_NOT_FOUND", "no worker attempt matches that selector")
        out = []
        for row in rows:
            attempt = row.get("attempt_id") or ""
            receipts = [
                dict(r)
                for r in conn.execute(
                    "SELECT sequence, receipt_sha256, recorded_at FROM worker_lifecycle_receipts "
                    "WHERE attempt_id = ? ORDER BY sequence",
                    (attempt,),
                )
            ]
            attestations = _attestations(conn, attempt)
            out.append(
                {
                    "task_id": row["task_id"],
                    "attempt_id": attempt,
                    "state": row.get("state"),
                    "writer_ownership": row.get("writer_ownership"),
                    "logical_outcome": row.get("logical_outcome"),
                    "executor_settled": bool(row.get("executor_settled")),
                    "cleanup_complete": bool(row.get("cleanup_complete")),
                    "lifecycle_sequence": row.get("lifecycle_sequence"),
                    "lease_expires_at": row.get("lease_expires_at"),
                    "binding": {
                        "project_id": row.get("project_id"),
                        "worktree_id": row.get("worktree_id"),
                        "host_session_id": row.get("host_session_id"),
                        "host_generation": row.get("host_generation"),
                        "native_attempt_id": row.get("native_attempt_id"),
                        "native_job_id": row.get("native_job_id"),
                        "agent_id": row.get("agent_id"),
                        "bound_at": row.get("bound_at"),
                    },
                    "receipts": receipts,
                    "quiescence_attestations": [
                        {
                            k: a[k]
                            for k in ("event_id", "resource", "method", "actor", "recorded_at")
                        }
                        for a in attestations
                    ],
                    "unresolved_conditions": unresolved_conditions(row, attestations),
                }
            )
        return {"attempts": out}


def _generation(value: object) -> int:
    """A known, non-negative host generation.

    Unknown is a distinct state, never a wildcard: ``None`` is rejected, a
    canonical numeric string is accepted for stored-schema compatibility, and a
    generation of ``0`` stays a legitimate generation. Truthiness is never used
    to decide whether a generation exists.
    """
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    raise RecoveryError("GENERATION_MISMATCH", "a known, non-negative host generation is required")


def _inventory_binding(row: dict[str, Any]) -> dict[str, Any]:
    """The identity a recovery decision is bound to: this exact execution."""
    binding = {
        key: row.get(key)
        for key in (
            "task_id",
            "attempt_id",
            "packet_sha256",
            "project_id",
            "worktree_id",
            "worktree_root",
            "host_session_id",
            "native_attempt_id",
            "native_job_id",
            "agent_id",
        )
    }
    binding["host_generation"] = _generation(row.get("host_generation"))
    return binding


def _interrupted_row(
    conn: sqlite3.Connection, attempt_id: str, host_generation: int
) -> dict[str, Any]:
    """The exact interrupted execution, or a refusal.

    The generation must come from the attempt's own recorded binding: a caller
    cannot substitute one, and two unknown generations are not a match.
    """
    generation = _generation(host_generation)
    rows = _rows(conn, project_id=None, task_id=None, attempt_id=attempt_id)
    if not rows:
        raise RecoveryError("ATTEMPT_NOT_FOUND", "no worker attempt matches that attempt id")
    row = rows[0]
    if _generation(row.get("host_generation")) != generation:
        raise RecoveryError(
            "GENERATION_MISMATCH",
            "the supplied generation does not match this attempt's recorded binding",
            detail={"recorded": row.get("host_generation"), "supplied": host_generation},
        )
    if row.get("access_intent") != "mutating":
        raise RecoveryError("BINDING_MISMATCH", "this is not a mutating ownership attempt")
    if (
        row.get("logical_outcome") not in (None, "unresolved")
        or int(row.get("executor_settled") or 0) != 0
        or int(row.get("cleanup_complete") or 0) != 0
        or int(row.get("lifecycle_sequence") or 0) != -1
        or row.get("state") not in ("SUBMITTED", "WORKING", "UNRESOLVED")
    ):
        raise RecoveryError(
            "USE_SETTLEMENT_RECONCILIATION",
            "interrupted release requires an attempt with no accepted outcome and no host receipt",
        )
    if row.get("writer_ownership") not in ("held", "quarantined", "released"):
        raise RecoveryError("BINDING_MISMATCH", "invalid writer ownership state")
    return row


def validate_census_observation(
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Prove an inspector's observation qualifies as a complete census.

    Separate from recording on purpose: the inspector says what was found, this
    proves the finding is complete, and the recorder persists it. Nothing here
    inspects the world, and completeness is never inferred from what happens to
    be present in the database.
    """
    resources = sorted({str(r).strip() for r in observation.get("resources", []) if str(r).strip()})
    if not resources:
        raise RecoveryError("INSUFFICIENT_EVIDENCE", "a census must name at least one resource")
    method = str(observation.get("method") or "").strip()
    evidence = str(observation.get("observation") or "").strip()
    if not method or not evidence:
        raise RecoveryError("INSUFFICIENT_EVIDENCE", "census method and observation are required")
    if observation.get("resources_complete") is not True:
        raise RecoveryError(
            "INSUFFICIENT_EVIDENCE",
            "a census without established completeness must not be recorded",
        )
    return {
        "attempt_id": str(observation.get("attempt_id") or ""),
        "host_generation": _generation(observation.get("host_generation")),
        "resources": resources,
        "resources_complete": True,
        "method": method,
        "observation": evidence,
        "actor": str(observation.get("actor") or "operator"),
    }


def record_census(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    host_generation: int,
    resources: list[str],
    method: str,
    observation: str,
    actor: str,
    resources_complete: bool = False,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Persist a qualified census atomically, under a short write transaction."""
    qualified = validate_census_observation(
        {
            "attempt_id": attempt_id,
            "host_generation": host_generation,
            "resources": resources,
            "method": method,
            "observation": observation,
            "actor": actor,
            "resources_complete": resources_complete,
        }
    )
    recorded = _now(now)
    conn = _connect(home, write=True)
    try:
        # Re-verify inside the transaction: the attempt must still be the same
        # execution, and the generation must still be the one bound to it.
        row = _interrupted_row(conn, attempt_id, qualified["host_generation"])
        record = {**qualified, "kind": "census", "binding": _inventory_binding(row)}
        result = _write_event(conn, record, attempt_id, qualified["host_generation"], recorded)
        conn.commit()
        return result
    finally:
        conn.close()


def _write_event(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    attempt_id: str,
    generation: int,
    recorded: str,
) -> dict[str, Any]:
    blob = json.dumps(record, sort_keys=True)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    event_id = f"r-{digest[:24]}"
    conn.execute(
        "INSERT OR IGNORE INTO worker_recovery_events("
        "event_id,attempt_id,host_generation,kind,resource,method,actor,"
        "payload_sha256,payload_json,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            attempt_id,
            generation,
            record.get("kind"),
            record.get("resource"),
            record.get("method"),
            record.get("actor"),
            digest,
            blob,
            recorded,
        ),
    )
    return {"event_id": event_id, "payload_sha256": digest, "recorded_at": recorded}


def _census_for(
    conn: sqlite3.Connection, attempt_id: str, generation: int, census_event_id: str
) -> dict[str, Any]:
    for event in _events_of_kind(conn, attempt_id, "census"):
        if event["event_id"] != census_event_id:
            continue
        payload = json.loads(event["payload_json"])
        if payload.get("resources_complete") is not True:
            raise RecoveryError(
                "INSUFFICIENT_EVIDENCE", "the selected census is not marked complete"
            )
        if _generation(payload.get("host_generation")) != generation:
            raise RecoveryError(
                "GENERATION_MISMATCH", "the selected census belongs to another generation"
            )
        return payload
    raise RecoveryError(
        "CENSUS_NOT_FOUND", "no census with that id is bound to this attempt and generation"
    )


def _events_of_kind(conn: sqlite3.Connection, attempt_id: str, kind: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM worker_recovery_events WHERE attempt_id = ? AND kind = ?"
            " ORDER BY recorded_at DESC",
            (attempt_id, kind),
        )
    ]


def record_quiescence(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    resource: str,
    method: str,
    actor: str,
    observation: str,
    host_generation: int,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Record how a resource was observed to be quiescent. Recording alone releases nothing."""
    if not resource.strip() or not method.strip() or not observation.strip():
        raise RecoveryError(
            "INSUFFICIENT_EVIDENCE", "resource, method and observation are required"
        )
    recorded = _now(now)
    payload = {
        "kind": "quiescence",
        "attempt_id": attempt_id,
        "host_generation": host_generation,
        "resource": resource,
        "method": method,
        "observation": observation,
        "actor": actor,
    }
    blob = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(blob.encode()).hexdigest()
    event_id = f"q-{digest[:16]}"
    with _connect(home) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO worker_recovery_events("
            "event_id,attempt_id,host_generation,kind,resource,method,actor,payload_sha256,payloa"
            "d_json,"
            "recorded_at) "
            ""
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                attempt_id,
                host_generation,
                "quiescence",
                resource,
                method,
                actor,
                digest,
                blob,
                recorded,
            ),
        )
        conn.commit()
    return {"event_id": event_id, "payload_sha256": digest, "recorded_at": recorded}


def recover_attempt(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    actor: str,
    host_generation: str | None = None,
    executor_settled_evidence: dict[str, Any] | None = None,
    cleanup_evidence: dict[str, Any] | None = None,
    census_event_id: str | None = None,
    dry_run: bool = True,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Apply the authoritative release transition when - and only when - evidence supports it."""
    with _connect(home) as conn:
        rows = _rows(conn, project_id=None, task_id=None, attempt_id=attempt_id)
        if not rows:
            raise RecoveryError("ATTEMPT_NOT_FOUND", "no worker attempt matches that attempt id")
        row = rows[0]
        attestations = _attestations(conn, attempt_id)

        if row.get("writer_ownership") == RELEASED:
            return {"attempt_id": attempt_id, "action": "already-released", "changed": False}

        if host_generation is not None and row.get("host_generation") not in (
            None,
            host_generation,
        ):
            raise RecoveryError(
                "GENERATION_MISMATCH",
                "the supplied host generation does not match this attempt",
                detail={"recorded": row.get("host_generation"), "supplied": host_generation},
            )

        settled = bool(row.get("executor_settled"))
        if not settled and executor_settled_evidence:
            if executor_settled_evidence.get("source") != "host-observation":
                raise RecoveryError(
                    "UNSUPPORTED_EVIDENCE",
                    "executor settlement evidence must be a recorded host observation",
                )
            if executor_settled_evidence.get("native_attempt_id") not in (
                None,
                row.get("native_attempt_id"),
            ):
                raise RecoveryError(
                    "BINDING_MISMATCH",
                    "settlement evidence does not match this attempt's native id",
                )
            settled = bool(executor_settled_evidence.get("executor_settled"))

        cleanup = bool(row.get("cleanup_complete"))
        if not cleanup:
            if cleanup_evidence and cleanup_evidence.get("source") == "host-observation":
                cleanup = bool(cleanup_evidence.get("cleanup_complete"))
            elif attestations:
                cleanup = True  # quiescence recorded for this attempt's resources
            elif cleanup_evidence:
                raise RecoveryError(
                    "UNSUPPORTED_EVIDENCE",
                    "cleanup evidence must be a host observation "
                    "or a recorded quiescence attestation",
                )

        conditions: list[str] = []
        if row.get("logical_outcome") in (None, "unresolved"):
            conditions.append("no accepted outcome recorded for this attempt")
        if not settled:
            conditions.append("executor settlement is not established by an authoritative receipt")
        if not cleanup:
            conditions.append(
                "cleanup completion is not established by evidence "
                "or a recorded quiescence attestation"
            )

        if conditions:
            return {
                "attempt_id": attempt_id,
                "action": "protection-retained",
                "changed": False,
                "unresolved_conditions": conditions,
                "supported_actions": [
                    "record the host's own settlement observation if "
                    "one exists for this attempt and generation",
                    "record a quiescence attestation per pending resource (worker-lease "
                    "quiesce) when the resource is verifiably idle",
                ],
            }

        if dry_run:
            return {
                "attempt_id": attempt_id,
                "action": "release-permitted",
                "changed": False,
                "dry_run": True,
            }

        sequence = int(row.get("lifecycle_sequence") or 0) + 1
        updated = _now(now)
        record = {
            "kind": "operator-recovery",
            "attempt_id": attempt_id,
            "host_generation": row.get("host_generation"),
            "actor": actor,
            "executor_settled": True,
            "cleanup_complete": True,
            "logical_outcome": row.get("logical_outcome"),
            "attestations": [a["event_id"] for a in attestations],
        }
        blob = json.dumps(record, sort_keys=True)
        digest = hashlib.sha256(blob.encode()).hexdigest()
        conn.execute(
            "INSERT INTO "
            "worker_lifecycle_receipts(attempt_id,sequence,receipt_sha256,payload_json,"
            "recorded_at) "
            ""
            ""
            ""
            "VALUES(?,?,?,?,?)",
            (attempt_id, sequence, digest, blob, updated),
        )
        conn.execute(
            "UPDATE worker_tasks SET writer_ownership=?,cleanup_complete=1,lifecycle_sequence=?,"
            "ownership_updated_at=?,updated_at=? WHERE task_id=?",
            (RELEASED, sequence, updated, updated, row["task_id"]),
        )
        conn.commit()
        return {
            "attempt_id": attempt_id,
            "action": "released-by-operator-recovery",
            "changed": True,
            "lifecycle_sequence": sequence,
            "receipt_sha256": digest,
            "logical_outcome_preserved": row.get("logical_outcome"),
        }


def release_interrupted_attempt(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    host_generation: int,
    census_event_id: str,
    actor: str,
    dry_run: bool = True,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Release ownership of an interrupted execution, on authoritative evidence.

    There is no accepted outcome and no host callback here, so nothing produced by
    this path may look like settlement: state, ``logical_outcome``,
    ``executor_settled``, ``cleanup_complete`` and the host ``lifecycle_sequence``
    are all preserved exactly as recorded. Release rests on two objects: a
    persisted complete census (the authoritative evidence of what the execution
    owned) and a bound quiescence attestation for *every* resource that census
    lists. The request selects the census and cannot shrink it.
    """
    generation = _generation(host_generation)
    conn = _connect(home)
    try:
        row = _interrupted_row(conn, attempt_id, generation)
        if row.get("writer_ownership") == RELEASED:
            return {"attempt_id": attempt_id, "action": "already-released", "changed": False}
        census = _census_for(conn, attempt_id, generation, census_event_id)
        wanted = sorted(str(r) for r in census.get("resources", []))
        attestations = [
            a
            for a in _attestations(conn, attempt_id)
            if _generation(a.get("host_generation")) == generation
        ]
        attested = {a["resource"] for a in attestations if a.get("resource")}
        missing = [r for r in wanted if r not in attested]
        if missing:
            return {
                "attempt_id": attempt_id,
                "action": "protection-retained",
                "changed": False,
                "unresolved_conditions": [
                    f"no bound quiescence attestation for: {', '.join(missing)}"
                ],
                "acted_on": {"census": census_event_id, "resources": wanted},
                "supported_actions": [
                    "verify each listed resource is genuinely idle, then record it with"
                    " worker-plane lease-quiesce against this attempt and generation"
                ],
            }
        if dry_run:
            return {
                "attempt_id": attempt_id,
                "action": "release-permitted",
                "changed": False,
                "dry_run": True,
                "would_release_resources": wanted,
            }

        updated = _now(now)
        record = {
            "kind": "operator-recovery-interrupted",
            "attempt_id": attempt_id,
            "host_generation": generation,
            "actor": actor,
            "binding": _inventory_binding(row),
            "census_event_id": census_event_id,
            "resources": wanted,
            "attestations": [
                a["event_id"] for a in attestations if a.get("resource") in set(wanted)
            ],
            # Truthful record: nothing here establishes settlement or completion.
            "executor_settled": False,
            "outcome_rewritten": False,
            "lifecycle_sequence_advanced": False,
            "resource_coverage": "census",
        }
        conn.execute("BEGIN IMMEDIATE")
        result = _write_event(conn, record, attempt_id, generation, updated)
        conn.execute(
            "UPDATE worker_tasks SET writer_ownership=?,ownership_updated_at=?,updated_at=?"
            " WHERE task_id=?",
            (RELEASED, updated, updated, row["task_id"]),
        )
        conn.commit()
        return {
            **result,
            "attempt_id": attempt_id,
            "action": "ownership-released-for-interrupted-attempt",
            "changed": True,
            "state_preserved": row.get("state"),
            "logical_outcome_preserved": row.get("logical_outcome"),
            "lifecycle_sequence_preserved": row.get("lifecycle_sequence"),
        }
    finally:
        conn.close()


def recover(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    actor: str,
    host_generation: str | None = None,
    executor_settled_evidence: dict[str, Any] | None = None,
    cleanup_evidence: dict[str, Any] | None = None,
    census_event_id: str | None = None,
    dry_run: bool = True,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Recover whichever way the recorded state supports.

    An attempt that recorded host activity is reconciled from settlement evidence;
    an attempt whose host never reported anything is released for service only
    against recorded quiescence attestations, preserving its interrupted state.
    """
    with _connect(home) as conn:
        rows = _rows(conn, project_id=None, task_id=None, attempt_id=attempt_id)
        if not rows:
            raise RecoveryError("ATTEMPT_NOT_FOUND", "no worker attempt matches that attempt id")
        row = rows[0]
    if row.get("executor_settled") or row.get("logical_outcome") not in (None, "unresolved"):
        return recover_attempt(
            home,
            attempt_id=attempt_id,
            actor=actor,
            host_generation=host_generation,
            executor_settled_evidence=executor_settled_evidence,
            cleanup_evidence=cleanup_evidence,
            dry_run=dry_run,
            now=now,
        )
    if census_event_id is None:
        raise RecoveryError(
            "CENSUS_REQUIRED",
            "interrupted release needs the id of a persisted complete census",
        )
    return release_interrupted_attempt(
        home,
        attempt_id=attempt_id,
        host_generation=host_generation,
        census_event_id=census_event_id,
        actor=actor,
        dry_run=dry_run,
        now=now,
    )


def reap_expired(
    home: Path | str | None = None, *, now: datetime | str | None = None
) -> list[dict[str, Any]]:
    """Existing protocol reaper: expired or unacknowledged attempts move to quarantine."""
    return reap(home if home is not None else Path.cwd(), now=now)
