"""Tests for the deterministic risk controller (Phase 7)."""

import subprocess

import pytest

from second_brain import risk
from second_brain.errors import BrainError


def _make_repo(tmp_path, file="hot.py", commits=0):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    for i in range(commits):
        (repo / file).write_text(f"line {i}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", f"c{i}"], cwd=repo, check=True, capture_output=True)
    return repo


def _signal(result, name):
    return next(s for s in result["signals"] if s["name"] == name)


# ---------------------------------------------------------------------------
# Signal math
# ---------------------------------------------------------------------------


def test_blast_radius_points(tmp_path):
    assert _signal(risk.assess_risk(tmp_path, ["a.py"]), "blast_radius")["points"] == 0
    assert (
        _signal(risk.assess_risk(tmp_path, ["a.py", "b.py", "c.py"]), "blast_radius")["points"] == 1
    )
    assert (
        _signal(risk.assess_risk(tmp_path, [f"f{i}.py" for i in range(6)]), "blast_radius")[
            "points"
        ]
        == 2
    )


@pytest.mark.parametrize(
    "path",
    [
        "src/second_brain/db.py",
        "src/second_brain/ledger.py",
        "src/second_brain/contracts.py",
        "migrations/0001_x.sql",
        "db/migrations/0001_x.sql",
    ],
)
def test_centrality_signal(tmp_path, path):
    result = risk.assess_risk(tmp_path, [path])
    assert _signal(result, "centrality")["points"] == 2
    assert _signal(result, "centrality")["detail"]


def test_centrality_no_match(tmp_path):
    result = risk.assess_risk(
        tmp_path, ["README.md", "src/app/main.py", "src/second_brain/monitor.py"]
    )
    assert _signal(result, "centrality")["points"] == 0


def test_concurrency_signal(tmp_path):
    for path in ["state/locks/app.lock", "src/daemon.py", "proc/ownership.json"]:
        assert _signal(risk.assess_risk(tmp_path, [path]), "concurrency")["points"] == 2
    assert _signal(risk.assess_risk(tmp_path, ["plain.py"]), "concurrency")["points"] == 0


def test_persistence_signal(tmp_path):
    for path in ["db/brain.sqlite", "src/second_brain/migrations/0002_x.sql"]:
        assert _signal(risk.assess_risk(tmp_path, [path]), "persistence")["points"] == 2


def test_security_boundary_signal(tmp_path):
    for path in [
        "constitution/security-boundaries.md",
        "immune/quarantine/x",
        "config/secrets.toml",
        "state/security/fp.json",
    ]:
        assert _signal(risk.assess_risk(tmp_path, [path]), "security_boundary")["points"] == 2


def test_public_api_signal(tmp_path):
    for path in ["src/second_brain/cli.py", "brainstem/prime-extension/src/index.ts"]:
        assert _signal(risk.assess_risk(tmp_path, [path]), "public_api")["points"] == 2
    assert (
        _signal(risk.assess_risk(tmp_path, ["src/second_brain/db.py"]), "public_api")["points"] == 0
    )


def test_data_loss_signal(tmp_path):
    for path in ["src/second_brain/backup.py", "scripts/restore.ps1", "tools/rmtree.py"]:
        assert _signal(risk.assess_risk(tmp_path, [path]), "data_loss")["points"] == 2


def test_config_scope_signal(tmp_path):
    for path in ["config/brain.toml", "src/second_brain/defaults/config/brain.toml"]:
        assert _signal(risk.assess_risk(tmp_path, [path]), "config_scope")["points"] == 2
    assert _signal(risk.assess_risk(tmp_path, ["configure.py"]), "config_scope")["points"] == 0


def test_hotspot_signal(tmp_path):
    repo = _make_repo(tmp_path, commits=2)
    signal = _signal(risk.assess_risk(repo, ["hot.py"]), "hotspot")
    assert signal["value"] == 2
    assert signal["points"] == 1

    repo7 = _make_repo(tmp_path / "r7", commits=7)
    assert _signal(risk.assess_risk(repo7, ["hot.py"]), "hotspot")["points"] == 2

    # Repo with commits, but the assessed file was never committed.
    repo0 = _make_repo(tmp_path / "r0", commits=1)
    signal0 = _signal(risk.assess_risk(repo0, ["never_committed.py"]), "hotspot")
    assert signal0["points"] == 0
    assert "no git history" in signal0["detail"]


