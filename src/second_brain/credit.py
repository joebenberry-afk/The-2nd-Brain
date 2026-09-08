"""Credit assignment (plan §43-44/§114, Phase 18).

NO_AUTO_REWARD invariant: nothing in this module — and no combination of
outcome recording + routing — creates credit_events automatically. The ONLY
writer is :func:`assign_credit`, which requires the caller to state levels
explicitly (plan §43: task success must never reward every active skill).

Counterfactual evaluation (plan §44) has two layers, kept structurally
distinct (predicted effect vs. observed effect):

- :func:`routing_counterfactual` / :func:`eval_skill_credit` — the PREDICTED
  effect: routes each task WITH and WITHOUT one shadow skill via the
  router's ``skills`` override (no filesystem mutation) and reports routing
  deltas; INERT recommendations only, nothing is written.
- :func:`counterfactual_result` — the OBSERVED effect: a bounded,
  same-starting-state with/without comparison across all six §44
  dimensions (success, tokens, tools, time, verification, regressions),
  built from real evidence the caller already collected (telemetry usage,
  P3.7/P3.8 verification outcomes, regression test evidence) — never
  self-reported or fabricated. A :func:`routing_counterfactual` result may be
  embedded as ``predicted_effect`` alongside it; the two are never
  conflated. Harness-neutral: applies identically to skills, memories,
  routing policies, Scout, and verification policy via one
  ``intervention_type`` enum, not five separate evaluators.
"""

from __future__ import annotations

import contextlib
import enum
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import build_identity, contracts, db, decisions, plasticity, router, telemetry
from .errors import BrainError

CREDIT_LEVELS: tuple[str, ...] = plasticity.CREDIT_LEVELS


class CreditClass(enum.StrEnum):
    DIRECT = "DIRECT"
    CONTRIBUTORY = "CONTRIBUTORY"
    CORRELATED = "CORRELATED"
    UNRELATED_NEGATIVE = "UNRELATED_NEGATIVE"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (str, enum.Enum)):
            val = other.value if isinstance(other, enum.Enum) else other
            return self.value.upper() == str(val).upper()
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash(self.value.upper())


def classify_credit(evidence: Mapping[str, Any] | Any) -> str:
    """Classify credit evidence into design-derived causal classes.

    Rules:
    - If evidence is not a mapping: CORRELATED
    - Paired design with negative effect: UNRELATED_NEGATIVE
    - Paired design with significant interaction:
        CONTRIBUTORY if verdict != INSUFFICIENT else CORRELATED
    - Holdout or paired design with verdict != INSUFFICIENT: DIRECT
    - Otherwise: CORRELATED
    """
    if not isinstance(evidence, Mapping):
        return CreditClass.CORRELATED

    design = str(evidence.get("design") or "").lower()

    econ = evidence.get("economics")
    econ_verdict = econ.get("verdict") if isinstance(econ, Mapping) else None
    verdict = str(evidence.get("verdict") or econ_verdict or "").upper()

    effect = (
        evidence.get("effect")
        if evidence.get("effect") is not None
        else evidence.get("r_bar")
        if evidence.get("r_bar") is not None
        else evidence.get("effect_size")
    )
    effect_num: float | None = None
    if effect is not None:
        try:
            effect_num = float(effect)
        except (ValueError, TypeError):
            effect_num = None

    if design == "paired" and effect_num is not None and effect_num < 0:
        return CreditClass.UNRELATED_NEGATIVE

    has_interaction = bool(
        evidence.get("interaction_significant")
        or evidence.get("interaction_term")
        or evidence.get("has_interaction")
        or evidence.get("significant_interaction")
    )
    if design == "paired" and has_interaction:
        return CreditClass.CONTRIBUTORY if verdict != "INSUFFICIENT" else CreditClass.CORRELATED

    if design in ("holdout", "paired") and verdict != "INSUFFICIENT":
        return CreditClass.DIRECT

    return CreditClass.CORRELATED


# Deterministic subject-kind inference contract (assign_credit).
_SKILL_DIRS = ("skills/shadow", "skills/candidates")
_MEMORY_PREFIX = "mem-"
_KIND_PREFIXES = {
    "tool:": "tool",
    "scout:": "scout",
    "verification:": "verification",
    "policy:": "policy",
}
_BARE_IDS = {"scout": "scout"}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _infer_kind(home: Path, subject_id: str) -> str:
    """Map a subject id to a subject_kind, or raise BrainError for unknowns."""
    for directory in _SKILL_DIRS:
        if (Path(home) / directory / subject_id).is_dir():
            return "skill"
    if subject_id.startswith(_MEMORY_PREFIX):
        return "memory"
    for prefix, kind in _KIND_PREFIXES.items():
        if subject_id.startswith(prefix):
            return kind
    if subject_id in _BARE_IDS:
        return _BARE_IDS[subject_id]
    raise BrainError(
        f"Unknown credit subject {subject_id!r}: not a skill, memory, or "
        "prefixed (tool:/scout:/verification:/policy:) id"
    )


