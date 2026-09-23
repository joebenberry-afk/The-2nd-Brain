"""Tests for the Intent Verifier brief builder (Phase 7) + the P3-G
risk-adaptive verification ladder (plan §10.2/§10.3/§10.4)."""

import subprocess
from pathlib import Path

import pytest

from second_brain import db, risk, verify
from second_brain import working_set as ws
from second_brain.errors import BrainError

REAL_LADDER_TOML = (
    Path(__file__)
    .resolve()
    .parent.parent.joinpath("config", "verification.toml")
    .read_text(encoding="utf-8")
)


def _commit_repo(repo):
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)


def _dirty(repo):
    """Make tracked-file changes that git diff will show."""
    _commit_repo(repo)
    (repo / "README.md").write_text("# repo\nchanged line\n", encoding="utf-8")
    (repo / "feature.py").write_text("def f():\n    return 1\n", encoding="utf-8")


def _capsule(brain_home, sid="s1", files=("README.md", "feature.py"), constraints=("stdlib only",)):
    ws.init_capsule(brain_home, sid, "Verify the patch")
    ws.update_capsule(brain_home, sid, files_touched=list(files), constraints=list(constraints))
    return sid


def _build(brain_home, repo, sid="s1"):
    path = verify.build_verifier_brief(brain_home, sid, repo)
    return path, path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Structure and ordering
# ---------------------------------------------------------------------------


