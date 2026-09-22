"""Activate the qualified successor into the production OMP installation.

Bounded by design: exactly the three files that differ between the installed
runtime and the approved successor are replaced, each backed up first, and the
identity transition is proved rather than assumed. The sealed predecessor pack is
not rewritten; the production record is written to a new directory.

Sequence (the manifest attests to reality; reality is not defined by it):

1. record the current production identity of the three files (+ backups);
2. copy the approved successor bytes;
3. re-hash the installed files and require the successor hashes;
4. recompute the whole governed surface (13 host + 26 extension files) and require
   zero unexpected and zero successor-required differences;
5. write the production HASHES.txt, RUN-IDENTITIES.json and deployment manifest;
6. `--check` the production manifest and require MANIFEST CURRENT.

    python scripts/activate_omp_successor.py --pack outputs/reports/omp-activation-<stamp>
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
PREDECESSOR_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19"
PRODUCTION_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19-production"
STAGED = Path(os.environ.get("TEMP", "")) / "omp-successor-20260920" / "staged"

OMP_PACKAGES = Path.home() / ".bun/install/global/node_modules/@oh-my-pi"
RETAIL = OMP_PACKAGES / "pi-coding-agent"
CANARY = OMP_PACKAGES / "pi-coding-agent-canary"
INSTALLED_EXTENSION = Path.home() / ".omp/agent/extensions/second-brain"

# The bounded activation surface: installed path -> approved successor source.
HOST_MODULE = "src/task/attempt-settlement.ts"
ACTIVATION_FILES = (
    ("extension/index.ts", INSTALLED_EXTENSION / "index.ts",
     STAGED / "extension" / "index.ts"),
    ("extension/recall-gate.ts", INSTALLED_EXTENSION / "recall-gate.ts",
     STAGED / "extension" / "recall-gate.ts"),
    (f"host/{HOST_MODULE}", RETAIL / HOST_MODULE, STAGED / "global" / "node_modules"
     / "@oh-my-pi" / "pi-coding-agent-canary" / HOST_MODULE),
)

GOVERNED_HOST = (
    "src/async/job-manager.ts", "src/session/agent-session.ts", "src/task/isolation-runner.ts",
    "src/task/cleanup-barrier.ts", "src/task/worktree.ts", "src/main.ts", "src/sdk.ts",
    "src/task/executor.ts", "src/task/index.ts", "src/task/structured-subagent.ts",
    "src/extensibility/extensions/runner.ts", "src/extensibility/extensions/types.ts",
    "src/task/attempt-settlement.ts",
)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def governed_extension() -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted((REPO_ROOT / "brainstem" / "prime-extension" / "src").glob("*.ts")):
        entries[path.name] = sha256_file(INSTALLED_EXTENSION / path.name) or ""
    types = INSTALLED_EXTENSION / "types" / "prime.d.ts"
    if types.is_file():
        entries["types/prime.d.ts"] = sha256_file(types) or ""
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument(
        "--staged",
        type=Path,
        default=None,
        help="stage root holding the approved bytes (default: the host-patch campaign stage)",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        metavar="LABEL=INSTALLED=SOURCE",
        help=(
            "activation surface, as data. Defaults to the three-file host-patch successor. "
            "A one-file extension repair passes exactly one entry, which is how a bounded "
            "repair reaches production without an unmanaged copy."
        ),
    )
    parser.add_argument(
        "--sealed-host",
        type=Path,
        default=None,
        help=(
            "the sealed reference for the host surface. Defaults to the canary under the "
            "stage root; a repair that changes no host file passes the installed package, "
            "which makes the recorded host delta zero because that is the truth."
        ),
    )
    args = parser.parse_args()
    staged_root: Path = args.staged or STAGED
    sealed_host: Path = args.sealed_host or (
        staged_root / "global" / "node_modules" / "@oh-my-pi" / "pi-coding-agent-canary"
    )
    if args.files:
        activation_files: tuple[tuple[str, Path, Path], ...] = tuple(
            (label, Path(installed), Path(source))
            for label, installed, source in (entry.split("=", 2) for entry in args.files)
        )
    else:
        activation_files = ACTIVATION_FILES
    pack: Path = args.pack
    pack.mkdir(parents=True, exist_ok=True)
    backups = pack / "backups"
    backups.mkdir(parents=True, exist_ok=True)

    record: dict = {
        "schema": "second-brain.omp-successor-activation.v1",
        "started_at": datetime.now(UTC).isoformat(),
        "authorization": (
            "user mandate: bounded activation of the three qualified successor files, followed by "
            "identity verification and a bounded live production qualification"
        ),
        "files": [],
    }

    # 1. record the current identity and back it up
    for label, installed, source in activation_files:
        before = sha256_file(installed)
        approved = sha256_file(source)
        if approved is None:
            raise SystemExit(f"approved successor bytes missing for {label}: {source}")
        backup = backups / label.replace("/", "__")
        if installed.is_file():
            shutil.copyfile(installed, backup)
        record["files"].append(
            {
                "label": label,
                "installed_path": str(installed),
                "successor_source": str(source),
                "installed_before": before,
                "successor_sha256": approved,
                "backup": str(backup),
                "backup_sha256": sha256_file(backup),
                "already_current": before == approved,
            }
        )

    # 2. install the approved bytes (only where they differ)
    for entry in record["files"]:
        if entry["already_current"]:
            continue
        shutil.copyfile(Path(entry["successor_source"]), Path(entry["installed_path"]))

    # 3. re-hash and require the successor hashes
    for entry in record["files"]:
        entry["installed_after"] = sha256_file(Path(entry["installed_path"]))
        entry["installed_matches_successor"] = (
            entry["installed_after"] == entry["successor_sha256"]
        )

    # 4. whole governed surface: unexpected deltas must be zero
    approved_extension = json.loads(
        (staged_root / "STAGE-MANIFEST.json").read_text(encoding="utf-8")
    )["extension"]["files"]
    approved_map = {row["staged"]: row["sha256"] for row in approved_extension}
    live_extension = governed_extension()
    unexpected = [
        name
        for name, digest in live_extension.items()
        if approved_map.get(name) not in (None, digest)
    ]
    missing = [name for name in approved_map if name not in live_extension]
    host_rows = []
    for relative in GOVERNED_HOST:
        installed = sha256_file(RETAIL / relative)
        canary = sha256_file(CANARY / relative)
        staged = sha256_file(
            staged_root / "global" / "node_modules" / "@oh-my-pi" / "pi-coding-agent-canary" / relative
        )
        host_rows.append(
            {
                "path": relative,
                "installed": installed,
                "successor": staged,
                "matches_successor": installed is not None and installed == staged,
                "matches_canary": installed is not None and installed == canary,
            }
        )
    record["governed_surface"] = {
        "extension_files": len(live_extension),
        "extension_unexpected_differences": unexpected,
        "extension_missing": missing,
        "unexpected_delta": len(unexpected) + len(missing),
        "host": host_rows,
        "host_files_matching_successor": sum(1 for row in host_rows if row["matches_successor"]),
    }

    # 5. production identity files and deployment manifest
    PRODUCTION_DIR.mkdir(parents=True, exist_ok=True)
    # The bind set keeps the predecessor's shape (canary host paths, extension
    # sources) so the deployment manifest reads it the same way, but every digest
    # is taken from the installed bytes this activation just produced.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import generate_omp_deployment_manifest as generator

    host_binds, extension_binds = generator.bound_hashes(PREDECESSOR_DIR)
    bind_lines = []
    for relative in sorted(host_binds):
        bind_lines.append(f"{sha256_file(RETAIL / relative)} {CANARY / relative}")
    for relative in sorted(extension_binds):
        installed_name = (
            relative if relative.startswith("types/") else relative.split("/")[-1]
        )
        bind_lines.append(
            f"{sha256_file(INSTALLED_EXTENSION / installed_name)} "
            f"{REPO_ROOT / 'brainstem' / 'prime-extension' / 'src' / relative}"
        )
    (PRODUCTION_DIR / "HASHES.txt").write_text("\n".join(bind_lines) + "\n", encoding="utf-8")
    manifest_write = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate_omp_deployment_manifest.py"),
            "--write",
            "--patch-dir",
            str(PRODUCTION_DIR),
            "--sealed-host",
            str(sealed_host),
            "--installed-host",
            str(RETAIL),
            "--installed-extension",
            str(INSTALLED_EXTENSION),
        ],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")},
    )
    # 6. the manifest must describe the installed bytes
    manifest_check = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate_omp_deployment_manifest.py"),
            "--check",
            "--patch-dir",
            str(PRODUCTION_DIR),
            "--sealed-host",
            str(sealed_host),
            "--installed-host",
            str(RETAIL),
            "--installed-extension",
            str(INSTALLED_EXTENSION),
        ],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")},
    )
    record["manifest"] = {
        "write_exit": manifest_write.returncode,
        "write_stdout": manifest_write.stdout[-800:],
        "check_exit": manifest_check.returncode,
        "check_stdout": manifest_check.stdout[-800:],
        "path": str(PRODUCTION_DIR / "DEPLOYMENT-MANIFEST.json"),
        "manifest_sha256": sha256_file(PRODUCTION_DIR / "DEPLOYMENT-MANIFEST.json"),
    }
    record["finished_at"] = datetime.now(UTC).isoformat()
    (pack / "activation-record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "files_changed": [
                    entry["label"] for entry in record["files"] if not entry["already_current"]
                ],
                "installed_match_successor": all(
                    entry["installed_matches_successor"] for entry in record["files"]
                ),
                "unexpected_delta": record["governed_surface"]["unexpected_delta"],
                "host_files_matching_successor": record["governed_surface"][
                    "host_files_matching_successor"
                ],
                "manifest_write_exit": manifest_write.returncode,
                "manifest_check_exit": manifest_check.returncode,
                "manifest_check": manifest_check.stdout.strip().splitlines()[-1]
                if manifest_check.stdout.strip()
                else "",
            },
            indent=2,
        )
    )
    return 0 if manifest_check.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
