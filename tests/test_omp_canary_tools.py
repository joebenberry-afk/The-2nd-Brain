"""Focused tests for the OMP qualification campaign tools (scripts/omp-canary).

These cover the review findings that are deterministically testable without a
live OMP process:

- snapshot classification is taken from the retained snapshot itself, so
  terminal bytes are never labelled state-1 (L1);
- missing-state reporting is explicit even when no attempt window was observed
  (L2);
- stale run inputs and null/mismatched identities fail the launch gate
  (L4/B1/B2);
- expectation gating turns an evidence-incomplete run into a non-success.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
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


def test_fresh_inputs_reject_stale_marker_and_trace(tmp_path: Path) -> None:
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
    errors = mod.validate_fresh_inputs(spec)
    assert len(errors) == 2

    (run_dir / "launch.json").write_text("{}", encoding="utf-8")
    marker.unlink()
    trace.unlink()
    errors = mod.validate_fresh_inputs(spec)
    assert len(errors) == 1


def test_required_identity_binding_gates_null_and_mismatch(tmp_path: Path) -> None:
    mod = _load("launch_run")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    good = tmp_path / "good.ts"
    good.write_text("export {};", encoding="utf-8")
    missing = tmp_path / "missing.ts"

    identities = tmp_path / "ids.json"
    identities.write_text(
        json.dumps(
            {
                "identities": [
                    {"role": "executable", "path": str(good), "sha256": _sha256(good)},
                    {"role": "observer", "path": str(missing), "sha256": None},
                ]
            }
        ),
        encoding="utf-8",
    )
    spec = {
        "identities_file": str(identities),
        "fixture_identity": {str(good): _sha256(good)},
    }
    result = mod.bind_required_identities(spec, run_dir)
    assert result["all_bound"] is False
    assert str(missing) in result["missing_or_null"]

    identities.write_text(
        json.dumps(
            {"identities": [{"role": "executable", "path": str(good), "sha256": _sha256(good)}]}
        ),
        encoding="utf-8",
    )
    result = mod.bind_required_identities(spec, run_dir)
    assert result["all_bound"] is True

    spec["fixture_identity"] = {str(good): "0" * 64}
    result = mod.bind_required_identities(spec, run_dir)
    assert result["all_bound"] is False
    assert str(good) in result["mismatched"]


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


def test_expectations_gate_evidence_incomplete_runs() -> None:
    mod = _load("launch_run")
    watcher = {"state_1_captured": True, "state_2_captured": False}
    spec = {"expect": {"state_1": True, "state_2": False, "child_exit": 0}}
    assert mod.evaluate_expectations(spec, 0, watcher)["met"] is True
    assert mod.evaluate_expectations(spec, 1, watcher)["met"] is False
    strict = {"expect": {"state_2": True}}
    assert mod.evaluate_expectations(strict, 0, watcher)["met"] is False
    assert mod.evaluate_expectations(strict, 0, None)["met"] is False
