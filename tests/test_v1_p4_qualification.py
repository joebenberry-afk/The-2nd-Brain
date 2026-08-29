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

import hashlib
import importlib.util
import json
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
check_artifact_hash_integrity = VERIFIER.check_artifact_hash_integrity
check_privacy_absence = VERIFIER.check_privacy_absence


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
    artifact backs -- even when the fabricated value is echoed elsewhere in
    the scenario dict itself (an unrelated extra field), proving the
    haystack is never the manifest row's own JSON text."""
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
        },
        # A fabricated claim that also happens to be echoed in an unrelated
        # extra manifest field must never "self-ground" via the row's own
        # JSON text.
        "note": "totally-fabricated-model-xyz",
    }
    ok, detail = claims_grounded(fabricated_scenario, out_dir)
    assert ok is False
    assert "not backed by any raw artifact" in detail


def test_claims_grounded_rejects_numeric_and_boolean_claims_not_in_raw_artifacts(tmp_path):
    """`token`- and `success`-keyed claims are checked independently of the
    `model` claim: each fabricated value must be rejected on its own, never
    accepted because it happens to match the manifest row's own JSON."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "fake_scenario_2"
    scen_dir.mkdir(parents=True)
    stdout_path = scen_dir / "01-cmd.stdout"
    stdout_path.write_text("nothing fabricated here", encoding="utf-8")
    ref = str(stdout_path.relative_to(out_dir).as_posix())

    for fabricated_key, fabricated_value in (
        ("reasoning_tokens", 999999),
        ("success", True),
    ):
        scenario = {
            "name": "fake_scenario_2",
            "evidence_refs": [ref],
            "commands": [{"stdout_ref": ref, "stderr_ref": None}],
            "metrics": {fabricated_key: fabricated_value},
        }
        ok, detail = claims_grounded(scenario, out_dir)
        assert ok is False, (fabricated_key, detail)
        assert "not backed by any raw artifact" in detail


def test_claims_grounded_accepts_claim_backed_only_by_evidence_ref_file(tmp_path):
    """A claim backed only by a non-command `evidence_refs` snapshot (a
    write_evidence() telemetry fixture, never a command stdout/stderr
    stream) must still be accepted as genuinely grounded."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "compacted_session"
    scen_dir.mkdir(parents=True)
    evidence_path = scen_dir / "01-compact-telemetry-records.json"
    evidence_path.write_text(
        json.dumps([{"kind": "session_compact", "model": "claude-real-model"}]), encoding="utf-8",
    )
    ref = str(evidence_path.relative_to(out_dir).as_posix())

    scenario = {
        "name": "compacted_session",
        "evidence_refs": [ref],
        "commands": [],
        "metrics": {"model": "claude-real-model"},
    }
    ok, detail = claims_grounded(scenario, out_dir)
    assert ok is True, detail


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


def test_artifact_hash_integrity_catches_tampered_non_command_evidence_ref(tmp_path):
    """A non-command `evidence_refs` artifact (a write_evidence() snapshot,
    never a command stdout/stderr stream) that is tampered with after the
    manifest recorded its hash must be caught by the integrity check."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "stale_state"
    scen_dir.mkdir(parents=True)
    evidence_path = scen_dir / "01-seed-telemetry.json"
    original = json.dumps([{"v": 2, "kind": "seed"}])
    evidence_path.write_text(original, encoding="utf-8")
    original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
    ref = str(evidence_path.relative_to(out_dir).as_posix())

    manifest = {
        "setup_commands": [],
        "scenarios": [
            {
                "name": "stale_state",
                "commands": [],
                "evidence_refs": [ref],
                "evidence_ref_hashes": {ref: original_hash},
            },
        ],
    }
    clean = check_artifact_hash_integrity(manifest, out_dir)
    assert clean["ok"] is True, clean

    evidence_path.write_text(json.dumps([{"v": 2, "kind": "tampered"}]), encoding="utf-8")
    tampered = check_artifact_hash_integrity(manifest, out_dir)
    assert tampered["ok"] is False
    assert ref in tampered["detail"]["mismatches"]

    evidence_path.unlink()
    removed = check_artifact_hash_integrity(manifest, out_dir)
    assert removed["ok"] is False
    assert ref in removed["detail"]["missing"]


def test_check_privacy_absence_flags_marker_in_non_command_evidence_ref(tmp_path):
    """A non-command evidence_refs file (not command stdout/stderr, not a
    telemetry home) that contains a forbidden privacy field must be caught,
    not silently skipped."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "compacted_session"
    scen_dir.mkdir(parents=True)
    evidence_path = scen_dir / "01-compact-telemetry-records.json"
    evidence_path.write_text(json.dumps([{"prompt": "leaked prompt text"}]), encoding="utf-8")
    ref = str(evidence_path.relative_to(out_dir).as_posix())

    manifest = {
        "home": str(tmp_path / "nonexistent-home"),
        "setup_commands": [],
        "scenarios": [
            {
                "name": "compacted_session",
                "commands": [],
                "evidence_refs": [ref],
            },
        ],
    }
    result = check_privacy_absence(manifest, out_dir)
    assert result["ok"] is False
    assert any(
        ref in offender and "prompt" in offender for offender in result["detail"]["offenders"]
    ), result["detail"]["offenders"]


def test_artifact_hash_integrity_requires_command_capture_hashes(tmp_path):
    """Command evidence is invalid when a capture exists without its hash."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "fresh_session"
    scen_dir.mkdir(parents=True)
    stdout_path = scen_dir / "01-doctor.stdout"
    stdout_path.write_text("observed", encoding="utf-8")
    ref = str(stdout_path.relative_to(out_dir).as_posix())

    manifest = {
        "setup_commands": [
            {"stdout_ref": ref, "stderr_ref": None},
        ],
        "scenarios": [],
    }
    result = check_artifact_hash_integrity(manifest, out_dir)
    assert result["ok"] is False
    assert ref in result["detail"]["unhashed"]


def test_check_privacy_absence_scans_nested_evidence_fields_case_insensitively(tmp_path):
    """Nested and differently-cased privacy fields are still violations."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "compacted_session"
    scen_dir.mkdir(parents=True)
    evidence_path = scen_dir / "01-compact-telemetry-records.json"
    evidence_path.write_text(
        json.dumps([{"metadata": {"PROMPT": "leaked prompt text"}}]),
        encoding="utf-8",
    )
    ref = str(evidence_path.relative_to(out_dir).as_posix())

    manifest = {
        "home": str(tmp_path / "nonexistent-home"),
        "setup_commands": [],
        "scenarios": [
            {
                "name": "compacted_session",
                "commands": [],
                "evidence_refs": [ref],
            },
        ],
    }
    result = check_privacy_absence(manifest, out_dir)
    assert result["ok"] is False
    assert any(ref in offender and "PROMPT" in offender for offender in result["detail"]["offenders"])


def test_artifact_hash_integrity_rejects_evidence_ref_outside_output_dir(tmp_path):
    """Manifest refs cannot make the verifier hash an unrelated file."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("not qualification evidence", encoding="utf-8")
    ref = "../outside.json"

    manifest = {
        "setup_commands": [],
        "scenarios": [
            {
                "name": "stale_state",
                "commands": [],
                "evidence_refs": [ref],
                "evidence_ref_hashes": {
                    ref: hashlib.sha256(outside.read_bytes()).hexdigest(),
                },
            },
        ],
    }
    result = check_artifact_hash_integrity(manifest, out_dir)
    assert result["ok"] is False
    assert ref in result["detail"]["missing"]
