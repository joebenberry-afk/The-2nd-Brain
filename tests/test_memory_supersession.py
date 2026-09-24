"""Tests for memory supersession (V3 MEM-03)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from second_brain import autoinject, backup, cli, db, semantic


@pytest.fixture
def fixture_home(brain_home):
    """Create fixture memories with supersession chain (see spec §6)."""
    home = brain_home
    # D1: "Orchestrator must delegate all work" (created 2026-08-01)
    d1 = semantic.add_memory(
        home,
        "Orchestrator must delegate all work",
        "The orchestrator must delegate all work to workers."
        "Topic: driver orchestrator execute delegate dispatch.",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, d1, status="current")
    # Backdate created_at
    conn = db.connect(db.db_path(home))
    conn.execute(
        "UPDATE memories SET created_at = '2026-08-01T00:00:00+00:00' WHERE memory_id = ?",
        (d1,),
    )
    conn.commit()
    conn.close()

    # R: "Driver may execute trivial deterministic work" (created 2026-08-16)
    r = semantic.add_memory(
        home,
        "Driver may execute trivial deterministic work",
        "The driver may execute trivial deterministic work."
        "Topic: driver orchestrator execute delegate dispatch.",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, r, status="current")
    conn = db.connect(db.db_path(home))
    conn.execute(
        "UPDATE memories SET created_at = '2026-08-16T00:00:00+00:00' WHERE memory_id = ?",
        (r,),
    )
    conn.commit()
    conn.close()

    # X: "Brain has no orchestrator..." (created 2026-09-23)
    x = semantic.add_memory(
        home,
        "Brain has no orchestrator; the native harness owns dispatch",
        "The Brain has no orchestrator; the native harness owns dispatch."
        "Topic: driver orchestrator execute delegate dispatch.",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, x, status="current")
    conn = db.connect(db.db_path(home))
    conn.execute(
        "UPDATE memories SET created_at = '2026-09-23T00:00:00+00:00' WHERE memory_id = ?",
        (x,),
    )
    conn.commit()
    conn.close()

    # late_mem: "Driver must never execute commands itself" (created NOW, newest)
    late_mem = semantic.add_memory(
        home,
        "Driver must never execute commands itself",
        "The driver must never execute commands itself."
        "Topic: driver orchestrator execute delegate dispatch.",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, late_mem, status="current")

    # Apply supersessions
    # R corrects D1
    semantic.retire_memory(
        home,
        d1,
        by=r,
        kind="corrects",
        reason="amendment 31",
        effective_at="2026-08-16T00:00:00+00:00",
    )

    # X supersedes R
    semantic.retire_memory(
        home,
        r,
        by=x,
        reason="orchestrator removal gate",
        effective_at="2026-09-23T00:00:00+00:00",
    )

    # X supersedes late_mem
    semantic.retire_memory(
        home,
        late_mem,
        by=x,
        reason="late import of pre-removal note",
        effective_at="2026-09-23T00:00:00+00:00",
    )

    # Rebuild the index for search tests
    semantic.reindex_all(home)

    return home, d1, r, x, late_mem


def test_current_search_excludes_superseded(fixture_home):
    """Assertion 1: Current search returns X and none of D1/R/L."""
    home, d1, r, x, late_mem = fixture_home
    rows = semantic.search_memories(
        home, "driver orchestrator execute delegate dispatch", include_history=False
    )
    found_ids = {row["memory_id"] for row in rows}
    assert x in found_ids, f"X should be in results, got {found_ids}"
    assert d1 not in found_ids, "D1 should not be in results (superseded)"
    assert r not in found_ids, "R should not be in results (superseded)"
    assert late_mem not in found_ids, "L should not be in results (superseded)"


def test_as_of_search(fixture_home):
    """Assertion 2: as_of filtering at different timestamps."""
    home, d1, r, x, _ = fixture_home

    # 2026-08-10: should return D1 only
    rows = semantic.search_memories(
        home,
        "driver orchestrator execute delegate dispatch",
        include_history=True,
        as_of="2026-08-10T00:00:00+00:00",
        top_k=100,
    )
    found_ids = {row["memory_id"] for row in rows}
    assert found_ids == {d1}, f"Expected only D1, got {found_ids}"

    # 2026-08-20: should return R only (with superseded_by == X, kind supersedes)
    rows = semantic.search_memories(
        home,
        "driver orchestrator execute delegate dispatch",
        include_history=True,
        as_of="2026-08-20T00:00:00+00:00",
        top_k=100,
    )
    found_ids = {row["memory_id"] for row in rows}
    assert found_ids == {r}, f"Expected only R, got {found_ids}"
    r_row = next(row for row in rows if row["memory_id"] == r)
    assert r_row.get("superseded_by") == x, "R should have superseded_by == X"
    assert r_row.get("supersession_kind") == "supersedes"

    # 2026-09-24: should return X only
    rows = semantic.search_memories(
        home,
        "driver orchestrator execute delegate dispatch",
        include_history=True,
        as_of="2026-09-24T00:00:00+00:00",
        top_k=100,
    )
    found_ids = {row["memory_id"] for row in rows}
    assert found_ids == {x}, f"Expected only X, got {found_ids}"

    # Before D1's created_at: should return none
    rows = semantic.search_memories(
        home,
        "driver orchestrator execute delegate dispatch",
        include_history=True,
        as_of="2026-07-31T00:00:00+00:00",
        top_k=100,
    )
    found_ids = {row["memory_id"] for row in rows}
    assert found_ids == set(), f"Expected empty, got {found_ids}"


def test_include_history_with_links(fixture_home):
    """Assertion 3: include_history returns all with supersession info."""
    home, d1, r, x, late_mem = fixture_home
    rows = semantic.search_memories(
        home, "driver orchestrator execute delegate dispatch", include_history=True, top_k=100
    )
    found_ids = {row["memory_id"] for row in rows}
    assert found_ids == {d1, r, x, late_mem}, f"Expected all four, got {found_ids}"

    # D1 carries superseded_by == R, supersession_kind == "corrects"
    d1_row = next(row for row in rows if row["memory_id"] == d1)
    assert d1_row.get("superseded_by") == r
    assert d1_row.get("supersession_kind") == "corrects"


def test_current_successor(fixture_home):
    """Assertion 4: current_successor follows the chain."""
    home, d1, r, x, _ = fixture_home
    assert semantic.current_successor(home, d1) == x, "D1 chain should end at X"
    assert semantic.current_successor(home, r) == x, "R chain should end at X"
    assert semantic.current_successor(home, x) == x, "X is current, returns self"


def test_canonical_file_status(fixture_home):
    """Assertion 5: Canonical file of R has status: superseded."""
    home, _, r, _, _ = fixture_home
    m = semantic.show_memory(home, r)
    body = m["body"]
    assert "status: superseded" in body, f"R's file should have status: superseded, got:\n{body}"


def test_refusals(fixture_home):
    """Assertion 6: Various refusals with BrainError."""
    home, d1, r, x, _ = fixture_home

    # Retire an already superseded record
    with pytest.raises(semantic.BrainError) as exc:
        semantic.retire_memory(home, d1, reason="test")
    assert "already historical" in str(exc.value)

    # X->R cycle attempt (retire X by R, but R is superseded)
    with pytest.raises(semantic.BrainError) as exc:
        semantic.retire_memory(home, x, by=r, reason="cycle")
    assert "not active" in str(exc.value)

    # by == memory_id
    with pytest.raises(semantic.BrainError) as exc:
        semantic.retire_memory(home, x, by=x, reason="test")
    assert "favor of itself" in str(exc.value)

    # invalidates with by
    with pytest.raises(semantic.BrainError) as exc:
        new_mem = semantic.add_memory(
            home, "test", "test", scope="project", project_id="proj-a", grade="TESTED"
        )
        semantic.curate(home, new_mem, status="current")
        semantic.retire_memory(home, new_mem, by=x, kind="invalidates", reason="test")
    assert "invalidates" in str(exc.value) and "requires" in str(exc.value)

    # supersedes without by
    with pytest.raises(semantic.BrainError) as exc:
        new_mem = semantic.add_memory(
            home, "test2", "test2", scope="project", project_id="proj-a", grade="TESTED"
        )
        semantic.curate(home, new_mem, status="current")
        semantic.retire_memory(home, new_mem, kind="supersedes", reason="test")
    assert "requires" in str(exc.value)

    # future effective_at
    with pytest.raises(semantic.BrainError) as exc:
        new_mem = semantic.add_memory(
            home, "test3", "test3", scope="project", project_id="proj-a", grade="TESTED"
        )
        semantic.curate(home, new_mem, status="current")
        # Artificially create a time 1 hour in the future
        future_dt = datetime.now(UTC)
        future_dt = future_dt.replace(hour=future_dt.hour + 1)
        semantic.retire_memory(home, new_mem, reason="test", effective_at=future_dt.isoformat())
    assert "cannot be in the future" in str(exc.value)

    # Unknown ids
    with pytest.raises(semantic.BrainError) as exc:
        semantic.retire_memory(home, "unknown_id", reason="test")
    assert "Unknown memory" in str(exc.value)

    # Empty reason
    with pytest.raises(semantic.BrainError) as exc:
        new_mem = semantic.add_memory(
            home, "test4", "test4", scope="project", project_id="proj-a", grade="TESTED"
        )
        semantic.curate(home, new_mem, status="current")
        semantic.retire_memory(home, new_mem, reason="")
    assert "non-empty string" in str(exc.value)

    # Replacement graded OBSERVED over a TESTED record (WEAKER_REPLACEMENT)
    weaker = semantic.add_memory(
        home,
        "weaker",
        "weaker",
        scope="project",
        project_id="proj-a",
        grade="OBSERVED",
    )
    semantic.curate(home, weaker, status="current")
    tested = semantic.add_memory(
        home,
        "tested",
        "tested",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, tested, status="current")
    with pytest.raises(semantic.BrainError) as exc:
        semantic.retire_memory(home, tested, by=weaker, reason="test")
    assert "WEAKER_REPLACEMENT" in str(exc.value)

    # Replacement in project proj-b for a proj-a record (SCOPE_MISMATCH)
    proj_b_mem = semantic.add_memory(
        home,
        "proj-b mem",
        "proj-b mem",
        scope="project",
        project_id="proj-b",
        grade="TESTED",
    )
    semantic.curate(home, proj_b_mem, status="current")
    proj_a_mem = semantic.add_memory(
        home,
        "proj-a mem",
        "proj-a mem",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, proj_a_mem, status="current")
    with pytest.raises(semantic.BrainError) as exc:
        semantic.retire_memory(home, proj_a_mem, by=proj_b_mem, reason="test")
    assert "SCOPE_MISMATCH" in str(exc.value)

    # REJECTED replacement
    rejected = semantic.add_memory(
        home,
        "rejected",
        "rejected",
        scope="project",
        project_id="proj-a",
        grade="REJECTED",
    )
    semantic.curate(home, rejected, status="current")
    good = semantic.add_memory(
        home,
        "good",
        "good",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, good, status="current")
    with pytest.raises(semantic.BrainError) as exc:
        semantic.retire_memory(home, good, by=rejected, reason="test")
    assert "REJECTED" in str(exc.value)


def test_invalidation(fixture_home):
    """Assertion 7: Invalidation creates link with new_memory_id=None."""
    home, _, _, _, _ = fixture_home
    m = semantic.add_memory(
        home,
        "measured wrong",
        "measured wrong",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, m, status="current")

    link = semantic.retire_memory(home, m, reason="measured wrong")
    assert link.get("kind") == "invalidates"
    assert link.get("new_memory_id") is None
    # M excluded from current search
    rows = semantic.search_memories(home, "measured wrong", include_history=False)
    found_ids = {row["memory_id"] for row in rows}
    assert m not in found_ids


def test_autoinject_excludes_superseded(fixture_home):
    """Assertion 8: AutoInject never delivers superseded record."""
    home, _, r, x, _ = fixture_home
    # R is superseded, so it should not be in selected_ids
    lifecycle = autoinject.BrainLifecycle(home)
    decision = lifecycle.prepare_injection(
        "driver orchestrator execute delegate dispatch",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="s1",
        branch_id="main",
    )
    assert r not in decision.selected_ids, "R should not be selected (it's superseded)"
    assert x in decision.selected_ids, "X should be selected (it's current)"


def test_migration(brain_home):
    """Assertion 9: Migration creates memory_supersessions; backup/restore works."""
    home = brain_home
    dbfile = db.db_path(home)
    db.migrate(dbfile)

    # Check table exists
    conn = db.connect(dbfile)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_supersessions'"
    )
    assert cursor.fetchone() is not None, "memory_supersessions table should exist"
    conn.close()

    # Second migrate should apply nothing (idempotent)
    db.migrate(dbfile)

    # Create a supersession link, backup, restore
    m1 = semantic.add_memory(home, "m1", "m1", scope="project", project_id="proj-a", grade="TESTED")
    semantic.curate(home, m1, status="current")
    m2 = semantic.add_memory(home, "m2", "m2", scope="project", project_id="proj-a", grade="TESTED")
    semantic.curate(home, m2, status="current")

    semantic.retire_memory(home, m1, by=m2, reason="test")

    # Backup
    backup_dir = backup.create_backup(home)
    assert backup_dir.exists()

    # Restore to fresh home
    fresh_home = Path(home).parent / "fresh_home"
    fresh_home.mkdir(exist_ok=True)
    backup.restore_backup(fresh_home, backup_dir, force=True)

    # Check link survived
    link = semantic.supersession_of(fresh_home, m1)
    assert link is not None
    assert link.get("new_memory_id") == m2


def test_cli_retire(fixture_home, capsys):
    """Assertion 10: CLI smoke test for retire and search --as-of."""
    home, _, r, x, _ = fixture_home

    # Create a new memory for the CLI test (fixture's late_mem is already retired)
    cli_test_mem = semantic.add_memory(
        home,
        "CLI test memory",
        "This memory is for testing the CLI retire command.",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, cli_test_mem, status="current")

    # Test retire command
    result = cli.main(
        [
            "--home",
            str(home),
            "memory",
            "retire",
            cli_test_mem,
            "--by",
            x,
            "--kind",
            "supersedes",
            "--reason",
            "cli test",
        ]
    )
    assert result == 0
    captured = capsys.readouterr()
    assert "retired" in captured.out

    # Test search --as-of
    result = cli.main(
        [
            "--home",
            str(home),
            "memory",
            "search",
            "driver",
            "--as-of",
            "2026-08-20T00:00:00+00:00",
        ]
    )
    assert result == 0
    captured = capsys.readouterr()
    assert r in captured.out  # R should be in output at this as-of


def test_supersession_of(fixture_home):
    """Test supersession_of returns correct link."""
    home, d1, r, _, _ = fixture_home
    link = semantic.supersession_of(home, d1)
    assert link is not None
    assert link.get("old_memory_id") == d1
    assert link.get("new_memory_id") == r
    assert link.get("kind") == "corrects"
    assert link.get("reason") == "amendment 31"


def test_current_successor_invalidate(brain_home):
    """Test current_successor with invalidation."""
    home = brain_home
    m = semantic.add_memory(
        home, "invalid", "invalid", scope="project", project_id="proj-a", grade="TESTED"
    )
    semantic.curate(home, m, status="current")

    semantic.retire_memory(home, m, reason="invalidated")
    result = semantic.current_successor(home, m)
    assert result is None, "Invalidated record should return None"


def test_authority_uses_effective_grade(brain_home):
    """A legacy unattested VERIFIED claim is effective TESTED: a TESTED record may
    replace it, and it never counts as stronger than TESTED."""
    home = brain_home
    legacy = semantic.add_memory(
        home,
        "Legacy claim",
        "legacy claim body",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, legacy, status="current")
    conn = db.connect(db.db_path(home))
    conn.execute("UPDATE memories SET evidence_grade = 'VERIFIED' WHERE memory_id = ?", (legacy,))
    conn.commit()
    conn.close()
    assert semantic.effective_evidence_grade(semantic._row(home, legacy) or {}) == "TESTED"

    replacement = semantic.add_memory(
        home,
        "Current claim",
        "current claim body",
        scope="project",
        project_id="proj-a",
        grade="TESTED",
    )
    semantic.curate(home, replacement, status="current")
    link = semantic.retire_memory(home, legacy, by=replacement, reason="removal gate")
    assert link["new_memory_id"] == replacement
    assert (semantic._row(home, legacy) or {})["status"] == "superseded"
