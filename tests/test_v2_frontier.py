"""Focused T7.8 Knowledge Frontier / active learning tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from second_brain import decisions, frontier
from second_brain.errors import BrainError


def test_frontier_rejects_item_without_decision_ref(brain_home: Path) -> None:
    """Frontier items must represent uncertainty that links to an actual Brain decision."""
    # 1. Empty string decision_ref rejected
    with pytest.raises(BrainError, match="valid non-empty decision_ref"):
        frontier.create_frontier_item(
            brain_home,
            unknown="Is model X faster than Y on refactoring?",
            decision_ref="",
            stake_tokens=1000.0,
            p_flip=0.5,
            expected_cost=10.0,
        )

    # 2. None decision_ref rejected
    with pytest.raises(BrainError, match="valid non-empty decision_ref"):
        frontier.create_frontier_item(
            brain_home,
            unknown="Generic interesting research query without decision link",
            decision_ref=None,  # type: ignore[arg-type]
            stake_tokens=1000.0,
            p_flip=0.5,
            expected_cost=10.0,
        )


def test_frontier_unknown_cost_does_not_outrank_measured_item(brain_home: Path) -> None:
    """Items with unknown cost stay priority=null and cannot outrank measured items."""
    # Measured item: priority = 1000 * 0.5 / 100 = 5.0
    item_measured = frontier.create_frontier_item(
        brain_home,
        unknown="Should model routing switch from T1 to T0 for simple test runs?",
        decision_ref="decision:kind:routing:model_switch",
        stake_tokens=1000.0,
        p_flip=0.5,
        expected_cost=100.0,
    )
    assert item_measured["priority"] == 5.0

    # Unmeasured item: huge stake (500,000 tokens) but expected_cost is unknown (None)
    item_unknown = frontier.create_frontier_item(
        brain_home,
        unknown="Should cache eviction watermark be raised from 80% to 90%?",
        decision_ref="decision:kind:eviction:watermark",
        stake_tokens=500000.0,
        p_flip=0.9,
        expected_cost=None,  # Unknown cost!
    )
    assert item_unknown["priority"] is None

    # List items: measured item MUST be ranked first, unknown cost item ranked last!
    items = frontier.list_frontier_items(brain_home)
    assert len(items) >= 2
    assert items[0]["frontier_id"] == item_measured["frontier_id"]
    assert items[1]["frontier_id"] == item_unknown["frontier_id"]


def test_frontier_rank_formula(brain_home: Path) -> None:
    """Priority rank strictly follows priority = stake_tokens * p_flip / expected_cost."""
    # Item A: priority = 2000 * 0.4 / 200 = 4.0
    item_a = frontier.create_frontier_item(
        brain_home,
        unknown="Query reformulation threshold optimization",
        decision_ref="decision:kind:retrieval:query_threshold",
        stake_tokens=2000.0,
        p_flip=0.4,
        expected_cost=200.0,
    )
    assert item_a["priority"] == 4.0

    # Item B: priority = 3000 * 0.5 / 150 = 10.0
    item_b = frontier.create_frontier_item(
        brain_home,
        unknown="Tool filter exclusion rule refinement",
        decision_ref="decision:kind:budget:tool_filter",
        stake_tokens=3000.0,
        p_flip=0.5,
        expected_cost=150.0,
    )
    assert item_b["priority"] == 10.0

    # Item C: priority = 500 * 0.2 / 50 = 2.0
    item_c = frontier.create_frontier_item(
        brain_home,
        unknown="Abstention floor calibration on low-risk tasks",
        decision_ref="decision:kind:verification:abstention",
        stake_tokens=500.0,
        p_flip=0.2,
        expected_cost=50.0,
    )
    assert item_c["priority"] == 2.0

    items = frontier.list_frontier_items(brain_home)
    ranked_ids = [item["frontier_id"] for item in items[:3]]
    # Ranked order: B (10.0) -> A (4.0) -> C (2.0)
    assert ranked_ids == [item_b["frontier_id"], item_a["frontier_id"], item_c["frontier_id"]]


def test_frontier_item_links_to_replayable_decision(brain_home: Path) -> None:
    """Frontier item must link to an actual replayable Brain decision in the decisions ledger."""
    # Record an actual routing decision in decisions table
    dec_id = decisions.record(
        brain_home,
        kind="routing",
        session_id="session-frontier-replay-001",
        task_id="task-routing-eval",
        chosen={"model": "claude-3-5-sonnet", "route": "T2"},
        alternatives=[{"model": "claude-3-5-haiku", "route": "T0"}],
        propensity=1.0,
        randomized=False,
        policy_version="v7.4",
        stage="SHADOW",
        inputs={"task_text": "Refactor auth protocol", "risk_class": "HIGH"},
    )

    # Link frontier item directly to this replayable decision
    item = frontier.create_frontier_item(
        brain_home,
        unknown="Does Claude 3.5 Haiku succeed on auth protocol tasks when given JIT context?",
        decision_ref=f"decision:{dec_id}:routing:model_choice",
        stake_tokens=5000.0,
        p_flip=0.6,
        expected_cost=50.0,
        experiments=[
            {
                "experiment_id": "exp-local-01",
                "type": "local_mock_run",
                "cost": "local",
                "expected_gain": 0.8,
            },
            {
                "experiment_id": "exp-live-02",
                "type": "live_model_call",
                "cost": 150.0,
                "expected_gain": 0.85,
            },
        ],
    )

    assert item["decision_ref"] == f"decision:{dec_id}:routing:model_choice"
    assert item["priority"] == 60.0  # 5000 * 0.6 / 50 = 60.0

    # Test choose_cheapest_experiment prefers the local cheap discriminator
    cheapest = frontier.choose_cheapest_experiment(brain_home, item["frontier_id"])
    assert cheapest["experiment_id"] == "exp-local-01"
    assert cheapest["cost"] == "local"
