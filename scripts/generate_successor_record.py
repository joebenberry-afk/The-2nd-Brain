"""Record and seal an OMP successor candidate without touching the sealed one.

The predecessor pack (`docs/integrations/omp-host-patch-2026-09-19/`) is sealed
history: its files, hashes and runs stay exactly as executed. A repaired
successor is a new, separately sealed subject with explicit lineage, so no run
is ever re-bound to bytes it did not execute.

Two passes, because the differences need human reasons:

    # 1. see exactly what differs from the predecessor
    python scripts/generate_successor_record.py --report

    # 2. write the record, using REASONS.json for per-path explanations
    python scripts/generate_successor_record.py --write \
        --staged-root outputs/qualification/<stamp>/staged

`--report` writes nothing. `--write` writes SUCCESSOR-RECORD.json, HASHES.txt
and RUN-IDENTITIES.json into the successor directory. `--seal` additionally
writes SHIPPING-CANDIDATE-MANIFEST.json and APPROVED-SUCCESSOR.json, which hash
the record's own files (and the campaign index when given), binding the
approved subject for the tests that guard against drift.

Any changed path without a reason in REASONS.json is recorded as `unresolved`
and blocks `--seal`: an unexplained difference is not admitted into a baseline.
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
SRC_ROOT = REPO_ROOT / "src"

PREDECESSOR_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19"
SUCCESSOR_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19-successor"
EXTENSION_SOURCES = REPO_ROOT / "brainstem" / "prime-extension"
OMP_PACKAGES = Path.home() / ".bun/install/global/node_modules/@oh-my-pi"
CANARY = OMP_PACKAGES / "pi-coding-agent-canary"
RETAIL = OMP_PACKAGES / "pi-coding-agent"
INSTALLED_EXTENSION = Path.home() / ".omp/agent/extensions/second-brain"
LIVE_USER_CONFIG = Path.home() / ".omp/agent/config.yml"
RECORD_FILE = "SUCCESSOR-RECORD.json"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_lf(path: Path) -> str:
    """Hash LF-normalized bytes: git blobs are LF, the worktree is CRLF."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def fingerprints() -> tuple[str | None, str | None]:
    """(source tree, extension) fingerprints from the Brain's own identity code."""
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from second_brain import build_identity

    return (
        build_identity.source_tree_fingerprint(REPO_ROOT),
        build_identity.adapter_build_fingerprint(REPO_ROOT),
    )


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def inventory(root: Path) -> dict[str, str]:
    """Every file under a staged root, relative path -> sha256."""
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): sha256_file(path) or ""
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def extension_sources() -> dict[str, str]:
    """Repository extension sources in the installed (flat) layout."""
    entries: dict[str, str] = {}
    for path in sorted((EXTENSION_SOURCES / "src").rglob("*.ts")):
        if path.is_file():
            relative = path.relative_to(EXTENSION_SOURCES / "src").as_posix()
            entries[relative] = sha256_file(path) or ""
    for path in sorted((EXTENSION_SOURCES / "types").rglob("*.d.ts")):
        if path.is_file():
            entries[f"types/{path.name}"] = sha256_file(path) or ""
    return entries


def tracked_subject_paths() -> dict[str, str]:
    """Candidate paths whose bytes define the repaired subject.

    Hashes are taken over LF-normalized bytes: git blobs are LF, while the
    worktree is checked out CRLF, and a line-ending difference is not a
    candidate difference.
    """
    paths: dict[str, str] = {}
    for relative in (
        "src/second_brain/cli.py",
        "src/second_brain/promotion.py",
        "src/second_brain/backup.py",
        "src/second_brain/doctor.py",
        "brainstem/prime-extension/src/index.ts",
        "brainstem/prime-extension/src/recall-gate.ts",
        "scripts/run-omp-patched.ps1",
        "scripts/generate_omp_deployment_manifest.py",
        "scripts/run_host_settlement_tests.py",
        "scripts/stage_omp_successor.py",
        "scripts/generate_successor_record.py",
        "docs/integrations/omp-host-patch-2026-09-19/host/agent-session.ts",
        "docs/integrations/omp-host-patch-2026-09-19/host/attempt-settlement.ts",
    ):
        path = REPO_ROOT / relative
        if path.is_file():
            paths[relative] = sha256_lf(path)
    return paths


