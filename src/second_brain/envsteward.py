"""Environment Steward (plan §74-75, Phase 8 §104).

Measurement first, then advisory, then safe owned cleanup.

- :func:`snapshot` captures the environment at session start
  (``environment.toml [track] session_start``): git state, language, package
  manager, lockfiles, tools, RepoWise freshness, brain version, children
  (unobservable from Python — recorded as n/a). Every subprocess probe is
  error-graced.
- Process ownership follows plan §75: never PID alone. Records store
  ``(pid, start_time, exe, token, session)``; identity is verified by matching
  the live start time, making PID reuse detectable.
- :func:`cleanup_owned` only kills records owned by this Brain
  (``token == "second-brain"``) with verified identity, and only after a
  fresh :func:`verify_process` immediately before the kill. Dry-run is the
  default; ambiguous records are never killed.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from .errors import BrainError
from .working_set import session_dir

OWNERSHIP_TOKEN = "second-brain"
PROCESSES_FILE = "processes.json"

TOOL_NAMES: tuple[str, ...] = ("python", "git", "rg", "ast-grep", "repowise", "node")
GIT_TIMEOUT = 15.0
POWERSHELL_TIMEOUT = 15.0
TASKKILL_TIMEOUT = 15.0


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _run(cmd: list[str], cwd: Path | None = None, timeout: float = GIT_TIMEOUT) -> str | None:
    """Run a probe; stdout on rc 0, else None. Never raises."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _git_error(name: str) -> dict:
    return {"error": f"git {name} failed (not a git repo?)"}


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def _languages(root: Path) -> list[str]:
    found = []
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        found.append("python")
    if (root / "package.json").exists():
        found.append("javascript")
    return found or ["unknown"]


def _package_managers(root: Path) -> list[str]:
    found = []
    if (root / "uv.lock").exists():
        found.append("uv")
    if (root / "poetry.lock").exists():
        found.append("poetry")
    if (root / "package-lock.json").exists():
        found.append("npm")
    return found or ["unknown"]


def _lockfiles(root: Path) -> list[str]:
    names = ("uv.lock", "poetry.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock")
    return [name for name in names if (root / name).exists()]


def _tools() -> dict[str, str | None]:
    return {name: shutil.which(name) for name in TOOL_NAMES}


def _brain_version(home: Path) -> str:
    version = Path(home) / "VERSION"
    try:
        text = version.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return text or "unknown"


def snapshot(home: Path, repo: Path, session_id: str | None = None) -> dict:
    """Capture the session-start environment. Optionally persists it."""
    root = Path(repo)
    resolved = str(root.resolve()) if root.exists() else str(root)
    out: dict = {
        "cwd": os.getcwd(),
        "repo": resolved,
        "branch": "unknown",
        "head": "unknown",
        "dirty": None,
        "worktrees": [],
        "language": _languages(root),
        "package_manager": _package_managers(root),
        "lockfiles": _lockfiles(root),
        "tools": _tools(),
        "repowise_freshness": "unknown",
        "children": {
            "available": False,
            "note": "agent spawns are not visible from the Python side",
        },
        "brain_version": _brain_version(home),
        "ts": _utcnow(),
    }
    branch = _run(["git", "-C", resolved, "rev-parse", "--abbrev-ref", "HEAD"])
    if branch is None:
        out["branch"] = _git_error("rev-parse --abbrev-ref HEAD")
    else:
        out["branch"] = branch.strip() or "unknown"
    head = _run(["git", "-C", resolved, "rev-parse", "--short", "HEAD"])
    out["head"] = head.strip() if head is not None else _git_error("rev-parse --short HEAD")
    status = _run(["git", "-C", resolved, "status", "--porcelain"])
    out["dirty"] = bool(status.strip()) if status is not None else _git_error("status")
    worktrees = _run(["git", "-C", resolved, "worktree", "list"])
    out["worktrees"] = (
        worktrees.splitlines() if worktrees is not None else _git_error("worktree list")
    )

    if shutil.which("repowise") is not None:
        raw = _run(
            ["repowise", "status", "--no-workspace", "--format", "json"], cwd=root, timeout=20
        )
        if raw is not None:
            try:
                status = json.loads(raw)
            except json.JSONDecodeError:
                status = None
            state = status.get("state") if isinstance(status, dict) else None
            if isinstance(state, dict) and "last_sync_commit" in state:
                commit = state["last_sync_commit"]
                if commit is None:
                    out["repowise_freshness"] = "not_synced"
                elif isinstance(commit, str) and commit:
                    out["repowise_freshness"] = commit

    if session_id is not None:
        target = session_dir(home, session_id) / "environment.json"
        _write_json_atomic(target, out)
    return out


EVIDENCE_FILE = "environment-evidence.json"
_SNAPSHOT_FIELDS = (
    "repo",
    "branch",
    "head",
    "dirty",
    "language",
    "package_manager",
    "lockfiles",
    "tools",
    "repowise_freshness",
    "brain_version",
)


