"""Independent verifier for the v1 P4 qualification manifest (Task 8, Step 5).

Reads the manifest and its raw evidence from disk in a fresh process and
performs the ten checks from the brief. It trusts nothing the runner
claimed: every check re-derives its own answer from the raw artifacts,
the fresh telemetry files, and a fresh `brain.sqlite` connection.

CLI:
    python scripts/verify_v1_p4_qualification.py \\
        --manifest outputs/reports/v1-p4/qualification-manifest.json \\
        --out outputs/reports/v1-p4/independent-verifier.json
"""

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from second_brain import backup as backup_module  # noqa: E402
from second_brain import db, immune, telemetry  # noqa: E402
from second_brain import fingerprints as fingerprints_module  # noqa: E402
from second_brain import paths as paths_module  # noqa: E402
from second_brain import radar as radar_module  # noqa: E402
from second_brain.errors import BrainError  # noqa: E402
from second_brain.goals import GoalStore  # noqa: E402

REQUIRED_SCENARIOS = frozenset(
    {
        "fresh_session",
        "resumed_session",
        "compacted_session",
        "cross_session_continuity",
        "harness_isolation",
        "harness_switch",
        "malformed_state",
        "stale_state",
        "token_pressure",
        "cache_sensitive",
        "long_running_goal",
        "brain_off",
        "brain_on",
        "recovery_rollback",
        "security_boundary",
        "genuine_project_dogfood",
    }
)

_P4_TABLES = (
    "goals",
    "goal_events",
    "bottleneck_fingerprints",
    "heartbeat_state",
    "heartbeat_runs",
)

_CLAIM_KEY_RE = re.compile(r"model|token|success", re.IGNORECASE)
_FORBIDDEN_MARKERS = (
    "chain_of_thought",
    "chain-of-thought",
    "internal_monologue",
    "<thinking>",
    "tool_input",
    "tool_output",
)
_FORBIDDEN_RECORD_FIELDS = frozenset(
    {
        "prompt",
        "payload",
        "secret",
        "content",
        "tool_input",
        "tool-output",
        "tool-input",
        "tool_output",
        "chain_of_thought",
        "chain-of-thought",
        "thinking",
        "internal_monologue",
        "cot",
    }
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_QUALIFICATION_EVIDENCE_PREFIX = "outputs/reports/v1-p4/"


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )


def _git_currency_detail(
    recorded_sha: Any,
    fresh_sha: str | None,
    repo: Path,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "recorded_sha": recorded_sha,
        "fresh_sha": fresh_sha,
        "repo": str(repo),
        **extra,
    }


def _is_repository_root(repo: Path) -> tuple[bool, str | None]:
    root = _run_git(repo, "rev-parse", "--show-toplevel")
    if root.returncode != 0:
        return False, "could not resolve repository root"
    try:
        return Path(root.stdout.strip()).resolve() == repo.resolve(), None
    except (OSError, RuntimeError):
        return False, "could not resolve repository root"


def _artifact_path(out_dir: Path, ref: Any) -> Path | None:
    """Resolve a relative ref only when it stays under the evidence directory."""
    if not isinstance(ref, str) or not ref:
        return None
    try:
        ref_path = Path(ref)
        # Manifest refs are repository-local evidence names, never filesystem
        # paths. Reject absolute and traversal spellings before resolution.
        if ref_path.is_absolute() or ".." in ref_path.parts:
            return None
        root = out_dir.resolve()
        path = (out_dir / ref_path).resolve()
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return path


