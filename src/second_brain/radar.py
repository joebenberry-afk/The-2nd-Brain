"""
Improvement Radar & Inefficiency Detection (Plan §3 P3.10).

Monitors session activities and telemetry to detect:
1. Repeated file reads (≥3 reads of identical file in close succession).
2. Search thrash (repeated queries returning 0 results).
3. Tool failure loops (consecutive errors on the same tool/command).
4. Redundant test runs without code edits.

Emits structured ImprovementAlerts with targeted token-saving recommendations.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import telemetry
from .errors import BrainError


class InefficiencyPattern(StrEnum):
    REPEATED_READ = "REPEATED_READ"
    SEARCH_THRASH = "SEARCH_THRASH"
    TOOL_ERROR_LOOP = "TOOL_ERROR_LOOP"
    REDUNDANT_TEST_RUN = "REDUNDANT_TEST_RUN"
    CONTEXT_CHURN = "CONTEXT_CHURN"


@dataclass
class ImprovementAlert:
    """An alert emitted by the Improvement Radar (§3 P3.10)."""
    pattern: InefficiencyPattern
    severity: str  # "INFO", "WARNING", "CRITICAL"
    summary: str
    evidence: list[str] = field(default_factory=list)
    suggested_action: str = ""
    tokens_wasted_estimate: int = 0
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern.value,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
            "tokens_wasted_estimate": self.tokens_wasted_estimate,
            "created_at": self.created_at,
        }


class ImprovementRadar:
    """Real-time and post-session inefficiency analyzer."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def _candidate_path(self) -> Path:
        return self.home / "state" / "radar" / "candidates.json"

    def _load_candidates(self) -> list[dict[str, Any]]:
        path = self._candidate_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrainError(f"corrupt Radar candidate store: {path}") from exc
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise BrainError(f"corrupt Radar candidate store: {path}")
        return data

    def _save_candidates(self, candidates: list[dict[str, Any]]) -> None:
        path = self._candidate_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(candidates, handle, indent=2, sort_keys=True)
            os.replace(temporary, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise BrainError(f"could not persist Radar candidates: {path}") from exc

    @staticmethod
    def _record_hash(record: dict[str, Any]) -> str:
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _signal_key(alert: ImprovementAlert) -> str:
        stable = [
            item
            for item in alert.evidence
            if item.startswith("Path:") or item.startswith("Tool:")
        ]
        return f"{alert.pattern.value}|{'|'.join(stable)}"
    def _session_rows(self, session_id: str) -> list[tuple[str, int, dict[str, Any]]]:
        path = telemetry.telemetry_dir(self.home) / f"{session_id}.jsonl"
        if path.is_file():
            rows: list[tuple[str, int, dict[str, Any]]] = []
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    record = {"__parse_error__": line[:80]}
                rows.append((path.name, line_number, record))
            return rows
        return [
            (filename, line_number, record)
            for filename, line_number, record in telemetry.iter_records(self.home)
            if record.get("session") == session_id
        ]


    def observe_session(
        self,
        session_id: str,
        *,
        project_id: str,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Observe one canonical telemetry stream and persist candidates."""
        if not project_id.strip():
            raise BrainError("project_id must be non-empty")
        rows = self._session_rows(session_id)
        events = [record for _, _, record in rows]
        alerts = self.analyze_events(events)
        if not alerts:
            return []
        candidates = self._load_candidates()
        results: list[dict[str, Any]] = []
        for alert in alerts:
            signal_key = self._signal_key(alert)
            candidate_id = (
                "candidate-"
                + hashlib.sha256(f"{project_id}|{signal_key}".encode()).hexdigest()[:24]
            )
            refs = [
                {
                    "telemetry_ref": f"{filename}:{line_number}",
                    "record_hash": self._record_hash(record),
                    "ts": record.get("ts"),
                }
                for filename, line_number, record in rows
                if record.get("kind") in {"tool_call", "tool_result", "brain_retrieval_attempt"}
            ]
            observation_id = hashlib.sha256(
                json.dumps(
                    {
                        "candidate_id": candidate_id,
                        "session_id": session_id,
                        "task_id": task_id,
                        "refs": refs,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:24]
            existing = next(
                (item for item in candidates if item.get("candidate_id") == candidate_id),
                None,
            )
            if existing is None:
                existing = {
                    "candidate_id": candidate_id,
                    "candidate_type": alert.pattern.value,
                    "project_id": project_id,
                    "lifecycle_state": "candidate",
                    "promotion_eligible": False,
                    "observations": [],
                }
                candidates.append(existing)
            if any(
                item.get("observation_id") == observation_id
                for item in existing["observations"]
            ):
                results.append(existing)
                continue
            timestamps: list[str] = []
            for _, _, record in rows:
                timestamp = record.get("ts")
                if isinstance(timestamp, str):
                    timestamps.append(timestamp)
            observation = {
                "observation_id": observation_id,
                "session_id": session_id,
                "task_id": task_id,
                "observation_window": {
                    "start": min(timestamps) if timestamps else None,
                    "end": max(timestamps) if timestamps else None,
                },
                "evidence_count": len(refs),
                "telemetry_evidence_refs": refs[:64],
            }
            merged_refs = [
                *existing.get("telemetry_evidence_refs", []),
                *refs,
            ][-64:]
            existing.update(
                {
                    "radar_observation_id": observation_id,
                    "triggering_signal": alert.pattern.value,
                    "reason_codes": [alert.pattern.value],
                    "evidence_count": int(existing.get("evidence_count", 0)) + len(refs),
                    "telemetry_evidence_refs": merged_refs,
                    "observation_window": observation["observation_window"],
                    "expected_benefit_tokens": alert.tokens_wasted_estimate,
                    "expected_cost_model_calls": 0,
                    "status": "candidate",
                    "promotion_authority": "existing_promotion",
                }
            )
            existing["observations"].append(observation)
            existing["observations"] = existing["observations"][-16:]
            results.append(existing)
        self._save_candidates(candidates)
        return results

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Return one persisted candidate without changing its lifecycle."""
        candidate = next(
            (item for item in self._load_candidates() if item.get("candidate_id") == candidate_id),
            None,
        )
        if candidate is None:
            raise BrainError(f"unknown Radar candidate: {candidate_id}")
        return candidate
    def validate_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Re-read referenced telemetry; stale evidence is never promotable."""
        candidate = next(
            (
                item
                for item in self._load_candidates()
                if item.get("candidate_id") == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise BrainError(f"unknown Radar candidate: {candidate_id}")
        for observation in candidate.get("observations", []):
            for reference in observation.get("telemetry_evidence_refs", []):
                ref = str(reference.get("telemetry_ref", ""))
                filename, separator, line_text = ref.rpartition(":")
                if not separator or not line_text.isdigit():
                    return {
                        "candidate_id": candidate_id,
                        "status": "stale",
                        "promotion_eligible": False,
                        "reason": "telemetry_reference_invalid",
                    }
                path = telemetry.telemetry_dir(self.home) / filename
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                    record = json.loads(lines[int(line_text) - 1])
                except (OSError, IndexError, ValueError, json.JSONDecodeError):
                    return {
                        "candidate_id": candidate_id,
                        "status": "stale",
                        "promotion_eligible": False,
                        "reason": "telemetry_evidence_missing",
                    }
                if self._record_hash(record) != reference.get("record_hash"):
                    return {
                        "candidate_id": candidate_id,
                        "status": "stale",
                        "promotion_eligible": False,
                        "reason": "telemetry_evidence_changed",
                    }
        return {
            "candidate_id": candidate_id,
            "status": "candidate",
            "promotion_eligible": False,
            "reason": "candidate_only",
        }

    def analyze_events(self, events: list[dict[str, Any]]) -> list[ImprovementAlert]:
        """
        Analyze a stream of session events for systemic token inefficiencies.
        """
        alerts: list[ImprovementAlert] = []
        now = datetime.now(UTC).isoformat()

        # 1. Detect Repeated File Reads
        read_counts: Counter[str] = Counter()
        for ev in events:
            if ev.get("kind") in ("tool_call", "tool_requested"):
                tool = ev.get("tool") or ev.get("toolName") or ""
                inp = ev.get("input") or {}
                target = ""
                if tool == "read":
                    target = str(ev.get("target_sha256") or "")
                elif tool in ("view_file", "read_file") and isinstance(inp, dict):
                    target = inp.get("AbsolutePath") or inp.get("path") or ""
                if target:
                    read_counts[target] += 1

        for target, count in read_counts.items():
            if count >= 3:
                alerts.append(
                    ImprovementAlert(
                        pattern=InefficiencyPattern.REPEATED_READ,
                        severity="WARNING",
                        summary=f"File read {count} times in session: {Path(target).name}",
                        evidence=[f"Path: {target}", f"Read count: {count}"],
                        suggested_action=(
                            "Use Context Virtual Memory (VMem) or Action Cache to "
                            "avoid repeat full reads."
                        ),
                        tokens_wasted_estimate=(count - 1) * 300,
                        created_at=now,
                    )
                )

        # 2. Detect Tool Failure Loops
        consecutive_errors = 0
        last_failed_tool = ""
        for ev in events:
            if ev.get("kind") == "tool_result":
                is_err = ev.get("is_error") or ("error" in str(ev.get("content", "")).lower())
                tool_name = str(ev.get("toolName") or ev.get("tool") or "")
                if is_err:
                    if tool_name == last_failed_tool:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 1
                        last_failed_tool = tool_name
                else:
                    consecutive_errors = 0

            if consecutive_errors >= 2:
                alerts.append(
                    ImprovementAlert(
                        pattern=InefficiencyPattern.TOOL_ERROR_LOOP,
                        severity="CRITICAL",
                        summary=f"Tool error loop detected on tool: {last_failed_tool}",
                        evidence=[
                            f"Tool: {last_failed_tool}",
                            f"Consecutive errors: {consecutive_errors}",
                        ],
                        suggested_action=(
                            "Review tool parameters or inspect error diagnostics "
                            "before retrying."
                        ),
                        tokens_wasted_estimate=consecutive_errors * 500,
                        created_at=now,
                    )
                )
                consecutive_errors = 0

        # 3. Detect Search Thrash
        zero_result_searches = 0
        for ev in events:
            if ev.get("kind") == "brain_retrieval_attempt":
                cand_count = ev.get("candidate_count", 0)
                if cand_count == 0:
                    zero_result_searches += 1

        if zero_result_searches >= 3:
            alerts.append(
                ImprovementAlert(
                    pattern=InefficiencyPattern.SEARCH_THRASH,
                    severity="WARNING",
                    summary=(
                        f"Search thrash detected: {zero_result_searches} searches "
                        "yielded 0 candidates"
                    ),
                    evidence=[f"Zero-result search attempts: {zero_result_searches}"],
                    suggested_action=(
                        "Broaden search terms, inspect vocabulary, or use Hybrid "
                        "Cascade Tier 2 fallback."
                    ),
                    tokens_wasted_estimate=zero_result_searches * 150,
                    created_at=now,
                )
            )

        return alerts

    def analyze_session(self, session_id: str) -> list[ImprovementAlert]:
        """Load session telemetry and return detected improvement alerts."""
        safe_stem = (
            "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in session_id)
            or "anon"
        )
        t_file = telemetry.telemetry_dir(self.home) / f"{safe_stem}.jsonl"
        if not t_file.exists():
            return []

        import contextlib
        import json

        events: list[dict[str, Any]] = []
        for line in t_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                with contextlib.suppress(Exception):
                    events.append(json.loads(line))

        return self.analyze_events(events)
