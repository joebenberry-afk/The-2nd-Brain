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
import stat
from datetime import UTC, datetime
from pathlib import Path

from . import frontier
from .errors import BrainError
from .security.identifiers import validate_policy_id, validate_trigger_id
from .security.paths import resolve_under
from .skillforge import (
    _DANGEROUS_TOKENS,
    _DISK_FORMAT_RE,
    _EXFIL_URL_RE,
    _INJECTION_PHRASES,
    _SECRET_RE,
)

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


def _normalize_policy_target(home: Path, raw: str) -> str:
    """Turn a rollback target into a home-relative path proven contained.

    SEC-05: the guard must name a Brain-managed file under the Brain home,
    never an arbitrary filesystem target. Absolute paths are accepted only
    when they resolve inside the home; everything else is treated as
    home-relative. The stored form is a posix relative path; rollback
    re-derives it through the containment boundary.
    """
    home_resolved = Path(home).resolve(strict=False)
    raw_path = Path(raw)
    if raw_path.is_absolute():
        try:
            rel = raw_path.resolve(strict=False).relative_to(home_resolved)
        except ValueError as exc:
            raise BrainError(
                "guard.rollback_target must be inside the Brain home (absolute "
                f"target {raw!r} is outside)"
            ) from exc
    else:
        rel = raw_path
    rel_posix = rel.as_posix()
    try:
        resolve_under(home, rel_posix, allow_missing=True)
    except ValueError as exc:
        raise BrainError(
            f"guard.rollback_target {raw!r} is not a safe Brain-managed path: {exc}"
        ) from exc
    return rel_posix


