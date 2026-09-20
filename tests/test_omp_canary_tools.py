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
    assert not (tmp_path / "out" / "state-2.sqlite").exists()

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
    provider_settings = tmp_path / "provider-settings.json"
    provider_settings.write_text("{}\n", encoding="utf-8")
    home_root = tmp_path / "home-root"
    profile_dir = home_root / ".omp" / "profiles" / "canary-settlement"
    profile_agent_dir = profile_dir / "agent"
    profile_agent_dir.mkdir(parents=True, exist_ok=True)

    roles = {
        "executable-bun": bun,
        "executable-cli-entry": cli,
        "configuration-canary-package": package,
        "configuration-default-profile-user": user_config,
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
                    "home_dir": str(home_root),
                    "config_dir_name": ".omp",
                    "profile_dir": str(profile_dir),
                    "profile_agent_dir": str(profile_agent_dir),
                    "profile_config_files": [
                        {"name": "config.yml", "expects": "absent"},
                        {"name": "config.yaml", "expects": "absent"},
                        {"name": "settings.json", "expects": "absent"},
                        {"name": ".env", "expects": "absent"},
                    ],
                    "env_files_must_be_absent": [
                        str(home_root / ".env"),
                        str(home_root / ".omp" / ".env"),
                        str(home_root / ".bunfig.toml"),
                    ],
                    "default_profile_user_config": str(user_config),
                    "forbidden_env": [
                        "PI_CONFIG_DIR",
                        "PI_CONFIG_FILES",
                        "OMP_PROFILE",
                        "PI_PROFILE",
                        "BUN_OPTIONS",
                        "NODE_OPTIONS",
                        "SECOND_BRAIN_OBSERVABILITY",
                    ],
                    "forbidden_env_prefixes": [
                        "BUN_",
                        "NODE_",
                        "PI_",
                        "OMP_",
                        "OM_CANARY_",
                        "SECOND_BRAIN_",
                    ],
                    "allowed_env_exceptions": [
                        "OM_CANARY_BOOT",
                        "OM_CANARY_FORCE_ISOLATED",
                        "OM_CANARY_ISOLATION",
                        "OM_CANARY_HOLD_RELEASE_UNTIL",
                        "SECOND_BRAIN_HOME",
                        "SECOND_BRAIN_PYTHON",
                    ],
                    "required_env_values": {
                        "OM_CANARY_FORCE_ISOLATED": "1",
                        "OM_CANARY_ISOLATION": "1",
                    },
                    "forbidden_argv_flags": ["--config"],
                    "forbidden_project_overlays": [
                        ".omp/config.yml",
                        ".claude/settings.yml",
                        ".env",
                        ".env.production",
                        "bunfig.toml",
                    ],
                    "fixture_allowed_entries": ["calc.py", "test_calc.py", "AGENTS.md"],
                    "user_provider_files": [
                        {"path": str(provider_settings), "sha256": _sha256(provider_settings)},
                        {"path": str(tmp_path / "absent-provider.json"), "expects": "absent"},
                    ],
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
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "config" / "context.toml").write_text("[rtd]\nenabled = true\n", encoding="utf-8")
    conn = sqlite3.connect(home / "db" / "brain.sqlite")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER, applied_at TEXT)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (24, '2026-01-01T00:00:00')")
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
                "home_config_manifest": {"context.toml": _sha256(home / "config" / "context.toml")},
                "home_config_exists": True,
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
        "_profile_agent_dir": str(profile_agent_dir),
        "_home_root": str(home_root),
    }


def _bind(tmp_path: Path, spec: dict) -> dict:
    mod = _load("launch_run")
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    env = {
        "USERPROFILE": spec["_home_root"],
        "HOME": spec["_home_root"],
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
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
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
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
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
        "PI_CONFIG_FILES": str(tmp_path / "overlay.yml"),
    }
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:forbidden-env" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    run_dir = tmp_path / "run-forbidden-config-dir"
    run_dir.mkdir(exist_ok=True)
    env = {
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
        "PI_CONFIG_DIR": ".astra-round5-nonexistent-config-root",
    }
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:forbidden-env" in result["mismatched"]

    spec = _complete_binding_spec(tmp_path)
    agent_config = Path(spec["_profile_agent_dir"]) / "config.yml"
    agent_config.write_text("modelRoles: {}\n", encoding="utf-8")
    result = _bind(tmp_path, spec)
    assert result["all_bound"] is False
    assert "configuration:profile-config:config.yml" in result["mismatched"]

    # A child-only USERPROFILE override moves the effective home and the
    # named-profile configuration root; the parent environment stays valid.
    spec = _complete_binding_spec(tmp_path)
    redirect = tmp_path / "redirect-home"
    (redirect / ".omp" / "profiles" / "canary-settlement" / "agent").mkdir(
        parents=True, exist_ok=True
    )
    run_dir = tmp_path / "run-redirect-home"
    run_dir.mkdir(exist_ok=True)
    env = {
        "USERPROFILE": str(redirect),
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
    }
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:home-dir" in result["mismatched"]
    assert "configuration:resolved-profile-dir" in result["mismatched"]

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


