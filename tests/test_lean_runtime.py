"""Lean runtime parity tests (plan §23).

Proves the harness-neutral lean_runtime helper mirrors the proven Prime
lean-code.ts semantics and that the canonical skill file is the single
kernel source (kernel hash/char count unchanged; no duplicate copy).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from second_brain import lean_runtime

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_SKILL = REPO_ROOT / "skills" / "candidates" / "lean-code" / "SKILL.md"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Minimal brain root for lean runtime tests (no full init needed)."""
    return tmp_path / "brain"


@pytest.fixture(autouse=True)
def _reset_cache():
    lean_runtime.reset_lean_kernel_cache()
    yield
    lean_runtime.reset_lean_kernel_cache()


def _seed(home: Path, level: str) -> None:
    target = home / "skills" / level / "lean-code"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANDIDATE_SKILL, target / "SKILL.md")


def _decide(home: Path, role: str, env: dict[str, str] | None = None):
    return lean_runtime.decide_lean_runtime(home, role, "base prompt", env=env)


def test_candidate_no_override_inert(home: Path) -> None:
    _seed(home, "candidates")
    out = _decide(home, "driver")
    assert out.decision == "omit" and out.reason == "off"
    assert out.kernel is None


def test_candidate_off_inert(home: Path) -> None:
    _seed(home, "candidates")
    out = _decide(home, "driver", {"SECOND_BRAIN_LEAN": "off"})
    assert out.decision == "omit" and out.reason == "off"


def test_candidate_advisory_injects(home: Path) -> None:
    _seed(home, "candidates")
    out = _decide(home, "driver", {"SECOND_BRAIN_LEAN": "advisory"})
    assert out.decision == "inject" and out.reason == "advisory"
    assert out.kernel is not None
    assert len(out.kernel) == 865


def test_active_injects(home: Path) -> None:
    _seed(home, "active")
    out = _decide(home, "driver")
    assert out.decision == "inject" and out.reason == "active"


def test_active_off_inert(home: Path) -> None:
    _seed(home, "active")
    out = _decide(home, "worker", {"SECOND_BRAIN_LEAN": "off"})
    assert out.decision == "omit"


def test_retired_inert(home: Path) -> None:
    _seed(home, "retired")
    out = _decide(home, "driver", {"SECOND_BRAIN_LEAN": "advisory"})
    assert out.decision == "omit"


def test_missing_skill_fail_open(home: Path) -> None:
    out = _decide(home, "driver", {"SECOND_BRAIN_LEAN": "advisory"})
    assert out.decision == "omit" and out.reason == "skill-missing"
    assert out.error is not None


def test_role_gate(home: Path) -> None:
    _seed(home, "active")
    assert _decide(home, "hard_orchestrator").decision == "omit"
    assert _decide(home, "reviewer").decision == "omit"
    assert _decide(home, "driver").decision == "inject"
    assert _decide(home, "worker").decision == "inject"


def test_dedup_marker(home: Path) -> None:
    _seed(home, "active")
    base = f"prompt [{lean_runtime.LEAN_KERNEL_MARKER}]"
    out = lean_runtime.decide_lean_runtime(home, "driver", base)
    assert out.decision == "omit" and out.dedup_hit is True


def test_file_eval_gate(home: Path) -> None:
    _seed(home, "candidates")
    (home / "config").mkdir(parents=True, exist_ok=True)
    cfg = home / "config" / "skills.toml"
    cfg.write_text('[lean]\neval = "advisory"\n', encoding="utf-8")
    out = _decide(home, "driver")
    assert out.decision == "inject" and out.eval_source == "file"
    cfg.write_text('[lean]\neval = "off"\n', encoding="utf-8")
    out = _decide(home, "driver")
    assert out.decision == "omit"


def test_env_overrides_file(home: Path) -> None:
    _seed(home, "candidates")
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "config" / "skills.toml").write_text('[lean]\neval = "advisory"\n', encoding="utf-8")
    out = _decide(home, "driver", {"SECOND_BRAIN_LEAN": "off"})
    assert out.decision == "omit" and out.eval_source == "env"


def test_kernel_bytes_unchanged_and_single_source(home: Path) -> None:
    canonical_text = CANDIDATE_SKILL.read_text(encoding="utf-8")
    kernel = lean_runtime.extract_runtime_kernel(canonical_text)
    assert kernel is not None
    assert len(kernel) == 865
    expected_sha = hashlib.sha256(kernel.encode("utf-8")).hexdigest()

    _seed(home, "active")
    out = _decide(home, "driver")
    assert out.kernel is not None and out.kernel == kernel
    assert hashlib.sha256(out.kernel.encode("utf-8")).hexdigest() == expected_sha

    # no duplicate kernel copy anywhere else in the repo
    kernel_text = kernel
    for level_dir in ("candidates", "shadow", "active", "retired"):
        p = REPO_ROOT / "skills" / level_dir / "lean-code" / "SKILL.md"
        if p.exists() and p != CANDIDATE_SKILL:
            assert lean_runtime.extract_runtime_kernel(p.read_text(encoding="utf-8")) != kernel_text
    assert "LEAN CODE: deliver the smallest" in kernel_text
