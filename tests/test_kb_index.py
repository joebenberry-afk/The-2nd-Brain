"""Tests for Brain index: derived SQLite, search, and write operations."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from second_brain.kb import index, projects, records
from second_brain.kb.records import Record, RecordError


def _make_id(name: str) -> str:
    """Generate a valid test record ID from a name."""
    # Pad to 6-32 chars of hex digits
    hex_part = name.encode().hex()[:32]
    hex_part = (hex_part + "0" * 32)[:32]
    return f"mem-{hex_part}"


def _record(**kw: object) -> Record:
    base: dict[str, object] = {
        "id": "mem-abc123def456",
        "title": "Migration ordering",
        "type": "gotcha",
        "project": "p1",
        "status": "current",
        "grade": "TESTED",
        "recorded_at": "2026-08-16T18:12:48+00:00",
        "evidence": ("src/migrations@1a2b3c4d5e6f",),
        "body": "Apply migrations in numeric order.",
    }
    base.update(kw)
    return Record(**base)  # type: ignore[arg-type]


class TestRefresh:
    """Test index refresh: add, update, remove; error reporting."""

    def test_refresh_adds_new_record(self, tmp_path: Path) -> None:
        """Refresh detects a new record."""
        records.save(tmp_path, _record())
        report = index.refresh(tmp_path)
        assert report.added == 1
        assert report.updated == 0
        assert report.removed == 0
        assert report.errors == []

    def test_refresh_updates_changed_record(self, tmp_path: Path) -> None:
        """Refresh detects when a record is modified."""
        rec = _record()
        records.save(tmp_path, rec)
        report = index.refresh(tmp_path)
        assert report.added == 1

        # Modify and re-save (even with same size, sha256 differs)
        modified = records.replace(rec, title="Different title")
        records.save(tmp_path, modified)

        # Refresh detects the change
        report = index.refresh(tmp_path)
        assert report.added == 0
        assert report.updated == 1
        assert report.removed == 0

    def test_refresh_removes_deleted_record(self, tmp_path: Path) -> None:
        """Refresh detects when a record file is deleted."""
        rec = _record()
        path = records.save(tmp_path, rec)
        report = index.refresh(tmp_path)
        assert report.added == 1

        # Delete the file
        path.unlink()
        report = index.refresh(tmp_path)
        assert report.added == 0
        assert report.updated == 0
        assert report.removed == 1

    def test_refresh_reports_invalid_file(self, tmp_path: Path) -> None:
        """Refresh reports unparseable files as errors."""
        records.save(tmp_path, _record())
        records.records_dir(tmp_path).joinpath("bad.md").write_text("no frontmatter")

        report = index.refresh(tmp_path)
        assert report.added == 1
        assert len(report.errors) == 1
        assert "bad.md" in report.errors[0]

    def test_rebuild_deletes_and_refreshes(self, tmp_path: Path) -> None:
        """rebuild deletes the database and refreshes."""
        records.save(tmp_path, _record())
        index.refresh(tmp_path)
        db_path = index.index_path(tmp_path)
        assert db_path.exists()

        # Rebuild
        report = index.rebuild(tmp_path)
        assert report.added == 1
        assert db_path.exists()


class TestSearch:
    """Test full-text search with ranking and filtering."""

    def test_search_empty_query_returns_empty(self, tmp_path: Path) -> None:
        """Search with no valid tokens returns nothing."""
        records.save(tmp_path, _record())
        results = index.search(tmp_path, "the and what", None)
        assert results == []

    def test_search_title_match_ranks_first(self, tmp_path: Path) -> None:
        """A title match ranks higher than body."""
        title_id = _make_id("title")
        body_id = _make_id("body")
        records.save(
            tmp_path,
            _record(
                id=title_id,
                title="Migration tool",
                scope="global",
                project=None,
            ),
        )
        records.save(
            tmp_path,
            _record(
                id=body_id,
                title="Other",
                body="Migration process",
                scope="global",
                project=None,
            ),
        )

        results = index.search(tmp_path, "migration", None)
        assert results[0].record.id == title_id

    def test_search_stopwords_ignored(self, tmp_path: Path) -> None:
        """Common stopwords are excluded from tokens."""
        records.save(
            tmp_path,
            _record(
                id=_make_id("stop"),
                body="the and what which",
                scope="global",
                project=None,
            ),
        )
        report = index.refresh(tmp_path)
        assert report.added == 1

        # Query with only stopwords returns nothing
        results = index.search(tmp_path, "the and", None)
        assert results == []

    def test_search_match_rule_single_token(self, tmp_path: Path) -> None:
        """Query with 1-2 tokens needs 1 match."""
        rec1_id = _make_id("m1single")
        rec2_id = _make_id("m2single")
        records.save(
            tmp_path,
            _record(
                id=rec1_id,
                title="Migration",
                body="content about migrations",
                scope="global",
                project=None,
            ),
        )
        records.save(
            tmp_path,
            _record(
                id=rec2_id,
                title="Other",
                body="unrelated topic",
                scope="global",
                project=None,
            ),
        )

        results = index.search(tmp_path, "migr", None)  # Matches "migration" prefix
        assert len(results) == 1
        assert results[0].record.id == rec1_id

    def test_search_match_rule_multiple_tokens(self, tmp_path: Path) -> None:
        """Query with 3+ tokens needs 2 matches."""
        rec1_id = _make_id("m1multi")
        rec2_id = _make_id("m2multi")
        records.save(
            tmp_path,
            _record(
                id=rec1_id,
                title="Migration tool",
                body="ordering",
                scope="global",
                project=None,
            ),
        )
        records.save(
            tmp_path,
            _record(
                id=rec2_id,
                title="Migration",
                body="other",
                scope="global",
                project=None,
            ),
        )

        results = index.search(tmp_path, "migr tool order", None)
        # rec1 matches migration (migr*), tool, ordering -> 3 matches >= 2, included
        # rec2 matches migration -> 1 match < 2, excluded
        assert len(results) == 1
        assert results[0].record.id == rec1_id

    def test_search_limit_clamped(self, tmp_path: Path) -> None:
        """limit is clamped to 1..10."""
        for i in range(15):
            records.save(
                tmp_path,
                _record(
                    id=_make_id(f"rec{i:02d}"),
                    title=f"Record {i}",
                    body="migration",
                    scope="global",
                    project=None,
                ),
            )

        results = index.search(tmp_path, "migration", None, limit=0)  # clamped to 1
        assert len(results) == 1

        results = index.search(tmp_path, "migration", None, limit=100)  # clamped to 10
        assert len(results) == 10

    def test_search_scope_isolation(self, tmp_path: Path) -> None:
        """Records from other projects are invisible."""
        p1_rec = _record(id=_make_id("scopep1"), project="p1", body="shared content")
        records.save(tmp_path, p1_rec)

        p1 = projects.Project(id="p1", name="Project 1")
        p2 = projects.Project(id="p2", name="Project 2")

        results = index.search(tmp_path, "shared", p1)
        assert len(results) == 1

        results = index.search(tmp_path, "shared", p2)
        assert len(results) == 0

    def test_search_all_projects(self, tmp_path: Path) -> None:
        """all_projects=True shows records from any project."""
        p1_rec = _record(id=_make_id("allp1"), project="p1", body="shared content")
        records.save(tmp_path, p1_rec)

        p2 = projects.Project(id="p2", name="Project 2")
        results = index.search(tmp_path, "shared", p2, all_projects=True)
        assert len(results) == 1

    def test_search_domain_tagged_visible(self, tmp_path: Path) -> None:
        """Domain-tagged records are visible to projects with those domains."""
        # Create project manifest
        proj_dir = tmp_path / "projects" / "p1"
        proj_dir.mkdir(parents=True)
        (proj_dir / "project.toml").write_text('id = "p1"\ndomains = ["ue4ss"]\n')

        # Save a domain-tagged record
        domain_rec = _record(
            id=_make_id("domain"),
            scope="domain",
            project="other",
            domains=("ue4ss",),
            body="shared knowledge",
        )
        records.save(tmp_path, domain_rec)

        p1 = projects.resolve(tmp_path, None, "p1")
        assert p1 is not None
        results = index.search(tmp_path, "shared", p1)
        assert len(results) == 1

    def test_search_active_only_by_default(self, tmp_path: Path) -> None:
        """Default search returns only active records."""
        active_id = _make_id("active")
        superseded_id = _make_id("supd")
        records.save(
            tmp_path,
            _record(
                id=active_id,
                status="current",
                body="content",
                scope="global",
                project=None,
            ),
        )
        records.save(
            tmp_path,
            _record(
                id=superseded_id,
                status="superseded",
                scope="global",
                project=None,
                superseded_by=active_id,
                supersession_kind="supersedes",
                supersession_reason="updated",
                superseded_at="2026-08-20T00:00:00+00:00",
                body="content",
            ),
        )

        results = index.search(tmp_path, "content", None)
        assert len(results) == 1
        assert results[0].record.id == active_id

    def test_search_history_includes_superseded(self, tmp_path: Path) -> None:
        """include_history=True includes superseded records."""
        active_id = _make_id("acthist")
        superseded_id = _make_id("suphist")
        records.save(
            tmp_path,
            _record(
                id=active_id,
                status="current",
                body="content",
                scope="global",
                project=None,
            ),
        )
        records.save(
            tmp_path,
            _record(
                id=superseded_id,
                status="superseded",
                scope="global",
                project=None,
                superseded_by=active_id,
                supersession_kind="supersedes",
                supersession_reason="updated",
                superseded_at="2026-08-20T00:00:00+00:00",
                body="content",
            ),
        )

        results = index.search(tmp_path, "content", None, include_history=True)
        ids = {r.record.id for r in results}
        assert ids == {active_id, superseded_id}

    def test_search_as_of_time(self, tmp_path: Path) -> None:
        """as_of filters records by valid_from/recorded_at and supersession time."""
        # D1 recorded 2026-08-01
        d1_id = _make_id("d1")
        r_id = _make_id("r")
        d1 = _record(
            id=d1_id,
            title="Driver",
            recorded_at="2026-08-01T00:00:00+00:00",
            body="orchestrator",
            scope="global",
            project=None,
        )
        records.save(tmp_path, d1)

        # R corrected D1, recorded 2026-08-16, effective 2026-08-16
        r = _record(
            id=r_id,
            title="Repair",
            recorded_at="2026-08-16T00:00:00+00:00",
            status="current",
            body="orchestrator",
            scope="global",
            project=None,
        )
        records.save(tmp_path, r)

        # Mark D1 as corrected by R
        d1_updated = records.replace(
            d1,
            status="superseded",
            superseded_by=r_id,
            supersession_kind="corrects",
            supersession_reason="fix",
            superseded_at="2026-08-16T00:00:00+00:00",
        )
        records.save(tmp_path, d1_updated)

        # as_of 2026-08-10: should get D1 only (R not yet recorded)
        results = index.search(tmp_path, "orchestrator", None, as_of="2026-08-10T00:00:00+00:00")
        ids = [r.record.id for r in results]
        assert ids == [d1_id]

        # as_of 2026-08-20: should get R only (D1 was superseded before this)
        results = index.search(tmp_path, "orchestrator", None, as_of="2026-08-20T00:00:00+00:00")
        ids = [r.record.id for r in results]
        assert ids == [r_id]

    def test_search_as_of_rejects_future_time(self, tmp_path: Path) -> None:
        """as_of rejects times in the future."""
        records.save(tmp_path, _record(body="test"))
        with pytest.raises(RecordError, match="future"):
            index.search(tmp_path, "test", None, as_of="2099-01-01T00:00:00+00:00")

    def test_search_includes_candidate_by_default(self, tmp_path: Path) -> None:
        """Candidate records are active and included."""
        records.save(
            tmp_path,
            _record(
                id=_make_id("cand"),
                status="candidate",
                body="content",
                scope="global",
                project=None,
            ),
        )
        results = index.search(tmp_path, "content", None)
        assert len(results) == 1
        assert results[0].record.status == "candidate"


class TestRenderHit:
    """Test hit rendering."""

    def test_render_basic(self, tmp_path: Path) -> None:
        """Render a basic hit."""
        rec = _record(id=_make_id("test"), title="Test title", type="fact")
        hit = index.Hit(record=rec, score=1.0, matched=("test",))
        rendered = index.render_hit(hit)
        assert rec.id in rendered
        assert "fact" in rendered
        assert "Test title" in rendered

    def test_render_with_evidence(self, tmp_path: Path) -> None:
        """Render includes first evidence."""
        rec = _record(
            id=_make_id("testev"),
            title="Test",
            evidence=("file@hash1", "file@hash2"),
        )
        hit = index.Hit(record=rec, score=1.0, matched=())
        rendered = index.render_hit(hit)
        assert "file@hash1" in rendered
        assert "file@hash2" not in rendered  # Only first

    def test_render_superseded(self, tmp_path: Path) -> None:
        """Render includes supersession info."""
        old_id = _make_id("old")
        new_id = _make_id("new")
        rec = _record(
            id=old_id,
            status="superseded",
            superseded_by=new_id,
            superseded_at="2026-08-20T12:34:56+00:00",
        )
        hit = index.Hit(record=rec, score=1.0, matched=())
        rendered = index.render_hit(hit)
        assert f"superseded by {new_id}" in rendered
        assert "2026-08-20" in rendered

    def test_render_truncates_long_lines(self, tmp_path: Path) -> None:
        """Render truncates to 240 chars."""
        rec = _record(id=_make_id("long"), title="x" * 300)
        hit = index.Hit(record=rec, score=1.0, matched=())
        rendered = index.render_hit(hit)
        assert len(rendered) <= 240
        assert rendered.endswith("…")


class TestOrchestrationRemovalChain:
    """Test the orchestration-removal chain scenario from the spec."""

    def test_orchestration_removal_chain(self, tmp_path: Path) -> None:
        """D1 -> corrected by R -> superseded by X; as_of filtering."""
        d1_id = _make_id("d1")
        r_id = _make_id("r")
        x_id = _make_id("x")
        l_id = _make_id("l")

        # D1 recorded 2026-08-01
        d1 = records.Record(
            id=d1_id,
            title="D1",
            type="fact",
            scope="project",
            project="p1",
            status="current",
            grade="OBSERVED",
            recorded_at="2026-08-01T00:00:00+00:00",
            body="driver orchestrator dispatch",
        )
        records.save(tmp_path, d1)

        # R recorded 2026-08-16, corrects D1 effective 2026-08-16
        r = records.Record(
            id=r_id,
            title="R",
            type="fact",
            scope="project",
            project="p1",
            status="current",
            grade="TESTED",
            recorded_at="2026-08-16T00:00:00+00:00",
            body="driver orchestrator dispatch",
        )
        records.save(tmp_path, r)

        # Mark D1 as corrected
        d1_corrected = records.replace(
            d1,
            status="superseded",
            superseded_by=r_id,
            supersession_kind="corrects",
            supersession_reason="correction",
            superseded_at="2026-08-16T00:00:00+00:00",
        )
        records.save(tmp_path, d1_corrected)

        # X recorded 2026-09-23, supersedes R effective 2026-09-23
        x = records.Record(
            id=x_id,
            title="X",
            type="fact",
            scope="project",
            project="p1",
            status="current",
            grade="TESTED",
            recorded_at="2026-09-23T00:00:00+00:00",
            body="driver orchestrator dispatch",
        )
        records.save(tmp_path, x)

        # Mark R as superseded by X
        r_superseded = records.replace(
            r,
            status="superseded",
            superseded_by=x_id,
            supersession_kind="supersedes",
            supersession_reason="supersession",
            superseded_at="2026-09-23T00:00:00+00:00",
        )
        records.save(tmp_path, r_superseded)

        # Update X to mention its supersessions
        x_updated = records.replace(x, supersedes=(r_id,))
        records.save(tmp_path, x_updated)

        # L recorded now, superseded by X effective 2026-09-23
        late_note = records.Record(
            id=l_id,
            title="L",
            type="fact",
            scope="project",
            project="p1",
            status="current",
            grade="OBSERVED",
            recorded_at=records.now_iso(),
            body="driver orchestrator dispatch",
        )
        records.save(tmp_path, late_note)

        late_note_superseded = records.replace(
            late_note,
            status="superseded",
            superseded_by=x_id,
            supersession_kind="supersedes",
            supersession_reason="late note superseded",
            superseded_at="2026-09-23T00:00:00+00:00",
        )
        records.save(tmp_path, late_note_superseded)

        p1 = projects.Project(id="p1")

        # Current search -> X only (L's newer timestamp does not win due to earlier effective date)
        results = index.search(tmp_path, "driver orchestrator dispatch", p1)
        ids = [r.record.id for r in results]
        assert ids == [x_id]

        # as_of 2026-08-10 -> D1
        results = index.search(
            tmp_path, "driver orchestrator dispatch", p1, as_of="2026-08-10T00:00:00+00:00"
        )
        ids = [r.record.id for r in results]
        assert ids == [d1_id]

        # as_of 2026-08-20 -> R
        results = index.search(
            tmp_path, "driver orchestrator dispatch", p1, as_of="2026-08-20T00:00:00+00:00"
        )
        ids = [r.record.id for r in results]
        assert ids == [r_id]

        # as_of 2026-09-24 -> X
        results = index.search(
            tmp_path, "driver orchestrator dispatch", p1, as_of="2026-09-24T00:00:00+00:00"
        )
        ids = [r.record.id for r in results]
        assert ids == [x_id]

        # as_of 2026-07-31 -> nothing
        results = index.search(
            tmp_path, "driver orchestrator dispatch", p1, as_of="2026-07-31T00:00:00+00:00"
        )
        assert results == []

        # include_history -> all four
        results = index.search(
            tmp_path,
            "driver orchestrator dispatch",
            p1,
            include_history=True,
            limit=10,
        )
        ids = {r.record.id for r in results}
        assert ids == {d1_id, r_id, x_id, l_id}

        # successor chain
        assert index.successor(tmp_path, d1_id) == x_id
        assert index.successor(tmp_path, r_id) == x_id
        assert index.successor(tmp_path, x_id) == x_id
        assert index.successor(tmp_path, l_id) == x_id


class TestAdd:
    """Test record addition."""

    def test_add_creates_candidate(self, tmp_path: Path) -> None:
        """add creates a candidate record."""
        record = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        assert record.status == "candidate"
        assert record.grade == "OBSERVED"
        assert record.recorded_at != ""

    def test_add_refuses_verified_unattested(self, tmp_path: Path) -> None:
        """add refuses VERIFIED grade."""
        with pytest.raises(RecordError, match="VERIFIED"):
            index.add(
                tmp_path,
                title="Test",
                body="Body",
                type="fact",
                scope="global",
                project=None,
                grade="VERIFIED",
            )

    def test_add_with_evidence_and_domains(self, tmp_path: Path) -> None:
        """add supports all optional fields."""
        record = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="domain",
            project="p1",
            domains=("tag1", "tag2"),
            grade="TESTED",
            evidence=("file@hash",),
            trigger_paths=("path/to/file",),
            trigger_errors=("error pattern",),
            terms=("keyword",),
            valid_from="2026-08-01T00:00:00+00:00",
            private=True,
        )
        assert record.domains == ("tag1", "tag2")
        assert record.evidence == ("file@hash",)
        assert record.private is True


class TestPromote:
    """Test record promotion."""

    def test_promote_candidate_to_current(self, tmp_path: Path) -> None:
        """promote moves candidate to current."""
        candidate = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )

        promoted = index.promote(tmp_path, candidate.id, reason="verified")
        assert promoted.status == "current"
        assert promoted.extra.get("promoted_at") is not None
        assert promoted.extra.get("promotion_reason") == "verified"

    def test_promote_requires_evidence(self, tmp_path: Path) -> None:
        """promote requires evidence."""
        candidate = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        with pytest.raises(RecordError, match="evidence"):
            index.promote(tmp_path, candidate.id, reason="test")

    def test_promote_requires_reason(self, tmp_path: Path) -> None:
        """promote requires non-empty reason."""
        candidate = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )
        with pytest.raises(RecordError, match="reason"):
            index.promote(tmp_path, candidate.id, reason="")

    def test_promote_only_candidate(self, tmp_path: Path) -> None:
        """promote only works on candidate records."""
        current = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )
        index.promote(tmp_path, current.id, reason="test")

        with pytest.raises(RecordError):
            index.promote(tmp_path, current.id, reason="test")


class TestSupersede:
    """Test record supersession."""

    def test_supersede_updates_both_records(self, tmp_path: Path) -> None:
        """supersede marks old as superseded and updates new."""
        old = index.add(
            tmp_path,
            title="Old",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )

        old_rec, new_rec = index.supersede(tmp_path, old.id, by=new.id, reason="update")
        assert old_rec.status == "superseded"
        assert old_rec.superseded_by == new.id
        assert old.id in new_rec.supersedes

    def test_supersede_requires_reason(self, tmp_path: Path) -> None:
        """supersede requires non-empty reason."""
        old = index.add(
            tmp_path,
            title="Old",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        with pytest.raises(RecordError, match="reason"):
            index.supersede(tmp_path, old.id, by=new.id, reason="")

    def test_supersede_rejects_self(self, tmp_path: Path) -> None:
        """Cannot supersede with self."""
        rec = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        with pytest.raises(RecordError, match="itself"):
            index.supersede(tmp_path, rec.id, by=rec.id, reason="test")

    def test_supersede_requires_active_records(self, tmp_path: Path) -> None:
        """Cannot supersede or be superseded with inactive records."""
        old = index.add(
            tmp_path,
            title="Old",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )

        # Retire new
        index.retire(tmp_path, new.id, reason="test")

        with pytest.raises(RecordError, match="inactive"):
            index.supersede(tmp_path, old.id, by=new.id, reason="test")

    def test_supersede_rejects_weaker_grade(self, tmp_path: Path) -> None:
        """Cannot replace TESTED with OBSERVED."""
        old = index.add(
            tmp_path,
            title="Old",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            grade="TESTED",
        )
        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            grade="OBSERVED",
        )
        with pytest.raises(RecordError, match="WEAKER_REPLACEMENT"):
            index.supersede(tmp_path, old.id, by=new.id, reason="test")

    def test_supersede_accepts_unattested_verified_by_tested(self, tmp_path: Path) -> None:
        """TESTED can replace unattested VERIFIED."""
        # Create VERIFIED record manually (add() refuses VERIFIED)
        old_id = _make_id("verified")
        old = _record(
            id=old_id,
            title="Old",
            type="fact",
            scope="global",
            project=None,
            grade="VERIFIED",
            attested=False,
            status="current",
        )
        records.save(tmp_path, old)

        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            grade="TESTED",
        )
        # Should not raise
        old_rec, _new_rec = index.supersede(tmp_path, old.id, by=new.id, reason="test")
        assert old_rec.status == "superseded"

    def test_supersede_rejects_scope_mismatch(self, tmp_path: Path) -> None:
        """Scope rules must be respected."""
        # Global -> local should fail
        old = index.add(
            tmp_path,
            title="Old",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="project",
            project="p1",
        )
        with pytest.raises(RecordError, match="SCOPE_MISMATCH"):
            index.supersede(tmp_path, old.id, by=new.id, reason="test")

    def test_supersede_rejects_future_effective_at(self, tmp_path: Path) -> None:
        """effective_at cannot be in the future."""
        old = index.add(
            tmp_path,
            title="Old",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        with pytest.raises(RecordError, match="future"):
            index.supersede(
                tmp_path,
                old.id,
                by=new.id,
                reason="test",
                effective_at="2099-01-01T00:00:00+00:00",
            )

    def test_supersede_kind_corrects(self, tmp_path: Path) -> None:
        """supersede with kind=corrects works."""
        old = index.add(
            tmp_path,
            title="Old",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        new = index.add(
            tmp_path,
            title="New",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        old_rec, _new_rec = index.supersede(
            tmp_path, old.id, by=new.id, reason="fix", kind="corrects"
        )
        assert old_rec.supersession_kind == "corrects"


class TestRetire:
    """Test record retirement (invalidation)."""

    def test_retire_invalidates_record(self, tmp_path: Path) -> None:
        """retire marks as superseded with invalidates."""
        record = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        retired = index.retire(tmp_path, record.id, reason="no longer valid")
        assert retired.status == "superseded"
        assert retired.supersession_kind == "invalidates"
        assert retired.superseded_by is None

    def test_retire_requires_reason(self, tmp_path: Path) -> None:
        """retire requires non-empty reason."""
        record = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        with pytest.raises(RecordError, match="reason"):
            index.retire(tmp_path, record.id, reason="")

    def test_retire_inactive_fails(self, tmp_path: Path) -> None:
        """Cannot retire an already inactive record."""
        record = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        index.retire(tmp_path, record.id, reason="test")
        with pytest.raises(RecordError, match="inactive"):
            index.retire(tmp_path, record.id, reason="test")


class TestSuccessor:
    """Test following the supersession chain."""

    def test_successor_active_record(self, tmp_path: Path) -> None:
        """successor returns the record id when it's active."""
        record = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        assert index.successor(tmp_path, record.id) == record.id

    def test_successor_follows_chain(self, tmp_path: Path) -> None:
        """successor follows supersession chain."""
        r1 = index.add(
            tmp_path,
            title="R1",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        r2 = index.add(
            tmp_path,
            title="R2",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        index.supersede(tmp_path, r1.id, by=r2.id, reason="test")
        assert index.successor(tmp_path, r1.id) == r2.id

    def test_successor_invalidation_returns_none(self, tmp_path: Path) -> None:
        """successor returns None when chain ends in invalidation."""
        record = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
        )
        index.retire(tmp_path, record.id, reason="test")
        assert index.successor(tmp_path, record.id) is None

    def test_successor_detects_loops(self, tmp_path: Path) -> None:
        """successor raises on circular references."""
        # Manually create a loop (normally prevented by supersede logic)
        loop1_id = _make_id("loop1")
        loop2_id = _make_id("loop2")
        r1 = _record(
            id=loop1_id,
            superseded_by=loop2_id,
            status="superseded",
            supersession_kind="supersedes",
            supersession_reason="loop",
            superseded_at="2026-08-20T00:00:00+00:00",
        )
        r2 = _record(
            id=loop2_id,
            superseded_by=loop1_id,
            status="superseded",
            supersession_kind="supersedes",
            supersession_reason="loop",
            superseded_at="2026-08-20T00:00:00+00:00",
        )
        records.save(tmp_path, r1)
        records.save(tmp_path, r2)
        with pytest.raises(RecordError, match="loop"):
            index.successor(tmp_path, r1.id)


class TestCLI:
    """Test CLI command execution."""

    def test_cli_add_and_query(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI: add -> q finds it."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain.kb.cli",
                "add",
                "Test Record",
                "--home",
                str(tmp_path),
                "--type",
                "fact",
                "--body",
                "Test body",
                "--scope",
                "global",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        record_id = result.stdout.strip()

        # Query for it
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain.kb.cli",
                "q",
                "test",
                "--home",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert record_id in result.stdout

    def test_cli_show_unknown_exits_1(self, tmp_path: Path) -> None:
        """CLI: show unknown record exits 1."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain.kb.cli",
                "show",
                "mem-unknown",
                "--home",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_cli_query_no_match_exits_1(self, tmp_path: Path) -> None:
        """CLI: query with no match exits 1."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain.kb.cli",
                "q",
                "nomatch",
                "--home",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_cli_promote(self, tmp_path: Path) -> None:
        """CLI: promote works."""
        # Add with evidence
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain.kb.cli",
                "add",
                "Test Record",
                "--home",
                str(tmp_path),
                "--type",
                "fact",
                "--body",
                "Test body",
                "--scope",
                "global",
                "--evidence",
                "test@hash",
            ],
            capture_output=True,
            text=True,
        )
        record_id = result.stdout.strip()

        # Promote it
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain.kb.cli",
                "promote",
                record_id,
                "--home",
                str(tmp_path),
                "--reason",
                "verified",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "current" in result.stdout

    def test_cli_index_rebuild(self, tmp_path: Path) -> None:
        """CLI: index --rebuild works."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain.kb.cli",
                "index",
                "--home",
                str(tmp_path),
                "--rebuild",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "added" in result.stdout


class TestPerformance:
    """Smoke test: ensure reasonable performance."""

    def test_performance_1000_records(self, tmp_path: Path) -> None:
        """1000 records refresh + search should complete in ~3s."""
        # Create 1000 records
        start = time.time()
        for i in range(1000):
            records.save(
                tmp_path,
                _record(
                    id=_make_id(f"perf{i:04d}"),
                    title=f"Record {i}",
                    body=f"content {i % 100}",
                ),
            )
        create_time = time.time() - start

        # Refresh
        start = time.time()
        index.refresh(tmp_path)
        refresh_time = time.time() - start

        # Search
        start = time.time()
        _results = index.search(tmp_path, "content", None)
        search_time = time.time() - start

        total_time = refresh_time + search_time

        print(
            f"\nPerformance: create={create_time:.2f}s, refresh={refresh_time:.2f}s, "
            f"search={search_time:.2f}s, total={total_time:.2f}s"
        )

        assert total_time < 3.0, f"Total time {total_time:.2f}s exceeds 3s limit"


def _saved(home: Path, **kw: object) -> Record:
    rec = Record(
        **{  # type: ignore[arg-type]
            "id": records.new_id(),
            "title": "Placeholder",
            "type": "fact",
            "scope": "global",
            "status": "current",
            "grade": "TESTED",
            "recorded_at": "2026-09-01T00:00:00+00:00",
            **kw,
        }
    )
    records.save(home, rec)
    return rec


def test_content_words_are_not_stopwords(tmp_path: Path) -> None:
    assert "second" in index.tokens("second brain wrong right new old")
    rec = _saved(tmp_path, title="Second opinion needed on wrong totals")
    assert [h.record.id for h in index.search(tmp_path, "second wrong", None)] == [rec.id]


def test_trigger_text_counts_as_a_match(tmp_path: Path) -> None:
    rec = _saved(tmp_path, title="Clear the variable", trigger_errors=("SRE module mismatch",))
    hits = index.search(tmp_path, "sre module mismatch", None)
    assert [h.record.id for h in hits] == [rec.id]


def test_fts_follows_edits_incrementally(tmp_path: Path) -> None:
    rec = _saved(tmp_path, title="Alpha widget calibration")
    assert index.search(tmp_path, "alpha widget", None)
    records.save(tmp_path, records.replace(rec, title="Beta gizmo calibration"))
    assert not index.search(tmp_path, "alpha widget", None)
    assert [h.record.id for h in index.search(tmp_path, "beta gizmo", None)] == [rec.id]
    records.record_path(tmp_path, rec.id).unlink()
    assert not index.search(tmp_path, "beta gizmo", None)


def test_supersede_refuses_invalidates_without_partial_writes(tmp_path: Path) -> None:
    old = _saved(tmp_path, title="Old claim")
    new = _saved(tmp_path, title="New claim")
    with pytest.raises(RecordError):
        index.supersede(tmp_path, old.id, by=new.id, reason="r", kind="invalidates")
    assert records.load(tmp_path, new.id).supersedes == ()
    assert records.load(tmp_path, old.id).status == "current"


def test_retire_refuses_a_future_time(tmp_path: Path) -> None:
    rec = _saved(tmp_path, title="Some claim")
    with pytest.raises(RecordError):
        index.retire(tmp_path, rec.id, reason="r", effective_at="2999-01-01T00:00:00+00:00")
    assert records.load(tmp_path, rec.id).status == "current"


def test_incidental_single_word_overlap_is_dropped(tmp_path: Path) -> None:
    target = _saved(tmp_path, title="Migration ordering", body="apply migrations in numeric order")
    for i in range(5):
        _saved(
            tmp_path, title=f"Telemetry trial {i} passes", body=f"run {i} kept the order of events"
        )
    hits = index.search(tmp_path, "migration order", None, limit=10)
    assert [h.record.id for h in hits] == [target.id]


def test_edit_changes_description_never_standing(tmp_path: Path) -> None:
    rec = _saved(tmp_path, title="PYTHONHOME pollution", status="current", grade="TESTED")
    edited = index.edit(
        tmp_path,
        rec.id,
        type="gotcha",
        add_trigger_errors=("SRE module mismatch", "SRE module mismatch"),
        add_evidence=("env-snapshot",),
    )
    assert (edited.type, edited.trigger_errors, edited.evidence) == (
        "gotcha",
        ("SRE module mismatch",),
        ("env-snapshot",),
    )
    assert (edited.status, edited.grade, edited.scope) == ("current", "TESTED", "global")
    assert "edited_at" in edited.extra
    with pytest.raises(RecordError):
        index.edit(tmp_path, rec.id, type="note")
    index.retire(tmp_path, rec.id, reason="done")
    with pytest.raises(RecordError):
        index.edit(tmp_path, rec.id, type="fact")
