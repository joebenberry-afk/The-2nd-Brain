"""End-to-end CLI tests: run brainctl as a subprocess with a sanitized env."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


from second_brain import semantic, working_set

def _env():
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return env

def run_cli(
    home: Path, *args: str, cwd: Path | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess:
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=cwd or home,
        timeout=120,
        input=stdin,
    )
def test_remember_one_line_creates_memory_with_evidence(tmp_path, monkeypatch):
    home = tmp_path / "brain"
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    source = repo / "notes.txt"
    source.write_text("first line\nsecond line\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )
    monkeypatch.setenv("SECOND_BRAIN_PROJECT", "demo")
    initialized = run_cli(home, "init", cwd=repo)
    assert initialized.returncode == 0, initialized.stderr

    result = run_cli(
        home,
        "remember",
        "Use bounded memory I/O",
        "--evidence",
        "notes.txt:1-2",
        cwd=repo,
    )

    assert result.returncode == 0, result.stderr
    memory_id = result.stdout.strip()
    assert memory_id.startswith("mem-")
    row = semantic.show_memory(home, memory_id)["row"]
    assert row["title"] == "Use bounded memory I/O"
    assert row["project_id"] == "demo"
    assert row["evidence_grade"] == "OBSERVED"
    conn = sqlite3.connect(home / "db" / "brain.sqlite")
    try:
        source_row = conn.execute(
            "SELECT path, range_start, range_end FROM memory_sources WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
    finally:
        conn.close()
    assert source_row is not None
    assert source_row[0] == "notes.txt"
    assert source_row[1:] == (1, 2)


def test_recall_prints_freshness_state(tmp_path, monkeypatch):
    home = tmp_path / "brain"
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    source = repo / "notes.txt"
    source.write_text("bounded memory I/O\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )
    monkeypatch.setenv("SECOND_BRAIN_PROJECT", "demo")
    initialized = run_cli(home, "init", cwd=repo)
    assert initialized.returncode == 0, initialized.stderr
    added = run_cli(home, "remember", "Use bounded memory I/O", "--evidence", "notes.txt", cwd=repo)
    assert added.returncode == 0, added.stderr
    memory_id = added.stdout.strip()

    result = run_cli(home, "recall", "bounded memory I/O", cwd=repo)
    assert result.stdout.count("\n") <= 3
    assert f"VERIFIED_CURRENT" in result.stdout
    assert memory_id in result.stdout
    assert "Use bounded memory I/O" in result.stdout



def test_remember_rejects_multiline_and_unsupported_flags(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    multiline = run_cli(home, "remember", "first\nsecond")
    unsupported = run_cli(home, "remember", "claim", "--project", "demo")
    assert multiline.returncode == 2
    assert "single line" in multiline.stderr
    assert unsupported.returncode == 2
    assert "unrecognized arguments" in unsupported.stderr


def test_remember_validates_grade_and_evidence_range(tmp_path):
    home = tmp_path / "brain"
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "notes.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )
    assert run_cli(home, "init", cwd=repo).returncode == 0
    bad_grade = run_cli(home, "remember", "claim", "--grade", "INFERRED", cwd=repo)
    bad_range = run_cli(home, "remember", "claim", "--evidence", "notes.txt:1-2", cwd=repo)
    assert bad_grade.returncode == 2
    assert bad_range.returncode == 2
    assert "invalid choice" in bad_grade.stderr
    assert "exceeds file line count" in bad_range.stderr


def test_recall_abstains_and_truncates_body(tmp_path, monkeypatch):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    monkeypatch.setenv("SECOND_BRAIN_PROJECT", "demo")
    semantic.add_memory(
        home,
        "Long body fact",
        "longbody " + ("x" * 300),
        scope="project",
        project_id="demo",
    )
    recalled = run_cli(home, "recall", "longbody", cwd=home)
    assert recalled.returncode == 0
    line = recalled.stdout.strip()
    assert line.startswith("[UNKNOWN] ")
    assert len(line.split(" — ", 1)[1].split(" (mem-", 1)[0]) == 200
    absent = run_cli(home, "recall", "unmatched gibberish", cwd=home)
    assert absent.returncode == 0
    assert absent.stdout.startswith("NO_INJECTION ")


def test_recall_question_wins_over_unrelated_capsule(tmp_path, monkeypatch):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    monkeypatch.setenv("SECOND_BRAIN_PROJECT", "demo")
    semantic.add_memory(
        home,
        "Beta memory",
        "beta-only retrieval fact",
        scope="project",
        project_id="demo",
    )
    recall_session = "brainctl-recall-" + hashlib.sha256(
        "beta-only retrieval".encode("utf-8")
    ).hexdigest()[:16]
    working_set.init_capsule(home, recall_session, "alpha-only objective")

    result = run_cli(home, "recall", "beta-only retrieval", cwd=home)

    assert result.returncode == 0, result.stderr
    assert "Beta memory" in result.stdout
    assert "alpha-only objective" not in result.stdout


def test_simplification_review_cli_persists_defer_and_deduplicates(tmp_path):
    home = tmp_path / "brain"
    project = tmp_path / "project"
    project.mkdir()
    args = (
        "simplification",
        "review",
        "--project-root",
        str(project),
        "--project",
        "demo",
        "--session",
        "s1",
        "--task-id",
        "t1",
        "--review-id",
        "r1",
        "--outcome",
        "defer",
        "--reason-code",
        "duplicate-wrapper",
        "--affected-hash",
        "a" * 64,
        "--deferred-hash",
        "b" * 64,
        "--json",
    )
    first = run_cli(home, *args)
    assert first.returncode == 0, first.stderr
    second = run_cli(home, *args)
    assert second.returncode == 0, second.stderr
    assert (project / "simplification-debt.md").read_text(encoding="utf-8").count("DEBT-") == 1


def _stop_args(session: str, task_id: str) -> tuple[str, ...]:
    return (
        "stop",
        "decide",
        "--session",
        session,
        "--task-id",
        task_id,
        "--parent-session-id",
        "parent-1",
        "--worker-session-id",
        session,
        "--stop-id",
        f"stop-{task_id}",
        "--reason-code",
        "completion_proven",
        "--triggering-condition",
        "completion_condition_satisfied",
        "--verification-state",
        "passed",
        "--completion-condition-state",
        "satisfied",
        "--final-substantive-event",
        "task_result",
        "--json",
    )


def test_stop_decide_allows_proven_completion_and_records_bounded_evidence(tmp_path):
    home = tmp_path / "brain"
    session = "omp-success"
    assert (
        run_cli(home, "requirements", "add", session, "ship the task", "--importance", "critical")
        .returncode
        == 0
    )
    assert (
        run_cli(home, "requirements", "evidence", session, "REQ-001", "focused test passed")
        .returncode
        == 0
    )
    assert run_cli(home, "requirements", "status", session, "REQ-001", "verified").returncode == 0

    result = run_cli(home, *_stop_args(session, "task-success"))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "stop"
    assert payload["stop_id"] == "stop-task-success"
    assert payload["verification_state"] == "passed"
    assert payload["completion_condition_state"] == "satisfied"
    assert payload["continuation_forbidden"] is True

    searched = run_cli(home, "ledger", "search", session, "--query", "stop_decided")
    assert searched.returncode == 0
    assert "completion_proven" in searched.stdout


def test_stop_decide_does_not_false_positive_when_acceptance_is_unresolved(tmp_path):
    home = tmp_path / "brain"
    session = "omp-incomplete"
    assert (
        run_cli(home, "requirements", "add", session, "ship the task", "--importance", "critical")
        .returncode
        == 0
    )

    result = run_cli(home, *_stop_args(session, "task-incomplete"))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "continue"
    assert payload["reason_code"] == "requirements_unresolved"
    assert payload["continuation_forbidden"] is False


def test_stop_decide_stops_failed_or_blocked_work(tmp_path):
    home = tmp_path / "brain"
    session = "omp-blocked"
    args = list(_stop_args(session, "task-blocked"))
    args[args.index("--reason-code") + 1] = "verification_failed"
    args[args.index("--triggering-condition") + 1] = "verification_failed"
    args[args.index("--verification-state") + 1] = "failed"
    args[args.index("--completion-condition-state") + 1] = "failed"
    result = run_cli(home, *args)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "stop"
    assert payload["continuation_forbidden"] is True

def test_verify_gate_blocks_stop_until_risk_actions_pass(tmp_path):
    home = tmp_path / "brain"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# gate\n", encoding="utf-8")
    gate_file = tmp_path / "gate.json"
    actions = [
        "targeted_test=passed",
        "typecheck_or_compile=passed",
        "diff_sanity=passed",
    ]
    gate = run_cli(
        home,
        "verify",
        "gate",
        "gate-cli",
        str(repo),
        "--file",
        "README.md",
        "--criticality",
        "LOW",
        "--action",
        actions[0],
        "--action",
        actions[1],
        "--action",
        actions[2],
        "--out",
        str(gate_file),
        "--json",
    )
    assert gate.returncode == 0, gate.stderr
    payload = json.loads(gate.stdout)
    assert payload["completion_allowed"] is True
    assert gate_file.exists()

    blocked_gate = dict(payload)
    blocked_gate["completion_allowed"] = False
    blocked_gate["decision_reason"] = "verification_actions_unresolved"
    blocked_file = tmp_path / "blocked-gate.json"
    blocked_file.write_text(json.dumps(blocked_gate), encoding="utf-8")
    stop = run_cli(
        home,
        "stop",
        "decide",
        "--session",
        "gate-cli",
        "--task-id",
        "task-gate-cli",
        "--stop-id",
        "stop-gate-cli",
        "--reason-code",
        "completion_proven",
        "--triggering-condition",
        "completion_condition_satisfied",
        "--verification-state",
        "passed",
        "--completion-condition-state",
        "satisfied",
        "--final-substantive-event",
        "gate",
        "--gate-file",
        str(blocked_file),
        "--json",
    )
    assert stop.returncode == 0, stop.stderr
    stop_payload = json.loads(stop.stdout)
    assert stop_payload["decision"] == "continue"
    assert stop_payload["reason_code"] == "accuracy_gate_blocked"

def test_independent_verifier_cli_binds_fresh_pass_to_high_gate(tmp_path):
    home = tmp_path / "brain"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# gate\n", encoding="utf-8")
    response = tmp_path / "response.txt"
    response.write_text("Result: PASS\nConfidence: 0.9\n", encoding="utf-8")
    verification = tmp_path / "verification.json"
    hashes = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    independent = run_cli(
        home,
        "verify",
        "independent",
        "--response-file",
        str(response),
        "--verification-id",
        "ver-cli",
        "--task-id",
        "task-cli",
        "--verifier-session-id",
        "verifier-cli",
        "--implementation-session-id",
        "implementation-cli",
        "--task-hash",
        hashes[0],
        "--requirements-hash",
        hashes[1],
        "--diff-hash",
        hashes[2],
        "--evidence-set-hash",
        hashes[3],
        "--out",
        str(verification),
        "--json",
    )
    assert independent.returncode == 0, independent.stderr
    assert json.loads(independent.stdout)["verdict"] == "PASS"

    actions = [
        "targeted_test=passed",
        "typecheck_or_compile=passed",
        "diff_sanity=passed",
        "targeted_plus_relevant_tests=passed",
        "requirement_ledger=passed",
        "affected_file_review=passed",
        "simplification_check=passed",
        "repowise_impact_context=passed",
        "independent_intent_verifier=passed",
        "negative_adversarial_tests=passed",
        "rollback_check=passed",
    ]
    args = [
        "verify",
        "gate",
        "gate-cli",
        str(repo),
        "--file",
        "README.md",
        "--criticality",
        "HIGH",
        "--verification-file",
        str(verification),
        "--task-hash",
        hashes[0],
        "--requirements-hash",
        hashes[1],
        "--diff-hash",
        hashes[2],
        "--evidence-set-hash",
        hashes[3],
        "--task-id",
        "task-cli",
        "--parent-session-id",
        "implementation-cli",
        "--action",
        actions[0],
        "--action",
        actions[1],
        "--action",
        actions[2],
        "--action",
        actions[3],
        "--action",
        actions[4],
        "--action",
        actions[5],
        "--action",
        actions[6],
        "--action",
        actions[7],
        "--action",
        actions[8],
        "--action",
        actions[9],
        "--action",
        actions[10],
        "--json",
    ]
    gate = run_cli(home, *args)
    assert gate.returncode == 0, gate.stderr
    gate_payload = json.loads(gate.stdout)
    assert gate_payload["completion_allowed"] is True
    assert gate_payload["verification_id"] == "ver-cli"

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


def test_vmem_claim_pages_cli_end_to_end(tmp_path):
    """Defect B (RC4 proactive-paging-repair pass): `second_brain vmem
    claim-pages <session> [--json]` reads a small bounded JSON payload from
    stdin and prints exactly the obj_ids actually claimed."""
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0

    content_file = tmp_path / "finding.txt"
    content_file.write_text("proactive paging target", encoding="utf-8")
    store_res = run_cli(
        home, "vmem", "store", "sess-claim-cli", "RESEARCH_RESULT", "Claim target",
        str(content_file), "--json",
    )
    assert store_res.returncode == 0, store_res.stderr
    obj_id = json.loads(store_res.stdout)["obj_id"]

    claim_res = run_cli(
        home, "vmem", "claim-pages", "sess-claim-cli", "--json",
        stdin=json.dumps({"candidates": [{"obj_id": obj_id, "kind": "RESEARCH_RESULT"}]}),
    )
    assert claim_res.returncode == 0, claim_res.stderr
    assert json.loads(claim_res.stdout) == [obj_id]

    list_res = run_cli(home, "vmem", "list", "sess-claim-cli", "--json")
    assert list_res.returncode == 0
    items = json.loads(list_res.stdout)
    assert items[0]["obj_id"] == obj_id
    assert items[0]["residency_state"] == "EVICTED"


def test_vmem_claim_pages_cli_second_claim_of_same_object_is_not_claimed_again(tmp_path):
    """CAS regression at the CLI layer: a second `claim-pages` request for
    an already-EVICTED object reports it as NOT claimed -- deterministic,
    safe, idempotent, no error."""
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0

    content_file = tmp_path / "finding.txt"
    content_file.write_text("race target", encoding="utf-8")
    store_res = run_cli(
        home, "vmem", "store", "sess-claim-cli-race", "RESEARCH_RESULT", "Race target",
        str(content_file), "--json",
    )
    obj_id = json.loads(store_res.stdout)["obj_id"]
    payload = json.dumps({"candidates": [{"obj_id": obj_id, "kind": "RESEARCH_RESULT"}]})

    first = run_cli(home, "vmem", "claim-pages", "sess-claim-cli-race", "--json", stdin=payload)
    second = run_cli(home, "vmem", "claim-pages", "sess-claim-cli-race", "--json", stdin=payload)
    assert json.loads(first.stdout) == [obj_id]
    assert json.loads(second.stdout) == []


def test_vmem_claim_pages_cli_malformed_stdin_errors_cleanly(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0
    r = run_cli(home, "vmem", "claim-pages", "sess-claim-cli-bad", stdin="not json at all")
    assert r.returncode == 2
    assert "JSON" in r.stderr

def test_capsule_ensure_and_additive_update_cli(tmp_path):
    home = tmp_path / "brain"
    assert run_cli(home, "init").returncode == 0

    ensure = run_cli(
        home,
        "capsule",
        "ensure",
        "omp-s1",
        "Resume the active task",
        "--next-action",
        "Run the focused proof",
        "--json",
    )
    assert ensure.returncode == 0, ensure.stderr
    first = json.loads(ensure.stdout)
    assert first["session_id"] == "omp-s1"
    assert first["changed"] is True
    assert Path(first["capsule_path"]).is_file()

    update = run_cli(
        home,
        "capsule",
        "update",
        "omp-s1",
        "--add-decision",
        "Reuse the existing VMem path",
        "--add-question",
        "Did compaction preserve the state?",
        "--json",
    )
    assert update.returncode == 0, update.stderr
    capsule = json.loads(update.stdout)["capsule"]
    assert capsule["decisions_this_session"] == ["Reuse the existing VMem path"]
    assert capsule["open_questions"] == ["Did compaction preserve the state?"]


def test_environment_assess_cli_records_readback_and_mutation_class(tmp_path):
    home = tmp_path / "brain"
    project = tmp_path / "project"
    project.mkdir()
    start = run_cli(
        home,
        "env",
        "assess",
        str(project),
        "--session",
        "p39-cli",
        "--task-id",
        "p39-task",
        "--phase",
        "session_start",
        "--json",
    )
    assert start.returncode == 0, start.stderr
    first = json.loads(start.stdout)
    assert first["completion_eligible"] is True
    assert len(first["environment_hash"]) == 64
    assert (home / "state" / "sessions" / "p39-cli" / "environment-evidence.json").is_file()

    shutdown = run_cli(
        home,
        "env",
        "assess",
        str(project),
        "--session",
        "p39-cli",
        "--task-id",
        "p39-task",
        "--phase",
        "shutdown",
        "--expected-field",
        "lockfiles",
        "--json",
    )
    assert shutdown.returncode == 0, shutdown.stderr
    second = json.loads(shutdown.stdout)
    assert second["before_environment_hash"] == first["environment_hash"]
    assert second["mutation_classification"] in {"noop", "unexpected", "intended"}


def test_environment_assess_cli_correlates_intended_dependency_mutation(tmp_path):
    home = tmp_path / "brain"
    project = tmp_path / "project"
    project.mkdir()
    start = run_cli(
        home,
        "env",
        "assess",
        str(project),
        "--session",
        "p39-dependency",
        "--phase",
        "session_start",
        "--json",
    )
    assert start.returncode == 0, start.stderr
    (project / "package-lock.json").write_text("{}\n", encoding="utf-8")
    mutation = run_cli(
        home,
        "env",
        "assess",
        str(project),
        "--session",
        "p39-dependency",
        "--phase",
        "mutation",
        "--expected-field",
        "lockfiles",
        "--expected-field",
        "package_manager",
        "--requested-change",
        "npm install package",
        "--mutation-state",
        "observed",
        "--json",
    )
    assert mutation.returncode == 0, mutation.stderr
    payload = json.loads(mutation.stdout)
    assert payload["mutation_classification"] == "intended"
    assert payload["verification_state"] == "passed"
    assert payload["before_environment_hash"] != payload["after_environment_hash"]
    assert payload["dependency_change_refs"]



def test_verify_gate_blocks_unexpected_environment_mutation(tmp_path):
    home = tmp_path / "brain"
    project = tmp_path / "project"
    project.mkdir()
    assert run_cli(home, "init").returncode == 0
    assert (
        run_cli(
            home,
            "env",
            "assess",
            str(project),
            "--session",
            "p39-gate",
            "--phase",
            "session_start",
            "--json",
        ).returncode
        == 0
    )
    (project / "package-lock.json").write_text("{}\n", encoding="utf-8")
    mutation = run_cli(
        home,
        "env",
        "assess",
        str(project),
        "--session",
        "p39-gate",
        "--phase",
        "mutation",
        "--expected-field",
        "lockfiles",
        "--requested-change",
        "unplanned package change",
        "--json",
    )
    assert mutation.returncode == 0
    evidence = home / "state" / "sessions" / "p39-gate" / "environment-evidence.json"
    gate = run_cli(
        home,
        "verify",
        "gate",
        "p39-gate",
        str(project),
        "--criticality",
        "LOW",
        "--action",
        "targeted_test=passed",
        "--action",
        "typecheck_or_compile=passed",
        "--action",
        "diff_sanity=passed",
        "--environment-file",
        str(evidence),
        "--environment-required",
        "--json",
    )

    assert gate.returncode == 1
    payload = json.loads(gate.stdout)
    assert payload["decision_reason"] == "environment_steward_invalid"
    assert "environment_steward" in payload["failed_actions"]


def test_environment_assess_cli_writes_bounded_output_file(tmp_path):
    home = tmp_path / "brain"
    project = tmp_path / "project"
    output = tmp_path / "assessment.json"
    project.mkdir()
    result = run_cli(
        home,
        "env",
        "assess",
        str(project),
        "--session",
        "p39-output",
        "--out",
        str(output),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["session_id"] == "p39-output"


def test_radar_observe_cli_persists_and_deduplicates_candidate(tmp_path):
    home = tmp_path / "brain"
    telemetry_dir = home / "telemetry" / "agent-performance"
    telemetry_dir.mkdir(parents=True)
    records = [
        {
            "v": 2,
            "kind": "tool_call",
            "session": "radar-cli",
            "ts": f"2026-08-26T00:00:0{i}Z",
            "tool": "read",
            "id": f"call-{i}",
            "target_sha256": "d" * 64,
            "input_bytes": 80,
        }
        for i in range(3)
    ]
    (telemetry_dir / "radar-cli.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    first = run_cli(
        home,
        "radar",
        "observe",
        "radar-cli",
        "--project-id",
        "project-a",
        "--repo",
        str(tmp_path),
        "--task-id",
        "task-a",
        "--json",
    )
    second = run_cli(
        home,
        "radar",
        "observe",
        "radar-cli",
        "--project-id",
        "project-a",
        "--repo",
        str(tmp_path),
        "--task-id",
        "task-a",
        "--json",
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_payload = json.loads(first.stdout)
    first_candidate = first_payload["candidates"][0]
    second_payload = json.loads(second.stdout)
    second_candidates = second_payload["candidates"]
    assert first_payload["radar_overhead_ms"] >= 0
    assert first_payload["repo"] == str(tmp_path.resolve())
    assert second_candidates[0]["candidate_id"] == first_candidate["candidate_id"]
    assert second_payload["radar_overhead_ms"] >= 0
    assert len(json.loads((home / "state" / "radar" / "candidates.json").read_text())) == 1

def test_doctor_json_includes_environment_steward_check(tmp_path):
    home = tmp_path / "brain"
    project = tmp_path / "project"
    project.mkdir()
    assert run_cli(home, "init").returncode == 0
    result = run_cli(
        home,
        "doctor",
        "--repo",
        str(project),
        "--session",
        "doctor-cli",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "environment steward")
    assert check["status"] == "ok"
    assert "doctor-cli" in check["detail"]