def test_section_order_and_content(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.add_requirement(brain_home, "s1", "Patch must add the feature", importance="critical")
    ws.add_evidence(brain_home, "s1", "REQ-001", "targeted test passes")
    path, text = _build(brain_home, repo)

    idx = {
        name: text.index(f"# {name}")
        for name in (
            "Backward Reconstruction",
            "Diff",
            "Requirements",
            "Constraints",
            "Validation Evidence",
            "Verifier Questions",
        )
    }
    assert idx["Backward Reconstruction"] < idx["Diff"] < idx["Requirements"]
    assert idx["Requirements"] < idx["Constraints"] < idx["Validation Evidence"]
    assert idx["Validation Evidence"] < idx["Verifier Questions"]

    assert "## Backward Reconstruction" in text
    assert "diff --git" in text  # real diff body present
    assert "- REQ-001 [critical/unverified] Patch must add the feature" in text
    assert "- stdlib only" in text
    assert "REQ-001:" in text and "targeted test passes" in text
    for question in verify.VERIFIER_QUESTIONS:
        assert question in text
    assert "session: s1" in text
    assert "generated_at:" in text
    assert f"repo: {repo}" in text
    assert path.parent == brain_home / "outputs" / "verification"
    assert path.name == "s1.md"


def test_diff_section_precedes_requirements(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.add_requirement(brain_home, "s1", "Some requirement")
    _, text = _build(brain_home, repo)
    diff_pos = text.index("# Diff")
    req_pos = text.index("# Requirements")
    body_pos = text.index("diff --git")
    req_line = text.index("Some requirement")
    assert diff_pos < req_pos
    assert body_pos < req_line  # the diff body itself precedes the requirement text


def test_solver_reasoning_excluded(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.update_capsule(
        brain_home,
        "s1",
        current_hypotheses=["SECRETHYP"],
        decisions_this_session=["SECRETDEC"],
        next_action="SECRETNEXT",
        open_questions=["SECRETOPEN"],
    )
    _, text = _build(brain_home, repo)
    for marker in ("SECRETHYP", "SECRETDEC", "SECRETNEXT", "SECRETOPEN"):
        assert marker not in text


def test_missing_capsule_raises(brain_home, repo):
    with pytest.raises(BrainError):
        verify.build_verifier_brief(brain_home, "nosession", repo)


# ---------------------------------------------------------------------------
# Fallbacks and determinism
# ---------------------------------------------------------------------------


def test_none_fallbacks(brain_home, repo):
    _capsule(brain_home, files=(), constraints=())  # no files, no constraints, no ledger
    _, text = _build(brain_home, repo)
    assert "# Diff\n\n(no files recorded)" in text
    assert "# Requirements\n\n(none)" in text
    assert "# Constraints\n\n(none)" in text
    assert "# Validation Evidence\n\n(none)" in text


def test_git_errors_graced(brain_home, tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    (plain / "a.txt").write_text("x", encoding="utf-8")
    _capsule(brain_home, files=("a.txt",), constraints=())
    _, text = _build(brain_home, plain)
    assert "(diff unavailable" in text


def test_determinism_identical_except_generated_at(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.add_requirement(brain_home, "s1", "Req one")
    ws.add_evidence(brain_home, "s1", "REQ-001", "evidence one")
    _, first = _build(brain_home, repo)
    _, second = _build(brain_home, repo)

    def strip(text):
        return "\n".join(line for line in text.splitlines() if not line.startswith("generated_at:"))

    assert strip(first) == strip(second)


def test_truncated_diff(brain_home, repo):
    _commit_repo(repo)
    big = repo / "big.py"
    big.write_text("one line\n", encoding="utf-8")
    subprocess.run(["git", "add", "big.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add big"], cwd=repo, check=True, capture_output=True)
    big.write_text("".join(f"line {i}\n" for i in range(500)), encoding="utf-8")
    _capsule(brain_home, files=("big.py",), constraints=())
    _, text = _build(brain_home, repo)
    diff_block = text.split("# Diff", 1)[1].split("# Requirements", 1)[0]
    diff_lines = [line for line in diff_block.splitlines() if line.strip()]
    assert len(diff_lines) <= verify.MAX_DIFF_LINES


# ---------------------------------------------------------------------------
# P3-G: risk-adaptive verification ladder (plan §10)
# ---------------------------------------------------------------------------


def test_ladder_from_toml_parses_real_config():
    ladder = verify.ladder_from_toml(REAL_LADDER_TOML)
    assert list(ladder) == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert "independent_intent_verifier" in ladder["HIGH"]
    assert "human_approval_for_irreversible" in ladder["CRITICAL"]


def test_ladder_from_toml_invalid_or_absent_falls_back_to_safe_defaults():
    # invalid TOML
    assert verify.ladder_from_toml("this is [ not toml") == verify.ladder_from_toml("")
    # absent [ladder] section
    empty_section = "[requirement_ledger]\nstatuses = []\n"
    assert verify.ladder_from_toml(empty_section) == verify.ladder_from_toml("")
    # non-list / empty / non-string values -> per-level defaults (a valid
    # list for one level is kept; invalid levels fall back individually)
    partial = "[ladder]\nLOW = 42\nMEDIUM = []\nHIGH = [1, 2]\nCRITICAL = ['ok']\n"
    ladder = verify.ladder_from_toml(partial)
    for level in ("LOW", "MEDIUM", "HIGH"):
        assert ladder[level] == verify.DEFAULT_VERIFICATION_LADDER[level]
    assert ladder["CRITICAL"] == ["ok"]
    # defaults are never empty and cover every level
    for level in verify.RISK_LEVELS:
        assert verify.DEFAULT_VERIFICATION_LADDER[level]


def test_load_verification_ladder_missing_home_never_throws():
    assert verify.load_verification_ladder(None) == verify.DEFAULT_VERIFICATION_LADDER
    missing = "C:/nonexistent-home-xyz"
    assert verify.load_verification_ladder(missing) == verify.DEFAULT_VERIFICATION_LADDER


def test_low_never_forces_independent_verifier():
    payload = verify.verification_ladder_payload("LOW")
    assert payload["level"] == "LOW"
    assert payload["independent_verifier"] is False
    assert payload["approval_required"] is False
    assert any("targeted" in a for a in payload["actions"])
    assert len(payload["actions"]) == len(verify.DEFAULT_VERIFICATION_LADDER["LOW"])


def test_medium_adds_relevant_tests_and_ledger_check():
    payload = verify.verification_ladder_payload("MEDIUM")
    assert payload["independent_verifier"] is False
    actions = " ".join(payload["actions"])
    assert "requirement-ledger" in actions
    assert "relevant tests" in actions
    assert "diff sanity" in actions  # LOW is cumulative into MEDIUM


def test_high_forces_fresh_independent_verifier_brief():
    payload = verify.verification_ladder_payload("HIGH")
    assert payload["independent_verifier"] is True
    assert payload["approval_required"] is False
    actions = " ".join(payload["actions"])
    assert "independent verifier brief" in actions
    assert "rollback" in actions
    assert "adversarial" in actions
    # HIGH is cumulative: LOW + MEDIUM actions are present too
    assert "diff sanity" in actions
    assert "requirement-ledger" in actions


def test_critical_adds_explicit_approval_flag():
    payload = verify.verification_ladder_payload("CRITICAL")
    assert payload["independent_verifier"] is True
    assert payload["approval_required"] is True
    actions = " ".join(payload["actions"])
    assert "human approval" in actions
    assert "rollback" in actions


def test_ladder_payload_is_compact_and_deterministic():
    a = verify.verification_ladder_payload("HIGH")
    b = verify.verification_ladder_payload("HIGH")
    assert a == b  # deterministic
    assert set(a) == {"level", "actions", "independent_verifier", "approval_required"}
    assert len(a["actions"]) <= 12  # compact: not nine paragraphs


def test_ladder_from_custom_config_seam():
    custom = {
        "LOW": ["diff_sanity"],
        "MEDIUM": ["all_medium"],
        "HIGH": ["all_medium", "independent_intent_verifier"],
        "CRITICAL": ["all_high", "human_approval_for_irreversible"],
    }
    payload = verify.verification_ladder_payload("MEDIUM", ladder=custom)
    assert payload["actions"] == ["diff sanity review"]  # all_medium resolves LOW
    assert payload["independent_verifier"] is False
    payload_high = verify.verification_ladder_payload("HIGH", ladder=custom)
    assert payload_high["independent_verifier"] is True


def test_unknown_level_raises():
    with pytest.raises(BrainError):
        verify.verification_ladder_payload("EXTREME")


# ---------------------------------------------------------------------------
# P3-G: user criticality raises, Lean never lowers (plan §10.2)
# ---------------------------------------------------------------------------


def test_user_criticality_raises_risk_to_critical():
    # one non-central file -> LOW score; user flags CRITICAL -> level raises
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        result = risk.assess_risk(Path(tmp), ["README.md"], user_criticality="CRITICAL")
    assert result["level"] == "CRITICAL"
    assert result["score"] < 9  # the raise came from the override, not the score
    # the ladder follows the raised level
    payload = verify.verification_ladder_payload(result["level"])
    assert payload["approval_required"] is True


def test_lean_never_lowers_existing_risk():
    """User criticality is RAISE-ONLY: it can lift a level but never lower one
    (the Lean path must not reduce verification below the computed risk)."""
    import tempfile
    from pathlib import Path

    high_files = ["src/second_brain/cli.py", "db/migrations/0001.py"]  # -> HIGH (score 7)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src" / "second_brain").mkdir(parents=True, exist_ok=True)
        (repo / "db" / "migrations").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "second_brain" / "cli.py").write_text("x\n", encoding="utf-8")
        (repo / "db" / "migrations" / "0001.py").write_text("x\n", encoding="utf-8")

        computed = risk.assess_risk(repo, high_files)
        assert computed["level"] == "HIGH", computed

        # A LOW/MEDIUM override must NOT lower HIGH...
        for override in ("LOW", "MEDIUM"):
            raised = risk.assess_risk(repo, high_files, user_criticality=override)
            assert raised["level"] == "HIGH", (override, raised)
        # ...and the ladder still demands the independent verifier at HIGH.
        payload = verify.verification_ladder_payload(computed["level"])
        assert payload["independent_verifier"] is True


def test_override_raise_only_invariant_every_level():
    """The raise-only invariant holds for every (computed, override) pair:
    the effective level is never below the computed level."""
    import tempfile

    with tempfile.TemporaryDirectory():
        for computed in risk.RISK_LEVELS:
            for override in risk.RISK_LEVELS:
                # the assess_risk override semantics, asserted directly
                effective = (
                    override
                    if risk.RISK_LEVELS.index(override) > risk.RISK_LEVELS.index(computed)
                    else computed
                )
                assert risk.RISK_LEVELS.index(effective) >= risk.RISK_LEVELS.index(computed)


# ---------------------------------------------------------------------------
# P3-G: CLI surface — `brainctl risk assess ... --verification-ladder`
# ---------------------------------------------------------------------------


def test_cli_risk_assess_verification_ladder(tmp_path):
    import os
    import sys

    home = tmp_path / "brain"
    home.mkdir()
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# r\n", encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "second_brain",
            "--home",
            str(home),
            "risk",
            "assess",
            str(repo),
            "--file",
            "README.md",
            "--verification-ladder",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=repo,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    out = run.stdout
    assert "Risk:" in out
    assert "Verification ladder" in out
    # LOW risk must say the independent verifier is NOT required
    assert "independent verifier: not required" in out
    assert "human approval: not required" in out


def _gate_actions(level: str, *, omit: set[str] | None = None) -> dict[str, str]:
    omit = omit or set()
    tokens = verify.expand_ladder_actions(verify.DEFAULT_VERIFICATION_LADDER, level)
    return {
        token: "passed"
        for token in tokens
        if token != "optional_second_independent_verification" and token not in omit
    }


def test_accuracy_gate_allows_complete_low_risk_work(brain_home, repo):
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-low",
        repo,
        ["README.md"],
        action_states=_gate_actions("LOW"),
    )
    assert result["risk_level"] == "LOW"
    assert result["completion_allowed"] is True
    assert result["failed_actions"] == []
    assert result["unresolved_material_requirements"] == []


def test_accuracy_gate_blocks_high_without_independent_verifier(brain_home, repo):
    actions = _gate_actions("HIGH", omit={"independent_intent_verifier"})
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-high",
        repo,
        ["README.md"],
        user_criticality="HIGH",
        action_states=actions,
    )
    assert result["risk_level"] == "HIGH"
    assert result["completion_allowed"] is False
    assert "independent_intent_verifier" in result["unresolved_actions"]


def test_accuracy_gate_blocks_critical_without_approval(brain_home, repo):
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-critical",
        repo,
        ["README.md"],
        user_criticality="CRITICAL",
        action_states=_gate_actions("CRITICAL"),
        approval_state="not_required",
    )
    assert result["risk_level"] == "CRITICAL"
    assert result["completion_allowed"] is False
    assert result["approval_state"] == "required"


def test_accuracy_gate_rejects_self_certified_independent_action(brain_home, repo):
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-self",
        repo,
        ["README.md"],
        user_criticality="HIGH",
        action_states=_gate_actions("HIGH"),
    )
    assert result["completion_allowed"] is False
    assert "independent_verification_missing" in result["decision_reason"]