def _raw_artifact_path(out_dir: Path, ref: Any) -> Path | None:
    """Resolve only raw evidence refs, excluding manifest/result metadata."""
    path = _artifact_path(out_dir, ref)
    if path is None:
        return None
    try:
        path.relative_to((out_dir / "raw").resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return path


def _forbidden_record_fields(
    node: Any,
    *,
    allowed_fields: frozenset[str] = frozenset(),
) -> list[str]:
    """Find privacy-sensitive field names recursively in JSON-like data."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            field = str(key).casefold()
            if field in _FORBIDDEN_RECORD_FIELDS and field not in allowed_fields:
                found.append(str(key))
            found.extend(_forbidden_record_fields(value, allowed_fields=allowed_fields))
    elif isinstance(node, list):
        for value in node:
            found.extend(_forbidden_record_fields(value, allowed_fields=allowed_fields))
    return found


def check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
    return {"check": name, "ok": bool(ok), "detail": detail}


# ---------------------------------------------------------------------------
# 1. Scenario completeness
# ---------------------------------------------------------------------------


def check_scenario_completeness(manifest: dict[str, Any]) -> dict[str, Any]:
    scenarios = manifest.get("scenarios", [])
    names = [row.get("name") for row in scenarios]
    counts: dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    missing = sorted(REQUIRED_SCENARIOS - set(names))
    unexpected = sorted(set(names) - REQUIRED_SCENARIOS)
    duplicated = sorted(n for n, c in counts.items() if c > 1)
    ok = not missing and not unexpected and not duplicated
    return check(
        "scenario_completeness",
        ok,
        {
            "missing": missing,
            "unexpected": unexpected,
            "duplicated": duplicated,
            "total": len(names),
        },
    )


# ---------------------------------------------------------------------------
# 2. Raw artifact hash integrity
def check_artifact_hash_integrity(manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    mismatches: list[str] = []
    missing: list[str] = []
    unhashed: list[str] = []
    checked = 0
    all_commands = list(manifest.get("setup_commands", []))
    for row in manifest.get("scenarios", []):
        all_commands.extend(row.get("commands", []))
    for index, cmd in enumerate(all_commands):
        if not isinstance(cmd, dict):
            unhashed.append(f"<command[{index}]>")
            continue
        for ref_key, hash_key in (("stdout_ref", "stdout_sha256"), ("stderr_ref", "stderr_sha256")):
            ref = cmd.get(ref_key)
            expected = cmd.get(hash_key)
            label = ref or f"<command[{index}].{ref_key}>"
            if not ref or not expected:
                unhashed.append(label)
                continue
            path = _artifact_path(out_dir, ref)
            if path is None or not path.is_file():
                missing.append(ref)
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            checked += 1
            if actual != expected:
                mismatches.append(ref)
    # Every evidence_refs entry (command captures *and* non-command
    # snapshots written via write_evidence(), e.g. seeded/compacted
    # telemetry fixtures) must also match its manifest-recorded hash, not
    # just the two command-stream refs above.
    for row in manifest.get("scenarios", []):
        ref_hashes = row.get("evidence_ref_hashes", {})
        for ref in row.get("evidence_refs", []):
            expected = ref_hashes.get(ref)
            if not expected:
                unhashed.append(ref)
                continue
            path = _artifact_path(out_dir, ref)
            if path is None or not path.is_file():
                missing.append(ref)
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            checked += 1
            if actual != expected:
                mismatches.append(ref)
    ok = not mismatches and not missing and not unhashed and checked > 0
    return check(
        "artifact_hash_integrity",
        ok,
        {"checked": checked, "mismatches": mismatches, "missing": missing, "unhashed": unhashed},
    )


# ---------------------------------------------------------------------------
# 3. Git SHA / repository currency
# ---------------------------------------------------------------------------


def check_git_currency(manifest: dict[str, Any]) -> dict[str, Any]:
    repo = Path(manifest.get("repo", "."))
    recorded_sha = (manifest.get("git") or {}).get("sha")
    if not repo.is_dir() or not (repo / ".git").exists():
        return check(
            "git_currency",
            False,
            _git_currency_detail(
                recorded_sha,
                None,
                repo,
                reason="repo is not a git checkout",
            ),
        )

    is_root, root_error = _is_repository_root(repo)
    if not is_root:
        return check(
            "git_currency",
            False,
            _git_currency_detail(
                recorded_sha,
                None,
                repo,
                reason=root_error or "repo is not the repository root",
            ),
        )

    fresh = _run_git(repo, "rev-parse", "HEAD")
    fresh_sha = fresh.stdout.strip() if fresh.returncode == 0 else None
    detail = _git_currency_detail(recorded_sha, fresh_sha, repo)
    if not isinstance(recorded_sha, str) or not _GIT_SHA_RE.fullmatch(recorded_sha):
        detail["reason"] = "recorded SHA is malformed"
        return check("git_currency", False, detail)
    if not isinstance(fresh_sha, str) or not _GIT_SHA_RE.fullmatch(fresh_sha):
        detail["reason"] = "could not read a valid HEAD SHA"
        return check("git_currency", False, detail)

    recorded_sha = recorded_sha.lower()
    fresh_sha = fresh_sha.lower()
    detail["recorded_sha"] = recorded_sha
    detail["fresh_sha"] = fresh_sha
    if recorded_sha == fresh_sha:
        detail.update({"ancestor": True, "intervening_paths": [], "disallowed_paths": []})
        return check("git_currency", True, detail)

    ancestor = _run_git(repo, "merge-base", "--is-ancestor", recorded_sha, fresh_sha)
    detail["ancestor"] = ancestor.returncode == 0
    if ancestor.returncode != 0:
        detail["reason"] = "recorded SHA is not an ancestor of HEAD"
        return check("git_currency", False, detail)

    diff = _run_git(
        repo, "diff", "--no-renames", "--name-only", "-z", f"{recorded_sha}..{fresh_sha}", "--"
    )
    if diff.returncode != 0:
        detail["reason"] = "could not inspect changes after recorded SHA"
        return check("git_currency", False, detail)
    paths = [path for path in diff.stdout.split("\0") if path]
    disallowed = sorted(
        path
        for path in paths
        if not path.replace("\\", "/").startswith(_QUALIFICATION_EVIDENCE_PREFIX)
    )
    detail.update({"intervening_paths": paths, "disallowed_paths": disallowed})
    return check("git_currency", not disallowed, detail)


# ---------------------------------------------------------------------------
# 4. Fresh DB integrity, idempotent migration replay, P4 tables present
# ---------------------------------------------------------------------------


def check_database_integrity(manifest: dict[str, Any]) -> dict[str, Any]:
    home = Path(manifest["home"])
    dbfile = paths_module.db_path(home)
    if not dbfile.is_file():
        return check(
            "database_integrity",
            False,
            {"reason": "brain.sqlite missing", "path": str(dbfile)},
        )

    conn = sqlite3.connect(str(dbfile))
    try:
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity_ok = bool(integrity_row) and integrity_row[0] == "ok"
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()
    missing_tables = sorted(t for t in _P4_TABLES if t not in tables)

    first_replay = db.migrate(dbfile)
    second_replay = db.migrate(dbfile)
    idempotent = first_replay == [] and second_replay == []

    ok = integrity_ok and not missing_tables and idempotent
    return check(
        "database_integrity",
        ok,
        {
            "integrity_check": integrity_row[0] if integrity_row else None,
            "missing_p4_tables": missing_tables,
            "migration_replay_idempotent": idempotent,
            "first_replay_applied": first_replay,
            "second_replay_applied": second_replay,
        },
    )


# ---------------------------------------------------------------------------
# 5. Fresh telemetry validation
# ---------------------------------------------------------------------------


def check_telemetry_validation(manifest: dict[str, Any]) -> dict[str, Any]:
    homes = {manifest["home"]}
    for row in manifest.get("scenarios", []):
        if row.get("home"):
            homes.add(row["home"])
    results = {}
    ok = True
    for home_str in sorted(homes):
        home = Path(home_str)
        if not home.is_dir():
            results[home_str] = {"reason": "home missing"}
            ok = False
            continue
        report = telemetry.validate(home)
        results[home_str] = report
        if report["issues"]:
            ok = False
    return check("telemetry_validation", ok, results)


# ---------------------------------------------------------------------------
# 6. Backup/restore preserves a created goal and fingerprint
# ---------------------------------------------------------------------------


def check_backup_restore_preservation(manifest: dict[str, Any]) -> dict[str, Any]:
    home = Path(manifest["home"])
    store = GoalStore(home)
    goal = store.create_goal(
        "independent-verifier backup/restore probe goal",
        "created by the independent verifier",
    )
    fp_store = fingerprints_module.BottleneckFingerprintStore(home)
    fingerprint = fp_store.record_bottleneck(
        fingerprints_module.BottleneckCategory.PROMPT_BLOAT,
        "independent verifier backup/restore probe fingerprint",
        "none; probe only",
        impact_score=1.0,
        signal_key="independent-verifier-probe",
        scope_id="verifier",
        evidence_refs=[],
    )

    backup_dir = backup_module.create_backup(home, note="independent-verifier-probe")

    conn = sqlite3.connect(str(paths_module.db_path(home)))
    try:
        conn.execute("DELETE FROM goals WHERE goal_id = ?", (goal.goal_id,))
        if fingerprint is not None:
            conn.execute(
                "DELETE FROM bottleneck_fingerprints WHERE fingerprint_id = ?",
                (fingerprint.fingerprint_id,),
            )
        conn.commit()
    finally:
        conn.close()

    backup_module.restore_backup(home, backup_dir, force=True)

    restored_goal = GoalStore(home).get_goal(goal.goal_id)
    restored_fp = None
    if fingerprint is not None:
        conn = sqlite3.connect(str(paths_module.db_path(home)))
        try:
            row = conn.execute(
                "SELECT fingerprint_id FROM bottleneck_fingerprints WHERE fingerprint_id = ?",
                (fingerprint.fingerprint_id,),
            ).fetchone()
        finally:
            conn.close()
        restored_fp = row is not None

    ok = (
        restored_goal is not None
        and restored_goal.title == goal.title
        and (fingerprint is None or restored_fp is True)
    )
    return check(
        "backup_restore_preservation",
        ok,
        {
            "goal_id": goal.goal_id,
            "goal_preserved": restored_goal is not None,
            "fingerprint_id": fingerprint.fingerprint_id if fingerprint else None,
            "fingerprint_preserved": restored_fp,
            "backup_dir": str(backup_dir),
        },
    )


# ---------------------------------------------------------------------------
# 7. Stale Radar evidence and unsafe rollback targets are refused
# ---------------------------------------------------------------------------


def check_stale_and_unsafe_refusals(manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    home = Path(manifest["home"])
    stale_row = next((r for r in manifest["scenarios"] if r["name"] == "stale_state"), None)
    candidate_id = (stale_row or {}).get("candidate_id") or (stale_row or {}).get(
        "metrics", {}
    ).get("candidate_id")
    radar_ok = False
    radar_detail: dict[str, Any] = {}
    if candidate_id:
        result = radar_module.ImprovementRadar(home).validate_candidate(candidate_id)
        radar_ok = result.get("status") == "stale"
        radar_detail = result

    scratch = out_dir / "verifier-scratch" / "unsafe-rollback"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "config").mkdir(parents=True, exist_ok=True)
    paths_module.ensure_layout(scratch)
    db.migrate(paths_module.db_path(scratch))
    target = scratch / "state" / "verifier-guarded-target.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    good = b"verifier good state\n"
    target.write_bytes(good)
    good_hash = hashlib.sha256(good).hexdigest()
    immune.register_policy(
        scratch,
        "verifier-unsafe-policy",
        {
            "rollback_trigger": "verifier-unsafe-trigger",
            "rollback_target": "state/verifier-guarded-target.txt",
            "backup_of": good_hash,
        },
    )
    immune.register_trigger(
        scratch,
        "verifier-unsafe-trigger",
        {"metric": "tests_failed", "operator": ">", "value": 0, "window": 1},
    )
    immune.ingest_metric(scratch, "tests_failed", 1, "verifier-probe")
    policy_path = scratch / "immune" / "policies" / "verifier-unsafe-policy.json"
    record = json.loads(policy_path.read_text(encoding="utf-8"))
    record["guard"]["rollback_target"] = "../../outside-secret.txt"
    policy_path.write_text(json.dumps(record), encoding="utf-8")

    unsafe_refused = False
    unsafe_detail = "no exception raised"
    try:
        immune.rollback(
            scratch,
            "verifier-unsafe-policy",
            "verifier-unsafe-trigger",
            "verifier probe",
        )
    except BrainError as exc:
        unsafe_refused = True
        unsafe_detail = str(exc)

    ok = radar_ok and unsafe_refused
    return check(
        "stale_and_unsafe_refusals",
        ok,
        {
            "stale_radar_candidate_id": candidate_id,
            "stale_radar_status": radar_detail.get("status"),
            "unsafe_rollback_refused": unsafe_refused,
            "unsafe_rollback_detail": unsafe_detail,
        },
    )


# ---------------------------------------------------------------------------
# 8. OFF/SHADOW mutation boundaries
# ---------------------------------------------------------------------------


def _read_json_ref(out_dir: Path, ref: str) -> Any:
    path = _artifact_path(out_dir, ref)
    if path is None or not path.is_file():
        raise ValueError(f"invalid or missing evidence ref: {ref!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def check_off_shadow_boundaries(manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    off_row = next((r for r in manifest["scenarios"] if r["name"] == "brain_off"), None)
    on_row = next((r for r in manifest["scenarios"] if r["name"] == "brain_on"), None)
    fresh_row = next((r for r in manifest["scenarios"] if r["name"] == "fresh_session"), None)
    if not off_row or not on_row or not fresh_row:
        return check("off_shadow_boundaries", False, {"reason": "required scenario rows missing"})

    off_home = Path(off_row.get("home", ""))
    off_dbfile = paths_module.db_path(off_home)
    off_runs = 0
    off_state = None
    if off_dbfile.is_file():
        conn = sqlite3.connect(str(off_dbfile))
        try:
            off_runs = conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0]
            off_state = conn.execute("SELECT last_run_at FROM heartbeat_state").fetchone()[0]
        finally:
            conn.close()
    off_no_mutation = off_runs == 0 and off_state is None

    next(
        (
            c["stdout_ref"]
            for c in fresh_row.get("commands", [])
            if "p4-pulse" in c.get("argv", [""])[-1] or any("p4" in a for a in c.get("argv", []))
        ),
        None,
    )
    shadow_no_maintenance = False
    shadow_detail: dict[str, Any] = {}
    for cmd in fresh_row.get("commands", []):
        if "pulse" in cmd.get("argv", []):
            payload = _read_json_ref(out_dir, cmd["stdout_ref"])
            shadow_detail = payload.get("heartbeat", {})
            shadow_no_maintenance = (
                shadow_detail.get("mode") == "shadow"
                and shadow_detail.get("maintenance_mutated") is False
            )
            break

    on_home = Path(on_row.get("home", ""))
    on_dbfile = paths_module.db_path(on_home)
    on_runs = 0
    if on_dbfile.is_file():
        conn = sqlite3.connect(str(on_dbfile))
        try:
            on_runs = conn.execute("SELECT COUNT(*) FROM heartbeat_runs").fetchone()[0]
        finally:
            conn.close()
    on_has_real_records = on_runs >= 1

    ok = off_no_mutation and shadow_no_maintenance and on_has_real_records
    return check(
        "off_shadow_boundaries",
        ok,
        {
            "off_heartbeat_runs": off_runs,
            "off_heartbeat_state": off_state,
            "off_no_mutation": off_no_mutation,
            "shadow_heartbeat": shadow_detail,
            "shadow_no_maintenance_mutation": shadow_no_maintenance,
            "on_heartbeat_runs": on_runs,
            "on_has_real_records": on_has_real_records,
        },
    )


# ---------------------------------------------------------------------------
# 9. Model/token claims are grounded in raw telemetry, or null
# ---------------------------------------------------------------------------


def _walk_claims(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Collect (path, value) for every scalar leaf under a model/token/success
    key. Containers (dict/list) are recursed into, never flagged themselves,
    so an all-`None` `provider_tokens` object never counts as a claim."""
    found: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(value, (dict, list)):
                found.extend(_walk_claims(value, child_path))
            elif (
                _CLAIM_KEY_RE.search(str(key))
                and value is not None
                and value != 0
                and value is not False
            ):
                found.append((child_path, value))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_walk_claims(value, f"{path}[{index}]"))
    return found


