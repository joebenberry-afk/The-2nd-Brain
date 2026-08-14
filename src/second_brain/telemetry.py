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
        if isinstance(rec.get("v"), int) and rec["v"] != SCHEMA_VERSION:
            issues.append(f"{fname}:{lineno}: schema v{rec['v']} != current {SCHEMA_VERSION}")
        kind = rec.get("kind")
        if kind not in KNOWN_KINDS:
            issues.append(f"{fname}:{lineno}: unknown kind {kind!r}")
        if not isinstance(rec.get("ts"), str):
            issues.append(f"{fname}:{lineno}: ts missing or not a string")
    return {"files": len(seen_files), "records": n_records, "issues": issues}


def _ts(record: dict) -> str | None:
    return record.get("ts") if isinstance(record.get("ts"), str) else None


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
