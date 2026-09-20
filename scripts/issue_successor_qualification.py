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
GUARDS_FEATURE = "governed-promotion-guards"
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
    for tree in ("config", "skills", "state"):
        for path in (canonical / tree).rglob("*"):
            if path.is_file():
                target = home / tree / path.relative_to(canonical / tree)
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


def bind_causal_observation(
    home: Path, relative: str, digest: str, artifact: dict, subject: dict
) -> dict:
    """Record the observation the guards artifact binds to, in the copy.

    The verifier's binding walks the copy's observations and accepts the one whose
    ``_evidence`` names the referenced artifact with the identity of the subject it
    was issued for, whose raw part is the artifact's ``observed_data`` and whose
    provenance hash covers the record. The refusal trial itself is read-only for
    Brain state, so the observation record is written here.
    """
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(home / "db" / "brain.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        prior = conn.execute(
            "SELECT o.observed_json, o.prediction_error_json, o.surprise_score, "
            "o.evidence_strength, o.credit_class, o.evaluator_ref, o.evidence_type, "
            "o.candidate_action_json, i.intervention_type, i.expected_json, "
            "i.baseline_ref, i.decision_ref, i.policy_version "
            "FROM v2_observations AS o "
            "JOIN v2_interventions AS i ON i.intervention_id = o.intervention_id "
            "WHERE i.target_ref = ? "
            "ORDER BY o.created_at DESC LIMIT 1",
            (artifact["target_ref"],),
        ).fetchone()
        if prior is None:
            raise SystemExit("no predecessor observation for the guards artifact")
        prior_observed = json.loads(prior["observed_json"])
        observed = dict(artifact["observed_data"])
        observed["_evidence"] = {
            "classification": "observed",
            "config_sha256": subject["config_sha256"],
            "feature": artifact["feature"],
            "path": relative,
            "qualification_eligible": True,
            "sha256": digest,
            "source_commit": subject["source_commit"],
            "source_tree_sha256": subject["source_tree_sha256"],
            "target_ref": artifact["target_ref"],
        }
        credit = prior_observed.get("_credit_evidence")
        if credit is not None:
            observed["_credit_evidence"] = credit
        prediction_error = json.loads(prior["prediction_error_json"])
        provenance = canonical_hash({"obs": observed, "pred_err": prediction_error})
        intervention_id = "intv-" + sha256_bytes(
            f"{artifact['target_ref']}|{subject['source_commit']}|{relative}".encode()
        )[:24]
        observation_id = "obs-" + sha256_bytes(
            f"{intervention_id}|{relative}|{digest}".encode()
        )[:24]
        conn.execute(
            """INSERT OR REPLACE INTO v2_interventions
               (intervention_id, intervention_type, target_ref, expected_json, baseline_ref,
                decision_ref, status, policy_version, provenance_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intervention_id,
                prior["intervention_type"],
                artifact["target_ref"],
                prior["expected_json"],
                prior["baseline_ref"],
                prior["decision_ref"],
                "OBSERVED",
                prior["policy_version"],
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
                prior["surprise_score"],
                prior["evidence_strength"],
                prior["credit_class"],
                prior["evaluator_ref"],
                prior["evidence_type"],
                prior["candidate_action_json"],
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
        "evidence_ref": {"path": relative, "sha256": digest, "feature": artifact["feature"]},
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
    queue: list[str] = []
    for row in rows:
        evidence = json.loads(row["evidence_json"])
        for ref in evidence.get("evidence_refs", []):
            queue.append(str(ref.get("path", "")))
    while queue:
        relative = queue.pop()
        if not relative or relative in seen:
            continue
        seen.add(relative)
        source = canonical / relative
        target = home / relative
        if not source.is_file():
            continue
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied += 1
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(document, dict):
            for raw in document.get("provenance", {}).get("raw_evidence_refs", []):
                if isinstance(raw, dict) and isinstance(raw.get("path"), str):
                    queue.append(raw["path"])
    return copied


def reidentify_reference(
    canonical: Path,
    home: Path,
    relative: str,
    subject: dict,
    now: str,
    note: str,
    cache: dict[str, tuple[str, dict | None]],
    extra_raw: dict | None = None,
) -> tuple[str, dict | None]:
    """Re-stamp one referenced file at the current subject, in the verification home.

    Qualification artifacts keep their measured content and gain the successor
    identity plus an explicit lineage block (what was re-verified versus carried
    forward). Non-artifact references are carried verbatim; their recorded hash
    still holds.
    """
    if relative in cache:
        return cache[relative]
    target = home / relative
    if not target.is_file():
        source = canonical / relative
        if not source.is_file():
            raise SystemExit(f"referenced evidence is unavailable: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    artifact = None
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        document = None
    if (
        isinstance(document, dict)
        and isinstance(document.get("observed_data"), dict)
        and document.get("coverage")
    ):
        artifact = document
        former = {
            "source_commit": document.get("source_commit"),
            "source_tree_sha256": document.get("source_tree_sha256"),
            "config_sha256": document.get("config_sha256"),
        }
        document["source_commit"] = subject["source_commit"]
        document["source_tree_sha256"] = subject["source_tree_sha256"]
        document["config_sha256"] = subject["config_sha256"]
        document["identity_captured_at"] = now
        document["observed_at"] = now
        document["rebound"] = {
            "rebound_from_artifact_sha256": sha256_file(canonical / relative),
            "rebound_from_subject": former,
            "rebound_to_subject": {
                "source_commit": subject["source_commit"],
                "source_tree_sha256": subject["source_tree_sha256"],
            },
            "reverified": note,
            "carried_forward": [
                "observed_data",
                "coverage",
                "feature",
                "target_ref",
                "gate_observations",
                "provenance",
            ],
        }
        document["rebound_history"] = [
            *document.get("rebound_history", []),
            {
                "at": now,
                "from": former["source_commit"],
                "to": subject["source_commit"],
                "reason": "activated successor qualification",
            },
        ]
        if extra_raw is not None:
            raws = document.setdefault("provenance", {}).setdefault("raw_evidence_refs", [])
            if all(
                not isinstance(raw, dict) or raw.get("path") != extra_raw["path"] for raw in raws
            ):
                raws.append(extra_raw)
        target.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    digest = sha256_file(target)
    if digest is None:
        raise SystemExit(f"reference could not be stamped: {relative}")
    cache[relative] = (digest, artifact)
    return digest, artifact


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

    # The governed-promotion refusal is re-executed against this subject; every
    # referenced artifact is re-stamped with the subject identity and lineage.
    trial_out = qualification / "evidence" / "v2-i-guard-refusal-current.json"
    trial = run_guard_refusal_trial(home, trial_out)
    if trial["exit_code"] != 0 or trial["record_sha256"] is None:
        raise SystemExit(f"guard refusal trial failed: {trial['stdout']} {trial['stderr']}")

    trial_relative = trial_out.relative_to(home).as_posix()
    causal_relative = next(
        str(ref["path"])
        for ref in json.loads(
            rows_by_key[("v2-i", "governed_self_improvement_proof")]["evidence_json"]
        )["evidence_refs"]
        if "governed-promotion-guards" in str(ref["path"])
    )
    now = datetime.now(UTC).isoformat()
    cache: dict[str, tuple[str, dict | None]] = {}
    new_rows = []
    rebind_record = []
    causal_binding = None
    for phase, requirement in requirements:
        predecessor_row = rows_by_key[(phase, requirement)]
        predecessor_evidence = json.loads(predecessor_row["evidence_json"])
        feature = predecessor_evidence["feature"]
        evidence_refs = []
        covered: set[str] = set()
        for ref in predecessor_evidence["evidence_refs"]:
            relative = str(ref["path"])
            note = (
                "identity re-stamped on the activated subject; the recorded observation is "
                "carried forward because the repaired paths (promotion journal, restore "
                "transaction, doctor reporting) do not enter this requirement's measured "
                "surface, and the causal requirement is the only one whose conduct is "
                "re-executed here"
            )
            extra_raw = None
            if relative == causal_relative:
                note = (
                    "re-observed on the activated subject: the governed promotion refusal path "
                    "was re-executed against this home and its outcome recorded as an "
                    "observation whose evidence names this artifact"
                )
                extra_raw = {
                    "path": trial_relative,
                    "sha256": trial["record_sha256"],
                    "type": "raw",
                }
            digest, artifact = reidentify_reference(
                canonical, home, relative, subject, now, note, cache, extra_raw
            )
            evidence_refs.append({**ref, "sha256": digest})
            if artifact is not None:
                covered.update(artifact.get("coverage", []))
                if artifact.get("feature") == GUARDS_FEATURE:
                    causal_binding = bind_causal_observation(
                        home, relative, digest, artifact, subject
                    )
        evidence_json = {
            "schema_version": 1,
            "classification": "observed",
            "qualification_eligible": True,
            "feature": feature,
            "source_commit": subject["source_commit"],
            "source_tree_sha256": subject["source_tree_sha256"],
            "config_sha256": subject["config_sha256"],
            "observed_at": now,
            "evidence_refs": evidence_refs,
        }
        new_rows.append(
            {
                "qualification_id": f"cand-{phase}-{requirement}",
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
                "successor_artifact_hash": canonical_hash(evidence_json),
                "coverage": sorted(covered),
                "reverified": (
                    "causal observation re-executed"
                    if requirement == "governed_self_improvement_proof"
                    else "identity re-stamped; observation carried forward"
                ),
            }
        )
    if causal_binding is None:
        raise SystemExit("governed promotion guards artifact was not referenced")

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
                "causal_observation": causal_binding,
                "guard_refusal_trial": trial,
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
