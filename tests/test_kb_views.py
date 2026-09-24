"""V3 core: views, corrections, conversion, and CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from second_brain.kb import cli, convert, projects, records, views
from second_brain.kb.records import Record


def _record(**kw: object) -> Record:
    """Helper to create a test record."""
    base: dict[str, object] = {
        "id": "mem-abc123def456",
        "title": "Test record",
        "type": "fact",
        "project": "p1",
        "status": "current",
        "grade": "TESTED",
        "recorded_at": "2026-08-16T18:12:48+00:00",
    }
    base.update(kw)
    return Record(**base)  # type: ignore[arg-type]


# Brief tests


def test_brief_empty_when_no_records() -> None:
    """Empty brief when no current records."""
    brief = views.render_brief([], None)
    assert brief == ""


def test_brief_selects_current_visible(tmp_path: Path) -> None:
    """Brief selects only current, visible records."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(status="current", project="p1"),  # Include
        _record(status="candidate", project="p1"),  # Exclude (not current)
        _record(status="current", project="p2"),  # Exclude (not visible)
    ]

    brief = views.render_brief(recs, p1)
    assert "Test record" in brief
    assert brief.count("Test record") == 1


def test_brief_excludes_historical() -> None:
    """Brief excludes records with effective_grade HISTORICAL."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(status="current", grade="HISTORICAL"),  # Exclude
        _record(status="current", grade="TESTED"),  # Include
    ]

    brief = views.render_brief(recs, p1)
    assert "HISTORICAL" not in brief
    assert "TESTED" not in brief  # body not shown
    assert "Test record" in brief


def test_brief_fact_grade_gate() -> None:
    """Facts require TESTED or higher grade."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(type="fact", grade="OBSERVED"),  # Exclude (fact needs TESTED+)
        _record(type="fact", grade="TESTED"),  # Include
        _record(type="gotcha", grade="OBSERVED"),  # Include (not fact)
    ]

    brief = views.render_brief(recs, p1)
    # Both gotcha and the tested fact should appear
    assert brief.count("Test record") == 2


def test_brief_sections_in_order() -> None:
    """Brief sections appear in correct order."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(type="state"),
        _record(type="decision"),
        _record(type="gotcha"),
        _record(type="locator"),
        _record(type="procedure"),
        _record(type="fact", grade="TESTED"),
    ]

    brief = views.render_brief(recs, p1)
    lines = brief.split("\n")

    # Find section headers
    active_idx = next((i for i, line in enumerate(lines) if "Active work" in line), -1)
    decisions_idx = next((i for i, line in enumerate(lines) if "Decisions" in line), -1)
    gotchas_idx = next((i for i, line in enumerate(lines) if "Gotchas" in line), -1)
    where_idx = next((i for i, line in enumerate(lines) if "Where things are" in line), -1)
    procedures_idx = next((i for i, line in enumerate(lines) if "Procedures" in line), -1)
    facts_idx = next((i for i, line in enumerate(lines) if "Facts" in line), -1)

    # Verify order
    assert -1 < active_idx < decisions_idx < gotchas_idx < where_idx < procedures_idx < facts_idx


def test_brief_sort_by_time_descending() -> None:
    """Records within a section sorted by valid_from/recorded_at descending."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(type="decision", id="mem-001", recorded_at="2026-01-01T00:00:00+00:00"),
        _record(type="decision", id="mem-003", recorded_at="2026-03-01T00:00:00+00:00"),
        _record(type="decision", id="mem-002", valid_from="2026-02-01T00:00:00+00:00"),
    ]

    brief = views.render_brief(recs, p1)
    lines = brief.split("\n")

    # Find decision lines
    decision_lines = [line for line in lines if "mem-" in line]
    assert len(decision_lines) == 3
    assert "mem-003" in decision_lines[0]  # Most recent first
    assert "mem-002" in decision_lines[1]
    assert "mem-001" in decision_lines[2]


def test_brief_observed_marker() -> None:
    """Records with OBSERVED/INFERRED grade get (observed) marker."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(type="decision", grade="OBSERVED"),
        _record(type="decision", grade="TESTED"),
    ]

    brief = views.render_brief(recs, p1)
    assert brief.count("(observed)") == 1


def test_brief_native_text_dedupe() -> None:
    """Brief skips records whose normalized title is substring of native_text."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(title="Migration ordering", type="gotcha"),
        _record(title="Other thing", type="gotcha"),
    ]

    native = "Learn about migration ordering when working with the database"
    brief = views.render_brief(recs, p1, native_text=native)

    assert "Migration ordering" not in brief
    assert "Other thing" in brief


