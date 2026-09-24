"""Focused regressions for the SEC-AUTH-01 / SEC-AUTH-02 authority boundary.

Requested authority is not effective authority. A caller that asserts its own
approval (SEC-AUTH-01), its own evidence grade, or its own model identity
(SEC-AUTH-02) gains nothing it could not already do: the self-authored claims
stay evidence, and the privileged outcomes they ask for fail closed.

Both exploits in ``docs/intake/m00-evidence/high-dispositions-20260923.md``
(§6, §7) were reproduced through these exact call shapes.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from conftest import clean_python_env
from second_brain import autoinject, contracts, reconsolidation, semantic, verify
from second_brain.errors import BrainError

CRITICAL_ACTIONS = tuple(
    action
    for action in verify.expand_ladder_actions(verify.DEFAULT_VERIFICATION_LADDER, "CRITICAL")
    if action != "optional_second_independent_verification"
)
HASHES: dict[str, Any] = {
    "task_hash": "a" * 64,
    "requirements_hash": "b" * 64,
    "diff_hash": "c" * 64,
    "evidence_set_hash": "d" * 64,
}


def _run_cli(home: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**clean_python_env(), "SECOND_BRAIN_HOME": str(home), "PYTHONIOENCODING": "utf-8"},
        cwd=str(cwd or home),
        timeout=120,
    )


def _scalar(home: Path, query: str) -> int:
    conn = sqlite3.connect(home / "db" / "brain.sqlite")
    try:
        return int(conn.execute(query).fetchone()[0])
    finally:
        conn.close()


def _count(home: Path, table: str) -> int:
    return _scalar(home, f"SELECT count(*) FROM {table}")


def _verified_memories(home: Path) -> int:
    return _scalar(home, "SELECT count(*) FROM memories WHERE evidence_grade = 'VERIFIED'")


def _self_authored_verification() -> dict:
    """A verification record the requester wrote about itself: distinct verifier
    session id, fresh, PASS, matching hashes, plus a claimed model identity."""
    return {
        "verification_id": "ver-self-authored",
        "task_id": "task-self",
        "verifier_session_id": "self-authored-verifier",
        "implementation_session_id": "impl-self",
        "verdict": "PASS",
        "freshness": "fresh",
        "reason_codes": [],
        "model_id": "self-claimed-model",
        **HASHES,
    }


def test_self_authored_critical_gate_cannot_authorize_completion(brain_home, repo):
    """SEC-AUTH-01: approval, action states and a self-written verification file
    are evidence; none of them can complete an irreversible gate."""
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-self-authored",
        repo,
        ["README.md"],
        action_states={action: "passed" for action in CRITICAL_ACTIONS},
        user_criticality="CRITICAL",
        approval_state="approved",
        independent_verification=_self_authored_verification(),
        task_id="task-self",
        parent_session_id="impl-self",
        **HASHES,
    )

    assert result["risk_level"] == "CRITICAL"
    assert "human_approval_for_irreversible" in result["required_actions"]
    # The self-authored claims were accepted as evidence ...
    assert set(CRITICAL_ACTIONS) <= set(result["completed_actions"])
    assert result["requested_approval_state"] == "approved"
    # ... and confer no authority.
    assert result["approval_state"] == "required"
    assert result["approval_attestation"] == "unavailable"
    assert result["completion_allowed"] is False
    assert result["decision_reason"] == "irreversible_action_approval_required"
    # SEC-AUTH-02 sink: no unauthenticated model outcome/profile was recorded.
    assert _count(brain_home, "model_skill_outcomes") == 0
    assert _count(brain_home, "model_profiles") == 0


def test_cli_self_authored_critical_gate_cannot_authorize_completion(brain_home, repo, tmp_path):
    """The reproduced CLI shape: every action passed, approval claimed, caller's
    own verification file supplied — still refused."""
    verification_file = tmp_path / "verification.json"
    verification_file.write_text(
        json.dumps(_self_authored_verification()), encoding="utf-8"
    )
    args = [
        "verify",
        "gate",
        "gate-cli-self",
        str(repo),
        "--file",
        "README.md",
        "--criticality",
        "CRITICAL",
        "--approval-state",
        "approved",
        "--verification-file",
        str(verification_file),
        "--task-id",
        "task-self",
        "--parent-session-id",
        "impl-self",
        *(arg for action in CRITICAL_ACTIONS for arg in ("--action", f"{action}=passed")),
        "--json",
    ]

    result = _run_cli(brain_home, *args, cwd=repo)

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["completion_allowed"] is False
    assert payload["approval_state"] == "required"
    assert payload["approval_attestation"] == "unavailable"
    assert payload["decision_reason"] == "irreversible_action_approval_required"
    assert _count(brain_home, "model_skill_outcomes") == 0
    assert _count(brain_home, "model_profiles") == 0


def test_critical_gate_requires_approval_even_without_the_ladder_token(brain_home, repo):
    """The boundary is structural, not config-dependent: a home-config ladder that
    drops the approval token still cannot authorize a self-approved critical gate."""
    (brain_home / "config" / "verification.toml").write_text(
        '[ladder]\nCRITICAL = ["all_high"]\n', encoding="utf-8"
    )
    actions = dict.fromkeys(
        (*CRITICAL_ACTIONS, "human_approval_for_irreversible"),
        "passed",
    )

    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-ladder-tamper",
        repo,
        ["README.md"],
        action_states=actions,
        user_criticality="CRITICAL",
        approval_state="approved",
        independent_verification=_self_authored_verification(),
        task_id="task-self",
        parent_session_id="impl-self",
        **HASHES,
    )

    assert "human_approval_for_irreversible" in result["required_actions"]
    assert "independent_intent_verifier" in result["completed_actions"]
    assert result["approval_state"] == "required"
    assert result["completion_allowed"] is False
    assert result["decision_reason"] == "irreversible_action_approval_required"


def test_remember_claimed_verified_grade_is_refused_not_downgraded(brain_home, repo, monkeypatch):
    """SEC-AUTH-02: `remember --grade VERIFIED` without attestation errors with a
    stable code and persists nothing; unprivileged grades still persist."""
    monkeypatch.setenv("SECOND_BRAIN_PROJECT", "demo")

    refused = _run_cli(
        brain_home, "remember", "Self-claimed verified fact", "--grade", "VERIFIED", cwd=repo
    )

    assert refused.returncode == 2
    assert semantic.VERIFIED_REQUIRES_ATTESTATION in refused.stderr
    assert _count(brain_home, "memories") == 0
    assert _verified_memories(brain_home) == 0

    persisted = _run_cli(brain_home, "remember", "Ordinary observed fact", cwd=repo)

    assert persisted.returncode == 0, persisted.stderr
    memory_id = persisted.stdout.strip()
    assert semantic.show_memory(brain_home, memory_id)["row"]["evidence_grade"] == "OBSERVED"


def test_curate_to_verified_requires_attestation(brain_home):
    """The second ingress for the same claim: curation to VERIFIED is refused at
    the authoritative writer and through the CLI, and never silently downgraded."""
    memory_id = semantic.add_memory(brain_home, "Observed fact", "Fact body", scope="global")

    with pytest.raises(BrainError) as excinfo:
        semantic.curate(brain_home, memory_id, grade="VERIFIED")
    assert semantic.VERIFIED_REQUIRES_ATTESTATION in str(excinfo.value)

    row = semantic.show_memory(brain_home, memory_id)["row"]
    assert row["evidence_grade"] == "OBSERVED"
    assert row["last_verified_at"] is None

    # The same claim through the CLI, and the `memory add` ingress of add_memory.
    curate = _run_cli(brain_home, "memory", "curate", memory_id, "--grade", "VERIFIED")
    assert curate.returncode == 2
    assert semantic.VERIFIED_REQUIRES_ATTESTATION in curate.stderr
    add = _run_cli(
        brain_home,
        "memory",
        "add",
        "Claimed",
        "Claimed body",
        "--scope",
        "global",
        "--grade",
        "VERIFIED",
    )
    assert add.returncode == 2
    assert semantic.VERIFIED_REQUIRES_ATTESTATION in add.stderr
    assert _verified_memories(brain_home) == 0

    # An unprivileged one-step upgrade is unaffected.
    assert semantic.curate(brain_home, memory_id, grade="TESTED")["evidence_grade"] == "TESTED"


def test_refused_verified_claim_reaches_no_privileged_treatment(brain_home, repo, monkeypatch):
    """The refused claim cannot become VERIFIED, so it cannot reach retrieval
    authority (admission confidence / trust score) or protected-memory state."""
    monkeypatch.setenv("SECOND_BRAIN_PROJECT", "demo")
    refused = _run_cli(
        brain_home, "remember", "Claimed verified fact", "--grade", "VERIFIED", cwd=repo
    )
    assert refused.returncode == 2
    assert semantic.VERIFIED_REQUIRES_ATTESTATION in refused.stderr

    created = _run_cli(brain_home, "remember", "Observed replacement fact", cwd=repo)
    assert created.returncode == 0, created.stderr
    memory_id = created.stdout.strip()
    semantic.curate(brain_home, memory_id, status="current")
    row = semantic.show_memory(brain_home, memory_id)["row"]

    assert _verified_memories(brain_home) == 0
    # Admission confidence follows the stored grade: the claim bought nothing.
    status, confidence = autoinject._grade_confidence(row["evidence_grade"], row["strength"], False)
    assert (status, confidence) == (contracts.MemoryItemStatus.UNCERTAIN, contracts.Confidence.LOW)
    # And a current memory is untouchable by reconsolidation only when its stored
    # grade is VERIFIED, which no caller-supplied claim can reach.
    assert reconsolidation._protected(row) is False


def test_caller_supplied_model_identity_records_no_policy_input(brain_home, repo):
    """SEC-AUTH-02: the `models` CLI cannot record outcome/policy input from a
    caller-supplied model identity."""
    recorded = _run_cli(
        brain_home,
        "models",
        "record",
        "self-claimed-model",
        "implementation",
        "task",
        "--success",
        "true",
    )

    assert recorded.returncode == 2
    assert "MODEL_IDENTITY_NOT_AUTHENTICATED" in recorded.stderr
    assert _count(brain_home, "model_skill_outcomes") == 0
