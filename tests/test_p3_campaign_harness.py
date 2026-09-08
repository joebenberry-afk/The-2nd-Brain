"""P3 campaign harness integrity tests (plan §28/§29/§35).

Proves the repaired runner is an orchestrator only:

- it cannot write task solutions (no apply_solution, no per-task solution
  branches, no hard-coded economics constants);
- if the external agent command does nothing, the arm is REJECTED rather than
  somehow producing a valid solution;
- the compiler refuses to count invalid/rejected arms and never reads the
  invalidated archive.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "scripts" / "run_p3_promotion_campaign.py"
COMPILER = REPO_ROOT / "scripts" / "compile_p3_promotion_report.py"


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(
    py: Path | str, script: Path, *args: str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(py), str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=300,
    )


FORBIDDEN_PATTERNS = [
    "def apply_solution",
    "if task_id == ",
    'task_id == "e07"',
    "turns = 3 if",
    "input_toks = 4500",
    "output_toks = 650",
    "hard-coded turns",
    '"PROMOTE ACTIVE"',  # compiler must derive, not hard-code
]


def test_runner_has_no_solution_engine() -> None:
    src = RUNNER.read_text(encoding="utf-8")
    for pat in FORBIDDEN_PATTERNS:
        assert pat not in src, f"forbidden pattern present: {pat!r}"


def test_runner_preflight_reports_blocker_when_agy_missing(monkeypatch) -> None:
    monkeypatch.delenv("P3_AGY_CMD", raising=False)
    r = _run(sys.executable, RUNNER, "--preflight")
    assert r.returncode == 0
    assert "READY_FOR_REAL_CAMPAIGN" in r.stdout or "STOP AT READY_FOR_REAL_CAMPAIGN" in r.stdout


def test_do_nothing_agent_cannot_produce_valid_arm(tmp_path, monkeypatch) -> None:
    """Replace the model command with one that does nothing: arm must fail."""
    runner_mod = _load_script("run_p3_promotion_campaign")

    fake = tmp_path / "fake-agy.cmd"
    fake.write_text("@echo off\r\n", encoding="utf-8")
    reports_root = tmp_path / "p3-promo-eval"
    reports_root.mkdir(parents=True)
    monkeypatch.setattr(runner_mod, "REPORTS_ROOT", reports_root)
    monkeypatch.setattr(runner_mod, "MIN_WALL_MS", 0)  # isolate from timing
    monkeypatch.setenv("P3_AGY_CMD", str(fake))
    monkeypatch.setenv("P3_AGY_MODEL", "gemini-3.7-flash")

    arm = runner_mod.run_arm("e07", "e07-jsonc-config", "b", "gemini", tmp_path / "work")
    assert arm["validity"] == "REJECTED"
    assert any("conversation ID" in r for r in arm["rejections"])
    assert any("usage" in r for r in arm["rejections"])


def test_validator_rejects_fake_arm() -> None:
    runner_mod = _load_script("run_p3_promotion_campaign")

    fake = {
        "conversation_id": "",
        "usage": {},
        "model_slug": "gemini-3.7-flash",
        "wall_ms": 0,
        "acceptance": "PASS",
        "lean_state": "ON",
        "brain_telemetry": [],
        "run_artifact_path": "",
    }
    problems = runner_mod.validate_arm(fake)
    assert problems
    joined = " ".join(problems)
    assert "conversation ID" in joined
    assert "usage" in joined
    assert "wall time" in joined


def test_compiler_ignores_invalidated_and_counts_only_valid(tmp_path, monkeypatch) -> None:
    compiler_mod = _load_script("compile_p3_promotion_report")

    # Build a fake valid DeepSeek pair (e01) with real telemetry.
    promodir = tmp_path / "p3-promo-eval"
    for arm in ("b", "c"):
        d = promodir / f"e01-{arm}-1"
        d.mkdir(parents=True)
        (d / "evidence.json").write_text(
            json.dumps(
                {
                    "acceptance": "PASS",
                    "validity": "VALID_COMPLETE",
                    "diff": {"added_lines": 1, "deleted_lines": 0},
                    "lc_decisions": ["LC_REUSE: reused existing mechanism"],
                    "usage": {"inputTokens": 100},
                    "brain_telemetry": [{"kind": "preinvocation"}],
                    "lean_state": "ON",
                }
            ),
            encoding="utf-8",
        )
        (d / "telemetry.jsonl").write_text(
            json.dumps({"model": "deepseek/deepseek-v4-flash"}) + "\n", encoding="utf-8"
        )
    # An invalid/rejected arm must not count.
    bad = promodir / "e07-b-1"
    bad.mkdir(parents=True)
    (bad / "evidence.json").write_text(
        json.dumps(
            {
                "acceptance": "PASS",
                "validity": "REJECTED",
            }
        ),
        encoding="utf-8",
    )
    # Invalidated archive must never be read.
    invalid = tmp_path / "p3-promo-eval-invalidated"
    invalid.mkdir()
    (invalid / "e09-b-1").mkdir(parents=True)
    (invalid / "e09-b-1" / "evidence.json").write_text(
        json.dumps(
            {
                "acceptance": "PASS",
                "validity": "VALID_COMPLETE",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(compiler_mod, "PROMO_EVAL_DIR", promodir)
    monkeypatch.setattr(compiler_mod, "INVALIDATED_DIR", invalid)
    monkeypatch.setattr(compiler_mod, "OUTPUT_REPORT", tmp_path / "report.md")
    pairs = compiler_mod.load_pairs()
    assert len(pairs) == 1 and pairs[0]["id"] == "e01"
    verdict, _reasons = compiler_mod.compute_verdict(pairs)
    assert verdict == "HOLD SHADOW — REAL CAMPAIGN INCOMPLETE"  # 1 pair cannot promote


def test_compiler_verdict_needs_real_pairs(tmp_path, monkeypatch) -> None:
    compiler_mod = _load_script("compile_p3_promotion_report")

    assert compiler_mod.compute_verdict([])[0] == "HOLD SHADOW — REAL CAMPAIGN INCOMPLETE"
    # Even 8 fake-but-valid-marked pairs without real economics cannot promote.
    pairs = []
    for i in range(8):
        pairs.append(
            {
                "id": f"e{i:02d}",
                "provider": "gemini",
                "baseline": {
                    "acceptance": "PASS",
                    "diff": {"added_lines": 5},
                    "lc_decisions": ["LC_REUSE"],
                },
                "candidate": {
                    "acceptance": "PASS",
                    "diff": {"added_lines": 2},
                    "lc_decisions": ["LC_REUSE"],
                    "usage": {},
                    "brain_telemetry": [],
                },
            }
        )
    verdict, _reasons = compiler_mod.compute_verdict(pairs)
    assert verdict == "HOLD SHADOW — REAL CAMPAIGN INCOMPLETE"
