"""Tests for risk calibration and configured weights / central paths (plan T3.2)."""

from __future__ import annotations

from pathlib import Path
import pytest

from second_brain import risk


def test_risk_uses_configured_weights_and_central_paths(tmp_path: Path):
    """Test that:
    a) custom weights alter risk score as configured;
    b) central paths only matches the configured central paths (e.g.
       src/second_brain/db.py matches, but src/second_brain/monitor.py does NOT).
    """
    home = tmp_path / "brain"
    home.mkdir()
    config_dir = home / "config"
    config_dir.mkdir()
    
    # Configure custom central_paths and risk_weights in verification.toml
    toml_content = """[risk]
central_paths = [
    "src/second_brain/db.py",
    "src/second_brain/ledger.py",
    "src/second_brain/contracts.py",
    "migrations/",
]

[risk_weights]
centrality = 2.5
blast_radius = 0.5
concurrency = 1.0
persistence = 1.0
"""
    (config_dir / "verification.toml").write_text(toml_content, encoding="utf-8")
    
    repo = tmp_path / "repo"
    repo.mkdir()
    
    # 1. Test central paths: db.py is central, monitor.py is NOT central
    res_db = risk.assess_risk(repo, ["src/second_brain/db.py"], home=home)
    sig_db_centrality = next(s for s in res_db["signals"] if s["name"] == "centrality")
    assert sig_db_centrality["points"] == 2, "db.py must match central_paths"
    
    res_monitor = risk.assess_risk(repo, ["src/second_brain/monitor.py"], home=home)
    sig_monitor_centrality = next(s for s in res_monitor["signals"] if s["name"] == "centrality")
    assert sig_monitor_centrality["points"] == 0, "monitor.py must NOT match central_paths"
    
    res_migration = risk.assess_risk(repo, ["migrations/0001_init.sql"], home=home)
    sig_mig_centrality = next(s for s in res_migration["signals"] if s["name"] == "centrality")
    assert sig_mig_centrality["points"] == 2, "migrations/ must match central_paths"
    
    res_semantic = risk.assess_risk(repo, ["src/second_brain/semantic.py"], home=home)
    sig_semantic_centrality = next(s for s in res_semantic["signals"] if s["name"] == "centrality")
    assert sig_semantic_centrality["points"] == 0, "semantic.py must NOT match central_paths"
    
    # 2. Test custom weights alter risk score as configured
    # For db.py alone: blast_radius=0 points (1 file < 2), centrality=2 points.
    # Without weights: score = 0 + 2 = 2 (LOW)
    # With weights: score = 0 * 0.5 + 2 * 2.5 = 5.0 (MEDIUM, since 5 >= 3 and < 6)
    assert res_db["score"] == 5.0, f"Expected score 5.0 with centrality weight 2.5, got {res_db['score']}"
    assert res_db["level"] == "MEDIUM", f"Expected level MEDIUM, got {res_db['level']}"
    
    # For 2 files (db.py and a.py): blast_radius=1 point.
    # score = 1 * 0.5 + 2 * 2.5 = 5.5 (MEDIUM)
    res_two = risk.assess_risk(repo, ["src/second_brain/db.py", "a.py"], home=home)
    assert res_two["score"] == 5.5, f"Expected score 5.5, got {res_two['score']}"
    assert res_two["level"] == "MEDIUM"


def test_is_central_function_direct():
    """_is_central matches central_paths and rejects non-central paths."""
    assert risk._is_central("src/second_brain/db.py") is True
    assert risk._is_central("src/second_brain/ledger.py") is True
    assert risk._is_central("src/second_brain/contracts.py") is True
    assert risk._is_central("migrations/0001_x.sql") is True
    assert risk._is_central("db/migrations/0001_x.sql") is True
    
    assert risk._is_central("src/second_brain/monitor.py") is False
    assert risk._is_central("src/second_brain/semantic.py") is False
    assert risk._is_central("src/second_brain/risk.py") is False
    assert risk._is_central("src/second_brain/cli.py") is False
    
    # Custom central_paths list
    custom = ["custom/core.py", "special/"]
    assert risk._is_central("custom/core.py", central_paths=custom) is True
    assert risk._is_central("special/deep/file.py", central_paths=custom) is True
    assert risk._is_central("src/second_brain/db.py", central_paths=custom) is False


