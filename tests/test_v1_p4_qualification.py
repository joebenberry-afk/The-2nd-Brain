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
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SCENARIOS = {
    "fresh_session",
    "resumed_session",
    "compacted_session",
    "cross_session_continuity",
    "harness_isolation",
    "harness_switch",
    "malformed_state",
    "stale_state",
    "token_pressure",
    "cache_sensitive",
    "long_running_goal",
    "brain_off",
    "brain_on",
    "recovery_rollback",
    "security_boundary",
    "genuine_project_dogfood",
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
confined_evidence_path = RUNNER._confined_evidence_path
claims_grounded = VERIFIER.claims_grounded
check_artifact_hash_integrity = VERIFIER.check_artifact_hash_integrity
check_privacy_absence = VERIFIER.check_privacy_absence
read_json_ref = VERIFIER._read_json_ref


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_manifest(repo: Path, recorded_sha: str) -> dict:
    return {"repo": str(repo), "git": {"sha": recorded_sha}}


def test_qualification_rejects_foreign_runtime_before_initializing_home(tmp_path):
    repo = tmp_path / "other-repository"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "source.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    output = tmp_path / "qualification"

    with pytest.raises(RuntimeError):
        run_qualification(output, repo)

    assert not (output / "homes" / "shared").exists()


def test_git_currency_accepts_exact_recorded_sha(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "source.py").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "baseline",
    )
    recorded_sha = _git(repo, "rev-parse", "HEAD")

    result = VERIFIER.check_git_currency(_git_manifest(repo, recorded_sha))

    assert result["ok"] is True, result
    assert result["detail"]["fresh_sha"] == recorded_sha


def test_git_currency_accepts_evidence_only_descendant(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "source.py").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "baseline",
    )
    recorded_sha = _git(repo, "rev-parse", "HEAD")

    evidence = repo / "outputs" / "reports" / "v1-p4" / "raw" / "capture.stdout"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("captured\n", encoding="utf-8")
    _git(repo, "add", str(evidence.relative_to(repo)))
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "evidence",
    )

    result = VERIFIER.check_git_currency(_git_manifest(repo, recorded_sha))

    assert result["ok"] is True, result
    assert result["detail"]["disallowed_paths"] == []


def test_git_currency_rejects_source_change_descendant(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "source.py").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "baseline",
    )
    recorded_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "source.py").write_text("changed\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "source change",
    )

    result = VERIFIER.check_git_currency(_git_manifest(repo, recorded_sha))

    assert result["ok"] is False, result
    assert result["detail"]["disallowed_paths"] == ["source.py"]


def test_git_currency_rejects_source_rename_into_evidence_namespace(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "source.py").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "baseline",
    )
    recorded_sha = _git(repo, "rev-parse", "HEAD")

    destination = repo / "outputs" / "reports" / "v1-p4" / "raw" / "source.py"
    destination.parent.mkdir(parents=True)
    (repo / "source.py").rename(destination)
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "rename source into evidence",
    )

    result = VERIFIER.check_git_currency(_git_manifest(repo, recorded_sha))

    assert result["ok"] is False, result
    assert result["detail"]["disallowed_paths"] == ["source.py"]


def test_qualification_manifest_has_all_required_scenarios(tmp_path):
    stale = tmp_path / "out" / "raw" / "old-scenario" / "stale.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    manifest = run_qualification(tmp_path / "out", repo=REPO_ROOT)
    names = {row["name"] for row in manifest["scenarios"]}
    assert names == REQUIRED_SCENARIOS
    assert manifest["git"]["sha"]
    assert not stale.exists()


@pytest.fixture(scope="module")
def qualified(tmp_path_factory):
    """Run the real qualification once and share it across the assertions
    below (each run drives the retained CLI scenarios in disposable homes)."""
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