def test_brief_budget_truncation() -> None:
    """Brief respects budget and adds footer with count."""
    p1 = projects.Project(id="p1")

    # Create many records to exceed budget
    recs = [_record(type="decision", id=f"mem-{i:012d}", title=f"Decision {i}") for i in range(20)]

    brief = views.render_brief(recs, p1, budget=100)

    assert views.estimate_tokens(brief) <= 100  # the cap holds for the whole text
    shown = brief.count("\n- ")
    assert 0 < shown < 20
    assert brief.endswith(f'(+{20 - shown} more current records — brain q "<topic>")')

    many = [
        _record(type="decision", id=f"mem-{i:012d}", title=f"Decision {i} " + "x" * 40)
        for i in range(200)
    ]
    full = views.render_brief(many, p1)
    assert views.estimate_tokens(full) <= views.BRIEF_TOKEN_BUDGET
    assert "more current records" in full


def test_brief_determinism() -> None:
    """Same input → byte-identical output."""
    p1 = projects.Project(id="p1")

    recs = [
        _record(type="decision", title="A"),
        _record(type="gotcha", title="B"),
    ]

    brief1 = views.render_brief(recs, p1)
    brief2 = views.render_brief(recs, p1)
    assert brief1 == brief2
    assert brief1.encode() == brief2.encode()


# Correction table tests


def test_correction_table_filter() -> None:
    """Correction table includes only current, high-grade corrections/gotchas."""
    recs = [
        _record(type="correction", status="current", grade="TESTED", trigger_errors=("err",)),
        _record(type="correction", status="candidate", grade="TESTED", trigger_errors=("err",)),
        _record(type="correction", status="current", grade="OBSERVED", trigger_errors=("err",)),
        _record(type="gotcha", status="current", grade="TESTED", trigger_errors=("err",)),
        _record(type="fact", status="current", grade="TESTED", trigger_errors=("err",)),
    ]

    table = views.correction_table(recs)
    assert len(table) == 2  # Only correction and gotcha with current + TESTED


def test_correction_table_text_format() -> None:
    """Correction table text is title, or title: first_sentence."""
    recs = [
        _record(
            type="correction",
            status="current",
            grade="TESTED",
            trigger_errors=("err",),
            title="Bad config",
            body="Remove the line. It causes problems.",
        ),
    ]

    table = views.correction_table(recs)
    assert len(table) == 1
    assert table[0]["text"] == "Bad config: Remove the line"


def test_correction_table_text_budget() -> None:
    """Correction table text is cut to CORRECTION_TOKEN_BUDGET * 4 chars."""
    long_title = "x" * 500
    recs = [
        _record(
            type="correction",
            status="current",
            grade="TESTED",
            trigger_errors=("err",),
            title=long_title,
        ),
    ]

    table = views.correction_table(recs)
    assert len(table[0]["text"]) <= views.CORRECTION_TOKEN_BUDGET * 4


def test_correction_table_sorted_by_id() -> None:
    """Correction table sorted by id."""
    recs = [
        _record(
            id="mem-zzz", type="correction", status="current", grade="TESTED", trigger_errors=("e",)
        ),
        _record(
            id="mem-aaa", type="correction", status="current", grade="TESTED", trigger_errors=("e",)
        ),
    ]

    table = views.correction_table(recs)
    assert table[0]["id"] == "mem-aaa"
    assert table[1]["id"] == "mem-zzz"


# Match error tests


def test_match_error_substring() -> None:
    """match_error finds substring match (casefolded)."""
    table = [
        {
            "id": "mem-123",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["database locked"],
            "text": "Recovery",
        },
    ]

    project = projects.Project(id="p1")
    match = views.match_error(table, "Error: database LOCKED", project)
    assert match is not None
    assert match["id"] == "mem-123"


def test_match_error_regex() -> None:
    """match_error handles re: regex patterns."""
    table = [
        {
            "id": "mem-456",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["re:no such table: \\w+"],
            "text": "SQL",
        },
    ]

    project = projects.Project(id="p1")
    match = views.match_error(table, "no such table: xyz", project)
    assert match is not None
    assert match["id"] == "mem-456"


def test_match_error_invalid_regex_skipped() -> None:
    """match_error skips invalid regexes."""
    table = [
        {
            "id": "mem-789",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["re:[invalid("],  # Bad regex
            "text": "Fix",
        },
    ]

    project = projects.Project(id="p1")
    match = views.match_error(table, "something", project)
    assert match is None


def test_match_error_longest_pattern_wins() -> None:
    """match_error picks the entry with longest matching pattern."""
    table = [
        {
            "id": "mem-short",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["error"],
            "text": "Short",
        },
        {
            "id": "mem-long",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["database error"],
            "text": "Long",
        },
    ]

    project = projects.Project(id="p1")
    match = views.match_error(table, "database error in transaction", project)
    assert match["id"] == "mem-long"