def test_hotspot_unavailable_graced(tmp_path):
    result = risk.assess_risk(tmp_path / "missing", ["a.py"])  # repo does not exist
    signal = _signal(result, "hotspot")
    assert signal["points"] == 0
    assert signal["detail"] == "unavailable"
    # Not a git repo either.
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("x", encoding="utf-8")
    assert _signal(risk.assess_risk(plain, ["a.py"]), "hotspot")["detail"] == "unavailable"


# ---------------------------------------------------------------------------
# Thresholds and overrides
# ---------------------------------------------------------------------------


def test_level_thresholds(tmp_path):
    assert risk.assess_risk(tmp_path, ["readme.md"])["level"] == "LOW"  # score 0
    # blast 1 + concurrency 2 = 3 -> MEDIUM (lower boundary).
    assert risk.assess_risk(tmp_path, ["a.py", "b.py", "state/locks/x.lock"])["level"] == "MEDIUM"
    # blast 1 + centrality 2 + persistence 2 = 5 -> MEDIUM (upper boundary).
    assert risk.assess_risk(tmp_path, ["a.py", "b.py", "migrations/0001.sql"])["level"] == "MEDIUM"
    # blast 1 + centrality 2 + persistence 2 + hotspot 1 = 6 -> HIGH (lower boundary).
    repo = _make_repo(tmp_path, commits=2)
    assert risk.assess_risk(repo, ["migrations/0001.sql", "hot.py"])["level"] == "HIGH"
    # blast 1 + centrality 2 + persistence 2 + config 2 = 7 -> HIGH.
    assert (
        risk.assess_risk(tmp_path, ["a.py", "migrations/0001.sql", "config/y.toml"])["level"]
        == "HIGH"
    )
    # blast 1 + centrality 2 + persistence 2 + config 2 + security 2 = 9 -> CRITICAL.
    result = risk.assess_risk(
        tmp_path, ["a.py", "migrations/0001.sql", "config/y.toml", "constitution/z.md"]
    )
    assert result["level"] == "CRITICAL"
    assert result["score"] == 9


def test_override_raises_not_lowers(tmp_path):
    base = risk.assess_risk(tmp_path, ["readme.md"])  # LOW
    assert base["level"] == "LOW"
    assert (
        risk.assess_risk(tmp_path, ["readme.md"], user_criticality="CRITICAL")["level"]
        == "CRITICAL"
    )
    assert risk.assess_risk(tmp_path, ["readme.md"], user_criticality="HIGH")["level"] == "HIGH"

    critical = risk.assess_risk(
        tmp_path, ["a.py", "migrations/0001.sql", "config/y.toml", "constitution/z.md"]
    )  # CRITICAL
    assert critical["level"] == "CRITICAL"
    assert (
        risk.assess_risk(
            tmp_path,
            ["a.py", "migrations/0001.sql", "config/y.toml", "constitution/z.md"],
            user_criticality="LOW",
        )["level"]
        == "CRITICAL"
    )


def test_override_invalid_ignored(tmp_path):
    result = risk.assess_risk(
        tmp_path, ["a.py", "b.py", "state/locks/x.lock"], user_criticality="BOGUS"
    )
    assert result["level"] == "MEDIUM"
    assert result["user_criticality"] == "BOGUS"


def test_score_is_sum_of_points(tmp_path):
    result = risk.assess_risk(tmp_path, ["a.py", "migrations/0001.sql", "config/y.toml"])
    assert result["score"] == sum(s["points"] for s in result["signals"])
    assert [s["name"] for s in result["signals"]] == list(risk.SIGNAL_NAMES)


def test_empty_files_never_raise(tmp_path):
    result = risk.assess_risk(tmp_path, [])
    assert result["score"] == 0
    assert result["level"] == "LOW"


def test_invalid_files_type_raises(tmp_path):
    with pytest.raises(BrainError, match="files_touched"):
        risk.assess_risk(tmp_path, "not-a-list")  # type: ignore[arg-type]