def test_claims_grounded_ignores_metadata_refs_and_aliases(tmp_path):
    """Manifest and verifier result files are metadata, never grounding
    evidence, including a raw symlink alias to either file."""
    out_dir = tmp_path / "out"
    raw_dir = out_dir / "raw" / "fake_scenario"
    raw_dir.mkdir(parents=True)
    metadata_model = "metadata-only-model"
    for filename in ("qualification-manifest.json", "independent-verifier.json"):
        (out_dir / filename).write_text(json.dumps({"model": metadata_model}), encoding="utf-8")
    refs = ["qualification-manifest.json", "independent-verifier.json"]
    alias = raw_dir / "metadata-alias.json"
    try:
        alias.symlink_to(out_dir / "qualification-manifest.json")
    except OSError:
        alias = None
    if alias is not None:
        refs.append(str(alias.relative_to(out_dir).as_posix()))
    scenario = {
        "name": "fake_scenario",
        "evidence_refs": refs,
        "commands": [],
        "metrics": {"model": metadata_model},
    }
    ok, detail = claims_grounded(scenario, out_dir)
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
        json.dumps([{"kind": "session_compact", "model": "claude-real-model"}]),
        encoding="utf-8",
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


def test_check_privacy_absence_scans_nested_command_json_fields(tmp_path):
    """Command captures are structurally checked, not only searched for
    marker strings, including nested lists and dictionaries."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "security_boundary"
    scen_dir.mkdir(parents=True)
    stdout_path = scen_dir / "01-command.stdout"
    stderr_path = scen_dir / "01-command.stderr"
    stdout_path.write_text(
        json.dumps({"result": [{"payload": {"tool-input": {"value": "secret"}}}]}),
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")
    stdout_ref = str(stdout_path.relative_to(out_dir).as_posix())
    stderr_ref = str(stderr_path.relative_to(out_dir).as_posix())
    manifest = {
        "home": str(tmp_path / "nonexistent-home"),
        "setup_commands": [],
        "scenarios": [
            {
                "name": "security_boundary",
                "commands": [
                    {
                        "argv": ["python", "safe-command"],
                        "stdout_ref": stdout_ref,
                        "stderr_ref": stderr_ref,
                    }
                ],
                "evidence_refs": [],
            }
        ],
    }
    result = check_privacy_absence(manifest, out_dir)
    assert result["ok"] is False
    assert any(
        stdout_ref in offender and "payload" in offender
        for offender in result["detail"]["offenders"]
    )


def test_check_privacy_absence_allows_action_cache_content(tmp_path):
    """Action-cache CLI output intentionally exposes a `content` field."""
    out_dir = tmp_path / "out"
    scen_dir = out_dir / "raw" / "cache_sensitive"
    scen_dir.mkdir(parents=True)
    stdout_path = scen_dir / "01-search.stdout"
    stderr_path = scen_dir / "01-search.stderr"
    stdout_path.write_text(json.dumps({"hit": True, "content": "cached result"}), encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    stdout_ref = str(stdout_path.relative_to(out_dir).as_posix())
    stderr_ref = str(stderr_path.relative_to(out_dir).as_posix())
    manifest = {
        "home": str(tmp_path / "nonexistent-home"),
        "setup_commands": [],
        "scenarios": [
            {
                "name": "cache_sensitive",
                "commands": [
                    {
                        "argv": ["python", "-m", "second_brain.cli", "action-cache", "search"],
                        "stdout_ref": stdout_ref,
                        "stderr_ref": stderr_ref,
                    }
                ],
                "evidence_refs": [],
            }
        ],
    }
    result = check_privacy_absence(manifest, out_dir)
    assert result["ok"] is True, result


def test_artifact_hash_integrity_requires_both_command_capture_refs(tmp_path):
    """A command capture without either stdout or stderr ref fails closed."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = check_artifact_hash_integrity(
        {"setup_commands": [{"stdout_ref": None, "stderr_ref": None}], "scenarios": []},
        out_dir,
    )
    assert result["ok"] is False
    assert any("stdout_ref" in item for item in result["detail"]["unhashed"])
    assert any("stderr_ref" in item for item in result["detail"]["unhashed"])