def _gather_raw_text(scenario: dict[str, Any], out_dir: Path) -> str:
    """Real raw-evidence text only: command stdout/stderr captures, every
    non-command `evidence_refs` artifact written via `write_evidence()`
    (e.g. seeded/compacted telemetry fixtures), and the scenario's home
    telemetry. NEVER the manifest/scenario row itself — that row is the
    claim under test, and folding it into the haystack would let a
    fabricated claim trivially "ground" itself in its own JSON text.
    """
    chunks: list[str] = []
    home = scenario.get("home")
    if home and Path(home).is_dir():
        for _, _, record in telemetry.iter_records(Path(home)):
            chunks.append(json.dumps(record, default=str))
    for cmd in scenario.get("commands", []):
        for ref_key in ("stdout_ref", "stderr_ref"):
            ref = cmd.get(ref_key)
            if not ref:
                continue
            path = _raw_artifact_path(out_dir, ref)
            if path is not None and path.is_file():
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    for ref in scenario.get("evidence_refs", []):
        path = _raw_artifact_path(out_dir, ref)
        if path is not None and path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def claims_grounded(scenario: dict[str, Any], out_dir: Path) -> tuple[bool, str]:
    """A scenario's metrics must never assert a `model`, `token`, or
    `success` claim unless a raw artifact backs the exact value verbatim.

    Values that are `None`/`0`/`False` are always allowed (an honest
    "unavailable" or "did not happen"); only a truthy, non-null claim
    must be traced.
    """
    suspects = _walk_claims(scenario.get("metrics", {}))
    if not suspects:
        return True, "no non-null model/token/success claims present"
    haystack = _gather_raw_text(scenario, out_dir)
    for key, value in suspects:
        if str(value) not in haystack:
            return False, (
                f"claim {key}={value!r} is not backed by any raw artifact "
                f"for scenario {scenario.get('name')!r}"
            )
    return True, "every model/token/success claim traced to a raw artifact"