def predecessor_subject_paths() -> dict[str, str]:
    """The same paths as they were in the predecessor candidate (commit abf2ab9)."""
    base = "abf2ab9"
    paths: dict[str, str] = {}
    for relative in tracked_subject_paths():
        blob = subprocess.run(
            ["git", "show", f"{base}:{relative}"], cwd=REPO_ROOT, capture_output=True
        )
        if blob.returncode == 0:
            paths[relative] = hashlib.sha256(blob.stdout).hexdigest()
    return paths


def differences(reasons: dict[str, dict]) -> list[dict]:
    """Path-by-path differences against the predecessor candidate."""
    rows: list[dict] = []
    successor = tracked_subject_paths()
    for relative, digest in successor.items():
        recorded = reasons.get(relative, {})
        before = predecessor_subject_paths().get(relative)
        if before is None:
            kind = "added"
        elif before != digest:
            kind = "changed"
        else:
            kind = "unchanged"
        if kind == "unchanged" and not recorded:
            continue
        entry = {
            "path": relative,
            "kind": kind,
            "predecessor_sha256": before,
            "successor_sha256": digest,
            "reason": recorded.get("reason"),
            "evidence": recorded.get("evidence"),
            "status": "explained" if recorded.get("reason") else "unresolved",
        }
        rows.append(entry)
    return rows


def installed_extension_state() -> dict:
    """How the production installation relates to the repaired sources."""
    sources = extension_sources()
    mismatches = []
    for relative, digest in sorted(sources.items()):
        installed_name = relative if relative.startswith("types/") else relative.split("/")[-1]
        installed = sha256_file(INSTALLED_EXTENSION / installed_name)
        if installed != digest:
            mismatches.append(
                {
                    "path": installed_name,
                    "source_sha256": digest,
                    "installed_sha256": installed,
                }
            )
    return {
        "root": str(INSTALLED_EXTENSION),
        "file_count": len(sources),
        "installed_matches_source": len(sources) - len(mismatches),
        "mismatches": mismatches,
    }


def host_package_state() -> dict:
    """Sealed canary versus production retail for the deployed host delta."""
    delta_file = PREDECESSOR_DIR / "host-delta-applied.json"
    if not delta_file.is_file():
        delta_file = (
            REPO_ROOT.parent.parent
            / "outputs/reports/omp-activation-20260920/host-delta-applied.json"
        )
    delta = json.loads(delta_file.read_text(encoding="utf-8")) if delta_file.is_file() else {}
    rows = []
    for relative in sorted(
        f"src/{name}"
        for name in (delta.get("applied_added", []) + delta.get("applied_changed", []))
    ):
        sealed = sha256_file(CANARY / relative)
        installed = sha256_file(RETAIL / relative)
        rows.append(
            {
                "path": relative,
                "canary_sha256": sealed,
                "retail_sha256": installed,
                "matches": sealed is not None and sealed == installed,
            }
        )
    return {
        "canary": str(CANARY),
        "retail": str(RETAIL),
        "delta_file": str(delta_file),
        "files": rows,
    }


def config_state() -> dict:
    """The default-profile user config, as observed and as recorded before."""
    recorded_pre = None
    inventory = json.loads((PREDECESSOR_DIR / "RUN-IDENTITIES.json").read_text(encoding="utf-8"))
    for entry in inventory["identities"]:
        if entry["role"] == "configuration-default-profile-user":
            recorded_pre = entry["sha256"]
    return {
        "path": str(LIVE_USER_CONFIG),
        "predecessor_recorded_sha256": recorded_pre,
        "live_sha256": sha256_file(LIVE_USER_CONFIG),
    }


