"""Focused tests for Off-Policy Evaluation (IPS/SNIPS) and decision replay (T5.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_brain import cli, contracts, db, decisions, economics
from second_brain.errors import BrainError


def test_ips_recovers_logging_policy_value():
    """Verify that when target_policy is the logging policy, IPS value equals the sample average reward."""
    rewards = [0.2, 0.8, -0.1, 0.5, 1.0, 0.0, 0.4, 0.9, -0.5, 0.7]
    sample_average = sum(rewards) / len(rewards)

    decisions_list = [
        {
            "inputs": {"query": f"task-{i}"},
            "chosen": ["mem-1"],
            "alternatives": [],
            "propensity": 1.0,
            "reward": r,
        }
        for i, r in enumerate(rewards)
    ]

    # Evaluate built-in logging policy
    res = economics.ope_ips(decisions_list, "logging")
    assert res["n"] == len(rewards)
    assert res["value"] == pytest.approx(sample_average)
    assert res["value_snips"] == pytest.approx(sample_average)
    assert res["ess"] == pytest.approx(float(len(rewards)))
    assert res["weights_sum"] == pytest.approx(float(len(rewards)))

    # Evaluate built-in current policy (alias for logging)
    res_current = economics.ope_ips(decisions_list, "current")
    assert res_current["value"] == pytest.approx(sample_average)

    # Evaluate callable target policy matching the logged action
    res_callable = economics.ope_ips(decisions_list, lambda x: ["mem-1"])
    assert res_callable["value"] == pytest.approx(sample_average)
    assert res_callable["value_snips"] == pytest.approx(sample_average)
    assert res_callable["ess"] == pytest.approx(float(len(rewards)))


def test_ess_reported():
    """Verify that ESS calculation strictly matches (sum w)^2 / sum (w^2)."""
    # Construct records with deliberate propensities and matches:
    # d0: match=1, p=0.1 -> w=10.0
    # d1: match=1, p=0.2 -> w=5.0
    # d2: match=1, p=0.5 -> w=2.0
    # d3: match=0, p=0.5 -> w=0.0
    decisions_list = [
        {"inputs": {}, "chosen": "A", "alternatives": [], "propensity": 0.1, "reward": 1.0},
        {"inputs": {}, "chosen": "A", "alternatives": [], "propensity": 0.2, "reward": 0.5},
        {"inputs": {}, "chosen": "A", "alternatives": [], "propensity": 0.5, "reward": 0.0},
        {"inputs": {}, "chosen": "B", "alternatives": [], "propensity": 0.5, "reward": 0.2},
    ]
    # target_policy chooses "A"
    res = economics.ope_ips(decisions_list, lambda x: "A")
    # Weights: [10.0, 5.0, 2.0, 0.0]
    expected_sum_w = 10.0 + 5.0 + 2.0 + 0.0  # 17.0
    expected_sum_w2 = 100.0 + 25.0 + 4.0 + 0.0  # 129.0
    expected_ess = (expected_sum_w ** 2) / expected_sum_w2  # 289.0 / 129.0 = 2.24031...

    assert res["weights_sum"] == pytest.approx(expected_sum_w)
    assert res["ess"] == pytest.approx(expected_ess)
    assert res["n"] == 4
    # Expected IPS value: (10*1.0 + 5*0.5 + 2*0.0 + 0*0.2) / 4 = 12.5 / 4 = 3.125
    assert res["value"] == pytest.approx(12.5 / 4.0)
    # Expected SNIPS value: 12.5 / 17.0 = 0.73529...
    assert res["value_snips"] == pytest.approx(12.5 / 17.0)


def test_empty_and_zero_weight_safe_handling():
    """Verify safe behavior for empty decision sets and zero matching weights."""
    empty_res = economics.ope_ips([], "logging")
    assert empty_res == {
        "value": 0.0,
        "value_snips": 0.0,
        "n": 0,
        "ess": 0.0,
        "weights_sum": 0.0,
    }

    no_match_decisions = [
        {"inputs": {}, "chosen": "A", "alternatives": [], "propensity": 1.0, "reward": 1.0},
        {"inputs": {}, "chosen": "A", "alternatives": [], "propensity": 1.0, "reward": 0.5},
    ]
    no_match_res = economics.ope_ips(no_match_decisions, lambda x: "B")
    assert no_match_res["n"] == 2
    assert no_match_res["value"] == 0.0
    assert no_match_res["value_snips"] == 0.0
    assert no_match_res["ess"] == 0.0
    assert no_match_res["weights_sum"] == 0.0


def test_propensity_clipping_bound():
    """Verify propensities below 0.05 are clipped to 0.05."""
    decisions_list = [
        {"inputs": {}, "chosen": "A", "alternatives": [], "propensity": 0.001, "reward": 1.0},
    ]
    res = economics.ope_ips(decisions_list, "logging")
    # Clipped to 0.05 -> w = 1 / 0.05 = 20.0
    assert res["weights_sum"] == pytest.approx(20.0)
    assert res["value"] == pytest.approx(20.0)


def test_builtin_policies_always_inject_and_holdout():
    """Verify built-in 'always_inject' and 'holdout' target policies."""
    records = [
        # Delivery (always_inject matches)
        {"inputs": {"withheld_id": None}, "chosen": ["m1"], "alternatives": [], "propensity": 0.9, "reward": 1.0},
        # Holdout (holdout matches)
        {"inputs": {"withheld_id": "m1"}, "chosen": [], "alternatives": ["m1"], "propensity": 0.1, "reward": 0.5},
    ]
    res_inject = economics.ope_ips(records, "always_inject")
    assert res_inject["n"] == 2
    assert res_inject["weights_sum"] == pytest.approx(1.0 / 0.9)
    # Only row 0 matches
    assert res_inject["value"] == pytest.approx((1.0 / 0.9 * 1.0) / 2)

    res_holdout = economics.ope_ips(records, "holdout")
    assert res_holdout["n"] == 2
    assert res_holdout["weights_sum"] == pytest.approx(1.0 / 0.1)
    # Only row 1 matches
    assert res_holdout["value"] == pytest.approx((1.0 / 0.1 * 0.5) / 2)


def test_record_and_list_decisions_roundtrip(brain_home):
    """Verify decisions.record persists inputs_json and list_decisions parses it."""
    d_id = decisions.record(
        brain_home,
        kind="retrieval",
        session_id="sess-ope-1",
        task_id="task-1",
        chosen=["m-10"],
        alternatives=["m-20"],
        propensity=0.5,
        randomized=True,
        policy_version="v2",
        stage="CANARY",
        inputs={"query_term": "unit test", "withheld_id": "m-20"},
    )
    decisions.set_outcome(brain_home, d_id, {"latency": 42}, 0.75)

    listed = decisions.list_decisions(brain_home, kind="retrieval")
    assert len(listed) == 1
    row = listed[0]
    assert row["decision_id"] == d_id
    assert row["inputs"] == {"query_term": "unit test", "withheld_id": "m-20"}
    assert row["chosen"] == ["m-10"]
    assert row["alternatives"] == ["m-20"]
    assert row["propensity"] == pytest.approx(0.5)
    assert row["randomized"] is True
    assert row["reward"] == pytest.approx(0.75)
    assert row["outcome"] == {"latency": 42}

    # Now evaluate via OPE
    ope_res = economics.ope_ips(listed, "holdout")
    assert ope_res["n"] == 1
    assert ope_res["value"] == pytest.approx(0.75 / 0.5)


def test_cli_ope_insufficient_logged_data_boundary(brain_home, capsys):
    """Verify CLI returns INSUFFICIENT_LOGGED_DATA when ESS < 30."""
    for i in range(10):
        d_id = decisions.record(
            brain_home,
            kind="retrieval",
            session_id=f"sess-{i}",
            task_id=f"task-{i}",
            chosen=["m-1"],
            alternatives=[],
            propensity=1.0,
            randomized=False,
            policy_version="v2",
            stage="SHADOW",
            inputs={"step": i},
        )
        decisions.set_outcome(brain_home, d_id, {"ok": True}, 0.5)

    # 1. Text output test
    ret = cli.main(["--home", str(brain_home), "v2", "learn", "ope", "--kind", "retrieval", "--policy", "logging"])
    out, err = capsys.readouterr()
    assert ret == 1
    assert "INSUFFICIENT_LOGGED_DATA (ess=10.0 < 30, n=10)" in out

    # 2. JSON output test
    ret_json = cli.main(["--home", str(brain_home), "v2", "learn", "ope", "--kind", "retrieval", "--policy", "logging", "--json"])
    out_json, err_json = capsys.readouterr()
    assert ret_json == 1
    data = json.loads(out_json)
    assert data["status"] == "INSUFFICIENT_LOGGED_DATA"
    assert data["n"] == 10
    assert data["ess"] == pytest.approx(10.0)
    assert data["value"] == pytest.approx(0.5)
    assert data["value_snips"] == pytest.approx(0.5)


def test_cli_ope_sufficient_logged_data_success(brain_home, capsys):
    """Verify CLI returns OK and exit code 0 when ESS >= 30."""
    for i in range(35):
        d_id = decisions.record(
            brain_home,
            kind="retrieval",
            session_id=f"sess-ok-{i}",
            task_id=f"task-{i}",
            chosen=["m-1"],
            alternatives=[],
            propensity=1.0,
            randomized=False,
            policy_version="v2",
            stage="ACTIVE",
            inputs={"step": i},
        )
        decisions.set_outcome(brain_home, d_id, {"ok": True}, 0.8)

    # 1. Text output test
    ret = cli.main(["--home", str(brain_home), "v2", "learn", "ope", "--kind", "retrieval", "--policy", "logging"])
    out, err = capsys.readouterr()
    assert ret == 0
    assert "OPE IPS:" in out
    assert "ess=35.0" in out
    assert "n=35" in out

    # 2. JSON output test
    ret_json = cli.main(["--home", str(brain_home), "v2", "learn", "ope", "--kind", "retrieval", "--policy", "logging", "--json"])
    out_json, err_json = capsys.readouterr()
    assert ret_json == 0
    data = json.loads(out_json)
    assert data["status"] == "OK"
    assert data["n"] == 35
    assert data["ess"] == pytest.approx(35.0)
    assert data["value"] == pytest.approx(0.8)
    assert data["value_snips"] == pytest.approx(0.8)
