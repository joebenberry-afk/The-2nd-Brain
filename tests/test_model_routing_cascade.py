"""Focused tests for T3.3 expected-cost routing with verifier cascade (Plan P3.3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from second_brain import crossmodel, db, model_routing, verify


def _candidate(
    provider: str,
    model: str,
    *,
    tier: str,
    cost: str,
    roles: tuple[str, ...] = (),
    available: bool = True,
    max_risk: str = "CRITICAL",
    capabilities: tuple[str, ...] = (),
    quality_score: float | None = None,
) -> model_routing.ModelCandidate:
    return model_routing.ModelCandidate(
        provider=provider,
        model=model,
        tier=tier,
        cost_class=cost,
        roles=roles,
        available=available,
        max_risk=max_risk,
        capabilities=capabilities,
        quality_score=quality_score,
    )


def _init_repo(repo: Path) -> None:
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)


def test_route_prefers_cheaper_model_only_if_expected_cost_lower(brain_home: Path) -> None:
    # Model A: low cost (rank 1), low success rate (1/10 successes -> (1+1)/(10+2) = 2/12 = 0.1667)
    # Expected cost A = 1 / 0.1667 = 6.0
    # Model B: price rank 2, smoothed success rate 10/12.
    # Expected cost B = 2 / 0.8333 = 2.4
    # Despite Model B being more expensive per call, expected cost is lower, so B is preferred.
    crossmodel.record_model(brain_home, "cheap-low-success", family="cheap")
    crossmodel.record_model(brain_home, "medium-high-success", family="medium")

    # Insert historical outcomes in model_skill_outcomes
    for _ in range(1):
        crossmodel.record_skill_outcome(
            brain_home, "cheap-low-success", "implementation", "implement feature", True
        )
    for _ in range(9):
        crossmodel.record_skill_outcome(
            brain_home, "cheap-low-success", "implementation", "implement feature", False
        )

    for _ in range(9):
        crossmodel.record_skill_outcome(
            brain_home, "medium-high-success", "implementation", "implement feature", True
        )
    for _ in range(1):
        crossmodel.record_skill_outcome(
            brain_home, "medium-high-success", "implementation", "implement feature", False
        )

    p_a = model_routing.p_success("cheap-low-success", "implementation", home=brain_home)
    p_b = model_routing.p_success("medium-high-success", "implementation", home=brain_home)
    assert abs(p_a - (2 / 12)) < 1e-4
    assert abs(p_b - (10 / 12)) < 1e-4

    candidates = [
        _candidate("p", "cheap-low-success", tier="balanced", cost="low", capabilities=("coding",)),
        _candidate(
            "p", "medium-high-success", tier="balanced", cost="medium", capabilities=("coding",)
        ),
    ]

    decision = model_routing.route_model(
        "implement feature",
        candidates,
        home=brain_home,
        role="dev",
    )
    assert decision.selected_model == "medium-high-success"

    # Now test scenario where cheaper model has higher/equal success rate:
    # Model C: price rank 1, smoothed success rate 10/12, expected cost 1.2.
    # Model C expected cost 1.2 < Model B expected cost 2.4 -> C is preferred.
    crossmodel.record_model(brain_home, "cheap-high-success", family="cheap")
    for _ in range(9):
        crossmodel.record_skill_outcome(
            brain_home, "cheap-high-success", "implementation", "implement feature", True
        )
    for _ in range(1):
        crossmodel.record_skill_outcome(
            brain_home, "cheap-high-success", "implementation", "implement feature", False
        )

    decision2 = model_routing.route_model(
        "implement feature",
        [
            _candidate(
                "p", "cheap-high-success", tier="balanced", cost="low", capabilities=("coding",)
            ),
            _candidate(
                "p", "medium-high-success", tier="balanced", cost="medium", capabilities=("coding",)
            ),
        ],
        home=brain_home,
        role="dev",
    )
    assert decision2.selected_model == "cheap-high-success"


def test_outcome_recorded_from_verification(brain_home: Path, repo: Path) -> None:
    _init_repo(repo)
    # Ensure migration 0013 index is applied
    db_path = db.db_path(brain_home)
    db.migrate(db_path)

    conn = db.connect(db_path)
    indexes = [
        row[1] for row in conn.execute("PRAGMA index_list('model_skill_outcomes')").fetchall()
    ]
    conn.close()
    assert "idx_outcomes_model_skill" in indexes

    # Call evaluate_accuracy_gate with model_id
    actions = {
        token: "passed"
        for token in verify.expand_ladder_actions(verify.DEFAULT_VERIFICATION_LADDER, "LOW")
    }
    result = verify.evaluate_accuracy_gate(
        brain_home,
        "gate-sess-001",
        repo,
        ["README.md"],
        action_states=actions,
        model_id="test-model-alpha",
        skill_name="implementation",
        task="implement feature",
    )
    assert result["completion_allowed"] is True

    # Verify model_skill_outcomes has the auto-recorded row
    conn = db.connect(db_path)
    rows = conn.execute(
        "SELECT model_id, skill_name, success, session_id FROM model_skill_outcomes WHERE"
        " model_id = ?",
        ("test-model-alpha",),
    ).fetchall()
    conn.close()

    assert len(rows) >= 1
    assert rows[0][0] == "test-model-alpha"
    assert rows[0][1] == "implementation"
    assert rows[0][2] == 1
    assert rows[0][3] == "gate-sess-001"


def test_escalates_after_verifier_failure(brain_home: Path) -> None:
    candidates = [
        _candidate("p", "model-efficient", tier="efficient", cost="low", capabilities=("coding",)),
        _candidate("p", "model-balanced", tier="balanced", cost="medium", capabilities=("coding",)),
        _candidate(
            "p",
            "model-premium",
            tier="premium",
            cost="high",
            capabilities=("coding", "architecture"),
        ),
    ]

    initial_decision = model_routing.route_model(
        "implement a feature",
        candidates,
        home=brain_home,
        role="dev",
    )
    assert initial_decision.selected_model == "model-efficient"
    assert initial_decision.selected_tier == "efficient"

    # Simulate verifier failure: cascade retry should escalate to balanced
    retry_decision = model_routing.route_model(
        "implement a feature",
        candidates,
        home=brain_home,
        role="dev",
        verifier_failed=True,
        previous_decision=initial_decision,
    )
    assert retry_decision.selected_tier == "balanced"
    assert retry_decision.selected_model == "model-balanced"
    assert retry_decision.escalation is True

    # Simulate second verifier failure: cascade retry should escalate to premium
    retry2_decision = model_routing.route_model(
        "implement a feature",
        candidates,
        home=brain_home,
        role="dev",
        verifier_failed=True,
        previous_decision=retry_decision,
        premium_authorized=True,
        premium_justification=("repeated_failure",),
    )
    assert retry2_decision.selected_tier == "premium"
    assert retry2_decision.selected_model == "model-premium"
    assert retry2_decision.escalation is True

    # Risk floor test: if minimum_tier is already balanced, never route below it
    floor_decision = model_routing.route_model(
        "implement a feature",
        candidates,
        home=brain_home,
        role="integrator",
        minimum_tier="balanced",
        verifier_failed=True,
        previous_tier="efficient",
    )
    assert floor_decision.selected_tier == "balanced"


def test_task_class_mapping() -> None:
    assert model_routing.classify_task("trivial") == model_routing.TaskClass.TRIVIAL
    assert model_routing.classify_task("summarize the README") == model_routing.TaskClass.TRIVIAL
    assert (
        model_routing.classify_task("find where config is loaded")
        == model_routing.TaskClass.NAVIGATION
    )
    assert (
        model_routing.classify_task("implement new feature")
        == model_routing.TaskClass.IMPLEMENTATION
    )
    assert model_routing.classify_task("debug error in query") == model_routing.TaskClass.DEBUGGING
    assert (
        model_routing.classify_task("verify test assertions")
        == model_routing.TaskClass.VERIFICATION
    )
    assert (
        model_routing.classify_task("explore alternative designs")
        == model_routing.TaskClass.EXPLORATION
    )
    assert (
        model_routing.classify_task("modify critical production security")
        == model_routing.TaskClass.HIGH_RISK
    )
    assert (
        model_routing.classify_task("continue session work") == model_routing.TaskClass.CONTINUATION
    )
    # 16-hex hash maps deterministically to a TaskClass
    hex_hash = "a1b2c3d4e5f60718"
    mapped = model_routing.classify_task(hex_hash)
    assert isinstance(mapped, model_routing.TaskClass)


def test_p_success_fallback_hierarchy(brain_home: Path) -> None:
    # 1. No data at all -> default 0.5
    assert model_routing.p_success("unknown-model", "implementation", home=brain_home) == 0.5

    # 2. Add outcome for a model in family "claude"
    crossmodel.record_model(brain_home, "claude-3-haiku", family="claude")
    crossmodel.record_model(brain_home, "claude-3-5-sonnet", family="claude")

    for _ in range(8):
        crossmodel.record_skill_outcome(brain_home, "claude-3-haiku", "trivial", "summarize", True)
    for _ in range(2):
        crossmodel.record_skill_outcome(brain_home, "claude-3-haiku", "trivial", "summarize", False)

    # claude-3-haiku for 'trivial' has exact outcomes: (8+1)/(10+2) = 9/12 = 0.75
    assert abs(model_routing.p_success("claude-3-haiku", "trivial", home=brain_home) - 0.75) < 1e-4

    # No exact Sonnet outcome: use the observed Claude family outcomes.
    # Fallback to (model_family, *): family outcomes = 8 successes, 10 total -> (8+1)/(10+2) = 0.75
    p_fam = model_routing.p_success("claude-3-5-sonnet", "implementation", home=brain_home)
    assert abs(p_fam - 0.75) < 1e-4


def test_exploration_randomize_only_trivial_navigation_and_canary(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates = [
        _candidate("p", "c1", tier="balanced", cost="low", capabilities=("coding",)),
        _candidate("p", "c2", tier="balanced", cost="low", capabilities=("coding",)),
    ]

    randomize_called = False

    def mock_randomize(choice, alts, epsilon, rng_seed=None):
        nonlocal randomize_called
        randomize_called = True
        return alts[1], 0.5, True

    monkeypatch.setattr(model_routing.decisions, "randomize", mock_randomize)

    # Implementation task (not trivial/navigation): should NOT randomize even if stage == CANARY
    randomize_called = False
    d1 = model_routing.route_model(
        "implement something",
        candidates,
        home=brain_home,
        stage="CANARY",
        task_class="implementation",
    )
    assert randomize_called is False
    assert d1.selected_model == "c1"

    # Trivial task with stage OFF: should NOT randomize
    randomize_called = False
    d2 = model_routing.route_model(
        "summarize the README",
        candidates,
        home=brain_home,
        stage="OFF",
    )
    assert randomize_called is False
    assert d2.selected_model == "c1"

    # Trivial task with stage CANARY: SHOULD randomize!
    randomize_called = False
    d3 = model_routing.route_model(
        "summarize the README",
        candidates,
        home=brain_home,
        stage="CANARY",
    )
    assert randomize_called is True
    assert d3.selected_model == "c2"
    assert d3.reason_code == "EXPLORATION_RANDOMIZED"


def test_route_cascade_helper(brain_home: Path) -> None:
    candidates = [
        _candidate("p", "m1", tier="efficient", cost="low", capabilities=("coding",)),
        _candidate("p", "m2", tier="balanced", cost="medium", capabilities=("coding",)),
    ]
    first = model_routing.route_model("code something", candidates, home=brain_home, role="dev")
    assert first.selected_model == "m1"
    assert first.selected_tier == "efficient"

    # Use route_cascade with first decision
    cascaded = model_routing.route_cascade(
        first,
        candidates,
        home=brain_home,
        role="dev",
    )
    assert cascaded.selected_tier == "balanced"
    assert cascaded.selected_model == "m2"
    assert cascaded.escalation is True
