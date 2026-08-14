import tomllib

import pytest

from second_brain import registry
from second_brain.errors import BrainError


def test_add_project_creates_row_and_dir(brain_home, repo):
    proj, created = registry.add_project(brain_home, repo)
    assert created
    assert proj.name == repo.name
    assert proj.id == registry.path_hash(str(repo))
    brain_dir = brain_home / "projects" / proj.id
    assert brain_dir.is_dir()
    assert (brain_dir / "overview.md").exists()
    manifest = tomllib.loads((brain_dir / "project.toml").read_text(encoding="utf-8"))
    assert manifest["id"] == proj.id
    assert manifest["repo_path"] == str(repo.resolve()).replace("\\", "/")


def test_add_project_idempotent(brain_home, repo):
    p1, created1 = registry.add_project(brain_home, repo)
    p2, created2 = registry.add_project(brain_home, repo)
    assert created1 and not created2
    assert p1.id == p2.id


def test_add_project_missing_path_raises(brain_home, tmp_path):
    with pytest.raises(BrainError):
        registry.add_project(brain_home, tmp_path / "does-not-exist")


def test_explicit_manifest_id_wins(brain_home, repo):
    (repo / ".brain").mkdir()
    (repo / ".brain" / "project.toml").write_text(
        'schema_version = 1\nid = "manifest-id-123"\n', encoding="utf-8"
    )
    proj, _ = registry.add_project(brain_home, repo)
    assert proj.id == "manifest-id-123"


def test_invalid_manifest_raises(brain_home, repo):
    (repo / ".brain").mkdir()
    (repo / ".brain" / "project.toml").write_text("id = 42\n", encoding="utf-8")
    with pytest.raises(BrainError):
        registry.add_project(brain_home, repo)


def test_manual_id_override(brain_home, repo):
    proj, _ = registry.add_project(brain_home, repo, name="Custom", project_id="custom-id")
    assert proj.id == "custom-id"
    assert proj.name == "Custom"


def test_list_and_get(brain_home, repo, tmp_path):
    registry.add_project(brain_home, repo, project_id="aaaa1111")
    registry.add_project(brain_home, repo, project_id="aaaa2222")
    projects = registry.list_projects(brain_home)
    assert len(projects) == 2
    assert registry.get_project(brain_home, "aaaa11").id == "aaaa1111"
    assert registry.get_project(brain_home, "aaaa2222").id == "aaaa2222"
    with pytest.raises(BrainError):
        registry.get_project(brain_home, "zzzz")


def test_project_status(brain_home, repo):
    registry.add_project(brain_home, repo)
    st = registry.project_status(brain_home, registry.path_hash(str(repo)))
    assert st["repo_exists"] == "True"
    assert st["brain_dir_exists"] == "True"
    assert st["active"] == "True"