def test_match_error_ties_go_to_smallest_id() -> None:
    """match_error picks smallest id when patterns tie."""
    table = [
        {
            "id": "mem-zzz",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["error"],
            "text": "Z",
        },
        {
            "id": "mem-aaa",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["error"],
            "text": "A",
        },
    ]

    project = projects.Project(id="p1")
    match = views.match_error(table, "error", project)
    assert match["id"] == "mem-aaa"


def test_match_error_invisible_entry_ignored() -> None:
    """match_error ignores entries not visible to project."""
    table = [
        {
            "id": "mem-p2",
            "scope": "project",
            "project": "p2",
            "domains": [],
            "errors": ["error"],
            "text": "P2",
        },
    ]

    project = projects.Project(id="p1")
    match = views.match_error(table, "error", project)
    assert match is None


def test_match_error_returns_none_when_no_match() -> None:
    """match_error returns None when nothing matches."""
    table = [
        {
            "id": "mem-123",
            "scope": "project",
            "project": "p1",
            "domains": [],
            "errors": ["database locked"],
            "text": "Recovery",
        },
    ]

    project = projects.Project(id="p1")
    match = views.match_error(table, "completely different error", project)
    assert match is None


# Compile views tests


def test_compile_views_creates_files(tmp_path: Path) -> None:
    """compile_views creates brief.md and corrections.json for each project."""
    home = tmp_path
    projects_dir = home / "projects"
    projects_dir.mkdir()

    # Create project manifest
    p1_dir = projects_dir / "p1"
    p1_dir.mkdir()
    (p1_dir / "project.toml").write_text('id = "p1"')

    # Create records
    rec = _record(project="p1", type="decision")
    records.save(home, rec)

    # Compile views
    result = views.compile_views(home)

    assert "p1" in result
    assert "_none" in result
    brief_path = home / "views" / "p1" / "brief.md"
    corr_path = home / "views" / "p1" / "corrections.json"
    assert brief_path.is_file()
    assert corr_path.is_file()


def test_compile_views_stale_cleanup(tmp_path: Path) -> None:
    """compile_views removes directories for deleted projects."""
    home = tmp_path

    # Create initial views for a project that doesn't exist anymore
    stale_dir = home / "views" / "stale-project"
    stale_dir.mkdir(parents=True)
    (stale_dir / "brief.md").write_text("old")
    (stale_dir / "corrections.json").write_text("[]")

    # Compile views (no projects defined)
    views.compile_views(home)

    # Stale project directory should be gone
    assert not stale_dir.exists()


# Converter tests


def _legacy_home(brain_home: Path) -> dict[str, str]:
    """A legacy store built through the real legacy API (schema of the running build)."""
    from second_brain import db, semantic

    ids = {
        "old": semantic.add_memory(
            brain_home,
            "Orchestrator must delegate all work",
            "old policy body",
            project_id="p1",
            grade="TESTED",
            sources=[{"ref": "docs/policy.md", "path": "docs/policy.md", "blob_sha": "a" * 40}],
        ),
        "new": semantic.add_memory(
            brain_home, "Brain has no orchestrator", "new body", project_id="p1", grade="TESTED"
        ),
        "domain": semantic.add_memory(
            brain_home, "Shared domain note", "d", scope="domain", project_id="p2"
        ),
        "rejected": semantic.add_memory(brain_home, "Rejected claim", "r", project_id="p1"),
        "archived": semantic.add_memory(brain_home, "Archived note", "a", project_id="p1"),
    }
    for key in ("old", "new"):
        semantic.curate(brain_home, ids[key], status="current")
    semantic.retire_memory(brain_home, ids["old"], by=ids["new"], reason="removal gate")
    conn = db.connect(db.db_path(brain_home))
    conn.execute(
        "UPDATE memories SET evidence_grade = 'REJECTED' WHERE memory_id = ?", (ids["rejected"],)
    )
    conn.execute("UPDATE memories SET status = 'archived' WHERE memory_id = ?", (ids["archived"],))
    conn.commit()
    conn.close()
    return ids


