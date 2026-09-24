"""V3 shipping profile: the Lean advisory kernel is OFF by default (S2, PERF-01).

The renderers decide Lean injection from `<home>/config/skills.toml` ``[lean] eval``
(env ``SECOND_BRAIN_LEAN`` overrides). S2 ships that gate as ``off`` in both places a
home can come from:

  * ``config/skills.toml`` - this branch's deployable home configuration;
  * ``src/second_brain/defaults/config/skills.toml`` - the seed ``brainctl init``
    copies into a newly initialized home.

The gate is configuration, not deletion: the canonical kernel stays in
``skills/<lifecycle>/lean-code/SKILL.md`` and is re-enabled per environment with
``SECOND_BRAIN_LEAN=advisory`` or ``eval = "advisory"`` (the V3 harness runs the
latter as its ``candidate_lean`` ablation arm).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from second_brain import cli, frontier, lean_runtime

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_CONFIG = REPO_ROOT / "config" / "skills.toml"
SEEDED_CONFIG = REPO_ROOT / "src" / "second_brain" / "defaults" / "config" / "skills.toml"
CANONICAL_LEAN_SKILL = REPO_ROOT / "skills" / "candidates" / "lean-code" / "SKILL.md"


@pytest.fixture(autouse=True)
def _reset_cache():
    lean_runtime.reset_lean_kernel_cache()
    yield
    lean_runtime.reset_lean_kernel_cache()


def _home_with_config(home: Path, config: Path, *, skill: bool = True) -> Path:
    """A disposable home carrying `config` as its skills.toml, plus the kernel source."""
    (home / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(config, home / "config" / "skills.toml")
    if skill:
        target = home / "skills" / "candidates" / "lean-code"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CANONICAL_LEAN_SKILL, target / "SKILL.md")
        # The renderer only injects reviewed content: bind the copied kernel to a
        # current approval exactly like tests/test_lean_canary.py does.
        frontier.frontier_review(
            home, "skill-lean-code-promotion", "skill", "high", "reviewer", "approve"
        )
    return home


def test_deployable_config_ships_lean_off(tmp_path: Path) -> None:
    """The branch's own home config resolves the gate to off and injects nothing."""
    home = _home_with_config(tmp_path / "shipped", SHIPPED_CONFIG)
    assert lean_runtime.resolve_lean_eval(home, env={}) == {
        "mode": "off",
        "source": "file",
        "error": None,
    }
    for role in ("driver", "worker"):
        outcome = lean_runtime.decide_lean_runtime(
            home, role, "perform the engineering task", env={}
        )
        assert outcome.decision == "omit"
        assert outcome.reason == "off"
        assert outcome.mode == "off" and outcome.eval_source == "file"
        assert outcome.kernel is None and outcome.kernel_chars == 0
        assert outcome.level == "NOOP"


def test_freshly_seeded_home_ships_lean_off(tmp_path: Path) -> None:
    """A new install (`brainctl init` seed) injects no Lean kernel either."""
    home = tmp_path / "seeded"
    home.mkdir()
    assert cli._seed_defaults(home) > 0
    assert (home / "config" / "skills.toml").read_text(
        encoding="utf-8"
    ) == SEEDED_CONFIG.read_text(encoding="utf-8")
    # A real install promotes the canonical kernel independently of the gate.
    target = home / "skills" / "candidates" / "lean-code"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANONICAL_LEAN_SKILL, target / "SKILL.md")
    outcome = lean_runtime.decide_lean_runtime(home, "driver", "task", env={})
    assert outcome.decision == "omit" and outcome.reason == "off"
    assert outcome.eval_source == "file" and outcome.mode == "off"


def test_env_override_re_enables_the_gate(tmp_path: Path) -> None:
    """`SECOND_BRAIN_LEAN=advisory` re-enables the gate without touching any file."""
    home = _home_with_config(tmp_path / "ablation", SHIPPED_CONFIG)
    assert lean_runtime.resolve_lean_eval(home, env={"SECOND_BRAIN_LEAN": "advisory"}) == {
        "mode": "advisory",
        "source": "env",
        "error": None,
    }
    outcome = lean_runtime.decide_lean_runtime(
        home, "driver", "perform the engineering task", env={"SECOND_BRAIN_LEAN": "advisory"}
    )
    assert outcome.mode == "advisory" and outcome.eval_source == "env"
    # The shipped file also enables the opportunity controller, so advisory stays
    # rule-gated here: no rule fires for a bare prompt, so nothing is injected.
    assert outcome.decision == "omit" and outcome.reason == "noop"


def test_pre_v3_live_advisory_setting_still_injects_the_kernel(tmp_path: Path) -> None:
    """The live install's setting (eval = "advisory", no opportunity controller) still works."""
    config = tmp_path / "live-skills.toml"
    config.write_text('[lean]\neval = "advisory"\n', encoding="utf-8")
    home = _home_with_config(tmp_path / "live", config)
    outcome = lean_runtime.decide_lean_runtime(
        home, "driver", "perform the engineering task", env={}
    )
    assert outcome.decision == "inject"
    assert outcome.reason == "advisory" and outcome.eval_source == "file"
    assert outcome.level == "FULL" and outcome.placement == "tail"
    assert outcome.kernel is not None
    assert "LEAN CODE: deliver the smallest" in outcome.kernel


def test_shipping_off_removes_no_kernel_source() -> None:
    """Turning the gate off must not delete the canonical kernel text."""
    text = CANONICAL_LEAN_SKILL.read_text(encoding="utf-8")
    assert lean_runtime.LEAN_KERNEL_HEADING in text
    kernel = lean_runtime.extract_runtime_kernel(text)
    assert kernel is not None and len(kernel) > 0
    for config in (SHIPPED_CONFIG, SEEDED_CONFIG):
        assert (
            lean_runtime.lean_eval_from_skills_toml(config.read_text(encoding="utf-8")) == "off"
        )