def register_policy(home: Path, policy_id: str, guard: dict) -> dict:
    """Record a policy change with its rollback guard. ``created_at`` is added
    automatically; the caller supplies the trigger id, target file, and the
    sha256 of the recorded (good) state."""
    policy_id = validate_policy_id(policy_id)
    if not isinstance(guard, dict):
        raise BrainError("guard must be a dict")
    for key in ("rollback_trigger", "rollback_target", "backup_of"):
        if not isinstance(guard.get(key), str) or not guard[key].strip():
            raise BrainError(f"guard.{key} must be a non-empty string")
    if not _HEX64_RE.fullmatch(guard["backup_of"]):
        raise BrainError("guard.backup_of must be a 64-char hex sha256")
    target_rel = _normalize_policy_target(home, guard["rollback_target"])
    record = {
        "policy_id": policy_id,
        "guard": {
            "rollback_trigger": guard["rollback_trigger"],
            "rollback_target": target_rel,
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
    trigger_id = validate_trigger_id(trigger_id)
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
        policy_id = validate_policy_id(policy_id)
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
    policy_id = validate_policy_id(policy_id)
    trigger_id = validate_trigger_id(trigger_id)
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

    # SEC-05: re-derive the target through the containment boundary
    # immediately before the operation; the stored value is home-relative and
    # never an arbitrary external path. Symlinks are rejected by policy.
    try:
        target = resolve_under(home, guard["rollback_target"], allow_missing=False)
    except (ValueError, TypeError, OSError) as exc:
        raise BrainError(f"Unsafe rollback target refused for policy {policy_id!r}: {exc}") from exc
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


# ---------------------------------------------------------------------------
# Foreign material inspection (local evidence only; never installation)
# ---------------------------------------------------------------------------

_FOREIGN_KINDS = ("skill", "tool", "policy")
_FOREIGN_MAX_ENTRIES = 256
_FOREIGN_MAX_FILE_BYTES = 1 << 20
_FOREIGN_MAX_TOTAL_BYTES = 8 << 20
_FOREIGN_SECRET_RE = re.compile(
    r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
    r"\b(?:api[_-]?key|access[_-]?token|password|secret)"
    r"""["']?\s*[:=]\s*["']?[A-Za-z0-9_+/=-]{8,}""",
    re.IGNORECASE,
)
_FOREIGN_SHELL_RE = re.compile(
    r"\brm\s+-(?:[a-z]*r[a-z]*f|[a-z]*f[a-z]*r)\b|"
    r"\b(?:remove-item|del)\b[^\n]*(?:-recurse|/s)\b|"
    r"\b(?:mkfs(?:\.\w+)?|shutdown)\b|"
    r"\b(?:bash|sh)\s+-c\b|\b(?:iex|invoke-expression)\b",
    re.IGNORECASE,
)
_FOREIGN_INJECTION_RE = re.compile(
    r"\b(?:ignore|disregard|override)\s+(?:all\s+)?"
    r"(?:previous|prior|system|developer|safety)\b|"
    r"\b(?:reveal|print|exfiltrate)\s+(?:the\s+)?(?:secrets?|credentials?|system prompt)\b",
    re.IGNORECASE,
)


def _foreign_path(home: Path, source: str | Path) -> Path:
    """Preserve lexical components so absolute paths cannot hide symlinks."""
    try:
        root = Path(home).resolve()
        raw = Path(source)
        if raw.is_absolute():
            relative = raw.relative_to(root).as_posix()
        elif isinstance(source, Path):
            relative = source.as_posix()
        else:
            relative = os.fspath(source)
        if len(relative) > 512:
            raise ValueError("source path is too long")
        return resolve_under(root, relative)
    except (OSError, TypeError, ValueError) as exc:
        raise BrainError(f"Unsafe foreign source: {exc}") from exc


def _foreign_security(text: str) -> list[dict]:
    """Bounded, redacted heuristics; a clean result is not an execution approval."""
    lowered = text.lower()
    findings = []
    if _SECRET_RE.search(text) or _FOREIGN_SECRET_RE.search(text):
        findings.append({"category": "secret", "detail": "secret-like value"})
    if (
        any(token in lowered for token in _DANGEROUS_TOKENS)
        or _DISK_FORMAT_RE.search(lowered)
        or _FOREIGN_SHELL_RE.search(text)
    ):
        findings.append({"category": "destructive", "detail": "dangerous shell pattern"})
    if _EXFIL_URL_RE.search(text) and re.search(
        r"\b(?:curl|wget|invoke-webrequest|invoke-restmethod)\b", text, re.IGNORECASE
    ):
        findings.append({"category": "exfiltration", "detail": "external network command"})
    if any(phrase in lowered for phrase in _INJECTION_PHRASES) or _FOREIGN_INJECTION_RE.search(
        text
    ):
        findings.append(
            {"category": "instruction-injection", "detail": "instruction override pattern"}
        )
    return findings


def inspect_foreign(home: Path, source: str | Path, *, origin_ref: str, kind: str) -> dict:
    """Inspect a home-contained file/tree without execution or writes.

    Invalid input and incomplete scans raise BrainError. Security findings return
    ``passed=False`` without including matched secret values. Limits are 256
    filesystem entries, 1 MiB per file, 8 MiB total, and 512-character paths.
    Permissions are POSIX mode evidence, not a Windows ACL audit.
    """
    if (
        not isinstance(origin_ref, str)
        or not origin_ref
        or origin_ref != origin_ref.strip()
        or len(origin_ref) > 512
        or any(ord(char) < 32 or ord(char) == 127 for char in origin_ref)
    ):
        raise BrainError("origin_ref must be a nonempty, bounded, single-line provenance reference")
    if kind not in _FOREIGN_KINDS:
        raise BrainError(f"Unsupported foreign kind; expected one of {_FOREIGN_KINDS}")
    root = Path(home).resolve()
    source_path = _foreign_path(root, source)
    source_relative = source_path.relative_to(root).as_posix()
    files: list[dict] = []
    directories: list[dict] = []
    findings: list[dict] = []
    pending = [source_path]
    entries = 0
    total_bytes = 0
    try:
        source_is_file = stat.S_ISREG(source_path.lstat().st_mode)
        while pending:
            current = pending.pop()
            relative = current.relative_to(root).as_posix()
            current = _foreign_path(root, relative)
            info = current.lstat()
            entries += 1
            if entries > _FOREIGN_MAX_ENTRIES:
                raise BrainError("Foreign inspection entry limit exceeded")
            mode = stat.S_IMODE(info.st_mode)
            local = current.name if source_is_file else current.relative_to(source_path).as_posix()
            evidence = {"path": local, "mode": f"{mode:04o}", "executable": bool(mode & 0o111)}
            if mode & (stat.S_ISUID | stat.S_ISGID) or (os.name != "nt" and mode & 0o022):
                findings.append(
                    {"path": local, "category": "permissions", "detail": "unsafe permission mode"}
                )
            if stat.S_ISDIR(info.st_mode):
                directories.append(evidence)
                children = []
                with os.scandir(current) as scan:
                    for entry in scan:
                        children.append(current / entry.name)
                        if entries + len(pending) + len(children) > _FOREIGN_MAX_ENTRIES:
                            raise BrainError("Foreign inspection entry limit exceeded")
                pending.extend(sorted(children, reverse=True))
                continue
            if not stat.S_ISREG(info.st_mode):
                raise BrainError("Foreign source contains a non-regular file")
            total_bytes += info.st_size
            if info.st_size > _FOREIGN_MAX_FILE_BYTES or total_bytes > _FOREIGN_MAX_TOTAL_BYTES:
                raise BrainError("Foreign inspection byte limit exceeded")
            with current.open("rb") as stream:
                content = stream.read(_FOREIGN_MAX_FILE_BYTES + 1)
            if len(content) != info.st_size:
                raise BrainError("Foreign source changed during inspection")
            digest = sha256_file(current)
            after = current.lstat()
            unchanged = all(
                getattr(after, field) == getattr(info, field)
                for field in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
            )
            if hashlib.sha256(content).hexdigest() != digest or not unchanged:
                raise BrainError("Foreign source changed during inspection")
            try:
                text = content.decode("utf-8-sig")
                if "\x00" in text:
                    raise UnicodeError("NUL bytes")
            except UnicodeError:
                security = [{"category": "unscannable", "detail": "not inspectable UTF-8 text"}]
            else:
                security = _foreign_security(text)
            findings.extend({"path": local, **finding} for finding in security)
            files.append({**evidence, "sha256": digest, "size_bytes": info.st_size})
    except (OSError, ValueError) as exc:
        raise BrainError(f"Foreign inspection failed: {exc}") from exc
    if not files:
        raise BrainError("Foreign source contains no regular files")
    return {
        "schema_version": 1,
        "origin_ref": origin_ref,
        "kind": kind,
        "source": source_relative,
        "source_type": "file" if source_is_file else "directory",
        "containment": {"within_home": True, "symlinks": "rejected"},
        "permission_scope": "posix-mode" if os.name != "nt" else "mode-only-not-windows-acl",
        "files": sorted(files, key=lambda item: item["path"]),
        "directories": sorted(directories, key=lambda item: item["path"]),
        "total_bytes": total_bytes,
        "findings": sorted(findings, key=lambda item: (item["path"], item["category"])),
        "passed": not findings,
    }


def quarantine_foreign(home: Path, source: str | Path, *, origin_ref: str, kind: str) -> dict:
    """Copy a clean inspection to a collision-refusing evidence capsule.

    The capsule contains ``payload/`` and ``manifest.json``. It does not install,
    activate, trust, or execute the material. Incomplete copies have no manifest.
    """
    inspection = inspect_foreign(home, source, origin_ref=origin_ref, kind=kind)
    if not inspection["passed"]:
        categories = sorted({finding["category"] for finding in inspection["findings"]})
        raise BrainError(f"Foreign inspection refused quarantine: {', '.join(categories)}")
    stable_id = hashlib.sha256(
        json.dumps(inspection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    root = Path(home).resolve()
    destination_relative = (
        (_immune_dir(root) / "quarantine" / f"foreign-{stable_id}").relative_to(root).as_posix()
    )
    try:
        destination = resolve_under(root, destination_relative, allow_missing=True)
        source_path = _foreign_path(root, inspection["source"])
        if destination.is_relative_to(source_path):
            raise BrainError("Foreign source must not contain its quarantine destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = resolve_under(root, destination_relative, allow_missing=True)
        destination.mkdir(exist_ok=False)
        payload = resolve_under(root, f"{destination_relative}/payload", allow_missing=True)
        payload.mkdir()
        for directory in inspection["directories"]:
            if directory["path"] != ".":
                resolve_under(payload, directory["path"], allow_missing=True).mkdir(
                    parents=True, exist_ok=True
                )
        for entry in inspection["files"]:
            source_relative = inspection["source"]
            if inspection["source_type"] == "directory":
                source_relative += "/" + entry["path"]
            original = _foreign_path(root, source_relative)
            target = resolve_under(payload, entry["path"], allow_missing=True)
            with original.open("rb") as incoming, target.open("xb") as outgoing:
                content = incoming.read(_FOREIGN_MAX_FILE_BYTES + 1)
                if len(content) != entry["size_bytes"]:
                    raise BrainError("Foreign source changed while copying; quarantine incomplete")
                outgoing.write(content)
            if sha256_file(target) != entry["sha256"]:
                raise BrainError("Foreign source changed while copying; quarantine incomplete")
        if inspect_foreign(home, source, origin_ref=origin_ref, kind=kind) != inspection:
            raise BrainError("Foreign source changed while copying; quarantine incomplete")
        manifest = {
            "schema_version": 1,
            "id": f"foreign-{stable_id}",
            "destination": destination_relative,
            "inspection": inspection,
        }
        _write_json(resolve_under(destination, "manifest.json", allow_missing=True), manifest)
    except FileExistsError as exc:
        raise BrainError(
            "Foreign quarantine destination already exists; refusing collision"
        ) from exc
    except (OSError, ValueError) as exc:
        raise BrainError(f"Foreign quarantine failed: {exc}") from exc
    return manifest
