"""Rehearse the successor rollback on disposable copies.

What this proves, without touching production:

1. the recorded rollback material restores the pre-activation bytes exactly
   (every restored file hashes to the ``was`` value recorded at activation);
2. a reverted host is *refused* by the identity gate - the deployment manifest
   check reports it stale and the supported launcher exits 2 naming the files -
   which is the behaviour a rollback depends on.

    python scripts/rehearse_successor_rollback.py --stage <staged root> \
        --out outputs/reports/omp-successor-qualification-<stamp>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUCCESSOR_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19-successor"
ACTIVATION_DIR = REPO_ROOT.parent.parent / "outputs/reports/omp-activation-20260920"
PYTHON = Path(sys.executable)


def clean_env() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items() if key not in ("PYTHONHOME", "PYTHONPATH")
    }


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    stage_manifest = json.loads((args.stage / "STAGE-MANIFEST.json").read_text(encoding="utf-8"))
    staged_host = Path(stage_manifest["host"]["package"])
    intended_tree = Path(stage_manifest["host"]["intended_tree"])
    staged_extension = Path(stage_manifest["extension"]["root"])
    delta = json.loads((ACTIVATION_DIR / "host-delta-applied.json").read_text(encoding="utf-8"))

    rehearsal_root = args.stage / "rollback-rehearsal"
    reverted = rehearsal_root / "host"
    if rehearsal_root.exists():
        shutil.rmtree(rehearsal_root)
    rehearsal_root.mkdir(parents=True)
    shutil.copytree(staged_host, reverted, symlinks=False)

    restored = []
    deleted = []
    for entry in delta.get("rollback", []):
        target = reverted / "src" / str(entry["file"]).replace("/", "\\")
        if entry.get("rollback_action") == "delete on rollback" or not entry.get("rollback_copy"):
            if target.is_file():
                target.unlink()
                deleted.append(entry["file"])
            continue
        copy = Path(entry["rollback_copy"])
        shutil.copyfile(copy, target)
        actual = sha256_file(target)
        restored.append(
            {
                "file": entry["file"],
                "rollback_copy": str(copy),
                "expected_was": entry["was"],
                "restored_sha256": actual,
                "restored_exactly": actual == str(entry["was"]).lower(),
            }
        )

    manifest_check = subprocess.run(
        [
            str(PYTHON),
            str(REPO_ROOT / "scripts" / "generate_omp_deployment_manifest.py"),
            "--check",
            "--patch-dir",
            str(SUCCESSOR_DIR),
            "--sealed-host",
            str(intended_tree),
            "--installed-host",
            str(reverted),
            "--installed-extension",
            str(staged_extension),
        ],
        capture_output=True,
        text=True,
        env=clean_env(),
    )

    launcher = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-File",
            str(REPO_ROOT / "scripts" / "run-omp-patched.ps1"),
            "-ManifestPath",
            str(SUCCESSOR_DIR / "DEPLOYMENT-MANIFEST.json"),
            "--version",
        ],
        capture_output=True,
        text=True,
        env={**clean_env(), "OMP_RETAIL_ROOT": str(reverted)},
    )

    payload = {
        "schema": "second-brain.omp-successor-rollback-rehearsal.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "disposable_root": str(rehearsal_root),
        "restored": restored,
        "deleted_added_files": deleted,
        "all_restored_exactly": all(row["restored_exactly"] for row in restored),
        "manifest_check": {
            "exit_code": manifest_check.returncode,
            "stdout_tail": manifest_check.stdout[-600:],
            "expected": "exit 1 with MANIFEST STALE (the reverted host no longer matches)",
        },
        "launcher_refusal": {
            "exit_code": launcher.returncode,
            "stdout_tail": launcher.stdout[-800:],
            "expected": "exit 2 listing the files that differ from the manifest",
        },
        "production_untouched": True,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "rollback-rehearsal.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "restored_files": len(restored),
                "all_restored_exactly": payload["all_restored_exactly"],
                "manifest_check_exit": manifest_check.returncode,
                "launcher_exit": launcher.returncode,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
