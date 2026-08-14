"""Tests for the Environment Steward (Phase 8).

No real processes are killed or probed: all PowerShell/taskkill subprocess
probes are monkeypatched.
"""

import json
import subprocess
import uuid

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from second_brain import envsteward
from second_brain.errors import BrainError


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _commit_repo(repo):
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "readme.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    _commit_repo(repo)
    return repo


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_git_fields(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "readme.md").write_text("hello\nchanged\n", encoding="utf-8")  # dirty
    snap = envsteward.snapshot(tmp_path, repo)
    assert snap["repo"] == str(repo.resolve())
    assert snap["branch"]  # master/main
    assert snap["head"] and len(snap["head"]) >= 4
    assert snap["dirty"] is True
    assert isinstance(snap["worktrees"], list)
    assert snap["ts"]
    assert snap["children"]["available"] is False
    assert snap["brain_version"] == "unknown"  # tmp home has no VERSION


def test_snapshot_dirty_flips_after_commit(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "readme.md").write_text("hello\nchanged\n", encoding="utf-8")
    assert envsteward.snapshot(tmp_path, repo)["dirty"] is True
    _commit_repo(repo)
    assert envsteward.snapshot(tmp_path, repo)["dirty"] is False


def test_snapshot_missing_git_graced(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    snap = envsteward.snapshot(tmp_path, plain)  # must not raise
    assert snap["branch"] == {"error": "git rev-parse --abbrev-ref HEAD failed (not a git repo?)"}
    assert isinstance(snap["head"], dict) and "error" in snap["head"]
    assert isinstance(snap["dirty"], dict) and "error" in snap["dirty"]
    assert isinstance(snap["worktrees"], dict) and "error" in snap["worktrees"]


def test_snapshot_language_package_lockfiles(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("", encoding="utf-8")
    (repo / "uv.lock").write_text("", encoding="utf-8")
    (repo / "package.json").write_text("{}", encoding="utf-8")
    (repo / "package-lock.json").write_text("{}", encoding="utf-8")
    snap = envsteward.snapshot(tmp_path, repo)
    assert snap["language"] == ["python", "javascript"]
    assert snap["package_manager"] == ["uv", "npm"]
    assert snap["lockfiles"] == ["uv.lock", "package-lock.json"]


def test_snapshot_tools_dict(tmp_path):
    snap = envsteward.snapshot(tmp_path, tmp_path)
    assert set(snap["tools"]) == set(envsteward.TOOL_NAMES)
    assert all(value is None or isinstance(value, str) for value in snap["tools"].values())
    assert snap["tools"]["git"]  # git is on PATH


def test_snapshot_repowise_freshness_never_raises(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    snap = envsteward.snapshot(tmp_path, repo)
    assert isinstance(snap["repowise_freshness"], str)
    assert snap["repowise_freshness"] in ("unknown",) or "Last sync" in snap["repowise_freshness"]


def test_snapshot_persists_with_session(brain_home, repo):
    snap = envsteward.snapshot(brain_home, repo, session_id="s1")
    target = brain_home / "state" / "sessions" / "s1" / "environment.json"
    assert target.is_file()
    stored = _read_json(target)
    assert stored["repo"] == snap["repo"]
    assert stored["ts"] == snap["ts"]
    with pytest.raises(BrainError):
        envsteward.snapshot(brain_home, repo, session_id="bad/id")


# ---------------------------------------------------------------------------
# Process registry
# ---------------------------------------------------------------------------


def test_register_and_list_processes(brain_home, monkeypatch):
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "2026-01-01T00:00:00+00:00")
    record = envsteward.register_process(
        brain_home, 4242, "C:/tools/agent/python.exe", "second-brain", session_id="s1"
    )
    assert record["pid"] == 4242
    assert record["start_time"] == "2026-01-01T00:00:00+00:00"
    assert record["exe"] == "C:/tools/agent/python.exe"
    assert record["token"] == "second-brain"
    assert record["session"] == "s1"
    assert record["identity_verified"] is True
    records = envsteward.list_processes(brain_home)
    assert len(records) == 1 and records[0] == record
    assert (brain_home / "state" / "ownership" / "processes.json").is_file()


def test_register_null_start_time_marks_unverified(brain_home, monkeypatch):
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: None)
    record = envsteward.register_process(brain_home, 1, "x.exe", "second-brain")
    assert record["start_time"] is None
    assert record["identity_verified"] is False
    assert envsteward.list_processes(brain_home)[0]["identity_verified"] is False


def test_register_validates(brain_home):
    with pytest.raises(BrainError, match="pid"):
        envsteward.register_process(brain_home, -3, "x.exe", "t")
    with pytest.raises(BrainError, match="exe"):
        envsteward.register_process(brain_home, 1, "  ", "t")
    with pytest.raises(BrainError, match="token"):
        envsteward.register_process(brain_home, 1, "x.exe", "")


def test_corrupt_registry_raises(brain_home):
    path = brain_home / "state" / "ownership" / "processes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        envsteward.list_processes(brain_home)
    assert str(path) in str(exc.value)
    with pytest.raises(BrainError):
        envsteward.register_process(brain_home, 1, "x.exe", "t")


# ---------------------------------------------------------------------------
# verify_process: PID-reuse safety
# ---------------------------------------------------------------------------


def test_verify_process_matches(brain_home, monkeypatch):
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T1")
    envsteward.register_process(brain_home, 100, "C:/tools/python.exe", "second-brain")
    assert envsteward.verify_process(brain_home, 100, "C:/tools/python.exe") is True
    assert envsteward.verify_process(brain_home, 100, "python.exe") is True  # exe-name match


def test_verify_process_pid_reuse_detected(brain_home, monkeypatch):
    # Recorded start time T1, but the live process now has start time T2:
    # the PID was reused by a different process -> must NOT verify.
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T1")
    envsteward.register_process(brain_home, 100, "python.exe", "second-brain")
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T2")
    assert envsteward.verify_process(brain_home, 100, "python.exe") is False
    # Different exe name also fails.
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T1")
    assert envsteward.verify_process(brain_home, 100, "other.exe") is False
    # Unknown pid fails.
    assert envsteward.verify_process(brain_home, 999, "python.exe") is False
    # Unverified records never verify.
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: None)
    assert envsteward.verify_process(brain_home, 100, "python.exe") is False


