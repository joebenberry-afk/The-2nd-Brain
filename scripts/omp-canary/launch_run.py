"""External launcher/supervisor for OMP qualification runs.

The launcher OWNS the OMP child process: it records executable identities,
starts the read-only DB watcher first and waits for its baseline
acknowledgment, re-validates the run-start binding at the last boundary before
spawn, spawns the real OMP process (bun + canary src entry) with the run
environment, waits for the actual process exit, records exit code and
timestamps, stops and reaps the watcher, evaluates per-run expectations and
reports success only when the evidence is complete and health-checked.

Supervision is exception-safe: teardown (child kill/reap, coordinator stop,
watcher stop/reap, log closure, partial launch record) runs in a finally path
for every exit, including early binding failure and operator interruption.

Optionally it also runs the external coordinator: it watches the canary trace
for the identity-bound ``isolation:hold-begin:`` record and creates the exact
nonce-bound signal file after the supervisor's refusal marker appears. The
signal only permits fixture-controlled work to proceed; it is not cleanup
evidence.

Usage:
    python launch_run.py --spec <spec.json>

Spec fields (all paths absolute unless noted):
    name, run_dir, home, fixture, prompt_file, trace_file, profile,
    bun, cli, extension[], hashes_file, hashes_base, identities_file,
    python, watcher_script, extra_env{}, hold_prefix|null,
    coordinator{marker}|null, timeout_seconds, watcher_timeout_seconds,
    watcher_ready_timeout_seconds, post_exit_grace_seconds,
    sessions_root, session_glob, schema_expected, preflight_file,
    executed{bun, cli_entry, extension, launcher, watcher},
    fixture_identity{path: sha256},
    expect{state_1, state_2, child_exit, child_exit_nonzero}

Exit codes: 2 = validation/binding failure (nothing launched or launch
aborted before spawn); 4 = run completed but expectations unmet; 5 =
supervision error or incomplete watcher evidence; otherwise the child's exit
code.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_hashes_file(path: Path, base: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, target = line.partition(" ")
        target = target.strip()
        candidate = Path(target)
        if not candidate.is_absolute():
            candidate = base / target
        entries[str(candidate)] = digest.lower()
    return entries


def validate_fresh_inputs(spec: dict) -> list[str]:
    """Refuse to reuse a previous run's artifacts by accident."""
    errors: list[str] = []
    if spec.get("coordinator") and Path(spec["coordinator"]["marker"]).exists():
        errors.append(f"refusal marker already exists: {spec['coordinator']['marker']}")
    trace = Path(spec["trace_file"])
    if trace.exists():
        errors.append(f"trace file already exists: {trace}")
    run_dir = Path(spec["run_dir"])
    if (run_dir / "launch.json").exists():
        errors.append(f"run directory already contains a launch record: {run_dir}")
    if (run_dir / "watcher" / "watcher-start.json").exists() or (run_dir / "watcher.stop").exists():
        errors.append(
            f"run directory contains watcher artifacts from a previous attempt: {run_dir}"
        )
    return errors