def test_windows_case_folding_and_relative_home_cannot_bypass_binding(tmp_path: Path) -> None:
    """Windows environment lookup is case-insensitive and child-relative paths
    resolve from the child cwd; both must be modelled by the gate."""
    mod = _load("launch_run")
    spec = _complete_binding_spec(tmp_path)
    redirect = tmp_path / "redirect-home"
    (redirect / ".omp" / "profiles" / "canary-settlement" / "agent").mkdir(
        parents=True, exist_ok=True
    )
    run_dir = tmp_path / "run-case"
    run_dir.mkdir(exist_ok=True)

    # A lower/mixed-case extra_env key must not evade the case-insensitive
    # child lookup: the gate and the child must see the same variable.
    base = {
        "USERPROFILE": spec["_home_root"],
        "HOME": spec["_home_root"],
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
    }
    env = mod.merge_env(base, {"userprofile": str(redirect)})
    assert sum(1 for key in env if key.upper() == "USERPROFILE") == 1
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:home-dir" in result["mismatched"]
    assert "configuration:resolved-profile-dir" in result["mismatched"]

    env = mod.merge_env(base, {"pi_config_dir": ".astra-redirect"})
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:forbidden-env" in result["mismatched"]

    # A relative home must fail: the gate runs from the launcher cwd while the
    # child runs from the fixture cwd.
    env = dict(base)
    env["USERPROFILE"] = "..\\..\\..\\.."
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:home-dir" in result["mismatched"]