# ---------------------------------------------------------------------------
# cleanup_owned
# ---------------------------------------------------------------------------


def _seed_registry(brain_home, monkeypatch):
    """One owned+verified record, one unverified, one foreign-token, one
    start-time-mismatched owned record."""
    times = {111: "T1", 222: "T2", 333: "T3", 444: "T4"}

    def probe(pid):
        return times.get(pid)

    monkeypatch.setattr(envsteward, "_probe_start_time", probe)
    envsteward.register_process(brain_home, 111, "owned.exe", "second-brain")  # verified, live T1
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: None)
    envsteward.register_process(brain_home, 222, "unver.exe", "second-brain")  # unverified
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T3")
    envsteward.register_process(brain_home, 333, "foreign.exe", "other-tool")  # foreign token
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T4")
    envsteward.register_process(brain_home, 444, "reused.exe", "second-brain")  # stored T4
    # Simulate PID reuse: live start time now differs from the stored one.
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T5" if pid == 444 else times.get(pid))
    return times


def test_cleanup_owned_dry_run_kills_nothing(brain_home, monkeypatch):
    _seed_registry(brain_home, monkeypatch)
    killed_calls = []
    monkeypatch.setattr(envsteward, "_taskkill", lambda pid: killed_calls.append(pid) or True)
    result = envsteward.cleanup_owned(brain_home, dry_run=True)
    assert killed_calls == []  # dry run never kills
    assert [k["pid"] for k in result["killed"]] == [111]
    assert result["killed"][0]["dry_run"] is True
    pids = {s["pid"]: s["reason"] for s in result["skipped"]}
    assert pids[222].startswith("identity unverified")
    assert pids[333].startswith("token")
    assert pids[444].startswith("start_time mismatch")
    assert result["unknown"] == []


def test_cleanup_owned_real_path_guarded(brain_home, monkeypatch):
    _seed_registry(brain_home, monkeypatch)
    killed_calls = []
    monkeypatch.setattr(envsteward, "_taskkill", lambda pid: killed_calls.append(pid) or True)
    verified = []

    def fake_verify(home, pid, exe):
        verified.append((pid, exe))
        return pid == 111

    monkeypatch.setattr(envsteward, "verify_process", fake_verify)
    result = envsteward.cleanup_owned(brain_home, dry_run=False)
    assert killed_calls == [111]
    assert verified == [(111, "owned.exe")]  # guard ran immediately before the kill
    assert [k["pid"] for k in result["killed"]] == [111]
    assert 444 not in [k["pid"] for k in result["killed"]]


def test_cleanup_unknown_live_identity(brain_home, monkeypatch):
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T1")
    envsteward.register_process(brain_home, 555, "ghost.exe", "second-brain")
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: None)  # live probe fails
    result = envsteward.cleanup_owned(brain_home, dry_run=True)
    assert [u["pid"] for u in result["unknown"]] == [555]
    assert result["killed"] == []


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    pids=st.lists(st.integers(min_value=1, max_value=10**6), min_size=1, max_size=10),
    exes=st.lists(st.text(alphabet="abcXYZ0123", min_size=1, max_size=12), min_size=1, max_size=5),
)
def test_process_registry_random_sequences(brain_home, pids, exes, monkeypatch):
    monkeypatch.setattr(envsteward, "_probe_start_time", lambda pid: "T-fixed")
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    seen = []
    for i, pid in enumerate(pids):
        exe = exes[i % len(exes)] + ".exe"
        record = envsteward.register_process(home, pid, exe, "second-brain", session_id=f"sid{i}")
        seen.append(record)
        assert record["pid"] == pid
        assert record["identity_verified"] is True
        current = envsteward.list_processes(home)
        assert len(current) == i + 1
        assert current[-1]["pid"] == pid  # append order
    final = envsteward.list_processes(home)
    assert [r["pid"] for r in final] == [r["pid"] for r in seen]
    assert [r["exe"] for r in final] == [r["exe"] for r in seen]
