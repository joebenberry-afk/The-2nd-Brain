"""Fail-closed v2 qualification and production-promotion trust-boundary tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from second_brain import contracts, credit, db, promotion
from second_brain.errors import BrainError

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load_script("verify_qualification.py")
self_improvement = _load_script("run_self_improvement_proof.py")


def _file_ref(home: Path, path: Path, evidence_type: str = "test") -> dict[str, str]:
    return {
        "path": path.relative_to(home).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "type": evidence_type,
    }


def _seed_complete_qualification(
    home: Path,
    *,
    classification: str = "fixture",
    qualification_eligible: bool = False,
    observed_at: str | None = None,
) -> Path:
    now = observed_at or datetime.now(UTC).isoformat()
    source_commit = verifier._git_head()
    source_tree_sha256 = verifier._source_tree_fingerprint()
    config_sha256 = verifier._config_fingerprint(home)
    gate_hashes, gate_errors = verifier._authority_gate_hashes()
    assert source_commit and source_tree_sha256 and config_sha256 and not gate_errors

    evidence_dir = home / "qualification" / "evidence"
    evidence_dir.mkdir(parents=True)
    host_path = evidence_dir / "host.json"
    host_path.write_text(
        contracts.canonical_json(
            {
                "schema_version": verifier.EVIDENCE_SCHEMA_VERSION,
                "classification": classification,
                "qualification_eligible": qualification_eligible,
                "evidence_type": "host",
                "name": "fixture-host",
                "build_id": "fixture-build-1",
                "source_commit": source_commit,
                "source_tree_sha256": source_tree_sha256,
                "config_sha256": config_sha256,
                "observed_at": now,
            }
        ),
        encoding="utf-8",
    )

    type_preference = (
        "host",
        "economics",
        "recovery",
        "security",
        "integration",
        "verification",
        "test",
    )
    manifest_rows = []
    conn = db.connect(db.db_path(home))
    try:
        for index, key in enumerate(verifier.EXPECTED_REQUIREMENTS):
            phase, requirement = key
            coverage_by_type: dict[str, list[str]] = {}
            for coverage_id, allowed_types in verifier.REQUIRED_GATE_COVERAGE[key].items():
                evidence_type = next(
                    candidate for candidate in type_preference if candidate in allowed_types
                )
                coverage_by_type.setdefault(evidence_type, []).append(coverage_id)

            refs = []
            for evidence_type, coverage in coverage_by_type.items():
                observed_data = {
                    "fixture": True,
                    "phase": phase,
                    "evidence_type": evidence_type,
                }
                raw_artifact = evidence_dir / f"{index:02d}-{requirement}-{evidence_type}-raw.json"
                raw_artifact.write_text(
                    contracts.canonical_json(
                        {
                            "classification": classification,
                            "observed_data": observed_data,
                        }
                    ),
                    encoding="utf-8",
                )
                producer = sorted(verifier._CANONICAL_EVIDENCE_PRODUCERS[evidence_type])[0]
                producer_path = REPO_ROOT / producer
                artifact = evidence_dir / f"{index:02d}-{requirement}-{evidence_type}.json"
                artifact.write_text(
                    contracts.canonical_json(
                        {
                            "schema_version": verifier.EVIDENCE_SCHEMA_VERSION,
                            "classification": classification,
                            "qualification_eligible": qualification_eligible,
                            "phase": phase,
                            "requirement": requirement,
                            "feature": "validator-fixture",
                            "target_ref": "policy:validator-fixture",
                            "source_commit": source_commit,
                            "source_tree_sha256": source_tree_sha256,
                            "config_sha256": config_sha256,
                            "gate_sha256": gate_hashes[key],
                            "evidence_type": evidence_type,
                            "coverage": coverage,
                            "gate_observations": {
                                item: {"result": "passed", "fixture": True} for item in coverage
                            },
                            "observed_data": observed_data,
                            "observed_at": now,
                            "provenance": {
                                "producer": producer,
                                "producer_sha256": hashlib.sha256(
                                    producer_path.read_bytes()
                                ).hexdigest(),
                                "observed_data_sha256": verifier._canonical_hash(observed_data),
                                "raw_evidence_refs": [_file_ref(home, raw_artifact, "raw")],
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                refs.append(_file_ref(home, artifact, evidence_type))

            evidence = {
                "schema_version": verifier.EVIDENCE_SCHEMA_VERSION,
                "classification": classification,
                "qualification_eligible": qualification_eligible,
                "feature": "validator-fixture",
                "source_commit": source_commit,
                "source_tree_sha256": source_tree_sha256,
                "config_sha256": config_sha256,
                "observed_at": now,
                "evidence_refs": refs,
            }
            artifact_hash = verifier._canonical_hash(evidence)
            conn.execute(
                """INSERT INTO v2_qualification(
                    qualification_id, phase, requirement, status, evidence_json,
                    source_commit, artifact_hash, created_at
                ) VALUES (?, ?, ?, 'PROVEN', ?, ?, ?, ?)""",
                (
                    f"qual-{index:02d}",
                    phase,
                    requirement,
                    contracts.canonical_json(evidence),
                    source_commit,
                    artifact_hash,
                    now,
                ),
            )
            manifest_rows.append(
                {
                    "phase": phase,
                    "requirement": requirement,
                    "required": True,
                    "artifact_hash": artifact_hash,
                    "gate_sha256": gate_hashes[key],
                }
            )
        conn.commit()
    finally:
        conn.close()

    authority = REPO_ROOT / verifier.QUALIFICATION_AUTHORITY
    manifest = {
        "schema_version": verifier.MANIFEST_SCHEMA_VERSION,
        "classification": classification,
        "authority": verifier.QUALIFICATION_AUTHORITY,
        "authority_sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
        "generated_at": now,
        "source_commit": source_commit,
        "source_tree_sha256": source_tree_sha256,
        "build_identity": verifier._current_build_identity(),
        "config_sha256": config_sha256,
        "host_identity": {
            "name": "fixture-host",
            "build_id": "fixture-build-1",
            "evidence": _file_ref(home, host_path, "host"),
        },
        "requirements": manifest_rows,
    }
    path = home / "qualification" / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _ledger_check(home: Path, manifest: Path) -> dict:
    return next(
        row
        for row in verifier.verify_all(home, manifest)["checks"]
        if row["check"] == "qualification_ledger"
    )


def _rewrite_evidence(home: Path, manifest: Path, requirement: str, mutate) -> None:
    conn = db.connect(db.db_path(home))
    try:
        row = conn.execute(
            "SELECT qualification_id, evidence_json FROM v2_qualification WHERE requirement = ?",
            (requirement,),
        ).fetchone()
        evidence = json.loads(row["evidence_json"])
        mutate(evidence)
        artifact_hash = verifier._canonical_hash(evidence)
        conn.execute(
            "UPDATE v2_qualification SET evidence_json = ?, artifact_hash = ? "
            "WHERE qualification_id = ?",
            (contracts.canonical_json(evidence), artifact_hash, row["qualification_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for entry in data["requirements"]:
        if entry["requirement"] == requirement:
            entry["artifact_hash"] = artifact_hash
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _rewrite_artifact(
    home: Path,
    manifest: Path,
    requirement: str,
    mutate,
    *,
    evidence_type: str | None = None,
) -> None:
    def rewrite(evidence: dict) -> None:
        ref = next(
            item
            for item in evidence["evidence_refs"]
            if evidence_type is None or item["type"] == evidence_type
        )
        path = home / ref["path"]
        artifact = json.loads(path.read_text(encoding="utf-8"))
        mutate(artifact)
        path.write_text(contracts.canonical_json(artifact), encoding="utf-8")
        ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    _rewrite_evidence(home, manifest, requirement, rewrite)


def test_complete_synthetic_fixture_proves_validator_logic_but_holds_release(
    brain_home: Path,
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    result = verifier.verify_all(brain_home, manifest)
    ledger = next(row for row in result["checks"] if row["check"] == "qualification_ledger")
    assert result["ok"] is False
    assert result["qualification_status"] == "HOLD"
    assert result["validated_evidence_bindings"] == []
    assert ledger["details"]["proven_count"] == len(verifier.EXPECTED_REQUIREMENTS)
    assert ledger["details"]["coverage_complete_count"] == len(verifier.EXPECTED_REQUIREMENTS)
    assert result["scope"] == [
        {"phase": phase, "requirement": requirement}
        for phase, requirement in verifier.EXPECTED_REQUIREMENTS
    ]


@pytest.mark.parametrize("remaining", [0, 1])
def test_empty_or_partial_ledger_fails_closed(brain_home: Path, remaining: int) -> None:
    manifest = _seed_complete_qualification(brain_home)
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "DELETE FROM v2_qualification WHERE qualification_id NOT IN "
            "(SELECT qualification_id FROM v2_qualification ORDER BY qualification_id LIMIT ?)",
            (remaining,),
        )
        conn.commit()
    finally:
        conn.close()
    result = _ledger_check(brain_home, manifest)
    assert result["ok"] is False
    assert any("missing canonical" in error for error in result["details"]["errors"])


def test_unknown_requirement_fails_closed(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    conn = db.connect(db.db_path(brain_home))
    try:
        source = verifier._git_head()
        now = datetime.now(UTC).isoformat()
        evidence = {
            "classification": "observed",
            "qualification_eligible": True,
            "observed_at": now,
            "evidence_refs": [],
        }
        conn.execute(
            "INSERT INTO v2_qualification VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "qual-unknown",
                "unknown",
                "invented_requirement",
                "PROVEN",
                contracts.canonical_json(evidence),
                source,
                verifier._canonical_hash(evidence),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("unknown qualification" in error for error in errors)


@pytest.mark.parametrize(
    "statuses, label",
    [(["PROVEN", "PROVEN"], "ambiguous"), (["PROVEN", "FAILED"], "contradictory")],
)
def test_duplicate_or_contradictory_records_fail_closed(
    brain_home: Path, statuses: list[str], label: str
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    phase, requirement = verifier.EXPECTED_REQUIREMENTS[0]
    conn = db.connect(db.db_path(brain_home))
    try:
        original = conn.execute(
            "SELECT * FROM v2_qualification WHERE phase = ? AND requirement = ?",
            (phase, requirement),
        ).fetchone()
        conn.execute(
            "UPDATE v2_qualification SET status = ? WHERE qualification_id = ?",
            (statuses[0], original["qualification_id"]),
        )
        conn.execute(
            "INSERT INTO v2_qualification VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "qual-duplicate",
                phase,
                requirement,
                statuses[1],
                original["evidence_json"],
                original["source_commit"],
                original["artifact_hash"],
                original["created_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any(label in error for error in errors)


def test_failed_requirement_fails_closed(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "UPDATE v2_qualification SET status = 'FAILED' WHERE qualification_id = 'qual-00'"
        )
        conn.commit()
    finally:
        conn.close()
    assert any(
        "failed/unresolved" in error
        for error in _ledger_check(brain_home, manifest)["details"]["errors"]
    )


@pytest.mark.parametrize(
    "field",
    ["source_commit", "source_tree_sha256", "build_identity", "config_sha256"],
)
def test_wrong_source_build_or_config_identity_fails(brain_home: Path, field: str) -> None:
    manifest = _seed_complete_qualification(brain_home)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data[field] = "wrong" if field != "build_identity" else {"package_version": "wrong"}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    result = verifier.verify_all(brain_home, manifest)
    manifest_check = next(
        row for row in result["checks"] if row["check"] == "qualification_manifest"
    )
    assert manifest_check["ok"] is False
    assert any(field in error for error in manifest_check["details"]["errors"])


def test_manifest_cannot_mark_canonical_requirement_unsupported(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["requirements"][0]["required"] = False
    manifest.write_text(json.dumps(data), encoding="utf-8")
    result = verifier.verify_all(brain_home, manifest)
    manifest_check = next(
        row for row in result["checks"] if row["check"] == "qualification_manifest"
    )
    assert manifest_check["ok"] is False
    assert any("unsupported/not required" in error for error in manifest_check["details"]["errors"])


def test_host_identity_must_bind_current_source_and_config(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["host_identity"]["build_id"] = "wrong-build"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    result = verifier.verify_all(brain_home, manifest)
    manifest_check = next(
        row for row in result["checks"] if row["check"] == "qualification_manifest"
    )
    assert manifest_check["ok"] is False
    assert any(
        "host evidence contradicts" in error for error in manifest_check["details"]["errors"]
    )


def test_missing_unresolvable_and_tampered_evidence_fail(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirements = [item[1] for item in verifier.EXPECTED_REQUIREMENTS[:3]]

    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        evidence_rows = {
            row["requirement"]: json.loads(row["evidence_json"])
            for row in conn.execute(
                "SELECT requirement, evidence_json FROM v2_qualification "
                "WHERE requirement IN (?, ?, ?)",
                tuple(requirements),
            ).fetchall()
        }
    finally:
        conn.close()
    (brain_home / evidence_rows[requirements[0]]["evidence_refs"][0]["path"]).unlink()
    _rewrite_evidence(
        brain_home,
        manifest,
        requirements[1],
        lambda evidence: evidence["evidence_refs"][0].update({"path": "../escape.json"}),
    )
    third = brain_home / evidence_rows[requirements[2]]["evidence_refs"][0]["path"]
    third.write_text("tampered", encoding="utf-8")

    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("missing evidence" in error for error in errors)
    assert any("unresolvable evidence" in error for error in errors)
    assert any("tampered evidence" in error for error in errors)


def test_evidence_age_alone_does_not_invent_expiry(brain_home: Path) -> None:
    old = (datetime.now(UTC) - timedelta(days=3650)).isoformat()
    manifest = _seed_complete_qualification(brain_home, observed_at=old)
    result = verifier.verify_all(brain_home, manifest)
    errors = [
        error
        for check_result in result["checks"]
        for error in check_result["details"].get("errors", [])
    ]
    assert result["qualification_status"] == "HOLD"
    assert not any("stale" in error or "chronology" in error for error in errors)


def test_unsupported_required_evidence_type_fails(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[1][1]
    _rewrite_evidence(
        brain_home,
        manifest,
        requirement,
        lambda evidence: evidence["evidence_refs"][0].update({"type": "self_assertion"}),
    )
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("unsupported evidence type" in error for error in errors)


@pytest.mark.parametrize(
    "classification",
    ["simulation", "simulated", "fixture", "mechanism", "unknown", " fixture "],
)
def test_nonproduction_classification_is_ineligible_even_with_true_boolean(
    brain_home: Path, classification: str
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[-1][1]
    _rewrite_evidence(
        brain_home,
        manifest,
        requirement,
        lambda evidence: evidence.update(
            {"classification": classification, "qualification_eligible": True}
        ),
    )
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("ineligible evidence classification" in error for error in errors)


@pytest.mark.parametrize(
    "artifact_classification",
    ["simulation", "simulated", "fixture", "mechanism", "unknown", " fixture "],
)
def test_wrapper_cannot_relabel_nonproduction_artifact_as_observed(
    brain_home: Path, artifact_classification: str
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[0][1]
    _rewrite_evidence(
        brain_home,
        manifest,
        requirement,
        lambda evidence: evidence.update(
            {"classification": "observed", "qualification_eligible": True}
        ),
    )
    _rewrite_artifact(
        brain_home,
        manifest,
        requirement,
        lambda artifact: artifact.update(
            {
                "classification": artifact_classification,
                "qualification_eligible": True,
            }
        ),
    )
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("ineligible evidence classification" in error for error in errors)


def test_simulated_producer_cannot_self_author_observed_gate_result(
    brain_home: Path,
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[0][1]
    _rewrite_evidence(
        brain_home,
        manifest,
        requirement,
        lambda evidence: evidence.update(
            {"classification": "observed", "qualification_eligible": True}
        ),
    )

    def relabel_artifact(artifact: dict) -> None:
        observed_data = {
            "phase": artifact["phase"],
            "evidence_type": artifact["evidence_type"],
        }
        raw_ref = artifact["provenance"]["raw_evidence_refs"][0]
        raw_path = brain_home / raw_ref["path"]
        raw_path.write_text(
            contracts.canonical_json(
                {"classification": "observed", "observed_data": observed_data}
            ),
            encoding="utf-8",
        )
        raw_ref["sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        producer = REPO_ROOT / "scripts" / "run_self_improvement_proof.py"
        artifact.update(
            {
                "classification": "observed",
                "qualification_eligible": True,
                "observed_data": observed_data,
            }
        )
        artifact["provenance"].update(
            {
                "producer": "scripts/run_self_improvement_proof.py",
                "producer_sha256": hashlib.sha256(producer.read_bytes()).hexdigest(),
                "observed_data_sha256": verifier._canonical_hash(observed_data),
            }
        )

    _rewrite_artifact(brain_home, manifest, requirement, relabel_artifact)
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("producer" in error and "not authoritative" in error for error in errors)


def test_arbitrary_json_cannot_be_passed_as_observed_evidence(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[0][1]
    _rewrite_artifact(
        brain_home,
        manifest,
        requirement,
        lambda artifact: (
            artifact.clear()
            or artifact.update(
                {
                    "classification": "observed",
                    "qualification_eligible": True,
                    "result": "passed",
                }
            )
        ),
    )
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("unsupported evidence schema_version" in error for error in errors)
    assert any("wrong canonical requirement" in error for error in errors)


@pytest.mark.parametrize("location", ["manifest", "envelope", "artifact"])
def test_unknown_schema_versions_fail_closed(brain_home: Path, location: str) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[0][1]
    if location == "manifest":
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["schema_version"] = 999
        manifest.write_text(json.dumps(data), encoding="utf-8")
        result = verifier.verify_all(brain_home, manifest)
        errors = next(
            item["details"]["errors"]
            for item in result["checks"]
            if item["check"] == "qualification_manifest"
        )
    elif location == "envelope":
        _rewrite_evidence(
            brain_home,
            manifest,
            requirement,
            lambda evidence: evidence.update({"schema_version": 999}),
        )
        errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    else:
        _rewrite_artifact(
            brain_home,
            manifest,
            requirement,
            lambda artifact: artifact.update({"schema_version": 999}),
        )
        errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("unsupported" in error and "schema_version" in error for error in errors)


def test_missing_authoritative_subgate_coverage_fails(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[9][1]
    missing = "no_mock_host_substitution"

    def remove_subgate(artifact: dict) -> None:
        artifact["coverage"].remove(missing)
        artifact["gate_observations"].pop(missing)

    _rewrite_artifact(
        brain_home,
        manifest,
        requirement,
        remove_subgate,
        evidence_type="host",
    )
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any(
        "missing authoritative Gate coverage" in error and missing in error for error in errors
    )


@pytest.mark.parametrize(
    ("requirement_index", "real_type"),
    [(2, "host"), (9, "host"), (11, "economics")],
)
def test_unit_evidence_cannot_replace_real_boundary_proof(
    brain_home: Path, requirement_index: int, real_type: str
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[requirement_index][1]
    _rewrite_artifact(
        brain_home,
        manifest,
        requirement,
        lambda artifact: artifact.update({"evidence_type": "test"}),
        evidence_type=real_type,
    )
    _rewrite_evidence(
        brain_home,
        manifest,
        requirement,
        lambda evidence: next(
            ref for ref in evidence["evidence_refs"] if ref["type"] == real_type
        ).update({"type": "test"}),
    )
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("cannot be proven by 'test' evidence" in error for error in errors)


def test_artifact_source_tree_binding_must_be_current(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    requirement = verifier.EXPECTED_REQUIREMENTS[0][1]
    _rewrite_artifact(
        brain_home,
        manifest,
        requirement,
        lambda artifact: artifact.update({"source_tree_sha256": "0" * 64}),
    )
    errors = _ledger_check(brain_home, manifest)["details"]["errors"]
    assert any("artifact source_tree_sha256 is not current" in error for error in errors)


@pytest.mark.parametrize("malformed", ["{", "[]", "null"])
def test_malformed_evidence_payload_holds_instead_of_crashing(
    brain_home: Path, malformed: str
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "UPDATE v2_qualification SET evidence_json = ? WHERE qualification_id = 'qual-00'",
            (malformed,),
        )
        conn.commit()
    finally:
        conn.close()
    result = verifier.verify_all(brain_home, manifest)
    assert result["qualification_status"] == "HOLD"
    assert result["ok"] is False


def test_malformed_manifest_shape_holds_instead_of_crashing(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["requirements"] = {"not": "a list"}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    result = verifier.verify_all(brain_home, manifest)
    assert result["qualification_status"] == "HOLD"
    assert any("requirements must be a list" in item for item in result["remaining_prerequisites"])


def test_unknown_applied_migration_version_fails_closed(brain_home: Path) -> None:
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
            (999, datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    result = verifier.check_schema_migrations(brain_home)
    assert result["ok"] is False
    assert result["details"]["unexpected"] == [999]


@pytest.mark.parametrize("kind", ["missing", "malformed", "non-object"])
def test_nonexistent_or_malformed_manifest_fails(brain_home: Path, kind: str) -> None:
    path = brain_home / "qualification" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "malformed":
        path.write_text("{not-json", encoding="utf-8")
    elif kind == "non-object":
        path.write_text("[]", encoding="utf-8")
    result = verifier.verify_all(brain_home, path)
    assert result["ok"] is False
    manifest_check = next(
        row for row in result["checks"] if row["check"] == "qualification_manifest"
    )
    assert manifest_check["ok"] is False


def test_cli_uses_supplied_manifest(brain_home: Path) -> None:
    _seed_complete_qualification(brain_home)
    wrong = brain_home / "qualification" / "wrong.json"
    wrong.write_text("{}", encoding="utf-8")
    assert verifier.main(["--home", str(brain_home), "--manifest", str(wrong), "--json"]) == 1


def test_complete_fixture_and_real_verifier_cannot_authorize_active(
    brain_home: Path,
) -> None:
    _seed_complete_qualification(brain_home)
    feature = "qualified-feature"
    observed_data = {
        "tokens_delta": -20.0,
        "effect": 10.0,
        "design": "paired",
        "verdict": "POSITIVE",
    }
    evidence = brain_home / "qualification" / "promotion-credit.json"
    evidence.write_text(
        contracts.canonical_json(
            {
                "classification": "observed",
                "qualification_eligible": True,
                "feature": feature,
                "target_ref": f"policy:{feature}",
                "source_commit": verifier._git_head(),
                "source_tree_sha256": verifier._source_tree_fingerprint(),
                "config_sha256": verifier._config_fingerprint(brain_home),
                "observed_data": observed_data,
            }
        ),
        encoding="utf-8",
    )
    intervention = credit.record_intervention(
        brain_home,
        "routing_policy",
        f"policy:{feature}",
        {
            "metric": "tokens_delta",
            "expected_delta": -10.0,
            "direction": "decrease",
            "expected_range": [-11.0, -9.0],
            "horizon": 1,
            "confidence": 0.95,
            "evaluator": "test-evaluator",
        },
        "qualification/evidence/00-baseline_identity_and_schema-integration.json",
    )
    observation = credit.record_observation(
        brain_home,
        intervention["intervention_id"],
        observed_data,
        "qualification/promotion-credit.json",
        "benchmark",
    )
    for stage in ("SHADOW", "ADVISORY", "CANARY"):
        promotion.transition_rollout_stage(brain_home, feature, stage, reason="qualified path")
    with pytest.raises(BrainError, match="Independent qualification verifier"):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="fixture cannot authorize production",
            credit_observation_id=observation["observation_id"],
            qualification_manifest="qualification/manifest.json",
        )
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"


def test_passing_report_without_exact_credit_binding_is_rejected(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    feature = "missing-binding"
    evidence = {
        "path": "qualification/promotion-credit.json",
        "sha256": "1" * 64,
        "feature": feature,
        "source_commit": verifier._git_head(),
        "source_tree_sha256": verifier._source_tree_fingerprint(),
        "config_sha256": verifier._config_fingerprint(brain_home),
    }
    verifier_path = REPO_ROOT / "scripts" / "verify_qualification.py"
    report = {
        "ok": True,
        "verifier": "scripts/verify_qualification.py",
        "verifier_sha256": hashlib.sha256(verifier_path.read_bytes()).hexdigest(),
        "manifest_path": str(manifest.resolve()),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "source_commit": evidence["source_commit"],
        "scope": [{"phase": "v2-i", "requirement": "governed_self_improvement_proof"}],
        "validated_evidence_bindings": [],
    }
    monkeypatch.setattr(
        promotion.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr=""),
    )
    with pytest.raises(BrainError, match="exact credit evidence binding"):
        promotion._run_independent_qualification(brain_home, manifest, evidence)


def test_caller_boole_cannot_bypass_production_promotion(brain_home: Path) -> None:
    feature = "no-bypass"
    legacy_args: dict[str, Any] = {"credit_class": "DIRECT", "verifier_passed": True}
    for stage in ("SHADOW", "ADVISORY", "CANARY"):
        promotion.transition_rollout_stage(brain_home, feature, stage, reason="mechanism")
    with pytest.raises(TypeError):
        promotion.transition_rollout_stage(
            brain_home,
            feature,
            "ACTIVE",
            reason="caller assertion",
            **legacy_args,
        )
    assert promotion.get_feature_stage(brain_home, feature) == "CANARY"


def test_mechanism_producer_never_qualifies_or_activates(brain_home: Path) -> None:
    scenario = self_improvement.run_scenario_a(brain_home)
    assert scenario["classification"] == "simulation"
    assert scenario["qualification_eligible"] is False
    assert scenario["production_activation_eligible"] is False
    assert scenario["evidence"]["final_stage"] == "CANARY"
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        count = conn.execute("SELECT COUNT(*) FROM v2_qualification").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def _candidate_fixture(home: Path) -> tuple[Path, Path, list[dict[str, Any]]]:
    """Export the ineligible fixture verbatim; never relabel it as release evidence."""
    manifest = _seed_complete_qualification(home)
    conn = db.connect(db.db_path(home))
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM v2_qualification")]
        conn.execute("DELETE FROM v2_qualification")
        conn.commit()
    finally:
        conn.close()
    records = manifest.with_name("records.json")
    records.write_text(json.dumps(rows), encoding="utf-8")
    return manifest, records, rows


def _qualification_rows(home: Path) -> list[dict[str, Any]]:
    conn = db.connect(db.db_path(home), readonly=True)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM v2_qualification")]
    finally:
        conn.close()


@pytest.mark.parametrize("kind", ["fixture", "partial", "forged", "stale", "malformed"])
def test_candidate_rejection_never_records(brain_home: Path, kind: str) -> None:
    manifest, records, rows = _candidate_fixture(brain_home)
    if kind == "partial":
        rows.pop()
    elif kind == "forged":
        rows[0]["artifact_hash"] = "0" * 64
    elif kind == "stale":
        rows[0]["source_commit"] = "0" * 40
    records.write_text("null" if kind == "malformed" else json.dumps(rows), encoding="utf-8")
    report = verifier.verify_all(brain_home, manifest, records)
    assert report["ok"] is False
    assert report["qualification_status"] == "HOLD"
    assert report["validated_evidence_bindings"] == []
    with pytest.raises(BrainError):
        promotion.record_qualification(brain_home, manifest, records)
    assert _qualification_rows(brain_home) == []


def test_candidate_records_must_be_contained(brain_home: Path, tmp_path: Path) -> None:
    manifest, _, rows = _candidate_fixture(brain_home)
    outside = tmp_path / "outside-records.json"
    outside.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(BrainError, match="contained"):
        promotion.record_qualification(brain_home, manifest, outside)
    with pytest.raises(ValueError):
        verifier.load_candidate_records(brain_home, outside)
    assert _qualification_rows(brain_home) == []


def _mock_candidate_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    manifest: Path,
    records: Path,
    *,
    after_report=None,
) -> None:
    """Isolate the transaction contract, NOT a valid observed evidence fixture."""
    calls = 0

    def run(command, **kwargs):
        nonlocal calls
        calls += 1
        assert command[-2:] == ["--records", str(records)]
        assert "PYTHONHOME" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        report = {
            "ok": True,
            "qualification_status": "READY_TO_RECORD",
            "verifier": "scripts/verify_qualification.py",
            "verifier_sha256": verifier._sha256_file(
                REPO_ROOT / "scripts" / "verify_qualification.py"
            ),
            "manifest_path": str(manifest),
            "manifest_sha256": verifier._sha256_file(manifest),
            "records_path": str(records),
            "records_sha256": verifier._sha256_file(records),
            "records_content_sha256": verifier._canonical_hash(json.loads(records.read_text())),
            "manifest_content_sha256": verifier._canonical_hash(json.loads(manifest.read_text())),
            "source_commit": json.loads(manifest.read_text())["source_commit"],
            "current_source_commit": source_commit,
            "source_tree_sha256": source_hash,
            "config_sha256": config_hash,
            "validated_evidence_bindings": [],
        }
        if after_report is not None and calls == 2:
            after_report()
        return SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr="")

    source_commit = verifier._git_head()
    source_hash = verifier._source_tree_fingerprint()
    config_hash = verifier._config_fingerprint(home)
    # subprocess is shared with build_identity; preserve real Git invocations.
    original_run = promotion.subprocess.run
    monkeypatch.setattr(
        promotion.subprocess,
        "run",
        lambda command, **kwargs: (
            run(command, **kwargs) if "--records" in command else original_run(command, **kwargs)
        ),
    )


def test_recording_transaction_is_idempotent_and_refuses_conflict(
    brain_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, records, rows = _candidate_fixture(brain_home)
    _mock_candidate_acceptance(monkeypatch, brain_home, manifest, records)
    assert promotion.record_qualification(brain_home, manifest, records)["inserted"] == len(rows)
    assert promotion.record_qualification(brain_home, manifest, records)["inserted"] == 0
    assert _qualification_rows(brain_home) == rows
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute(
            "UPDATE v2_qualification SET status = 'HELD' WHERE qualification_id = ?",
            (rows[0]["qualification_id"],),
        )
        conn.commit()
    finally:
        conn.close()
    before = _qualification_rows(brain_home)
    with pytest.raises(BrainError, match="Conflicting"):
        promotion.record_qualification(brain_home, manifest, records)
    assert _qualification_rows(brain_home) == before
    # Even a transaction-only acceptance mock never makes this fixture qualify.
    assert verifier.verify_all(brain_home, manifest)["qualification_status"] == "HOLD"


@pytest.mark.parametrize("failure", ["records_changed", "raw_changed", "insert_failed"])
def test_recording_rolls_back_whole_batch(
    brain_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    manifest, records, rows = _candidate_fixture(brain_home)
    mutate = None
    if failure == "records_changed":

        def change_records() -> None:
            records.write_text(records.read_text(encoding="utf-8") + " ", encoding="utf-8")

        mutate = change_records
    elif failure == "raw_changed":
        envelope = json.loads(rows[0]["evidence_json"])
        artifact_path = brain_home / envelope["evidence_refs"][0]["path"]
        artifact = json.loads(artifact_path.read_text())
        raw = brain_home / artifact["provenance"]["raw_evidence_refs"][0]["path"]

        def change_raw() -> None:
            raw.write_text(raw.read_text(encoding="utf-8") + " ", encoding="utf-8")

        mutate = change_raw
    else:
        conn = db.connect(db.db_path(brain_home))
        try:
            conn.execute(
                "CREATE TRIGGER reject_second_qualification BEFORE INSERT ON v2_qualification "
                "WHEN (SELECT COUNT(*) FROM v2_qualification) > 0 "
                "BEGIN SELECT RAISE(ABORT, 'contract insert failure'); END"
            )
            conn.commit()
        finally:
            conn.close()
    _mock_candidate_acceptance(
        monkeypatch,
        brain_home,
        manifest,
        records,
        after_report=mutate,
    )
    with pytest.raises(BrainError):
        promotion.record_qualification(brain_home, manifest, records)
    assert _qualification_rows(brain_home) == []


def test_candidate_success_label_cannot_authorize_active(
    brain_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report-mode contract only; mocked checks do not create release evidence."""
    manifest, records, _ = _candidate_fixture(brain_home)
    binding = {
        "path": "qualification/credit.json",
        "sha256": "1" * 64,
        "feature": "candidate-mode",
        "source_commit": verifier._git_head(),
        "source_tree_sha256": verifier._source_tree_fingerprint(),
        "config_sha256": verifier._config_fingerprint(brain_home),
    }
    monkeypatch.setattr(
        verifier,
        "check_manifest",
        lambda *args: (
            verifier.check("qualification_manifest", True, {}),
            json.loads(manifest.read_text()),
        ),
    )
    monkeypatch.setattr(
        verifier,
        "validate_qualification_rows",
        lambda *args: verifier.check(
            "qualification_ledger",
            True,
            {"validated_evidence_bindings": [binding], "records": json.loads(records.read_text())},
        ),
    )
    report = verifier.verify_all(brain_home, manifest, records)
    assert report["ok"] is True
    assert report["qualification_status"] == "READY_TO_RECORD"
    assert report["validated_evidence_bindings"] == []
    assert _qualification_rows(brain_home) == []
    # Even supplying an exact credit binding cannot turn candidate acceptance
    # into a normal-mode release authorization.
    report["validated_evidence_bindings"] = [binding]
    monkeypatch.setattr(
        promotion,
        "_qualification_process",
        lambda *args: (SimpleNamespace(returncode=0), report),
    )
    with pytest.raises(BrainError, match="exact credit evidence binding"):
        promotion._run_independent_qualification(brain_home, manifest, binding)


