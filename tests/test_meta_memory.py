"""Focused T7.2 Meta-Memory, reconsolidation, and strategic forgetting tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from second_brain import db, decisions, reconsolidation, semantic
from second_brain.errors import BrainError


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


def test_leave_unresolved_preserves_evidence_versions_and_lineage(brain_home: Path) -> None:
    parent = semantic.add_memory(
        brain_home,
        "Unresolved rules",
        "Two unresolved rules.",
        sources=[{"ref": "test:original-observation"}],
    )
    split = reconsolidation.propose_plan(
        brain_home,
        "split",
        parent,
        parts=[
            {"title": "First rule", "body": "First unresolved rule."},
            {"title": "Second rule", "body": "Second unresolved rule."},
        ],
    )
    created = reconsolidation.apply_plan(brain_home, split)["applied_result"]["created_memory_ids"]

    def memory_snapshot() -> tuple:
        conn = db.connect(db.db_path(brain_home), readonly=True)
        try:
            rows = tuple(
                tuple(tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                for table in ("memories", "memory_sources", "memory_versions")
            )
        finally:
            conn.close()
        bodies = tuple(
            Path(semantic.show_memory(brain_home, mid)["path"]).read_bytes()
            for mid in (parent, *created)
        )
        return rows, bodies

    before = memory_snapshot()
    plan = reconsolidation.propose_plan(
        brain_home,
        "leave_unresolved",
        created[0],
        change_note="Independent evidence does not yet resolve this rule.",
    )
    applied = reconsolidation.apply_plan(brain_home, plan)
    assert applied["status"] == "applied"
    assert applied["applied_result"]["resolution"] == "unresolved"
    assert memory_snapshot() == before
    reverted = reconsolidation.revert_plan(brain_home, applied)
    assert reverted["status"] == "reverted"
    assert memory_snapshot() == before
    choices = [
        row["chosen"]
        for row in decisions.list_decisions(brain_home, kind="reconsolidation")
        if row["chosen"].get("plan_id") == plan["plan_id"]
    ]
    assert {"applied", "reverted"} <= {choice.get("status") for choice in choices}


def test_contradiction_prevents_silent_strengthening(brain_home: Path) -> None:
    """Contradiction signals strictly block strengthening even with high ACT-R activation."""
    mid = semantic.add_memory(
        brain_home,
        title="Cache Expiry Rule",
        body="Cache entries expire after 30 seconds unconditionally.",
        scope="project",
        grade="TESTED",
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
    reconsolidation.decay_pass(brain_home)
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


def test_archive_plan_mutates_status_and_reverts(brain_home: Path) -> None:
    mid = semantic.add_memory(
        brain_home,
        title="Archive candidate",
        body="Retain this history but exclude it from default retrieval.",
        grade="TESTED",
        sources=[{"ref": "test:archived-observation", "path": "src/original.py"}],
        origin_class="LOCAL_REPO",
        origin_root_sha="a" * 64,
    )
    semantic.curate(brain_home, mid, status="current")
    before = semantic.show_memory(brain_home, mid)
    before_sources = semantic._sources(brain_home, mid)
    plan = reconsolidation.propose_plan(brain_home, "archive", mid)
    applied = reconsolidation.apply_plan(brain_home, plan)
    assert semantic.show_memory(brain_home, mid)["row"]["status"] == "archived"
    assert semantic.list_memories(brain_home, status="current") == []
    archived = semantic.show_memory(brain_home, mid)
    assert archived["path"] == before["path"]
    assert archived["body"].split("---", 2)[-1] == before["body"].split("---", 2)[-1]
    assert semantic._sources(brain_home, mid) == before_sources
    changed_fields = {"status", "updated_at"}
    assert {key: value for key, value in archived["row"].items() if key not in changed_fields} == {
        key: value for key, value in before["row"].items() if key not in changed_fields
    }
    assert [(row["version"], row["body_path"]) for row in semantic.history(brain_home, mid)] == [
        (before["row"]["current_version"], before["row"]["body_path"])
    ]
    assert semantic.search_memories(brain_home, "history") == []
    assert [
        row["memory_id"]
        for row in semantic.search_memories(brain_home, "history", include_history=True)
    ] == [mid]

    reverted = reconsolidation.revert_plan(brain_home, applied)
    assert reverted["status"] == "reverted"
    assert semantic.show_memory(brain_home, mid)["row"]["status"] == "current"
    restored = semantic.show_memory(brain_home, mid)
    assert restored["body"] == before["body"]
    assert semantic._sources(brain_home, mid) == before_sources
    assert {key: value for key, value in restored["row"].items() if key != "updated_at"} == {
        key: value for key, value in before["row"].items() if key != "updated_at"
    }


@pytest.mark.parametrize("action", ["strengthen", "narrow", "update", "split", "merge"])
def test_incomplete_action_refuses_without_mutation(brain_home: Path, action: str) -> None:
    mid = semantic.add_memory(brain_home, title="Action coverage", body="Original body.")
    before = semantic.show_memory(brain_home, mid)
    with pytest.raises(BrainError):
        reconsolidation.propose_plan(brain_home, action, mid)
    assert semantic.show_memory(brain_home, mid) == before


@pytest.mark.parametrize("action", ["narrow", "update"])
def test_content_plan_restores_version_and_retains_new_evidence(
    brain_home: Path, action: str
) -> None:
    mid = semantic.add_memory(
        brain_home,
        "Cache rule",
        "Cache every response.",
        sources=[{"ref": "test:old"}],
        origin_class="LOCAL_REPO",
        origin_root_sha="a" * 64,
    )
    before = semantic.show_memory(brain_home, mid)
    plan = reconsolidation.propose_plan(
        brain_home,
        action,
        mid,
        new_body="Cache only successful responses.",
        new_sources=[{"ref": "test:successful-only"}],
    )
    applied = reconsolidation.apply_plan(brain_home, plan)
    current = semantic.show_memory(brain_home, mid)
    assert current["row"]["current_version"] > before["row"]["current_version"]
    assert "Cache only successful responses." in current["body"]
    assert current["row"]["origin_root_sha"] == "a" * 64
    assert current["row"]["authority_ceiling"] == "advisory"
    reverted = reconsolidation.revert_plan(brain_home, applied)
    assert semantic.show_memory(brain_home, mid)["body"] == before["body"]
    assert {source["ref"] for source in semantic._sources(brain_home, mid)} == {
        "test:old",
        "test:successful-only",
    }
    assert {version["version"] for version in semantic.history(brain_home, mid)} == {1, 2}
    assert reverted["reverted_result"]["states"][mid]["origin_root_sha"] == "a" * 64
    second_plan = reconsolidation.propose_plan(
        brain_home,
        action,
        mid,
        new_body="Cache only successful and verified responses.",
    )
    second_applied = reconsolidation.apply_plan(brain_home, second_plan)
    assert second_applied["applied_result"]["new_version"] == 3
    history = semantic.history(brain_home, mid)
    assert {version["version"] for version in history} == {1, 2, 3}
    version_two = next(version for version in history if version["version"] == 2)
    assert "Cache only successful responses." in Path(
        brain_home / version_two["body_path"]
    ).read_text(encoding="utf-8")


def test_strengthen_restores_storage_not_intrinsic_strength_or_evidence(brain_home: Path) -> None:
    mid = semantic.add_memory(brain_home, "Supported fact", "A supported claim.")
    before = semantic.show_memory(brain_home, mid)["row"]
    plan = reconsolidation.propose_plan(
        brain_home, "strengthen", mid, new_sources=[{"ref": "test:new-proof", "kind": "test"}]
    )
    applied = reconsolidation.apply_plan(brain_home, plan)
    strengthened = semantic.show_memory(brain_home, mid)["row"]
    assert strengthened["storage_strength"] == pytest.approx(before["storage_strength"] + 0.1)
    for key in ("strength", "stability", "evidence_grade", "origin_class", "authority_ceiling"):
        assert strengthened[key] == before[key]
    reconsolidation.revert_plan(brain_home, applied)
    restored = semantic.show_memory(brain_home, mid)["row"]
    assert restored["storage_strength"] == before["storage_strength"]
    assert restored["strength"] == before["strength"]
    assert semantic._sources(brain_home, mid)[0]["ref"] == "test:new-proof"
    with pytest.raises(BrainError, match="Stale"):
        reconsolidation.revert_plan(brain_home, applied)
    reconsolidation.record_activation(brain_home, mid, "contradicted")
    with pytest.raises(BrainError, match="Contradictions"):
        reconsolidation.propose_plan(
            brain_home, "strengthen", mid, new_sources=[{"ref": "test:another-proof"}]
        )


def test_split_preserves_lineage_and_archives_outputs_on_rollback(brain_home: Path) -> None:
    mid = semantic.add_memory(
        brain_home,
        "Combined rule",
        "Read safely. Write safely.",
        grade="TESTED",
        sources=[{"ref": "test:safety", "range_sha": "c" * 64}],
        origin_class="LOCAL_REPO",
        origin_root_sha="a" * 64,
    )
    semantic.curate(brain_home, mid, status="current", authority_ceiling="advisory")
    before = semantic.show_memory(brain_home, mid)
    plan = reconsolidation.propose_plan(
        brain_home,
        "split",
        mid,
        parts=[
            {"title": "Read rule", "body": "Read safely."},
            {"title": "Write rule", "body": "Write safely."},
        ],
    )
    applied = reconsolidation.apply_plan(brain_home, plan)
    outputs = applied["applied_result"]["created_memory_ids"]
    assert semantic.show_memory(brain_home, mid)["row"]["status"] == "superseded"
    bodies = set()
    for out in outputs:
        row = semantic._row(brain_home, out)
        assert row is not None
        bodies.add(semantic._body_text(brain_home, row).strip())
    assert bodies == {"Read safely.", "Write safely."}
    for out in outputs:
        row = semantic.show_memory(brain_home, out)["row"]
        assert (row["origin_class"], row["origin_root_sha"], row["authority_ceiling"]) == (
            "LOCAL_REPO",
            "a" * 64,
            "advisory",
        )
        refs = {source["ref"]: source for source in semantic._sources(brain_home, out)}
        assert refs["test:safety"]["range_sha"] == "c" * 64
        assert f"memory:{mid}@v1" in refs
    reconsolidation.revert_plan(brain_home, applied)
    assert semantic.show_memory(brain_home, mid)["body"] == before["body"]
    assert semantic.show_memory(brain_home, mid)["row"]["status"] == "current"
    for out in outputs:
        assert semantic.show_memory(brain_home, out)["row"]["status"] == "archived"
        assert Path(semantic.show_memory(brain_home, out)["path"]).is_file()


def test_merge_inherits_weakest_authority_and_guards_every_output(brain_home: Path) -> None:
    trusted = semantic.add_memory(
        brain_home,
        "Local claim",
        "Local fact.",
        grade="TESTED",
        origin_class="LOCAL_REPO",
        origin_root_sha="a" * 64,
        sources=[{"ref": "test:local"}],
    )
    foreign = semantic.add_memory(
        brain_home,
        "Foreign claim",
        "External fact.",
        origin_class="EXTERNAL_WEB",
        origin_root_sha="b" * 64,
        sources=[{"ref": "https://example.com/fact"}],
    )
    plan = reconsolidation.propose_plan(
        brain_home,
        "merge",
        trusted,
        merge_memory_ids=[foreign],
        new_title="Combined claim",
        new_body="Local and external facts.",
    )
    applied = reconsolidation.apply_plan(brain_home, plan)
    merged = applied["applied_result"]["created_memory_ids"][0]
    row = semantic.show_memory(brain_home, merged)["row"]
    # Neither input carries issuer-granted authority, so the derived memory
    # cannot inherit project authority: it stays advisory. With equal ceilings
    # the reduction keeps the primary input's origin metadata.
    assert row["authority_ceiling"] == "advisory"
    assert (row["origin_class"], row["origin_root_sha"]) == ("LOCAL_REPO", "a" * 64)
    assert row["evidence_grade"] == "OBSERVED"
    assert {source["ref"] for source in semantic._sources(brain_home, merged)} == {
        "test:local",
        "https://example.com/fact",
        f"memory:{trusted}@v1",
        f"memory:{foreign}@v1",
    }
    reconsolidation.revert_plan(brain_home, applied)
    assert semantic.show_memory(brain_home, trusted)["row"]["status"] == "candidate"
    assert semantic.show_memory(brain_home, foreign)["row"]["status"] == "candidate"
    assert semantic.show_memory(brain_home, merged)["row"]["status"] == "archived"
    next_plan = reconsolidation.propose_plan(
        brain_home,
        "merge",
        trusted,
        merge_memory_ids=[foreign],
        new_body="Another merge.",
    )
    next_applied = reconsolidation.apply_plan(brain_home, next_plan)
    next_merged = next_applied["applied_result"]["created_memory_ids"][0]
    semantic.supersede(
        brain_home, next_merged, new_body="Later edit.", change_note="Independent edit"
    )
    with pytest.raises(BrainError, match="Stale"):
        reconsolidation.revert_plan(brain_home, next_applied)
    assert semantic.show_memory(brain_home, trusted)["row"]["status"] == "superseded"
    assert "Later edit." in semantic.show_memory(brain_home, next_merged)["body"]


@pytest.mark.parametrize("action", ["update", "leave_unresolved"])
def test_plan_cannot_apply_after_evidence_or_version_changes(brain_home: Path, action: str) -> None:
    mid = semantic.add_memory(brain_home, "Mutable fact", "Before.")
    plan = reconsolidation.propose_plan(
        brain_home, action, mid, new_body="Proposed." if action == "update" else None
    )
    semantic.curate(brain_home, mid, sources=[{"ref": "test:intervening"}], verify=False)
    with pytest.raises(BrainError, match="Stale"):
        reconsolidation.apply_plan(brain_home, plan)
    assert semantic.show_memory(brain_home, mid)["row"]["current_version"] == 1


def test_split_failure_restores_input_and_retains_partial_output_as_history(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mid = semantic.add_memory(
        brain_home, "Two rules", "First and second.", sources=[{"ref": "test:original"}]
    )
    plan = reconsolidation.propose_plan(
        brain_home,
        "split",
        mid,
        parts=[
            {"title": "First", "body": "First rule."},
            {"title": "Second", "body": "Second rule."},
        ],
    )
    original_add = semantic.add_memory
    created = []

    def fail_second(*args, **kwargs):
        if created:
            raise BrainError("Storage unavailable")
        output = original_add(*args, **kwargs)
        created.append(output)
        return output

    monkeypatch.setattr(semantic, "add_memory", fail_second)
    with pytest.raises(BrainError, match="Storage unavailable"):
        reconsolidation.apply_plan(brain_home, plan)
    assert semantic.show_memory(brain_home, mid)["row"]["status"] == "candidate"
    assert semantic.show_memory(brain_home, created[0])["row"]["status"] == "archived"
    assert "test:original" in {
        source["ref"] for source in semantic._sources(brain_home, created[0])
    }


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
    """Protected memories (constitution title / legacy verified current) reject manual
    demotion."""
    mid = semantic.add_memory(
        brain_home,
        title="Constitution Core Rule",
        body="Immutable constitutional directive.",
        scope="global",
        grade="TESTED",
    )
    semantic.curate(brain_home, mid, status="current")
    with pytest.raises(BrainError, match="protected"):
        reconsolidation.demote_memory(brain_home, mid, target_heat="COLD")
