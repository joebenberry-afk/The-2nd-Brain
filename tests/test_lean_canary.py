"""Lean Code runtime kernel activation and canary verification tests (plan §11-§14).

Validates:
- Lean Runtime Kernel activation through the canonical config/skills.toml path.
- In-process hook integration and ephemeral message composition.
- Dedup marker, role gating, and fail-open behavior.
- Controlled comparison proving runtime injection when active vs inert when off.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

import pytest

from second_brain import cli, frontier, lean_runtime

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_LEAN_SKILL = REPO_ROOT / "skills" / "candidates" / "lean-code" / "SKILL.md"


@pytest.fixture(autouse=True)
def _reset_cache():
    lean_runtime.reset_lean_kernel_cache()
    yield
    lean_runtime.reset_lean_kernel_cache()


def _seed_lean_skill(home: Path) -> None:
    """Seed the canonical lean-code skill and config into the test brain_home."""
    target_skill = home / "skills" / "candidates" / "lean-code"
    target_skill.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANONICAL_LEAN_SKILL, target_skill / "SKILL.md")
    frontier.frontier_review(
        home, "skill-lean-code-promotion", "skill", "high", "reviewer", "approve"
    )

    target_cfg = home / "config" / "skills.toml"
    target_cfg.parent.mkdir(parents=True, exist_ok=True)
    target_cfg.write_text(
        'schema_version = 1\n\n[lean]\neval = "advisory"\n\n[router]\nmax_active = 3\n',
        encoding="utf-8",
    )


def test_lean_runtime_kernel_activated_from_skills_toml(brain_home: Path) -> None:
    """Proves Lean Runtime Kernel is active when [lean] eval = 'advisory' in config/skills.toml."""
    _seed_lean_skill(brain_home)
    outcome = lean_runtime.decide_lean_runtime(brain_home, "driver", "perform engineering task")
    assert outcome.decision == "inject"
    assert outcome.reason == "advisory"
    assert outcome.mode == "advisory"
    assert outcome.eval_source == "file"
    assert outcome.kernel is not None
    assert "LEAN CODE: deliver the smallest" in outcome.kernel
    assert outcome.kernel_chars == len(outcome.kernel)
    assert outcome.dedup_hit is False


def test_lean_kernel_dedup_marker_suppresses_duplicate_block(brain_home: Path) -> None:
    """Kernel marker already in context prevents duplicate kernel injection."""
    _seed_lean_skill(brain_home)
    kernel_block = lean_runtime.compose_lean_kernel_block("some kernel")
    base_with_marker = f"Context before turn\n{kernel_block}\nNext user prompt"

    outcome = lean_runtime.decide_lean_runtime(brain_home, "driver", base_with_marker)
    assert outcome.decision == "omit"
    assert outcome.dedup_hit is True
    assert outcome.kernel is None


def test_lean_role_gating_applies_to_driver_and_worker_only(brain_home: Path) -> None:
    """Only driver and worker roles receive the Lean kernel; orchestrator/reviewer do not."""
    _seed_lean_skill(brain_home)
    for allowed_role in ("driver", "worker"):
        res = lean_runtime.decide_lean_runtime(brain_home, allowed_role, "task prompt")
        assert res.decision == "inject"
        assert res.kernel is not None

    for disallowed_role in ("hard_orchestrator", "reviewer", "observer", "unknown"):
        res = lean_runtime.decide_lean_runtime(brain_home, disallowed_role, "task prompt")
        assert res.decision == "omit"
        assert res.reason == "role"
        assert res.kernel is None


def test_antigravity_hook_injects_lean_kernel_ephemeral(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the live Antigravity hook pipeline injects the Lean Kernel into model context."""
    _seed_lean_skill(brain_home)
    # Ensure autoinject config is active
    (brain_home / "config" / "autoinject.toml").write_text(
        'schema_version = 1\n\n[autoinject]\nmode = "active"\n', encoding="utf-8"
    )

    payload = {
        "event": "PreInvocation",
        "conversationId": "conv-lean-canary-01",
        "modelName": "gemini-3.7-flash-high",
        "workspacePaths": [str(brain_home)],
        "task": "Refactor database connection pool safely",
        "preInvocationHookArgs": {"invocationNum": 1, "initialNumSteps": 0},
    }

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)

    exit_code = cli._cmd_antigravity_hook(brain_home)
    assert exit_code == 0

    output = json.loads(buf.getvalue())
    assert "injectSteps" in output
    ephemeral = output["injectSteps"][0]["ephemeralMessage"]
    assert lean_runtime.LEAN_KERNEL_MARKER in ephemeral
    assert "LEAN CODE: deliver the smallest" in ephemeral


