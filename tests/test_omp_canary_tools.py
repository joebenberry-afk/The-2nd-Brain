"""Focused tests for the OMP qualification campaign tools (scripts/omp-canary).

Covered review findings, deterministically and without a live OMP process:

- snapshot classification is taken from the retained snapshot itself, so
  terminal bytes are never labelled state-1 and the rejected candidate is
  removed (L1);
- missing-state reporting is explicit even when no attempt window was observed
  (L2);
- the full binding gate enforces required roles, executed-spec paths, schema,
  preflight and fixture identities (B2);
- a binding failure returns before spawn while still tearing the watcher down
  and writing a launch record (L3 early-return path);
- launcher success is gated on watcher health and expectations (L4).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

TOOLS = Path(__file__).resolve().parents[1] / "scripts" / "omp-canary"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE worker_tasks (task_id TEXT, state TEXT, writer_ownership TEXT,
            executor_settled INTEGER, cleanup_complete INTEGER);
        CREATE TABLE worker_lifecycle_receipts (attempt_id TEXT, sequence INTEGER,
            receipt_sha256 TEXT, payload_json TEXT, recorded_at TEXT);
        """
    )
    conn.commit()
    return conn


def _receipt(
    conn: sqlite3.Connection,
    attempt: str,
    sequence: int,
    cleanup_complete: bool,
    recorded_at: str = "2026-01-01T00:00:00",
) -> None:
    conn.execute(
        "INSERT INTO worker_lifecycle_receipts VALUES (?, ?, ?, ?, ?)",
        (
            attempt,
            sequence,
            f"sha-{attempt}-{sequence}",
            json.dumps({"cleanup_complete": cleanup_complete}),
            recorded_at,
        ),
    )
    conn.commit()


def test_state1_not_fabricated_when_first_observation_is_terminal(tmp_path: Path) -> None:
    mod = _load("db_watch")
    db = tmp_path / "brain.sqlite"
    conn = _make_db(db)
    _receipt(conn, "old:1", 1, True)  # baseline attempt, pre-existing
    conn.close()

    state = mod.WatchState(db, tmp_path / "out", "test")
    state.baseline()

    # A new attempt whose FIRST observation is already terminal: the intermediate
    # state was missed and must be reported missing, never fabricated.
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO worker_tasks VALUES ('new', 'COMPLETED', 'released', 1, 1)")
    _receipt(conn, "new:1", 1, False)
    _receipt(conn, "new:1", 2, True)
    conn.close()

    state.observe_state()

    assert state.state1 is None
    assert state.state1_missing is True
    assert state.state2 is not None
    assert not (tmp_path / "out" / "state-1.json").exists()
    assert not (tmp_path / "out" / "state-1.sqlite").exists()
    assert (tmp_path / "out" / "state-2.json").exists()
    record = state.finish("terminal-state-captured")
    assert record["state_1_missing"] is True
    assert record["state_2_captured"] is True
    assert record["watched_attempt"] == "new:1"


def test_state1_captured_before_terminal_then_state2(tmp_path: Path) -> None:
    mod = _load("db_watch")
    db = tmp_path / "brain.sqlite"
    conn = _make_db(db)
    _receipt(conn, "old:1", 1, True)
    conn.close()

    state = mod.WatchState(db, tmp_path / "out", "test")
    state.baseline()

    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO worker_tasks VALUES ('new', 'RUNNING', 'pending', 0, 0)")
    _receipt(conn, "new:1", 1, False)

    state.observe_state()
    assert state.state1 is not None
    assert state.state1["phase"] == "receipt-after-first-sequence-before-terminal"
    assert state.state1["tasks"][-1]["state"] == "RUNNING"

    conn.execute(
        "UPDATE worker_tasks SET state='COMPLETED', writer_ownership='released', "
        "executor_settled=1, cleanup_complete=1 WHERE task_id='new'"
    )
    _receipt(conn, "new:1", 2, True)
    conn.close()
    state.observe_state()
    assert state.state2 is not None
    assert state.state2["terminal_sequence"] == 2
    record = state.finish("terminal-state-captured")
    assert record["state_1_missing"] is False
    assert record["state_2_missing"] is False


def test_missing_flags_are_explicit_without_any_attempt(tmp_path: Path) -> None:
    mod = _load("db_watch")
    db = tmp_path / "brain.sqlite"
    conn = _make_db(db)
    conn.close()
    state = mod.WatchState(db, tmp_path / "out", "test")
    state.baseline()
    record = state.finish("stop-file")
    assert record["attempt_observed"] is False
    assert record["state_1_missing"] is True
    assert record["state_2_missing"] is True


