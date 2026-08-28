"""Telemetry aggregation and validation (Phase 2 observability).

Reads JSONL telemetry written by the Prime measurement extension into
<home>/telemetry/agent-performance/<session>.jsonl (schema v2, see
brainstem/telemetry/SCHEMA.md). Aggregation is deterministic and read-only.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = 2
KNOWN_KINDS = {
    "session_start",
    "before_agent_start",
    "turn_start",
    "context",
    "tool_call",
    "tool_result",
    "turn_end",
    "agent_end",
    "session_before_compact",
    "session_compact",
    "session_shutdown",
    "rtd_shadow",
    "extension_error",
    "orchestrator_policy_violation",
    # P3-B economics kinds (SCHEMA.md): additive v3 records from the Prime
    # extension (assistant_usage / provider_request_meta / provider_response_meta).
    "assistant_usage",
    "provider_request_meta",
    "provider_response_meta",
}
# P3-B economics kinds carry v=3 (additive); every other kind stays v=2.
# The version check is kind-aware so legacy records are never flagged and the
# new records are still validated strictly.
KIND_SCHEMA_VERSION = {
    "assistant_usage": 3,
    "provider_request_meta": 3,
    "provider_response_meta": 3,
}
REQUIRED_FIELDS = ("v", "kind", "session")


def telemetry_dir(home: Path) -> Path:
    return home / "telemetry" / "agent-performance"


def iter_records(home: Path) -> list[tuple[str, int, dict]]:
    """All parsed records as (file_name, line_number, record)."""
    out: list[tuple[str, int, dict]] = []
    tdir = telemetry_dir(home)
    if not tdir.is_dir():
        return out
    for f in sorted(tdir.glob("*.jsonl")):
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                out.append((f.name, lineno, {"__parse_error__": line[:80]}))
                continue
            out.append((f.name, lineno, record))
    return out


def validate(home: Path) -> dict:
    """Check every record. Returns {'files', 'records', 'issues': [..]}."""
    issues: list[str] = []
    n_records = 0
    seen_files: set[str] = set()
    for fname, lineno, rec in iter_records(home):
        seen_files.add(fname)
        n_records += 1
        if "__parse_error__" in rec:
            issues.append(f"{fname}:{lineno}: unparseable JSON line")
            continue
        if not isinstance(rec, dict):
            issues.append(f"{fname}:{lineno}: record is not a JSON object")
            continue
        for field in REQUIRED_FIELDS:
            if field not in rec:
                issues.append(f"{fname}:{lineno}: missing required field {field!r}")
        kind = rec.get("kind")
        if kind not in KNOWN_KINDS:
            issues.append(f"{fname}:{lineno}: unknown kind {kind!r}")
        expected_v = SCHEMA_VERSION
        if isinstance(kind, str):
            expected_v = KIND_SCHEMA_VERSION.get(kind, SCHEMA_VERSION)
        if isinstance(rec.get("v"), int) and rec["v"] != expected_v:
            issues.append(
                f"{fname}:{lineno}: schema v{rec['v']} != expected v{expected_v} for kind {kind!r}"
            )
        if not isinstance(rec.get("ts"), str):
            issues.append(f"{fname}:{lineno}: ts missing or not a string")
    return {"files": len(seen_files), "records": n_records, "issues": issues}


def _ts(record: dict) -> str | None:
    return record.get("ts") if isinstance(record.get("ts"), str) else None


def session_usage(home: Path, session_id: str) -> dict:
    """Real per-session token usage, summed from this session's
    ``assistant_usage`` records (P3-B economics kind). Every field mirrors an
    EXACT host-reported counter (plan §44: use current runtime evidence, do
    not fabricate). ``reasoning`` stays ``None`` when no record in this
    session ever reported it — omission is preserved, never invented as 0."""
    totals: dict[str, int] = {
        "input": 0,
        "cache_read": 0,
        "cache_write": 0,
        "output": 0,
        "total": 0,
    }
    reasoning_total = 0
    reasoning_seen = False
    message_count = 0
    for _, _, record in iter_records(home):
        if record.get("session") != session_id or record.get("kind") != "assistant_usage":
            continue
        message_count += 1
        totals["input"] += int(record.get("input_tokens") or 0)
        totals["cache_read"] += int(record.get("cache_read_tokens") or 0)
        totals["cache_write"] += int(record.get("cache_write_tokens") or 0)
        totals["output"] += int(record.get("output_tokens") or 0)
        totals["total"] += int(record.get("total_tokens") or 0)
        if "reasoning_tokens" in record:
            reasoning_seen = True
            reasoning_total += int(record.get("reasoning_tokens") or 0)
    result: dict[str, int | None] = dict(totals)
    result["reasoning"] = reasoning_total if reasoning_seen else None
    result["message_count"] = message_count
    return result


def session_tool_calls(home: Path, session_id: str) -> int:
    """Real count of ``tool_call`` records for one session — actual tool
    executions, not an estimate."""
    return sum(
        1
        for _, _, record in iter_records(home)
        if record.get("session") == session_id and record.get("kind") == "tool_call"
    )


def session_wall_time_ms(home: Path, session_id: str) -> float | None:
    """Real elapsed wall time for one session: the span between its first and
    last telemetry timestamp (one clock, ms; plan §44 'stable timestamps').
    ``None`` when fewer than two timestamped records exist for the session."""
    ts_values = sorted(
        ts
        for _, _, record in iter_records(home)
        if record.get("session") == session_id
        for ts in [_ts(record)]
        if ts is not None
    )
    if len(ts_values) < 2:
        return None
    from datetime import datetime as _datetime

    start = _datetime.fromisoformat(ts_values[0].replace("Z", "+00:00"))
    end = _datetime.fromisoformat(ts_values[-1].replace("Z", "+00:00"))
    return max((end - start).total_seconds() * 1000, 0.0)


def report(home: Path, *, since: str | None = None) -> dict:
    """Aggregate telemetry into a compact report (deterministic)."""
    records = [rec for _, _, rec in iter_records(home) if "__parse_error__" not in rec]
    if since:
        records = [r for r in records if (_ts(r) or "") >= since]

    kinds = Counter(r.get("kind") for r in records)
    tools = Counter(r.get("tool") for r in records if r.get("kind") in ("tool_call", "tool_result"))
    sessions: set[str] = {s for s in (r.get("session") for r in records) if isinstance(s, str)}

    starts = [r for r in records if r.get("kind") == "session_start"]
    cwds = Counter(r.get("cwd") for r in starts if r.get("cwd"))
    models = Counter(str(r.get("model")) for r in starts if r.get("model"))

    errors = [r for r in records if r.get("kind") == "tool_result" and r.get("is_error")]
    orchestrator_violations = [
        r for r in records if r.get("kind") == "orchestrator_policy_violation"
    ]
    violation_codes = Counter(
        v.get("violation") for v in orchestrator_violations if isinstance(v.get("violation"), str)
    )
    compactions = [r for r in records if r.get("kind") == "session_compact"]
    ext_errors = [r for r in records if r.get("kind") == "extension_error"]
    bash_calls = [r for r in records if r.get("kind") == "tool_call" and r.get("tool") == "bash"]

    context_pcts: list[float] = []
    for r in records:
        cu = r.get("context_usage")
        if isinstance(cu, dict) and isinstance(cu.get("percent"), (int, float)):
            context_pcts.append(float(cu["percent"]))

    ts_list = sorted(ts for ts in (_ts(r) for r in records) if ts is not None)
    result_bytes = [
        r.get("output_bytes")
        for r in records
        if r.get("kind") == "tool_result" and isinstance(r.get("output_bytes"), int)
    ]

    return {
        "sessions": len(sessions),
        "records": len(records),
        "first_ts": ts_list[0] if ts_list else None,
        "last_ts": ts_list[-1] if ts_list else None,
        "kinds": dict(sorted(kinds.items())),
        "tools": dict(sorted(tools.items())),
        "tool_results_with_error": len(errors),
        "bash_calls": len(bash_calls),
        "compactions": len(compactions),
        "extension_errors": len(ext_errors),
        "orchestrator_violations": len(orchestrator_violations),
        "violation_codes": dict(sorted(violation_codes.items())),
        "max_context_percent": round(max(context_pcts), 1) if context_pcts else None,
        "total_result_bytes": sum(x for x in result_bytes if isinstance(x, int)),
        "cwds": dict(sorted(cwds.items(), key=lambda kv: -kv[1])),
        "models": dict(sorted(models.items(), key=lambda kv: -kv[1])),
    }


def format_report(rep: dict) -> str:
    lines = [
        f"Sessions:            {rep['sessions']}",
        f"Records:             {rep['records']}",
        f"Time range:          {rep['first_ts']} .. {rep['last_ts']}",
        f"Tool results w/ err: {rep['tool_results_with_error']}",
        f"bash calls:          {rep['bash_calls']}",
        f"Compactions:         {rep['compactions']}",
        f"Extension errors:    {rep['extension_errors']}",
        f"Orchestrator viol.:  {rep['orchestrator_violations']}",
        f"Max context %:       {rep['max_context_percent']}",
        f"Result bytes:        {rep['total_result_bytes']}",
    ]
    lines.append("Events by kind:")
    for k, v in rep["kinds"].items():
        lines.append(f"  {k:22s} {v}")
    if rep["tools"]:
        lines.append("Tool events by tool:")
        for k, v in rep["tools"].items():
            lines.append(f"  {k!s:22s} {v}")
    if rep["cwds"]:
        lines.append("Working dirs:")
        for k, v in rep["cwds"].items():
            lines.append(f"  {k!s:60s} {v}")
    if rep["models"]:
        lines.append("Models:")
        for k, v in rep["models"].items():
            lines.append(f"  {k:40s} {v}")
    return "\n".join(lines)