def successor_binds(
    staged_root: Path, staged_host_package: Path
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(host, extension) binds for the successor HASHES.txt.

    The host bind set is the predecessor's bound files plus the recorded
    activation delta, hashed from the staged bytes; the extension bind set is
    every staged extension file. A repaired file therefore binds its repaired
    bytes, and the predecessor's own HASHES.txt is never rewritten.
    """
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import generate_omp_deployment_manifest as generator

    host_binds, _extension_binds = generator.bound_hashes(PREDECESSOR_DIR)
    delta = json.loads(generator.delta_path(PREDECESSOR_DIR).read_text(encoding="utf-8"))
    for name in delta.get("applied_added", []) + delta.get("applied_changed", []):
        host_binds.setdefault(f"src/{name}", "")
    host_rows = []
    for relative in sorted(host_binds):
        digest = sha256_file(Path(staged_host_package) / relative)
        intended = sha256_file(staged_root / "host-source" / relative)
        if intended is not None and intended != digest:
            raise SystemExit(f"stage mismatch for {relative}: host and intended bytes differ")
        host_rows.append((relative, digest or ""))
    extension_root = staged_root / "extension"
    extension_rows = [
        (path.relative_to(extension_root).as_posix(), sha256_file(path) or "")
        for path in sorted(extension_root.rglob("*"))
        if path.is_file()
    ]
    return host_rows, extension_rows


def staged_inventory(staged_root: Path) -> dict:
    stage_manifest = staged_root / "STAGE-MANIFEST.json"
    stage = (
        json.loads(stage_manifest.read_text(encoding="utf-8")) if stage_manifest.is_file() else {}
    )
    return {
        "root": str(staged_root),
        "host_package": stage.get("host", {}).get("package"),
        "stage_manifest_sha256": sha256_file(stage_manifest),
        "host_files": sum(1 for path in (staged_root / "host").rglob("*") if path.is_file()),
        "extension_files": sum(
            1 for path in (staged_root / "extension").rglob("*") if path.is_file()
        ),
        "overlays": stage.get("host", {}).get("overlays", []),
        "settlement": stage.get("host", {}).get("attempt_settlement", {}),
        "intended_tree": stage.get("host", {}).get("intended_tree"),
        "user_root": stage.get("user_root", {}),
        "runtime_cache": stage.get("runtime_cache", []),
        "global_dependencies": stage.get("global_dependencies", []),
    }


def build_record(args: argparse.Namespace) -> dict:
    reasons = json.loads((args.successor_dir / "REASONS.json").read_text(encoding="utf-8"))
    staged = staged_inventory(args.staged_root)
    record = {
        "schema": "second-brain.omp-successor-candidate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Successor candidate record for the repaired OMP baseline. The predecessor pack is "
            "sealed history and is not modified; this record, its own HASHES.txt, "
            "RUN-IDENTITIES.json and shipping seal describe the repaired subject and the staged "
            "layout it was qualified in."
        ),
        "authorization": args.authorization,
        "lineage": {
            "predecessor": {
                "dir": "docs/integrations/omp-host-patch-2026-09-19",
                "shipping_candidate_manifest_sha256": sha256_file(
                    PREDECESSOR_DIR / "SHIPPING-CANDIDATE-MANIFEST.json"
                ),
                "run_identities_sha256": sha256_file(PREDECESSOR_DIR / "RUN-IDENTITIES.json"),
                "hashes_file_sha256": sha256_file(PREDECESSOR_DIR / "HASHES.txt"),
                "sealed_commit": "a2e49e4",
                "functional_commit": "40d2218",
                "candidate_head": "abf2ab9",
                "status": "preserved byte-identical; its runs remain what executed",
            },
            "successor": {
                "worktree": str(REPO_ROOT),
                "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "commit": git("rev-parse", "HEAD"),
                "source_tree_sha256": fingerprints()[0],
                "extension_fingerprint": fingerprints()[1],
            },
        },
        "differences": differences(reasons),
        "production_state": {
            "extension": installed_extension_state(),
            "host_delta": host_package_state(),
            "user_config": config_state(),
            "configuration_contract": configuration_contract(args.staged_root),
            "user_provider_reconciliation": configuration_reconciliation(),
        },
        "staged_layout": {
            "root": staged["root"],
            "host_package": staged["host_package"],
            "intended_tree": staged["intended_tree"],
            "stage_manifest_sha256": staged["stage_manifest_sha256"],
            "host_files": staged["host_files"],
            "extension_files": staged["extension_files"],
            "overlays": staged["overlays"],
            "settlement": staged["settlement"],
            "runtime_cache": staged["runtime_cache"],
            "global_dependencies": staged["global_dependencies"],
            "reproduce": (
                "python scripts/stage_omp_successor.py --root <root>: copy the sealed canary "
                "package to <root>/host, overlay the eight repository host-patch sources at their "
                "target paths (writing the intended bytes to <root>/host-source), and copy "
                "brainstem/prime-extension/src/*.ts flat plus types/*.d.ts into <root>/extension."
            ),
        },
        "negative_control": {
            "subject": (
                "docs/integrations/omp-host-patch-2026-09-19/tests/"
                "attempt-settlement-outcome.test.ts"
            ),
            "sealed_host_module": (
                "docs/integrations/omp-host-patch-2026-09-19/host/agent-session.ts"
            ),
            "runner": "scripts/run_host_settlement_tests.py",
            "expected": "sealed host fails (exit 1) and candidate passes (exit 0)",
        },
        "checks": campaign_checks(args.campaign_index),
        "explicit_non_claims": [
            "The predecessor pack, its seals and its runs are unchanged.",
            "No production installation, configuration, database, lease or host replacement.",
            "Universal qualification stays HOLD; economics stays INSUFFICIENT.",
        ],
    }
    return record


def write_record(record: dict, successor_dir: Path) -> None:
    successor_dir.mkdir(parents=True, exist_ok=True)
    (successor_dir / RECORD_FILE).write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    staged_root = Path(record["staged_layout"]["root"])
    host_rows, extension_rows = successor_binds(
        staged_root, Path(record["staged_layout"]["host_package"])
    )
    staged_host = record["staged_layout"]["intended_tree"].replace("\\", "/")
    staged_extension = (staged_root / "extension").as_posix()
    lines = [f"{digest} {staged_host}/{relative}" for relative, digest in host_rows]
    lines += [f"{digest} {staged_extension}/{relative}" for relative, digest in extension_rows]
    (successor_dir / "HASHES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


UNATTRIBUTED_LIVE_INPUTS = {
    r"C:\Users\assas\.codex\config.toml": (
        "live change after the predecessor inventory (file mtime 2026-09-20 07:10); the "
        "predecessor bytes were not preserved, so the change is recorded, not interpreted"
    ),
}


def reconcile_contract(contract: dict) -> tuple[dict, list[dict]]:
    """Bind live provider-config hashes, with lineage for anything that moved.

    These entries exist so that no unrecorded provider overlay can influence a
    bound run. A live change is recorded explicitly (previous hash, attribution)
    instead of being silently adopted, and the reconciliation list is part of the
    record that gets sealed.
    """
    reconciliation: list[dict] = []
    reconciled = json.loads(json.dumps(contract))
    for item in reconciled.get("user_provider_files", []):
        path = Path(str(item.get("path")))
        live = sha256_file(path)
        recorded = item.get("sha256")
        if item.get("expects") == "absent" or live is None:
            reconciliation.append(
                {
                    "path": str(path),
                    "expects": item.get("expects", "bound"),
                    "recorded_sha256": recorded,
                    "live_sha256": live,
                    "match": (recorded == live),
                    "attribution": "absent as expected" if live is None else None,
                }
            )
            continue
        attribution = None
        if recorded is not None and recorded != live:
            attribution = UNATTRIBUTED_LIVE_INPUTS.get(str(path), "unattributed live change")
        item["sha256"] = live
        if recorded is not None and recorded != live:
            item["predecessor_sha256"] = recorded
        if attribution:
            item["attribution"] = attribution
        reconciliation.append(
            {
                "path": str(path),
                "expects": "bound",
                "recorded_sha256": recorded,
                "live_sha256": live,
                "match": recorded == live,
                "attribution": attribution,
            }
        )
    return reconciled, reconciliation


def campaign_checks(index_path: Path | None) -> dict:
    """Campaign results recorded into the candidate record, when available."""
    if index_path is None or not index_path.is_file():
        return {}
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        "campaign_index": {"path": str(index_path), "sha256": sha256_file(index_path)},
        "steps": index.get("steps", {}),
        "staged_layout": index.get("staged_layout", {}),
    }


def configuration_contract(staged_root: Path) -> dict:
    """The predecessor's contract, rebound to the staged user root.

    The run must not write the real profile store, so the child's user root is
    relocated into the stage and the contract follows it: home, profile and
    default-profile config all resolve there. Provider files are additionally
    required to be absent under the staged root - the strongest form of the guard
    the predecessor expressed by binding them - while the real user-level paths
    stay recorded (read-only) exactly as the predecessor bound them.
    """
    predecessor = json.loads((PREDECESSOR_DIR / "RUN-IDENTITIES.json").read_text(encoding="utf-8"))
    contract, _reconciliation = reconcile_contract(predecessor.get("configuration_contract", {}))
    stage = json.loads((staged_root / "STAGE-MANIFEST.json").read_text(encoding="utf-8"))
    user_root = Path(stage["user_root"]["root"])
    contract["home_dir"] = str(user_root)
    contract["config_dir_name"] = ".omp"
    contract["profile_dir"] = str(user_root / ".omp" / "profiles" / str(contract["profile"]))
    contract["profile_agent_dir"] = str(Path(contract["profile_dir"]) / "agent")
    contract["default_profile_user_config"] = stage["user_root"]["default_profile_user_config"]
    provider_files = list(contract.get("user_provider_files", []))
    for item in list(provider_files):
        staged = user_root / Path(str(item["path"])).name
        provider_files.append(
            {
                "path": str(staged),
                "expects": "absent",
                "note": "staged user root: no provider file may exist here",
            }
        )
    contract["user_provider_files"] = provider_files
    contract["env_files_must_be_absent"] = [
        *contract.get("env_files_must_be_absent", []),
        str(user_root / ".env"),
        str(user_root / ".bunfig.toml"),
        str(user_root / ".omp" / ".env"),
    ]
    return contract


def configuration_reconciliation() -> list[dict]:
    predecessor = json.loads((PREDECESSOR_DIR / "RUN-IDENTITIES.json").read_text(encoding="utf-8"))
    _contract, reconciliation = reconcile_contract(predecessor.get("configuration_contract", {}))
    return reconciliation


def write_run_identities(record: dict, successor_dir: Path) -> dict:
    """Successor runtime inventory: predecessor roles, repaired values."""
    predecessor = json.loads((PREDECESSOR_DIR / "RUN-IDENTITIES.json").read_text(encoding="utf-8"))
    staged_root = Path(record["staged_layout"]["root"])
    by_role: dict[str, dict] = {}
    for entry in predecessor["identities"]:
        role = entry["role"]
        path = Path(entry["path"])
        if role == "adapter-index":
            relative = str(path).split("prime-extension", 1)[1].lstrip("\\/").replace("\\", "/")
            name = relative.split("/")[-1]
            by_role[role] = {
                "role": role,
                "path": str(staged_root / "extension" / name),
                "sha256": sha256_file(staged_root / "extension" / name),
                "note": "repaired by F-08; the staged extension carries these bytes",
            }
        elif role == "brain-cli":
            by_role[role] = {
                "role": role,
                "path": str(REPO_ROOT / "src" / "second_brain" / "cli.py"),
                "sha256": sha256_file(REPO_ROOT / "src" / "second_brain" / "cli.py"),
                "note": "repaired by F-01..F-05",
            }
        elif role == "configuration-default-profile-user":
            staged_config = Path(
                record["production_state"]["configuration_contract"]["default_profile_user_config"]
            )
            by_role[role] = {
                "role": role,
                "path": str(staged_config),
                "sha256": sha256_file(staged_config),
                "note": (
                    "staged copy of the default-profile config: the run's user root is relocated "
                    "so no production profile state is written. The live file changed after the "
                    "predecessor inventory (task model preference; codex provider config); both "
                    "values stay recorded in the activation pack and in this record."
                ),
            }
        elif path.parts and str(path).startswith(str(CANARY)):
            relative = str(path).split("pi-coding-agent-canary", 1)[1].lstrip("\\/")
            relative = relative.replace("\\", "/")
            staged_host_package = Path(record["staged_layout"]["host_package"])
            by_role[role] = {
                "role": role,
                "path": str(staged_host_package / relative),
                "sha256": sha256_file(staged_host_package / relative),
                "note": "staged host copy of the sealed canary file",
            }
        elif "prime-extension" in str(path):
            relative = str(path).split("prime-extension", 1)[1].lstrip("\\/").replace("\\", "/")
            name = relative if relative.startswith("types/") else relative.split("/")[-1]
            by_role[role] = {
                "role": role,
                "path": str(staged_root / "extension" / name),
                "sha256": sha256_file(staged_root / "extension" / name),
                "note": "staged extension copy of the repaired source",
            }
        else:
            current = sha256_file(path)
            by_role[role] = {
                "role": role,
                "path": str(path),
                "sha256": current if current is not None else entry["sha256"],
                "note": "unchanged from the predecessor",
            }
    staged_extension = staged_root / "extension"
    staged_host = Path(record["staged_layout"]["host_package"])

    def staged_host_role(role: str, relative: str, note: str) -> dict:
        return {
            "role": role,
            "path": str(staged_host / relative),
            "sha256": sha256_file(staged_host / relative),
            "note": note,
        }

    additions = [
        staged_host_role(
            "host-attempt-settlement",
            "src/task/attempt-settlement.ts",
            "F-06 repair: the sealed settlement module is replaced by the repaired bytes",
        ),
        staged_host_role(
            "host-sdk",
            "src/sdk.ts",
            "activation delta file; absent from the predecessor inventory",
        ),
        staged_host_role(
            "host-task-executor",
            "src/task/executor.ts",
            "activation delta file; absent from the predecessor inventory",
        ),
        staged_host_role(
            "host-task-index",
            "src/task/index.ts",
            "activation delta file; absent from the predecessor inventory",
        ),
        {
            "role": "extension-recall-gate",
            "path": str(staged_extension / "recall-gate.ts"),
            "sha256": sha256_file(staged_extension / "recall-gate.ts"),
            "note": "F-08 repair; production still carries the pre-repair bytes",
        },
        {
            "role": "launcher-successor",
            "path": str(REPO_ROOT / "scripts" / "run-omp-patched.ps1"),
            "sha256": sha256_file(REPO_ROOT / "scripts" / "run-omp-patched.ps1"),
            "note": "manifest override added so a staged layout can be verified and launched",
        },
        {
            "role": "deployment-manifest-generator",
            "path": str(REPO_ROOT / "scripts" / "generate_omp_deployment_manifest.py"),
            "sha256": sha256_file(REPO_ROOT / "scripts" / "generate_omp_deployment_manifest.py"),
            "note": (
                "parameterized so a successor records its own deployment without touching the seal"
            ),
        },
    ]
    identities = list(by_role.values()) + additions
    required = sorted({entry["role"] for entry in identities})
    contract = record["production_state"]["configuration_contract"]
    reconciliation = record["production_state"]["user_provider_reconciliation"]
    document = {
        "schema": predecessor["schema"],
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Successor runtime inventory. Every path resolves to the staged qualification layout "
            "or to a repaired repository file; the predecessor inventory is unchanged and still "
            "describes the accepted campaign."
        ),
        "lineage": {
            "predecessor_file": "docs/integrations/omp-host-patch-2026-09-19/RUN-IDENTITIES.json",
            "predecessor_sha256": sha256_file(PREDECESSOR_DIR / "RUN-IDENTITIES.json"),
        },
        "required_roles": required,
        "configuration_contract": contract,
        "configuration_reconciliation": reconciliation,
        "identities": identities,
    }
    (successor_dir / "RUN-IDENTITIES.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return document


def write_candidate_identity(record: dict, successor_dir: Path) -> dict:
    """Per-file identity of the committed candidate (repo-relative, LF-normalized).

    The staged deployment binds disposable paths; this file binds the bytes that
    live in the repository, so a drift check can validate the candidate without
    depending on a staging directory that may be gone.
    """
    files = tracked_subject_paths()
    for relative, _digest in extension_sources().items():
        if relative.startswith("types/"):
            repo_relative = f"brainstem/prime-extension/types/{relative.split('/')[-1]}"
        else:
            repo_relative = f"brainstem/prime-extension/src/{relative}"
        path = REPO_ROOT / repo_relative
        if path.is_file():
            files.setdefault(repo_relative, sha256_lf(path))
    document = {
        "schema": "second-brain.omp-successor-candidate-identity.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "subject": record["lineage"]["successor"],
        "fingerprints": {
            "source_tree_sha256": record["lineage"]["successor"]["source_tree_sha256"],
            "extension_fingerprint": record["lineage"]["successor"]["extension_fingerprint"],
        },
        "files": dict(sorted(files.items())),
        "note": (
            "Hashes are LF-normalized so a line-ending checkout difference is not a candidate "
            "difference. The staged deployment hashes live in HASHES.txt and RUN-IDENTITIES.json."
        ),
    }
    (successor_dir / "CANDIDATE-IDENTITY.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return document


def seal(
    record: dict,
    successor_dir: Path,
    campaign_index: Path | None,
    review: Path | None,
) -> dict:
    unresolved = [row["path"] for row in record["differences"] if row["status"] != "explained"]
    if unresolved:
        raise SystemExit(f"refusing to seal: unexplained differences: {unresolved}")
    files = {}
    for name in (
        RECORD_FILE,
        "HASHES.txt",
        "RUN-IDENTITIES.json",
        "REASONS.json",
        "CANDIDATE-IDENTITY.json",
    ):
        path = successor_dir / name
        if path.is_file():
            files[name] = sha256_file(path)
    evidence = {}
    if campaign_index is not None and campaign_index.is_file():
        evidence["campaign_index"] = {
            "path": str(campaign_index),
            "sha256": sha256_file(campaign_index),
        }
    if review is not None and review.is_file():
        evidence["review_verdict"] = {"path": str(review), "sha256": sha256_file(review)}
    manifest = {
        "schema": "second-brain.omp-successor-shipping-candidate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Seal for the repaired successor candidate: the record files that describe it, the "
            "staged layout it was qualified in, and the campaign evidence it produced."
        ),
        "subject": record["lineage"]["successor"],
        "predecessor": record["lineage"]["predecessor"],
        "record_files": files,
        "evidence": evidence,
        "checks": record.get("checks", {}),
        "explicit_non_claims": record["explicit_non_claims"],
    }
    (successor_dir / "SHIPPING-CANDIDATE-MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    approval = {
        "schema": "second-brain.omp-approved-successor.v1",
        "approved_at": datetime.now(UTC).isoformat(),
        "successor_dir": "docs/integrations/omp-host-patch-2026-09-19-successor",
        "record": RECORD_FILE,
        "record_sha256": files.get(RECORD_FILE),
        "shipping_candidate_manifest_sha256": sha256_file(
            successor_dir / "SHIPPING-CANDIDATE-MANIFEST.json"
        ),
        "identities_file_sha256": files.get("RUN-IDENTITIES.json"),
        "hashes_file_sha256": files.get("HASHES.txt"),
        "predecessor_dir": "docs/integrations/omp-host-patch-2026-09-19",
        "rule": (
            "Identity checks validate this successor. The predecessor remains sealed history and "
            "is never re-validated against live bytes."
        ),
    }
    (successor_dir / "APPROVED-SUCCESSOR.json").write_text(
        json.dumps(approval, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return approval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print the differences only")
    parser.add_argument("--write", action="store_true", help="write the record files")
    parser.add_argument("--seal", action="store_true", help="write the seal and approval pointer")
    parser.add_argument("--staged-root", type=Path, default=None)
    parser.add_argument("--successor-dir", type=Path, default=SUCCESSOR_DIR)
    parser.add_argument("--campaign-index", type=Path, default=None)
    parser.add_argument("--review", type=Path, default=None)
    parser.add_argument(
        "--authorization", default="user mandate 2026-09-20: bounded successor re-issue campaign"
    )
    args = parser.parse_args()

    if args.report:
        reasons_path = args.successor_dir / "REASONS.json"
        if reasons_path.is_file():
            reasons = json.loads(reasons_path.read_text(encoding="utf-8"))
        else:
            reasons = {}
        for row in differences(reasons):
            print(f"{row['kind']:9} {row['status']:10} {row['path']}")
            if row["reason"]:
                print(f"          reason: {row['reason']}")
        return 0

    if not args.staged_root:
        raise SystemExit("--staged-root is required with --write/--seal")
    record = build_record(args)
    if args.write or args.seal:
        write_record(record, args.successor_dir)
        write_run_identities(record, args.successor_dir)
        write_candidate_identity(record, args.successor_dir)
        print(
            f"wrote {args.successor_dir / RECORD_FILE}, RUN-IDENTITIES.json and "
            "CANDIDATE-IDENTITY.json"
        )
    if args.seal:
        approval = seal(record, args.successor_dir, args.campaign_index, args.review)
        print(json.dumps(approval, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
