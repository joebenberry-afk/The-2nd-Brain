"""Assemble and verify the successor export package.

The export is a manifest of the exact tested subject (commit, fingerprints, the
pack files that describe it), the deployment and rollback recipe, the
finding-closure matrix, the test accounting, and the evidence files the campaign
produced - each with a digest. ``--verify`` re-hashes every referenced file
from the exported package, so a reader can confirm the export describes the
bytes it claims to.

    python scripts/export_successor_package.py \
        --pack outputs/reports/omp-successor-qualification-<stamp>
    python scripts/export_successor_package.py --pack <pack> --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUCCESSOR_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19-successor"
PREDECESSOR_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19"
HARDENING_PACK = REPO_ROOT.parent.parent / "outputs/reports/omp-verification-hardening-20260920"

PACK_FILES = (
    "SUCCESSOR-RECORD.json",
    "HASHES.txt",
    "RUN-IDENTITIES.json",
    "CANDIDATE-IDENTITY.json",
    "DEPLOYMENT-MANIFEST.json",
    "SHIPPING-CANDIDATE-MANIFEST.json",
    "APPROVED-SUCCESSOR.json",
    "REASONS.json",
)

RECIPE = [
    {
        "step": "record differences",
        "command": "python scripts/generate_successor_record.py --report",
        "outputs": ["stdout: kind/status/path per differing path"],
    },
    {
        "step": "stage the successor (disposable)",
        "command": (
            "python scripts/stage_omp_successor.py --root %TEMP%/omp-successor-<stamp>"
            "/staged"
        ),
        "outputs": [
            "STAGE-MANIFEST.json (host overlays, intended tree, extension, user root, "
            "runtime packages, vendor junctions)"
        ],
    },
    {
        "step": "write and seal the record",
        "command": (
            "python scripts/generate_successor_record.py --write --staged-root <stage> "
            "--campaign-index <pack>/campaign-index.json && "
            "python scripts/generate_successor_record.py --seal --staged-root <stage> "
            "--campaign-index <pack>/campaign-index.json [--review <verdict.json>]"
        ),
        "outputs": PACK_FILES,
    },
    {
        "step": "deployment manifest for the staged layout",
        "command": (
            "python scripts/generate_omp_deployment_manifest.py --write "
            "--patch-dir docs/integrations/omp-host-patch-2026-09-19-successor "
            "--sealed-host <stage>/host-source --installed-host <stage>/global/node_modules/"
            "@oh-my-pi/pi-coding-agent-canary --installed-extension <stage>/extension"
        ),
        "outputs": ["DEPLOYMENT-MANIFEST.json"],
    },
    {
        "step": "run the bounded campaign",
        "command": (
            "python scripts/run_successor_campaign.py --stage <stage> --out <pack> "
            "--steps preflight,session-1,post-exit-1,session-2,post-exit-2 [--suffix=-x]"
        ),
        "outputs": [
            "preflight.json",
            "session-1*/launch.json + watcher/",
            "post-exit-session-1*.json",
            "session-2*/launch.json + watcher/",
            "post-exit-session-2*.json",
        ],
    },
    {
        "step": "negative control (sealed module must fail)",
        "command": "python scripts/run_host_settlement_tests.py",
        "outputs": ["stdout: sealed 1 / candidate 0, PASS"],
    },
    {
        "step": "supported launcher against the staged manifest",
        "command": (
            "powershell -NoProfile -File scripts/run-omp-patched.ps1 -ManifestPath "
            "docs/integrations/omp-host-patch-2026-09-19-successor/DEPLOYMENT-MANIFEST.json "
            "--version"
        ),
        "outputs": ["stdout: patched OMP host verified (20 host files, 26 extension files)"],
    },
    {
        "step": "rollback rehearsal on disposable copies",
        "command": "python scripts/rehearse_successor_rollback.py --stage <stage> --out <pack>",
        "outputs": ["rollback-rehearsal.json"],
    },
]

FINDINGS = [
    # (id, failure, repair commit, regression, reviewer evidence)
    (
        "F-01",
        "publication visible before its authority was journaled",
        "5103f59",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "F-02",
        "restore recorded hashes for files it never restored",
        "5103f59",
        "tests/test_backup.py",
        "verify-round3.json",
    ),
    (
        "F-03",
        "restore losing records reported a first-ever baseline",
        "5103f59",
        "tests/test_backup.py, tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "F-04",
        "restore could delete pre-existing destination data",
        "5103f59, d79da7a",
        "tests/test_backup.py",
        "verify-round3.json",
    ),
    (
        "F-05",
        "journal paths trusted as authority",
        "5103f59",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-1",
        "failed record write left the artifact published with no authority",
        "d79da7a",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-2",
        "recovery committed a journal for a live caller",
        "d79da7a",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-3",
        "damaged record blocked every later promotion",
        "d79da7a, 246c6bf",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-4",
        "doctor hid one governance problem behind another",
        "246c6bf",
        "tests/test_doctor.py",
        "verify-round3.json",
    ),
    (
        "R2-5",
        "recovered record inherited the journal's inflated version",
        "246c6bf",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-6",
        "failed marker write dropped the intent",
        "246c6bf",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-7",
        "failed move left status at the target level",
        "246c6bf",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-8",
        "reservation cleanup failure failed a committed publication",
        "246c6bf",
        "tests/test_promotion.py",
        "verify-round3.json",
    ),
    (
        "R2-9",
        "layout cleanup deleted a pre-existing layout parent",
        "246c6bf",
        "tests/test_backup.py",
        "verify-round3.json",
    ),
    (
        "R3-1",
        "rollback deleted authority a concurrent writer committed",
        "a72a1c0",
        "tests/test_promotion.py",
        "verify-round4.json",
    ),
    (
        "R3-2",
        "marker then contradicted the deleted record",
        "a72a1c0",
        "tests/test_promotion.py",
        "verify-round4.json",
    ),
    (
        "R3-3",
        "quarantine scanned only the current skill's records",
        "a72a1c0",
        "tests/test_promotion.py",
        "verify-round4.json",
    ),
    (
        "R3-4",
        "non-object JSON was damage to the reader, healthy to quarantine",
        "a72a1c0",
        "tests/test_promotion.py",
        "verify-round4.json",
    ),
    (
        "R3-5",
        "quarantine overwrote earlier damaged evidence",
        "a72a1c0, 86653c9",
        "tests/test_promotion.py",
        "verify-round4.json, verify-round5.json",
    ),
    (
        "R4-1",
        "record name could be re-acquired after commit",
        "86653c9",
        "tests/test_promotion.py",
        "verify-round5.json",
    ),
    (
        "R4-2",
        "failed marker write removed the journal",
        "e888503",
        "tests/test_promotion.py",
        "verify-round5.json",
    ),
    (
        "R4-3",
        "journal cleanup failure escaped after a completed publication",
        "e888503",
        "tests/test_promotion.py",
        "verify-round5.json",
    ),
    (
        "R4-4",
        "invalid UTF-8 escaped the damaged-record predicate",
        "e888503",
        "tests/test_promotion.py",
        "verify-round6.json",
    ),
    (
        "R5-1",
        "partially written archive trusted as complete",
        "478f906",
        "tests/test_promotion.py",
        "verify-round6.json",
    ),
    (
        "R5-2",
        "healthy replacement could be archived as damage",
        "478f906",
        "tests/test_promotion.py",
        "verify-round6.json",
    ),
    (
        "R5-3",
        "superseded publication left a stale marker level",
        "478f906, 6563e41",
        "tests/test_promotion.py, tests/test_doctor.py",
        "verify-round7.json",
    ),
    (
        "R6-1",
        "two quarantine passes shared a staging file",
        "3aea515",
        "tests/test_promotion.py",
        "verify-round7.json",
    ),
    (
        "F-06",
        "accepted attempt outcome was mutable on the host",
        "4ae207b",
        "docs/integrations/omp-host-patch-2026-09-19/tests/attempt-settlement-outcome.test.ts",
        "negative-control-settlement.txt",
    ),
    (
        "F-07",
        "the qualified route had no verified launcher",
        "0226e94, 5cc8481",
        "scripts/run-omp-patched.ps1",
        "launcher-staged-version.txt",
    ),
    (
        "F-08",
        "recall passed the raw prompt as the query",
        "9f9c642",
        "brainstem/prime-extension/tests/recall-gate.test.ts",
        "session-1-f/launch.json",
    ),
]


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def build(pack: Path) -> dict:
    record = json.loads((SUCCESSOR_DIR / "SUCCESSOR-RECORD.json").read_text(encoding="utf-8"))
    evidence = sorted(
        {
            *[
                p.name
                for p in pack.iterdir()
                if p.is_file() and p.name != "EXPORT-MANIFEST.json"
            ],
            *[
                str(p.relative_to(pack).as_posix())
                for p in pack.rglob("*")
                if p.is_file() and p.parent != pack and p.name != "EXPORT-MANIFEST.json"
            ],
        }
    )
    return {
        "schema": "second-brain.omp-successor-export.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "subject": {
            "worktree": str(REPO_ROOT),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": git("rev-parse", "HEAD"),
            "source_tree_sha256": record["lineage"]["successor"]["source_tree_sha256"],
            "extension_fingerprint": record["lineage"]["successor"]["extension_fingerprint"],
            "staged_layout": record["staged_layout"]["root"],
            "stage_manifest_sha256": record["staged_layout"]["stage_manifest_sha256"],
        },
        "lineage": record["lineage"],
        "pack_files": {
            name: sha256_file(SUCCESSOR_DIR / name)
            for name in PACK_FILES
            if (SUCCESSOR_DIR / name).is_file()
        },
        "predecessor_files": {
            name: sha256_file(PREDECESSOR_DIR / name)
            for name in ("SHIPPING-CANDIDATE-MANIFEST.json", "RUN-IDENTITIES.json", "HASHES.txt")
        },
        "hardening_record": {
            "path": str(HARDENING_PACK),
            "closure_report_sha256": sha256_file(HARDENING_PACK / "CLOSURE-REPORT.md"),
        },
        "recipe": RECIPE,
        "evidence": {name: sha256_file(pack / name) for name in evidence},
        "finding_matrix": [
            {
                "id": finding,
                "failure": failure,
                "repair_commit": commit,
                "regression": regression,
                "reviewer_evidence": reviewer,
            }
            for finding, failure, commit, regression, reviewer in FINDINGS
        ],
        "test_accounting": {
            "source": "full-suite.txt",
            "note": (
                "The predecessor run's single failure was the identity guard; it is replaced by "
                "two tests bound to the approved successor (drift on the candidate identity, and "
                "predecessor-seal preservation), so the collected count changes by one."
            ),
        },
        "explicit_non_claims": record["explicit_non_claims"],
    }


def verify(pack: Path, manifest: dict) -> list[str]:
    problems: list[str] = []
    for group, paths in (
        ("pack_files", {name: SUCCESSOR_DIR / name for name in manifest["pack_files"]}),
        (
            "predecessor_files",
            {name: PREDECESSOR_DIR / name for name in manifest["predecessor_files"]},
        ),
        ("evidence", {name: pack / name for name in manifest["evidence"]}),
    ):
        for name, recorded in (
            manifest["pack_files"].items()
            if group == "pack_files"
            else manifest["predecessor_files"].items()
            if group == "predecessor_files"
            else manifest["evidence"].items()
        ):
            path = paths.get(name)
            actual = sha256_file(path) if path else None
            if actual != recorded:
                problems.append(f"{group}:{name}: recorded {recorded} actual {actual}")
    stage = Path(manifest["subject"]["staged_layout"]) / "STAGE-MANIFEST.json"
    if sha256_file(stage) != manifest["subject"]["stage_manifest_sha256"]:
        problems.append(f"stage manifest: recorded {manifest['subject']['stage_manifest_sha256']}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    manifest_path = args.pack / "EXPORT-MANIFEST.json"
    if args.verify:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        problems = verify(args.pack, manifest)
        print(json.dumps({"problems": problems, "ok": not problems}, indent=2))
        return 1 if problems else 0

    manifest = build(args.pack)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    problems = verify(args.pack, manifest)
    print(
        json.dumps(
            {
                "export": str(manifest_path),
                "pack_files": len(manifest["pack_files"]),
                "evidence_files": len(manifest["evidence"]),
                "findings": len(manifest["finding_matrix"]),
                "verification_problems": problems,
            },
            indent=2,
        )
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