def assign_credit(
    home: Path,
    session_id: str | None,
    *,
    direct: list[str],
    contributory: list[str],
    correlated: list[str],
) -> dict:
    """Insert one credit_event per (subject, level). The ONLY credit writer;
    levels are always explicit. Returns per-level counts."""
    counts = {"direct": 0, "contributory": 0, "correlated": 0, "total": 0}
    for level, subject_ids in (
        ("direct", direct),
        ("contributory", contributory),
        ("correlated", correlated),
    ):
        if not isinstance(subject_ids, list):
            raise BrainError(f"{level} must be a list of subject ids")
        for subject_id in subject_ids:
            if not isinstance(subject_id, str) or not subject_id.strip():
                raise BrainError(f"{level} contains an invalid subject id {subject_id!r}")
            kind = _infer_kind(home, subject_id)
            plasticity.record_credit(home, session_id, subject_id, kind, level)
            counts[level] += 1
            counts["total"] += 1
    return counts


def credit_report(home: Path, session_id: str | None = None) -> dict:
    """Per (subject_id, subject_kind) counts by level; deterministic."""
    conn = db.connect(db.db_path(home))
    try:
        try:
            if session_id is not None:
                rows = conn.execute(
                    "SELECT subject_id, subject_kind, credit_level FROM credit_events "
                    "WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT subject_id, subject_kind, credit_level FROM credit_events"
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return {"total_events": 0, "subjects": []}  # nothing assigned yet
            raise
    finally:
        conn.close()
    subjects: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        key = (row["subject_id"], row["subject_kind"])
        entry = subjects.setdefault(key, {level: 0 for level in CREDIT_LEVELS})
        entry[row["credit_level"]] += 1
    entries = [
        {
            "subject_id": key[0],
            "subject_kind": key[1],
            **{level: data[level] for level in CREDIT_LEVELS},
            "total": sum(data.values()),
        }
        for key, data in sorted(subjects.items())
    ]
    return {"total_events": len(rows), "subjects": entries}


def _shadow_names(home: Path) -> list[str]:
    directory = Path(home) / "skills" / "shadow"
    return sorted(p.name for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []


def routing_counterfactual(home: Path, skill_name: str, tasks: list[dict]) -> dict:
    """Local counterfactual (plan §44): route each task with and without one
    shadow skill (router `skills` override — no filesystem mutation).
    delta_tools is unobservable here and reported honestly as 0."""
    if not isinstance(skill_name, str) or not skill_name.strip():
        raise BrainError("skill_name must be a non-empty string")
    all_names = _shadow_names(home)
    if skill_name not in all_names:
        raise BrainError(f"No shadow skill {skill_name!r}")
    without = [name for name in all_names if name != skill_name]
    per_task = []
    affected = 0
    for task in tasks:
        text = str(task.get("text", ""))
        with_skill = router.route(home, text, skills=all_names)["selected"]
        without_skill = router.route(home, text, skills=without)["selected"]
        changed = with_skill != without_skill
        affected += 1 if changed else 0
        per_task.append(
            {
                "text": text,
                "selected_with": with_skill,
                "selected_without": without_skill,
                "delta_tools": 0,  # unobservable from the Python side
                "routed_change": changed,
            }
        )
    report = {
        "skill": skill_name,
        "tasks": per_task,
        "tasks_affected": affected,
        "tasks_unaffected": len(tasks) - affected,
    }
    _write_report(home, skill_name, report)
    return report


def _write_report(home: Path, skill_name: str, report: dict) -> Path:
    out_dir = Path(home) / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"counterfactual-{skill_name}.md"
    lines = [
        "# Counterfactual Eval",
        "",
        f"skill: {skill_name}",
        f"generated_at: {_utcnow()}",
        f"tasks: {len(report['tasks'])} (affected {report['tasks_affected']}, "
        f"unaffected {report['tasks_unaffected']})",
        "",
        "| task | with | without | changed |",
        "|---|---|---|---|",
    ]
    for task in report["tasks"]:
        lines.append(
            f"| {task['text'][:60]} | {', '.join(task['selected_with']) or '-'} | "
            f"{', '.join(task['selected_without']) or '-'} | {task['routed_change']} |"
        )
    content = "\n".join(lines) + "\n"
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write counterfactual report {target}: {exc}") from exc
    return target


def eval_skill_credit(home: Path, skill_name: str, tasks: list[dict]) -> dict:
    """Counterfactual + INERT credit recommendations (direct/contributory/
    correlated). Nothing is written — recommendations are text only."""
    eval_result = routing_counterfactual(home, skill_name, tasks)
    expect_by_text = {str(task.get("text", "")): set(task.get("expect") or []) for task in tasks}
    recommendations: dict[str, int] = {"direct": 0, "contributory": 0, "correlated": 0}
    per_task: list[dict] = []
    for task in eval_result["tasks"]:
        if not task["routed_change"]:
            per_task.append({**task, "recommendation": None})
            continue
        expected = expect_by_text.get(task["text"], set())
        if skill_name in expected:
            level = "direct"
        elif skill_name in task["selected_with"] and len(task["selected_with"]) > 1:
            level = "contributory"
        else:
            level = "correlated"
        recommendations[level] += 1
        per_task.append({**task, "recommendation": level})
    return {
        "skill": skill_name,
        "tasks": per_task,
        "recommendations": recommendations,
        "note": "recommendations only; nothing was written (NO_AUTO_REWARD)",
    }


# ---------------------------------------------------------------------------
# Counterfactual result (plan §44, observed effect)
# ---------------------------------------------------------------------------

# Harness-neutral intervention classes §44 names explicitly. One evaluator,
# not five: every class flows through the same counterfactual_result().
INTERVENTION_TYPES: tuple[str, ...] = (
    "skill",
    "memory",
    "routing_policy",
    "scout",
    "verification_policy",
)

# Reuse verify.py's exact action-state vocabulary (evaluate_accuracy_gate)
# so "verification" comes from the existing P3.7/P3.8 evidence, not a new
# enum invented here.
VERIFICATION_OUTCOMES: tuple[str, ...] = ("passed", "failed", "unresolved")

# Real telemetry counters only (brainstem/telemetry/SCHEMA.md assistant_usage
# field names). "reasoning" and "cache_write" are tracked separately from the
# mandatory fields because not every harness's real usage schema reports
# them (e.g. the Antigravity/Gemini `agy` CLI stream never includes a
# cache-write counter at all) — they must never be fabricated as 0 when the
# provider genuinely does not expose the concept.
TOKEN_FIELDS: tuple[str, ...] = ("input", "cache_read", "output", "total")
OPTIONAL_TOKEN_FIELDS: tuple[str, ...] = ("cache_write", "reasoning")

STARTING_STATE_FIELDS: tuple[str, ...] = (
    "task_hash",
    "repository_state_hash",
    "requirements_hash",
    "model_config_hash",
    "available_tools_hash",
    "environment_hash",
)


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _validate_tokens(tokens: object, label: str) -> dict:
    if not isinstance(tokens, dict):
        raise BrainError(f"{label}.tokens must be a dict")
    out: dict[str, int | None] = {}
    for field in TOKEN_FIELDS:
        value = tokens.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise BrainError(f"{label}.tokens.{field} must be a non-negative integer")
        out[field] = value
    for field in OPTIONAL_TOKEN_FIELDS:
        value = tokens.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise BrainError(f"{label}.tokens.{field} must be a non-negative integer or None")
        out[field] = value
    return out


def _validate_verification(verification: object, label: str) -> dict:
    if not isinstance(verification, dict):
        raise BrainError(f"{label}.verification must be a dict")
    outcome = verification.get("outcome")
    if outcome not in VERIFICATION_OUTCOMES:
        raise BrainError(f"{label}.verification.outcome must be one of {VERIFICATION_OUTCOMES}")
    evidence_ref = verification.get("evidence_ref")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise BrainError(f"{label}.verification.evidence_ref must be a non-empty string")
    return {"outcome": outcome, "evidence_ref": evidence_ref}


def _validate_regressions(regressions: object, label: str) -> dict:
    if not isinstance(regressions, dict):
        raise BrainError(f"{label}.regressions must be a dict")
    count = regressions.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise BrainError(f"{label}.regressions.count must be a non-negative integer")
    evidence_ref = regressions.get("evidence_ref")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise BrainError(f"{label}.regressions.evidence_ref must be a non-empty string")
    return {"count": count, "evidence_ref": evidence_ref}


def _validate_arm(arm: object, label: str) -> dict:
    if not isinstance(arm, dict):
        raise BrainError(f"{label} must be a dict")
    run_id = arm.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise BrainError(f"{label}.run_id must be a non-empty string")
    success = arm.get("success")
    if not isinstance(success, bool):
        raise BrainError(f"{label}.success must be a bool")
    tool_calls = arm.get("tool_calls")
    if not isinstance(tool_calls, int) or isinstance(tool_calls, bool) or tool_calls < 0:
        raise BrainError(f"{label}.tool_calls must be a non-negative integer")
    wall_time_ms = arm.get("wall_time_ms")
    if (
        not isinstance(wall_time_ms, (int, float))
        or isinstance(wall_time_ms, bool)
        or wall_time_ms < 0
    ):
        raise BrainError(f"{label}.wall_time_ms must be a non-negative number")
    return {
        "run_id": run_id,
        "success": success,
        "tokens": _validate_tokens(arm.get("tokens"), label),
        "tool_calls": tool_calls,
        "wall_time_ms": float(wall_time_ms),
        "verification": _validate_verification(arm.get("verification"), label),
        "regressions": _validate_regressions(arm.get("regressions"), label),
    }


def _validate_starting_state(starting_state: object) -> dict:
    if not isinstance(starting_state, dict):
        raise BrainError("starting_state must be a dict")
    out: dict[str, str] = {}
    for field in STARTING_STATE_FIELDS:
        value = starting_state.get(field)
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"starting_state.{field} must be a non-empty string")
        out[field] = value
    return out


def _token_deltas(with_tokens: dict, without_tokens: dict) -> dict:
    deltas = {field: with_tokens[field] - without_tokens[field] for field in TOKEN_FIELDS}
    for field in OPTIONAL_TOKEN_FIELDS:
        with_value = with_tokens[field]
        without_value = without_tokens[field]
        deltas[field] = (
            with_value - without_value
            if with_value is not None and without_value is not None
            else None
        )
    return deltas


def counterfactual_result(
    home: Path,
    *,
    evaluation_id: str,
    intervention_type: str,
    intervention_id: str,
    intervention_hash: str,
    starting_state: dict,
    with_arm: dict,
    without_arm: dict,
    predicted_effect: dict | None = None,
) -> dict:
    """§44 OBSERVED counterfactual result: one bounded, same-starting-state
    with(A)/without(B) comparison across success, tokens, tools, time,
    verification, and regressions.

    ``starting_state`` is a single shared argument (not supplied per arm),
    which structurally enforces the "same starting state" invariant — the
    two arms cannot diverge on it. ``with_arm``/``without_arm`` must carry
    distinct ``run_id``s (genuinely separate executions) and real evidence:
    tokens/tool_calls/wall_time from telemetry (see :func:`arm_from_telemetry`),
    ``verification`` from existing P3.7/P3.8 gate evidence (never
    self-reported), ``regressions`` from existing test evidence. Zero is a
    valid, measured value everywhere; nothing here is hardcoded or invented.
    Optionally embeds a :func:`routing_counterfactual` result as
    ``predicted_effect`` — the routing-selection PREDICTION, kept structurally
    distinct from this function's OBSERVED execution effect.
    """
    if not isinstance(evaluation_id, str) or not evaluation_id.strip():
        raise BrainError("evaluation_id must be a non-empty string")
    if intervention_type not in INTERVENTION_TYPES:
        raise BrainError(f"intervention_type must be one of {INTERVENTION_TYPES}")
    if not isinstance(intervention_id, str) or not intervention_id.strip():
        raise BrainError("intervention_id must be a non-empty string")
    if not isinstance(intervention_hash, str) or not intervention_hash.strip():
        raise BrainError("intervention_hash must be a non-empty string")
    state = _validate_starting_state(starting_state)
    with_result = _validate_arm(with_arm, "with_arm")
    without_result = _validate_arm(without_arm, "without_arm")
    if with_result["run_id"] == without_result["run_id"]:
        raise BrainError(
            "with_arm and without_arm must be genuinely separate runs (distinct run_id)"
        )
    started = time.perf_counter()
    starting_state_hash = _stable_hash(state)

    with_verdict = with_result["verification"]["outcome"]
    without_verdict = without_result["verification"]["outcome"]
    if with_result["success"] and without_result["success"]:
        success_delta = "both_succeeded"
    elif with_result["success"] and not without_result["success"]:
        success_delta = "with_only"
    elif not with_result["success"] and without_result["success"]:
        success_delta = "without_only"
    else:
        success_delta = "neither_succeeded"

    deltas = {
        "success": success_delta,
        "tokens": _token_deltas(with_result["tokens"], without_result["tokens"]),
        "tool_calls": with_result["tool_calls"] - without_result["tool_calls"],
        "wall_time_ms": with_result["wall_time_ms"] - without_result["wall_time_ms"],
        "verification": (
            "same" if with_verdict == without_verdict else f"{without_verdict}->{with_verdict}"
        ),
        "regressions": with_result["regressions"]["count"] - without_result["regressions"]["count"],
    }

    result = {
        "schema_version": 1,
        "evaluation_id": evaluation_id,
        "intervention": {
            "type": intervention_type,
            "id": intervention_id,
            "hash": intervention_hash,
        },
        "starting_state": state,
        "starting_state_hash": starting_state_hash,
        "with_arm": with_result,
        "without_arm": without_result,
        "observed_effect": {"deltas": deltas},
        "predicted_effect": predicted_effect,
        "evaluator_economics": {
            "evaluation_model_calls": 0,
            "evaluation_tokens": 0,
            "evaluation_tool_calls": 0,
            "bookkeeping_wall_time_ms": round((time.perf_counter() - started) * 1000, 3),
        },
        "created_at": _utcnow(),
    }
    _write_counterfactual_result(home, result)
    return result


def _write_counterfactual_result(home: Path, result: dict) -> Path:
    intervention = result["intervention"]
    out_dir = Path(home) / "outputs" / "audits" / "counterfactual" / intervention["type"]
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{intervention['id']}-{result['evaluation_id']}.json"
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write counterfactual result {target}: {exc}") from exc
    return target


def is_counterfactual_result_current(result: dict, current_intervention_hash: str) -> bool:
    """§44 treatment-identity check: a result only describes the exact
    intervention version it was computed against. A changed intervention
    (new hash) makes stale evidence detectable rather than silently reused."""
    intervention = result.get("intervention")
    return isinstance(intervention, dict) and intervention.get("hash") == current_intervention_hash


def arm_from_telemetry(
    home: Path,
    session_id: str,
    *,
    success: bool,
    verification: dict,
    regressions: dict,
) -> dict:
    """Build one counterfactual arm from REAL current telemetry for one
    session: token usage (:func:`telemetry.session_usage`), tool-call count
    (:func:`telemetry.session_tool_calls`), and wall time
    (:func:`telemetry.session_wall_time_ms`). ``success``/``verification``/
    ``regressions`` are supplied by the caller from existing requirement,
    P3.7/P3.8 verification, and test evidence — never derived from telemetry
    or model self-report."""
    wall_time_ms = telemetry.session_wall_time_ms(home, session_id)
    if wall_time_ms is None:
        raise BrainError(
            f"No measurable telemetry for session {session_id!r}: at least two "
            "timestamped records are required for a real wall-time measurement. "
            "A missing or absent session must be rejected, never reported as a "
            "zero-valued arm."
        )
    usage = telemetry.session_usage(home, session_id)
    missing = [field for field in TOKEN_FIELDS if usage.get(field) is None]
    if missing:
        raise BrainError(
            f"Session {session_id!r} has missing required token counters: {', '.join(missing)}"
        )
    return {
        "run_id": session_id,
        "success": success,
        "tokens": {field: usage[field] for field in (*TOKEN_FIELDS, *OPTIONAL_TOKEN_FIELDS)},
        "tool_calls": telemetry.session_tool_calls(home, session_id),
        "wall_time_ms": wall_time_ms,
        "verification": verification,
        "regressions": regressions,
    }


def _validate_prior_expectation(
    expected_outcome: Mapping[str, Any],
    baseline_ref: str,
) -> dict[str, Any]:
    if not isinstance(baseline_ref, str) or not baseline_ref.strip():
        raise BrainError("Intervention requires a non-empty baseline_ref")

    expected = dict(expected_outcome)
    required = ("metric", "direction", "expected_range", "horizon", "confidence", "evaluator")
    missing = [key for key in required if key not in expected]
    if missing:
        raise BrainError("Intervention requires prior causal fields: " + ", ".join(missing))
    if not isinstance(expected["metric"], str) or not expected["metric"].strip():
        raise BrainError("Intervention requires a non-empty metric")
    if expected["direction"] not in {"increase", "decrease", "unchanged", "pass"}:
        raise BrainError("Intervention direction must be increase, decrease, unchanged, or pass")
    expected_range = expected["expected_range"]
    if (
        not isinstance(expected_range, (list, tuple))
        or len(expected_range) != 2
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in expected_range
        )
        or float(expected_range[0]) > float(expected_range[1])
    ):
        raise BrainError("Intervention expected_range must contain two ordered finite numbers")
    horizon = expected["horizon"]
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
        raise BrainError("Intervention horizon must be a positive integer")
    confidence = expected["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 < float(confidence) <= 1
    ):
        raise BrainError("Intervention confidence must be a finite number in (0, 1]")
    if not isinstance(expected["evaluator"], str) or not expected["evaluator"].strip():
        raise BrainError("Intervention evaluator must be non-empty text")

    measurable = ("expected_delta", "expected_value", "expected_pass")
    if not any(key in expected for key in measurable):
        raise BrainError("Intervention requires prior measurable expected_outcome")
    return expected


