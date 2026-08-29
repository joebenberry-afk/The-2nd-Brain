"""Contract tests for the real v1 P4 qualification runner and verifier
(Task 8).

Loads `scripts/run_v1_p4_qualification.py` and
`scripts/verify_v1_p4_qualification.py` the same way
`tests/test_p3_campaign_harness.py` loads campaign scripts: by file path,
since `scripts/` is not an importable package. The module is registered in
`sys.modules` before execution so `@dataclass` (which looks up
`sys.modules[cls.__module__]`) resolves correctly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SCENARIOS = {
    "fresh_session", "resumed_session", "compacted_session",
    "cross_session_continuity", "harness_isolation", "harness_switch",
    "driver_worker", "failed_worker", "malformed_state", "stale_state",
    "token_pressure", "cache_sensitive", "long_running_goal",
    "brain_off", "brain_on", "recovery_rollback",
    "security_boundary", "genuine_project_dogfood",
}


def _load_script(name: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load_script("run_v1_p4_qualification")
VERIFIER = _load_script("verify_v1_p4_qualification")

run_qualification = RUNNER.run_qualification
claims_grounded = VERIFIER.claims_grounded


def test_qualification_manifest_has_all_required_scenarios(tmp_path):
    manifest = run_qualification(tmp_path / "out", repo=REPO_ROOT)
    names = {row["name"] for row in manifest["scenarios"]}
    assert names == REQUIRED_SCENARIOS
    assert manifest["git"]["sha"]


@pytest.fixture(scope="module")
def qualified(tmp_path_factory):
    """Run the real qualification once and share it across the assertions
    below (each real run drives ~20 subprocesses; sharing keeps the suite
    fast without weakening any individual check)."""
    out_dir = tmp_path_factory.mktemp("q8-shared") / "out"
    manifest = run_qualification(out_dir, repo=REPO_ROOT)
    return manifest, out_dir


def test_every_scenario_appears_exactly_once(qualified):
    manifest, _ = qualified
    names = [row["name"] for row in manifest["scenarios"]]
    assert len(names) == len(REQUIRED_SCENARIOS)
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    assert all(count == 1 for count in counts.values()), counts


def test_every_scenario_carries_required_contract_fields(qualified):
    manifest, _ = qualified
    for row in manifest["scenarios"]:
        assert row["status"] == "passed", (row["name"], row.get("error"))
        assert isinstance(row["evidence_refs"], list) and row["evidence_refs"], row["name"]
        assert isinstance(row["commands"], list), row["name"]
        assert isinstance(row["metrics"], dict), row["name"]


def test_unavailable_counters_are_none_never_synthesized(qualified):
    """None of these scenarios invoke a real model; every provider-token
    counter must be `None` (unavailable), never a fabricated 0 or number."""
    manifest, _ = qualified
    for row in manifest["scenarios"]:
        tokens = row["metrics"].get("provider_tokens")
        if tokens is None:
            continue
        for key, value in tokens.items():
            assert value is None, (
                f"{row['name']}.provider_tokens.{key} claims {value!r} with no real "
                "assistant_usage telemetry to back it"
            )


def test_real_manifest_claims_are_all_grounded(qualified):
    manifest, out_dir = qualified
    for row in manifest["scenarios"]:
        ok, detail = claims_grounded(row, out_dir)
        assert ok, detail


def test_claims_grounded_rejects_fabricated_model_and_token_values(tmp_path):
    """The independent verifier's grounding check must reject a manifest
    scenario asserting a `model`, `token`, or `success` value that no raw
    artifact backs."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "fake_scenario"
    scen_dir.mkdir(parents=True)
    stdout_path = scen_dir / "01-cmd.stdout"
    stdout_path.write_text("real observed output; nothing fabricated here", encoding="utf-8")

    fabricated_scenario = {
        "name": "fake_scenario",
        "status": "passed",
        "evidence_refs": [str(stdout_path.relative_to(out_dir).as_posix())],
        "commands": [
            {"stdout_ref": str(stdout_path.relative_to(out_dir).as_posix()), "stderr_ref": None},
        ],
        "metrics": {
            "model": "totally-fabricated-model-xyz",
            "provider_tokens": {"total": 999999, "input": None, "output": None},
            "success": True,
        },
    }
    ok, detail = claims_grounded(fabricated_scenario, out_dir)
    assert ok is False
    assert "not backed by any raw artifact" in detail


def test_claims_grounded_accepts_null_counters(tmp_path):
    """A scenario asserting only `None` provider-token/model claims is never
    rejected as fabrication: `None` is an honest 'unavailable', not a claim."""
    out_dir = tmp_path / "out"
    honest_scenario = {
        "name": "honest_scenario",
        "status": "passed",
        "evidence_refs": [],
        "commands": [],
        "metrics": {
            "model": None,
            "provider_tokens": {"total": None, "input": None, "output": None},
            "success": None,
            "background_model_calls": 0,
        },
    }
    ok, detail = claims_grounded(honest_scenario, out_dir)
    assert ok is True, detail