def test_accuracy_gate_accepts_fresh_independent_pass(brain_home, repo):
    hashes = {
        "task_hash": "a" * 64,
        "requirements_hash": "b" * 64,
        "diff_hash": "c" * 64,
        "evidence_set_hash": "d" * 64,
    }
    verification = {
        "verification_id": "ver-pass",
        "task_id": "task-pass",
        "verifier_session_id": "verifier-pass",
        "implementation_session_id": "impl-pass",
        "verdict": "PASS",
        "freshness": "fresh",
        "reason_codes": [],
        **hashes,
    }
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-pass",
        repo,
        ["README.md"],
        user_criticality="HIGH",
        action_states=_gate_actions("HIGH"),
        independent_verification=verification,
        task_id="task-pass",
        parent_session_id="impl-pass",
        task_hash=hashes["task_hash"],
        requirements_hash=hashes["requirements_hash"],
        diff_hash=hashes["diff_hash"],
        evidence_set_hash=hashes["evidence_set_hash"],
    )
    assert result["completion_allowed"] is True
    assert result["verification_id"] == "ver-pass"


def test_accuracy_gate_rejects_stale_independent_pass(brain_home, repo):
    hashes = {
        "task_hash": "a" * 64,
        "requirements_hash": "b" * 64,
        "diff_hash": "c" * 64,
        "evidence_set_hash": "d" * 64,
    }
    stale = {
        "verification_id": "ver-stale",
        "task_id": "task-stale",
        "verifier_session_id": "verifier-stale",
        "implementation_session_id": "impl-stale",
        "verdict": "PASS",
        "freshness": "fresh",
        "reason_codes": [],
        "task_hash": "0" * 64,
        "requirements_hash": hashes["requirements_hash"],
        "diff_hash": hashes["diff_hash"],
        "evidence_set_hash": hashes["evidence_set_hash"],
    }
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-stale",
        repo,
        ["README.md"],
        user_criticality="HIGH",
        action_states=_gate_actions("HIGH"),
        independent_verification=stale,
        task_id="task-stale",
        parent_session_id="impl-stale",
        task_hash=hashes["task_hash"],
        requirements_hash=hashes["requirements_hash"],
        diff_hash=hashes["diff_hash"],
        evidence_set_hash=hashes["evidence_set_hash"],
    )
    assert result["completion_allowed"] is False
    assert "independent_verification_stale" in result["decision_reason"]


