"""External launcher/supervisor for OMP qualification runs.

The launcher OWNS the OMP child process: it records executable identities,
starts the read-only DB watcher first and waits for its baseline
acknowledgment, re-validates the run-start binding at the last boundary before
spawn, spawns the real OMP process (bun + canary src entry) with the run
environment, waits for the actual process exit, records exit code and
timestamps, stops and reaps the watcher, and evaluates per-run expectations.
It never repairs ownership, replays receipts, or supplies any shutdown
guarantee the host is being tested for.

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
    sessions_root, session_glob,
    expect{state_1, state_2, child_exit}

Exit codes: 2 = validation/binding failure (nothing launched or launch
aborted before spawn); 4 = run completed but expectations unmet; 5 =
supervision error; otherwise the child's exit code.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
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
    """Refuse to reuse a previous run's marker or trace by accident."""
    errors: list[str] = []
    if spec.get("coordinator") and Path(spec["coordinator"]["marker"]).exists():
        errors.append(f"refusal marker already exists: {spec['coordinator']['marker']}")
    trace = Path(spec["trace_file"])
    if trace.exists():
        errors.append(f"trace file already exists: {trace}")
    run_dir = Path(spec["run_dir"])
    if (run_dir / "launch.json").exists():
        errors.append(f"run directory already contains a launch record: {run_dir}")
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


