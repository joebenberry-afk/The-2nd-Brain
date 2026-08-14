"""Immune system — rollback trigger detectors with GUARDED auto-rollback
(plan §118, Phase 22).

Policies register a guard: a rollback trigger, the target file to move aside,
and the sha256 of the recorded (good) state. Metric samples are ingested into
``immune/metrics.jsonl`` (last 1000 lines kept). A trigger matches when the
latest sample of its metric within the configured window satisfies the
operator. Rollback is only allowed when the trigger currently matches AND the
policy was never frontier-approved AND the target actually differs from the
recorded backup — and only once per policy registration (double rollback is
refused until re-registration).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from . import frontier
from .errors import BrainError

DETECTORS: tuple[str, ...] = (
    "tests_failed",
    "f1_delta",
    "noise_delta",
    "compile_error_count",
    "success_rate_delta",
)
OPERATORS: tuple[str, ...] = ("<", "<=", ">", ">=", "==", "!=")
MAX_METRICS_LINES = 1000

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

_OPERATOR_FN = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _immune_dir(home: Path) -> Path:
    return Path(home) / "immune"


def _policies_dir(home: Path) -> Path:
    return _immune_dir(home) / "policies"


def _triggers_dir(home: Path) -> Path:
    return _immune_dir(home) / "triggers"


def _rollbacks_dir(home: Path) -> Path:
    return _immune_dir(home) / "rollbacks"


def _metrics_path(home: Path) -> Path:
    return _immune_dir(home) / "metrics.jsonl"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrainError(f"Corrupt immune file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BrainError(f"Corrupt immune file {path}: not a JSON object")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{_utcnow().replace(':', '-')}")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise BrainError(f"Could not write {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_policy(home: Path, policy_id: str, guard: dict) -> dict:
    """Record a policy change with its rollback guard. ``created_at`` is added
    automatically; the caller supplies the trigger id, target file, and the
    sha256 of the recorded (good) state."""
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise BrainError("policy_id must be a non-empty string")
    if not isinstance(guard, dict):
        raise BrainError("guard must be a dict")
    for key in ("rollback_trigger", "rollback_target", "backup_of"):
        if not isinstance(guard.get(key), str) or not guard[key].strip():
            raise BrainError(f"guard.{key} must be a non-empty string")
    if not _HEX64_RE.fullmatch(guard["backup_of"]):
        raise BrainError("guard.backup_of must be a 64-char hex sha256")
    record = {
        "policy_id": policy_id,
        "guard": {
            "rollback_trigger": guard["rollback_trigger"],
            "rollback_target": guard["rollback_target"],
            "backup_of": guard["backup_of"],
            "created_at": _utcnow(),
        },
    }
    _write_json(_policies_dir(home) / f"{policy_id}.json", record)
    # Re-registration re-arms the guard by refreshing created_at: older rollback
    # records no longer block a fresh rollback, and they stay in the log as
    # history.
    return record


def register_trigger(home: Path, trigger_id: str, matcher: dict) -> dict:
    """Record a trigger: metric (from DETECTORS), comparison operator, numeric
    value, and a positive sample window."""
    if not isinstance(trigger_id, str) or not trigger_id.strip():
        raise BrainError("trigger_id must be a non-empty string")
    if not isinstance(matcher, dict):
        raise BrainError("matcher must be a dict")
    metric = matcher.get("metric")
    if metric not in DETECTORS:
        raise BrainError(f"matcher.metric must be one of {', '.join(DETECTORS)}")
    operator = matcher.get("operator")
    if operator not in OPERATORS:
        raise BrainError(f"matcher.operator must be one of {', '.join(OPERATORS)}")
    value = matcher.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrainError("matcher.value must be a real number")
    window = matcher.get("window")
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        raise BrainError("matcher.window must be a positive integer")
    record = {
        "trigger_id": trigger_id,
        "matcher": {
            "metric": metric,
            "operator": operator,
            "value": float(value),
            "window": window,
        },
    }
    _write_json(_triggers_dir(home) / f"{trigger_id}.json", record)
    return record


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def read_metrics(home: Path) -> list[dict]:
    path = _metrics_path(home)
    if not path.exists():
        return []
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BrainError(f"Corrupt metrics file {path}:{lineno}: {exc}") from exc
        records.append(record)
    return records


def ingest_metric(home: Path, metric: str, value: float, run_id: str) -> None:
    """Append one sample; keep the last MAX_METRICS_LINES lines (deterministic
    truncate-rewrite)."""
    if metric not in DETECTORS:
        raise BrainError(f"metric must be one of {', '.join(DETECTORS)}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrainError("value must be a real number")
    if not isinstance(run_id, str) or not run_id.strip():
        raise BrainError("run_id must be a non-empty string")
    path = _metrics_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines.append(
        json.dumps(
            {
                "metric": metric,
                "value": float(value),
                "run_id": run_id,
                "ts": _utcnow(),
            },
            sort_keys=True,
        )
    )
    kept = lines[-MAX_METRICS_LINES:]
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(kept) + "\n")


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------


def _samples_for(records: list[dict], metric: str, window: int) -> list[dict]:
    return [r for r in records if r.get("metric") == metric][-window:]


def check_triggers(home: Path, policy_id: str | None = None) -> list[dict]:
    """Evaluate every registered trigger against the last ``window`` samples of
    its metric. Returns [{trigger_id, policy_ids, samples, computed, matched}]
    in deterministic trigger order."""
    triggers_dir = _triggers_dir(home)
    trigger_files = sorted(p for p in triggers_dir.glob("*.json")) if triggers_dir.is_dir() else []
    if policy_id is not None:
        policies_dir = _policies_dir(home)
        policy = _read_json(policies_dir / f"{policy_id}.json")
        wanted = policy["guard"]["rollback_trigger"]
        trigger_files = [p for p in trigger_files if p.stem == wanted]
    records = read_metrics(home)
    results = []
    for path in trigger_files:
        trigger = _read_json(path)
        matcher = trigger["matcher"]
        metric = matcher["metric"]
        samples = [
            {"value": float(s["value"]), "run_id": s.get("run_id")}
            for s in _samples_for(records, metric, matcher["window"])
        ]
        computed = samples[-1]["value"] if samples else None
        matched = computed is not None and _OPERATOR_FN[matcher["operator"]](
            computed, matcher["value"]
        )
        policy_ids = []
        policies_dir = _policies_dir(home)
        if policies_dir.is_dir():
            for policy_path in sorted(policies_dir.glob("*.json")):
                policy = _read_json(policy_path)
                if policy["guard"]["rollback_trigger"] == trigger["trigger_id"]:
                    policy_ids.append(policy["policy_id"])
        results.append(
            {
                "trigger_id": trigger["trigger_id"],
                "policy_ids": policy_ids,
                "samples": samples,
                "computed": computed,
                "matched": matched,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Guarded rollback
# ---------------------------------------------------------------------------


def rollback(home: Path, policy_id: str, trigger_id: str, reason: str) -> dict:
    """GUARDED auto-rollback: moves the policy's target file aside only when
    (a) its rollback trigger currently matches in the metrics window, (b) the
    policy was never frontier-approved, (c) the target differs from the
    recorded backup, and (d) no rollback happened yet for this registration.
    Refusals are explicit dicts with a reason; nothing is mutated on refusal.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise BrainError("reason must be a non-empty string")
    policies_dir = _policies_dir(home)
    policy_path = policies_dir / f"{policy_id}.json"
    if not policy_path.exists():
        raise BrainError(f"Unknown policy {policy_id!r}")
    policy = _read_json(policy_path)
    guard = policy["guard"]
    if guard["rollback_trigger"] != trigger_id:
        return {"rolled_back": False, "reason": "wrong_trigger"}

    matched = [
        r
        for r in check_triggers(home, policy_id=policy_id)
        if r["trigger_id"] == trigger_id and r["matched"]
    ]
    if not matched:
        return {"rolled_back": False, "reason": "trigger_not_matched"}

    if frontier.gate_check(home, policy_id)["ok"]:
        return {"rolled_back": False, "reason": "frontier_approved"}

    rollbacks_dir = _rollbacks_dir(home)
    registered_at = guard["created_at"]
    if rollbacks_dir.is_dir():
        for old_record in rollbacks_dir.glob(f"{policy_id}-*.json"):
            if _read_json(old_record).get("ts", "") >= registered_at:
                return {"rolled_back": False, "reason": "already_rolled_back"}

    target = Path(guard["rollback_target"])
    if not target.is_file():
        return {"rolled_back": False, "reason": "target_missing"}
    current_sha = sha256_file(target)
    if current_sha == guard["backup_of"]:
        return {"rolled_back": False, "reason": "no_change"}

    stamp = _utcnow().replace(":", "-")
    backup = rollbacks_dir / f"{policy_id}-{stamp}.bak"
    rollbacks_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(backup))
    record = {
        "policy_id": policy_id,
        "trigger": trigger_id,
        "reason": reason,
        "ts": _utcnow(),
        "restored_from_sha": current_sha,
    }
    _write_json(rollbacks_dir / f"{policy_id}-{stamp}.json", record)
    return {"rolled_back": True, "backup": str(backup), "record": record}


def rollback_log(home: Path) -> list[dict]:
    """All rollback records, sorted by timestamp then policy_id."""
    rollbacks_dir = _rollbacks_dir(home)
    if not rollbacks_dir.is_dir():
        return []
    records = [_read_json(p) for p in sorted(rollbacks_dir.glob("*.json"))]
    records.sort(key=lambda r: (r.get("ts", ""), r.get("policy_id", "")))
    return records