def test_read_json_ref_rejects_traversal_absolute_and_outside_symlink(tmp_path):
    """Verifier JSON reads must reject refs before opening files."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "inside.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text('{"unsafe": true}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_json_ref(out_dir, "../outside.json")
    with pytest.raises(ValueError):
        read_json_ref(out_dir, str(outside))
    link = out_dir / "outside-link.json"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    with pytest.raises(ValueError):
        read_json_ref(out_dir, "outside-link.json")


def test_runner_evidence_path_rejects_unsafe_refs(tmp_path):
    """Runner hashing must not follow absolute/traversal/outside refs."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("outside", encoding="utf-8")
    assert confined_evidence_path(out_dir, "../outside.json") is None
    assert confined_evidence_path(out_dir, str(outside)) is None
    link = out_dir / "link.json"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    assert confined_evidence_path(out_dir, "link.json") is None


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
    assert any(
        ref in offender and "PROMPT" in offender for offender in result["detail"]["offenders"]
    )


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


def test_v2_export_writes_strict_artifact_and_classified_raw_wrapper(brain_home):
    from datetime import UTC, datetime, timedelta

    identity = RUNNER.qualification_identity(brain_home)
    identity["captured_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    capture = brain_home / "capture.stdout"
    capture.write_bytes(b"selected test output\n")
    capture_ref = {
        "path": "capture.stdout",
        "sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
        "type": "stdout",
    }
    result = RUNNER.export_v2_observation(
        brain_home,
        brain_home / "outputs" / "reports" / "v2" / "v2-a",
        phase="v2-a",
        requirement="trusted_retrieval_freshness",
        evidence_type="test",
        feature="focused-tests",
        observed_data={
            "execution": "pytest",
            "case_outcomes": [{"outcome": "passed", "note": "λ 日本語"}],
        },
        gate_observations={
            "v1_safe_defaults_unchanged": {"selected_cases_passed": True},
        },
        identity=identity,
        producer=REPO_ROOT / "scripts" / "verify_v1_p4_qualification.py",
        raw_refs=[capture_ref],
    )

    strict = RUNNER._strict_verifier_module()
    gate_hash = strict._authority_gate_hashes()[0][("v2-a", "trusted_retrieval_freshness")]
    arguments = {
        "key": ("v2-a", "trusted_retrieval_freshness"),
        "source_commit": identity["source_commit"],
        "source_tree_sha256": identity["source_tree_sha256"],
        "config_sha256": identity["config_sha256"],
        "gate_sha256": gate_hash,
        "latest_observed_at": datetime.now(UTC),
    }
    errors, coverage, artifact = strict._validate_evidence_artifact(brain_home, result, **arguments)
    assert errors == []
    assert coverage == {"v1_safe_defaults_unchanged"}
    assert datetime.fromisoformat(artifact["observed_at"]) > datetime.fromisoformat(
        identity["captured_at"]
    )
    assert capture.read_bytes() == b"selected test output\n"
    raw_ref = artifact["provenance"]["raw_evidence_refs"][0]
    raw_path = brain_home / raw_ref["path"]
    raw_path.write_text('{"observed_data":{"tampered":true}}', encoding="utf-8")
    errors, _, _ = strict._validate_evidence_artifact(brain_home, result, **arguments)
    assert errors


def test_v2_export_refuses_overwrite_and_non_test_gate(brain_home):
    identity = RUNNER.qualification_identity(brain_home)
    kwargs = {
        "phase": "v2-a",
        "requirement": "trusted_retrieval_freshness",
        "evidence_type": "test",
        "feature": "focused-tests",
        "observed_data": {"execution": "pytest"},
        "gate_observations": {"v1_safe_defaults_unchanged": {"passed": True}},
        "identity": identity,
        "producer": REPO_ROOT / "scripts" / "verify_v1_p4_qualification.py",
    }
    out_dir = brain_home / "outputs" / "reports" / "v2" / "v2-a"
    RUNNER.export_v2_observation(brain_home, out_dir, **kwargs)
    with pytest.raises(FileExistsError):
        RUNNER.export_v2_observation(brain_home, out_dir, **kwargs)

    with pytest.raises(ValueError):
        RUNNER.export_v2_observation(
            brain_home,
            brain_home / "outputs" / "reports" / "v2" / "bad",
            **{
                **kwargs,
                "phase": "v2-b",
                "requirement": "low_friction_io",
                "gate_observations": {"real_supported_harness_paths": {"passed": True}},
            },
        )


def test_junit_matching_real_parameterized_outcomes_and_missing(tmp_path, monkeypatch):
    """A real pytest JUnit report keeps parameter outcomes and class scope exact."""
    test_root = tmp_path / "tests"
    test_root.mkdir()
    (test_root / "test_parameters.py").write_text(
        """
import pytest
@pytest.mark.parametrize("value", ["pass", "fail", "skip"])
def test_values(value):
    if value == "skip":
        pytest.skip("intentional")
    assert value != "fail"


@pytest.mark.parametrize("value", ["one", "two"])
def test_all_pass(value):
    assert value in {"one", "two"}


class TestFirst:
    def test_same(self):
        assert True


class TestSecond:
    def test_same(self):
        assert False
""",
        encoding="utf-8",
    )
    junit = tmp_path / "pytest.junit.xml"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PYTHON") and key.upper() != "PYTEST_ADDOPTS"
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml",
            str(junit),
            "-o",
            "junit_family=xunit1",
            "tests/test_parameters.py",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    monkeypatch.setattr(VERIFIER, "REPO_ROOT", tmp_path)
    cases = VERIFIER._parse_junit_cases(junit)
    assert VERIFIER._junit_outcome("tests/test_parameters.py::test_all_pass", cases)[0] == "passed"

    outcome, matches = VERIFIER._junit_outcome("tests/test_parameters.py::test_values", cases)
    assert outcome == "failed"
    assert {case["name"] for case in matches} == {
        "test_values[pass]",
        "test_values[fail]",
        "test_values[skip]",
    }
    assert (
        VERIFIER._junit_outcome("tests/test_parameters.py::test_values[pass]", cases)[0] == "passed"
    )
    assert (
        VERIFIER._junit_outcome("tests/test_parameters.py::test_values[fail]", cases)[0] == "failed"
    )
    assert (
        VERIFIER._junit_outcome("tests/test_parameters.py::test_values[skip]", cases)[0]
        == "skipped"
    )
    assert VERIFIER._junit_outcome("tests/test_parameters.py::test_missing", cases)[0] == "missing"
    assert (
        VERIFIER._junit_outcome("tests/test_parameters.py::TestFirst::test_same", cases)[0]
        == "passed"
    )
    assert (
        VERIFIER._junit_outcome("tests/test_parameters.py::TestSecond::test_same", cases)[0]
        == "failed"
    )


def test_v2_structure_ownership_uses_ast_and_entrypoint_metadata():
    cli = VERIFIER._cli_ownership()
    assert cli["path"] == "src/second_brain/cli.py"
    assert cli["entrypoint"] == "second_brain.cli:main"
    assert cli["v2_parser_owned"] is True
    assert cli["v2_dispatch_owned"] is True
    assert cli["competing_modules"] == []
    assert cli["v3_cli"]["entrypoint"] == "brain=second_brain.kb.cli:main"
    assert "src/second_brain/kb/cli.py" in cli["v3_cli"]["modules"]
    assert all(path.startswith("src/second_brain/kb/") for path in cli["v3_cli"]["modules"])
    assert VERIFIER._production_v2_definitions() == []
