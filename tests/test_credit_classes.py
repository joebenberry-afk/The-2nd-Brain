"""Tests for design-derived credit classes and causal promotion gate (T5.4)."""

import pytest

from second_brain import credit, db, frontier, paths, plasticity, promotion, router, skillforge
from second_brain.credit import CreditClass, classify_credit


def _skill(home, name="scout", level="shadow", marker="content"):
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"# {title}\n\n- {marker}"
        for title in (
            "Purpose",
            "Positive Triggers",
            "Negative Triggers",
            "Inputs",
            "Procedure",
            "Tools",
            "Safety",
            "Verification",
            "Output",
            "References",
        )
    )
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\nstatus: {level}\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    return directory


def _approve(home, name):
    frontier.frontier_review(home, f"skill-{name}-promotion", "promote", "high", "r", "approve")


def _bind(home, name, owner="steward-scout"):
    skillforge.bind_candidate(
        home,
        name,
        source_type="frontier",
        source_ref=f"frontier-{name}",
        owner=owner,
    )
    skillforge.record_evaluation(
        home,
        name,
        {
            "evaluation_id": f"eval-{name}",
            "task_id": f"task-{name}",
            "task_hash": "t" * 64,
            "repository_state_hash": "r" * 64,
            "baseline": {"input_tokens": 1000, "output_tokens": 100},
            "candidate": {"input_tokens": 500, "output_tokens": 100},
            "quality": {
                "correctness": True,
                "requirements": True,
                "protected_values": True,
                "regressions": False,
                "verification": True,
            },
            "gates": {
                "trigger": {"failed": 0},
                "workflow": {"structural": True, "failed": 0},
                "regression": {"regression": False, "failed": 0},
                "security": {"passed": True},
            },
        },
    )