def test_controlled_comparison_lean_active_vs_off(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Controlled comparison: same prompt under Lean active vs SECOND_BRAIN_LEAN=off."""
    _seed_lean_skill(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        'schema_version = 1\n\n[autoinject]\nmode = "active"\n', encoding="utf-8"
    )

    payload = {
        "event": "PreInvocation",
        "conversationId": "conv-lean-comparison",
        "modelName": "gemini-3.7-flash-high",
        "workspacePaths": [str(brain_home)],
        "task": "Implement bounded retry with backoff",
        "preInvocationHookArgs": {"invocationNum": 1, "initialNumSteps": 0},
    }

    # Arm 1: Lean active (default via config/skills.toml)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    buf_active = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf_active)
    assert cli._cmd_antigravity_hook(brain_home) == 0
    out_active = json.loads(buf_active.getvalue())
    ep_active = out_active["injectSteps"][0]["ephemeralMessage"]
    assert lean_runtime.LEAN_KERNEL_MARKER in ep_active

    # Arm 2: Lean disabled via env override
    monkeypatch.setenv("SECOND_BRAIN_LEAN", "off")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    buf_off = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf_off)
    assert cli._cmd_antigravity_hook(brain_home) == 0
    out_off = json.loads(buf_off.getvalue())
    # Lean marker must NOT be in the ephemeral message when Lean is off
    if "injectSteps" in out_off:
        ep_off = out_off["injectSteps"][0]["ephemeralMessage"]
        assert lean_runtime.LEAN_KERNEL_MARKER not in ep_off
    else:
        assert out_off == {}


def test_lean_telemetry_emission_active_vs_off(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that preinvocation telemetry captures Lean execution telemetry accurately."""
    _seed_lean_skill(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        'schema_version = 1\n\n[autoinject]\nmode = "active"\n', encoding="utf-8"
    )

    conv_id = "conv-telem-lean-eval"
    payload = {
        "event": "PreInvocation",
        "conversationId": conv_id,
        "modelName": "gemini-3.7-flash-high",
        "workspacePaths": [str(brain_home)],
        "task": "Test task with Lean active",
        "preInvocationHookArgs": {"invocationNum": 1, "initialNumSteps": 0},
    }

    # Turn 1: Lean active
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert cli._cmd_antigravity_hook(brain_home) == 0

    # Turn 2: Lean disabled
    monkeypatch.setenv("SECOND_BRAIN_LEAN", "off")
    payload_off = dict(payload)
    payload_off["conversationId"] = f"{conv_id}-off"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload_off)))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert cli._cmd_antigravity_hook(brain_home) == 0

    hook_log = brain_home / "telemetry" / "agent-performance" / "antigravity-hooks.jsonl"
    assert hook_log.is_file()

    records = [json.loads(line) for line in hook_log.read_text(encoding="utf-8").splitlines()]
    pre_on = next(r for r in records if r["kind"] == "preinvocation" and r["session"] == conv_id)
    assert pre_on["lean_decision"] == "inject"
    assert pre_on["lean_reason"] == "advisory"
    assert pre_on["lean_mode"] == "advisory"
    assert pre_on["lean_eval_source"] == "file"
    assert pre_on["lean_kernel_chars"] > 0
    assert pre_on["lean_dedup_hit"] is False

    pre_off = next(
        r for r in records if r["kind"] == "preinvocation" and r["session"] == f"{conv_id}-off"
    )
    assert pre_off["lean_decision"] == "omit"
    assert pre_off["lean_reason"] == "off"
    assert pre_off["lean_mode"] == "off"
    assert pre_off["lean_eval_source"] == "env"
    assert pre_off["lean_kernel_chars"] == 0
