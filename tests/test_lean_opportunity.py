"""Tests for T3.4 Lean Opportunity Controller (Deep Upgrade Plan U1).

Validates:
- Rule table evaluation: REPEAT_READ, SCOPE_EXPANSION, NEW_DEPENDENCY, NEW_ABSTRACTION,
  POST_ACCEPTANCE_WORK, UNRELATED_DIFF, TEST_WEAKENING_RISK.
- Severity mapping: 0 -> NOOP, 1 (except TEST_WEAKENING_RISK) -> NUDGE,
  TEST_WEAKENING_RISK or >= 2 -> FULL.
- Placement: NUDGE/FULL in TAIL slot (never PREFIX).
- Byte-stable frozen NUDGE line.
- Cooldown and gating: 1 NUDGE per task phase, same reason never repeated after emission,
  FULL only emitted on new severity transition.
- Independence of STOP: verify.evaluate_accuracy_gate remains the sole authorizer.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from second_brain import injection_slots, lean_runtime, verify

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_LEAN_SKILL = REPO_ROOT / "skills" / "candidates" / "lean-code" / "SKILL.md"

FROZEN_NUDGE = (
    "LEAN NUDGE: make the minimum sufficient change to meet acceptance; "
    "reuse existing code, avoid new abstractions or dependencies, and stop at acceptance."
)


@pytest.fixture(autouse=True)
def _reset_lean():
    lean_runtime.reset_lean_kernel_cache()
    lean_runtime.reset_lean_cooldown()
    yield
    lean_runtime.reset_lean_kernel_cache()
    lean_runtime.reset_lean_cooldown()


def _seed_lean_skill(home: Path) -> None:
    target_skill = home / "skills" / "candidates" / "lean-code"
    target_skill.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANONICAL_LEAN_SKILL, target_skill / "SKILL.md")

    target_cfg = home / "config" / "skills.toml"
    target_cfg.parent.mkdir(parents=True, exist_ok=True)
    target_cfg.write_text(
        'schema_version = 1\n\n[lean]\neval = "advisory"\nopportunity ='
        " true\n\n[router]\nmax_active = 3\n",
        encoding="utf-8",
    )


def test_noop_when_no_reason(brain_home: Path) -> None:
    """0 reasons -> NOOP level, 0 tokens injected, decision omit."""
    _seed_lean_skill(brain_home)
    outcome = lean_runtime.decide_lean_runtime(brain_home, "driver", "perform task")
    assert outcome.level == "NOOP"
    assert outcome.decision == "omit"
    assert outcome.kernel is None
    assert outcome.kernel_chars == 0
    assert outcome.reasons == ()
    assert outcome.placement == "tail"


def test_nudge_is_byte_stable_and_in_tail(brain_home: Path) -> None:
    """Single reason -> NUDGE (frozen byte-stable line) in TAIL slot, never in
    PREFIX."""
    _seed_lean_skill(brain_home)

    # Trigger REPEAT_READ: same blob read >= 3 times
    read_ledger = [
        {"path": "src/module.py", "blob_sha": "blob-12345"},
        {"path": "src/module.py", "blob_sha": "blob-12345"},
        {"path": "src/module.py", "blob_sha": "blob-12345"},
    ]

    outcome = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "perform task",
        read_ledger=read_ledger,
    )

    assert outcome.level == "NUDGE"
    assert outcome.decision == "inject"
    assert outcome.reasons == ("REPEAT_READ",)
    assert outcome.placement == "tail"

    # Exact byte-stable string from SKILL.md # Nudge
    assert outcome.kernel == FROZEN_NUDGE
    assert outcome.nudge == FROZEN_NUDGE

    # Placement in TAIL slot
    tail = injection_slots.assemble_tail(
        delta_context="[BRAIN_CONTEXT_DELTA v1]",
        lean_content=outcome.kernel,
    )
    assert FROZEN_NUDGE in tail
    assert "[BRAIN_CONTEXT_DELTA v1]" in tail

    # Prefix carries nothing Lean-related
    prefix = injection_slots.assemble_prefix(
        home=brain_home,
        project_id="test-proj",
        role="driver",
    )
    assert FROZEN_NUDGE not in prefix


def test_full_on_test_weakening(brain_home: Path) -> None:
    """TEST_WEAKENING_RISK alone promotes directly to FULL severity in TAIL."""
    _seed_lean_skill(brain_home)

    diff = """diff --git a/tests/test_core.py b/tests/test_core.py
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -10,3 +10,2 @@
 def test_contract():
