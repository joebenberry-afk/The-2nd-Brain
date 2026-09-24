"""Tests for Brain doctor: health check."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from second_brain.kb import capture, cli, doctor, index, records
from second_brain.kb.records import Record


def _record(**kw: object) -> Record:
    base: dict[str, object] = {
        "id": "mem-abc123def456",
        "title": "Test record",
        "type": "fact",
        "project": "p1",
        "status": "current",
        "grade": "TESTED",
        "recorded_at": "2026-08-16T18:12:48+00:00",
        "evidence": ("test@hash",),
    }
    base.update(kw)
    return Record(**base)  # type: ignore[arg-type]


class TestDoctorHealthCheck:
    """Test doctor.check() function."""

    def test_clean_home_no_errors(self, tmp_path: Path) -> None:
        """A clean home with no records has no errors."""
        report = doctor.check(tmp_path)
        assert report.errors == []
        assert "records" in report.sizes
        assert report.sizes["records"] == 0

    def test_record_file_errors_reported(self, tmp_path: Path) -> None:
        """Record file errors from load_all are reported."""
        records.save(tmp_path, _record())
        records.records_dir(tmp_path).joinpath("bad.md").write_text("no frontmatter")

        report = doctor.check(tmp_path)
        assert any("bad.md" in e for e in report.errors)

    def test_supersession_integrity_missing_target(self, tmp_path: Path) -> None:
        """superseded_by referencing non-existent record is an error."""
        rec = _record(
            status="superseded",
            superseded_by="mem-missing",
            supersession_kind="supersedes",
            supersession_reason="test",
            superseded_at="2026-08-16T18:12:48+00:00",
        )
        records.save(tmp_path, rec)

        report = doctor.check(tmp_path)
        assert any("superseded_by" in e and "not found" in e for e in report.errors)

    def test_supersession_integrity_half_written(self, tmp_path: Path) -> None:
        """Half-written supersession (target lacks reference) is a warning."""
        old_id = "mem-abc123def456"
        new_id = "mem-def456abc123"

        old_rec = _record(
            id=old_id,
            status="superseded",
            superseded_by=new_id,
            supersession_kind="supersedes",
            supersession_reason="test",
            superseded_at="2026-08-16T18:12:48+00:00",
        )
        new_rec = _record(id=new_id, title="New record")

        records.save(tmp_path, old_rec)
        records.save(tmp_path, new_rec)

        report = doctor.check(tmp_path)
        assert any("half-written supersession" in w for w in report.warnings)

    def test_supersession_integrity_active_superseded(self, tmp_path: Path) -> None:
        """A record with supersedes pointing to active record is a warning."""
        old_id = "mem-abc123def456"
        new_id = "mem-def456abc123"

        old_rec = _record(id=old_id, title="Old record", status="current")
        new_rec = _record(id=new_id, title="New record", supersedes=(old_id,))

        records.save(tmp_path, old_rec)
        records.save(tmp_path, new_rec)

        report = doctor.check(tmp_path)
        assert any("still active" in w for w in report.warnings)

    def test_supersession_integrity_loop_error(self, tmp_path: Path) -> None:
        """A supersession loop is an error."""
        id1 = "mem-111111111111"
        id2 = "mem-222222222222"

        # Create a loop: 1 -> 2 -> 1
        rec1 = _record(
            id=id1,
            status="superseded",
            superseded_by=id2,
            supersession_kind="supersedes",
            supersession_reason="test",
            superseded_at="2026-08-16T18:12:48+00:00",
        )
        rec2 = _record(
            id=id2,
            status="superseded",
            superseded_by=id1,
            supersession_kind="supersedes",
            supersession_reason="test",
            superseded_at="2026-08-16T18:12:48+00:00",
        )

        records.save(tmp_path, rec1)
        records.save(tmp_path, rec2)

        report = doctor.check(tmp_path)
        assert any("loop" in e for e in report.errors)

    def test_index_row_count_matches(self, tmp_path: Path) -> None:
        """Index row count should equal loaded records count."""
        records.save(tmp_path, _record())
        records.save(tmp_path, _record(id="mem-aaa111aaa111", title="Another"))

        report = doctor.check(tmp_path)
        # After refresh, counts should match
        assert not any("index mismatch" in e for e in report.errors)

    def test_stale_views_warning(self, tmp_path: Path) -> None:
        """Stale views (older than newest record) trigger a warning."""
        rec = _record()
        records.save(tmp_path, rec)

        # Create views directory with old files
        views_dir = tmp_path / "views" / "_none"
        views_dir.mkdir(parents=True)
        brief_file = views_dir / "brief.md"
        brief_file.write_text("# Brief")

        # Set mtime of brief to be older than the record
        old_time = time.time() - 3600
        os.utime(brief_file, (old_time, old_time))

        # Also create a projects.json
        (tmp_path / "views" / "projects.json").write_text("{}")

        report = doctor.check(tmp_path)
        assert any("stale" in w for w in report.warnings)

    def test_missing_projects_json_warning(self, tmp_path: Path) -> None:
        """Missing projects.json is a warning."""
        report = doctor.check(tmp_path)
        assert any("projects.json" in w for w in report.warnings)

    def test_privacy_git_ignored_ok(self, tmp_path: Path) -> None:
        """Private directory properly gitignored is OK."""
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)

        # Create private directory
        private_dir = records.private_dir(tmp_path)
        private_dir.mkdir(parents=True)

        # Add .gitignore
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("records/private/\n")

        report = doctor.check(tmp_path)
        # No warning about unignored private directory
        assert not any("gitignored" in w for w in report.warnings)

    def test_privacy_git_not_ignored_warning(self, tmp_path: Path) -> None:
        """Private directory not gitignored is a warning."""
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)

        # Create private directory without .gitignore
        private_dir = records.private_dir(tmp_path)
        private_dir.mkdir(parents=True)

        report = doctor.check(tmp_path)
        # Warning about unignored private directory
        assert any("gitignored" in w for w in report.warnings)

    def test_stale_evidence_warning(self, tmp_path: Path) -> None:
        """Stale evidence triggers a warning."""
        # Create a record with evidence pointing to non-existent file
        # Note: blob must be 7+ hex characters to be checked
        rec = _record(evidence=("missing/file@abc1234567",))
        records.save(tmp_path, rec)

        report = doctor.check(tmp_path)
        assert any("stale evidence" in w for w in report.warnings)

    def test_sizes_computed(self, tmp_path: Path) -> None:
        """Sizes are computed for various directories."""
        records.save(tmp_path, _record())

        report = doctor.check(tmp_path)
        assert "records" in report.sizes
        assert "db/kb.sqlite" in report.sizes
        assert "views" in report.sizes
        assert report.sizes["records"] > 0


class TestPromotionProvenance:
    """Test promotion actor tracking."""

    def test_promote_records_actor_explicit(self, tmp_path: Path) -> None:
        """Promote with explicit actor parameter."""
        candidate = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )

        promoted = index.promote(tmp_path, candidate.id, reason="verified", actor="alice")
        assert promoted.extra.get("promoted_by") == "alice"

    def test_promote_records_actor_from_brain_actor_env(self, tmp_path: Path) -> None:
        """Promote reads BRAIN_ACTOR environment variable."""
        candidate = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )

        old_env = os.environ.get("BRAIN_ACTOR")
        try:
            os.environ["BRAIN_ACTOR"] = "bob"
            promoted = index.promote(tmp_path, candidate.id, reason="verified")
            assert promoted.extra.get("promoted_by") == "bob"
        finally:
            if old_env is not None:
                os.environ["BRAIN_ACTOR"] = old_env
            else:
                os.environ.pop("BRAIN_ACTOR", None)

    def test_promote_records_actor_from_user_env(self, tmp_path: Path) -> None:
        """Promote reads USER/USERNAME environment variable."""
        candidate = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )

        old_user = os.environ.get("USER")
        old_username = os.environ.get("USERNAME")
        old_brain_actor = os.environ.get("BRAIN_ACTOR")
        try:
            # Clear BRAIN_ACTOR and set USER
            os.environ.pop("BRAIN_ACTOR", None)
            os.environ["USER"] = "charlie"
            os.environ.pop("USERNAME", None)

            promoted = index.promote(tmp_path, candidate.id, reason="verified")
            assert promoted.extra.get("promoted_by") == "charlie"
        finally:
            if old_user is not None:
                os.environ["USER"] = old_user
            else:
                os.environ.pop("USER", None)
            if old_username is not None:
                os.environ["USERNAME"] = old_username
            else:
                os.environ.pop("USERNAME", None)
            if old_brain_actor is not None:
                os.environ["BRAIN_ACTOR"] = old_brain_actor
            else:
                os.environ.pop("BRAIN_ACTOR", None)

    def test_promote_records_actor_unknown_fallback(self, tmp_path: Path) -> None:
        """Promote uses unknown when no actor source available."""
        candidate = index.add(
            tmp_path,
            title="Test",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )

        old_user = os.environ.get("USER")
        old_username = os.environ.get("USERNAME")
        old_brain_actor = os.environ.get("BRAIN_ACTOR")
        try:
            # Clear all actor sources
            os.environ.pop("BRAIN_ACTOR", None)
            os.environ.pop("USER", None)
            os.environ.pop("USERNAME", None)

            promoted = index.promote(tmp_path, candidate.id, reason="verified")
            assert promoted.extra.get("promoted_by") == "unknown"
        finally:
            if old_user is not None:
                os.environ["USER"] = old_user
            if old_username is not None:
                os.environ["USERNAME"] = old_username
            if old_brain_actor is not None:
                os.environ["BRAIN_ACTOR"] = old_brain_actor


class TestEventRetention:
    """Test event file retention and pruning."""

    def test_prune_events_deletes_old_files(self, tmp_path: Path) -> None:
        """Prune events deletes files older than retention period."""
        events_dir = capture.events_dir(tmp_path)
        events_dir.mkdir(parents=True)

        # Create an old event file
        old_file = events_dir / "old.jsonl"
        old_file.write_text('{"event": "test"}\n')

        # Create cursor entry for the old file
        cursor_file = events_dir / ".cursor.json"
        cursor = {"old": 100}
        cursor_file.write_text(json.dumps(cursor))

        # Set mtime to be older than retention period
        old_time = time.time() - (15 * 24 * 60 * 60)  # 15 days ago
        os.utime(old_file, (old_time, old_time))

        # Prune with that time
        deleted = capture.prune_events(tmp_path, now=time.time())

        assert "old" in deleted
        assert not old_file.exists()

    def test_prune_events_keeps_new_files(self, tmp_path: Path) -> None:
        """Prune events keeps files newer than retention period."""
        events_dir = capture.events_dir(tmp_path)
        events_dir.mkdir(parents=True)

        # Create a new event file
        new_file = events_dir / "new.jsonl"
        new_file.write_text('{"event": "test"}\n')

        # Create cursor entry
        cursor_file = events_dir / ".cursor.json"
        cursor = {"new": 100}
        cursor_file.write_text(json.dumps(cursor))

        # Set mtime to be recent
        now = time.time()
        os.utime(new_file, (now, now))

        # Prune
        deleted = capture.prune_events(tmp_path, now=now)

        assert "new" not in deleted
        assert new_file.exists()

    def test_prune_events_not_in_dry_run(self, tmp_path: Path) -> None:
        """capture_events in dry run does not prune."""
        events_dir = capture.events_dir(tmp_path)
        events_dir.mkdir(parents=True)

        # Create an old event file
        old_file = events_dir / "old.jsonl"
        old_file.write_text('{"ok": true, "tool": "python", "command": "python test.py"}\n')

        # Create cursor entry
        cursor_file = events_dir / ".cursor.json"
        cursor = {"old": len(old_file.read_bytes())}
        cursor_file.write_text(json.dumps(cursor))

        # Set mtime to be old
        old_time = time.time() - (15 * 24 * 60 * 60)
        os.utime(old_file, (old_time, old_time))

        # Run capture_events in dry run mode
        capture.capture_events(tmp_path, dry_run=True)

        # File should still exist
        assert old_file.exists()

    def test_prune_events_only_fully_processed_files(self, tmp_path: Path) -> None:
        """Prune only deletes files that have been fully processed (cursor exists)."""
        events_dir = capture.events_dir(tmp_path)
        events_dir.mkdir(parents=True)

        # Create event files
        old_processed = events_dir / "processed.jsonl"
        old_processed.write_text('{"event": "test"}\n')
        old_unprocessed = events_dir / "unprocessed.jsonl"
        old_unprocessed.write_text('{"event": "test"}\n')

        # Only add cursor for the processed file
        cursor_file = events_dir / ".cursor.json"
        cursor = {"processed": 100}
        cursor_file.write_text(json.dumps(cursor))

        # Set mtime to be old
        old_time = time.time() - (15 * 24 * 60 * 60)
        os.utime(old_processed, (old_time, old_time))
        os.utime(old_unprocessed, (old_time, old_time))

        # Prune
        deleted = capture.prune_events(tmp_path, now=time.time())

        assert "processed" in deleted
        assert not old_processed.exists()
        assert old_unprocessed.exists()


class TestReviewRecently:
    """Test review command's recently promoted section."""

    def test_review_shows_recently_promoted(self, tmp_path: Path, capsys) -> None:
        """Review command shows recently promoted section."""
        # Create and promote a record
        candidate = index.add(
            tmp_path,
            title="Test record",
            body="Body",
            type="fact",
            scope="global",
            project=None,
            evidence=("test@hash",),
        )

        index.promote(tmp_path, candidate.id, reason="verified", actor="alice")

        # Run review command via cli.main
        exit_code = cli.main(["review", "--home", str(tmp_path), "--no-capture"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "recently promoted" in captured.out
        assert "alice" in captured.out


class TestDoctorCommand:
    """Test the doctor CLI command."""

    def test_doctor_exit_zero_no_errors(self, tmp_path: Path) -> None:
        """Doctor exits 0 when no errors exist."""
        exit_code = cli.main(["doctor", "--home", str(tmp_path)])
        assert exit_code == 0

    def test_doctor_exit_one_on_errors(self, tmp_path: Path) -> None:
        """Doctor exits 1 when errors exist."""
        records.records_dir(tmp_path).mkdir(parents=True)
        records.records_dir(tmp_path).joinpath("bad.md").write_text("no frontmatter")

        exit_code = cli.main(["doctor", "--home", str(tmp_path)])
        assert exit_code == 1

    def test_doctor_json_output(self, tmp_path: Path, capsys) -> None:
        """Doctor --json outputs JSON."""
        cli.main(["doctor", "--home", str(tmp_path), "--json"])
        captured = capsys.readouterr()

        # Should be valid JSON
        data = json.loads(captured.out)
        assert "errors" in data
        assert "warnings" in data
        assert "sizes" in data

    def test_doctor_text_output(self, tmp_path: Path, capsys) -> None:
        """Doctor without --json outputs human-readable text."""
        cli.main(["doctor", "--home", str(tmp_path)])
        captured = capsys.readouterr()

        # Should contain expected text
        assert "errors (" in captured.out
        assert "warnings (" in captured.out
        assert "sizes" in captured.out


def test_doctor_is_quiet_about_git_outside_a_repository_and_lists_errors_once(
    tmp_path: Path,
) -> None:
    from second_brain.kb import doctor, records

    rec = records.Record(
        id="mem-aaaaaaaaaaaa",
        title="Private note",
        scope="global",
        status="current",
        grade="TESTED",
        recorded_at="2026-09-01T00:00:00+00:00",
        private=True,
    )
    records.save(tmp_path, rec)
    (records.records_dir(tmp_path) / "mem-bbbbbbbbbbbb.md").write_text("broken", encoding="utf-8")
    report = doctor.check(tmp_path)
    assert not any("gitignored" in w for w in report.warnings)
    broken = [e for e in report.errors if "mem-bbbbbbbbbbbb" in e]
    assert len(broken) == 1


def test_prune_keeps_old_files_that_were_not_fully_processed(tmp_path: Path) -> None:
    import json
    import os
    import time

    from second_brain.kb import capture

    events = capture.events_dir(tmp_path)
    events.mkdir(parents=True)
    old = events / "old.jsonl"
    old.write_text('{"v": 1}\n{"v": 1}\n', encoding="utf-8")
    (events / ".cursor.json").write_text(json.dumps({"old": 5}), encoding="utf-8")
    stamp = time.time() - 30 * 86400
    os.utime(old, (stamp, stamp))
    assert capture.prune_events(tmp_path) == []
    (events / ".cursor.json").write_text(json.dumps({"old": old.stat().st_size}), encoding="utf-8")
    assert capture.prune_events(tmp_path) == ["old"]
