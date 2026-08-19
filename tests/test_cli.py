"""End-to-end CLI tests: run brainctl as a subprocess with a sanitized env."""

import json
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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _git_repo_with_commit(repo: Path, filename: str, content: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")


def test_action_cache_search_hits_on_second_call_and_misses_after_a_commit(tmp_path):
    """Phase R5: narrowest Brain-owned execution-bypass layer (Prime's
    tool_call hook cannot itself skip execution — see
    outputs/reports/rc4/02-prime-live-callgraph.md and
    outputs/reports/rc4/05-action-cache-live.md)."""
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    repo = tmp_path / "repo"
    _git_repo_with_commit(repo, "hello.py", "def hello():\n    return 'world'\n")

    r1 = run_cli(home, "action-cache", "search", "hello", "--path", str(repo), "--json")
    assert r1.returncode == 0, r1.stderr
    out1 = json.loads(r1.stdout)
    assert out1["hit"] is False
    assert "hello.py" in out1["content"]

    r2 = run_cli(home, "action-cache", "search", "hello", "--path", str(repo), "--json")
    out2 = json.loads(r2.stdout)
    assert out2["hit"] is True
    assert out2["content"] == out1["content"]

    # A new commit changes the git tree hash -> the proof no longer matches -> miss.
    (repo / "hello.py").write_text("def hello():\n    return 'world2'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "change")

    r3 = run_cli(home, "action-cache", "search", "hello", "--path", str(repo), "--json")
    out3 = json.loads(r3.stdout)
    assert out3["hit"] is False


def test_action_cache_search_non_git_dir_never_caches(tmp_path):
    """No git tree to gate on -> validate_proof would never re-check content,
    so the search command must compute fresh every time rather than cache."""
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "note.txt").write_text("marker_value_xyz\n", encoding="utf-8")

    r1 = run_cli(home, "action-cache", "search", "marker_value_xyz", "--path", str(plain), "--json")
    assert r1.returncode == 0, r1.stderr
    out1 = json.loads(r1.stdout)
    assert out1["hit"] is False

    r2 = run_cli(home, "action-cache", "search", "marker_value_xyz", "--path", str(plain), "--json")
    out2 = json.loads(r2.stdout)
    assert out2["hit"] is False


def test_worker_plane_ceiling_block_complete_respawn(tmp_path):
    """Phase R7: the required proof scenario end to end — spawn 2 (allowed),
    spawn a 3rd (blocked), complete one, spawn a new one (allowed again).
    Prime has no extension hook for subagent spawn (see
    outputs/reports/rc4/02-prime-live-callgraph.md), so this CLI command is
    the actual enforcement surface (outputs/reports/rc4/07-worker-plane-live.md)."""
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0

    r1 = run_cli(home, "worker-plane", "spawn", "sess-1", "task1", "--max-workers", "2", "--json")
    assert r1.returncode == 0, r1.stderr
    w1 = json.loads(r1.stdout)
    assert w1["spawned"] is True
    worker1_id = w1["worker_id"]

    r2 = run_cli(home, "worker-plane", "spawn", "sess-1", "task2", "--max-workers", "2", "--json")
    assert r2.returncode == 0, r2.stderr
    assert json.loads(r2.stdout)["spawned"] is True

    r3 = run_cli(home, "worker-plane", "spawn", "sess-1", "task3", "--max-workers", "2", "--json")
    assert r3.returncode == 2  # blocked: ceiling reached
    out3 = json.loads(r3.stdout)
    assert out3["spawned"] is False
    assert "ceiling" in out3["error"].lower()

    r_status = run_cli(home, "worker-plane", "status", "sess-1", "--max-workers", "2", "--json")
    assert json.loads(r_status.stdout) == {"active_workers": 2, "max_concurrent_workers": 2}

    r_complete = run_cli(
        home, "worker-plane", "complete", "sess-1", worker1_id,
        "--status", "COMPLETED", "--summary", "done", "--json",
    )
    assert r_complete.returncode == 0, r_complete.stderr
    assert json.loads(r_complete.stdout) == {
        "completed": True, "worker_id": worker1_id, "status": "COMPLETED",
    }

    r_status2 = run_cli(home, "worker-plane", "status", "sess-1", "--max-workers", "2", "--json")
    assert json.loads(r_status2.stdout)["active_workers"] == 1

    r4 = run_cli(home, "worker-plane", "spawn", "sess-1", "task4", "--max-workers", "2", "--json")
    assert r4.returncode == 0, r4.stderr
    assert json.loads(r4.stdout)["spawned"] is True


def test_fresh_verifier_record_parses_real_verdict_never_fabricates(tmp_path):
    """Phase R9: fresh-verifier record only ever parses a verdict from a raw
    response file that already exists on disk — there is no code path that
    can produce PASS/FAIL without it (see
    outputs/reports/rc4/09-fresh-verifier.md)."""
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("## Requirement\nDo the thing.\n", encoding="utf-8")
    raw_response_file = tmp_path / "raw_response.txt"
    raw_response_file.write_text(
        "Conclusion: implementation matches requirement\nResult: PASS\nConfidence: 0.9\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "evidence"

    r = run_cli(
        home, "fresh-verifier", "record",
        "--out", str(out_dir),
        "--prompt-file", str(prompt_file),
        "--raw-response", str(raw_response_file),
        "--provider", "anthropic",
        "--model", "claude-sonnet-5",
        "--host", "claude-code",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["verdict"] == {"verdict": "PASS", "confidence": 0.9}
    assert out["provider"] == "anthropic"
    assert out["session_id"] == {
        "available": False, "reason": "host does not expose provider run ID"
    }

    written = (out_dir / "raw-response.txt").read_text(encoding="utf-8")
    assert written == raw_response_file.read_text(encoding="utf-8")
    verdict_json = json.loads((out_dir / "verdict.json").read_text(encoding="utf-8"))
    assert verdict_json == {"verdict": "PASS", "confidence": 0.9}


def test_fresh_verifier_record_unparseable_response_never_guesses(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("prompt text", encoding="utf-8")
    raw_response_file = tmp_path / "raw_response.txt"
    raw_response_file.write_text("This response never states a clear result.", encoding="utf-8")

    r = run_cli(
        home, "fresh-verifier", "record",
        "--out", str(tmp_path / "evidence"),
        "--prompt-file", str(prompt_file),
        "--raw-response", str(raw_response_file),
        "--json",
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["verdict"] == {"verdict": "UNPARSEABLE", "confidence": None}


def test_fresh_verifier_record_missing_raw_response_file_errors(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("prompt text", encoding="utf-8")

    r = run_cli(
        home, "fresh-verifier", "record",
        "--out", str(tmp_path / "evidence"),
        "--prompt-file", str(prompt_file),
        "--raw-response", str(tmp_path / "does-not-exist.txt"),
    )
    assert r.returncode == 2
    assert "not found" in r.stderr.lower()
