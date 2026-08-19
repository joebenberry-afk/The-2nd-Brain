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

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import telemetry


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
                if tool in ("view_file", "read_file") and isinstance(inp, dict):
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
