"""P1 orchestration telemetry tests (Phase D; plan §19/20, amendment §12/§22).

`brainctl orchestration record --json-stdin` reads one counters JSON event,
computes delegation_purity, and appends a privacy-safe record to
telemetry/agent-performance/orchestration-<session>.jsonl. Fail-open on
malformed input; only the nine counters are ever persisted.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(home: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        input=stdin,
        timeout=120,
    )


def _records(home: Path, session: str) -> list[dict]:
    f = home / "telemetry" / "agent-performance" / f"orchestration-{session}.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def _event(**kw: int) -> str:
    base = {
        "driver_actions_total": 100,
        "driver_execution_attempts": 1,
        "blocked_execution_attempts": 0,
        "emergency_execution_actions": 0,
        "worker_tasks": 5,
        "worker_corrections": 1,
        "worker_verifications": 2,
        "fan_out_width": 2,
        "recursion_depth": 0,
    }
    base.update(kw)
    return json.dumps(base)


def test_purity_math_and_record(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    r = _run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    # 1 execution + 0 emergency out of 100 actions -> purity 0.99
    r = _run_cli(home, "orchestration", "record", "--session", "s1", stdin=_event())
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["recorded"] is True
    assert out["delegation_purity"] == 0.99
    recs = _records(home, "s1")
    assert len(recs) == 1
    rec = recs[0]
    assert rec["kind"] == "orchestration_record"
    assert rec["delegation_purity"] == 0.99
    assert rec["worker_tasks"] == 5
    assert rec["fan_out_width"] == 2
    assert rec["recursion_depth"] == 0
    # emergency actions count against purity too: (1+1)/10 -> 0.8
    r2 = _run_cli(home, "orchestration", "record", "--session", "s1", stdin=_event(
        driver_actions_total=10, driver_execution_attempts=1, emergency_execution_actions=1
    ))
    out2 = json.loads(r2.stdout)
    assert out2["delegation_purity"] == 0.8
    assert len(_records(home, "s1")) == 2  # append-only


def test_zero_actions_purity_null_not_fabricated(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    _run_cli(home, "init")
    event = _event(driver_actions_total=0)
    r = _run_cli(home, "orchestration", "record", "--session", "s2", stdin=event)
    out = json.loads(r.stdout)
    assert out["recorded"] is True
    assert out["delegation_purity"] is None  # never infer 0 or 1 from no data
    rec = _records(home, "s2")[0]
    assert rec["delegation_purity"] is None


def test_malformed_fail_open(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    _run_cli(home, "init")
    for bad in ("not json", "", '{"driver_actions_total": -3}', '{"driver_actions_total": "x"}'):
        r = _run_cli(home, "orchestration", "record", "--session", "s3", stdin=bad)
        assert r.returncode == 0, (bad, r.stderr)
        out = json.loads(r.stdout)
        assert out["recorded"] is False
        assert "error" in out
    assert _records(home, "s3") == []  # nothing persisted for malformed input


def test_only_known_counters_persisted_no_secrets(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    _run_cli(home, "init")
    payload = json.loads(_event())
    payload["secret_token"] = "s3cr3t"
    payload["raw_prompt"] = "do the thing"
    r = _run_cli(home, "orchestration", "record", "--session", "s4", stdin=json.dumps(payload))
    assert r.returncode == 0
    rec = _records(home, "s4")[0]
    assert "secret_token" not in rec
    assert "raw_prompt" not in rec
    assert set(rec) <= {
        "v", "ts", "kind", "session", "delegation_purity",
        "driver_actions_total", "driver_execution_attempts", "blocked_execution_attempts",
        "emergency_execution_actions", "worker_tasks", "worker_corrections",
        "worker_verifications", "fan_out_width", "recursion_depth",
    }