def rehash_bound_files(spec: dict, run_dir: Path) -> dict:
    hashes_file = Path(spec["hashes_file"])
    base = Path(spec.get("hashes_base", "."))
    expected = parse_hashes_file(hashes_file, base)
    recorded = {}
    mismatches = []
    for target, digest in expected.items():
        path = Path(target)
        actual = sha256_file(path)
        recorded[target] = {"expected": digest, "actual": actual, "match": actual == digest}
        if actual != digest:
            mismatches.append(target)
    payload = {
        "checked_at_unix": time.time(),
        "checked_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "hashes_file": str(hashes_file),
        "hashes_file_sha256": sha256_file(hashes_file),
        "files": recorded,
        "mismatches": mismatches,
        "all_match": not mismatches,
        "boundary": "last-setup-boundary-before-spawn",
    }
    (run_dir / "run-start-rehash.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def read_schema_version(db: Path) -> int | None:
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            row = conn.execute(
                "SELECT value FROM schema_version ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return None


def bind_required_identities(spec: dict, run_dir: Path, env: dict, argv: list[str]) -> dict:
    """Full binding gate derived from the ACTUAL spawn inputs: required roles,
    executed paths, environment/profile consistency, schema, preflight record
    and fixture identities must all agree before spawn."""
    identities_file = Path(spec["identities_file"])
    inventory = json.loads(identities_file.read_text(encoding="utf-8"))
    required_roles = list(inventory.get("required_roles", []))
    present_roles = {entry.get("role"): entry for entry in inventory.get("identities", [])}
    records = []
    missing: list[str] = []
    mismatched: list[str] = []

    for entry in inventory.get("identities", []):
        path = Path(entry["path"])
        expected = entry.get("sha256")
        actual = sha256_file(path) if path.exists() else None
        ok = expected is not None and actual is not None and actual.lower() == str(expected).lower()
        records.append(
            {
                "role": entry.get("role"),
                "path": str(path),
                "expected": expected,
                "actual": actual,
                "ok": ok,
            }
        )
        if actual is None or expected is None:
            missing.append(str(path))
        elif not ok:
            mismatched.append(str(path))

    for role in required_roles:
        entry = present_roles.get(role)
        if entry is None or entry.get("sha256") is None:
            missing.append(f"required-role:{role}")

    # Bindings are derived from the values the launcher will actually execute,
    # never from a parallel declaration a spec could disagree with.
    spawn_inputs = {
        "executable-bun": [spec["bun"]],
        "executable-cli-entry": [spec["cli"]],
        "adapter-index": list(spec.get("extension", [])),
        "launcher": [str(Path(__file__))],
        "watcher": [spec["watcher_script"]],
        "runtime-python": [spec["python"]],
    }
    executed_checks = []
    for role, actual_paths in spawn_inputs.items():
        entry = present_roles.get(role)
        bound = Path(entry["path"]).resolve() if entry and entry.get("path") else None
        actual_resolved = [Path(item).resolve() for item in actual_paths]
        ok = (
            entry is not None
            and entry.get("sha256") is not None
            and len(actual_resolved) >= 1
            and all(item == bound for item in actual_resolved)
        )
        executed_checks.append(
            {
                "role": role,
                "actual": [str(item) for item in actual_paths],
                "bound": str(bound) if bound else None,
                "ok": ok,
            }
        )
        if not ok:
            mismatched.append(f"spawn:{role}")

    env_checks = []
    for name, expected in (
        ("SECOND_BRAIN_HOME", spec["home"]),
        ("SECOND_BRAIN_PYTHON", spec["python"]),
        ("OM_CANARY_BOOT", spec["trace_file"]),
    ):
        actual = env.get(name)
        ok = actual == expected
        env_checks.append({"name": name, "expected": expected, "actual": actual, "ok": ok})
        if not ok:
            mismatched.append(f"env:{name}")

    profile = spec.get("profile")
    profile_flag_ok = "--profile" in argv and argv[argv.index("--profile") + 1] == profile
    extension_flags_ok = all(path in argv for path in spec.get("extension", []))
    argv_checks = [
        {"name": "profile-flag", "expected": profile, "ok": profile_flag_ok},
        {
            "name": "extension-flags",
            "expected": list(spec.get("extension", [])),
            "ok": extension_flags_ok,
        },
    ]
    if not profile_flag_ok:
        mismatched.append("argv:profile")
    if not extension_flags_ok:
        mismatched.append("argv:extension")

    # Tracked configuration contract: binds the intended profile and user
    # configuration file and forbids configuration overlays, so the effective
    # configuration cannot drift silently between candidate and run.
    contract = inventory.get("configuration_contract") or {}
    contract_checks: list[dict] = []

    def contract_check(name: str, ok: bool, detail: object) -> None:
        contract_checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            mismatched.append(f"configuration:{name}")

    expected_profile = contract.get("profile")
    contract_check(
        "profile",
        bool(expected_profile) and profile == expected_profile,
        {"expected": expected_profile, "actual": profile},
    )
    profile_dir = contract.get("profile_dir")
    contract_check("profile-dir", bool(profile_dir) and Path(profile_dir).is_dir(), profile_dir)
    user_config_file = contract.get("user_config_file")
    user_config_ok = bool(user_config_file) and any(
        entry.get("role") == "configuration-user"
        and Path(entry["path"]).resolve() == Path(str(user_config_file)).resolve()
        for entry in inventory.get("identities", [])
    )
    contract_check("user-config-bound", user_config_ok, user_config_file)
    forbidden_env_hits = [name for name in contract.get("forbidden_env", []) if env.get(name)]
    contract_check("forbidden-env", not forbidden_env_hits, forbidden_env_hits)
    forbidden_flag_hits = [
        flag for flag in contract.get("forbidden_argv_flags", []) if flag in argv
    ]
    contract_check("forbidden-argv", not forbidden_flag_hits, forbidden_flag_hits)
    overlay_hits = [
        relative
        for relative in contract.get("forbidden_project_overlays", [])
        if (Path(spec["fixture"]) / relative).exists()
    ]
    contract_check("project-overlays", not overlay_hits, overlay_hits)

    schema_actual = read_schema_version(Path(spec["home"]) / "db" / "brain.sqlite")
    schema_ok = spec.get("schema_expected") is not None and schema_actual == spec.get(
        "schema_expected"
    )
    if not schema_ok:
        mismatched.append(f"schema:{schema_actual}")

    preflight_ok = False
    preflight_summary = None
    preflight_file = spec.get("preflight_file")
    if preflight_file and Path(preflight_file).exists():
        data = json.loads(Path(preflight_file).read_text(encoding="utf-8"))
        preflight_summary = {
            "home": data.get("home"),
            "fixture": data.get("fixture"),
            "project_id": data.get("project_id"),
            "schema_version": data.get("schema_version"),
            "home_counts": data.get("home_counts"),
            "red": (data.get("fixture_starts_red") or {}).get("red"),
        }
        preflight_ok = (
            data.get("home") == spec.get("home")
            and data.get("fixture") == spec.get("fixture")
            and data.get("schema_version") == spec.get("schema_expected")
            and (data.get("home_counts") or {}).get("worker_tasks") == 0
            and (data.get("home_counts") or {}).get("worker_lifecycle_receipts") == 0
            and (data.get("fixture_starts_red") or {}).get("red") is True
        )
    if not preflight_ok:
        mismatched.append("preflight")

    fixture_identity = spec.get("fixture_identity") or {}
    fixture_records = []
    if not fixture_identity:
        mismatched.append("fixture_identity:missing")
    for path_text, expected in fixture_identity.items():
        actual = sha256_file(Path(path_text))
        ok = expected is not None and actual is not None and actual.lower() == str(expected).lower()
        fixture_records.append(
            {"path": str(path_text), "expected": expected, "actual": actual, "ok": ok}
        )
        if not ok:
            if actual is None:
                missing.append(str(path_text))
            else:
                mismatched.append(str(path_text))

    all_bound = not missing and not mismatched and bool(required_roles) and bool(executed_checks)
    payload = {
        "checked_at_unix": time.time(),
        "checked_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "identities_file": str(identities_file),
        "identities_file_sha256": sha256_file(identities_file),
        "required_roles": required_roles,
        "role_records": records,
        "spawn_input_checks": executed_checks,
        "env_checks": env_checks,
        "argv_checks": argv_checks,
        "configuration_contract_checks": contract_checks,
        "configuration": {
            "profile": profile,
            "argv": argv,
            "effective_env": {
                name: env.get(name)
                for name in ("SECOND_BRAIN_HOME", "SECOND_BRAIN_PYTHON", "OM_CANARY_BOOT")
            },
        },
        "schema": {
            "expected": spec.get("schema_expected"),
            "actual": schema_actual,
            "ok": schema_ok,
        },
        "preflight": {"file": preflight_file, "ok": preflight_ok, "summary": preflight_summary},
        "fixture_records": fixture_records,
        "missing_or_null": missing,
        "mismatched": mismatched,
        "all_bound": all_bound,
        "boundary": "last-setup-boundary-before-spawn",
    }
    (run_dir / "identity-binding.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (run_dir / "effective-configuration.json").write_text(
        json.dumps(
            {
                "profile": profile,
                "argv": argv,
                "extensions": list(spec.get("extension", [])),
                "env": payload["configuration"]["effective_env"],
                "spawn_inputs": spawn_inputs,
                "configuration_contract_checks": contract_checks,
                "schema_expected": spec.get("schema_expected"),
                "fixture": spec.get("fixture"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return payload


def executable_identity(spec: dict) -> dict:
    def version(cmd: list[str]) -> str | None:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            text = (proc.stdout or proc.stderr).strip()
            return text.splitlines()[0] if text else None
        except Exception:
            return None

    bun = Path(spec["bun"])
    cli = Path(spec["cli"])
    extensions = [Path(item) for item in spec.get("extension", [])]
    watcher = Path(spec["watcher_script"])
    launcher = Path(__file__)
    return {
        "bun": {
            "path": str(bun),
            "sha256": sha256_file(bun),
            "version": version([str(bun), "--version"]),
        },
        "cli_entry": {"path": str(cli), "sha256": sha256_file(cli)},
        "extensions": [{"path": str(item), "sha256": sha256_file(item)} for item in extensions],
        "watcher": {"path": str(watcher), "sha256": sha256_file(watcher)},
        "launcher": {"path": str(launcher), "sha256": sha256_file(launcher)},
        "coordinator": {
            "path": str(launcher),
            "sha256": sha256_file(launcher),
            "mode": "in-launcher-thread",
        },
        "python": spec.get("python"),
    }


class Coordinator(threading.Thread):
    """External coordinator: emits the identity-bound signal after the marker."""

    def __init__(self, trace_file: Path, marker: Path, log_dir: Path, deadline: float) -> None:
        super().__init__(daemon=True)
        self.trace_file = trace_file
        self.marker = marker
        self.log_dir = log_dir
        self.deadline = deadline
        self.record: dict = {"state": "waiting"}
        self._stop = threading.Event()

    def log(self, message: str) -> None:
        with (self.log_dir / "coordinator.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")

    def run(self) -> None:
        self.log("coordinator-start")
        binding = None
        while time.time() < self.deadline and not self._stop.is_set():
            try:
                text = self.trace_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            line = next(
                (
                    candidate
                    for candidate in text.splitlines()
                    if "isolation:hold-begin:" in candidate
                ),
                None,
            )
            if line:
                payload = line.split("isolation:hold-begin:", 1)[1].strip()
                try:
                    binding = json.loads(payload)
                    break
                except ValueError:
                    binding = None
            time.sleep(0.3)
        if binding is None:
            self.record = {"state": "hold-begin-not-observed"}
            self.log("hold-begin-not-observed")
            return
        self.record = {"state": "hold-observed", "binding": binding}
        self.log(
            "hold-begin-observed attempt="
            f"{binding.get('attemptId')} generation={binding.get('generation')}"
        )
        while time.time() < self.deadline and not self._stop.is_set():
            if self.marker.exists():
                break
            time.sleep(0.3)
        if not self.marker.exists():
            self.record["state"] = "marker-not-observed"
            self.log("marker-not-observed")
            return
        hold_file = Path(binding["holdFile"])
        if hold_file.exists():
            self.record["state"] = "signal-already-exists"
            self.log(f"signal-already-exists {hold_file}")
        else:
            hold_file.parent.mkdir(parents=True, exist_ok=True)
            hold_file.write_bytes(b"")
            self.record["state"] = "signal-created"
            self.log(f"signal-created {hold_file}")
        self.record["signalCreatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        (self.log_dir / "coordinator.json").write_text(
            json.dumps(self.record, indent=2), encoding="utf-8"
        )

    def stop(self) -> None:
        self._stop.set()


def collect_sessions(spec: dict, started_at: float, run_dir: Path) -> list[dict]:
    root = spec.get("sessions_root")
    pattern = spec.get("session_glob", "**/*.jsonl")
    if not root:
        return []
    root_path = Path(root)
    if not root_path.exists():
        return []
    copied = []
    sessions_out = run_dir / "sessions"
    sessions_out.mkdir(parents=True, exist_ok=True)
    for path in sorted(root_path.glob(pattern)):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < started_at - 5:
            continue
        target = sessions_out / path.name
        if path.is_file():
            target.write_bytes(path.read_bytes())
            copied.append(
                {
                    "source": str(path),
                    "evidence_copy": str(target),
                    "bytes": path.stat().st_size,
                    "mtime": mtime,
                }
            )
    return copied


def wait_for_watcher_ready(run_dir: Path, timeout: float) -> bool:
    marker = run_dir / "watcher" / "watcher-start.json"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker.exists():
            return True
        time.sleep(0.1)
    return False


def evaluate_expectations(spec: dict, child_exit: int, watcher_record: dict | None) -> dict:
    expect = spec.get("expect", {})
    checks = []

    def add(name: str, expected: object, actual: object) -> None:
        checks.append(
            {"name": name, "expected": expected, "actual": actual, "met": actual == expected}
        )

    if "child_exit" in expect:
        add("child_exit", expect["child_exit"], child_exit)
    if expect.get("child_exit_nonzero"):
        checks.append(
            {
                "name": "child_exit_nonzero",
                "expected": True,
                "actual": child_exit != 0,
                "met": child_exit != 0,
            }
        )
    if "state_1" in expect:
        actual = bool(watcher_record and watcher_record.get("state_1_captured"))
        add("state_1", bool(expect["state_1"]), actual)
    if "state_2" in expect:
        actual = bool(watcher_record and watcher_record.get("state_2_captured"))
        add("state_2", bool(expect["state_2"]), actual)
    return {"checks": checks, "met": all(check["met"] for check in checks) and bool(checks)}


def stop_watcher(process: subprocess.Popen | None, run_dir: Path, grace: float) -> int | str | None:
    if process is None:
        return None
    if process.poll() is None:
        time.sleep(grace)
        (run_dir / "watcher.stop").write_text("stop", encoding="utf-8")
    try:
        return process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                return process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                return "unreaped"


def launcher_outcome(evidence_complete: bool, expectations_met: bool, exit_code: int) -> int:
    """Success is gated on complete evidence, satisfied expectations and a real
    zero exit; an unhealthy watcher makes any run incomplete."""
    if not evidence_complete:
        return 5
    if not expectations_met:
        return 4
    return 0 if exit_code == 0 else (exit_code if isinstance(exit_code, int) else 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
    run_dir = Path(spec["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)

    errors = validate_fresh_inputs(spec)
    if errors:
        print(json.dumps({"error": "stale run inputs", "details": errors}))
        return 2

    identity = executable_identity(spec)
    env = dict(os.environ)
    env.update({k: str(v) for k, v in spec.get("extra_env", {}).items()})
    if spec.get("hold_prefix"):
        env["OM_CANARY_HOLD_RELEASE_UNTIL"] = spec["hold_prefix"]
    env["OM_CANARY_BOOT"] = spec["trace_file"]

    state: dict = {
        "coordinator": None,
        "watcher": None,
        "child": None,
        "watcher_log": None,
        "watcher_err": None,
        "watcher_started": None,
        "exit_code": None,
        "timed_out": False,
        "launch_started": time.time(),
        "spawn_observed": None,
        "exit_at": None,
        "rehash": None,
        "binding": {},
        "argv": None,
        "supervision_error": None,
        "record_written": False,
    }

    def teardown() -> None:
        child = state["child"]
        if child is not None and child.poll() is None:
            child.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=30)
        coordinator = state["coordinator"]
        if coordinator is not None:
            coordinator.stop()
            coordinator.join(timeout=10)
        if state["watcher"] is not None:
            state["watcher_exit"] = stop_watcher(
                state["watcher"], run_dir, float(spec.get("post_exit_grace_seconds", 3))
            )
        if state["watcher_log"] is not None:
            state["watcher_log"].close()
        if state["watcher_err"] is not None:
            state["watcher_err"].close()
        if not state["record_written"] and state["supervision_error"] is not None:
            failure = {
                "name": spec.get("name"),
                "error": state["supervision_error"],
                "launch_started_at_unix": state["launch_started"],
                "child_spawned": state["child"] is not None,
                "child_exit_code": state["exit_code"],
                "watcher_exit_code": state.get("watcher_exit"),
                "supervision_error": True,
            }
            (run_dir / "launch.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
            state["record_written"] = True

    try:
        watcher_cmd = [
            spec["python"],
            spec["watcher_script"],
            "--db",
            str(Path(spec["home"]) / "db" / "brain.sqlite"),
            "--outdir",
            str(run_dir / "watcher"),
            "--stop-file",
            str(run_dir / "watcher.stop"),
            "--label",
            spec["name"],
            "--timeout",
            str(spec.get("watcher_timeout_seconds", 1800)),
        ]
        state["watcher_log"] = (run_dir / "watcher.stdout.txt").open("w", encoding="utf-8")
        state["watcher_err"] = (run_dir / "watcher.stderr.txt").open("w", encoding="utf-8")
        state["watcher"] = subprocess.Popen(
            watcher_cmd, stdout=state["watcher_log"], stderr=state["watcher_err"]
        )
        state["watcher_started"] = time.time()
        if not wait_for_watcher_ready(
            run_dir, float(spec.get("watcher_ready_timeout_seconds", 30))
        ):
            raise RuntimeError("watcher did not acknowledge baseline readiness before launch")

        if spec.get("coordinator"):
            state["coordinator"] = Coordinator(
                Path(spec["trace_file"]),
                Path(spec["coordinator"]["marker"]),
                run_dir,
                deadline=state["launch_started"] + float(spec.get("timeout_seconds", 900)),
            )
            state["coordinator"].start()

        argv = [spec["bun"], spec["cli"], "--profile", spec["profile"], "-p", "--auto-approve"]
        for extension in spec.get("extension", []):
            argv += ["-e", extension]
        argv.append(f"@{spec['prompt_file']}")
        state["argv"] = argv

        # Last setup boundary: rehash and full identity binding immediately
        # before spawn. Any mismatch aborts with no child.
        state["rehash"] = rehash_bound_files(spec, run_dir)
        state["binding"] = bind_required_identities(spec, run_dir, env, argv)
        if not state["rehash"]["all_match"] or not state["binding"]["all_bound"]:
            failure = {
                "name": spec.get("name"),
                "launched": False,
                "binding_failed": True,
                "launch_started_at_unix": state["launch_started"],
                "rehash_all_match": state["rehash"]["all_match"],
                "binding_all_bound": state["binding"]["all_bound"],
                "binding_missing_or_null": state["binding"]["missing_or_null"],
                "binding_mismatched": state["binding"]["mismatched"],
            }
            (run_dir / "launch.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
            state["record_written"] = True
            print(
                json.dumps(
                    {
                        "error": "run-start binding failed immediately before spawn",
                        "rehash_mismatches": state["rehash"]["mismatches"],
                        "binding_missing_or_null": state["binding"]["missing_or_null"],
                        "binding_mismatched": state["binding"]["mismatched"],
                    }
                )
            )
            return 2

        stdout_path = run_dir / f"{spec['name']}.stdout.txt"
        stderr_path = run_dir / f"{spec['name']}.stderr.txt"
        with (
            stdout_path.open("w", encoding="utf-8") as stdout,
            stderr_path.open("w", encoding="utf-8") as stderr,
        ):
            child = subprocess.Popen(
                argv, cwd=spec["fixture"], env=env, stdout=stdout, stderr=stderr
            )
            state["child"] = child
            state["spawn_observed"] = time.time()
            try:
                state["exit_code"] = child.wait(timeout=float(spec.get("timeout_seconds", 900)))
            except subprocess.TimeoutExpired:
                state["timed_out"] = True
                child.kill()
                state["exit_code"] = child.wait(timeout=60)
        state["exit_at"] = time.time()
    except BaseException as error:  # includes operator interruption; teardown still runs
        state["supervision_error"] = f"{type(error).__name__}: {error}"
    finally:
        teardown()

    if state["supervision_error"] is not None:
        print(json.dumps({"error": "supervision failure", "detail": state["supervision_error"]}))
        return 5

    watcher_record_path = run_dir / "watcher" / "watcher.json"
    watcher_record = (
        json.loads(watcher_record_path.read_text(encoding="utf-8"))
        if watcher_record_path.exists()
        else None
    )
    watcher_exit = state.get("watcher_exit")
    watcher_healthy = watcher_record is not None and watcher_exit == 0
    sessions = collect_sessions(spec, state["launch_started"], run_dir)
    exit_code = state["exit_code"] if state["exit_code"] is not None else -1
    expectations = evaluate_expectations(spec, exit_code, watcher_record)

    record = {
        "name": spec["name"],
        "launch_started_at_unix": state["launch_started"],
        "launch_started_at_iso": time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(state["launch_started"])
        ),
        "spawn_observed_at_unix": state["spawn_observed"],
        "exit_at_unix": state["exit_at"],
        "exit_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state["exit_at"]))
        if state["exit_at"]
        else None,
        "duration_seconds": (
            round(state["exit_at"] - state["launch_started"], 3) if state["exit_at"] else None
        ),
        "argv": state["argv"],
        "cwd": spec["fixture"],
        "profile": spec["profile"],
        "child_pid": state["child"].pid if state["child"] else None,
        "child_exit_code": state["exit_code"],
        "timed_out": state["timed_out"],
        "supervised_process_ownership": "launcher-spawned-and-reaped",
        "environment": {
            "SECOND_BRAIN_HOME": env.get("SECOND_BRAIN_HOME"),
            "SECOND_BRAIN_PYTHON": env.get("SECOND_BRAIN_PYTHON"),
            "OM_CANARY_BOOT": env.get("OM_CANARY_BOOT"),
            "OM_CANARY_FORCE_ISOLATED": env.get("OM_CANARY_FORCE_ISOLATED"),
            "OM_CANARY_ISOLATION": env.get("OM_CANARY_ISOLATION"),
            "OM_CANARY_HOLD_RELEASE_UNTIL_set": bool(env.get("OM_CANARY_HOLD_RELEASE_UNTIL")),
        },
        "identity": identity,
        "run_start_binding": {
            "rehash_all_match": state["rehash"]["all_match"] if state["rehash"] else None,
            "rehash_file": str(run_dir / "run-start-rehash.json"),
            "identity_all_bound": state["binding"].get("all_bound"),
            "identity_file": str(run_dir / "identity-binding.json"),
            "validated_before_spawn": True,
        },
        "watcher": {
            "pid": state["watcher"].pid if state["watcher"] else None,
            "started_at_unix": state["watcher_started"],
            "exit_code": watcher_exit,
            "healthy": watcher_healthy,
            "record": watcher_record,
        },
        "coordinator": state["coordinator"].record if state["coordinator"] else None,
        "sessions_copied": sessions,
        "expectations": expectations,
        "evidence_complete": watcher_healthy,
        "qualification_complete": bool(watcher_healthy and expectations["met"] and exit_code == 0),
    }
    (run_dir / "launch.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    state["record_written"] = True
    print(
        json.dumps(
            {
                "name": spec["name"],
                "child_exit_code": state["exit_code"],
                "timed_out": state["timed_out"],
                "duration_seconds": record["duration_seconds"],
                "watcher_exit_code": watcher_exit,
                "watcher_healthy": watcher_healthy,
                "watcher_state_1": watcher_record.get("state_1_captured")
                if watcher_record
                else None,
                "watcher_state_2": watcher_record.get("state_2_captured")
                if watcher_record
                else None,
                "coordinator_state": state["coordinator"].record.get("state")
                if state["coordinator"]
                else None,
                "expectations_met": expectations["met"],
                "qualification_complete": record["qualification_complete"],
                "launch_record": str(run_dir / "launch.json"),
            },
            indent=2,
        )
    )
    if not watcher_healthy:
        return launcher_outcome(
            evidence_complete=False, expectations_met=expectations["met"], exit_code=exit_code
        )
    if not expectations["met"]:
        return launcher_outcome(evidence_complete=True, expectations_met=False, exit_code=exit_code)
    return launcher_outcome(evidence_complete=True, expectations_met=True, exit_code=exit_code)


if __name__ == "__main__":
    sys.exit(main())