# ---------------------------------------------------------------------------
# Release-scope overlay (OMP-only successor contract, 2026-09-19)
# ---------------------------------------------------------------------------

_SCOPED_REQUIREMENT = ("control-plane", "universal_control_plane")
_RETIRED_CLAUSES = [
    "limited_to_rich_preserves_decisions",
    "limited_to_rich_preserves_evidence",
    "limited_to_rich_preserves_unresolved_work",
    "rich_to_limited_preserves_decisions",
    "rich_to_limited_preserves_evidence",
    "rich_to_limited_preserves_unresolved_work",
]


def _scope_overlay(path: Path, **overrides: Any) -> Path:
    overlay: dict[str, Any] = {
        "schema_version": verifier.RELEASE_SCOPE_SCHEMA_VERSION,
        "scope_id": "test-omp-only",
        "supersedes": "test-universal",
        "authority": verifier.QUALIFICATION_AUTHORITY,
        "authorized_by": "unit test",
        "change_record": "unit test",
        "retired_gates": {f"{_SCOPED_REQUIREMENT[0]}/{_SCOPED_REQUIREMENT[1]}": _RETIRED_CLAUSES},
    }
    overlay.update(overrides)
    path.write_text(json.dumps(overlay), encoding="utf-8")
    return path


def _strip_gate_coverage(home: Path, manifest: Path, clauses: list[str]) -> None:
    """Remove coverage of the named clauses from the scoped requirement's artifacts."""

    def rewrite(evidence: dict) -> None:
        retained_refs = []
        for ref in evidence["evidence_refs"]:
            path = home / ref["path"]
            artifact = json.loads(path.read_text(encoding="utf-8"))
            coverage = [item for item in artifact["coverage"] if item not in clauses]
            if not coverage:
                continue
            artifact["coverage"] = coverage
            for clause in clauses:
                artifact["gate_observations"].pop(clause, None)
            path.write_text(contracts.canonical_json(artifact), encoding="utf-8")
            ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            retained_refs.append(ref)
        evidence["evidence_refs"] = retained_refs

    _rewrite_evidence(home, manifest, _SCOPED_REQUIREMENT[1], rewrite)