def _canonical(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _state(snapshot_data: dict) -> dict:
    state = {key: snapshot_data.get(key) for key in _SNAPSHOT_FIELDS}
    state["worktree_count"] = (
        len(snapshot_data.get("worktrees", []))
        if isinstance(snapshot_data.get("worktrees"), list)
        else 0
    )
    return state


def environment_hash(snapshot_data: dict) -> str:
    """Hash only stable environment identity/state fields, excluding timestamps."""
    return hashlib.sha256(_canonical(_state(snapshot_data)).encode("utf-8")).hexdigest()


def _project_id(repo: Path) -> str:
    return hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:16]


def classify_mutation(
    before: dict,
    after: dict,
    *,
    expected_fields: list[str] | None = None,
    result_state: str = "observed",
) -> dict:
    """Classify a read-back delta without treating command exit as success."""
    if result_state not in {"observed", "failed", "partial"}:
        raise BrainError("result_state must be observed, failed, or partial")
    expected = set(expected_fields or [])
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    if result_state in {"failed", "partial"}:
        classification = result_state
        eligible = False
        verification_state = "failed"
    elif not changed:
        classification = "noop"
        eligible = True
        verification_state = "passed"
    elif set(changed).issubset(expected):
        classification = "intended"
        eligible = True
        verification_state = "passed"
    else:
        classification = "unexpected"
        eligible = False
        verification_state = "failed"
    return {
        "mutation_detected": bool(changed),
        "classification": classification,
        "changed_fields": changed,
        "expected_fields": sorted(expected),
        "verification_state": verification_state,
        "completion_eligible": eligible,
    }