def test_fresh_inputs_reject_stale_artifacts(tmp_path: Path) -> None:
    mod = _load("launch_run")
    marker = tmp_path / "marker"
    trace = tmp_path / "boot.txt"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec = {
        "coordinator": {"marker": str(marker)},
        "trace_file": str(trace),
        "run_dir": str(run_dir),
    }
    assert mod.validate_fresh_inputs(spec) == []

    marker.write_text("stale", encoding="utf-8")
    trace.write_text("stale", encoding="utf-8")
    assert len(mod.validate_fresh_inputs(spec)) == 2

    marker.unlink()
    trace.unlink()
    (run_dir / "watcher").mkdir()
    (run_dir / "watcher" / "watcher-start.json").write_text("{}", encoding="utf-8")
    assert len(mod.validate_fresh_inputs(spec)) == 1
    (run_dir / "watcher" / "watcher-start.json").unlink()
    (run_dir / "watcher.stop").write_text("stop", encoding="utf-8")
    assert len(mod.validate_fresh_inputs(spec)) == 1

    (run_dir / "watcher.stop").unlink()
    (run_dir / "launch.json").write_text("{}", encoding="utf-8")
    assert len(mod.validate_fresh_inputs(spec)) == 1


def _complete_binding_spec(tmp_path: Path) -> dict:
    bun = tmp_path / "bun.exe"
    bun.write_bytes(b"bun")
    cli = tmp_path / "cli.ts"
    cli.write_text("export {};", encoding="utf-8")
    extension = tmp_path / "index.ts"
    extension.write_text("export {};", encoding="utf-8")
    launcher = TOOLS / "launch_run.py"  # the launcher binds its own executed file
    watcher = tmp_path / "db_watch.py"
    watcher.write_text("# watcher", encoding="utf-8")
    package = tmp_path / "package.json"
    package.write_text("{}", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")
    user_config = tmp_path / "user-config.yml"
    user_config.write_text("# user settings\n", encoding="utf-8")
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(exist_ok=True)

    roles = {
        "executable-bun": bun,
        "executable-cli-entry": cli,
        "configuration-canary-package": package,
        "configuration-user": user_config,
        "adapter-index": extension,
        "launcher": launcher,
        "watcher": watcher,
        "runtime-python": python,
    }
    identities = tmp_path / "ids.json"
    identities.write_text(
        json.dumps(
            {
                "required_roles": list(roles),
                "configuration_contract": {
                    "profile": "canary-settlement",
                    "profile_dir": str(profile_dir),
                    "user_config_file": str(user_config),
                    "forbidden_env": ["PI_CONFIG_FILES"],
                    "forbidden_argv_flags": ["--config"],
                    "forbidden_project_overlays": [".omp/config.yml", ".claude/settings.yml"],
                },
                "identities": [
                    {"role": role, "path": str(path), "sha256": _sha256(path)}
                    for role, path in roles.items()
                ],
            }
        ),
        encoding="utf-8",
    )

    home = tmp_path / "home"
    (home / "db").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(home / "db" / "brain.sqlite")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (value INTEGER)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (24)")
    conn.commit()
    conn.close()

    fixture = tmp_path / "fixture"
    fixture.mkdir(exist_ok=True)
    calc = fixture / "calc.py"
    calc.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    preflight = tmp_path / "preflight.json"
    preflight.write_text(
        json.dumps(
            {
                "home": str(home),
                "fixture": str(fixture),
                "project_id": "test-project",
                "schema_version": 24,
                "home_counts": {"worker_tasks": 0, "worker_lifecycle_receipts": 0},
                "fixture_starts_red": {"red": True, "red_reason": "assertion-failure"},
            }
        ),
        encoding="utf-8",
    )

    return {
        "identities_file": str(identities),
        "home": str(home),
        "fixture": str(fixture),
        "schema_expected": 24,
        "preflight_file": str(preflight),
        "profile": "canary-settlement",
        "bun": str(bun),
        "cli": str(cli),
        "extension": [str(extension)],
        "watcher_script": str(watcher),
        "python": str(python),
        "trace_file": str(tmp_path / "boot.txt"),
        "fixture_identity": {str(calc): _sha256(calc)},
        "argv": ["bun", "cli", "--profile", "canary-settlement", "-e", str(extension)],
    }


def _bind(tmp_path: Path, spec: dict) -> dict:
    mod = _load("launch_run")
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    env = {
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
    }
    return mod.bind_required_identities(spec, run_dir, env, spec["argv"])


def test_required_identity_binding_accepts_complete_spec(tmp_path: Path) -> None:
    spec = _complete_binding_spec(tmp_path)
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is True
    assert result["mismatched"] == []
    assert result["missing_or_null"] == []
    assert result["schema"]["ok"] is True
    assert result["preflight"]["ok"] is True


def test_required_identity_binding_rejects_each_gap(tmp_path: Path) -> None:
    spec = _complete_binding_spec(tmp_path)

    # Null role hash
    identities = json.loads(Path(spec["identities_file"]).read_text(encoding="utf-8"))
    identities["identities"][0]["sha256"] = None
    Path(spec["identities_file"]).write_text(json.dumps(identities), encoding="utf-8")
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert any(item.startswith("required-role:") for item in result["missing_or_null"])

    spec = _complete_binding_spec(tmp_path)
    spec["bun"] = str(tmp_path / "other-bun.exe")
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "spawn:executable-bun" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    spec["extension"] = [str(tmp_path / "other-extension.ts")]
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "spawn:adapter-index" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    spec["argv"] = ["bun", "cli", "--profile", "other-profile", "-e", spec["extension"][0]]
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "argv:profile" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    run_dir = tmp_path / "run-env"
    run_dir.mkdir(exist_ok=True)
    mod = _load("launch_run")
    env = {
        "SECOND_BRAIN_HOME": str(tmp_path / "other-home"),
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
    }
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "env:SECOND_BRAIN_HOME" in result["mismatched"]

    # Configuration contract: an unbound profile, an overlay env var, an
    # overlay argv flag and a project-local settings file must each fail.
    spec = _complete_binding_spec(tmp_path)
    spec["profile"] = "unbound-profile"
    spec["argv"] = [
        "bun",
        "cli",
        "--profile",
        "unbound-profile",
        "-e",
        spec["extension"][0],
    ]
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "configuration:profile" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    run_dir = tmp_path / "run-forbidden-env"
    run_dir.mkdir(exist_ok=True)
    env = {
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "PI_CONFIG_FILES": str(tmp_path / "overlay.yml"),
    }
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:forbidden-env" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    spec["argv"] = spec["argv"] + ["--config", str(tmp_path / "overlay.yml")]
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "configuration:forbidden-argv" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    overlay = Path(spec["fixture"]) / ".omp"
    overlay.mkdir()
    (overlay / "config.yml").write_text("modelRoles: {}\n", encoding="utf-8")
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "configuration:project-overlays" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    spec["schema_expected"] = 25
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert any(item.startswith("schema:") for item in result["mismatched"])

    spec = _complete_binding_spec(tmp_path)
    spec["preflight_file"] = str(tmp_path / "missing-preflight.json")
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "preflight" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    spec["fixture_identity"] = {}
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "fixture_identity:missing" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    calc = next(iter(spec["fixture_identity"]))
    spec["fixture_identity"] = {calc: "0" * 64}
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert calc in result["mismatched"]


def test_rehash_gate_detects_mismatch(tmp_path: Path) -> None:
    mod = _load("launch_run")
    target = tmp_path / "file.ts"
    target.write_text("content", encoding="utf-8")
    hashes = tmp_path / "HASHES.txt"
    hashes.write_text(f"{'deadbeef' * 8} {target}\n", encoding="utf-8")
    spec = {"hashes_file": str(hashes), "hashes_base": str(tmp_path)}
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert mod.rehash_bound_files(spec, run_dir)["all_match"] is False
    hashes.write_text(f"{_sha256(target)} {target}\n", encoding="utf-8")
    result = mod.rehash_bound_files(spec, run_dir)
    assert result["all_match"] is True
    assert result["boundary"] == "last-setup-boundary-before-spawn"


def test_expectations_and_launcher_outcome_gate_evidence() -> None:
    mod = _load("launch_run")
    watcher = {"state_1_captured": True, "state_2_captured": False}
    spec = {"expect": {"state_1": True, "state_2": False, "child_exit": 0}}
    assert mod.evaluate_expectations(spec, 0, watcher)["met"] is True
    assert mod.evaluate_expectations(spec, 1, watcher)["met"] is False
    strict = {"expect": {"state_2": True}}
    assert mod.evaluate_expectations(strict, 0, watcher)["met"] is False
    assert mod.evaluate_expectations(strict, 0, None)["met"] is False
    twin = {"expect": {"state_1": True, "state_2": False, "child_exit_nonzero": True}}
    assert mod.evaluate_expectations(twin, 1, watcher)["met"] is True
    assert mod.evaluate_expectations(twin, 0, watcher)["met"] is False

    # Watcher health gates success: incomplete evidence can never return 0.
    assert mod.launcher_outcome(True, True, 0) == 0
    assert mod.launcher_outcome(True, True, 3) == 3
    assert mod.launcher_outcome(False, True, 0) == 5
    assert mod.launcher_outcome(True, False, 0) == 4


def test_tracked_identity_inventory_matches_live_files() -> None:
    """The committed RUN-IDENTITIES.json must match the live bound files on this
    machine; a stale inventory blocks the run by design (N1 class)."""
    docs = (
        Path(__file__).resolve().parents[1] / "docs" / "integrations" / "omp-host-patch-2026-09-19"
    )
    inventory = json.loads((docs / "RUN-IDENTITIES.json").read_text(encoding="utf-8"))
    roles = [entry["role"] for entry in inventory["identities"]]
    assert set(roles) == set(inventory["required_roles"]), "required roles must be listed exactly"
    missing_on_disk = [
        entry["path"] for entry in inventory["identities"] if not Path(entry["path"]).exists()
    ]
    if missing_on_disk:
        import pytest

        pytest.skip(f"canary/worktree bound paths unavailable: {missing_on_disk[:2]}")
    for entry in inventory["identities"]:
        assert entry["sha256"] is not None, entry["path"]
        assert _sha256(Path(entry["path"])) == entry["sha256"], f"stale identity: {entry['path']}"
    for line in (docs / "HASHES.txt").read_text(encoding="utf-8").splitlines():
        digest, _, target = line.strip().partition(" ")
        assert _sha256(Path(target.strip())) == digest, f"stale HASHES entry: {target}"
    contract = inventory.get("configuration_contract") or {}
    assert contract.get("profile") == "canary-settlement"
    assert contract.get("forbidden_env"), "configuration contract must guard overlays"
    if contract.get("profile_dir") and not Path(contract["profile_dir"]).is_dir():
        import pytest

        pytest.skip(f"profile directory unavailable: {contract['profile_dir']}")


def test_binding_failure_reaps_watcher_and_records_launch(tmp_path: Path) -> None:
    """The launcher must tear the watcher down and write a launch record even
    when the binding fails before spawn (early-return teardown path)."""
    db = tmp_path / "brain.sqlite"
    conn = _make_db(db)
    conn.close()
    home = tmp_path / "home"
    (home / "db").mkdir(parents=True)
    (home / "db" / "brain.sqlite").write_bytes(db.read_bytes())

    target = tmp_path / "file.ts"
    target.write_text("content", encoding="utf-8")
    hashes = tmp_path / "HASHES.txt"
    hashes.write_text(f"{'deadbeef' * 8} {target}\n", encoding="utf-8")

    run_dir = tmp_path / "run"
    spec = {
        "name": "binding-failure-test",
        "run_dir": str(run_dir),
        "home": str(home),
        "fixture": str(tmp_path),
        "prompt_file": str(tmp_path / "prompt.txt"),
        "trace_file": str(tmp_path / "boot.txt"),
        "profile": "canary-settlement",
        "bun": str(tmp_path / "missing-bun.exe"),
        "cli": str(tmp_path / "cli.ts"),
        "extension": [],
        "hashes_file": str(hashes),
        "hashes_base": str(tmp_path),
        "identities_file": str(tmp_path / "ids.json"),
        "python": sys.executable,
        "watcher_script": str(TOOLS / "db_watch.py"),
        "watcher_ready_timeout_seconds": 30,
        "post_exit_grace_seconds": 1,
        "timeout_seconds": 30,
        "expect": {},
    }
    (tmp_path / "ids.json").write_text(
        json.dumps({"required_roles": [], "identities": []}), encoding="utf-8"
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(TOOLS / "launch_run.py"), "--spec", str(spec_path)],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            k: v
            for k, v in __import__("os").environ.items()
            if k not in ("PYTHONHOME", "PYTHONPATH")
        },
    )
    assert result.returncode == 2, result.stdout + result.stderr
    launch = json.loads((run_dir / "launch.json").read_text(encoding="utf-8"))
    assert launch["binding_failed"] is True
    assert launch["launched"] is False
    watcher_record = json.loads((run_dir / "watcher" / "watcher.json").read_text(encoding="utf-8"))
    assert watcher_record["stop_reason"] == "stop-file"
    assert watcher_record["state_2_missing"] is True