def test_unbound_omp_environment_overrides_rejected(tmp_path: Path) -> None:
    """Every PI_/OMP_/OM_CANARY_ variable except the run contract set must be
    rejected, and the contract set must carry its expected values."""
    mod = _load("launch_run")
    spec = _complete_binding_spec(tmp_path)
    run_dir = tmp_path / "run-omp-env"
    run_dir.mkdir(exist_ok=True)
    base = {
        "USERPROFILE": spec["_home_root"],
        "HOME": spec["_home_root"],
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
    }
    assert (
        mod.bind_required_identities(spec, run_dir, dict(base), spec["argv"])["all_bound"] is True
    )

    for override in (
        {"OM_CANARY_AGENT_IDLE_TTL_MS": "12345"},
        {"PI_SMOL_MODEL": "some-model"},
        {"OMP_THREADS": "2"},
        {"om_canary_agent_idle_ttl_ms": "0"},
    ):
        env = dict(base)
        env.update(override)
        result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
        assert result["all_bound"] is False, override
        assert "configuration:forbidden-env-prefixes" in result["mismatched"], override

    env = dict(base)
    env["OM_CANARY_FORCE_ISOLATED"] = "0"
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:required-env-values" in result["mismatched"]

    # The hold prefix must match the spec: absent when no hold is requested,
    # exactly the requested value otherwise.
    env_hold = dict(base)
    env_hold["OM_CANARY_HOLD_RELEASE_UNTIL"] = "C:/tmp/hold."
    result = mod.bind_required_identities(spec, run_dir, env_hold, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:hold-prefix" in result["mismatched"]

    spec_hold = _complete_binding_spec(tmp_path)
    spec_hold["hold_prefix"] = "C:/tmp/hold."
    env_ok = dict(base)
    env_ok["OM_CANARY_HOLD_RELEASE_UNTIL"] = "C:/tmp/hold."
    result = mod.bind_required_identities(spec_hold, run_dir, env_ok, spec_hold["argv"])
    assert result["all_bound"] is True

    env_bad = dict(base)
    env_bad["OM_CANARY_HOLD_RELEASE_UNTIL"] = "C:/tmp/other."
    result = mod.bind_required_identities(spec_hold, run_dir, env_bad, spec_hold["argv"])
    assert result["all_bound"] is False
    assert "configuration:hold-prefix" in result["mismatched"]

    # The adapter must not be silently disabled and its home must exist.
    for override in (
        {"SECOND_BRAIN_OBSERVABILITY": "off"},
        {"second_brain_observability": "0"},
        {"SECOND_BRAIN_TELEMETRY": "0"},
    ):
        env_disabled = dict(base)
        env_disabled.update(override)
        result = mod.bind_required_identities(spec, run_dir, env_disabled, spec["argv"])
        assert result["all_bound"] is False, override
        assert "configuration:forbidden-env-prefixes" in result["mismatched"], override

    env_missing_home = dict(base)
    env_missing_home["SECOND_BRAIN_HOME"] = str(tmp_path / "no-such-home")
    result = mod.bind_required_identities(spec, run_dir, env_missing_home, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:brain-home-exists" in result["mismatched"]


def test_dotenv_injection_paths_cannot_bypass_binding(tmp_path: Path) -> None:
    """OMP eagerly loads .env from the home, config root, profile agent dir and
    project cwd even when bun autoload is disabled; each path must fail closed."""
    mod = _load("launch_run")
    spec = _complete_binding_spec(tmp_path)
    run_dir = tmp_path / "run-dotenv"
    run_dir.mkdir(exist_ok=True)
    env = {
        "USERPROFILE": spec["_home_root"],
        "HOME": spec["_home_root"],
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
    }

    project_env = Path(spec["fixture"]) / ".env"
    project_env.write_text("PI_CONFIG_DIR=.redirect\n", encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:project-overlays" in result["mismatched"]
    project_env.unlink()

    agent_env = Path(spec["_profile_agent_dir"]) / ".env"
    agent_env.write_text("PI_CONFIG_DIR=.redirect\n", encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:profile-config:.env" in result["mismatched"]
    agent_env.unlink()

    home_env = Path(spec["_home_root"]) / ".env"
    home_env.write_text("PI_CONFIG_DIR=.redirect\n", encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:env-files-absent" in result["mismatched"]
    home_env.unlink()

    # Bun startup inputs: BUN_OPTIONS/NODE_OPTIONS (and any BUN_/NODE_ prefix)
    # can preload code or inject env files despite --no-env-file.
    env_opt = dict(env)
    env_opt["BUN_OPTIONS"] = "--preload C:/tmp/preload.cjs"
    result = mod.bind_required_identities(spec, run_dir, env_opt, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:forbidden-env" in result["mismatched"]

    env_cf = {k.upper(): v for k, v in env.items()}
    env_cf["BUN_INSTALL"] = "C:/tmp/bun"
    result = mod.bind_required_identities(spec, run_dir, env_cf, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:forbidden-env-prefixes" in result["mismatched"]

    # Bun also reads bunfig.toml from the fixture cwd and the home directory.
    bunfig = Path(spec["fixture"]) / "bunfig.toml"
    bunfig.write_text('preload = ["C:/tmp/preload.cjs"]\n', encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:project-overlays" in result["mismatched"]
    bunfig.unlink()

    home_bunfig = Path(spec["_home_root"]) / ".bunfig.toml"
    home_bunfig.write_text('preload = ["C:/tmp/preload.cjs"]\n', encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:env-files-absent" in result["mismatched"]
    home_bunfig.unlink()

    # bun autoload must also be disabled for the actual child.
    mod_main = (TOOLS / "launch_run.py").read_text(encoding="utf-8")
    assert '"--no-env-file"' in mod_main


def test_project_and_user_discovery_inputs_cannot_bypass_binding(tmp_path: Path) -> None:
    """Project-level provider files live only in the fixture allowlist, and
    user-level provider files are hash-bound or enforced absent."""
    mod = _load("launch_run")
    spec = _complete_binding_spec(tmp_path)
    run_dir = tmp_path / "run-discovery"
    run_dir.mkdir(exist_ok=True)
    env = {
        "USERPROFILE": spec["_home_root"],
        "HOME": spec["_home_root"],
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
    }
    assert mod.bind_required_identities(spec, run_dir, env, spec["argv"])["all_bound"] is True

    # A project settings provider file in the fixture is not allowed.
    opencode = Path(spec["fixture"]) / "opencode.json"
    opencode.write_text('{"compaction": {"enabled": false}}\n', encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:fixture-tree" in result["mismatched"]
    opencode.unlink()

    # Changing a bound user provider file must fail.
    contract = json.loads(Path(spec["identities_file"]).read_text(encoding="utf-8"))
    bound_path = next(
        item["path"]
        for item in contract["configuration_contract"]["user_provider_files"]
        if "sha256" in item
    )
    Path(bound_path).write_text('{"changed": true}\n', encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert any(item.startswith("configuration:user-provider") for item in result["mismatched"])

    # Creating a file the contract requires absent must fail.
    spec = _complete_binding_spec(tmp_path)
    absent_path = next(
        item["path"]
        for item in json.loads(Path(spec["identities_file"]).read_text(encoding="utf-8"))[
            "configuration_contract"
        ]["user_provider_files"]
        if item.get("expects") == "absent"
    )
    Path(absent_path).write_text("{}\n", encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert any(item.startswith("configuration:user-provider") for item in result["mismatched"])


def test_home_config_manifest_binds_run_home_configuration(tmp_path: Path) -> None:
    """The run home's canonical config directory is a snapshot manifest; any
    added, removed or changed file fails the last-boundary gate."""
    mod = _load("launch_run")
    spec = _complete_binding_spec(tmp_path)
    run_dir = tmp_path / "run-home-config"
    run_dir.mkdir(exist_ok=True)
    env = {
        "USERPROFILE": spec["_home_root"],
        "HOME": spec["_home_root"],
        "SECOND_BRAIN_HOME": spec["home"],
        "SECOND_BRAIN_PYTHON": spec["python"],
        "OM_CANARY_BOOT": spec["trace_file"],
        "OM_CANARY_FORCE_ISOLATED": "1",
        "OM_CANARY_ISOLATION": "1",
    }
    assert mod.bind_required_identities(spec, run_dir, env, spec["argv"])["all_bound"] is True

    added = Path(spec["home"]) / "config" / "autoinject.toml"
    added.write_text('[autoinject]\nmode = "off"\n', encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:home-config-manifest" in result["mismatched"]
    added.unlink()

    changed = Path(spec["home"]) / "config" / "context.toml"
    changed.write_text("[rtd]\nenabled = false\n", encoding="utf-8")
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:home-config-manifest" in result["mismatched"]
    changed.write_text("[rtd]\nenabled = true\n", encoding="utf-8")

    changed.unlink()
    result = mod.bind_required_identities(spec, run_dir, env, spec["argv"])
    assert result["all_bound"] is False
    assert "configuration:home-config-manifest" in result["mismatched"]
    changed.write_text("[rtd]\nenabled = true\n", encoding="utf-8")


def test_fixture_files_are_lf_for_native_patch_application(tmp_path: Path) -> None:
    """The pinned host's native canApplyPatch refuses a CRLF worktree whose
    patch context is LF; fixture sources must be written LF."""
    mod = _load("preflight_run")
    target = tmp_path / "calc.py"
    mod.write_lf(target, "def add(a, b):\r\n    return a - b\n")
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw == b"def add(a, b):\n    return a - b\n"


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
    if contract.get("profile_agent_dir") and Path(contract["profile_agent_dir"]).is_dir():
        for item in contract.get("profile_config_files", []):
            if item.get("expects") == "absent":
                assert not (Path(contract["profile_agent_dir"]) / str(item["name"])).exists(), (
                    "unbound profile config present; refresh the contract deliberately: "
                    f"{item['name']}"
                )
    for path in contract.get("env_files_must_be_absent", []):
        assert not Path(str(path)).exists(), f"unbound env file present: {path}"
    for item in contract.get("user_provider_files", []):
        path = Path(str(item["path"]))
        if item.get("expects") == "absent":
            assert not path.exists(), f"unbound user provider file present: {path}"
        else:
            assert path.exists(), f"bound user provider file missing: {path}"
            assert _sha256(path) == item["sha256"], f"stale user provider identity: {path}"
    fixture_entries = contract.get("fixture_allowed_entries", [])
    for entry in ("calc.py", "test_calc.py", "AGENTS.md"):
        assert entry in fixture_entries, f"fixture allowlist must include {entry}"


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