def test_convert_maps_the_real_legacy_schema(brain_home: Path, tmp_path: Path) -> None:
    from second_brain import db

    ids = _legacy_home(brain_home)
    out = tmp_path / "out"
    report = convert.convert(db.db_path(brain_home), brain_home, out)
    assert report.errors == [] and report.written == 5

    old = records.load(out, ids["old"])
    assert (old.status, old.superseded_by, old.supersession_kind) == (
        "superseded",
        ids["new"],
        "supersedes",
    )
    assert old.supersession_reason == "removal gate" and old.superseded_at
    assert old.evidence == ("docs/policy.md@aaaaaaaaaaaa",)
    assert old.body == "old policy body" and old.title == "Orchestrator must delegate all work"
    assert records.load(out, ids["new"]).supersedes == (ids["old"],)

    domain = records.load(out, ids["domain"])
    assert (domain.scope, domain.project) == ("domain", "p2")  # visibility not widened
    assert not projects.visible(domain, projects.Project(id="p3"))

    rejected = records.load(out, ids["rejected"])
    assert (rejected.status, rejected.grade, rejected.extra["legacy_grade"]) == (
        "retracted",
        "HISTORICAL",
        "REJECTED",
    )
    assert records.load(out, ids["archived"]).extra["legacy_status"] == "archived"

    again = convert.convert(db.db_path(brain_home), brain_home, out)
    assert again.written == 0 and len(again.skipped) == 5


def test_convert_dry_run_writes_nothing(brain_home: Path, tmp_path: Path) -> None:
    from second_brain import db

    _legacy_home(brain_home)
    out = tmp_path / "dry"
    report = convert.convert(db.db_path(brain_home), brain_home, out, dry_run=True)
    assert report.written == 5 and not records.records_dir(out).exists()


def test_cli_brief_command(tmp_path: Path, capsys) -> None:
    """CLI brief command renders and prints brief."""
    home = tmp_path
    projects_dir = home / "projects"
    projects_dir.mkdir()
    p1_dir = projects_dir / "p1"
    p1_dir.mkdir()
    (p1_dir / "project.toml").write_text('id = "p1"')

    rec = _record(project="p1")
    records.save(home, rec)

    exit_code = cli.main(["brief", "--home", str(home), "--project", "p1"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Brain brief" in captured.out or captured.out == ""


def test_cli_views_command(tmp_path: Path, capsys) -> None:
    """CLI views command compiles and prints summary."""
    home = tmp_path
    projects_dir = home / "projects"
    projects_dir.mkdir()
    p1_dir = projects_dir / "p1"
    p1_dir.mkdir()
    (p1_dir / "project.toml").write_text('id = "p1"')

    exit_code = cli.main(["views", "--home", str(home)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "p1:" in captured.out


def test_cli_match_error_command(tmp_path: Path, capsys) -> None:
    """CLI match-error command finds and prints matching correction."""
    home = tmp_path

    rec = records.Record(
        id="mem-corr123",
        title="Database error",
        type="correction",
        scope="project",
        project="p1",
        status="current",
        grade="TESTED",
        recorded_at="2026-01-01T00:00:00+00:00",
        trigger_errors=("database locked",),
    )
    records.save(home, rec)

    exit_code = cli.main(["match-error", "database locked", "--home", str(home), "--project", "p1"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "mem-corr123" in captured.out


def test_cli_import_native_command(tmp_path: Path, capsys) -> None:
    """CLI import-native command imports bullets from MEMORY.md."""
    home = tmp_path
    memory_path = tmp_path / "MEMORY.md"
    memory_path.write_text("- First bullet\n- Second bullet\n")

    exit_code = cli.main(["import-native", str(memory_path), "--home", str(home)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "mem-" in captured.out


# Real-corpus smoke test

_REPO = Path(__file__).resolve().parents[1]
_REPO_DB = _REPO / "db" / "brain.sqlite"


@pytest.mark.skipif(
    not _REPO_DB.exists(),
    reason="Real corpus database not present",
)
def test_real_corpus_smoke_conversion(tmp_path: Path) -> None:
    """Real-corpus smoke test: convert the repo's own database."""
    db_path = _REPO_DB
    legacy_home = _REPO
    out_home = tmp_path / "converted"

    report = convert.convert(db_path, legacy_home, out_home)

    assert report.written >= 100
    assert len(report.errors) == 0


@pytest.mark.skipif(
    not _REPO_DB.exists(),
    reason="Real corpus database not present",
)
def test_real_corpus_brief_tokens(tmp_path: Path) -> None:
    """Real-corpus smoke test: brief for second-brain project is ≤600 tokens."""
    db_path = _REPO_DB
    legacy_home = _REPO
    out_home = tmp_path / "converted"

    # Convert
    convert.convert(db_path, legacy_home, out_home)

    # Load converted records
    all_records, _ = records.load_all(out_home)

    # Render brief for second-brain project
    sb_project = projects.Project(id="second-brain", name="Second Brain")
    brief = views.render_brief(all_records, sb_project)

    tokens = views.estimate_tokens(brief)
    assert tokens <= 600
