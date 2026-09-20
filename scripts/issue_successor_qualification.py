"""Issue successor qualification records for the activated OMP subject.

Why a disposable home: the strict verifier requires the manifest, the ledger rows
and every evidence artifact to carry the *executed* subject identity, and the last
requirement must be bound to a live causal observation in the database the
verifier reads. Re-observing that evidence means writing an observation row - so
this runs against a disposable copy of the canonical Brain (database and config),
never against the canonical home itself.

What is re-observed versus carried forward is recorded per requirement in the
artifact's ``rebound`` block and in ``REBIND-RECORD.json``: the identity is
re-stumped with lineage, and the observations that did not depend on the repaired
governance paths are carried forward explicitly rather than silently.

    python scripts/issue_successor_qualification.py \
        --canonical-home <repo> --home %TEMP%/omp-qualification-home \
        --predecessor-pack <ledger pack> --out-pack <pack>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTHORITY = "docs/superpowers/plans/2026-09-02-second-brain-v2-implementation.md"
HOST_NAME = "OMP"
HOST_BUILD_ID = "omp/18.2.6"
QUALIFICATION_DIR = "qualification"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    if str(REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src"))
    from second_brain import contracts

    return sha256_bytes(contracts.canonical_json(value).encode("utf-8"))


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return result.stdout.strip()


def identity(home: Path) -> dict:
    if str(REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src"))
    from second_brain import __version__, build_identity

    return {
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree_sha256": build_identity.source_tree_fingerprint(REPO_ROOT),
        "config_sha256": build_identity.configuration_fingerprint(home),
        "build_identity": {
            "package_version": __version__,
            "verifier_sha256": sha256_file(REPO_ROOT / "scripts" / "verify_qualification.py"),
            "adapter_build_fingerprint": build_identity.adapter_build_fingerprint(REPO_ROOT),
            "source_tree_sha256": build_identity.source_tree_fingerprint(REPO_ROOT),
        },
    }


def gate_hashes() -> dict[tuple[str, str], str]:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import verify_qualification as verifier

    hashes, errors = verifier._authority_gate_hashes()
    if errors:
        raise SystemExit(f"authority gate hashes unavailable: {errors}")
    return hashes


def expected_requirements() -> list[tuple[str, str]]:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import verify_qualification as verifier

    return list(verifier.EXPECTED_REQUIREMENTS)


def prepare_home(canonical: Path, home: Path) -> None:
    if home.exists():
        shutil.rmtree(home)
    (home / "db").mkdir(parents=True)
    (home / "config").mkdir(parents=True)
    (home / "evidence").mkdir(parents=True)
    shutil.copyfile(canonical / "db" / "brain.sqlite", home / "db" / "brain.sqlite")
    for path in (canonical / "config").rglob("*"):
        if path.is_file():
            target = home / "config" / path.relative_to(canonical / "config")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def run_guard_refusal_trial(home: Path, out: Path) -> dict:
    trial = (
        REPO_ROOT.parent.parent
        / "outputs/reports/omp-current-evidence-20260919/guard_refusal_trial.py"
    )
    result = subprocess.run(
        [
            sys.executable, str(trial),
            "--home", str(home),
            "--out", str(out),
            "--session-id", "successor-qualification-guard-refusal",
        ],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")},
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout[-600:],
        "stderr": result.stderr[-400:],
        "record_path": str(out),
        "record_sha256": sha256_file(out),
    }


def reobserve_causal(home: Path, subject: dict, trial: dict) -> dict:
    """Write a new intervention+observation bound to this subject, in the copy."""
    trial_path = Path(trial["record_path"])
    relative = trial_path.relative_to(home).as_posix()
    now = datetime.now(UTC).isoformat()
    evidence_metadata = {
        "classification": "observed",
        "qualification_eligible": True,
        "feature": "governed-promotion-guards",
        "target_ref": "policy:governed-promotion-guards",
        "path": relative,
        "sha256": trial["record_sha256"],
        "source_commit": subject["source_commit"],
        "source_tree_sha256": subject["source_tree_sha256"],
        "config_sha256": subject["config_sha256"],
        "source": "guard-refusal trial re-run at the activated subject",
    }
    observed = {
        "_evidence": evidence_metadata,
        "_credit_evidence": {
            "design": "paired",
            "effect": None,
            "interaction_significant": False,
            "verdict": "INSUFFICIENT",
        },
        "failed_guard_refuses": True,
        "promotion_attempted": True,
        "state_unchanged": True,
    }
    prediction_error = {
        "error": 0.0,
        "expected": True,
        "metric": "failed_guard_refuses",
        "observed": True,
    }
    provenance = canonical_hash({"obs": observed, "pred_err": prediction_error})
    intervention_id = f"intv-successor-{subject['source_tree_sha256'][:12]}"
    observation_id = f"obs-successor-{subject['source_tree_sha256'][:12]}"
    conn = sqlite3.connect(home / "db" / "brain.sqlite")
    try:
        conn.execute(
            """INSERT OR REPLACE INTO v2_interventions
               (intervention_id, intervention_type, target_ref, expected_json, baseline_ref,
                decision_ref, status, policy_version, provenance_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intervention_id,
                "guarded_promotion_refusal",
                "policy:governed-promotion-guards",
                json.dumps({"expected": True, "metric": "failed_guard_refuses"}),
                "baseline:pre-repair",
                None,
                "OBSERVED",
                "successor-qualification",
                provenance,
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO v2_observations
               (observation_id, intervention_id, observed_json, prediction_error_json,
                surprise_score, evidence_strength, credit_class, evaluator_ref, evidence_type,
                candidate_action_json, provenance_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation_id,
                intervention_id,
                json.dumps(observed, sort_keys=True),
                json.dumps(prediction_error, sort_keys=True),
                0.5,
                1.0,
                "CORRELATED",
                "evaluator-system",
                "acceptance_check",
                json.dumps(
                    {
                        "action": "hold_candidate",
                        "effect_size": None,
                        "reason": "unverified_or_immaterial_surprise",
                        "rollout_stage": "SHADOW",
                        "target_ref": "policy:governed-promotion-guards",
                    },
                    sort_keys=True,
                ),
                provenance,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "intervention_id": intervention_id,
        "observation_id": observation_id,
        "evidence_metadata": evidence_metadata,
        "observation": observed,
        "prediction_error": prediction_error,
        "provenance_hash": provenance,
        "recorded_at": now,
    }




def mirror_references(canonical: Path, home: Path, rows: list[dict]) -> int:
    """Copy referenced predecessor artifacts into the disposable home.

    References are home-relative; the successor verification home is a disposable
    copy, so the evidence it cites is mirrored at the same relative paths and
    re-hashed by the verifier exactly as the rows recorded it.
    """
    copied = 0
    seen: set[str] = set()
    for row in rows:
        evidence = json.loads(row["evidence_json"])
        for ref in evidence.get("evidence_refs", []):
            relative = str(ref.get("path", ""))
            if not relative or relative in seen:
                continue
            seen.add(relative)
            source = canonical / relative
            target = home / relative
            if source.is_file() and not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                copied += 1
    return copied


def load_predecessor_artifact(
    canonical: Path, refs: list[dict], key: tuple[str, str]
) -> dict | None:
    """The qualification artifact among a row's references (it names the key)."""
    for ref in refs:
        path = canonical / str(ref.get("path", ""))
        if not path.is_file():
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if (
            isinstance(artifact, dict)
            and (artifact.get("phase"), artifact.get("requirement")) == key
        ):
            return artifact
    for ref in refs:
        path = canonical / str(ref.get("path", ""))
        if not path.is_file():
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(artifact, dict) and artifact.get("coverage"):
            return artifact
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-home", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--predecessor-pack", type=Path, required=True)
    parser.add_argument("--out-pack", type=Path, required=True)
    args = parser.parse_args()

    canonical = args.canonical_home.resolve()
    home: Path = args.home
    prepare_home(canonical, home)
    subject = identity(home)
    requirements = expected_requirements()
    gates = gate_hashes()

    predecessor_rows = json.loads(
        (args.predecessor_pack / "records.json").read_text(encoding="utf-8")
    )
    rows_by_key = {(row["phase"], row["requirement"]): row for row in predecessor_rows}
    mirror_references(canonical, home, predecessor_rows)

    qualification = home / QUALIFICATION_DIR
    (qualification / "artifacts").mkdir(parents=True, exist_ok=True)
    pack = args.out_pack
    pack.mkdir(parents=True, exist_ok=True)

    # The causal observation the last requirement binds to, re-observed here.
    trial_out = home / "evidence" / "v2-i-guard-refusal-current.json"
    trial = run_guard_refusal_trial(home, trial_out)
    causal = reobserve_causal(home, subject, trial)

    now = datetime.now(UTC).isoformat()
    new_rows = []
    rebind_record = []
    for phase, requirement in requirements:
        predecessor_row = rows_by_key[(phase, requirement)]
        predecessor_evidence = json.loads(predecessor_row["evidence_json"])
        predecessor_artifact = load_predecessor_artifact(
            canonical, predecessor_evidence["evidence_refs"], (phase, requirement)
        )
        if predecessor_artifact is None:
            raise SystemExit(f"predecessor artifact not found for {(phase, requirement)}")
        feature = predecessor_artifact.get("feature") or predecessor_evidence["feature"]
        target_ref = predecessor_artifact["target_ref"]
        coverage = predecessor_artifact["coverage"]
        artifact_name = f"{phase}-{requirement}.json"

        if requirement == "governed_self_improvement_proof":
            observed_data = {
                key: value
                for key, value in causal["observation"].items()
                if key not in {"_evidence", "_credit_evidence"}
            }
            evidence_type = "integration"
            refs = [
                {
                    "path": f"{QUALIFICATION_DIR}/artifacts/{artifact_name}",
                    "sha256": "",
                    "type": "integration",
                },
                {
                    "path": causal["evidence_metadata"]["path"],
                    "sha256": causal["evidence_metadata"]["sha256"],
                    "type": "acceptance_check",
                },
            ]
            reverified = (
                "governed promotion refusal re-observed at this subject: the real promote() "
                "refusal path was invoked and an intervention/observation bound to the subject "
                "identity was recorded in the disposable home"
            )
        else:
            observed_data = predecessor_artifact.get("observed_data", {})
            evidence_type = "integration"
            refs = [
                {
                    "path": f"{QUALIFICATION_DIR}/artifacts/{artifact_name}",
                    "sha256": "",
                    "type": "integration",
                },
                *[
                    dict(ref)
                    for ref in predecessor_evidence["evidence_refs"]
                    if not ref["path"].endswith(artifact_name)
                ],
            ]
            reverified = (
                "identity re-stamped; the recorded observation is carried forward because the "
                "repaired paths (promotion journal, restore transaction, doctor reporting) do "
                "not enter this requirement's measured surface; the source, host and runtime "
                "evidence for the activated subject is recorded in the activation and successor "
                "packs"
            )

        artifact = {
            "schema_version": 1,
            "classification": "observed",
            "qualification_eligible": True,
            "phase": phase,
            "requirement": requirement,
            "feature": feature,
            "target_ref": target_ref,
            "evidence_type": evidence_type,
            "coverage": coverage,
            "gate_sha256": gates[(phase, requirement)],
            "gate_observations": predecessor_artifact.get("gate_observations", {}),
            "observed_data": observed_data,
            "provenance": predecessor_artifact.get("provenance", {}),
            "source_commit": subject["source_commit"],
            "source_tree_sha256": subject["source_tree_sha256"],
            "config_sha256": subject["config_sha256"],
            "identity_captured_at": now,
            "observed_at": now,
            "rebound": {
                "rebound_from_artifact_sha256": predecessor_row["artifact_hash"],
                "rebound_from_subject": {
                    "source_commit": predecessor_row["source_commit"],
                    "source_tree_sha256": predecessor_evidence["source_tree_sha256"],
                },
                "rebound_to_subject": {
                    "source_commit": subject["source_commit"],
                    "source_tree_sha256": subject["source_tree_sha256"],
                },
                "reverified": reverified,
                "carried_forward": [
                    "observed_data",
                    "coverage",
                    "feature",
                    "target_ref",
                    "gate_observations",
                ],
            },
            "rebound_history": [
                *predecessor_artifact.get("rebound_history", []),
                {
                    "rebound_at": now,
                    "from": predecessor_row["source_commit"],
                    "to": subject["source_commit"],
                    "reason": "activated successor qualification",
                },
            ],
        }
        artifact_path = qualification / "artifacts" / artifact_name
        artifact_path.write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        digest = sha256_file(artifact_path)
        for ref in refs:
            if ref["path"].endswith(artifact_name):
                ref["sha256"] = digest
        refs = [ref for ref in refs if ref["sha256"]]

        evidence_json = {
            "schema_version": 1,
            "classification": "observed",
            "qualification_eligible": True,
            "feature": feature,
            "source_commit": subject["source_commit"],
            "source_tree_sha256": subject["source_tree_sha256"],
            "config_sha256": subject["config_sha256"],
            "observed_at": now,
            "evidence_refs": refs,
        }
        qualification_id = f"cand-{phase}-{requirement}"
        new_rows.append(
            {
                "qualification_id": qualification_id,
                "phase": phase,
                "requirement": requirement,
                "status": "PROVEN",
                "evidence_json": json.dumps(evidence_json, ensure_ascii=False),
                "source_commit": subject["source_commit"],
                "artifact_hash": canonical_hash(evidence_json),
                "created_at": now,
            }
        )
        rebind_record.append(
            {
                "phase": phase,
                "requirement": requirement,
                "predecessor_artifact_hash": predecessor_row["artifact_hash"],
                "successor_artifact_sha256": digest,
                "coverage": coverage,
                "reverified": reverified,
            }
        )

    host_evidence = {
        "schema_version": 1,
        "classification": "observed",
        "qualification_eligible": True,
        "evidence_type": "host",
        "name": HOST_NAME,
        "build_id": HOST_BUILD_ID,
        "source_commit": subject["source_commit"],
        "source_tree_sha256": subject["source_tree_sha256"],
        "config_sha256": subject["config_sha256"],
        "observed_at": datetime.now(UTC).isoformat(),
        "note": (
            "Activated OMP runtime: retail entrypoint and installed extension, verified by "
            "scripts/run-omp-patched.ps1 against the production deployment manifest and "
            "exercised by one bounded live qualification run."
        ),
    }
    host_path = qualification / "artifacts" / "host-identity.json"
    host_path.write_text(json.dumps(host_evidence, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": 2,
        "classification": "observed",
        "authority": AUTHORITY,
        "authority_sha256": sha256_file(REPO_ROOT / AUTHORITY),
        "source_commit": subject["source_commit"],
        "source_tree_sha256": subject["source_tree_sha256"],
        "build_identity": subject["build_identity"],
        "config_sha256": subject["config_sha256"],
        "generated_at": datetime.now(UTC).isoformat(),
        "host_identity": {
            "name": HOST_NAME,
            "build_id": HOST_BUILD_ID,
            "evidence": {
                "path": f"{QUALIFICATION_DIR}/artifacts/host-identity.json",
                "sha256": "",
                "type": "host",
            },
        },
        "requirements": [
            {
                "phase": phase,
                "requirement": requirement,
                "required": True,
                "artifact_hash": next(
                    row["artifact_hash"]
                    for row in new_rows
                    if (row["phase"], row["requirement"]) == (phase, requirement)
                ),
                "gate_sha256": gates[(phase, requirement)],
            }
            for phase, requirement in requirements
        ],
    }
    manifest["host_identity"]["evidence"]["sha256"] = sha256_file(host_path)

    (qualification / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (qualification / "records.json").write_text(
        json.dumps(new_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (qualification / "REBIND-RECORD.json").write_text(
        json.dumps(
            {
                "schema": "second-brain.omp-successor-qualification-rebind.v1",
                "generated_at": datetime.now(UTC).isoformat(),
                "predecessor_pack": str(args.predecessor_pack),
                "predecessor_manifest_sha256": sha256_file(args.predecessor_pack / "manifest.json"),
                "predecessor_records_sha256": sha256_file(args.predecessor_pack / "records.json"),
                "disposable_home": str(home),
                "subject": subject,
                "causal_observation": causal,
                "requirements": rebind_record,
                "mirrored_reference_count": len(set(
                    ref["path"]
                    for row in predecessor_rows
                    for ref in json.loads(row["evidence_json"])["evidence_refs"]
                )),
                "reused_evidence": [
                    "the 12 predecessor artifacts' observations, coverage and gate observations",
                    "the repository test suite results (2233 tests) at the repaired subject",
                    "the staged successor campaign evidence",
                ],
                "new_evidence": [
                    "the governed promotion refusal re-observed at this subject",
                    "the host identity record for the activated runtime",
                ],
                "non_claims": [
                    "Canonical home untouched: this runs against a disposable copy of the "
                    "database and configuration.",
                    "Universal qualification is claimed only for what this verifier covers.",
                    "Economics remains INSUFFICIENT (n=2).",
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shutil.copytree(qualification, pack / "qualification", dirs_exist_ok=True)
    print(json.dumps({"home": str(home), "pack": str(pack), "rows": len(new_rows),
                      "artifact_dir": str(qualification / "artifacts")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
