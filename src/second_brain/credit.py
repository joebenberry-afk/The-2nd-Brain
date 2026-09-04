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
import os
import sqlite3
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db, plasticity, router, telemetry
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