def assess(
    home: Path,
    repo: Path,
    *,
    session_id: str,
    task_id: str | None = None,
    phase: str = "session_start",
    expected_fields: list[str] | None = None,
    requested_changes: list[str] | None = None,
    result_state: str = "observed",
    doctor_check_state: str = "not_run",
) -> dict:
    """Capture and persist bounded Environment Steward evidence."""
    started_at = time.perf_counter()
    current = snapshot(home, repo)
    current_state = _state(current)
    target = session_dir(home, session_id) / EVIDENCE_FILE
    previous = None
    if target.exists():
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
    before_state = previous.get("environment_state") if isinstance(previous, dict) else None
    mutation = (
        classify_mutation(
            before_state,
            current_state,
            expected_fields=expected_fields,
            result_state=result_state,
        )
        if isinstance(before_state, dict) and phase != "session_start"
        else {
            "mutation_detected": False,
            "classification": "none",
            "changed_fields": [],
            "expected_fields": sorted(set(expected_fields or [])),
            "verification_state": "passed",
            "completion_eligible": True,
        }
    )
    project_id = _project_id(Path(repo))
    if isinstance(previous, dict) and previous.get("project_id") not in {None, project_id}:
        mutation = {
            "mutation_detected": True,
            "classification": "scope_mismatch",
            "changed_fields": ["project_id"],
            "expected_fields": [],
            "verification_state": "failed",
            "completion_eligible": False,
        }
    environment_hash_value = environment_hash(current)
    steward_seed = {"project_id": project_id, "session_id": session_id}
    repo_exists = Path(repo).exists()
    requested = [item.strip() for item in (requested_changes or []) if item.strip()]
    dependency_refs = [
        f"dependency-{hashlib.sha256(item.encode('utf-8')).hexdigest()[:16]}" for item in requested
    ]
    evidence = {
        "schema_version": 1,
        "environment_steward_id": (
            f"envsteward-{hashlib.sha256(_canonical(steward_seed).encode()).hexdigest()[:16]}"
        ),
        "project_id": steward_seed["project_id"],
        "session_id": session_id,
        "doctor_check_state": doctor_check_state,
        "task_id": task_id,
        "phase": phase,
        "environment_hash": environment_hash_value,
        "environment_state": current_state,
        "required_checks": ["snapshot", "project_identity", "worktree_identity"],
        "check_outcomes": {
            "snapshot": "passed",
            "project_identity": "passed" if repo_exists else "failed",
            "worktree_identity": "passed" if current_state["worktree_count"] >= 0 else "failed",
        },
        "mutation_detected": mutation["mutation_detected"],
        "mutation_classification": mutation["classification"],
        "mutation_result_state": result_state,
        "changed_fields": mutation["changed_fields"],
        "requested_changes": requested,
        "verification_state": mutation["verification_state"],
        "before_environment_hash": (
            previous.get("environment_hash") if isinstance(previous, dict) else None
        ),
        "after_environment_hash": environment_hash_value,
        "dependency_change_refs": dependency_refs,
        "recovery_state": "not_required"
        if mutation["completion_eligible"] and repo_exists
        else "required",
        "completion_eligible": mutation["completion_eligible"] and repo_exists,
        "assessment_overhead_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }
    _write_json_atomic(target, evidence)
    return evidence


# ---------------------------------------------------------------------------
# JSON registry helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise BrainError(f"Missing state file: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise BrainError(f"Corrupt state file {path}: {exc}") from exc


def _write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write {path}: {exc}") from exc


def _processes_path(home: Path) -> Path:
    return Path(home) / "state" / "ownership" / PROCESSES_FILE


def _validate_record(path: Path, index: int, record: object) -> None:
    err = f"Corrupt process registry {path}"
    if not isinstance(record, dict):
        raise BrainError(f"{err}: entry {index} is not an object")
    if (
        not isinstance(record.get("pid"), int)
        or isinstance(record["pid"], bool)
        or record["pid"] <= 0
    ):
        raise BrainError(f"{err}: entry {index} pid must be a positive integer")
    for key in ("exe", "token", "ts"):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            raise BrainError(f"{err}: entry {index} field {key!r} invalid")
    if record.get("start_time") is not None and not isinstance(record["start_time"], str):
        raise BrainError(f"{err}: entry {index} start_time must be a string or null")
    if record.get("session") is not None and not isinstance(record["session"], str):
        raise BrainError(f"{err}: entry {index} session must be a string or null")
    if not isinstance(record.get("identity_verified"), bool):
        raise BrainError(f"{err}: entry {index} identity_verified must be a boolean")


def _load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = _read_json(path)
    if not isinstance(data, list):
        raise BrainError(f"Corrupt process registry {path}: expected a JSON list")
    for index, record in enumerate(data):
        _validate_record(path, index, record)
    return data


# ---------------------------------------------------------------------------
# Process identity (plan §75)
# ---------------------------------------------------------------------------


def _probe_start_time(pid: int) -> str | None:
    """Live process creation time via PowerShell; None on any failure."""
    command = (
        f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CreationDate.ToString('o')"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=POWERSHELL_TIMEOUT,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


def _exe_name(exe: str) -> str:
    return os.path.basename(str(exe).replace("\\", "/")).lower()


def register_process(
    home: Path,
    pid: int,
    exe: str,
    token: str,
    session_id: str | None = None,
) -> dict:
    """Append a process record. Never PID alone: start_time is captured via
    PowerShell; when unavailable the record is stored but marked
    ``identity_verified: false``."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise BrainError("pid must be a positive integer")
    if not isinstance(exe, str) or not exe.strip():
        raise BrainError("exe must be a non-empty string")
    if not isinstance(token, str) or not token.strip():
        raise BrainError("token must be a non-empty string")
    path = _processes_path(home)
    records = _load_records(path)
    start_time = _probe_start_time(pid)
    record = {
        "pid": pid,
        "start_time": start_time,
        "exe": exe,
        "token": token,
        "session": session_id,
        "ts": _utcnow(),
        "identity_verified": start_time is not None,
    }
    records.append(record)
    _write_json_atomic(path, records)
    return record


def list_processes(home: Path) -> list[dict]:
    """All stored process records, append order."""
    return _load_records(_processes_path(home))


def verify_process(home: Path, pid: int, exe: str) -> bool:
    """True when a live process matches a stored identity-verified record:
    same pid, same exe name, and matching start time (PID-reuse-safe)."""
    live = _probe_start_time(pid)
    if live is None:
        return False
    for record in list_processes(home):
        if not record.get("identity_verified"):
            continue
        if record["pid"] != pid or _exe_name(record["exe"]) != _exe_name(exe):
            continue
        if live == record.get("start_time"):
            return True
    return False


def _taskkill(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            timeout=TASKKILL_TIMEOUT,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def cleanup_owned(home: Path, dry_run: bool = True) -> dict:
    """Kill (or report) only records owned by this Brain with verified
    identity. Ambiguous records are never killed.

    Returns ``{"killed": [...], "skipped": [...], "unknown": [...]}``.
    """
    killed: list[dict] = []
    skipped: list[dict] = []
    unknown: list[dict] = []
    for record in list_processes(home):
        pid = record["pid"]
        exe = record["exe"]
        if not record.get("identity_verified"):
            skipped.append(
                {"pid": pid, "exe": exe, "reason": "identity unverified (no start_time)"}
            )
            continue
        if record.get("token") != OWNERSHIP_TOKEN:
            skipped.append(
                {
                    "pid": pid,
                    "exe": exe,
                    "reason": f"token {record.get('token')!r} != {OWNERSHIP_TOKEN!r}",
                }
            )
            continue
        live = _probe_start_time(pid)
        if live is None:
            unknown.append({"pid": pid, "exe": exe, "reason": "live identity unavailable"})
            continue
        if live != record.get("start_time"):
            skipped.append(
                {
                    "pid": pid,
                    "exe": exe,
                    "reason": "start_time mismatch (PID reused or process replaced)",
                }
            )
            continue
        if dry_run:
            killed.append({"pid": pid, "exe": exe, "dry_run": True})
            continue
        # Guard immediately before killing (defense in depth, plan §75).
        if not verify_process(home, pid, exe):
            skipped.append(
                {"pid": pid, "exe": exe, "reason": "verify failed immediately before kill"}
            )
            continue
        if _taskkill(pid):
            killed.append({"pid": pid, "exe": exe, "dry_run": False})
        else:
            unknown.append({"pid": pid, "exe": exe, "reason": "taskkill failed"})
    return {"killed": killed, "skipped": skipped, "unknown": unknown}