def check_claims_grounded(manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    failures: list[str] = []
    for row in manifest.get("scenarios", []):
        ok, detail = claims_grounded(row, out_dir)
        if not ok:
            failures.append(detail)
    return check("claims_grounded", not failures, {"failures": failures})


# ---------------------------------------------------------------------------
# 10. No prompt text, tool payloads, secrets, or chain-of-thought markers
# ---------------------------------------------------------------------------


def check_privacy_absence(manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    offenders: list[str] = []
    scanned = 0
    all_commands = list(manifest.get("setup_commands", []))
    for row in manifest.get("scenarios", []):
        all_commands.extend(row.get("commands", []))
    command_refs: set[str] = set()
    for cmd in all_commands:
        if not isinstance(cmd, dict):
            continue
        allowed_fields = (
            frozenset({"content"})
            if "action-cache" in [str(arg) for arg in cmd.get("argv", [])]
            else frozenset()
        )
        for ref_key in ("stdout_ref", "stderr_ref"):
            ref = cmd.get(ref_key)
            if not ref:
                continue
            command_refs.add(ref)
            path = _artifact_path(out_dir, ref)
            if path is None or not path.is_file():
                continue
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            scanned += 1
            lowered = raw_text.lower()
            for marker in _FORBIDDEN_MARKERS:
                if marker in lowered:
                    offenders.append(f"{ref}: contains {marker!r}")
            try:
                parsed = json.loads(raw_text)
            except (json.JSONDecodeError, ValueError):
                continue
            for field in _forbidden_record_fields(parsed, allowed_fields=allowed_fields):
                offenders.append(f"{ref}: forbidden field {field!r} present")
    # Non-command evidence artifacts written via write_evidence() (seeded/
    # compacted telemetry fixtures, etc.) carry the same privacy obligations.
    for row in manifest.get("scenarios", []):
        for ref in row.get("evidence_refs", []):
            if ref in command_refs:
                continue
            path = _artifact_path(out_dir, ref)
            if path is None or not path.is_file():
                continue
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            scanned += 1
            lowered = raw_text.lower()
            for marker in _FORBIDDEN_MARKERS:
                if marker in lowered:
                    offenders.append(f"{ref}: contains {marker!r}")
            try:
                parsed = json.loads(raw_text)
            except (json.JSONDecodeError, ValueError):
                continue
            for field in _forbidden_record_fields(parsed):
                offenders.append(f"{ref}: forbidden field {field!r} present")
    homes = {manifest["home"]}
    for row in manifest.get("scenarios", []):
        if row.get("home"):
            homes.add(row["home"])
    for home_str in homes:
        home = Path(home_str)
        if not home.is_dir():
            continue
        for _, _, record in telemetry.iter_records(home):
            for field in _forbidden_record_fields(record):
                offenders.append(f"telemetry {home_str}: forbidden field {field!r} present")
            scanned += 1
    ok = not offenders and scanned > 0
    return check("privacy_absence", ok, {"scanned": scanned, "offenders": offenders})


CHECKS = (
    check_scenario_completeness,
    check_artifact_hash_integrity,
    check_git_currency,
    check_database_integrity,
    check_telemetry_validation,
    check_backup_restore_preservation,
    check_stale_and_unsafe_refusals,
    check_off_shadow_boundaries,
    check_claims_grounded,
    check_privacy_absence,
)


def verify(manifest_path: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = manifest_path.parent

    results = []
    for fn in CHECKS:
        try:
            if fn in (check_scenario_completeness,):
                results.append(fn(manifest))
            elif fn in (
                check_artifact_hash_integrity,
                check_stale_and_unsafe_refusals,
                check_off_shadow_boundaries,
                check_claims_grounded,
                check_privacy_absence,
            ):
                results.append(fn(manifest, out_dir))
            elif fn in (
                check_git_currency,
                check_database_integrity,
                check_telemetry_validation,
                check_backup_restore_preservation,
            ):
                results.append(fn(manifest))
            else:
                results.append(fn(manifest))
        except Exception as exc:
            results.append(check(fn.__name__, False, {"exception": f"{type(exc).__name__}: {exc}"}))

    ok = all(row["ok"] for row in results)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest_path": str(manifest_path),
        "ok": ok,
        "checks": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    result = verify(args.manifest)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {"ok": result["ok"], "checks": [(c["check"], c["ok"]) for c in result["checks"]]},
            indent=2,
        )
    )
    return 0 if result["ok"] else 1


def _runner_module() -> Any:
    loaded = sys.modules.get("run_v1_p4_qualification")
    if loaded is not None:
        return loaded
    path = REPO_ROOT / "scripts" / "run_v1_p4_qualification.py"
    spec = importlib.util.spec_from_file_location("run_v1_p4_qualification", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonical qualification producer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_junit_cases(path: Path) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    cases: list[dict[str, Any]] = []
    for element in root.iter("testcase"):
        attrs = {str(key): str(value) for key, value in element.attrib.items()}
        if element.find("failure") is not None or element.find("error") is not None:
            outcome = "failed"
        elif element.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        attrs["outcome"] = outcome
        cases.append(
            {
                "classname": attrs.get("classname", ""),
                "name": attrs.get("name", ""),
                "file": attrs.get("file", "").replace("\\", "/"),
                "outcome": outcome,
                "detail": attrs,
            }
        )
    return cases


def _normalize_test_file(path_value: str, *, allow_absolute: bool = False) -> str | None:
    if not path_value:
        return None
    raw = Path(path_value)
    if (raw.is_absolute() and not allow_absolute) or ".." in raw.parts:
        return None
    try:
        resolved = (raw if raw.is_absolute() else REPO_ROOT / raw).resolve()
        relative = resolved.relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError):
        return None
    if relative.parts[:1] != ("tests",) or relative.suffix != ".py":
        return None
    return relative.as_posix()


def _validate_node_id(node_id: str) -> None:
    path_part, separator, selectors = node_id.partition("::")
    if not separator or not path_part or not selectors:
        raise ValueError(f"pytest node ID must contain a file and non-empty selectors: {node_id!r}")
    if _normalize_test_file(path_part) is None:
        raise ValueError(f"pytest node ID must reference a contained tests/*.py path: {node_id!r}")
    parts = selectors.split("::")
    if any(not part.strip() for part in parts):
        raise ValueError(f"pytest node ID selectors must be non-empty: {node_id!r}")


def _node_parts(node_id: str) -> tuple[str, tuple[str, ...]]:
    path_part, _, selectors = node_id.partition("::")
    parts = tuple(selectors.split("::"))
    return _normalize_test_file(path_part) or path_part.replace("\\", "/"), parts


def _base_function_name(name: str) -> str:
    return name.split("[", 1)[0]


def _case_matches(node_id: str, case: dict[str, Any]) -> bool:
    module, selectors = _node_parts(node_id)
    function = selectors[-1]
    case_file = _normalize_test_file(case.get("file", ""), allow_absolute=True)
    if case_file != module:
        return False
    case_name = case.get("name", "")
    if "[" in function:
        if case_name != function:
            return False
    elif _base_function_name(case_name) != function:
        return False
    classname = str(case.get("classname", ""))
    class_parts = selectors[:-1]
    if class_parts:
        return classname.split(".")[-len(class_parts) :] == list(class_parts)
    module_parts = module[:-3].split("/")
    module_names = {
        ".".join(module_parts),
        ".".join(module_parts[1:]),
        module_parts[-1],
    }
    return classname in module_names


def _junit_outcome(node_id: str, cases: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    matches = [case for case in cases if _case_matches(node_id, case)]
    if not matches:
        return "missing", []
    if any(case["outcome"] == "failed" for case in matches):
        return "failed", matches
    if any(case["outcome"] == "skipped" for case in matches):
        return "skipped", matches
    return "passed", matches


def run_v2_test_observations(home: Path, out_dir: Path, bindings: list[dict]) -> dict:
    """Run reviewed pytest node IDs and export only explicitly testable Gates."""
    home = Path(home).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.relative_to(home)
    strict = _runner_module()._strict_verifier_module()
    _, gate_errors = strict._authority_gate_hashes()
    if gate_errors:
        raise RuntimeError(f"canonical Gate authority is invalid: {gate_errors}")
    identity = _runner_module().qualification_identity(home)
    if not isinstance(bindings, list):
        raise TypeError("bindings must be a list")
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    union: set[str] = set()
    for row in bindings:
        if not isinstance(row, dict):
            raise TypeError("each binding must be an object")
        phase, requirement, feature, gate = (
            row.get("phase"),
            row.get("requirement"),
            row.get("feature"),
            row.get("gate"),
        )
        if (
            not isinstance(phase, str)
            or not phase.strip()
            or not isinstance(requirement, str)
            or not requirement.strip()
        ):
            raise ValueError("binding phase and requirement must be non-empty strings")
        key = (phase, requirement)
        if key not in strict.EXPECTED_REQUIREMENTS:
            raise ValueError(f"unknown canonical requirement: {key!r}")
        if (
            not isinstance(feature, str)
            or not feature.strip()
            or not isinstance(gate, str)
            or not gate.strip()
        ):
            raise ValueError("binding feature and gate must be non-empty strings")
        allowed = strict.REQUIRED_GATE_COVERAGE[key]
        if gate not in allowed or "test" not in allowed[gate]:
            raise ValueError(f"Gate does not explicitly permit test evidence: {gate!r}")
        node_ids = row.get("node_ids")
        if (
            not isinstance(node_ids, list)
            or not node_ids
            or any(not isinstance(node, str) or not node.strip() for node in node_ids)
            or len(set(node_ids)) != len(node_ids)
        ):
            raise ValueError("binding node_ids must be a non-empty unique list of strings")
        for node_id in node_ids:
            _validate_node_id(node_id)
        group = grouped.setdefault(
            (phase, requirement, feature),
            {"phase": phase, "requirement": requirement, "feature": feature, "gates": {}},
        )
        if gate in group["gates"]:
            raise ValueError(f"duplicate Gate binding: {(phase, requirement, feature, gate)!r}")
        group["gates"][gate] = sorted(node_ids)
        union.update(node_ids)
    if not union:
        return {"identity": identity, "evidence_refs": [], "unresolved": [], "capture": None}

    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    junit_path = raw_dir / "pytest.junit.xml"
    stdout_path = raw_dir / "pytest.stdout"
    stderr_path = raw_dir / "pytest.stderr"
    if any(path.exists() for path in (junit_path, stdout_path, stderr_path)):
        raise FileExistsError("refusing to overwrite existing pytest captures")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PYTHON") and key.upper() != "PYTEST_ADDOPTS"
    }
    env["SECOND_BRAIN_HOME"] = str(home)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--junitxml",
        str(junit_path),
        "-o",
        "junit_family=xunit1",
        "--",
        *sorted(union),
    ]
    try:
        process = subprocess.run(
            argv,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            timeout=300,
            check=False,
        )
        stdout = (
            process.stdout
            if isinstance(process.stdout, bytes)
            else str(process.stdout or "").encode()
        )
        stderr = (
            process.stderr
            if isinstance(process.stderr, bytes)
            else str(process.stderr or "").encode()
        )
        exit_code = process.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else str(exc.stdout or "").encode()
        stderr = exc.stderr if isinstance(exc.stderr, bytes) else str(exc.stderr or "").encode()
        stderr += f"\n{exc}".encode("utf-8", "replace")
        exit_code = -1
    except OSError as exc:
        stdout = b""
        stderr = str(exc).encode("utf-8", "replace")
        exit_code = -1
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    cases: list[dict[str, Any]] = []
    junit_error: str | None = None
    if junit_path.is_file():
        try:
            cases = _parse_junit_cases(junit_path)
        except (ET.ParseError, OSError) as exc:
            junit_error = f"{type(exc).__name__}: {exc}"
    else:
        junit_error = "JUnit capture is missing"

    def outcome_for(node_id: str) -> tuple[str, list[dict[str, Any]], str | None]:
        outcome, matches = _junit_outcome(node_id, cases)
        if not matches:
            return "missing", [], junit_error or "selected node ID absent from JUnit"
        reason = None if outcome == "passed" else f"case outcome: {outcome}"
        return outcome, matches, reason

    capture_refs: list[dict[str, Any]] = []
    for kind, path in (("stdout", stdout_path), ("stderr", stderr_path)):
        capture_refs.append(
            {
                "path": path.relative_to(home).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "type": kind,
            }
        )
    if junit_path.is_file():
        capture_refs.append(
            {
                "path": junit_path.relative_to(home).as_posix(),
                "sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
                "type": "junit",
            }
        )
    capture = {
        "argv": [str(value) for value in argv],
        "exit": exit_code,
        "stdout_ref": capture_refs[0]["path"],
        "stderr_ref": capture_refs[1]["path"],
        "junit_ref": capture_refs[2]["path"] if len(capture_refs) == 3 else None,
    }
    evidence_refs: list[dict] = []
    unresolved: list[dict[str, Any]] = []
    for group in sorted(
        grouped.values(), key=lambda item: (item["phase"], item["requirement"], item["feature"])
    ):
        group_cases: list[dict[str, Any]] = []
        group_unresolved: list[dict[str, Any]] = []
        gate_observations: dict[str, dict[str, Any]] = {}
        for gate in sorted(group["gates"]):
            node_ids = group["gates"][gate]
            gate_cases = []
            for node_id in node_ids:
                outcome, matches, reason = outcome_for(node_id)
                case = {
                    "node_id": node_id,
                    "outcome": outcome,
                    "junit_cases": [match["detail"] for match in matches],
                }
                if reason:
                    case["reason"] = reason
                    group_unresolved.append({"gate": gate, **case})
                gate_cases.append(case)
                group_cases.append(case)
            gate_observations[gate] = {
                "node_ids": node_ids,
                "outcomes": gate_cases,
                "all_selected_cases_passed": all(row["outcome"] == "passed" for row in gate_cases),
            }
        if group_unresolved or exit_code != 0:
            unresolved.extend(
                {
                    "phase": group["phase"],
                    "requirement": group["requirement"],
                    "feature": group["feature"],
                    **row,
                }
                for row in group_unresolved
            )
            if not group_unresolved:
                unresolved.append(
                    {
                        "phase": group["phase"],
                        "requirement": group["requirement"],
                        "feature": group["feature"],
                        "gate": sorted(group["gates"])[0],
                        "reason": f"pytest exited {exit_code}",
                    }
                )
            continue
        observed_data = {
            "execution": "pytest",
            "node_ids": sorted(union),
            "case_outcomes": group_cases,
            "capture_hashes": {ref["type"]: ref["sha256"] for ref in capture_refs},
        }
        artifact = _runner_module().export_v2_observation(
            home,
            out_dir
            / "evidence"
            / re.sub(
                r"[^A-Za-z0-9_.-]+",
                "-",
                f"{group['phase']}-{group['requirement']}-{group['feature']}",
            ),
            phase=group["phase"],
            requirement=group["requirement"],
            evidence_type="test",
            feature=group["feature"],
            observed_data=observed_data,
            gate_observations=gate_observations,
            identity=identity,
            producer=Path(__file__),
            raw_refs=capture_refs,
        )
        evidence_refs.append(artifact)
    return {
        "identity": identity,
        "evidence_refs": evidence_refs,
        "unresolved": unresolved,
        "capture": capture,
    }


