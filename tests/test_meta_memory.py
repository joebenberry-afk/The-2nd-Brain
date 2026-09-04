"""Focused T7.2 Meta-Memory, reconsolidation, and strategic forgetting tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from second_brain import db, decisions, reconsolidation, semantic
from second_brain.errors import BrainError


def test_reconsolidation_actions_are_bounded() -> None:
    expected = (
        "strengthen",
        "narrow",
        "update",
        "split",
        "merge",
        "supersede",
        "demote",
        "archive",
    )
    assert reconsolidation.RECONSOLIDATION_ACTIONS == expected


def test_reconsolidation_preserves_evidence(brain_home: Path) -> None:
    """All supporting evidence, source rows, and version snapshots remain intact."""
    sources = [
        {
            "ref": "evidence:core-run",
            "repo_id": "test-repo",
            "path": "src/core.py",
            "symbol": "run_core",
            "commit_sha": "a" * 40,
            "blob_sha": "b" * 40,
            "range_start": 10,
            "range_end": 20,
            "range_sha": "c" * 40,
        }
    ]
    mid = semantic.add_memory(
        brain_home,
        title="Evidence Preservation Invariant",
        body="Critical policy body backed by verifiable repo source.",
        scope="project",
        grade="TESTED",
        sources=sources,
    )
    semantic.curate(brain_home, mid, status="current")
    reconsolidation.apply_heat(brain_home, mid, "HOT")

    # Record activation history
    for _ in range(3):
        reconsolidation.record_activation(brain_home, mid, "correct", kind="used")

    # 1. Evaluate memory
    eval_res = reconsolidation.evaluate_memory(brain_home, mid)
    assert eval_res["action"] == "strengthen"

    # 2. Demote memory
    demote_res = reconsolidation.demote_memory(brain_home, mid, target_heat="COLD")
    assert demote_res["heat"] == "COLD"

    # 3. Propose and apply supersede
    plan = reconsolidation.propose_plan(
        brain_home,
        "supersede",
        mid,
        new_title="Evidence Preservation Invariant v2",
        new_body="Updated critical policy body with preserved evidence.",
        change_note="Bump to v2",
    )
    applied = reconsolidation.apply_plan(brain_home, plan)
    assert applied["status"] == "applied"

    # 4. Revert supersede back to v1
    reverted = reconsolidation.revert_plan(brain_home, applied)
    assert reverted["status"] == "reverted"

    # Verify that throughout demotion, supersede, and reversal:
    # - memory_sources is completely intact
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        source_rows = conn.execute(
            "SELECT * FROM memory_sources WHERE memory_id = ?", (mid,)
        ).fetchall()
        assert len(source_rows) == 1
        assert source_rows[0]["path"] == "src/core.py"
        assert source_rows[0]["symbol"] == "run_core"
        assert source_rows[0]["source_ref"] == "evidence:core-run"

        # - memory_versions retains history
        version_rows = conn.execute(
            "SELECT * FROM memory_versions WHERE memory_id = ?", (mid,)
        ).fetchall()
        assert len(version_rows) >= 1
    finally:
        conn.close()

    # - active memory file on disk exists and contains original body
    show = semantic.show_memory(brain_home, mid)
    assert show["row"]["current_version"] == 1
    assert "Critical policy body backed by verifiable repo source." in show["body"]
    assert Path(show["path"]).is_file()


def test_contradiction_prevents_silent_strengthening(brain_home: Path) -> None:
    """Contradiction signals strictly block strengthening even with high ACT-R activation."""
    mid = semantic.add_memory(
        brain_home,
        title="Cache Expiry Rule",
        body="Cache entries expire after 30 seconds unconditionally.",
        scope="project",
        grade="VERIFIED",
    )
    semantic.curate(brain_home, mid, status="current")
    reconsolidation.apply_heat(brain_home, mid, "HOT")

    # Record 5 positive activations so B > 0 and P_need is near 1.0
    for _ in range(5):
        reconsolidation.record_activation(brain_home, mid, "correct", kind="used")

    # Before contradiction: evaluates to strengthen
    pre_eval = reconsolidation.evaluate_memory(brain_home, mid)
    assert pre_eval["action"] == "strengthen"
    assert pre_eval["b"] > 0
    assert pre_eval["contradiction_count"] == 0

    # Record 1 contradiction
    reconsolidation.record_activation(brain_home, mid, "contradicted")
    row_after = reconsolidation._memory_row(brain_home, mid)
    assert row_after["contradiction_count"] == 1
    assert row_after["heat"] == "COLD"
    assert row_after["status"] == "labile"

    # After contradiction: evaluate_memory MUST NOT strengthen!
    post_eval = reconsolidation.evaluate_memory(brain_home, mid)
    assert post_eval["action"] != "strengthen"
    assert post_eval["action"] in ("narrow", "demote")
    assert post_eval["contradiction_count"] >= 1
    assert "silent strengthening blocked" in post_eval["reason"]

    # Running decay_pass does NOT escalate back to HOT
    changes = reconsolidation.decay_pass(brain_home)
    row_final = reconsolidation._memory_row(brain_home, mid)
    assert row_final["heat"] == "COLD"


def test_supersede_is_reversible(brain_home: Path) -> None:
    """Automatic supersede emits a plan, can be applied, and is completely reversible."""
    mid = semantic.add_memory(
        brain_home,
        title="Database Timeout Policy",
        body="Database connection timeout is 10000ms.",
        scope="project",
        grade="TESTED",
    )
    semantic.curate(brain_home, mid, status="current")

    # 1. Propose plan in SHADOW stage
    plan = reconsolidation.propose_plan(
        brain_home,
        "supersede",
        mid,
        new_title="Database Timeout Policy v2",
        new_body="Database connection timeout is 5000ms with jitter.",
        change_note="Lower timeout for fail-fast recovery",
    )
    assert plan["rollout_stage"] == "SHADOW"
    assert plan["status"] == "planned"
    assert plan["decision_ref"]

    # Verify SHADOW did not mutate the memory
    current_show = semantic.show_memory(brain_home, mid)
    assert current_show["row"]["current_version"] == 1
    assert "Database connection timeout is 10000ms." in current_show["body"]

    # 2. Apply plan
    applied = reconsolidation.apply_plan(brain_home, plan)
    assert applied["status"] == "applied"
    v2_show = semantic.show_memory(brain_home, mid)
    assert v2_show["row"]["current_version"] == 2
    assert "Database connection timeout is 5000ms with jitter." in v2_show["body"]

    # 3. Revert plan
    reverted = reconsolidation.revert_plan(brain_home, applied)
    assert reverted["status"] == "reverted"

    # Verify active memory is restored to version 1
    v1_restored = semantic.show_memory(brain_home, mid)
    assert v1_restored["row"]["current_version"] == 1
    assert v1_restored["row"]["title"] == "Database Timeout Policy"
    assert "Database connection timeout is 10000ms." in v1_restored["body"]

    # Verify history retains both versions
    hist = semantic.history(brain_home, mid)
    versions = {h["version"] for h in hist}
    assert 1 in versions
    assert 2 in versions


def test_hotset_demotion_does_not_delete_memory(brain_home: Path) -> None:
    """Demoting a memory out of the hot set changes heat but never deletes files or rows."""
    mid = semantic.add_memory(
        brain_home,
        title="Hot Set Rule",
        body="Active guidance currently residing in the hot set.",
        scope="project",
        grade="TESTED",
    )
    semantic.curate(brain_home, mid, status="current")
    reconsolidation.apply_heat(brain_home, mid, "HOT")

    row_hot = reconsolidation._memory_row(brain_home, mid)
    assert row_hot["heat"] == "HOT"
    initial_path = Path(brain_home / row_hot["body_path"])
    assert initial_path.is_file()
    initial_body = initial_path.read_text(encoding="utf-8")

    # Demote from HOT to WARM
    demoted_warm = reconsolidation.demote_memory(brain_home, mid, target_heat="WARM")
    assert demoted_warm["heat"] == "WARM"
    assert initial_path.is_file()
    assert initial_path.read_text(encoding="utf-8") == initial_body

    # Demote from WARM to COLD
    demoted_cold = reconsolidation.demote_memory(brain_home, mid, target_heat="COLD")
    assert demoted_cold["heat"] == "COLD"
    assert initial_path.is_file()
    assert initial_path.read_text(encoding="utf-8") == initial_body

    # Accessible via show_memory
    show = semantic.show_memory(brain_home, mid)
    assert show["row"]["memory_id"] == mid
    assert show["row"]["heat"] == "COLD"
    assert "Active guidance currently residing in the hot set." in show["body"]

    # Verify decisions logged for each demotion
    recons_decisions = decisions.list_decisions(brain_home, kind="reconsolidation")
    assert len(recons_decisions) >= 2


def test_protected_memory_cannot_be_demoted(brain_home: Path) -> None:
    """Protected memories (constitution / verified current) reject manual demotion."""
    mid = semantic.add_memory(
        brain_home,
        title="Constitution Core Rule",
        body="Immutable constitutional directive.",
        scope="global",
        grade="VERIFIED",
    )
    semantic.curate(brain_home, mid, status="current")
    with pytest.raises(BrainError, match="protected"):
        reconsolidation.demote_memory(brain_home, mid, target_heat="COLD")
