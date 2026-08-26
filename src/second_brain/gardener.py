"""
Skill ROI Tracking & Skill Gardener (Plan §3 P3.14, P3.15).

Capabilities:
1. P3.14 Skill ROI Layer:
   - Composes existing evidence into a version-bound Skill ROI record:
     P3.10 Improvement Radar (state/radar/candidates.json
     expected_benefit_tokens) supplies the ESTIMATED figure; P3.11 Skill
     Forge evaluation (evaluation.json roi.net_tokens_saved) or P3.13
     counterfactual_result (outputs/audits/counterfactual/**/*.json
     observed_effect.deltas) supplies the MEASURED figure. Neither is
     recomputed here — P3.13 remains the authority for observed
     counterfactual measurements; P3.14 consumes and summarizes them.
   - Every record is bound to the skill's exact current content hash
     (skillforge.lifecycle_content_hash); evidence for a different version
     is rejected as stale, never silently reused.
   - A missing measurement is never coerced to 0: measurement_state
     distinguishes measured / estimated_only / unavailable, and the
     existing net_tokens_saved/roi_ratio/success_rate/SkillHealth
     arithmetic is computed ONLY over measured rows.
   - A first-class measured-vs-estimated comparison (estimation error and
     classification) is produced whenever both figures are known.
2. P3.15 Skill Gardener:
   - Evaluates portfolio health across all skills.
   - Flags degraded/negative-ROI skills for review or automated deprecation
     (read-only reporting; no automatic promotion/retirement is performed
     here — that remains P3.15's own frozen contract).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import paths, skillforge, telemetry
from .errors import BrainError
from .radar import ImprovementRadar

_MAX_EVIDENCE_REFS = 32
_MAX_REFERENCE_LENGTH = 256
_MAX_AUDIT_FINDINGS = 32
_ISSUE_TYPES = {
    "evidence_stale": "stale",
    "dead_skill": "broken",
    "capability_overlap": "duplicate",
    "false_trigger": "broken",
    "measured_zero_use": "unused",
    "measured_negative": "negative_roi",
    "exact_duplicate": "duplicate",
    "scope_too_broad": "broken",
    "scope_too_narrow": "broken",
    "model_specific_quirk": "broken",
    "superseded": "superseded",
}



def _bounded_refs(*values: object) -> list[str]:
    """Return only short, string evidence references from persisted metadata."""
    refs: list[str] = []
    for value in values:
        if not isinstance(value, list):
            continue
        for ref in value:
            if isinstance(ref, str) and ref and ref not in refs:
                refs.append(ref[:_MAX_REFERENCE_LENGTH])
                if len(refs) >= _MAX_EVIDENCE_REFS:
                    return refs
    return refs


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_roi_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    session_id TEXT NOT NULL,
    skill_version TEXT,
    tokens_invested INTEGER NOT NULL,
    tokens_saved INTEGER NOT NULL,
    success INTEGER NOT NULL,
    measurement_state TEXT NOT NULL DEFAULT 'measured',
    estimated_tokens_saved INTEGER,
    estimate_evidence_ref TEXT,
    measured_evidence_ref TEXT,
    candidate_evaluation_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_name ON skill_roi_ledger (skill_name);
"""
def _evidence_refs(value: object, fallback: str) -> list[str]:
    """Extract only bounded refs from one explicit evidence payload."""
    refs: list[object] = []
    if isinstance(value, dict):
        for key in ("evidence_refs", "evidence", "refs"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                refs.extend(candidate)
            elif isinstance(candidate, str):
                refs.append(candidate)
    return _bounded_refs(refs, [fallback])


def _explicit_condition(
    binding: dict[str, Any], evaluation: dict[str, Any], code: str, skill_name: str
) -> tuple[bool, list[str], object | None]:
    """Read a condition only when persisted evidence names that condition."""
    values: list[tuple[str, object]] = []
    for label, source in (("binding", binding), ("evaluation", evaluation)):
        if not isinstance(source, dict):
            continue
        for container_name in (
            "condition_evidence",
            "issue_evidence",
            "classification",
            "gardener_evidence",
            "conditions",
        ):
            container = source.get(container_name)
            if isinstance(container, dict) and code in container:
                values.append((f"{label}:{container_name}:{code}", container[code]))
        direct = source.get(code)
        if direct is not None:
            values.append((f"{label}:{code}", direct))
        codes = source.get("condition_codes")
        if isinstance(codes, list) and code in codes:
            values.append((f"{label}:condition_codes:{code}", {"detected": True}))

    for fallback, value in values:
        detected = value is True
        if isinstance(value, dict):
            detected = any(
                value.get(key) is True
                for key in (
                    "detected",
                    "present",
                    "material",
                    "failed",
                    "false_positive",
                    "outside_scope",
                    "missed",
                    "divergent",
                )
            )
        elif isinstance(value, list):
            detected = bool(value)
        if detected:
            return True, _evidence_refs(value, f"skill:{skill_name}:{fallback}"), value
    return False, [], None


def _normalized_capability_hash(path: Path) -> str | None:
    """Hash body/capability content while ignoring lifecycle identity fields."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
        except ValueError:
            end = -1
        if end >= 0:
            lines = [
                line
                for line in lines[end + 1 :]
                if not re.match(r"^\s*(name|status|version)\s*:", line, re.I)
            ]
    normalized = "\n".join(" ".join(line.split()) for line in lines if line.strip()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def _capability_identity(
    path: Path, binding: dict[str, Any], evaluation: dict[str, Any]
) -> str | None:
    for source in (binding, evaluation):
        for key in ("normalized_capability_hash", "capability_hash", "content_identity"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value:
                return value
        evidence = source.get("capability_evidence") if isinstance(source, dict) else None
        if isinstance(evidence, dict):
            for key in ("normalized_hash", "capability_hash", "content_hash"):
                value = evidence.get(key)
                if isinstance(value, str) and value:
                    return value
    return _normalized_capability_hash(path)


def _replacement_evidence(
    binding: dict[str, Any], evaluation: dict[str, Any], skill_name: str
) -> tuple[dict[str, str] | None, list[str]]:
    for label, source in (("binding", binding), ("evaluation", evaluation)):
        if not isinstance(source, dict):
            continue
        for key in ("replacement_ref", "replacement", "superseded_by"):
            value = source.get(key)
            if not isinstance(value, dict):
                continue
            name = value.get("skill_name") or value.get("name") or value.get("id")
            version = value.get("version") or value.get("skill_version")
            capability = value.get("capability_hash") or value.get(
                "normalized_capability_hash"
            )
            cap_evidence = value.get("capability_evidence")
            if not isinstance(capability, str) and isinstance(cap_evidence, dict):
                for cap_key in ("normalized_hash", "capability_hash", "content_hash"):
                    candidate = cap_evidence.get(cap_key)
                    if isinstance(candidate, str) and candidate:
                        capability = candidate
                        break
            if (
                isinstance(name, str)
                and name
                and name != skill_name
                and isinstance(version, str)
                and version
                and isinstance(capability, str)
                and capability
            ):
                replacement = {
                    "skill_name": name[:_MAX_REFERENCE_LENGTH],
                    "skill_version": version[:_MAX_REFERENCE_LENGTH],
                    "capability_hash": capability[:_MAX_REFERENCE_LENGTH],
                }
                return replacement, _evidence_refs(
                    value, f"{label}:{key}:{name}:{version}"
                )
    return None, []


def _stale_evidence(
    item: dict[str, Any], binding: dict[str, Any], evaluation: dict[str, Any]
) -> list[str]:
    current_hash = item.get("content_hash")
    current_version = item.get("skill_version")
    refs: list[str] = []
    for label, source in (("binding", binding), ("evaluation", evaluation)):
        if not isinstance(source, dict):
            continue
        for key in (
            "candidate_content_sha256",
            "content_hash",
            "skill_content_hash",
            "artifact_sha256",
        ):
            value = source.get(key)
            if isinstance(value, str) and value and isinstance(current_hash, str) and value != current_hash:
                refs.append(f"{label}:{key}")
        for key in ("candidate_version", "skill_version", "artifact_version"):
            value = source.get(key)
            if isinstance(value, str) and value and isinstance(current_version, str) and value != current_version:
                refs.append(f"{label}:{key}")
        freshness = source.get("freshness")
        if isinstance(freshness, dict) and freshness.get("ok") is False:
            refs.extend(_evidence_refs(freshness, f"{label}:freshness"))
    return _bounded_refs(refs)


def _ledger_usage(home: Path, skill_name: str) -> tuple[bool, list[str]]:
    """Return measured usage evidence without creating or changing state."""
    dbfile = home / "state" / "skills" / "skill_roi.sqlite"
    if not dbfile.is_file():
        return False, []
    try:
        with sqlite3.connect(dbfile, timeout=1.0) as conn:
            rows = conn.execute(
                "SELECT id, measurement_state FROM skill_roi_ledger "
                "WHERE skill_name = ? ORDER BY id LIMIT 32",
                (skill_name,),
            ).fetchall()
    except sqlite3.Error:
        return False, []
    measured = [row for row in rows if row[1] == MeasurementState.MEASURED.value]
    return bool(measured), [f"ledger:{row[0]}" for row in measured]


def _telemetry_usage(home: Path) -> dict[str, list[str]]:
    """Collect bounded per-skill usage evidence in one telemetry pass."""
    usage: dict[str, list[str]] = {}
    for file_name, _, record in telemetry.iter_records(home):
        if not isinstance(record, dict):
            continue
        name = record.get("skill_name")
        if (
            isinstance(name, str)
            and record.get("kind") in {"skill_invocation", "skill_use", "skill_selected"}
        ):
            refs = usage.setdefault(name, [])
            if len(refs) < _MAX_EVIDENCE_REFS:
                refs.append(f"telemetry:{file_name}")
    return usage


def _usage_state(
    home: Path,
    skill_name: str,
    binding: dict[str, Any],
    evaluation: dict[str, Any],
    telemetry_usage: dict[str, list[str]],
) -> tuple[str, list[str]]:
    for label, source in (("binding", binding), ("evaluation", evaluation)):
        if not isinstance(source, dict):
            continue
        for key in ("usage", "usage_telemetry", "telemetry"):
            usage = source.get(key)
            if not isinstance(usage, dict):
                continue
            count = usage.get("invocations", usage.get("invocation_count", usage.get("uses")))
            measured = usage.get("measured") is True or isinstance(usage.get("window"), str)
            if isinstance(count, int) and count >= 0 and measured:
                refs = _evidence_refs(usage, f"{label}:{key}:{skill_name}")
                return ("zero" if count == 0 else "used"), refs
    used, refs = _ledger_usage(home, skill_name)
    if used:
        return "used", refs
    if skill_name in telemetry_usage:
        return "used", telemetry_usage[skill_name]
    return "unknown", [f"usage_unavailable:{skill_name}"]


def _ledger_measured_roi(
    home: Path, skill_name: str, content_hash: str
) -> tuple[int | None, list[str]]:
    dbfile = home / "state" / "skills" / "skill_roi.sqlite"
    if not dbfile.is_file():
        return None, []
    try:
        with sqlite3.connect(dbfile, timeout=1.0) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(tokens_saved), 0), "
                "COALESCE(SUM(tokens_invested), 0) "
                "FROM skill_roi_ledger WHERE skill_name = ? AND skill_version = ? "
                "AND measurement_state = ?",
                (skill_name, content_hash, MeasurementState.MEASURED.value),
            ).fetchone()
            refs = conn.execute(
                "SELECT id FROM skill_roi_ledger WHERE skill_name = ? "
                "AND skill_version = ? AND measurement_state = ? ORDER BY id LIMIT 32",
                (skill_name, content_hash, MeasurementState.MEASURED.value),
            ).fetchall()
    except sqlite3.Error:
        return None, []
    if not row or not row[0]:
        return None, []
    return int(row[1]) - int(row[2]), [f"ledger:{int(ref[0])}" for ref in refs]


def _measured_roi(
    home: Path, item: dict[str, Any]
) -> tuple[MeasurementState, int | None, list[str]]:
    name = str(item["skill_name"])
    version = str(item.get("content_hash") or item["skill_version"])
    measured, ref = _measured_from_counterfactual_result(home, name, version)
    if measured is not None:
        return MeasurementState.MEASURED, measured, _bounded_refs([ref] if ref else [])
    measured, ref, candidate_ref = _measured_from_evaluation(home, name, version)
    if measured is not None:
        return MeasurementState.MEASURED, measured, _bounded_refs(
            [ref, f"candidate:{candidate_ref}"] if ref else []
        )
    if isinstance(item.get("content_hash"), str):
        measured, refs = _ledger_measured_roi(home, name, item["content_hash"])
        if measured is not None:
            return MeasurementState.MEASURED, measured, refs
    return MeasurementState.UNAVAILABLE, None, []

def _issue_record(
    item: dict[str, Any],
    condition_code: str,
    evidence_refs: list[str],
    *,
    measurement_state: str = "unavailable",
    reason_codes: list[str] | None = None,
    replacement_ref: dict[str, str] | None = None,
    suffix: str = "",
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "issue_id": f"{item['skill_name']}:{condition_code}{suffix}",
        "issue_type": _ISSUE_TYPES[condition_code],
        "condition_code": condition_code,
        "skill_name": item["skill_name"],
        "skill_version": item["skill_version"],
        "lifecycle_state": item["lifecycle_state"],
        "reason_codes": reason_codes or [condition_code],
        "evidence_refs": _bounded_refs(evidence_refs),
        "measurement_state": measurement_state,
    }
    if replacement_ref is not None:
        issue["replacement_ref"] = replacement_ref
    return issue


def _classify_portfolio(
    home: Path,
    skills: list[dict[str, Any]],
    evidence: dict[str, tuple[dict[str, Any], dict[str, Any], Path]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    identities: dict[str, list[dict[str, Any]]] = {}
    telemetry_usage = _telemetry_usage(home)
    required_sections = {
        "Purpose",
        "Positive Triggers",
        "Negative Triggers",
        "Inputs",
        "Procedure",
        "Tools",
        "Safety",
        "Verification",
        "Output",
        "References",
    }
    for item in skills:
        name = str(item["skill_name"])
        binding, evaluation, path = evidence[name]
        audit_findings = [
            finding for finding in item.get("audit_findings", []) if isinstance(finding, str)
        ]
        audit_refs = [f"audit:{name}:{finding}" for finding in audit_findings]
        stale_refs = _stale_evidence(item, binding, evaluation)
        stale_refs.extend(
            ref
            for ref in audit_refs
            if re.search(r"frontmatter\s+status|freshness|stale", ref, re.I)
        )
        stale_refs = _bounded_refs(stale_refs)
        if stale_refs:
            issues.append(
                _issue_record(
                    item, "evidence_stale", stale_refs, reason_codes=["evidence_stale"]
                )
            )
        dead = item.get("content_hash") is None or any(
            re.search(
                r"missing\s+skill\.md|missing\s+promotion|cannot\s+execute|execution|"
                r"corrupt|missing\s+section|empty|placeholder|tbd|todo",
                finding,
                re.I,
            )
            or finding.strip() in required_sections
            for finding in audit_findings
        )
        if dead:
            refs = list(audit_refs)
            if item.get("content_hash") is None:
                refs.append(f"skill:{name}:SKILL.md")
            issues.append(_issue_record(item, "dead_skill", refs))

        usage_state, usage_refs = _usage_state(
            home, name, binding, evaluation, telemetry_usage
        )
        item["usage_state"] = usage_state
        item["usage_evidence_refs"] = _bounded_refs(usage_refs)
        if usage_state == "zero":
            issues.append(
                _issue_record(
                    item,
                    "measured_zero_use",
                    usage_refs,
                    measurement_state=MeasurementState.MEASURED.value,
                )
            )

        measurement_state, measured_roi, roi_refs = _measured_roi(home, item)
        if (
            measurement_state == MeasurementState.MEASURED
            and measured_roi is not None
            and measured_roi < 0
        ):
            issues.append(
                _issue_record(
                    item,
                    "measured_negative",
                    roi_refs or [f"roi:{name}"],
                    measurement_state=measurement_state.value,
                )
            )


        if not stale_refs:
            for code in (
                "dead_skill",
                "capability_overlap",
                "false_trigger",
                "scope_too_broad",
                "scope_too_narrow",
                "model_specific_quirk",
            ):
                detected, refs, value = _explicit_condition(
                    binding, evaluation, code, name
                )
                if not detected:
                    continue
                if code == "dead_skill" and item.get("content_hash") is None:
                    continue
                suffix = ""
                if code == "capability_overlap":
                    if not isinstance(value, dict):
                        continue
                    target_name = (
                        value.get("with")
                        or value.get("skill_name")
                        or value.get("skill_id")
                    )
                    if (
                        not isinstance(target_name, str)
                        or not target_name
                        or target_name == name
                        or value.get("material") is not True
                    ):
                        continue
                    suffix = f":{target_name[:_MAX_REFERENCE_LENGTH]}"
                issues.append(_issue_record(item, code, refs, suffix=suffix))

            replacement, replacement_refs = _replacement_evidence(
                binding, evaluation, name
            )
            if replacement is not None:
                target_name = replacement["skill_name"]
                target = next(
                    (candidate for candidate in skills if candidate["skill_name"] == target_name),
                    None,
                )
                target_evidence = evidence.get(target_name)
                target_identity = (
                    _capability_identity(
                        target_evidence[2], target_evidence[0], target_evidence[1]
                    )
                    if target_evidence is not None
                    else None
                )
                if (
                    target is not None
                    and target.get("content_hash") is not None
                    and target.get("lifecycle_state") in paths.SKILL_LEVEL_DIRS
                    and replacement.get("skill_version") == target.get("skill_version")
                    and replacement.get("capability_hash") == target_identity
                ):
                    issues.append(
                        _issue_record(
                            item,
                            "superseded",
                            replacement_refs,
                            replacement_ref=replacement,
                        )
                    )
        identity = _capability_identity(path, binding, evaluation)
        if identity:
            identities.setdefault(identity, []).append(item)

    for identity, members in identities.items():
        if len(members) < 2:
            continue
        refs = [f"capability:{identity[:_MAX_REFERENCE_LENGTH]}"]
        for item in members:
            issues.append(_issue_record(item, "exact_duplicate", refs))
    unique: dict[str, dict[str, Any]] = {}
    for issue in issues:
        unique.setdefault(issue["issue_id"], issue)
    return list(unique.values())

class SkillHealth(StrEnum):
    HEALTHY = "HEALTHY"  # ROI > 0, Success rate >= 80%
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Low usage or marginal ROI
    DEGRADED = "DEGRADED"  # Negative net tokens or Success rate < 70%
    DEPRECATED = "DEPRECATED"  # Flagged for archival


class MeasurementState(StrEnum):
    """§119/P3.14: a Skill ROI figure is either a real MEASURED outcome
    (P3.11 evaluation or P3.13 counterfactual_result, version-bound), an
    ESTIMATED_ONLY prediction with no current measurement yet (P3.10 Radar
    only), or UNAVAILABLE (neither exists, or all available evidence is
    stale for the skill's current content hash). Never conflated with a
    fabricated zero."""

    MEASURED = "measured"
    ESTIMATED_ONLY = "estimated_only"
    UNAVAILABLE = "unavailable"


# Comparison classifications (plan-neutral; frozen contract does not name a
# vocabulary, so this is the smallest reproducible one satisfying "estimate
# optimistic / accurate / pessimistic / measured negative / measured
# approximately zero / inconclusive").
_APPROXIMATELY_ZERO_TOKENS = 25
_ACCURATE_TOLERANCE_RATIO = 0.15
_ACCURATE_TOLERANCE_FLOOR = 50


def _classify_comparison(
    estimated_tokens_saved: int | None,
    measured_tokens_saved: int | None,
    measurement_state: MeasurementState,
) -> str:
    """Compare MEASURED against ESTIMATED honestly. Never forces a positive
    result; a real negative or near-zero measurement is reported as such
    regardless of what was estimated."""
    if measurement_state != MeasurementState.MEASURED or measured_tokens_saved is None:
        return "inconclusive"
    if measured_tokens_saved < 0:
        return "measured_negative"
    if abs(measured_tokens_saved) <= _APPROXIMATELY_ZERO_TOKENS:
        return "measured_approximately_zero"
    if estimated_tokens_saved is None:
        return "inconclusive"
    error = measured_tokens_saved - estimated_tokens_saved
    tolerance = max(
        abs(estimated_tokens_saved) * _ACCURATE_TOLERANCE_RATIO, _ACCURATE_TOLERANCE_FLOOR
    )
    if error > tolerance:
        return "estimate_pessimistic"  # reality exceeded the estimate
    if error < -tolerance:
        return "estimate_optimistic"  # estimate was too rosy
    return "estimate_accurate"


def _estimated_benefit(
    binding: dict | None, radar: ImprovementRadar
) -> tuple[int | None, str | None]:
    """P3.10 ESTIMATED benefit: state/radar/candidates.json
    expected_benefit_tokens for a Radar-backed candidate's source signal.
    Returns (None, None) honestly when no Radar lineage exists — never
    invented."""
    if not binding:
        return None, None
    radar_id = binding.get("source_radar_candidate_id")
    if not isinstance(radar_id, str) or not radar_id:
        if binding.get("source_type") == "radar" and isinstance(binding.get("source_ref"), str):
            radar_id = binding["source_ref"]
        else:
            return None, None
    try:
        candidate = radar.get_candidate(radar_id)
    except BrainError:
        return None, None
    value = candidate.get("expected_benefit_tokens")
    if not isinstance(value, int) or isinstance(value, bool):
        return None, None
    return value, f"radar:{radar_id}"


def _measured_from_counterfactual_result(
    home: Path, skill_name: str, skill_version: str
) -> tuple[int | None, str | None]:
    """P3.13 MEASURED benefit: the most recent counterfactual_result whose
    intervention is exactly this skill's current content hash (stale
    evidence for a different version is rejected, not reused).
    tokens_saved = without_arm - with_arm (savings FROM having the skill)."""
    directory = home / "outputs" / "audits" / "counterfactual" / "skill"
    if not directory.is_dir():
        return None, None
    matches: list[tuple[str, Path, dict]] = []
    for path in sorted(directory.glob(f"{skill_name}-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        intervention = data.get("intervention")
        if not isinstance(intervention, dict):
            continue
        if intervention.get("id") != skill_name or intervention.get("hash") != skill_version:
            continue  # different skill or a different (stale) version
        matches.append((str(data.get("created_at") or ""), path, data))
    if not matches:
        return None, None
    matches.sort(key=lambda item: item[0])
    _, path, data = matches[-1]
    with_total = data["with_arm"]["tokens"]["total"]
    without_total = data["without_arm"]["tokens"]["total"]
    return without_total - with_total, f"counterfactual:{path.name}"


def _measured_from_evaluation(
    home: Path, skill_name: str, skill_version: str
) -> tuple[int | None, str | None, str | None]:
    """P3.11 MEASURED benefit (fallback when no current P3.13 result
    exists): evaluation.json roi.net_tokens_saved, only when its bound
    candidate_content_sha256 matches the skill's current content hash.
    Also accepts a match against the pre-P3.12 raw (non-lifecycle-
    normalized) content hash: that scheme predates lifecycle_content_hash
    but represents the identical, unchanged file bytes — a real
    backward-compatibility case, not a fabricated pass."""
    path = skillforge.skill_path(home, skill_name)
    if path is None:
        return None, None, None
    evaluation_path = path.parent / "evaluation.json"
    if not evaluation_path.exists():
        return None, None, None
    try:
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None, None
    bound_hash = evaluation.get("candidate_content_sha256")
    if bound_hash != skill_version and bound_hash != hashlib.sha256(path.read_bytes()).hexdigest():
        return None, None, None  # stale: evaluation ran against a different version
    roi = evaluation.get("roi")
    if not isinstance(roi, dict) or not isinstance(roi.get("net_tokens_saved"), int):
        return None, None, None
    evaluation_id = evaluation.get("evaluation_id")
    ref = f"evaluation:{evaluation_id}" if evaluation_id else "evaluation:evaluation.json"
    candidate_id = evaluation.get("candidate_id")
    return roi["net_tokens_saved"], ref, candidate_id


@dataclass
class SkillROISummary:
    """ROI summary for a skill (measured evidence only)."""

    skill_name: str
    invocations: int
    total_tokens_invested: int
    total_tokens_saved: int
    net_tokens_saved: int
    roi_ratio: float
    success_rate: float
    health: SkillHealth
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "invocations": self.invocations,
            "total_tokens_invested": self.total_tokens_invested,
            "total_tokens_saved": self.total_tokens_saved,
            "net_tokens_saved": self.net_tokens_saved,
            "roi_ratio": round(self.roi_ratio, 2),
            "success_rate": round(self.success_rate, 2),
            "health": self.health.value,
            "recommendation": self.recommendation,
        }


class SkillROILedger:
    """Tracks token investments and savings per skill invocation (§3 P3.14).

    A derived evidence store, not an independent source of economic truth:
    record_from_evidence() is the primary writer and points every row back
    to the canonical P3.10/P3.11/P3.13 evidence it was composed from.
    record_usage() remains available as the low-level raw-value primitive
    for direct/already-known measured invocations (unchanged semantics).
    """

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self._db_dir = self.home / "state" / "skills"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._dbfile = self._db_dir / "skill_roi.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def record_usage(
        self,
        skill_name: str,
        session_id: str,
        tokens_invested: int,
        tokens_saved: int,
        success: bool = True,
        *,
        skill_version: str | None = None,
        measurement_state: MeasurementState = MeasurementState.MEASURED,
        estimated_tokens_saved: int | None = None,
        estimate_evidence_ref: str | None = None,
        measured_evidence_ref: str | None = None,
        candidate_evaluation_ref: str | None = None,
    ) -> None:
        """Record one MEASURED skill execution in the ROI ledger. A row is
        only ever inserted for measurement_state MEASURED (record_usage's
        historical contract); callers with only an estimate or nothing
        measured must not call this — use record_from_evidence(), which
        honestly returns without inserting a ledger row in that case."""
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            conn.execute(
                "INSERT INTO skill_roi_ledger "
                "(skill_name, session_id, skill_version, tokens_invested, tokens_saved, "
                "success, measurement_state, estimated_tokens_saved, estimate_evidence_ref, "
                "measured_evidence_ref, candidate_evaluation_ref, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    skill_name,
                    session_id,
                    skill_version,
                    tokens_invested,
                    tokens_saved,
                    1 if success else 0,
                    measurement_state.value,
                    estimated_tokens_saved,
                    estimate_evidence_ref,
                    measured_evidence_ref,
                    candidate_evaluation_ref,
                    now,
                ),
            )
            conn.commit()

    def record_from_evidence(
        self, home: Path | str, skill_name: str, *, session_id: str = ""
    ) -> dict[str, Any]:
        """Compose real, currently-bound P3.10/P3.11/P3.13 evidence into one
        version-bound Skill ROI record plus a first-class measured-vs-
        estimated comparison. Never fabricates: a missing measurement stays
        estimated_only/unavailable and is never inserted as a fake measured
        0, and stale (version-mismatched) evidence is rejected outright.
        Makes zero model/tool calls of its own — pure local composition of
        already-generated evidence."""
        started = time.perf_counter()
        home_path = Path(home)
        skill_path = skillforge.skill_path(home_path, skill_name)
        if skill_path is None:
            raise BrainError(f"No skill {skill_name!r} found under lifecycle directories")
        skill_version = skillforge.lifecycle_content_hash(skill_path)
        binding = skillforge.candidate_binding(home_path, skill_name)

        estimated_tokens_saved, estimate_evidence_ref = _estimated_benefit(
            binding, ImprovementRadar(home_path)
        )

        measured_tokens_saved, measured_evidence_ref = _measured_from_counterfactual_result(
            home_path, skill_name, skill_version
        )
        candidate_evaluation_ref: str | None = None
        if measured_tokens_saved is None:
            measured_tokens_saved, measured_evidence_ref, candidate_evaluation_ref = (
                _measured_from_evaluation(home_path, skill_name, skill_version)
            )

        if measured_tokens_saved is not None:
            measurement_state = MeasurementState.MEASURED
        elif estimated_tokens_saved is not None:
            measurement_state = MeasurementState.ESTIMATED_ONLY
        else:
            measurement_state = MeasurementState.UNAVAILABLE

        record_id: int | None = None
        if measurement_state == MeasurementState.MEASURED:
            with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
                existing = conn.execute(
                    "SELECT id FROM skill_roi_ledger WHERE skill_name = ? AND skill_version = ? "
                    "AND measured_evidence_ref = ? AND measurement_state = ?",
                    (skill_name, skill_version, measured_evidence_ref, measurement_state.value),
                ).fetchone()
                if existing is not None:
                    # Idempotent: the same immutable evidence file was already
                    # composed into this exact ledger row; re-reading it must
                    # not double-count the measurement.
                    record_id = int(existing[0])
                else:
                    now = datetime.now(UTC).isoformat()
                    cursor = conn.execute(
                        "INSERT INTO skill_roi_ledger "
                        "(skill_name, session_id, skill_version, tokens_invested, tokens_saved, "
                        "success, measurement_state, estimated_tokens_saved, "
                        "estimate_evidence_ref, "
                        "measured_evidence_ref, candidate_evaluation_ref, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            skill_name,
                            session_id,
                            skill_version,
                            0,
                            measured_tokens_saved,
                            1,
                            measurement_state.value,
                            estimated_tokens_saved,
                            estimate_evidence_ref,
                            measured_evidence_ref,
                            candidate_evaluation_ref,
                            now,
                        ),
                    )
                    conn.commit()
                    record_id = cursor.lastrowid

        comparison = _classify_comparison(
            estimated_tokens_saved, measured_tokens_saved, measurement_state
        )
        return {
            "skill_name": skill_name,
            "skill_version": skill_version,
            "record_id": record_id,
            "measurement_state": measurement_state.value,
            "estimated_tokens_saved": estimated_tokens_saved,
            "estimate_evidence_ref": estimate_evidence_ref,
            "measured_tokens_saved": measured_tokens_saved,
            "measured_evidence_ref": measured_evidence_ref,
            "candidate_evaluation_ref": candidate_evaluation_ref,
            "comparison": comparison,
            "estimation_error": (
                measured_tokens_saved - estimated_tokens_saved
                if measured_tokens_saved is not None and estimated_tokens_saved is not None
                else None
            ),
            "economics": {
                "model_calls": 0,
                "tool_calls": 0,
                "tokens": 0,
                "bookkeeping_wall_time_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        }

    def get_summary(self, skill_name: str) -> SkillROISummary:
        """Compute aggregate ROI and health for a skill from MEASURED rows
        only; estimated_only/unavailable evidence never enters this
        arithmetic."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(tokens_invested), SUM(tokens_saved), SUM(success) "
                "FROM skill_roi_ledger WHERE skill_name = ? AND measurement_state = ?",
                (skill_name, MeasurementState.MEASURED.value),
            ).fetchone()

            if not row or row[0] == 0:
                return SkillROISummary(
                    skill_name=skill_name,
                    invocations=0,
                    total_tokens_invested=0,
                    total_tokens_saved=0,
                    net_tokens_saved=0,
                    roi_ratio=0.0,
                    success_rate=0.0,
                    health=SkillHealth.NEEDS_REVIEW,
                    recommendation="No invocation data yet.",
                )

            invocations = int(row[0])
            invested = int(row[1] or 0)
            saved = int(row[2] or 0)
            success_count = int(row[3] or 0)
            net_saved = saved - invested
            roi_ratio = saved / max(invested, 1)
            success_rate = success_count / max(invocations, 1)

            # Health classification
            if net_saved < 0 or success_rate < 0.60:
                health = SkillHealth.DEGRADED
                recommendation = "Negative ROI or high failure rate: review or deprecate."
            elif roi_ratio >= 1.5 and success_rate >= 0.80:
                health = SkillHealth.HEALTHY
                recommendation = "High value skill: promote to core resident catalog."
            else:
                health = SkillHealth.NEEDS_REVIEW
                recommendation = "Acceptable performance: monitor ongoing ROI."

            return SkillROISummary(
                skill_name=skill_name,
                invocations=invocations,
                total_tokens_invested=invested,
                total_tokens_saved=saved,
                net_tokens_saved=net_saved,
                roi_ratio=roi_ratio,
                success_rate=success_rate,
                health=health,
                recommendation=recommendation,
            )

    def list_all(self) -> list[SkillROISummary]:
        """List summaries for all skills with at least one MEASURED row."""
        with sqlite3.connect(self._dbfile, timeout=5.0) as conn:
            rows = conn.execute(
                "SELECT DISTINCT skill_name FROM skill_roi_ledger WHERE measurement_state = ? "
                "ORDER BY skill_name",
                (MeasurementState.MEASURED.value,),
            ).fetchall()
            return [self.get_summary(r[0]) for r in rows]


