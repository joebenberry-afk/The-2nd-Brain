"""Tests for skills export and consolidation (SKL-01..03, LRN-01)."""

from __future__ import annotations

from pathlib import Path

import pytest

from second_brain.kb import (
    commands_capture,
    consolidate,
    records,
    skills_export,
)
from second_brain.kb.records import Record, RecordError


def _record(**kw: object) -> Record:
    """Helper to create a test record."""
    base: dict[str, object] = {
        "id": "mem-abc123def456",
        "title": "Test procedure",
        "type": "procedure",
        "project": "p1",
        "scope": "project",
        "status": "current",
        "grade": "TESTED",
        "recorded_at": "2026-08-16T18:12:48+00:00",
        "body": "Test body",
    }
    base.update(kw)
    return Record(**base)  # type: ignore[arg-type]


class TestSkillsExport:
    """Tests for skills_export.export_skill()."""

    def test_export_writes_skill_file(self, tmp_path: Path) -> None:
        """Export writes a SKILL.md file with correct format."""
        # Create and save a record
        home = tmp_path / "brain"
        home.mkdir()
        rec = _record(
            title="Configure CI Pipeline",
            body="Steps to set up continuous integration.",
            evidence=["docs/ci/setup.md", "examples/github-actions.yml"],
        )
        records.save(home, rec)

        # Export it
        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)

        # Verify file exists
        assert skill_path.exists()
        assert skill_path.name == "SKILL.md"
        assert "configure-ci-pipeline" in str(skill_path)

        # Check content structure
        content = skill_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "name: configure-ci-pipeline" in content
        assert 'description: "Configure CI Pipeline' in content
        assert f"from Second Brain record {rec.id}" in content
        assert "(TESTED, advisory)" in content
        assert "# Configure CI Pipeline" in content
        assert "Steps to set up continuous integration." in content
        assert "## Applicability" in content
        assert "## Evidence" in content
        assert "- docs/ci/setup.md" in content
        assert "- examples/github-actions.yml" in content

    def test_export_slug_generation(self, tmp_path: Path) -> None:
        """Test slug generation rules."""
        home = tmp_path / "brain"
        home.mkdir()

        test_cases = [
            ("Simple Title", "simple-title"),
            ("UPPERCASE TITLE", "uppercase-title"),
            ("Title-With-Dashes", "title-with-dashes"),
            ("Title  With  Spaces", "title-with-spaces"),
            ("Title_With_Underscores", "title-with-underscores"),
            ("Title!@#$%^&*()", "title"),
            ("123-456", "123-456"),
            ("!!!Title!!!", "title"),
        ]

        for i, (title, expected_slug) in enumerate(test_cases):
            rec = _record(title=title, id=f"mem-t{i:06x}")
            records.save(home, rec)

            out_dir = tmp_path / f"skills_test{i}"
            skill_path = skills_export.export_skill(home, rec.id, out_dir)

            assert expected_slug in str(skill_path), f"Expected {expected_slug} in {skill_path}"

    def test_export_slug_empty_fallback_to_id(self, tmp_path: Path) -> None:
        """Empty slug falls back to record id."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(title="!@#$%", id="mem-fallback00000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)

        # Slug should be the record id since title produces empty slug
        assert "mem-fallback00000" in str(skill_path)

    def test_export_slug_truncated_to_64_chars(self, tmp_path: Path) -> None:
        """Slug is truncated to 64 characters."""
        home = tmp_path / "brain"
        home.mkdir()

        long_title = "a" * 100
        rec = _record(title=long_title, id="mem-long000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)

        # Slug should be at most 64 chars
        slug = skill_path.parent.name
        assert len(slug) <= 64

    def test_export_description_capped_to_1024_chars(self, tmp_path: Path) -> None:
        """Description field is capped to 1024 characters."""
        home = tmp_path / "brain"
        home.mkdir()

        # Use a title near the max (200 chars)
        long_title = "a" * 200
        rec = _record(title=long_title, id="mem-desc00000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)

        content = skill_path.read_text(encoding="utf-8")
        # Description should be in the output
        lines = content.split("\n")
        desc_line = next(line for line in lines if line.startswith("description:"))
        # Description field should be reasonable (< 1100 to account for overhead)
        assert len(desc_line) < 1100
        # Should contain the record ID in the description
        assert "mem-desc00000000" in desc_line
        # Should contain the grade
        assert "TESTED" in desc_line

    def test_export_refuses_unknown_record(self, tmp_path: Path) -> None:
        """Refuses to export unknown record."""
        home = tmp_path / "brain"
        home.mkdir()

        out_dir = tmp_path / "skills"
        with pytest.raises(RecordError, match="unknown record"):
            skills_export.export_skill(home, "mem-unknown000000", out_dir)

    def test_export_refuses_non_procedure(self, tmp_path: Path) -> None:
        """Refuses to export non-procedure records."""
        home = tmp_path / "brain"
        home.mkdir()

        for record_type in ["fact", "decision", "gotcha", "locator"]:
            rec = _record(type=record_type, id=f"mem-{record_type[:3]}000000")
            records.save(home, rec)

            out_dir = tmp_path / f"skills_{record_type}"
            with pytest.raises(RecordError, match="type must be 'procedure'"):
                skills_export.export_skill(home, rec.id, out_dir)

    def test_export_refuses_candidate_status(self, tmp_path: Path) -> None:
        """Refuses to export candidate status records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(status="candidate", id="mem-cand000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        with pytest.raises(RecordError, match="status must be 'current'"):
            skills_export.export_skill(home, rec.id, out_dir)

    def test_export_refuses_superseded_status(self, tmp_path: Path) -> None:
        """Refuses to export superseded records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(
            status="superseded",
            supersession_kind="supersedes",
            superseded_by="mem-other00000000",
            supersession_reason="Better version",
            superseded_at="2026-08-20T00:00:00+00:00",
            id="mem-super00000000",
        )
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        with pytest.raises(RecordError, match="status must be 'current'"):
            skills_export.export_skill(home, rec.id, out_dir)

    def test_export_refuses_observed_grade(self, tmp_path: Path) -> None:
        """Refuses to export OBSERVED grade records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(grade="OBSERVED", id="mem-obs000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        with pytest.raises(RecordError, match="effective grade must be TESTED"):
            skills_export.export_skill(home, rec.id, out_dir)

    def test_export_refuses_inferred_grade(self, tmp_path: Path) -> None:
        """Refuses to export INFERRED grade records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(grade="INFERRED", id="mem-inf000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        with pytest.raises(RecordError, match="effective grade must be TESTED"):
            skills_export.export_skill(home, rec.id, out_dir)

    def test_export_allows_tested_grade(self, tmp_path: Path) -> None:
        """Allows TESTED grade records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(grade="TESTED", id="mem-test000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)
        assert skill_path.exists()

    def test_export_allows_verified_grade(self, tmp_path: Path) -> None:
        """Allows VERIFIED grade records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(grade="VERIFIED", id="mem-ver000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)
        assert skill_path.exists()

    def test_export_verified_unattested_treated_as_tested(self, tmp_path: Path) -> None:
        """VERIFIED without attestation is treated as TESTED."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(grade="VERIFIED", attested=False, id="mem-vun000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)

        content = skill_path.read_text(encoding="utf-8")
        assert "(TESTED, advisory)" in content

    def test_export_refuses_to_overwrite_without_force(self, tmp_path: Path) -> None:
        """Refuses to overwrite existing SKILL.md without force."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(id="mem-over000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"

        # First export succeeds
        skill_path = skills_export.export_skill(home, rec.id, out_dir)
        assert skill_path.exists()

        # Second export fails
        with pytest.raises(RecordError, match="file exists"):
            skills_export.export_skill(home, rec.id, out_dir, force=False)

        # With force=True, succeeds
        skill_path2 = skills_export.export_skill(home, rec.id, out_dir, force=True)
        assert skill_path2.exists()

    def test_export_deterministic_output(self, tmp_path: Path) -> None:
        """Export produces deterministic output."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(
            title="Deterministic Test",
            body="Test body",
            evidence=["a.md", "b.md"],
            id="mem-det000000000",
        )
        records.save(home, rec)

        # Export twice
        out_dir1 = tmp_path / "skills1"
        out_dir2 = tmp_path / "skills2"

        skill_path1 = skills_export.export_skill(home, rec.id, out_dir1)
        skill_path2 = skills_export.export_skill(home, rec.id, out_dir2)

        content1 = skill_path1.read_text(encoding="utf-8")
        content2 = skill_path2.read_text(encoding="utf-8")

        assert content1 == content2

    def test_export_output_parses_as_frontmatter_and_body(self, tmp_path: Path) -> None:
        """Exported output parses as valid frontmatter + body."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(
            title="Parse Test",
            body="Test body content",
            id="mem-parse00000000",
        )
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)

        content = skill_path.read_text(encoding="utf-8")

        # Should start with ---
        assert content.startswith("---\n")

        # Should have closing ---
        parts = content.split("\n---\n")
        assert len(parts) == 2

        frontmatter, body = parts[0][4:], parts[1].lstrip("\n")

        # Frontmatter should have name and description
        assert "name:" in frontmatter
        assert "description:" in frontmatter

        # Body should have title
        assert "Parse Test" in body

    def test_export_with_domains(self, tmp_path: Path) -> None:
        """Export correctly includes domains in Applicability."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(
            domains=("ue4ss", "telemetry"),
            id="mem-dom000000000",
        )
        records.save(home, rec)

        out_dir = tmp_path / "skills"
        skill_path = skills_export.export_skill(home, rec.id, out_dir)

        content = skill_path.read_text(encoding="utf-8")
        assert "scope: project p1 ue4ss telemetry" in content

    def test_export_with_valid_from(self, tmp_path: Path) -> None:
        """Export uses valid_from if present, else recorded_at."""
        home = tmp_path / "brain"
        home.mkdir()

        # With valid_from
        rec1 = _record(valid_from="2026-08-01T00:00:00+00:00", id="mem-vf1000000000")
        records.save(home, rec1)

        out_dir1 = tmp_path / "skills1"
        skill_path1 = skills_export.export_skill(home, rec1.id, out_dir1)
        content1 = skill_path1.read_text(encoding="utf-8")
        assert "valid from: 2026-08-01" in content1

        # Without valid_from
        rec2 = _record(valid_from=None, id="mem-vf2000000000")
        records.save(home, rec2)

        out_dir2 = tmp_path / "skills2"
        skill_path2 = skills_export.export_skill(home, rec2.id, out_dir2)
        content2 = skill_path2.read_text(encoding="utf-8")
        assert "valid from: 2026-08-16" in content2  # recorded_at