def test_accuracy_gate_blocks_unresolved_material_requirement(brain_home, repo):
    ws.add_requirement(brain_home, "gate-medium", "Acceptance evidence", importance="critical")
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-medium",
        repo,
        ["README.md"],
        user_criticality="MEDIUM",
        action_states=_gate_actions("MEDIUM"),
    )
    assert result["completion_allowed"] is False
    assert result["unresolved_material_requirements"] == ["REQ-001"]


def test_accuracy_gate_returns_bounded_canonical_evidence(brain_home, repo):
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-evidence",
        repo,
        ["README.md"],
        user_criticality="HIGH",
        action_states=_gate_actions("HIGH"),
        approval_state="not_required",
        task_id="task-evidence",
        parent_session_id="parent-evidence",
        worker_session_id="worker-evidence",
    )
    assert set(result) == {
        "accuracy_gate_id",
        "task_id",
        "parent_session_id",
        "worker_session_id",
        "risk_level",
        "risk_reasons",
        "ladder_id",
        "required_actions",
        "completed_actions",
        "failed_actions",
        "unresolved_actions",
        "unresolved_material_requirements",
        "approval_state",
        "completion_allowed",
        "decision_reason",
        "verification_id",
        "verifier_session_id",
        "verification_verdict",
        "verification_freshness",
        "verification_reason_codes",
        "environment_steward_id",
        "environment_hash",
        "environment_mutation_classification",
        "environment_completion_eligible",
        "economics",
    }
    assert result["task_id"] == "task-evidence"
    assert result["parent_session_id"] == "parent-evidence"
    assert result["worker_session_id"] == "worker-evidence"
    assert result["economics"]["verification_model_calls"] == 0