def bind_required_identities(spec: dict, run_dir: Path) -> dict:
    """Compare the required identity inventory (executable/adapter/observer/
    launcher/watcher/configuration/schema/fixture) against the committed file."""
    identities_file = Path(spec["identities_file"])
    inventory = json.loads(identities_file.read_text(encoding="utf-8"))
    records = []
    missing = []
    mismatched = []
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
    payload = {
        "checked_at_unix": time.time(),
        "checked_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "identities_file": str(identities_file),
        "identities_file_sha256": sha256_file(identities_file),
        "records": records,
        "missing_or_null": missing,
        "mismatched": mismatched,
        "all_bound": not missing and not mismatched,
        "boundary": "last-setup-boundary-before-spawn",
    }
    fixture_identity = spec.get("fixture_identity") or {}
    fixture_records = []
    for path_text, expected in fixture_identity.items():
        actual = sha256_file(Path(path_text))
        ok = expected is not None and actual is not None and actual.lower() == str(expected).lower()
        fixture_records.append(
            {"path": str(path_text), "expected": expected, "actual": actual, "ok": ok}
        )
        if not ok:
            payload["all_bound"] = False
            if actual is None:
                payload["missing_or_null"].append(str(path_text))
            else:
                payload["mismatched"].append(str(path_text))
    payload["fixture_records"] = fixture_records
    (run_dir / "identity-binding.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
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

    def add(name: str, expected, actual) -> None:
        checks.append(
            {"name": name, "expected": expected, "actual": actual, "met": actual == expected}
        )

    if "child_exit" in expect:
        add("child_exit", expect["child_exit"], child_exit)
    if "state_1" in expect:
        actual = bool(watcher_record and watcher_record.get("state_1_captured"))
        add("state_1", bool(expect["state_1"]), actual)
    if "state_2" in expect:
        actual = bool(watcher_record and watcher_record.get("state_2_captured"))
        add("state_2", bool(expect["state_2"]), actual)
    return {"checks": checks, "met": all(check["met"] for check in checks) and bool(checks)}


def stop_watcher(process: subprocess.Popen, run_dir: Path, grace: float) -> int | str | None:
    stop_file = run_dir / "watcher.stop"
    if process.poll() is None:
        time.sleep(grace)
        stop_file.write_text("stop", encoding="utf-8")
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
    hold_prefix = spec.get("hold_prefix")
    if hold_prefix:
        env["OM_CANARY_HOLD_RELEASE_UNTIL"] = hold_prefix
    env["OM_CANARY_BOOT"] = spec["trace_file"]

    coordinator = None
    watcher: subprocess.Popen | None = None
    child: subprocess.Popen | None = None
    watcher_log = watcher_err = None
    exit_code: int | None = None
    timed_out = False
    launch_started = time.time()
    binding: dict = {}

    try:
        # Watcher first: the read-only observer must be running and have its
        # baseline before the launch, and it must acknowledge readiness.
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
        watcher_log = (run_dir / "watcher.stdout.txt").open("w", encoding="utf-8")
        watcher_err = (run_dir / "watcher.stderr.txt").open("w", encoding="utf-8")
        watcher = subprocess.Popen(watcher_cmd, stdout=watcher_log, stderr=watcher_err)
        if not wait_for_watcher_ready(
            run_dir, float(spec.get("watcher_ready_timeout_seconds", 30))
        ):
            raise RuntimeError("watcher did not acknowledge baseline readiness before launch")

        if spec.get("coordinator"):
            coordinator = Coordinator(
                Path(spec["trace_file"]),
                Path(spec["coordinator"]["marker"]),
                run_dir,
                deadline=launch_started + float(spec.get("timeout_seconds", 900)),
            )
            coordinator.start()

        argv = [
            spec["bun"],
            spec["cli"],
            "--profile",
            spec["profile"],
            "-p",
            "--auto-approve",
        ]
        for extension in spec.get("extension", []):
            argv += ["-e", extension]
        argv.append(f"@{spec['prompt_file']}")

        # Last setup boundary: the run-start rehash and the full identity binding
        # are validated here, immediately before spawn. Any mismatch aborts the
        # launch with no child.
        rehash = rehash_bound_files(spec, run_dir)
        binding = bind_required_identities(spec, run_dir)
        binding["rehash_all_match"] = rehash["all_match"]
        if not rehash["all_match"] or not binding["all_bound"]:
            print(
                json.dumps(
                    {
                        "error": "run-start binding failed immediately before spawn",
                        "rehash_mismatches": rehash["mismatches"],
                        "identity_missing_or_null": binding["missing_or_null"],
                        "identity_mismatched": binding["mismatched"],
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
            spawn_observed = time.time()
            try:
                exit_code = child.wait(timeout=float(spec.get("timeout_seconds", 900)))
            except subprocess.TimeoutExpired:
                timed_out = True
                child.kill()
                exit_code = child.wait(timeout=60)
        exit_at = time.time()
    except Exception as error:  # supervision must close out children and evidence
        if child is not None and child.poll() is None:
            child.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=30)
        if coordinator is not None:
            coordinator.stop()
            coordinator.join(timeout=10)
        watcher_exit = stop_watcher(watcher, run_dir, 0) if watcher is not None else None
        if watcher_log:
            watcher_log.close()
        if watcher_err:
            watcher_err.close()
        failure = {
            "name": spec.get("name"),
            "error": f"{type(error).__name__}: {error}",
            "launch_started_at_unix": launch_started,
            "child_spawned": child is not None,
            "timed_out": timed_out,
            "watcher_exit_code": watcher_exit,
            "binding": binding,
            "supervision_error": True,
        }
        (run_dir / "launch.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(json.dumps({"error": "supervision failure", "detail": str(error)}))
        return 5

    if coordinator is not None:
        coordinator.stop()
        coordinator.join(timeout=10)

    watcher_exit = stop_watcher(watcher, run_dir, float(spec.get("post_exit_grace_seconds", 3)))
    assert watcher_log is not None and watcher_err is not None
    watcher_log.close()
    watcher_err.close()

    watcher_record_path = run_dir / "watcher" / "watcher.json"
    watcher_record = (
        json.loads(watcher_record_path.read_text(encoding="utf-8"))
        if watcher_record_path.exists()
        else None
    )
    sessions = collect_sessions(spec, launch_started, run_dir)
    expectations = evaluate_expectations(
        spec, exit_code if exit_code is not None else -1, watcher_record
    )

    record = {
        "name": spec["name"],
        "launch_started_at_unix": launch_started,
        "launch_started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(launch_started)),
        "spawn_observed_at_unix": spawn_observed,
        "exit_at_unix": exit_at,
        "exit_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(exit_at)),
        "duration_seconds": round(exit_at - launch_started, 3),
        "argv": argv,
        "cwd": spec["fixture"],
        "profile": spec["profile"],
        "child_pid": child.pid if child else None,
        "child_exit_code": exit_code,
        "timed_out": timed_out,
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
            "rehash_all_match": rehash["all_match"],
            "rehash_file": str(run_dir / "run-start-rehash.json"),
            "identity_all_bound": binding["all_bound"],
            "identity_file": str(run_dir / "identity-binding.json"),
            "validated_before_spawn": True,
        },
        "watcher": {
            "pid": watcher.pid if watcher else None,
            "started_at_unix": launch_started,
            "exit_code": watcher_exit,
            "record": watcher_record,
        },
        "coordinator": coordinator.record if coordinator else None,
        "sessions_copied": sessions,
        "expectations": expectations,
        "qualification_complete": bool(
            expectations["met"] and watcher_record is not None and exit_code == 0
        ),
    }
    (run_dir / "launch.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "name": spec["name"],
                "child_exit_code": exit_code,
                "timed_out": timed_out,
                "duration_seconds": record["duration_seconds"],
                "watcher_state_1": watcher_record.get("state_1_captured")
                if watcher_record
                else None,
                "watcher_state_2": watcher_record.get("state_2_captured")
                if watcher_record
                else None,
                "coordinator_state": coordinator.record.get("state") if coordinator else None,
                "expectations_met": expectations["met"],
                "launch_record": str(run_dir / "launch.json"),
            },
            indent=2,
        )
    )
    if not expectations["met"]:
        return 4
    return 0 if exit_code == 0 else (exit_code if isinstance(exit_code, int) else 1)


if __name__ == "__main__":
    sys.exit(main())
