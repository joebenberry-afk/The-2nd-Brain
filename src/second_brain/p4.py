"""Bounded P4 bridge: composes the local heartbeat with shutdown-only Radar
observation into one JSON-safe pulse (plan §3 P4, Task 7).

`pulse()` is the single entry point OMP/Prime host bridges call once per
lifecycle event. It never invents data: the heartbeat result comes verbatim
from `HeartbeatCoordinator.run_if_due()` (Task 3) and, only for
`session_shutdown` with a `project_id`, the candidates/fingerprints come
verbatim from `ImprovementRadar.observe_session()` (Task 5).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path
from typing import Any

from . import telemetry
from .heartbeat import HeartbeatCoordinator
from .radar import ImprovementRadar

SHUTDOWN_EVENT = "session_shutdown"

_HEARTBEAT_RECORD_FIELDS = (
    "mode",
    "event",
    "due",
    "ran",
    "healthy",
    "db_ok",
    "cache_pruned_count",
    "git_dirty",
    "issue_codes",
    "latency_ms",
    "model_tokens_used",
    "artifacts_gc_count",
)


def _collect_fingerprints(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe candidate fingerprints by id, keeping the highest-impact
    version and sorting by descending impact (mirrors `cmd_radar`'s
    aggregation in cli.py so both surfaces rank identically)."""
    by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        for fingerprint in candidate.get("fingerprints", []):
            fingerprint_id = str(fingerprint.get("fingerprint_id", ""))
            existing = by_id.get(fingerprint_id)
            score = float(fingerprint.get("impact_score", 0)) * int(
                fingerprint.get("occurrence_count", 0)
            )
            existing_score = (
                float(existing.get("impact_score", 0)) * int(existing.get("occurrence_count", 0))
                if existing is not None
                else -1.0
            )
            if existing is None or score > existing_score:
                by_id[fingerprint_id] = fingerprint
    ranked = sorted(
        by_id.values(),
        key=lambda item: (
            -(float(item.get("impact_score", 0)) * int(item.get("occurrence_count", 0))),
            str(item.get("fingerprint_id", "")),
        ),
    )
    for index, fingerprint in enumerate(ranked):
        refs = fingerprint.get("evidence_refs") or []
        ranked[index] = {
            **fingerprint,
            "evidence_count": len(refs),
            "evidence_hash": hashlib.sha256(
                json.dumps(refs, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
    return ranked


def pulse(
    home: Path,
    *,
    event: str,
    session_id: str,
    repo_dir: Path | None,
    project_id: str | None = None,
    force: bool = False,
    emit_telemetry: bool = True,
) -> dict[str, Any]:
    """Run one bounded heartbeat, plus Radar observation on shutdown only.

    `HeartbeatCoordinator.run_if_due()` runs for every event. Radar's
    `observe_session()` runs only when `event == "session_shutdown"` and
    `project_id` is a non-empty string; a missing/blank `project_id` simply
    skips Radar (never raises). `emit_telemetry` gates every P4 telemetry
    write this pulse would otherwise make: the pulse's own `heartbeat_pulse`
    record, and (via `observe_session(emit_telemetry=...)`) Radar's internal
    `bottleneck_fingerprint` records. `False` returns the identical
    JSON-safe result without writing anything to telemetry.
    """
    home = Path(home)
    heartbeat_result = HeartbeatCoordinator(home).run_if_due(
        event, session_id, repo_dir, force=force
    )

    candidates: list[dict[str, Any]] = []
    if event == SHUTDOWN_EVENT and project_id and project_id.strip():
        candidates = ImprovementRadar(home).observe_session(
            session_id, project_id=project_id, emit_telemetry=emit_telemetry
        )

    if emit_telemetry:
        with contextlib.suppress(OSError, ValueError):
            telemetry.append_record(
                home,
                session_id,
                "heartbeat_pulse",
                {field: heartbeat_result[field] for field in _HEARTBEAT_RECORD_FIELDS},
            )

    return {
        "session_id": session_id,
        "event": event,
        "heartbeat": heartbeat_result,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "fingerprints": _collect_fingerprints(candidates),
    }