def _record_outcome(home, skill_name, session_id="s0"):
    conn = db.connect(db.db_path(home))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO model_profiles (model_id, family, capabilities, first_seen_at) "
            "VALUES ('m1', 'fam', 'cap', '2026-08-14T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO model_skill_outcomes (model_id, skill_name, task_hash, success, noise, f1, session_id, created_at) "
            "VALUES ('m1', ?, 'thash', 1, 0, 1.0, ?, '2026-08-14T00:00:00+00:00')",
            (skill_name, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_observational_evidence_is_correlated():
    """Observational evidence, missing evidence, or holdout/paired with INSUFFICIENT verdict -> CORRELATED."""
    # Non-mapping evidence
    assert classify_credit(None) == "CORRELATED"
    assert classify_credit("invalid") == "CORRELATED"
    assert classify_credit(42) == "CORRELATED"
    assert classify_credit([{"design": "holdout"}]) == "CORRELATED"

    # Empty or default mapping
    assert classify_credit({}) == "CORRELATED"

    # Observational designs
    assert classify_credit({"design": "observational"}) == "CORRELATED"
    assert classify_credit({"design": "OBSERVATIONAL", "verdict": "APPROVE"}) == "CORRELATED"
    assert classify_credit({"design": "observational", "economics": {"verdict": "PROVEN"}}) == "CORRELATED"
    assert classify_credit({"design": "other", "verdict": "APPROVE"}) == "CORRELATED"

    # Holdout / paired with INSUFFICIENT verdict
    assert classify_credit({"design": "holdout", "verdict": "INSUFFICIENT"}) == "CORRELATED"
    assert classify_credit({"design": "HOLDOUT", "verdict": "insufficient"}) == "CORRELATED"
    assert classify_credit({"design": "holdout", "economics": {"verdict": "INSUFFICIENT"}}) == "CORRELATED"
    assert classify_credit({"design": "paired", "verdict": "INSUFFICIENT"}) == "CORRELATED"
    assert classify_credit({"design": "PAIRED", "verdict": "insufficient"}) == "CORRELATED"
    assert classify_credit({"design": "paired", "economics": {"verdict": "INSUFFICIENT"}}) == "CORRELATED"

    # Paired with interaction but verdict is INSUFFICIENT -> CORRELATED
    assert classify_credit({
        "design": "paired",
        "interaction_significant": True,
        "verdict": "INSUFFICIENT",
    }) == "CORRELATED"
    assert classify_credit({
        "design": "paired",
        "has_interaction": True,
        "economics": {"verdict": "INSUFFICIENT"},
    }) == "CORRELATED"


def test_holdout_evidence_can_be_direct():
    """Holdout or paired with non-insufficient verdict -> DIRECT, negative effect -> UNRELATED_NEGATIVE, interaction -> CONTRIBUTORY."""
    # Holdout designs with non-insufficient verdict -> DIRECT
    c1 = classify_credit({"design": "holdout", "verdict": "APPROVE"})
    assert c1 == "DIRECT"
    assert c1 == "direct"
    assert c1 == CreditClass.DIRECT
    assert str(c1) == "DIRECT"

    c2 = classify_credit({"design": "HOLDOUT", "verdict": "PROVEN"})
    assert c2 == "DIRECT"

    c3 = classify_credit({"design": "holdout", "economics": {"verdict": "PASS"}})
    assert c3 == "DIRECT"

    # Paired design without interaction -> DIRECT
    c4 = classify_credit({"design": "paired", "verdict": "PROVEN", "effect": 0.35})
    assert c4 == "DIRECT"

    # Paired design with negative effect -> UNRELATED_NEGATIVE
    c_neg1 = classify_credit({"design": "paired", "effect": -0.15, "verdict": "PROVEN"})
    assert c_neg1 == "UNRELATED_NEGATIVE"
    assert c_neg1 == "unrelated_negative"
    assert c_neg1 == CreditClass.UNRELATED_NEGATIVE

    c_neg2 = classify_credit({"design": "paired", "r_bar": -0.5, "verdict": "APPROVE"})
    assert c_neg2 == "UNRELATED_NEGATIVE"

    c_neg3 = classify_credit({"design": "paired", "effect_size": "-0.01"})
    assert c_neg3 == "UNRELATED_NEGATIVE"

    # Negative effect takes precedence over interaction in paired design
    c_neg_int = classify_credit({
        "design": "paired",
        "interaction_significant": True,
        "effect": -0.2,
        "verdict": "PROVEN",
    })
    assert c_neg_int == "UNRELATED_NEGATIVE"

    # Paired design with interaction and verdict != INSUFFICIENT -> CONTRIBUTORY
    for key in ("interaction_significant", "interaction_term", "has_interaction", "significant_interaction"):
        c_int = classify_credit({"design": "paired", key: True, "verdict": "PROVEN"})
        assert c_int == "CONTRIBUTORY"
        assert c_int == "contributory"
        assert c_int == CreditClass.CONTRIBUTORY
        assert str(c_int) == "CONTRIBUTORY"
def test_promotion_requires_causal_credit(brain_home):
    """Promotion G1 requires at least one DIRECT or CONTRIBUTORY credit event.
    Neither model_skill_outcomes nor correlated credit satisfies G1.
    """
    skill_name = "test-causal-skill"
    _skill(brain_home, name=skill_name, level="shadow")
    _approve(brain_home, skill_name)
    _bind(brain_home, skill_name)

    # 1. No evidence -> promotion fails G1
    guards, _ = promotion._guard_checks(brain_home, skill_name)
    assert guards["evidence"] is False
    res_no_ev = promotion.promote(brain_home, skill_name, "shadow", "candidate")
    assert res_no_ev["promoted"] is False
    assert res_no_ev["reason"] == "no_evidence"

    # 2. Only model_skill_outcomes -> still fails G1
    _record_outcome(brain_home, skill_name)
    counts = promotion._evidence_counts(brain_home, skill_name)
    assert counts["model_skill_outcomes"] == 1
    assert counts["causal_credit_events"] == 0
    guards, _ = promotion._guard_checks(brain_home, skill_name)
    assert guards["evidence"] is False
    res_outcome_only = promotion.promote(brain_home, skill_name, "shadow", "candidate")
    assert res_outcome_only["promoted"] is False
    assert res_outcome_only["reason"] == "no_evidence"

    # 3. Only CORRELATED credit event -> still fails G1
    plasticity.record_credit(brain_home, "s_corr", skill_name, "skill", "correlated")
    counts = promotion._evidence_counts(brain_home, skill_name)
    assert counts["credit_events"] == 1
    assert counts["causal_credit_events"] == 0
    guards, _ = promotion._guard_checks(brain_home, skill_name)
    assert guards["evidence"] is False
    res_corr_only = promotion.promote(brain_home, skill_name, "shadow", "candidate")
    assert res_corr_only["promoted"] is False
    assert res_corr_only["reason"] == "no_evidence"

    # 4. CONTRIBUTORY credit event -> passes G1 and promotes successfully
    plasticity.record_credit(brain_home, "s_contrib", skill_name, "skill", "contributory")
    counts = promotion._evidence_counts(brain_home, skill_name)
    assert counts["credit_events"] == 2
    assert counts["causal_credit_events"] == 1
    guards, _ = promotion._guard_checks(brain_home, skill_name)
    assert guards["evidence"] is True
    res_contrib = promotion.promote(brain_home, skill_name, "shadow", "candidate")
    assert res_contrib["promoted"] is True
    assert (brain_home / "skills" / "candidates" / skill_name).is_dir()

    # 5. DIRECT credit event on a second skill -> passes G1
    skill_name2 = "test-causal-skill2"
    _skill(brain_home, name=skill_name2, level="shadow")
    _approve(brain_home, skill_name2)
    _bind(brain_home, skill_name2)
    plasticity.record_credit(brain_home, "s_dir", skill_name2, "skill", "direct")
    counts2 = promotion._evidence_counts(brain_home, skill_name2)
    assert counts2["causal_credit_events"] == 1
    guards2, _ = promotion._guard_checks(brain_home, skill_name2)
    assert guards2["evidence"] is True
    res_direct = promotion.promote(brain_home, skill_name2, "shadow", "candidate")
    assert res_direct["promoted"] is True
    assert (brain_home / "skills" / "candidates" / skill_name2).is_dir()


def test_routing_counterfactual_clean_rename_no_alias(brain_home):
    """counterfactual_eval is renamed to routing_counterfactual with NO alias/deprecated path."""
    assert not hasattr(credit, "counterfactual_eval"), "credit.counterfactual_eval must NOT exist (no deprecated alias)"
    assert hasattr(credit, "routing_counterfactual"), "credit.routing_counterfactual must exist"

    # Test routing_counterfactual works as expected
    skill_name = "sqlite-migration-verifier"
    directory = brain_home / "skills" / "shadow" / skill_name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {skill_name}\nstatus: shadow\nversion: 1\n---\n\n# Purpose\n\n- sqlite migration helper\n",
        encoding="utf-8",
    )

    tasks = [
        {"text": "sqlite migration failed with schema mismatch", "expect": [skill_name]},
        {"text": "generic task", "expect": []},
    ]
    res = credit.routing_counterfactual(brain_home, skill_name, tasks)
    assert "tasks_affected" in res
    assert "tasks_unaffected" in res
    assert len(res["tasks"]) == 2