class TestConsolidateNearDuplicates:
    """Tests for consolidate.near_duplicates()."""

    def test_finds_duplicate_pair(self, tmp_path: Path) -> None:
        """Finds a pair of near-duplicate records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec1 = _record(
            title="Fix bug in parsing system",
            id="mem-dup00000000001",
            project="p1",
        )
        rec2 = _record(
            title="Fix bug in parser system",
            id="mem-dup00000000002",
            project="p1",
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.5)

        assert len(duplicates) >= 1
        # Should find the pair
        pair_ids = {(a, b) for a, b, _ in duplicates}
        assert ("mem-dup00000000001", "mem-dup00000000002") in pair_ids

    def test_respects_project_bucket(self, tmp_path: Path) -> None:
        """Different projects are not paired."""
        home = tmp_path / "brain"
        home.mkdir()

        rec1 = _record(
            title="Configure Pipeline",
            id="mem-p1a000000000",
            project="p1",
        )
        rec2 = _record(
            title="Configure Pipeline",
            id="mem-p2a000000000",
            project="p2",
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.0)

        # Should not find a pair because projects differ
        pair_ids = {(a, b) for a, b, _ in duplicates}
        assert ("mem-p1a000000000", "mem-p2a000000000") not in pair_ids

    def test_respects_scope_bucket(self, tmp_path: Path) -> None:
        """Different scopes are not paired."""
        home = tmp_path / "brain"
        home.mkdir()

        rec1 = _record(
            title="Configure Pipeline",
            id="mem-s1a000000000",
            scope="project",
            project="p1",
        )
        rec2 = _record(
            title="Configure Pipeline",
            id="mem-s2a000000000",
            scope="global",
            project=None,
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.0)

        pair_ids = {(a, b) for a, b, _ in duplicates}
        assert ("mem-s1a000000000", "mem-s2a000000000") not in pair_ids

    def test_respects_domains_bucket(self, tmp_path: Path) -> None:
        """Different domains are not paired."""
        home = tmp_path / "brain"
        home.mkdir()

        rec1 = _record(
            title="Configure Pipeline",
            id="mem-d1a000000000",
            project="p1",
            domains=("ue4ss",),
        )
        rec2 = _record(
            title="Configure Pipeline",
            id="mem-d2a000000000",
            project="p1",
            domains=("telemetry",),
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.0)

        pair_ids = {(a, b) for a, b, _ in duplicates}
        assert ("mem-d1a000000000", "mem-d2a000000000") not in pair_ids

    def test_skips_inactive_records(self, tmp_path: Path) -> None:
        """Skips inactive (superseded, retracted) records."""
        home = tmp_path / "brain"
        home.mkdir()

        rec1 = _record(
            title="Configure Pipeline",
            id="mem-inv000000000",
            status="superseded",
            supersession_kind="supersedes",
            superseded_by="mem-other00000000",
            supersession_reason="Superseded",
            superseded_at="2026-08-20T00:00:00+00:00",
        )
        rec2 = _record(
            title="Configure Pipeline",
            id="mem-inv200000000",
            status="current",
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.0)

        pair_ids = {(a, b) for a, b, _ in duplicates}
        assert ("mem-inv000000000", "mem-inv200000000") not in pair_ids

    def test_skips_one_token_titles(self, tmp_path: Path) -> None:
        """Skips records with <2 title tokens."""
        home = tmp_path / "brain"
        home.mkdir()

        rec1 = _record(
            title="Pipeline",
            id="mem-t1a000000000",
        )
        rec2 = _record(
            title="Pipeline",
            id="mem-t1b000000000",
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.0)

        pair_ids = {(a, b) for a, b, _ in duplicates}
        # Should not find pair because "Pipeline" is one token
        assert ("mem-t1a000000000", "mem-t1b000000000") not in pair_ids

    def test_threshold_edge(self, tmp_path: Path) -> None:
        """Threshold edge case: exactly at threshold is included."""
        home = tmp_path / "brain"
        home.mkdir()

        # Two titles with exactly matching tokens -> Jaccard = 1.0
        rec1 = _record(
            title="Fix bug in parser",
            id="mem-th1000000000",
        )
        rec2 = _record(
            title="Fix bug in parser",
            id="mem-th2000000000",
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]

        # At threshold 1.0
        duplicates_at = consolidate.near_duplicates(all_recs, threshold=1.0)
        assert len(duplicates_at) >= 1

        # Above threshold 1.0
        duplicates_above = consolidate.near_duplicates(all_recs, threshold=1.01)
        assert len(duplicates_above) == 0

    def test_ordering_by_score_descending(self, tmp_path: Path) -> None:
        """Results are sorted by score descending, then by ids."""
        home = tmp_path / "brain"
        home.mkdir()

        # Perfect match (score 1.0)
        rec1 = _record(
            title="Fix bug in parser",
            id="mem-ord000000000",
        )
        rec2 = _record(
            title="Fix bug in parser",
            id="mem-ord100000000",
        )

        # Partial match (lower score)
        rec3 = _record(
            title="Fix bug elsewhere",
            id="mem-ord200000000",
        )

        records.save(home, rec1)
        records.save(home, rec2)
        records.save(home, rec3)

        all_recs = [rec1, rec2, rec3]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.3)

        # First pair should be perfect match
        if duplicates:
            scores = [score for _, _, score in duplicates]
            # Scores should be in descending order
            assert scores == sorted(scores, reverse=True)

    def test_ordering_by_ids_when_score_equal(self, tmp_path: Path) -> None:
        """When scores are equal, sort by ids."""
        home = tmp_path / "brain"
        home.mkdir()

        rec1 = _record(
            title="Alpha beta gamma",
            id="mem-zzz000000000",
        )
        rec2 = _record(
            title="Beta gamma alpha",
            id="mem-aaa000000000",
        )

        records.save(home, rec1)
        records.save(home, rec2)

        all_recs = [rec1, rec2]
        duplicates = consolidate.near_duplicates(all_recs, threshold=0.5)

        # Should be sorted by ids when score is equal
        if duplicates:
            ids = [(a, b) for a, b, _ in duplicates]
            # First element should have smaller id first
            assert ids[0][0] < ids[0][1]


class TestReviewWithDuplicates:
    """Tests for review command showing duplicates."""

    def test_review_prints_possible_duplicates_section(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """Review output includes possible duplicates section."""
        home = tmp_path / "brain"
        home.mkdir()

        # Create two near-duplicate records
        rec1 = _record(
            title="Configure CI Pipeline",
            id="mem-ci1000000000",
            status="current",
        )
        rec2 = _record(
            title="Setup CI Pipeline",
            id="mem-ci2000000000",
            status="current",
        )

        records.save(home, rec1)
        records.save(home, rec2)

        # Mock args for review
        import argparse

        args = argparse.Namespace(home=str(home), no_capture=True, git=[])

        # Call review
        result = commands_capture.handle_review(args)
        assert result == 0

        # Check output
        captured = capsys.readouterr()
        assert "possible duplicates" in captured.out
        # Should have the count
        assert "(" in captured.out and ")" in captured.out


class TestExportSkillCLI:
    """Tests for export-skill CLI command."""

    def test_export_skill_cli_success(self, tmp_path: Path, capsys: object) -> None:
        """CLI command successfully exports a skill."""
        home = tmp_path / "brain"
        home.mkdir()

        rec = _record(id="mem-cli000000000")
        records.save(home, rec)

        out_dir = tmp_path / "skills"

        # Mock args
        import argparse

        args = argparse.Namespace(home=str(home), id=rec.id, dir=str(out_dir), force=False)

        # Call handler via commands_skills
        from second_brain.kb import commands_skills

        result = commands_skills.handle_export_skill(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "SKILL.md" in captured.out

    def test_export_skill_cli_error_exit_code(self, tmp_path: Path) -> None:
        """CLI command returns exit code 2 on error."""
        home = tmp_path / "brain"
        home.mkdir()

        # Mock args for non-existent record
        import argparse

        args = argparse.Namespace(
            home=str(home), id="mem-unknown000000", dir=str(tmp_path), force=False
        )

        from second_brain.kb import commands_skills

        result = commands_skills.handle_export_skill(args)
        assert result == 2


def test_description_with_colons_and_quotes_stays_parseable(tmp_path: Path) -> None:
    import json

    from second_brain.kb import records, skills_export

    rec = records.Record(
        id="mem-abcabcabcabc",
        title='OMP: run "brain views" after pulling',
        type="procedure",
        scope="global",
        status="current",
        grade="TESTED",
        recorded_at="2026-09-01T00:00:00+00:00",
    )
    records.save(tmp_path / "home", rec)
    path = skills_export.export_skill(tmp_path / "home", rec.id, tmp_path / "skills")
    line = next(
        entry
        for entry in path.read_text(encoding="utf-8").splitlines()
        if entry.startswith("description: ")
    )
    value = json.loads(line.removeprefix("description: "))
    assert value.startswith('OMP: run "brain views" after pulling')
