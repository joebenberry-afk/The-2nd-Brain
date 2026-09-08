"""Retrieval isolation and delta filtering regression and adversarial tests.

Validates:
- Positive controls: same-project memories and explicit global policies remain retrievable.
- Negative controls: wrong-project implementation details are suppressed.
- Adversarial cases: keyword collisions across projects, high semantic score wrong-project
  memories, unresolved project identity fallback safety, delta conservatism, deduplication.
- Telemetry observability: audit fields captured in JSONL records.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from second_brain import autoinject, registry, semantic, telemetry
from second_brain.contracts import InjectionDecision, NoInjectionReason


def _add_memory(
    home: Path,
    title: str,
    body: str,
    *,
    project_id: str | None = "sz",
    scope: str = "project",
    grade: str = "VERIFIED",
    status: str = "current",
) -> str:
    mid = semantic.add_memory(
        home,
        title,
        body,
        scope=scope,
        project_id=project_id,
        grade=grade,
    )
    semantic.curate(home, mid, status=status, grade=grade)
    return mid


def test_sz_session_receives_sz_and_global_memories_positive_control(brain_home: Path) -> None:
    """Positive control: In an SZ session, useful SZ context and global policy are retrievable."""
    sz_mem1 = _add_memory(
        brain_home,
        "SZ environment setup",
        "SZ project requires specific build flags and environment variables",
        project_id="sz",
    )
    sz_mem2 = _add_memory(
        brain_home,
        "SZ database schema",
        "SZ database uses partitioned tables for time-series data",
        project_id="sz",
    )
    _add_memory(
        brain_home,
        "Evidence outranks memory",
        "Current live repository evidence outranks prior persisted memory",
        project_id=None,
        scope="global",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)
    decision = lifecycle.prepare_injection(
        "SZ environment setup and database schema",
        project_id="sz",
        agent_id="driver",
        session_id="sess-sz-pos-1",
    )

    assert decision.decision is InjectionDecision.INJECT
    assert sz_mem1 in decision.selected_ids or sz_mem2 in decision.selected_ids
    packet = autoinject.render_packet(decision)
    assert packet is not None
    assert "project: sz" in packet


def test_sz_session_suppresses_second_brain_implementation_memories_negative_control(
    brain_home: Path,
) -> None:
    """Negative control: SZ session never receives unrelated Second Brain memories."""
    sb_mem1 = _add_memory(
        brain_home,
        "SQLite WAL restore safety",
        "Restoring db/brain.sqlite while a same-lineage -wal file remains replays stale frames",
        project_id="second-brain",
    )
    sb_mem2 = _add_memory(
        brain_home,
        "Antigravity hook ephemeral injection",
        "Antigravity adapter sends ephemeralMessage payload on PreInvocation hook",
        project_id="second-brain",
    )
    sb_mem3 = _add_memory(
        brain_home,
        "P3 Lean Runtime Kernel",
        "Lean Code runtime adapter mirrors Prime decision semantics from canonical skill",
        project_id="second-brain",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)
    decision = lifecycle.prepare_injection(
        "SQLite WAL restore safety and hook ephemeral injection",
        project_id="sz",
        agent_id="driver",
        session_id="sess-sz-neg-1",
    )

    # Wrong-project memories must NOT be injected
    assert decision.decision is InjectionDecision.NO_INJECTION
    assert decision.reason is NoInjectionReason.WRONG_PROJECT
    assert decision.selected_ids == []
    for sb_mid in (sb_mem1, sb_mem2, sb_mem3):
        assert sb_mid not in decision.selected_ids


def test_identical_keywords_different_project_isolated(brain_home: Path) -> None:
    """Adversarial: identical keywords in different projects remain strictly isolated."""
    proj_a_mem = _add_memory(
        brain_home,
        "Cache eviction policy",
        "Project A uses LRU cache eviction with 100MB limit",
        project_id="proj-a",
    )
    proj_b_mem = _add_memory(
        brain_home,
        "Cache eviction policy",
        "Project B uses LFU cache eviction with Redis cluster",
        project_id="proj-b",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)

    # Search from Project A
    dec_a = lifecycle.prepare_injection(
        "cache eviction policy",
        project_id="proj-a",
        agent_id="driver",
        session_id="sess-a",
    )
    assert dec_a.decision is InjectionDecision.INJECT
    assert proj_a_mem in dec_a.selected_ids
    assert proj_b_mem not in dec_a.selected_ids

    # Search from Project B
    dec_b = lifecycle.prepare_injection(
        "cache eviction policy",
        project_id="proj-b",
        agent_id="driver",
        session_id="sess-b",
    )
    assert dec_b.decision is InjectionDecision.INJECT
    assert proj_b_mem in dec_b.selected_ids
    assert proj_a_mem not in dec_b.selected_ids


def test_high_semantic_score_wrong_project_never_crowds_out_right_project(
    brain_home: Path,
) -> None:
    """Adversarial: high-scoring wrong-project memories do not displace right-project memories."""
    # Seed 10 Project A memories with dense keywords
    for i in range(10):
        _add_memory(
            brain_home,
            f"Authentication token refresh handler {i}",
            f"OAuth2 JWT token refresh handler implementation details variant {i}",
            project_id="proj-a",
        )

    # Seed 1 Project B memory
    target_b = _add_memory(
        brain_home,
        "Authentication token refresh handler B",
        "Project B basic token refresh",
        project_id="proj-b",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)
    decision = lifecycle.prepare_injection(
        "Authentication token refresh handler implementation details variant",
        project_id="proj-b",
        agent_id="driver",
        session_id="sess-crowding-test",
    )

    assert decision.decision is InjectionDecision.INJECT
    assert target_b in decision.selected_ids


def test_global_policy_retrievable_across_all_projects(brain_home: Path) -> None:
    """Global policies are eligible regardless of the active project."""
    global_policy = _add_memory(
        brain_home,
        "Test verification integrity rule",
        "Verification must not fake or mock away real integration requirements",
        project_id=None,
        scope="global",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)
    for project in ("proj-alpha", "proj-beta", "sz", "second-brain"):
        decision = lifecycle.prepare_injection(
            "test verification integrity rule",
            project_id=project,
            agent_id="driver",
            session_id=f"sess-global-{project}",
        )
        assert decision.decision is InjectionDecision.INJECT
        assert global_policy in decision.selected_ids


def test_unresolved_project_identity_fails_safe_to_global_only(brain_home: Path) -> None:
    """Unresolved project identity fails safe: project memories blocked, global allowed."""
    _add_memory(
        brain_home,
        "Secret project implementation",
        "Internal proprietary algorithm for secret project",
        project_id="secret-proj",
    )
    global_policy = _add_memory(
        brain_home,
        "Standard coding guidelines",
        "All code must pass static analysis and formatting checks",
        project_id=None,
        scope="global",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)

    # Query matching the secret project memory with unresolved identity -> WRONG_PROJECT / blocked
    dec_unresolved = lifecycle.prepare_injection(
        "secret project implementation algorithm",
        project_id=None,
        cwd=None,
        agent_id="driver",
        session_id="sess-unres-1",
    )
    assert dec_unresolved.decision is InjectionDecision.NO_INJECTION
    assert dec_unresolved.selected_ids == []

    # Query matching the global policy -> INJECT
    dec_global = lifecycle.prepare_injection(
        "standard coding guidelines static analysis",
        project_id=None,
        cwd=None,
        agent_id="driver",
        session_id="sess-unres-2",
    )
    assert dec_global.decision is InjectionDecision.INJECT
    assert global_policy in dec_global.selected_ids


def test_unresolved_project_default_memory_suppressed_and_global_policy_allowed(
    brain_home: Path,
) -> None:
    """Adversarial: unresolved identity must be GLOBAL-ONLY.

    A project-scoped memory tagged project_id='default' must NOT inject under an
    unresolved project, while an explicit global policy with matching text CAN inject.
    """
    default_proj_mem = _add_memory(
        brain_home,
        "Fallback runtime config default",
        "Default project local configuration for internal worker timeout. "
        "Violetwidget beaconthrottle localonly settingresolve.",
        project_id="default",
        scope="project",
    )
    global_policy_mem = _add_memory(
        brain_home,
        "Global runtime config policy",
        "Default project global configuration for internal worker timeout",
        project_id=None,
        scope="global",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)

    # Query with unresolved project identity matching both memories
    decision = lifecycle.prepare_injection(
        "default project configuration for internal worker timeout",
        project_id=None,
        cwd=None,
        agent_id="driver",
        session_id="sess-unres-default-gate",
    )

    assert decision.decision is InjectionDecision.INJECT
    # Global policy MUST inject
    assert global_policy_mem in decision.selected_ids
    # Project-scoped memory with project_id='default' MUST NOT inject
    assert default_proj_mem not in decision.selected_ids
    assert decision.selected_ids == [global_policy_mem]

    # Query matching ONLY the default project-scoped memory -> NO_INJECTION (WRONG_PROJECT)
    dec_only_default = lifecycle.prepare_injection(
        "violetwidget beaconthrottle localonly settingresolve",
        project_id=None,
        cwd=None,
        agent_id="driver",
        session_id="sess-unres-default-only",
    )
    assert dec_only_default.decision is InjectionDecision.NO_INJECTION
    assert dec_only_default.reason is NoInjectionReason.WRONG_PROJECT
    assert dec_only_default.selected_ids == []


def test_delta_stricter_than_startup_budget_and_confidence(brain_home: Path) -> None:
    """Delta injection applies stricter token budgets and confidence thresholds than startup."""
    # OBSERVED grade memory (medium confidence)
    obs_mem = _add_memory(
        brain_home,
        "Observed telemetry quirk",
        "Observed telemetry counter offset by 1 on cold startup",
        project_id="proj-delta",
        grade="OBSERVED",
        status="current",
    )
    # VERIFIED grade memory (high confidence)
    ver_mem = _add_memory(
        brain_home,
        "Verified database lock timeout",
        "Database lock timeout set to 5000ms in production configuration",
        project_id="proj-delta",
        grade="VERIFIED",
        status="current",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)

    # Startup injection: allows OBSERVED grade
    startup_dec = lifecycle.prepare_injection(
        "observed telemetry quirk",
        project_id="proj-delta",
        agent_id="driver",
        session_id="sess-startup-1",
        is_delta=False,
    )
    assert startup_dec.decision is InjectionDecision.INJECT
    assert obs_mem in startup_dec.selected_ids

    # Mid-session delta: rejects OBSERVED grade (requires VERIFIED/TESTED)
    delta_dec_obs = lifecycle.prepare_injection(
        "observed telemetry quirk",
        project_id="proj-delta",
        agent_id="driver",
        session_id="sess-delta-1",
        is_delta=True,
    )
    assert delta_dec_obs.decision is InjectionDecision.NO_INJECTION
    assert obs_mem not in delta_dec_obs.selected_ids

    # Mid-session delta: accepts VERIFIED grade
    delta_dec_ver = lifecycle.prepare_injection(
        "verified database lock timeout",
        project_id="proj-delta",
        agent_id="driver",
        session_id="sess-delta-2",
        is_delta=True,
    )
    assert delta_dec_ver.decision is InjectionDecision.INJECT
    assert ver_mem in delta_dec_ver.selected_ids


def test_deduplication_suppresses_repeated_unchanged_delta(brain_home: Path) -> None:
    """An already-delivered unchanged memory is not repeatedly re-injected."""
    mem_id = _add_memory(
        brain_home,
        "Deduplication invariant",
        "Never inject the same unchanged memory twice into the same active session",
        project_id="proj-dedup",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)
    sess_id = "sess-dedup-lineage"

    # Turn 1 (Startup): delivered
    turn1 = lifecycle.prepare_injection(
        "deduplication invariant",
        project_id="proj-dedup",
        session_id=sess_id,
        is_delta=False,
    )
    assert turn1.decision is InjectionDecision.INJECT
    assert turn1.selected_ids == [mem_id]

    # Turn 2 (Delta): same query -> ALREADY_DELIVERED
    turn2 = lifecycle.prepare_injection(
        "deduplication invariant",
        project_id="proj-dedup",
        session_id=sess_id,
        is_delta=True,
    )
    assert turn2.decision is InjectionDecision.NO_INJECTION
    assert turn2.reason is NoInjectionReason.ALREADY_DELIVERED
    assert turn2.selected_ids == [mem_id]


def test_materially_updated_memory_delivered_with_supersede_pointer(
    brain_home: Path,
) -> None:
    """A materially updated memory becomes eligible again and records a supersede pointer."""
    mem_id = _add_memory(
        brain_home,
        "Worker concurrency limit",
        "Worker concurrency limit is 2 workers maximum",
        project_id="proj-supersede",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)
    sess_id = "sess-supersede-lineage"

    # Turn 1: v1 delivered
    turn1 = lifecycle.prepare_injection(
        "worker concurrency limit",
        project_id="proj-supersede",
        session_id=sess_id,
        is_delta=False,
    )
    assert turn1.decision is InjectionDecision.INJECT
    assert turn1.selected_ids == [mem_id]

    # Update memory to v2
    semantic.supersede(
        brain_home,
        mem_id,
        new_body="Worker concurrency limit updated to 4 workers for high-concurrency tasks",
        change_note="Updated concurrency ceiling",
    )
    semantic.curate(brain_home, mem_id, status="current", grade="VERIFIED")

    # Turn 2: v2 becomes eligible again as a delta
    turn2 = lifecycle.prepare_injection(
        "worker concurrency limit updated",
        project_id="proj-supersede",
        session_id=sess_id,
        is_delta=True,
    )
    assert turn2.decision is InjectionDecision.INJECT
    assert turn2.selected_ids == [mem_id]
    packet = autoinject.render_packet(turn2)
    assert packet is not None
    assert f"UPDATE {mem_id} v2 supersedes {mem_id} v1" in packet


def test_retrieval_telemetry_captures_all_required_audit_fields(brain_home: Path) -> None:
    """Retrieval telemetry captures project_id, is_delta, candidate counts, and decisions."""
    _add_memory(
        brain_home,
        "Telemetry verification check",
        "Verify all retrieval decisions produce compliant telemetry records",
        project_id="proj-telem",
    )

    lifecycle = autoinject.BrainLifecycle(brain_home)
    sess_id = "sess-audit-telem-1"

    # Startup injection
    lifecycle.prepare_injection(
        "telemetry verification check",
        project_id="proj-telem",
        session_id=sess_id,
        is_delta=False,
    )

    # Check telemetry logs
    tdir = telemetry.telemetry_dir(brain_home)
    log_file = tdir / f"{sess_id}.jsonl"
    assert log_file.is_file()

    records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    kinds = {r["kind"] for r in records}
    assert "brain_retrieval_attempt" in kinds
    assert "brain_packet_delivered" in kinds

    attempt = next(r for r in records if r["kind"] == "brain_retrieval_attempt")
    assert attempt["project_id"] == "proj-telem"
    assert attempt["is_delta"] is False
    assert attempt["candidate_count"] >= 1

    delivered = next(r for r in records if r["kind"] == "brain_packet_delivered")
    assert delivered["project_id"] == "proj-telem"
    assert delivered["is_delta"] is False
    assert delivered["delivery_prepared"] is True


def test_cwd_worktree_detection_matches_git_remote(brain_home: Path, tmp_path: Path) -> None:
    """Git worktree in a different folder matches project via git remote."""
    repo_main = tmp_path / "my-main-repo"
    repo_main.mkdir(parents=True)
    (repo_main / "README.md").write_text("# main\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo_main, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/my-project.git"],
        cwd=repo_main,
        check=True,
    )

    registry.add_project(brain_home, repo_main, name="MyProject", project_id="my-proj")

    # Create a separate worktree directory with the same remote
    worktree_dir = tmp_path / "my-worktree-branch"
    worktree_dir.mkdir(parents=True)
    (worktree_dir / "README.md").write_text("# worktree\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=worktree_dir, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/my-project.git"],
        cwd=worktree_dir,
        check=True,
    )

    resolved = autoinject._resolve_project_id(brain_home, cwd=str(worktree_dir), explicit=None)
    assert resolved == "my-proj"


def test_nested_repository_uses_its_registry_instead_of_parent_manifest(brain_home, tmp_path):
    parent = tmp_path / "parent"
    child = parent / "workspaces" / "child"
    nested = child / "src"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(parent)], check=True)
    subprocess.run(["git", "init", "-q", str(child)], check=True)
    (parent / ".brain").mkdir()
    (parent / ".brain" / "project.toml").write_text('id = "parent"\n', encoding="utf-8")
    registry.add_project(brain_home, parent, name="A Parent", project_id="parent")
    registry.add_project(brain_home, child, name="Z Child", project_id="child")

    resolved = autoinject.resolve_project(brain_home, str(nested))

    assert resolved["project_id"] == "child"
    assert Path(resolved["repo_root"]) == child.resolve()
    assert autoinject.resolve_project(brain_home, str(parent))["project_id"] == "parent"


def test_unregistered_nested_git_file_never_inherits_parent_identity(
    brain_home,
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("SECOND_BRAIN_PROJECT", raising=False)
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(parent)], check=True)
    subprocess.run(
        ["git", "init", "-q", "--separate-git-dir", str(tmp_path / "child-git"), str(child)],
        check=True,
    )
    (parent / ".brain").mkdir()
    (parent / ".brain" / "project.toml").write_text('id = "parent"\n', encoding="utf-8")
    registry.add_project(brain_home, parent, project_id="parent")

    resolved = autoinject.resolve_project(brain_home, str(child))

    assert resolved["project_id"] == "default"
    assert (
        autoinject.resolve_project(brain_home, str(child), explicit="chosen")["project_id"]
        == "chosen"
    )
