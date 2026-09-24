"""V3 core: record format and project visibility."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from second_brain.kb import projects, records
from second_brain.kb.records import Record, RecordError


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
        "trigger_errors": ("no such table: kb_meta",),
        "body": "Apply migrations in numeric order.\n\nSecond paragraph.",
    }
    base.update(kw)
    return Record(**base)  # type: ignore[arg-type]


def test_round_trip_is_exact_and_deterministic(tmp_path: Path) -> None:
    rec = _record(domains=("ue4ss",), extra={"legacy_status": "labile"}, private=True)
    text = records.dumps(rec)
    assert records.loads(text) == rec
    assert records.dumps(records.loads(text)) == text
    records.save(tmp_path, rec)
    loaded, errors = records.load_all(tmp_path)
    assert loaded == [rec] and errors == []


def test_legacy_memory_file_parses() -> None:
    legacy = (
        "---\nid: mem-a8d221e64549\ntitle: Migration ordering\nscope: project\n"
        "project: second-brain\nstatus: current\ngrade: TESTED\nversion: 1\n"
        "created_at: 2026-08-16T18:12:48.523090+00:00\n---\n\napply migrations in numeric order\n"
    )
    rec = records.loads(legacy.replace("\n", "\r\n"))
    assert rec.recorded_at.startswith("2026-08-16")
    assert rec.extra == {"version": "1"}
    assert rec.body == "apply migrations in numeric order"


def test_claimed_verified_is_effective_tested() -> None:
    assert _record(grade="VERIFIED").effective_grade == "TESTED"
    assert _record(grade="VERIFIED", attested=True).effective_grade == "VERIFIED"


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"id": "Bad Id"}, "id"),
        ({"type": "note"}, "type"),
        ({"scope": "project", "project": None}, "requires project"),
        ({"status": "superseded"}, "supersession_kind"),
        ({"recorded_at": "yesterday"}, "ISO-8601"),
    ],
)
def test_validation_rejects(changes: dict[str, object], fragment: str) -> None:
    errors = records.validate(_record(**changes))
    assert any(fragment in e for e in errors), errors


def test_save_refuses_invalid(tmp_path: Path) -> None:
    with pytest.raises(RecordError):
        records.save(tmp_path, _record(type="note"))


def test_load_all_reports_bad_files(tmp_path: Path) -> None:
    records.save(tmp_path, _record())
    (records.records_dir(tmp_path) / "mem-zzz999zzz999.md").write_text("no frontmatter")
    loaded, errors = records.load_all(tmp_path)
    assert [r.id for r in loaded] == ["mem-abc123def456"]
    assert len(errors) == 1 and "mem-zzz999zzz999" in errors[0]


def _manifest(home: Path, pid: str, body: str) -> None:
    d = home / "projects" / pid
    d.mkdir(parents=True)
    (d / "project.toml").write_text(f'id = "{pid}"\n{body}', encoding="utf-8")


def test_resolution_by_path_windows_and_posix(tmp_path: Path) -> None:
    repo = tmp_path / "work" / "repo"
    (repo / "sub").mkdir(parents=True)
    _manifest(tmp_path, "p1", f'repo_path = "C:/Users/x/Repo"\npaths = ["{repo.as_posix()}"]\n')
    _manifest(tmp_path, "outer", f'paths = ["{(tmp_path / "work").as_posix()}"]\n')
    assert projects.resolve(tmp_path, repo / "sub").id == "p1"  # longest path wins
    assert projects.normalize_path("C:\\Users\\X\\Repo\\") == "c:/users/x/repo"


def test_resolution_by_git_remote(tmp_path: Path) -> None:
    repo = tmp_path / "clone"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:Owner/Repo.git"], cwd=repo, check=True
    )
    _manifest(tmp_path, "p1", 'git_remote = "https://github.com/owner/repo"\n')
    assert projects.resolve(tmp_path, repo).id == "p1"
    assert projects.resolve(tmp_path, tmp_path / "nowhere") is None


def test_visibility_rules() -> None:
    p1 = projects.Project(id="p1", domains=("ue4ss",))
    assert projects.visible(_record(), p1)
    assert not projects.visible(_record(project="p2"), p1)
    assert not projects.visible(_record(), None)
    assert projects.visible(_record(scope="global", project=None), None)
    tagged = _record(scope="domain", project="p2", domains=("ue4ss",))
    assert projects.visible(tagged, p1)
    assert not projects.visible(tagged, projects.Project(id="p3"))
    legacy_domain = _record(scope="domain", project="p2")
    assert not projects.visible(legacy_domain, projects.Project(id="p3"))
    assert projects.visible(legacy_domain, None)


def test_core_import_stays_lean() -> None:
    code = (
        "import sys, second_brain.kb.cli; "
        "bad = [m for m in sys.modules if m.startswith('second_brain.') "
        "and not m.startswith('second_brain.kb') and m != 'second_brain.paths']; "
        "print(','.join(sorted(bad)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