_V2_CREATE_RE = re.compile(
    r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[\"`\[]?(v2_[A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _static_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        values = [part.value for part in node.values if isinstance(part, ast.Constant)]
        return "".join(value for value in values if isinstance(value, str))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _production_v2_definitions() -> list[dict[str, str | int]]:
    definitions: list[dict[str, str | int]] = []
    canonical_paths = {path.resolve() for path in db.migration_files()}
    for path in sorted((REPO_ROOT / "src").rglob("*")):
        if not path.is_file() or path.resolve() in canonical_paths:
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        if path.suffix.casefold() in {".sql", ".ddl"}:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in _V2_CREATE_RE.finditer(text):
                definitions.append(
                    {
                        "path": relative,
                        "line": text.count("\n", 0, match.start()) + 1,
                        "table": match.group(1).lower(),
                    }
                )
            continue
        if path.suffix.casefold() != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                values = [node.value]
            elif isinstance(node, ast.Call):
                values = node.args
            else:
                continue
            for value in values:
                sql = _static_string(value)
                if sql is None:
                    continue
                for match in _V2_CREATE_RE.finditer(sql):
                    definitions.append(
                        {"path": relative, "line": node.lineno, "table": match.group(1).lower()}
                    )
    return definitions


# The V3 memory CLI (owner decision O1) is a separate command surface, not a competitor for
# the v2 command group: exactly this entry point and this package are reported under ``v3_cli``.
_V3_CLI_ENTRYPOINT = ("brain", "second_brain.kb.cli:main")
_V3_CLI_PACKAGE = ("src", "second_brain", "kb")


def _cli_ownership() -> dict[str, Any]:
    cli_path = REPO_ROOT / "src" / "second_brain" / "cli.py"
    v3_package = REPO_ROOT.joinpath(*_V3_CLI_PACKAGE)
    metadata_path = REPO_ROOT / "pyproject.toml"
    findings: dict[str, Any] = {
        "path": cli_path.relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(cli_path.read_bytes()).hexdigest(),
        "entrypoint": None,
        "entrypoints": {},
        "v2_parser_owned": False,
        "v2_dispatch_owned": False,
        "competing_modules": [],
        "v3_cli": {"entrypoint": None, "modules": []},
    }
    try:
        tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        findings["v2_parser_owned"] = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "v2"
            for node in ast.walk(tree)
        )
        findings["v2_dispatch_owned"] = "cmd_v2" in functions and any(
            isinstance(node, ast.Dict)
            and any(
                isinstance(key, ast.Constant)
                and key.value == "v2"
                and isinstance(value, ast.Name)
                and value.id == "cmd_v2"
                for key, value in zip(node.keys, node.values, strict=True)
            )
            for node in ast.walk(tree)
        )
    except (OSError, SyntaxError) as exc:
        findings["ast_error"] = f"{type(exc).__name__}: {exc}"
    try:
        metadata = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
        entrypoints = metadata.get("project", {}).get("scripts", {})
        if isinstance(entrypoints, dict):
            findings["entrypoints"] = {
                str(name): str(target) for name, target in entrypoints.items()
            }
            findings["entrypoint"] = findings["entrypoints"].get("brainctl")
            v3_name, v3_target = _V3_CLI_ENTRYPOINT
            if findings["entrypoints"].get(v3_name) == v3_target:
                findings["v3_cli"]["entrypoint"] = f"{v3_name}={v3_target}"
            findings["competing_modules"] = sorted(
                f"{name}={target}"
                for name, target in findings["entrypoints"].items()
                if (name, target) not in {("brainctl", "second_brain.cli:main"), _V3_CLI_ENTRYPOINT}
            )
    except (OSError, tomllib.TOMLDecodeError) as exc:
        findings["metadata_error"] = f"{type(exc).__name__}: {exc}"
    ast_competing: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        if path == cli_path:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        if any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "ArgumentParser")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"ArgumentParser", "add_parser"}
                )
            )
            for node in ast.walk(tree)
        ):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if path.is_relative_to(v3_package):
                findings["v3_cli"]["modules"].append(relative)
            else:
                ast_competing.append(relative)
    findings["competing_modules"] = sorted(set(findings["competing_modules"]) | set(ast_competing))
    return findings