-    assert verify_signature() is True
+    pass
"""

    outcome = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "perform task",
        diff=diff,
    )

    assert outcome.level == "FULL"
    assert outcome.decision == "inject"
    assert outcome.reasons == ("TEST_WEAKENING_RISK",)
    assert outcome.placement == "tail"
    assert outcome.kernel is not None
    assert "LEAN CODE: deliver the smallest" in outcome.kernel


def test_cooldown_blocks_repeat_reason(brain_home: Path) -> None:
    """Cooldown enforces: same reason never repeated; 1 NUDGE per task phase."""
    _seed_lean_skill(brain_home)

    reads = [
        {"path": "src/module.py", "blob_sha": "blob-12345"},
        {"path": "src/module.py", "blob_sha": "blob-12345"},
        {"path": "src/module.py", "blob_sha": "blob-12345"},
    ]

    # Turn 1: REPEAT_READ triggers NUDGE
    out1 = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "turn 1",
        read_ledger=reads,
        session_id="sess-cd-1",
        phase="phase-1",
    )
    assert out1.level == "NUDGE"
    assert out1.reasons == ("REPEAT_READ",)

    # Turn 2: Same reason in same phase -> suppressed to NOOP
    out2 = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "turn 2",
        read_ledger=reads,
        session_id="sess-cd-1",
        phase="phase-1",
    )
    assert out2.level == "NOOP"
    assert out2.decision == "omit"

    # Turn 3: New reason (NEW_DEPENDENCY) in same phase -> blocked by "1 NUDGE per phase"
    diff_dep = """diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -5,1 +5,2 @@
 dependencies = []
+dependencies = ["foo"]
"""
    out3 = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "turn 3",
        diff=diff_dep,
        session_id="sess-cd-1",
        phase="phase-1",
    )
    assert out3.level == "NOOP"
    assert out3.decision == "omit"

    # Turn 4: Advance to new task phase -> NUDGE allowed again
    out4 = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "turn 4",
        diff=diff_dep,
        session_id="sess-cd-1",
        phase="phase-2",
    )
    assert out4.level == "NUDGE"
    assert out4.decision == "inject"
    assert out4.reasons == ("NEW_DEPENDENCY",)


def test_full_on_two_or_more_reasons(brain_home: Path) -> None:
    """>= 2 distinct reasons trigger FULL severity."""
    _seed_lean_skill(brain_home)

    reads = [
        {"path": "src/module.py", "blob_sha": "blob-1"},
        {"path": "src/module.py", "blob_sha": "blob-1"},
        {"path": "src/module.py", "blob_sha": "blob-1"},
    ]
    diff_dep = """diff --git a/package.json b/package.json
--- a/package.json
+++ b/package.json
@@ -1 +1 @@
+{"new": 1}
"""

    outcome = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "multi reasons",
        read_ledger=reads,
        diff=diff_dep,
    )
    assert outcome.level == "FULL"
    assert set(outcome.reasons) == {"REPEAT_READ", "NEW_DEPENDENCY"}


def test_scope_expansion_rule(brain_home: Path) -> None:
    """Two modified files outside capsule and requirement references trigger scope expansion."""
    _seed_lean_skill(brain_home)

    capsule = {"files_touched": ["src/allowed.py"]}
    reqs = [{"id": "REQ-001", "requirement": "Implement foo", "refs": ["src/req_ref.py"]}]
    diff = """diff --git a/src/outside1.py b/src/outside1.py
--- a/src/outside1.py
+++ b/src/outside1.py
@@ -1 +1 @@
+x
diff --git a/src/outside2.py b/src/outside2.py
--- a/src/outside2.py
+++ b/src/outside2.py
@@ -1 +1 @@
+y
"""

    outcome = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "scope test",
        capsule=capsule,
        requirements=reqs,
        diff=diff,
    )
    assert "SCOPE_EXPANSION" in outcome.reasons


def test_new_abstraction_rule(brain_home: Path) -> None:
    """New module or file >= 80 lines not named in requirements triggers
    NEW_ABSTRACTION."""
    _seed_lean_skill(brain_home)

    new_file_lines = "\n".join(f"+line_{i} = {i}" for i in range(85))
    diff = f"""diff --git a/src/brand_new_module.py b/src/brand_new_module.py
new file mode 100644
--- /dev/null
+++ b/src/brand_new_module.py
@@ -0,0 +1,85 @@
{new_file_lines}
"""
    reqs = [{"id": "REQ-001", "requirement": "Update existing service", "refs": ["src/service.py"]}]

    outcome = lean_runtime.decide_lean_runtime(
        brain_home,
        "driver",
        "new abstraction test",
        requirements=reqs,
        diff=diff,
    )
    assert "NEW_ABSTRACTION" in outcome.reasons


def test_stop_stays_independent() -> None:
    """Lean never emits completion; verify.evaluate_accuracy_gate remains the sole
    authorizer."""
    # Lean runtime exposes no completion emission or authorization primitives
    assert not hasattr(lean_runtime, "emit_completion")
    assert not hasattr(lean_runtime, "authorize_completion")
    assert not hasattr(lean_runtime, "evaluate_accuracy_gate")

    # verify.evaluate_accuracy_gate is the sole authorizer and its contract is intact
    assert callable(verify.evaluate_accuracy_gate)