class SkillGardener:
    """Autonomous skill maintenance and portfolio pruning (§3 P3.15)."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self.ledger = SkillROILedger(self.home)
    def observe_portfolio(self) -> dict[str, Any]:
        """Compose a bounded, read-only observation of lifecycle skills.

        This intentionally reads existing evidence instead of calling
        ``record_from_evidence``: observation must not create or update ROI
        """
        evidence_by_skill: dict[str, tuple[dict[str, Any], dict[str, Any], Path]] = {}
        started = time.perf_counter()
        lifecycle_audit = skillforge.audit_lifecycle(self.home)
        audit_entries = lifecycle_audit.get("skills", [])
        audit_by_identity: dict[tuple[str, str], list[str]] = {}
        if isinstance(audit_entries, list):
            for entry in audit_entries:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                level = entry.get("level")
                if not isinstance(name, str) or not isinstance(level, str):
                    continue
                findings = entry.get("issues", [])
                if isinstance(findings, list):
                    audit_by_identity[(name, level)] = [
                        str(item)[:_MAX_REFERENCE_LENGTH]
                        for item in findings[:_MAX_AUDIT_FINDINGS]
                    ]

        skills: list[dict[str, Any]] = []
        for level, relative in paths.SKILL_LEVEL_DIRS.items():
            directory = self.home / relative
            if not directory.is_dir():
                continue
            for skill_dir in sorted(path for path in directory.iterdir() if path.is_dir()):
                path = skill_dir / "SKILL.md"
                metadata: dict[str, str] = {}
                content_hash: str | None = None
                if path.is_file():
                    try:
                        metadata = skillforge.read_metadata(path)
                        content_hash = skillforge.lifecycle_content_hash(path)
                    except OSError:
                        # The audit still records an unreadable/missing artifact;
                        # observation keeps the identity and reports no hash.
                        metadata = {}

                binding_path = skill_dir / "candidate-binding.json"
                evaluation_path = skill_dir / "evaluation.json"
                binding = _read_json_object(binding_path)
                evaluation = _read_json_object(evaluation_path)
                evidence_refs = _bounded_refs(binding.get("evidence_refs"))
                evidence_by_skill[skill_dir.name] = (binding, evaluation, path)
                source_type = binding.get("source_type")
                source_ref = binding.get("source_ref")
                if isinstance(source_type, str) and isinstance(source_ref, str):
                    evidence_refs = _bounded_refs(
                        evidence_refs, [f"{source_type}:{source_ref}"]
                    )
                evaluation_id = evaluation.get("evaluation_id")
                if isinstance(evaluation_id, str) and evaluation_id:
                    evidence_refs = _bounded_refs(
                        evidence_refs, [f"evaluation:{evaluation_id}"]
                    )
                audit_findings = audit_by_identity.get((skill_dir.name, level), [])
                roi_summary = self.ledger.get_summary(skill_dir.name).to_dict()
                lifecycle_state = metadata.get("status") or level
                skill_version = metadata.get("version", "unversioned")
                skills.append(
                    {
                        "skill_name": skill_dir.name,
                        "skill_version": skill_version,
                        "content_hash": content_hash,
                        "lifecycle_state": lifecycle_state,
                        "binding_present": binding_path.is_file(),
                        "evaluation_present": evaluation_path.is_file(),
                        "binding_state": {
                            key: binding[key][:_MAX_REFERENCE_LENGTH]
                            for key in (
                                "lifecycle_state",
                                "evaluation_state",
                                "promotion_state",
                                "install_state",
                            )
                            if isinstance(binding.get(key), str)
                        },
                        "roi_summary": roi_summary,
                        "audit_findings": audit_findings,
                        "evidence_refs": evidence_refs,
                    }
                )

        issues = _classify_portfolio(self.home, skills, evidence_by_skill)
        issue_ids_by_skill: dict[str, list[str]] = {}
        issue_refs_by_skill: dict[str, list[str]] = {}
        for issue in issues:
            name = issue["skill_name"]
            issue_ids_by_skill.setdefault(name, []).append(issue["issue_id"])
            issue_refs_by_skill.setdefault(name, []).extend(issue["evidence_refs"])
        recommendations = [
            {
                "skill_name": item["skill_name"],
                "skill_version": item["skill_version"],
                "lifecycle_state": item["lifecycle_state"],
                "recommendation": "keep",
                "issue_ids": issue_ids_by_skill.get(item["skill_name"], []),
                "evidence_refs": _bounded_refs(
                    item["evidence_refs"],
                    issue_refs_by_skill.get(item["skill_name"], []),
                ),
            }
            for item in skills
        ]
        return {
            "skills": skills,
            "issues": issues,
            "recommendations": recommendations,
            "economics": {
                "model_calls": 0,
                "tool_calls": 0,
                "tokens": 0,
                "records_inspected": len(skills) + len(audit_entries)
                if isinstance(audit_entries, list)
                else len(skills),
                "local_processing_time_ms": round(
                    (time.perf_counter() - started) * 1000, 3
                ),
                "maintenance_work_performed": 0,
            },
        }


    def audit_portfolio(self) -> dict[str, Any]:
        """
        Scan all skills and produce maintenance recommendations.
        """
        summaries = self.ledger.list_all()
        healthy = [s for s in summaries if s.health == SkillHealth.HEALTHY]
        degraded = [s for s in summaries if s.health == SkillHealth.DEGRADED]
        review = [s for s in summaries if s.health == SkillHealth.NEEDS_REVIEW]

        return {
            "total_skills_tracked": len(summaries),
            "healthy_count": len(healthy),
            "degraded_count": len(degraded),
            "review_count": len(review),
            "degraded_skills": [d.to_dict() for d in degraded],
            "healthy_skills": [h.to_dict() for h in healthy],
        }
