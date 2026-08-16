"""End-to-end CLI tests: run brainctl as a subprocess with a sanitized env."""

import os
import subprocess
import sys
from pathlib import Path


def _env():
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    return env


def run_cli(home: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=cwd or home,
        timeout=120,
    )


def test_init_doctor_status_flow(tmp_path):
    home = tmp_path / "brain"
    r = run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    assert (home / "db" / "brain.sqlite").exists()
    assert (home / ".git").exists()

    r = run_cli(home, "doctor")
    assert r.returncode == 0, r.stdout + r.stderr

    r = run_cli(home, "status")
    assert r.returncode == 0
    from second_brain import db

    expected = max(int(p.name[:4]) for p in db.migration_files())
    assert f"schema v{expected}" in r.stdout


def test_init_refuses_non_empty_non_brain(tmp_path):
    home = tmp_path / "not-a-brain"
    home.mkdir()
    (home / "important-user-data.txt").write_text("do not touch")
    r = run_cli(home, "init")
    assert r.returncode == 2
    assert (
        "important-user-data.txt" not in "".join([p.name for p in (home / "db").iterdir()])
        if (home / "db").exists()
        else True
    )
    assert not (home / "db").exists()


def test_project_add_list_status(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)

    r = run_cli(home, "project", "add", str(repo), "--name", "DemoRepo")
    assert r.returncode == 0, r.stderr
    assert "Attached project 'DemoRepo'" in r.stdout
    assert (repo / ".brain" / "project.toml").exists()
    assert (repo / "AGENTS.md").exists()

    r = run_cli(home, "project", "list")
    assert "DemoRepo" in r.stdout

    r = run_cli(home, "project", "status", "DemoRepo")
    assert r.returncode == 0
    assert "repo_exists" in r.stdout


def test_backup_restore_cli(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    assert run_cli(home, "project", "add", str(repo)).returncode == 0

    r = run_cli(home, "backup", "--note", "cli test")
    assert r.returncode == 0, r.stderr
    bdir = r.stdout.strip().splitlines()[-1].split(":", 1)[1].strip()

    home2 = tmp_path / "brain2"
    assert run_cli(home2, "init").returncode == 0
    r = run_cli(home2, "restore", bdir, "--force")
    assert r.returncode == 0, r.stderr
    r = run_cli(home2, "project", "list")
    assert "repo" in r.stdout.lower()


def test_unknown_project_status_errors(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    r = run_cli(home, "project", "status", "zzz")
    assert r.returncode == 2
    assert "error" in r.stderr


def test_home_flag_after_subcommand(tmp_path):
    """`brainctl init --home X` must work like `brainctl --home X init`."""
    home = tmp_path / "brain"
    r = run_cli(home, "init", "--home", str(home))
    assert r.returncode == 0, r.stderr
    assert (home / "db" / "brain.sqlite").exists()


def test_home_after_leaf_subcommands(tmp_path):
    """--home must work after leaf subcommands (verifier finding)."""
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    r = run_cli(home, "project", "add", "--home", str(home), str(repo), "--name", "LeafRepo")
    assert r.returncode == 0, r.stderr
    r = run_cli(home, "project", "list", "--home", str(home))
    assert "LeafRepo" in r.stdout


# ---------------------------------------------------------------------------
# P3-cleanup regression: memory add must not silently default to second-brain
# (pre-P3 truth cleanup; Outcome B minimal fix)
# ---------------------------------------------------------------------------


def test_memory_add_without_project_fails_clearly(tmp_path):
    home = tmp_path / "brain"
    r = run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    r = run_cli(home, "memory", "add", "unattached title", "unattached body")
    assert r.returncode == 2  # fails clearly, never silently second-brain
    assert "requires --project" in r.stdout
    from second_brain import semantic

    assert semantic.list_memories(home) == []  # nothing written


def test_memory_add_explicit_project_still_works(tmp_path):
    home = tmp_path / "brain"
    r = run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    r = run_cli(home, "memory", "add", "scoped title", "scoped body", "--project", "second-brain")
    assert r.returncode == 0, r.stderr
    from second_brain import semantic

    rows = semantic.list_memories(home)
    assert rows[0]["project_id"] == "second-brain"


def test_memory_add_resolves_registered_project_from_cwd(tmp_path):
    home = tmp_path / "brain"
    r = run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    from second_brain import registry

    proj_dir = tmp_path / "proj-x"
    proj_dir.mkdir()
    registry.add_project(home, proj_dir, name="Proj X", project_id="proj-x")
    r = run_cli(home, "memory", "add", "resolved title", "resolved body", cwd=proj_dir)
    assert r.returncode == 0, r.stderr
    from second_brain import semantic

    rows = semantic.list_memories(home)
    assert rows[0]["project_id"] == "proj-x"
