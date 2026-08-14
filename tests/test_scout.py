"""Tests for Scout: evidence map, pre-pass, command builder (Phase 6)."""

import subprocess

import pytest

from second_brain import registry, scout
from second_brain.errors import BrainError

rg_available = pytest.mark.skipif(
    not scout.shutil.which("rg"), reason="ripgrep not installed on this machine"
)


def _make_repo(tmp_path, with_commit=True):
    """A tiny git repo: a.py and b.py mention 'widget', c.py mentions 'parser'."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    (repo / "a.py").write_text("widget handling\n", encoding="utf-8")
    (repo / "b.py").write_text("widget parser combo\n", encoding="utf-8")
    (repo / "c.py").write_text("parser only\n", encoding="utf-8")
    excluded = repo / "node_modules" / "vendor.js"
    excluded.parent.mkdir(parents=True)
    excluded.write_text("widget widget widget\n", encoding="utf-8")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "lib.py").write_text("widget hidden\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    if with_commit:
        subprocess.run(
            ["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True, capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# Template and slugs
# ---------------------------------------------------------------------------


def test_evidence_map_schema():
    assert scout.EVIDENCE_MAP_FIELDS == (
        "task",
        "likely_edit_sites",
        "relevant_tests",
        "callers_dependencies",
        "architecture_context",
        "hotspot_risk_notes",
        "unknowns",
        "recommended_next_read",
        "source_freshness",
    )
    assert set(scout.SECTION_TITLES) == set(scout.EVIDENCE_MAP_FIELDS)


def test_make_slug():
    assert scout.make_slug("Hello, World!") == "hello-world"
    assert scout.make_slug("") == "scout"
    assert scout.make_slug("   !!! ") == "scout"
    assert scout.make_slug("A B C") == "a-b-c"
    assert len(scout.make_slug("word " * 30)) <= scout.SLUG_MAX


# ---------------------------------------------------------------------------
# resolve_repo
# ---------------------------------------------------------------------------


def test_resolve_repo_path_passthrough(tmp_path):
    repo = tmp_path / "existing"
    repo.mkdir()
    assert scout.resolve_repo(tmp_path, repo) == repo.resolve()
    # A file also passes through (spec: any existing path).
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    assert scout.resolve_repo(tmp_path, f) == f.resolve()


def test_resolve_repo_missing_path_raises(brain_home, tmp_path):
    with pytest.raises(BrainError):
        scout.resolve_repo(brain_home, tmp_path / "does-not-exist")


def test_resolve_repo_project_key(brain_home, repo):
    _, _ = registry.add_project(brain_home, repo, project_id="scout-proj", name="Scout Repo")
    assert scout.resolve_repo(brain_home, "scout-proj") == repo.resolve()
    assert scout.resolve_repo(brain_home, "Scout Repo") == repo.resolve()
    with pytest.raises(BrainError):
        scout.resolve_repo(brain_home, "no-such-project")


# ---------------------------------------------------------------------------
# deterministic_prepass
# ---------------------------------------------------------------------------


@rg_available
def test_prepass_git_and_candidates(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "a.py").write_text("widget handling\nCHANGED\n", encoding="utf-8")  # dirty
    prepass = scout.deterministic_prepass(repo, "implement widget parser")
    git = prepass["git"]
    assert git["dirty"] is True
    assert git["branch"]
    assert git["head"] and git["head"] != "unknown"
    assert git["error"] is None

    candidates = prepass["candidates"]
    assert candidates["words"] == ["implement", "widget", "parser"]
    assert candidates["files"] == {"a.py": 1, "b.py": 2, "c.py": 1}
    assert candidates["errors"] == []

    # Excluded dirs never appear.
    assert not any("node_modules" in f or ".venv" in f for f in candidates["files"])


@rg_available
def test_prepass_max_candidates_cap(tmp_path):
    repo = _make_repo(tmp_path)
    prepass = scout.deterministic_prepass(repo, "widget", max_candidates=1)
    assert len(prepass["candidates"]["files"]) <= 1


def test_prepass_clean_and_repowise_grace(tmp_path):
    repo = _make_repo(tmp_path)
    prepass = scout.deterministic_prepass(repo, "no matching words here")
    assert prepass["git"]["dirty"] is False
    repowise = prepass["repowise"]
    assert isinstance(repowise["cli_available"], bool)
    assert isinstance(repowise["index_present"], bool)
    assert repowise["freshness"] in ("unknown",) or "Last sync" in repowise["freshness"]
    # No matches -> empty candidates, no exception.
    assert prepass["candidates"]["files"] == {}


def test_prepass_probes_never_raise(tmp_path):
    # git commands fail here (not a repo), rg may be missing; must not raise.
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "readme.txt").write_text("hello widget world\n", encoding="utf-8")
    prepass = scout.deterministic_prepass(plain, "widget parser")
    assert prepass["git"]["branch"] == "unknown"
    assert prepass["git"]["dirty"] is None
    assert isinstance(prepass["repowise"], dict)
    assert isinstance(prepass["candidates"], dict)


# ---------------------------------------------------------------------------
# write_evidence_map
# ---------------------------------------------------------------------------


def test_write_evidence_map_content(tmp_path):
    repo = _make_repo(tmp_path)
    prepass = scout.deterministic_prepass(repo, "fix widget parser")
    out = tmp_path / "maps"
    map_path = scout.write_evidence_map(repo, "fix widget parser", prepass, out)
    assert map_path == out / "fix-widget-parser.md"
    text = map_path.read_text(encoding="utf-8")
    assert text.startswith("# Evidence Map\n")
    for field in scout.EVIDENCE_MAP_FIELDS:
        assert f"## {scout.SECTION_TITLES[field]}" in text
    assert "## Task\n\nfix widget parser" in text
    assert "## Source Freshness\n\n- git branch:" in text
    assert "- repowise cli:" in text
    assert "## Deterministic Pre-pass" in text
    assert "- candidates:" in text
    # Other sections keep their placeholders.
    assert "## Likely Edit Sites\n\n(fill me)" in text
    assert "## Unknowns\n\n(fill me)" in text


def test_write_evidence_map_suffix_collision(tmp_path):
    repo = _make_repo(tmp_path)
    prepass = scout.deterministic_prepass(repo, "same task")
    out = tmp_path / "maps"
    first = scout.write_evidence_map(repo, "same task", prepass, out)
    second = scout.write_evidence_map(repo, "same task", prepass, out)
    third = scout.write_evidence_map(repo, "same task", prepass, out)
    assert first == out / "same-task.md"
    assert second == out / "same-task-1.md"
    assert third == out / "same-task-2.md"
    assert first.exists() and second.exists() and third.exists()


# ---------------------------------------------------------------------------
# scout_command
# ---------------------------------------------------------------------------


def test_scout_command_shape(tmp_path):
    repo = _make_repo(tmp_path)
    map_path = tmp_path / "maps" / "evidence.md"
    cmd = scout.scout_command(repo, "fix the widget", map_path)
    assert cmd[0] == "bash"
    assert "C:/Tools/prime-agent/prime-agent.sh" in cmd
    assert "-p" in cmd
    assert "-t" in cmd and "ipython,bash" in cmd
    assert "--model" in cmd and "deepseek/deepseek-v4-flash" in cmd
    assert "--cwd" in cmd and str(repo) in cmd
    assert "--offline" in cmd
    assert "--daemon-socket" in cmd
    prompt = cmd[-1]
    assert "fix the widget" in prompt
    assert str(map_path) in prompt
    assert "read-only" in prompt.lower()


def test_scout_command_unique_daemon_socket(tmp_path):
    repo = _make_repo(tmp_path)
    map_path = tmp_path / "m.md"
    a = scout.scout_command(repo, "t", map_path)
    b = scout.scout_command(repo, "t", map_path)
    socket_a = a[a.index("--daemon-socket") + 1]
    socket_b = b[b.index("--daemon-socket") + 1]
    assert socket_a.startswith("scout-")
    assert socket_a != socket_b


def test_scout_command_ext_optional(tmp_path):
    repo = _make_repo(tmp_path)
    map_path = tmp_path / "m.md"
    plain = scout.scout_command(repo, "t", map_path)
    assert "-e" not in plain
    with_ext = scout.scout_command(repo, "t", map_path, ext="C:/ext")
    assert "-e" in with_ext and "C:/ext" in with_ext


def test_scout_command_no_shell_injection(tmp_path):
    repo = _make_repo(tmp_path)
    map_path = tmp_path / "m.md"
    nasty = 'weird "quoted" `tick` $(sub) ; rm -rf / & stuff {braces}'
    cmd = scout.scout_command(repo, nasty, map_path)
    assert isinstance(cmd, list)
    assert cmd[-1] == scout.SCOUT_PROMPT_TEMPLATE.replace("{task}", nasty).replace(
        "{map_path}", str(map_path)
    )
    assert "rm -rf" not in " ".join(cmd[:8])  # never reaches the argv prefix