def record_intervention(
    home: Path | str,
    intervention_type: str,
    target_ref: str,
    expected_outcome: Mapping[str, Any],
    baseline_ref: str,
    *,
    decision_ref: str | None = None,
    policy_version: str = "v7.5",
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Record an adaptive intervention with prior measurable expected outcome.

    Rule: Every adaptive intervention records an expected measurable outcome
    before execution. Free-form expectation or missing expectation is rejected.
    """
    home_p = Path(home)
    if db.pending_migrations(db.db_path(home_p)):
        db.migrate(db.db_path(home_p))

    if not isinstance(expected_outcome, Mapping) or not expected_outcome:
        raise BrainError(
            "Intervention requires non-empty prior measurable expected_outcome mapping"
        )
    if not any(
        key in expected_outcome
        for key in ("metric", "expected_delta", "expected_value", "expected_pass")
    ):
        raise BrainError("Intervention requires prior measurable expected_outcome")
    expected_dict = _validate_prior_expectation(expected_outcome, baseline_ref)
    now = datetime.now(UTC).isoformat()
    intervention_dict = {
        "intervention_type": str(intervention_type),
        "target_ref": str(target_ref),
        "baseline_ref": str(baseline_ref),
    }

    identity_str = (
        f"{intervention_type}:{target_ref}:{baseline_ref}:{contracts.canonical_json(expected_dict)}"
    )
    intervention_id = "intv-" + hashlib.sha256(identity_str.encode("utf-8")).hexdigest()[:24]
    provenance_hash = hashlib.sha256(
        contracts.canonical_json(
            {"intervention": intervention_dict, "expected": expected_dict}
        ).encode("utf-8")
    ).hexdigest()

    conn = db.connect(db.db_path(home_p))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT OR REPLACE INTO v2_interventions(
                intervention_id, intervention_type, target_ref, expected_json,
                baseline_ref, decision_ref, status, policy_version, provenance_hash,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
            (
                intervention_id,
                intervention_type,
                target_ref,
                contracts.canonical_json(expected_dict),
                baseline_ref,
                decision_ref,
                policy_version,
                provenance_hash,
                now,
                now,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record intervention: {exc}") from exc
    finally:
        conn.close()

    dec_ref = decisions.record(
        home_p,
        kind="learning",
        session_id=session_id or f"sess-{intervention_id}",
        task_id=task_id or f"task-{intervention_id}",
        chosen={
            "action": "record_intervention",
            "intervention_id": intervention_id,
            "status": "PENDING",
        },
        alternatives=[{"action": "no_intervention"}],
        propensity=1.0,
        randomized=False,
        policy_version=policy_version,
        stage="SHADOW",
        inputs={
            "target_ref": target_ref,
            "expected": expected_dict,
            "baseline_ref": baseline_ref,
        },
    )

    return {
        "intervention_id": intervention_id,
        "intervention_type": intervention_type,
        "target_ref": target_ref,
        "expected_outcome": expected_dict,
        "baseline_ref": baseline_ref,
        "decision_ref": dec_ref,
        "status": "PENDING",
        "provenance_hash": provenance_hash,
        "created_at": now,
    }


def _observation_evidence(
    home: Path,
    evidence_ref: str,
    classification: str,
    observed_data: Mapping[str, Any],
    target_ref: str,
) -> dict[str, Any]:
    requested_classification = str(classification).strip().lower()
    if requested_classification not in {"observed", "simulation"}:
        raise BrainError("evidence_classification must be 'observed' or 'simulation'")

    raw = Path(evidence_ref)
    path: Path | None = None
    if not raw.is_absolute() and ".." not in raw.parts:
        root = home.resolve()
        candidate = (root / raw).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            pass
        else:
            path = candidate

    artifact: dict[str, Any] = {}
    artifact_hash: str | None = None
    if path is not None and path.is_file():
        try:
            raw_artifact = path.read_bytes()
            loaded = json.loads(raw_artifact)
        except (OSError, UnicodeError, json.JSONDecodeError):
            loaded = None
        else:
            artifact_hash = hashlib.sha256(raw_artifact).hexdigest()
        if isinstance(loaded, dict):
            artifact = loaded

    artifact_classification = str(artifact.get("classification", "unknown")).strip().lower()
    derived_classification = (
        "simulation" if requested_classification == "simulation" else artifact_classification
    )
    feature = target_ref.removeprefix("policy:") if target_ref.startswith("policy:") else None
    repo = Path(__file__).resolve().parents[2]
    binding_matches = (
        derived_classification == "observed"
        and artifact.get("qualification_eligible") is True
        and isinstance(feature, str)
        and bool(feature)
        and artifact.get("feature") == feature
        and artifact.get("target_ref") == target_ref
        and isinstance(artifact.get("source_commit"), str)
        and artifact["source_commit"] == build_identity.git_sha(repo)
        and isinstance(artifact.get("source_tree_sha256"), str)
        and artifact["source_tree_sha256"] == build_identity.source_tree_fingerprint(repo)
        and isinstance(artifact.get("config_sha256"), str)
        and artifact["config_sha256"] == build_identity.configuration_fingerprint(home)
        and contracts.canonical_json(artifact.get("observed_data"))
        == contracts.canonical_json(dict(observed_data))
    )
    return {
        "classification": derived_classification,
        "path": evidence_ref,
        "sha256": artifact_hash,
        "feature": artifact.get("feature"),
        "target_ref": artifact.get("target_ref"),
        "source_commit": artifact.get("source_commit"),
        "source_tree_sha256": artifact.get("source_tree_sha256"),
        "config_sha256": artifact.get("config_sha256"),
        "qualification_eligible": binding_matches,
    }


def record_observation(
    home: Path | str,
    intervention_id: str,
    observed_data: Mapping[str, Any],
    evidence_ref: str,
    evidence_type: str,
    *,
    evaluator_ref: str = "evaluator-system",
    evidence_strength: float = 1.0,
    evidence_classification: str = "observed",
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Record bounded evidence; unresolved/simulated evidence remains non-promotable."""
    home_p = Path(home)
    if db.pending_migrations(db.db_path(home_p)):
        db.migrate(db.db_path(home_p))

    allowed_evidence_types = {
        "telemetry",
        "test_runner",
        "acceptance_check",
        "benchmark",
    }
    clean_ev_type = str(evidence_type).strip().lower()
    if (
        clean_ev_type not in allowed_evidence_types
        or "self_report" in clean_ev_type
        or "model_assertion" in clean_ev_type
    ):
        raise BrainError(
            "Model self-report is not an observation; requires telemetry or test evidence"
        )

    if not isinstance(observed_data, Mapping) or not observed_data:
        raise BrainError("observed_data must be a non-empty mapping")

    conn = db.connect(db.db_path(home_p))
    try:
        row = conn.execute(
            "SELECT * FROM v2_interventions WHERE intervention_id = ?",
            (intervention_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise BrainError(f"Unknown intervention {intervention_id!r}")

    expected_raw = row["expected_json"]
    if not expected_raw or expected_raw == "{}":
        raise BrainError("Cannot compute prediction error without prior expectation")

    expected_dict = json.loads(expected_raw)
    observed_dict = dict(observed_data)
    observed_dict["_evidence"] = _observation_evidence(
        home_p,
        evidence_ref,
        evidence_classification,
        observed_dict,
        str(row["target_ref"]),
    )
    metric_name = expected_dict.get("metric", "delta")
    exp_val = expected_dict.get(
        "expected_delta",
        expected_dict.get("expected_value", expected_dict.get("expected_pass")),
    )
    obs_val = observed_dict.get(
        metric_name,
        observed_dict.get(
            "delta",
            observed_dict.get("actual_delta", observed_dict.get("pass")),
        ),
    )

    if isinstance(exp_val, (int, float)) and isinstance(obs_val, (int, float)):
        pred_error = float(obs_val) - float(exp_val)
        rel_diff = abs(pred_error) / max(1.0, abs(float(exp_val)))
        surprise_score = min(1.0, round(rel_diff, 4))
    elif isinstance(exp_val, bool) and isinstance(obs_val, bool):
        pred_error = 0.0 if exp_val == obs_val else 1.0
        surprise_score = 0.0 if exp_val == obs_val else 1.0
    else:
        pred_error = 0.0
        surprise_score = 0.5

    prediction_error_dict = {
        "metric": metric_name,
        "expected": exp_val,
        "observed": obs_val,
        "error": pred_error,
    }

    design = observed_dict.get("design", "paired")
    effect = observed_dict.get(
        "effect",
        observed_dict.get(
            "r_bar",
            -pred_error if "token" in metric_name else obs_val,
        ),
    )
    verdict_str = observed_dict.get(
        "verdict",
        "POSITIVE" if effect and float(effect) > 0 else "INSUFFICIENT",
    )

    credit_evidence = {
        "design": design,
        "verdict": verdict_str,
        "effect": effect,
        "interaction_significant": observed_dict.get("interaction_significant", False),
    }
    derived_credit = classify_credit(credit_evidence)
    observed_dict["_credit_evidence"] = credit_evidence

    target_ref = row["target_ref"]
    if derived_credit == CreditClass.UNRELATED_NEGATIVE or (
        isinstance(effect, (int, float)) and effect < 0
    ):
        candidate_action = {
            "action": "demote_candidate",
            "target_ref": target_ref,
            "rollout_stage": "SHADOW",
            "reason": "negative_causal_effect",
            "effect_size": effect,
        }
    elif derived_credit in (CreditClass.DIRECT, CreditClass.CONTRIBUTORY) and surprise_score >= 0.2:
        candidate_action = {
            "action": "propose_candidate_update",
            "target_ref": target_ref,
            "rollout_stage": "SHADOW",
            "reason": "positive_causal_effect",
            "effect_size": effect,
        }
    else:
        candidate_action = {
            "action": "hold_candidate",
            "target_ref": target_ref,
            "rollout_stage": "SHADOW",
            "reason": "unverified_or_immaterial_surprise",
            "effect_size": effect,
        }

    now = datetime.now(UTC).isoformat()
    obs_id = (
        "obs-" + hashlib.sha256(f"{intervention_id}:{evidence_ref}:{now}".encode()).hexdigest()[:24]
    )
    prov_hash = hashlib.sha256(
        contracts.canonical_json({"obs": observed_dict, "pred_err": prediction_error_dict}).encode(
            "utf-8"
        )
    ).hexdigest()

    conn = db.connect(db.db_path(home_p))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO v2_observations(
                observation_id, intervention_id, observed_json, prediction_error_json,
                surprise_score, evidence_strength, credit_class, evaluator_ref,
                evidence_type, candidate_action_json, provenance_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                obs_id,
                intervention_id,
                contracts.canonical_json(observed_dict),
                contracts.canonical_json(prediction_error_dict),
                float(surprise_score),
                float(evidence_strength),
                str(derived_credit),
                evaluator_ref,
                clean_ev_type,
                contracts.canonical_json(candidate_action),
                prov_hash,
                now,
            ),
        )
        conn.execute(
            "UPDATE v2_interventions SET status = 'OBSERVED', updated_at = ? "
            "WHERE intervention_id = ?",
            (now, intervention_id),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise BrainError(f"Could not record observation: {exc}") from exc
    finally:
        conn.close()

    decisions.record(
        home_p,
        kind="learning",
        session_id=session_id or f"sess-{obs_id}",
        task_id=task_id or f"task-{obs_id}",
        chosen={
            "observation_id": obs_id,
            "intervention_id": intervention_id,
            "credit_class": str(derived_credit),
            "candidate_action": candidate_action["action"],
            "rollout_stage": "SHADOW",
        },
        alternatives=[],
        propensity=1.0,
        randomized=False,
        policy_version="v7.5",
        stage="SHADOW",
        inputs={
            "intervention_id": intervention_id,
            "surprise_score": surprise_score,
            "prediction_error": prediction_error_dict,
            "credit_class": str(derived_credit),
        },
    )

    return {
        "observation_id": obs_id,
        "intervention_id": intervention_id,
        "observed_data": observed_dict,
        "prediction_error": prediction_error_dict,
        "surprise_score": surprise_score,
        "credit_class": str(derived_credit),
        "candidate_action": candidate_action,
        "evidence_type": clean_ev_type,
        "evaluator_ref": evaluator_ref,
        "qualification_eligible": observed_dict["_evidence"]["qualification_eligible"],
        "provenance_hash": prov_hash,
        "created_at": now,
    }