def _canonical_sql_table_owners(migration_files: list[Path]) -> dict[str, list[str]]:
    definitions: dict[str, list[str]] = {}
    for path in migration_files:
        text = path.read_text(encoding="utf-8")
        for match in _V2_CREATE_RE.finditer(text):
            table = match.group(1).lower()
            if table.startswith("v2_"):
                definitions.setdefault(table, []).append(path.relative_to(REPO_ROOT).as_posix())
    return definitions


def observe_v2_structure(home: Path, out_dir: Path) -> dict:
    """Inspect migration and command ownership instead of probing presence only."""
    home = Path(home).resolve()
    out_dir = Path(out_dir).resolve()
    runner = _runner_module()
    identity = runner.qualification_identity(home)
    strict = runner._strict_verifier_module()
    _, gate_errors = strict._authority_gate_hashes()
    if gate_errors:
        raise RuntimeError(f"canonical Gate authority is invalid: {gate_errors}")
    evidence_refs: list[dict] = []
    unresolved: list[dict[str, Any]] = []

    migration_files = db.migration_files()
    definitions = _canonical_sql_table_owners(migration_files)
    competing_definitions = _production_v2_definitions()
    expected_tables = {
        "v2_candidates",
        "v2_interventions",
        "v2_observations",
        "v2_frontier_items",
        "v2_rollout_events",
        "v2_qualification",
    }
    duplicate_tables = {table: owners for table, owners in definitions.items() if len(owners) != 1}
    missing_tables = sorted(expected_tables - set(definitions))
    extra_tables = sorted(set(definitions) - expected_tables)
    migration_data = {
        "migration_files": [
            {
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in migration_files
        ],
        "table_owners": definitions,
        "duplicate_tables": duplicate_tables,
        "missing_tables": missing_tables,
        "unexpected_v2_tables": extra_tables,
        "competing_production_definitions": competing_definitions,
    }
    if duplicate_tables or missing_tables or extra_tables or competing_definitions:
        unresolved.append({"gate": "single_table_and_migration_owner", "findings": migration_data})
    else:
        evidence_refs.append(
            runner.export_v2_observation(
                home,
                out_dir / "evidence-single-table",
                phase="v2-0",
                requirement="baseline_identity_and_schema",
                evidence_type="verification",
                feature="migration-ownership",
                observed_data=migration_data,
                gate_observations={
                    "single_table_and_migration_owner": {"table_owners": definitions}
                },
                identity=identity,
                producer=Path(__file__),
            )
        )

    cli_data = _cli_ownership()
    cli_data["command_owner"] = {
        "path": cli_data["path"],
        "sha256": cli_data["sha256"],
    }
    if (
        not cli_data["v2_parser_owned"]
        or not cli_data["v2_dispatch_owned"]
        or cli_data["entrypoint"] != "second_brain.cli:main"
        or cli_data["competing_modules"]
    ):
        unresolved.append({"gate": "single_command_module", "findings": cli_data})
    else:
        evidence_refs.append(
            runner.export_v2_observation(
                home,
                out_dir / "evidence-single-command",
                phase="v2-b",
                requirement="low_friction_io",
                evidence_type="verification",
                feature="single-command-module",
                observed_data=cli_data,
                gate_observations={
                    "single_command_module": {"command_owner": cli_data["command_owner"]}
                },
                identity=identity,
                producer=Path(__file__),
            )
        )
    return {"identity": identity, "evidence_refs": evidence_refs, "unresolved": unresolved}


if __name__ == "__main__":
    sys.exit(main())
