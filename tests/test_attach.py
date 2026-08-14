"""Phase 3 — project attach/detach (plan §99) integration tests."""

import tomllib

import pytest

from second_brain import registry
from second_brain.errors import BrainError

USER_TEXT = "## My own rules\n\n- rule one\n- rule two\n"


def _attach(repo, brain_home, **kw):
    return registry.attach_project(brain_home, repo, **kw)


def test_attach_writes_manifest_and_marker(brain_home, repo):
    proj, created, changes = _attach(repo, brain_home)
    assert created
    assert changes["manifest_created"] and changes["marker_added"]

    manifest = tomllib.loads((repo / ".brain" / "project.toml").read_text(encoding="utf-8"))
    assert manifest["id"] == proj.id
    assert manifest["schema_version"] == 1
    assert manifest["repository_is_authoritative"] is True
    assert manifest["meta"]["managed_by"] == "second-brain"

    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "The-Second-Brain:begin id=" in agents
    assert "%SECOND_BRAIN_HOME%" in agents


def test_attach_preserves_existing_agents(brain_home, repo):
    (repo / "AGENTS.md").write_text(USER_TEXT, encoding="utf-8", newline="")
    _attach(repo, brain_home)
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith(USER_TEXT)


def test_reattach_is_idempotent(brain_home, repo):
    _attach(repo, brain_home)
    _proj, created, changes = _attach(repo, brain_home)
    assert not created
    assert changes["manifest_created"] is False
    assert changes["marker_added"] is False
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count("The-Second-Brain:begin id=") == 1


def test_attach_respects_existing_manifest(brain_home, repo):
    (repo / ".brain").mkdir()
    (repo / ".brain" / "project.toml").write_text(
        'schema_version = 1\nid = "user-manifest-id"\nname = "UserName"\n', encoding="utf-8"
    )
    proj, _created, changes = _attach(repo, brain_home)
    assert proj.id == "user-manifest-id"
    assert changes["manifest_created"] is False


def test_attach_skips_parts(brain_home, repo):
    _attach(repo, brain_home, with_marker=False, with_manifest=False)
    assert not (repo / ".brain" / "project.toml").exists()
    assert not (repo / "AGENTS.md").exists()


def test_detach_restores_agents_exactly(brain_home, repo):
    (repo / "AGENTS.md").write_text(USER_TEXT, encoding="utf-8", newline="")
    _attach(repo, brain_home)
    changes = registry.detach_project(brain_home, repo.name)
    assert changes["marker_removed"] is True
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == USER_TEXT


def test_detach_keeps_whitespace_only_agents_file(brain_home, repo):
    (repo / "AGENTS.md").write_text("\n\n", encoding="utf-8", newline="")
    _attach(repo, brain_home)
    changes = registry.detach_project(brain_home, repo.name)
    assert changes["marker_removed"] is True
    assert (repo / "AGENTS.md").exists()
    assert (repo / "AGENTS.md").read_text(encoding="utf-8", newline="") == "\n\n"


def test_detach_removes_managed_manifest_keeps_user_manifest(brain_home, repo, tmp_path):
    _attach(repo, brain_home)
    registry.detach_project(brain_home, repo.name)
    assert not (repo / ".brain" / "project.toml").exists()

    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    (repo2 / ".brain").mkdir()
    (repo2 / ".brain" / "project.toml").write_text(
        'schema_version = 1\nid = "mine"\nname = "Mine"\n', encoding="utf-8"
    )
    _attach(repo2, brain_home)
    changes = registry.detach_project(brain_home, "mine")
    assert changes["manifest_removed"] is False
    assert (repo2 / ".brain" / "project.toml").exists()


def test_detach_deactivates_row(brain_home, repo):
    _attach(repo, brain_home)
    registry.detach_project(brain_home, repo.name)
    projects = registry.list_projects(brain_home)
    assert projects == []
    projects = registry.list_projects(brain_home, include_inactive=True)
    assert len(projects) == 1 and projects[0].active is False