def _ledger_with_scope(home: Path, manifest: Path, scope: Path | None = None) -> dict:
    return next(
        row
        for row in verifier.verify_all(home, manifest, None, scope)["checks"]
        if row["check"] == "qualification_ledger"
    )


def test_retired_clauses_are_required_without_scope_and_not_counted_with_scope(
    brain_home: Path,
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    _strip_gate_coverage(brain_home, manifest, _RETIRED_CLAUSES)

    universal = _ledger_with_scope(brain_home, manifest)
    assert (
        universal["details"]["coverage_complete_count"] == len(verifier.EXPECTED_REQUIREMENTS) - 1
    )
    assert any(
        "missing authoritative Gate coverage" in error for error in universal["details"]["errors"]
    )

    scope = _scope_overlay(brain_home / "scope.json")
    scoped = _ledger_with_scope(brain_home, manifest, scope)
    assert scoped["details"]["coverage_complete_count"] == len(verifier.EXPECTED_REQUIREMENTS)
    assert not any(
        "missing authoritative Gate coverage" in error for error in scoped["details"]["errors"]
    )
    assert scoped["details"]["retired_gate_count"] == len(_RETIRED_CLAUSES)
    assert scoped["details"]["retired_gates_counted_as_passed"] is False
    assert scoped["details"]["scoped_gate_count"] == 74 - len(_RETIRED_CLAUSES)
    assert scoped["details"]["scoped_gate_covered"] == 74 - len(_RETIRED_CLAUSES)


def test_missing_retained_clause_still_fails_under_scope(brain_home: Path) -> None:
    manifest = _seed_complete_qualification(brain_home)
    retained = ["adapter_owns_no_canonical_state"]
    _strip_gate_coverage(brain_home, manifest, [*_RETIRED_CLAUSES, *retained])
    scope = _scope_overlay(brain_home / "scope.json")
    scoped = _ledger_with_scope(brain_home, manifest, scope)
    assert scoped["details"]["coverage_complete_count"] == len(verifier.EXPECTED_REQUIREMENTS) - 1
    assert any(
        "missing authoritative Gate coverage" in error and retained[0] in error
        for error in scoped["details"]["errors"]
    )


def test_clause_coverage_of_retired_gates_cannot_substitute_for_retained_gate(
    brain_home: Path,
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    retained = ["false_capabilities_rejected"]
    _strip_gate_coverage(brain_home, manifest, retained)
    scope = _scope_overlay(brain_home / "scope.json")
    scoped = _ledger_with_scope(brain_home, manifest, scope)
    assert scoped["details"]["coverage_complete_count"] == len(verifier.EXPECTED_REQUIREMENTS) - 1
    assert scoped["details"]["scoped_gate_covered"] == 74 - len(_RETIRED_CLAUSES) - len(retained)
    assert any(
        "missing authoritative Gate coverage" in error and retained[0] in error
        for error in scoped["details"]["errors"]
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": 99},
        {"scope_id": ""},
        {"authority": "docs/other.md"},
        {"retired_gates": {}},
        {"retired_gates": {"unknown/requirement": ["clause"]}},
        {"retired_gates": {"control-plane/universal_control_plane": ["not_a_clause"]}},
        {"retired_gates": {"control-plane/universal_control_plane": [*_RETIRED_CLAUSES] * 2}},
        {
            "retired_gates": {
                "control-plane/universal_control_plane": sorted(
                    set(verifier.REQUIRED_GATE_COVERAGE[_SCOPED_REQUIREMENT])
                )
            }
        },
    ],
)
def test_malformed_release_scope_fails_closed(brain_home: Path, overrides: dict) -> None:
    del brain_home
    overlay = _scope_overlay(Path(__file__).parent / "_scope_probe.json", **overrides)
    try:
        scope, errors = verifier.load_release_scope(overlay)
        assert scope is None
        assert errors
    finally:
        overlay.unlink(missing_ok=True)


def test_scope_check_row_reports_retired_clauses_without_a_hardcoded_pass(
    brain_home: Path,
) -> None:
    manifest = _seed_complete_qualification(brain_home)
    scope = _scope_overlay(brain_home / "scope.json")
    result = verifier.verify_all(brain_home, manifest, None, scope)
    row = next(item for item in result["checks"] if item["check"] == "release_scope")
    assert row["ok"] is True
    assert result["release_scope"]["scope_id"] == "test-omp-only"
    assert result["release_scope"]["retired_gates_counted_as_passed"] is False
    assert result["release_scope"]["retired_gate_count"] == len(_RETIRED_CLAUSES)
    assert result["release_scope"]["sha256"] == hashlib.sha256(scope.read_bytes()).hexdigest()
    # The synthetic fixture is non-production evidence, so the release still holds.
    assert result["ok"] is False
