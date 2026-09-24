"""Brain health check: records, supersessions, index, views, privacy, evidence, sizes."""

from __future__ import annotations

import contextlib
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import capture, index, projects, records


@dataclass
class DoctorReport:
    """Result of a health check."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sizes: dict[str, int] = field(default_factory=dict)


def check(home: Path) -> DoctorReport:
    """Check brain health: records, index, views, privacy, evidence, sizes."""
    report = DoctorReport()
    home = Path(home)

    # 1. Record files — collect load_all errors
    loaded_records, load_errors = records.load_all(home)
    report.errors.extend(load_errors)

    # 2. Supersession integrity
    seen_ids = {r.id for r in loaded_records}
    for record in loaded_records:
        if record.status == "superseded":
            # Check superseded_by references a valid record
            if record.superseded_by and record.superseded_by not in seen_ids:
                report.errors.append(
                    f"{record.id}: superseded_by {record.superseded_by!r} not found"
                )
            elif record.superseded_by:
                # Check that superseded_by record has this id in its supersedes
                try:
                    successor_record = records.load(home, record.superseded_by)
                    if record.id not in successor_record.supersedes:
                        report.warnings.append(
                            f"{record.id}: half-written supersession "
                            f"(superseded_by {record.superseded_by} but not in its supersedes)"
                        )
                except records.RecordError:
                    pass

        # Check that supersedes lists only inactive records
        for superseded_id in record.supersedes:
            try:
                superseded_record = records.load(home, superseded_id)
                if superseded_record.active:
                    report.warnings.append(
                        f"{record.id}: supersedes {superseded_id} which is still active "
                        "(crash between the two writes of index.supersede)"
                    )
            except records.RecordError:
                pass

        # Check for chain loops
        if record.superseded_by:
            try:
                index.successor(home, record.id)
            except records.RecordError as e:
                report.errors.append(f"{record.id}: {e}")

    # 2b. Conflict links (MEM-04) must name existing records on both sides.
    by_id = {r.id: r for r in loaded_records}
    for record in loaded_records:
        for other_id in record.conflicts:
            other = by_id.get(other_id)
            if other is None:
                report.warnings.append(f"{record.id}: conflicts with missing record {other_id}")
            elif record.id not in other.conflicts:
                report.warnings.append(
                    f"{record.id}: conflict with {other_id} is not recorded on {other_id}"
                )

    # 3. Index
    refresh_report = index.refresh(home)
    report.errors.extend(e for e in refresh_report.errors if e not in report.errors)

    # Check that index row count matches loaded records count
    try:
        conn = index.connect(home)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM kb_records")
        indexed_count = cursor.fetchone()[0]
        conn.close()
        if indexed_count != len(loaded_records):
            report.errors.append(
                f"index mismatch: {indexed_count} rows vs {len(loaded_records)} records"
            )
    except sqlite3.Error as e:
        report.errors.append(f"index error: {e}")

    # 4. Views
    views_dir = Path(home) / "views"

    # Check projects.json exists
    if not (views_dir / "projects.json").is_file():
        report.warnings.append("views/projects.json missing: run brain views")

    # Find newest record mtime
    newest_record_mtime = 0
    records_dir_path = records.records_dir(home)
    if records_dir_path.is_dir():
        for record_file in records_dir_path.glob("*.md"):
            try:
                mtime = record_file.stat().st_mtime
                if mtime > newest_record_mtime:
                    newest_record_mtime = mtime
            except OSError:
                pass

    private_dir_path = records.private_dir(home)
    if private_dir_path.is_dir():
        for record_file in private_dir_path.glob("*.md"):
            try:
                mtime = record_file.stat().st_mtime
                if mtime > newest_record_mtime:
                    newest_record_mtime = mtime
            except OSError:
                pass

    # Check each project's views
    loaded_projects = projects.load_projects(home)
    project_ids = [p.id for p in loaded_projects] + ["_none"]

    for project_id in project_ids:
        brief_file = views_dir / project_id / "brief.md"
        corrections_file = views_dir / project_id / "corrections.json"

        # Check files exist
        if not brief_file.is_file():
            report.warnings.append(f"views/{project_id}/brief.md missing: run brain views")
        if not corrections_file.is_file():
            report.warnings.append(f"views/{project_id}/corrections.json missing: run brain views")

        # Check mtimes if records exist
        if newest_record_mtime > 0:
            try:
                brief_mtime = brief_file.stat().st_mtime if brief_file.is_file() else 0
                corrections_mtime = (
                    corrections_file.stat().st_mtime if corrections_file.is_file() else 0
                )
                if brief_mtime < newest_record_mtime or corrections_mtime < newest_record_mtime:
                    report.warnings.append(f"views/{project_id}: stale (run brain views)")
            except OSError:
                pass

    # 5. Privacy
    private_dir_path = records.private_dir(home)
    if private_dir_path.is_dir():
        # Check if .gitignore is set up properly
        try:
            # Test if a file in records/private/ is ignored
            test_path = "records/private/x.md"
            result = subprocess.run(
                ["git", "-C", str(home), "check-ignore", "-q", test_path],
                capture_output=True,
                timeout=5,
                check=False,
            )
            # 0 = ignored, 1 = not ignored, anything else = not a repository / git error
            if result.returncode == 1:
                report.warnings.append("records/private/ not properly gitignored")
        except (OSError, subprocess.TimeoutExpired):
            # Git not available or timed out
            pass

    # 6. Evidence staleness
    stale_count = len(capture.stale_evidence(home))
    if stale_count > 0:
        report.warnings.append(f"stale evidence: {stale_count}")

    # 7. Sizes
    report.sizes = _compute_sizes(home)

    return report


def _compute_sizes(home: Path) -> dict[str, int]:
    """Compute sizes of various directories and files."""
    sizes: dict[str, int] = {}

    def dir_size(path: Path) -> int:
        """Recursively compute directory size."""
        if not path.is_dir():
            return 0
        total = 0
        for entry in path.rglob("*"):
            if entry.is_file():
                with contextlib.suppress(OSError):
                    total += entry.stat().st_size
        return total

    def file_size(path: Path) -> int:
        """Get file size."""
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                pass
        return 0

    # Records (excluding private)
    records_dir_path = records.records_dir(home)
    records_size = 0
    if records_dir_path.is_dir():
        for entry in records_dir_path.rglob("*.md"):
            # Skip files in private subdirectory
            if "private" not in entry.parts:
                with contextlib.suppress(OSError):
                    records_size += entry.stat().st_size
    sizes["records"] = records_size

    # Private records
    sizes["records/private"] = dir_size(records.private_dir(home))

    # Database
    db_file = Path(home) / "db" / "kb.sqlite"
    sizes["db/kb.sqlite"] = file_size(db_file)

    # Views
    sizes["views"] = dir_size(Path(home) / "views")

    # State directories
    sizes["state/kb-events"] = dir_size(Path(home) / "state" / "kb-events")
    sizes["state/kb-inbox"] = dir_size(Path(home) / "state" / "kb-inbox")

    # Telemetry
    telemetry_file = Path(home) / "telemetry" / "kb-hooks.jsonl"
    sizes["telemetry/kb-hooks.jsonl"] = file_size(telemetry_file)

    return sizes