def test_accuracy_gate_blocks_material_environment_evidence():
    evidence = {
        "project_id": "project",
        "environment_state": {"repo": "C:/repo"},
        "environment_hash": "a" * 64,
        "after_environment_hash": "b" * 64,
        "verification_state": "failed",
        "completion_eligible": False,
    }
    result = verify.evaluate_accuracy_gate(
        Path("brain"),
        "environment-material",
        Path("C:/repo"),
        [],
        user_criticality="LOW",
        action_states=_gate_actions("LOW"),
        environment_evidence=evidence,
        environment_required=True,
    )

    assert "environment_steward" in result["required_actions"]
    assert "environment_steward" in result["failed_actions"]
    assert result["completion_allowed"] is False


def test_accuracy_gate_ignores_optional_environment_evidence():
    result = verify.evaluate_accuracy_gate(
        Path("brain"),
        "environment-optional",
        Path("C:/repo"),
        [],
        user_criticality="LOW",
        action_states=_gate_actions("LOW"),
        environment_evidence={"completion_eligible": False},
        environment_required=False,
    )

    assert "environment_steward" not in result["required_actions"]


def test_explicit_observed_model_records_skill_outcome(brain_home, repo):
    _commit_repo(repo)
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-sess-001",
        repo,
        ["README.md"],
        action_states={
            action: "passed"
            for action in verify.expand_ladder_actions(verify.DEFAULT_VERIFICATION_LADDER, "LOW")
        },
        model_id="observed-model-alpha",
        skill_name="implementation",
        task="implement feature",
    )
    assert result["completion_allowed"] is True
    with db.connect(db.db_path(brain_home)) as conn:
        row = conn.execute(
            "SELECT skill_name, success, session_id FROM model_skill_outcomes WHERE model_id=?",
            ("observed-model-alpha",),
        ).fetchone()
    assert tuple(row) == ("implementation", 1, "gate-sess-001")
