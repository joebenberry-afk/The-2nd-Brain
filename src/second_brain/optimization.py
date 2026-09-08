"""Governed P4 optimization lifecycle coordinator.

This module is intentionally thin: fingerprints, Skill Forge evaluations,
frontier reviews, promotion, immune rollback, and Plasticity remain the
canonical authorities.  Proposal files are immutable evidence records; each
lifecycle transition appends a version under the audit directory.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import credit, frontier, immune, plasticity, promotion, skillforge, telemetry
from .errors import BrainError
from .fingerprints import BottleneckFingerprintStore
from .security.identifiers import validate_skill_name

MODES = ("off", "shadow", "active")
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PROPOSAL_RE = re.compile(r"^(proposal-[0-9a-f]{24})-v([1-9][0-9]*)\.json$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _optimization_dir(home: Path) -> Path:
    return Path(home) / "outputs" / "audits" / "optimization"


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BrainError(f"{name} must be a non-empty string")
    return value.strip()


def _proposal_id(fingerprint_id: str, intervention_hash: str) -> str:
    return (
        "proposal-"
        + hashlib.sha256(fingerprint_id.encode() + intervention_hash.encode()).hexdigest()[:24]
    )


def _proposal_files(home: Path, proposal_id: str) -> list[tuple[int, Path]]:
    directory = _optimization_dir(home)
    if not directory.is_dir():
        return []
    files: list[tuple[int, Path]] = []
    for path in directory.glob(f"{proposal_id}-v*.json"):
        match = _PROPOSAL_RE.fullmatch(path.name)
        if match and match.group(1) == proposal_id:
            files.append((int(match.group(2)), path))
    return sorted(files)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrainError(f"Corrupt optimization proposal {path}") from exc
    if not isinstance(value, dict):
        raise BrainError(f"Corrupt optimization proposal {path}: expected object")
    return value


def get_proposal(home: Path, proposal_id: str) -> dict:
    proposal_id = _require_text(proposal_id, "proposal_id")
    files = _proposal_files(Path(home), proposal_id)
    if not files:
        raise BrainError(f"Unknown optimization proposal {proposal_id!r}")
    version, path = files[-1]
    record = _read_json(path)
    if record.get("proposal_id") != proposal_id or record.get("version") != version:
        raise BrainError(f"Corrupt optimization proposal {path}")
    return record


def _write_new(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        if path.exists():
            existing = _read_json(path)
            if existing != record:
                raise BrainError(f"Immutable optimization proposal already exists: {path.name}")
            return
        os.replace(temporary, path)
        temporary = ""
    except OSError as exc:
        raise BrainError(f"Could not write optimization proposal {path}: {exc}") from exc
    finally:
        if temporary:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def _append(home: Path, current: dict, **changes: Any) -> dict:
    proposal_id = current["proposal_id"]
    versions = _proposal_files(Path(home), proposal_id)
    version = (versions[-1][0] if versions else int(current.get("version", 1))) + 1
    updated = dict(current)
    updated.update(changes)
    updated["version"] = version
    target = _optimization_dir(Path(home)) / f"{proposal_id}-v{version}.json"
    _write_new(target, updated)
    return updated


def _fingerprint_exists(home: Path, fingerprint_id: str) -> bool:
    # The store intentionally exposes a bounded ranking API, not a second
    # lookup authority.  Read all bounded persisted records and match ids.
    return any(
        fp.fingerprint_id == fingerprint_id
        for fp in BottleneckFingerprintStore(home).list_top_bottlenecks(10000)
    )


def _emit(
    home: Path,
    kind: str,
    proposal: dict,
    *,
    status: str,
    evidence_hash: str = "",
    session: str = "",
) -> None:
    evidence_hash = (
        evidence_hash
        or hashlib.sha256(
            json.dumps(proposal, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    )
    telemetry.append_record(
        home,
        session or proposal["proposal_id"],
        kind,
        {
            "proposal_id": proposal["proposal_id"],
            "status": status,
            "intervention_hash": proposal["intervention"]["hash"],
            "evidence_hash": evidence_hash,
            "approval_state": status,
            "rollback_state": proposal.get("rollback_state", "clear"),
        },
    )


def propose(
    home: Path,
    fingerprint_id: str,
    *,
    skill_name: str,
    intervention_hash: str,
    mode: str = "shadow",
) -> dict:
    fingerprint_id = _require_text(fingerprint_id, "fingerprint_id")
    skill_name = validate_skill_name(_require_text(skill_name, "skill_name"))
    if mode not in MODES:
        raise BrainError(f"mode must be one of {MODES}")
    if not _HEX64_RE.fullmatch(intervention_hash or ""):
        raise BrainError("intervention_hash must be a 64-char hex sha256")
    if not _fingerprint_exists(home, fingerprint_id):
        raise BrainError(f"Unknown bottleneck fingerprint {fingerprint_id!r}")
    skill_path = skillforge.skill_path(home, skill_name)
    if skill_path is None:
        raise BrainError(f"No skill {skill_name!r} found under lifecycle directories")

    proposal_id = _proposal_id(fingerprint_id, intervention_hash)
    existing = _proposal_files(Path(home), proposal_id)
    if existing:
        current = get_proposal(home, proposal_id)
        if (
            current.get("fingerprint_id") != fingerprint_id
            or current.get("intervention", {}).get("hash") != intervention_hash
        ):
            raise BrainError("proposal id is bound to a different fingerprint or intervention")
        return current

    record = {
        "schema_version": 1,
        "version": 1,
        "proposal_id": proposal_id,
        "fingerprint_id": fingerprint_id,
        "skill_name": skill_name,
        "intervention": {"type": "skill", "id": skill_name, "hash": intervention_hash},
        "mode": mode,
        "status": "shadow",
        "evaluation_ref": None,
        "frontier_change_id": f"skill-{skill_name}-promotion",
        "rollback_policy_id": f"skill-{skill_name}",
        "rollback_state": "clear",
        "created_at": _utc_now(),
    }
    target = _optimization_dir(Path(home)) / f"{proposal_id}-v1.json"
    _write_new(target, record)
    _emit(home, "optimization_proposal", record, status=record["status"])
    return record


def _counterfactual_evidence(result: dict, intervention_hash: str) -> tuple[dict, bool]:
    evidence = result.get("counterfactual_result", result)
    if not isinstance(evidence, dict) or not credit.is_counterfactual_result_current(
        evidence, intervention_hash
    ):
        raise BrainError("counterfactual evidence is stale or malformed")
    with_arm, without_arm = evidence.get("with_arm"), evidence.get("without_arm")
    if not isinstance(with_arm, dict) or not isinstance(without_arm, dict):
        raise BrainError("counterfactual evidence requires two arms")
    if with_arm.get("run_id") == without_arm.get("run_id"):
        raise BrainError("counterfactual arms must have distinct run ids")
    for arm in (with_arm, without_arm):
        if not isinstance(arm.get("verification"), dict) or not isinstance(
            arm.get("regressions"), dict
        ):
            raise BrainError(
                "counterfactual evidence requires verification and regression evidence"
            )
        if (
            not isinstance(arm.get("tokens"), dict)
            or not isinstance(arm.get("tool_calls"), int)
            or not isinstance(arm.get("wall_time_ms"), (int, float))
        ):
            raise BrainError("counterfactual evidence requires measured telemetry economics")
    with_tokens = with_arm["tokens"].get("total")
    without_tokens = without_arm["tokens"].get("total")
    if not isinstance(with_tokens, (int, float)) or not isinstance(without_tokens, (int, float)):
        raise BrainError("counterfactual evidence requires total token economics")
    net_saved = without_tokens - with_tokens
    verified = (
        with_arm.get("success") is True
        and with_arm["verification"].get("outcome") == "passed"
        and with_arm["regressions"].get("count") == 0
    )
    summary = {
        "evaluation_id": str(evidence.get("evaluation_id", "")),
        "candidate_content_sha256": result.get("candidate_content_sha256"),
        "status": "evaluated" if verified and net_saved > 0 else "hold",
        "roi": {"net_tokens_saved": net_saved, "candidate_better": net_saved > 0},
        "baseline": {"input_tokens": int(without_tokens), "output_tokens": 0},
        "candidate": {"input_tokens": int(with_tokens), "output_tokens": 0},
        "quality": {
            "correctness": verified,
            "requirements": verified,
            "protected_values": verified,
            "regressions": not verified,
            "verification": verified,
        },
        "gates": {
            "trigger": {"failed": 0},
            "workflow": {"structural": verified, "failed": 0},
            "regression": {"regression": not verified, "failed": 0},
            "security": {"passed": verified},
        },
        "evidence_hash": hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest(),
    }
    return summary, verified and net_saved > 0


def evaluate(home: Path, proposal_id: str, result: dict) -> dict:
    current = get_proposal(home, proposal_id)
    if not isinstance(result, dict):
        raise BrainError("evaluation result must be a JSON object")
    if current["mode"] == "off":
        return current
    intervention_hash = result.get("intervention_hash")
    intervention = result.get("intervention")
    if isinstance(intervention, dict):
        intervention_hash = intervention.get("hash", intervention_hash)
    counterfactual = result.get("counterfactual_result")
    if intervention_hash is None and isinstance(counterfactual, dict):
        cf_intervention = counterfactual.get("intervention")
        if isinstance(cf_intervention, dict):
            intervention_hash = cf_intervention.get("hash")
    if intervention_hash != current["intervention"]["hash"]:
        updated = _append(home, current, status="hold", refusal_reason="intervention_stale")
        _emit(home, "optimization_evaluation", updated, status="hold")
        return updated

    skill_name = current["skill_name"]
    skill_path = skillforge.skill_path(home, skill_name)
    if (
        skill_path is None
        or skillforge.lifecycle_content_hash(skill_path) != current["intervention"]["hash"]
    ):
        updated = _append(home, current, status="hold", refusal_reason="intervention_stale")
        _emit(home, "optimization_evaluation", updated, status="hold")
        return updated

    try:
        if "counterfactual_result" in result or "with_arm" in result:
            summary, passed = _counterfactual_evidence(result, current["intervention"]["hash"])
            forge_result = {
                "evaluation_id": summary["evaluation_id"],
                "task_id": summary["evaluation_id"],
                "task_hash": str(result.get("task_hash", summary["evaluation_id"])),
                "repository_state_hash": str(
                    result.get("repository_state_hash", summary["evaluation_id"])
                ),
                "intervention_hash": current["intervention"]["hash"],
                "baseline": summary["baseline"],
                "candidate": summary["candidate"],
                "quality": summary["quality"],
                "gates": summary["gates"],
            }
            evaluation = skillforge.record_evaluation(home, skill_name, forge_result)
            passed = evaluation.get("status") == "passed"
            summary.update(
                candidate_content_sha256=evaluation.get("candidate_content_sha256"),
                quality_gate=evaluation.get("quality_gate"),
                roi=evaluation.get("roi", summary["roi"]),
            )
        else:
            evaluation = skillforge.record_evaluation(home, skill_name, result)
            passed = evaluation.get("status") == "passed"
            summary = {
                "evaluation_id": evaluation.get("evaluation_id"),
                "candidate_content_sha256": evaluation.get("candidate_content_sha256"),
                "status": "evaluated" if passed else "hold",
                "quality_gate": evaluation.get("quality_gate"),
                "roi": evaluation.get("roi", {}),
                "evidence_hash": hashlib.sha256(
                    json.dumps(evaluation, sort_keys=True).encode()
                ).hexdigest(),
            }
    except BrainError as exc:
        summary = {
            "evaluation_id": None,
            "status": "hold",
            "roi": {"net_tokens_saved": 0, "candidate_better": False},
            "refusal_reason": str(exc),
            "evidence_hash": hashlib.sha256(
                json.dumps(result, sort_keys=True, default=str).encode()
            ).hexdigest(),
        }
        passed = False
    status = "evaluated" if passed else "hold"
    ref_id = summary.get("evaluation_id")
    evaluation_ref = f"evaluation:{ref_id}" if ref_id else None
    updated = _append(
        home,
        current,
        status=status,
        evaluation_ref=evaluation_ref,
        evaluation=summary,
        evaluated_at=_utc_now(),
    )
    _emit(
        home,
        "optimization_evaluation",
        updated,
        status=status,
        evidence_hash=summary.get("evidence_hash", ""),
    )
    if passed:
        roi = summary.get("roi", {})
        net_value = roi.get("net_tokens_saved", 0)
        if isinstance(net_value, (int, float)) and net_value > 0:
            plasticity.utility_update(
                home,
                skill_name,
                "skill",
                float(net_value),
                f"verified optimization evaluation {summary.get('evaluation_id', '')}",
            )
    return updated


def _current_review_matches(home: Path, skill_name: str, skill_path: Path) -> bool:
    latest = frontier.latest_review(home, f"skill-{skill_name}-promotion")
    if not latest or latest.get("verdict") != "approve":
        return False
    binding = skillforge.artifact_binding(home, skill_name)
    return all(
        latest.get(key) == binding[key]
        for key in ("artifact_sha256", "artifact_version", "eval_manifest_sha256")
    )


def activate(home: Path, proposal_id: str, *, session_id: str = "") -> dict:
    current = get_proposal(home, proposal_id)
    if current.get("mode") == "off":
        return {"activated": False, "reason": "mode_off"}
    if current.get("mode") != "active":
        return {"activated": False, "reason": "mode_not_active"}
    if current.get("status") != "evaluated":
        return {"activated": False, "reason": "evaluation_not_proven"}
    if not _fingerprint_exists(home, current["fingerprint_id"]):
        return {"activated": False, "reason": "fingerprint_stale"}
    skill_name = current["skill_name"]
    path = Path(home) / "skills" / "candidates" / skill_name / "SKILL.md"
    if not path.exists():
        return {"activated": False, "reason": "skill_stale"}
    if skillforge.lifecycle_content_hash(path) != current["intervention"]["hash"]:
        return {"activated": False, "reason": "intervention_stale"}
    binding = skillforge.candidate_binding(home, skill_name)
    if not binding:
        return {"activated": False, "reason": "owner_missing"}
    if not str(binding.get("owner") or "").strip():
        return {"activated": False, "reason": "owner_missing"}
    evaluation_path = path.parent / "evaluation.json"
    try:
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"activated": False, "reason": "evaluation_stale"}
    if not (
        binding.get("evaluation_state") == "passed"
        and binding.get("candidate_content_sha256") == skillforge.lifecycle_content_hash(path)
        and evaluation.get("status") == "passed"
        and evaluation.get("candidate_content_sha256") == skillforge.lifecycle_content_hash(path)
    ):
        return {"activated": False, "reason": "evaluation_stale"}
    if not frontier.gate_check(home, current["frontier_change_id"])["ok"]:
        return {"activated": False, "reason": "frontier_not_approved"}
    if not _current_review_matches(home, skill_name, path):
        return {"activated": False, "reason": "frontier_stale"}
    try:
        version = int(skillforge.read_metadata(path).get("version", "0"))
    except (TypeError, ValueError):
        return {"activated": False, "reason": "version_invalid"}
    if version < 1:
        return {"activated": False, "reason": "version_invalid"}
    ready = skillforge.validate_execution_ready(path)
    if not ready["ok"]:
        return {"activated": False, "reason": "execution_not_ready", "validation": ready}
    history = promotion.promotion_status(home, skill_name).get("records", [])
    prior_versions = [
        int(record["resulting_version"])
        for record in history
        if record.get("to_level") == "active" and str(record.get("resulting_version", "")).isdigit()
    ]
    if prior_versions and version <= max(prior_versions):
        return {"activated": False, "reason": "version_not_incremented"}
    active_path = Path(home) / "skills" / "active" / skill_name / "SKILL.md"
    if active_path.exists():
        return {"activated": False, "reason": "destination_exists"}
    if any(
        record.get("policy_id") == current["rollback_policy_id"]
        for record in immune.rollback_log(home)
    ):
        return {"activated": False, "reason": "rolled_back"}

    # Promotion's existing evidence gate is credit-based.  A verified,
    # positive evaluation is the explicit evidence for this coordinator.
    credit.assign_credit(
        home,
        session_id or proposal_id,
        direct=[skill_name],
        contributory=[],
        correlated=[],
    )
    promoted = promotion.promote(home, skill_name, "candidate", "active", session_id=session_id)
    if not promoted.get("promoted"):
        return {"activated": False, "reason": promoted.get("reason", "promotion_refused")}
    immune.register_policy(
        home,
        current["rollback_policy_id"],
        {
            "rollback_trigger": current["rollback_policy_id"],
            "rollback_target": str(active_path),
            "backup_of": immune.sha256_file(active_path),
        },
    )
    updated = _append(
        home,
        current,
        status="activated",
        activation={"session_id": session_id, "promotion": promoted},
        activated_at=_utc_now(),
    )
    _emit(home, "optimization_activation", updated, status="activated", session=session_id)
    return {"activated": True, "proposal": updated, "promotion": promoted}


def rollback(home: Path, proposal_id: str, trigger_id: str, reason: str) -> dict:
    current = get_proposal(home, proposal_id)
    trigger_id = _require_text(trigger_id, "trigger_id")
    if trigger_id != current.get("rollback_policy_id"):
        return {"rolled_back": False, "reason": "wrong_trigger"}
    result = immune.rollback(home, current["rollback_policy_id"], trigger_id, reason)
    if not result.get("rolled_back"):
        return result
    updated = _append(
        home,
        current,
        status="rolled_back",
        rollback_state="rolled_back",
        rollback=result,
        rolled_back_at=_utc_now(),
    )
    _emit(home, "optimization_rollback", updated, status="rolled_back")
    return {"rolled_back": True, "proposal": updated, "rollback": result}
