"""Telemetry aggregation and validation (Phase 2 observability).

Reads JSONL telemetry written by the Prime measurement extension into
<home>/telemetry/agent-performance/<session>.jsonl (schema v2, see
brainstem/telemetry/SCHEMA.md). Aggregation is deterministic and read-only.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2
KNOWN_KINDS = {
    "OMP_SECOND_BRAIN_READY", "active_state_delivery", "agent_end",
    "assistant_usage", "autoinject_shadow_decision", "before_agent_start",
    "brain_no_injection", "brain_packet_delivered", "brain_retrieval_attempt",
    "claude_code_stop_turn", "claude_code_user_prompt", "claude_code_tool_result",
    "codex_hook_shadow_decision", "context", "context_paging", "context_structure",
    "extension_error",
    "hermes_model_decision", "hermes_post_tool_call", "hermes_pre_llm_call",
    "hermes_session_finalized", "hermes_session_started",
    "hermes_worker_context_resolved", "hermes_worker_lifecycle",
    "hermes_worker_result_corrected", "hermes_worker_result_correction_requested",
    "hermes_worker_result_reviewed", "hermes_writeback_candidate", "lean_kernel",
    "model_fallback_used", "model_invocation_completed",
    "model_invocation_failed", "model_invocation_started", "model_routing_decision",
    "omp_routing_decision", "omp_routing_handoff_failure",
    "omp_routing_invocation", "omp_routing_response",
    "omp_visibility_plan", "omp_worker_child_result", "omp_worker_context_failure",
    "omp_worker_context_handoff", "orchestration_record", "orchestrator_policy_violation",
    "preinvocation", "preinvocation_no_task", "prime_tool_surface",
    "provider_request_meta", "provider_response_meta", "rtd_shadow",
    "session_before_compact", "session_compact", "session_finalized",
    "session_shutdown", "session_start", "session_started",
    "simplification_review", "stop_allowed", "stop_blocked",
    "stop_blocked_result", "stop_boundary", "stop_continue",
    "stop_control_result", "stop_finalization_error", "stop_finalized",
    "stop_not_triggered", "tool_call", "tool_result", "turn_end", "turn_start",
    "vmem_compact_prep", "vmem_fault_in", "vmem_hot_context", "writeback_candidate",
    "heartbeat_pulse", "bottleneck_fingerprint", "optimization_proposal",
    "optimization_evaluation", "optimization_activation", "optimization_rollback",
}
KIND_SCHEMA_VERSION = {
    kind: 3
    for kind in {
        "assistant_usage", "provider_request_meta", "provider_response_meta",
        "OMP_SECOND_BRAIN_READY", "omp_routing_decision",
        "omp_routing_handoff_failure", "omp_routing_invocation",
        "omp_routing_response", "omp_visibility_plan", "omp_worker_child_result",
        "omp_worker_context_failure", "omp_worker_context_handoff",
    }
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


_HEARTBEAT_FIELDS = (
    "mode", "event", "due", "ran", "healthy", "db_ok", "cache_pruned_count",
    "git_dirty", "issue_codes", "latency_ms", "model_tokens_used",
)
_HEARTBEAT_MODES = frozenset({"off", "shadow", "active"})
_P4_OPTIMIZATION_KINDS = frozenset({
    "optimization_proposal", "optimization_evaluation",
    "optimization_activation", "optimization_rollback",
})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_FORBIDDEN_P4_FIELDS = frozenset({
    "prompt", "payload", "secret", "content", "tool_input", "tool_output",
    "chain_of_thought", "thinking", "internal_monologue",
})


def _field_issue(identity: str, field: str, message: str) -> str:
    return f"{identity}: invalid {field}: {message}"


def _p4_issues(record: dict, identity: str) -> list[str]:
    issues: list[str] = []
    kind = record.get("kind")
    for field in sorted(_FORBIDDEN_P4_FIELDS.intersection(record)):
        issues.append(_field_issue(identity, field, "content fields are not permitted"))

    def require(field: str) -> object | None:
        if field not in record:
            issues.append(f"{identity}: missing required field {field!r}")
            return None
        return record[field]

    if kind == "heartbeat_pulse":
        values = {field: require(field) for field in _HEARTBEAT_FIELDS}
        mode = values["mode"]
        if "mode" in record and (
            not isinstance(mode, str) or mode not in _HEARTBEAT_MODES
        ):
            issues.append(_field_issue(identity, "mode", "must be off, shadow, or active"))
        event = values["event"]
        if "event" in record and (
            not isinstance(event, str) or len(event) > 128
        ):
            issues.append(
                _field_issue(
                    identity,
                    "event",
                    "must be a string of at most 128 characters",
                )
            )
        for field in ("due", "ran", "healthy", "db_ok", "git_dirty"):
            value = values[field]
            if field in record and not isinstance(value, bool):
                issues.append(_field_issue(identity, field, "must be boolean"))
        for field in ("cache_pruned_count", "latency_ms", "model_tokens_used"):
            value = values[field]
            if field in record and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                issues.append(_field_issue(identity, field, "must be a non-negative integer"))
        cache_count = values["cache_pruned_count"]
        if (
            "cache_pruned_count" in record
            and isinstance(cache_count, int)
            and not isinstance(cache_count, bool)
            and cache_count > 1_000_000
        ):
            issues.append(_field_issue(identity, "cache_pruned_count", "exceeds bound"))
        latency = values["latency_ms"]
        if (
            "latency_ms" in record
            and isinstance(latency, int)
            and not isinstance(latency, bool)
            and latency > 86_400_000
        ):
            issues.append(_field_issue(identity, "latency_ms", "exceeds bound"))
        tokens = values["model_tokens_used"]
        if "model_tokens_used" in record and isinstance(tokens, int) and tokens != 0:
            issues.append(_field_issue(identity, "model_tokens_used", "must equal zero"))
        codes = values["issue_codes"]
        if "issue_codes" in record and (
            not isinstance(codes, list)
            or len(codes) > 32
            or any(not isinstance(code, str) or not 1 <= len(code) <= 64 for code in codes)
        ):
            issues.append(
                _field_issue(
                    identity,
                    "issue_codes",
                    "must be at most 32 bounded strings",
                )
            )

    elif kind == "bottleneck_fingerprint":
        for field in ("fingerprint_id", "category", "occurrence_count", "impact_score"):
            require(field)
        for field in ("fingerprint_id", "category", "scope_id"):
            if field in record and (
                not isinstance(record[field], str) or not 1 <= len(record[field]) <= 128
            ):
                issues.append(_field_issue(identity, field, "must be a bounded non-empty string"))
        for field in ("occurrence_count", "evidence_count"):
            if field in record and (
                isinstance(record[field], bool)
                or not isinstance(record[field], int)
                or record[field] < 0
                or record[field] > 1_000_000_000
            ):
                issues.append(
                    _field_issue(
                        identity,
                        field,
                        "must be a bounded non-negative integer",
                    )
                )
        impact = record.get("impact_score")
        if "impact_score" in record and (
            isinstance(impact, bool)
            or not isinstance(impact, (int, float))
            or not math.isfinite(impact)
            or impact < 0
            or impact > 1_000_000
        ):
            issues.append(
                _field_issue(
                    identity,
                    "impact_score",
                    "must be a bounded non-negative number",
                )
            )
        if "evidence_hash" in record and (
            not isinstance(record["evidence_hash"], str)
            or not _SHA256_RE.fullmatch(record["evidence_hash"])
        ):
            issues.append(_field_issue(identity, "evidence_hash", "must be a SHA-256 hex digest"))

    elif kind in _P4_OPTIMIZATION_KINDS:
        for field in ("proposal_id", "status"):
            require(field)
        for field in ("proposal_id", "status", "approval_state", "rollback_state"):
            if field in record and (
                not isinstance(record[field], str) or not _TOKEN_RE.fullmatch(record[field])
            ):
                issues.append(_field_issue(identity, field, "must be a bounded token"))
        for field in ("intervention_hash", "evidence_hash"):
            if field in record and (
                not isinstance(record[field], str) or not _SHA256_RE.fullmatch(record[field])
            ):
                issues.append(_field_issue(identity, field, "must be a SHA-256 hex digest"))
    return issues


def _record_issues(record: object, identity: str) -> list[str]:
    if not isinstance(record, dict):
        return [f"{identity}: record is not a JSON object"]
    issues: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in record:
            issues.append(f"{identity}: missing required field {field!r}")
    kind = record.get("kind")
    if kind not in KNOWN_KINDS:
        issues.append(f"{identity}: unknown kind {kind!r}")
    expected_v = (
        KIND_SCHEMA_VERSION.get(kind, SCHEMA_VERSION)
        if isinstance(kind, str)
        else SCHEMA_VERSION
    )
    version = record.get("v")
    if isinstance(version, bool) or (version is not None and not isinstance(version, int)):
        issues.append(f"{identity}: schema version is not an integer")
    elif isinstance(version, int) and version != expected_v:
        issues.append(
            f"{identity}: schema v{version} != expected v{expected_v} for kind {kind!r}"
        )
    if not isinstance(record.get("ts"), str):
        issues.append(f"{identity}: ts missing or not a string")
    if kind in {
        "heartbeat_pulse", "bottleneck_fingerprint", *_P4_OPTIMIZATION_KINDS,
    }:
        issues.extend(_p4_issues(record, identity))
    return issues
def validate(home: Path) -> dict:
    """Check every record. Returns {'files', 'records', 'issues': [..]}."""
    issues: list[str] = []
    n_records = 0
    seen_files: set[str] = set()
    for fname, lineno, rec in iter_records(home):
        seen_files.add(fname)
        n_records += 1
        if isinstance(rec, dict) and "__parse_error__" in rec:
            issues.append(f"{fname}:{lineno}: unparseable JSON line")
            continue
        issues.extend(_record_issues(rec, f"{fname}:{lineno}"))
    return {"files": len(seen_files), "records": n_records, "issues": issues}


def _ts(record: dict) -> str | None:
    return record.get("ts") if isinstance(record.get("ts"), str) else None


def session_usage(home: Path, session_id: str) -> dict:
    """Return exact token counters reported for one session.

    Prime ``assistant_usage`` records expose counters at the record root;
    Hermes ``model_invocation_completed`` records nest the same counters under
    ``usage``. Missing and explicitly null counters remain ``None``.
    """
    totals: dict[str, int | None] = {
        "input": None,
        "cache_read": None,
        "cache_write": None,
        "output": None,
        "total": None,
    }
    source_kind: str | None = None
    reasoning_total = 0
    reasoning_seen = False
    message_count = 0
    field_sources = (
        ("input", "input_tokens"),
        ("cache_read", "cache_read_tokens"),
        ("cache_write", "cache_write_tokens"),
        ("output", "output_tokens"),
        ("total", "total_tokens"),
    )
    for _, _, record in iter_records(home):
        kind = record.get("kind")
        if record.get("session") != session_id or kind not in {
            "assistant_usage",
            "model_invocation_completed",
        }:
            continue
        usage = record if kind == "assistant_usage" else record.get("usage")
        if not isinstance(usage, dict):
            continue
        message_count += 1
        if source_kind is None:
            source_kind = kind
        elif source_kind != kind:
            source_kind = None
        for target, source in field_sources:
            value = usage.get(source)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[target] = (totals[target] or 0) + value
        if "reasoning_tokens" in usage:
            value = usage.get("reasoning_tokens")
            if isinstance(value, int) and not isinstance(value, bool):
                reasoning_seen = True
                reasoning_total += value
    result: dict[str, int | None | str] = dict(totals)
    result["reasoning"] = reasoning_total if reasoning_seen else None
    result["message_count"] = message_count
    result["source_kind"] = source_kind
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


def operational_report(home: Path, since: str | None = None) -> dict:
    """Aggregate bounded operational counters in one deterministic pass."""
    tokens: dict[str, int | None] = {
        "input": None, "output": None, "total": None,
        "cache_read": None, "cache_write": None,
    }
    counts = {
        "tool_calls": 0, "tool_result_bytes": 0, "file_reads": 0,
        "file_rereads": 0, "compactions": 0, "driver_events": 0,
        "worker_events": 0, "background_events": 0, "tool_errors": 0,
        "extension_errors": 0, "heartbeat_runs": 0, "fingerprint_events": 0,
        "optimization_events": 0, "validation_issues": 0,
    }
    seen_targets: set[str] = set()
    for _, _, record in iter_records(home):
        if not isinstance(record, dict) or "__parse_error__" in record:
            continue
        if since and (_ts(record) or "") < since:
            continue
        kind = record.get("kind")
        if kind == "assistant_usage":
            for field, source in (
                ("input", "input_tokens"), ("output", "output_tokens"),
                ("total", "total_tokens"), ("cache_read", "cache_read_tokens"),
                ("cache_write", "cache_write_tokens"),
            ):
                value = record.get(source)
                if isinstance(value, int) and not isinstance(value, bool):
                    current = tokens[field]
                    tokens[field] = value if current is None else current + value
        if kind == "tool_call":
            counts["tool_calls"] += 1
            if record.get("tool") == "read":
                counts["file_reads"] += 1
                target = record.get("target_sha256")
                if isinstance(target, str) and target:
                    if target in seen_targets:
                        counts["file_rereads"] += 1
                    seen_targets.add(target)
        if kind == "tool_result":
            output_bytes = record.get("output_bytes")
            if (
                isinstance(output_bytes, int)
                and not isinstance(output_bytes, bool)
                and output_bytes >= 0
            ):
                counts["tool_result_bytes"] += output_bytes
            if record.get("is_error") is True:
                counts["tool_errors"] += 1
        if kind == "session_compact":
            counts["compactions"] += 1
        if kind == "extension_error":
            counts["extension_errors"] += 1
        if kind == "heartbeat_pulse":
            if record.get("ran") is True:
                counts["heartbeat_runs"] += 1
            issue_codes = record.get("issue_codes")
            if isinstance(issue_codes, list):
                counts["validation_issues"] += len(issue_codes)
        if kind == "bottleneck_fingerprint":
            counts["fingerprint_events"] += 1
        if kind in _P4_OPTIMIZATION_KINDS:
            counts["optimization_events"] += 1

        roles = {
            value.lower()
            for field in ("role", "bot_role", "role_profile", "worker_role", "parent_role")
            if isinstance(value := record.get(field), str)
        }
        if roles & {"driver", "integrator", "orchestrator", "hard_orchestrator"}:
            counts["driver_events"] += 1
        if roles & {"worker", "dev", "validator", "explorer", "verifier"}:
            counts["worker_events"] += 1
        harness = record.get("harness")
        if (
            isinstance(harness, str)
            and harness.lower() in {"background", "daemon", "cron"}
        ) or "background" in roles:
            counts["background_events"] += 1

    return {"provider_tokens": tokens, **counts}


def report(home: Path, *, since: str | None = None) -> dict:
    """Aggregate telemetry into a compact report (deterministic)."""
    records = [
        rec for _, _, rec in iter_records(home)
        if isinstance(rec, dict) and "__parse_error__" not in rec
    ]
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

    result = {
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
    result["operational"] = operational_report(home, since=since)
    return result


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
_APPEND_FIELDS = {
    "heartbeat_pulse": set(_HEARTBEAT_FIELDS),
    "bottleneck_fingerprint": {
        "fingerprint_id", "category", "scope_id", "occurrence_count",
        "impact_score", "evidence_count", "evidence_hash",
    },
}
for _optimization_kind in _P4_OPTIMIZATION_KINDS:
    _APPEND_FIELDS[_optimization_kind] = {
        "proposal_id", "status", "intervention_hash", "evidence_hash",
        "approval_state", "rollback_state",
    }


def _safe_stem(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", session_id)[:128] or "unknown"


def append_record(
    home: Path | str,
    session_id: str,
    kind: str,
    fields: dict | None = None,
    **extra: object,
) -> dict:
    """Append one validated, privacy-safe telemetry record.

    The writer allowlists bounded fields for P4 records: prompts, payloads,
    secrets, and chain-of-thought fields never reach the JSONL store.
    """
    sid = str(session_id)
    if not sid or sid in {".", ".."} or sid != Path(sid).name or "\x00" in sid:
        raise ValueError("session id must remain within telemetry directory")
    if kind not in _APPEND_FIELDS:
        raise ValueError(f"unsupported append kind: {kind!r}")
    payload = dict(fields or {})
    payload.update(extra)
    safe = {key: payload[key] for key in _APPEND_FIELDS[kind] if key in payload}
    if kind == "heartbeat_pulse":
        safe.setdefault("mode", "shadow")
        safe.setdefault("event", "")
        safe.setdefault("due", False)
        safe.setdefault("ran", False)
        safe.setdefault("healthy", False)
        safe.setdefault("db_ok", False)
        safe.setdefault("cache_pruned_count", 0)
        safe.setdefault("git_dirty", False)
        safe.setdefault("issue_codes", [])
        safe.setdefault("latency_ms", 0)
        safe.setdefault("model_tokens_used", 0)
    record = {
        "v": KIND_SCHEMA_VERSION.get(kind, SCHEMA_VERSION),
        "kind": kind,
        "session": sid[:256],
        "ts": datetime.now(UTC).isoformat(),
        **safe,
    }
    issues = _record_issues(record, "record")
    if issues:
        raise ValueError(issues[0])
    tdir = telemetry_dir(Path(home))
    path = tdir / f"{_safe_stem(sid)}.jsonl"
    try:
        if path.resolve().parent != tdir.resolve():
            raise ValueError("session filename escapes telemetry directory")
    except OSError as exc:
        raise ValueError("invalid telemetry path") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
    return record