def test_detach_missing_repo_raises(brain_home, repo):
    _attach(repo, brain_home)
    import shutil

    shutil.rmtree(repo)
    with pytest.raises(BrainError):
        registry.detach_project(brain_home, repo.name)


def test_detach_no_marker_is_noop_for_marker(brain_home, repo):
    (repo / "AGENTS.md").write_text(USER_TEXT, encoding="utf-8", newline="")
    _attach(repo, brain_home, with_marker=False)
    changes = registry.detach_project(brain_home, repo.name)
    assert changes["marker_removed"] is False
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == USER_TEXT


def test_attach_detach_reattach_cycle(brain_home, repo):
    (repo / "AGENTS.md").write_text(USER_TEXT, encoding="utf-8", newline="")
    _attach(repo, brain_home)
    registry.detach_project(brain_home, repo.name)
    proj, created, changes = _attach(repo, brain_home)
    # the registry row persists (deactivated), so re-attach reactivates it
    assert not created and proj.active is True
    assert changes["marker_added"] and changes["manifest_created"]


def test_project_status_includes_repowise(brain_home, repo):
    _attach(repo, brain_home)
    st = registry.project_status(brain_home, registry.path_hash(str(repo)))
    assert st["repowise_cli"] in ("True", "False")
    assert st["repowise_index"] == "False"


def test_remove_project_row_and_purge(brain_home, repo):
    proj, _, _ = _attach(repo, brain_home)
    out = registry.remove_project(brain_home, proj.id)
    assert out["purged"] == "False"
    assert (brain_home / "projects" / proj.id).exists()
    assert registry.list_projects(brain_home) == []

    proj2, _, _ = _attach(repo, brain_home)
    out = registry.remove_project(brain_home, proj2.id, purge=True)
    assert out["purged"] == "True"
    assert not (brain_home / "projects" / proj2.id).exists()


CRLF_TEXT = "# Rules\r\n\r\n- one\r\n- two\r\n"


def test_attach_detach_preserves_crlf_exactly(brain_home, repo):
    """Windows line endings must survive attach+detach byte-for-byte."""
    (repo / "AGENTS.md").write_bytes(CRLF_TEXT.encode("utf-8"))
    _attach(repo, brain_home)
    attached = (repo / "AGENTS.md").read_bytes()
    assert attached.startswith(CRLF_TEXT.encode("utf-8"))
    changes = registry.detach_project(brain_home, repo.name)
    assert changes["marker_removed"] is True
    assert (repo / "AGENTS.md").read_bytes() == CRLF_TEXT.encode("utf-8")


def test_attach_detach_preserves_no_trailing_newline(brain_home, repo):
    text = "## rules\n- single\n- no trailing newline"
    (repo / "AGENTS.md").write_bytes(text.encode("utf-8"))
    _attach(repo, brain_home)
    registry.detach_project(brain_home, repo.name)
    assert (repo / "AGENTS.md").read_bytes() == text.encode("utf-8")


def test_remote_identity_priority(brain_home, repo):
    """Plan §10 priority 2: same git remote at different paths -> same id."""
    import subprocess

    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/proj.git"],
        check=True,
        capture_output=True,
    )
    proj, _, _ = _attach(repo, brain_home)
    assert proj.id == registry.remote_identity("https://github.com/acme/proj.git")
    assert proj.id != registry.path_hash(str(repo))

    repo2 = repo.parent / "clone-elsewhere"
    import shutil

    shutil.copytree(repo, repo2)
    proj2, created2, _ = _attach(repo2, brain_home)
    assert created2 is False  # same identity -> existing row refreshed
    assert proj2.id == proj.id


def test_manual_id_overrides_remote(brain_home, repo):
    import subprocess

    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://example.com/x.git"],
        check=True,
        capture_output=True,
    )
    proj, _, _ = _attach(repo, brain_home, project_id="explicit-choice")
    assert proj.id == "explicit-choice"


def test_manifest_includes_sz_tool(brain_home, repo):
    import tomllib

    _attach(repo, brain_home)
    manifest = tomllib.loads((repo / ".brain" / "project.toml").read_text(encoding="utf-8"))
    assert manifest["tools"]["sz_tool"] == "auto"