def test_logistic_regression_synthetic():
    """Unit test for calibrate_risk.py logistic regression training."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import calibrate_risk
    
    feature_names = ["blast_radius", "centrality", "concurrency"]
    X = [
        [0.0, 2.0, 0.0],
        [0.0, 2.0, 2.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [2.0, 2.0, 0.0],
    ]
    y = [1, 1, 0, 0, 1]
    
    weights, bias = calibrate_risk.fit_logistic_regression(
        X, y, feature_names, iterations=200, l2=0.1, lr=0.1
    )
    
    assert isinstance(weights, dict)
    assert len(weights) == 3
    # centrality is strongly correlated with failure, so its weight must be highest
    assert weights["centrality"] > weights["blast_radius"]
    assert weights["centrality"] > 0.5
    # Deterministic 200 iterations check
    weights2, bias2 = calibrate_risk.fit_logistic_regression(
        X, y, feature_names, iterations=200, l2=0.1, lr=0.1
    )
    assert weights == weights2
    assert bias == bias2


def test_precision_recall_computation():
    """Unit test for precision and recall calculation in calibrate_risk.py."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import calibrate_risk
    
    samples = [
        {"signals": [{"name": "centrality", "points": 2}, {"name": "blast_radius", "points": 1}], "failed": 1},
        {"signals": [{"name": "centrality", "points": 2}, {"name": "concurrency", "points": 2}, {"name": "blast_radius", "points": 2}], "failed": 1},
        {"signals": [{"name": "blast_radius", "points": 0}], "failed": 0},
        {"signals": [{"name": "centrality", "points": 2}], "failed": 0},
    ]
    
    # Unweighted: sample 0 score 3 (MEDIUM), sample 1 score 6 (HIGH), sample 2 score 0, sample 3 score 2
    # Predicted HIGH/CRITICAL: only sample 1.
    # True failures: sample 0 and 1.
    # TP=1, FP=0, FN=1, TN=2 -> Precision=1.0, Recall=0.5
    res_unweighted = calibrate_risk.compute_precision_recall(samples, weights=None)
    assert res_unweighted["precision"] == 1.0
    assert res_unweighted["recall"] == 0.5
    
    # Calibrated weights: centrality=2.5
    # sample 0 score = 2.5*2 + 1 = 6.0 (HIGH) -> now TP!
    # TP=2, FP=0, FN=0, TN=2 -> Precision=1.0, Recall=1.0
    res_weighted = calibrate_risk.compute_precision_recall(samples, weights={"centrality": 2.5, "blast_radius": 1.0})
    assert res_weighted["precision"] == 1.0
    assert res_weighted["recall"] == 1.0


def test_toml_updating(tmp_path: Path):
    """Test updating [risk_weights] in verification.toml without corrupting other sections."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import calibrate_risk
    
    toml_path = tmp_path / "verification.toml"
    toml_path.write_text("""# test config
schema_version = 1

[ladder]
LOW = ["targeted_test"]

[risk_weights]
old_signal = 0.5

[other]
flag = true
""", encoding="utf-8")
    
    weights = {"centrality": 1.45, "blast_radius": 0.25}
    calibrate_risk.write_risk_weights_to_toml(toml_path, weights)
    
    import tomllib
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["ladder"]["LOW"] == ["targeted_test"]
    assert data["other"]["flag"] is True
    assert data["risk_weights"] == {"centrality": 1.45, "blast_radius": 0.25}


def test_collect_session_data_and_calibrate_end_to_end(tmp_path: Path):
    """End-to-end test for data collection, logistic regression fitting, and config writing."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import calibrate_risk
    import json
    import tomllib

    home = tmp_path / "brain_e2e"
    home.mkdir()
    (home / "config").mkdir()
    (home / "config" / "verification.toml").write_text("""[ladder]
LOW = ["targeted_test"]

[risk]
central_paths = [
    "src/second_brain/db.py",
    "src/second_brain/ledger.py",
    "src/second_brain/contracts.py",
    "migrations/",
]
""", encoding="utf-8")

    # Session 1: touched central file db.py, failed accuracy gate
    s1_dir = home / "state" / "sessions" / "sess-1"
    s1_dir.mkdir(parents=True)
    (s1_dir / "active-state.json").write_text(json.dumps({
        "files_touched": ["src/second_brain/db.py"],
        "verification": {"completion_allowed": False, "status": "failed"},
    }), encoding="utf-8")

    # Session 2: touched non-central file README.md, passed
    s2_dir = home / "state" / "sessions" / "sess-2"
    s2_dir.mkdir(parents=True)
    (s2_dir / "active-state.json").write_text(json.dumps({
        "files_touched": ["README.md"],
        "verification": {"completion_allowed": True, "status": "verified"},
    }), encoding="utf-8")

    # Session 3: recorded via telemetry with pytest failure
    t_dir = home / "telemetry" / "agent-performance"
    t_dir.mkdir(parents=True)
    s3_telemetry = (
        json.dumps({"kind": "turn_start", "session": "sess-3", "files_touched": ["migrations/0001_init.sql"]}) + "\n" +
        json.dumps({"kind": "tool_result", "session": "sess-3", "tool": "pytest", "is_error": True, "command": "pytest tests/"}) + "\n"
    )
    (t_dir / "sess-3.jsonl").write_text(s3_telemetry, encoding="utf-8")

    # Run calibrate
    res = calibrate_risk.calibrate(home=home, repo=home, dry_run=False)

    assert res["sample_count"] == 3
    assert "weights" in res
    weights = res["weights"]
    # Centrality was present in both failed sessions (sess-1 and sess-3) and absent in passed sess-2
    assert weights["centrality"] > 0

    # Verify verification.toml updated
    cfg = tomllib.loads((home / "config" / "verification.toml").read_text(encoding="utf-8"))
    assert "risk_weights" in cfg
    assert cfg["risk_weights"]["centrality"] == weights["centrality"]

    # Verify assess_risk reads the newly written weights from home
    assessed = risk.assess_risk(home, ["src/second_brain/db.py"], home=home)
    # score must use the calibrated centrality weight * 2
    expected_score = round(weights["centrality"] * 2.0, 2)
    if expected_score.is_integer():
        expected_score = int(expected_score)
    assert assessed["score"] == expected_score
