"""Generate the machine-readable OMP host deployment manifest.

One manifest drives installation, verification and rollback: the complete host
delta (bound + added + changed files with sealed, installed and rollback
hashes), the installed extension files, and the qualified launch entrypoint.
The activation card previously listed six host files while the installed delta
is thirteen (audit finding F-07); this manifest is the single source that
verification reads instead of a hand-maintained file list.

Read-only: it inspects the sealed canary package, the installed retail package
and the extension sources, and writes only the manifest (or prints it).

Usage:
    python scripts/generate_omp_deployment_manifest.py --check
    python scripts/generate_omp_deployment_manifest.py --write

    # A successor candidate keeps its own record without touching the sealed one:
    python scripts/generate_omp_deployment_manifest.py --write \
        --patch-dir docs/integrations/omp-host-patch-2026-09-19-successor \
        --installed-host <staged host package> \
        --installed-extension <staged extension root>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATCH_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19"
EXTENSION_SOURCES = REPO_ROOT / "brainstem" / "prime-extension"
HOST_VERSION = "omp/18.2.6"

_OMP_PACKAGES = Path.home() / ".bun/install/global/node_modules/@oh-my-pi"
DEFAULT_SEALED_PACKAGE = _OMP_PACKAGES / "pi-coding-agent-canary"
DEFAULT_INSTALLED_PACKAGE = _OMP_PACKAGES / "pi-coding-agent"
DEFAULT_INSTALLED_EXTENSION = Path.home() / ".omp/agent/extensions/second-brain"
BUN = Path.home() / ".bun/bin/bun.exe"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Target:
    """What a manifest describes: the patch record, and the bytes to compare.

    Defaults are the sealed candidate and the production installation. A
    successor candidate passes its own patch directory and the staged layout it
    was qualified in, so the sealed record and the live installation are never
    rewritten to describe work they did not do.
    """

    patch_dir: Path = DEFAULT_PATCH_DIR
    sealed_package: Path = DEFAULT_SEALED_PACKAGE
    installed_package: Path = DEFAULT_INSTALLED_PACKAGE
    installed_extension: Path = DEFAULT_INSTALLED_EXTENSION

    @property
    def manifest_path(self) -> Path:
        return self.patch_dir / "DEPLOYMENT-MANIFEST.json"


def bound_hashes(patch_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """HASHES.txt split into host binds and extension binds.

    Host entries are package-relative; extension entries are relative to the
    extension source root (the installer copies ``src/*.ts`` flat and
    ``types/*.d.ts`` into ``types/``). The sealed candidate writes absolute
    paths under the canary package and the extension sources; a successor writes
    absolute paths under its staged layout, marked by ``/host-source/`` and
    ``/extension/``.
    """
    host: dict[str, str] = {}
    extension: dict[str, str] = {}
    for line in (patch_dir / "HASHES.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        digest, absolute = parts
        path = absolute.replace("\\", "/")
        if "/pi-coding-agent-canary/" in path:
            host[path.split("/pi-coding-agent-canary/", 1)[1]] = digest
        elif "/host-source/" in path:
            host[path.split("/host-source/", 1)[1]] = digest
        elif "/prime-extension/src/" in path:
            extension[path.split("/prime-extension/src/", 1)[1]] = digest
        elif "/extension/" in path:
            extension[path.split("/extension/", 1)[1]] = digest
    return host, extension


def delta_path(patch_dir: Path, explicit: Path | None = None) -> Path:
    """The recorded activation delta (which host files were added or changed)."""
    import os

    if explicit is not None:
        return explicit
    candidates = [
        patch_dir / "host-delta-applied.json",
        REPO_ROOT.parent.parent / "outputs/reports/omp-activation-20260920/host-delta-applied.json",
        REPO_ROOT / "outputs/reports/omp-activation-20260920/host-delta-applied.json",
    ]
    home = os.environ.get("SECOND_BRAIN_HOME")
    if home:
        candidates.insert(
            1, Path(home) / "outputs/reports/omp-activation-20260920/host-delta-applied.json"
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "recording activation delta not found; pass --delta or copy host-delta-applied.json "
        f"into {patch_dir}"
    )


def host_files(target: Target, delta_file: Path) -> list[dict]:
    delta = json.loads(delta_file.read_text(encoding="utf-8"))
    bound, _extension_bound = bound_hashes(target.patch_dir)
    entries: list[dict] = []

    def entry(relative: str, role: str, rollback: dict) -> dict:
        sealed = target.sealed_package / relative
        installed = target.installed_package / relative
        item = {
            "path": relative,
            "role": role,
            "sealed_sha256": sha256_file(sealed) if sealed.is_file() else None,
            "installed_sha256": sha256_file(installed) if installed.is_file() else None,
            "rollback": rollback,
        }
        item["installed_matches_sealed"] = (
            item["sealed_sha256"] is not None and item["sealed_sha256"] == item["installed_sha256"]
        )
        expected = bound.get(relative)
        if expected is not None:
            item["bound_sha256"] = expected
            item["installed_matches_bound"] = expected == item["installed_sha256"]
        return item

    for relative, digest in sorted(bound.items()):
        entries.append(entry(relative, "bound", {"action": "restore", "sha256": digest}))
    for relative in sorted(delta.get("applied_added", [])):
        entries.append(entry(f"src/{relative}", "added", {"action": "delete"}))
    for relative in sorted(delta.get("applied_changed", [])):
        entries.append(entry(f"src/{relative}", "changed", {"action": "restore", "sha256": None}))
    return entries


def extension_files(target: Target) -> list[dict]:
    """Sealed extension sources mapped to their installed (flat) layout.

    The installer copies ``src/*.ts`` flat into the extension root and
    ``types/*.d.ts`` into ``types/``, so a nested sealed path and its installed
    name are not identical.
    """
    _host_bound, extension_bound = bound_hashes(target.patch_dir)
    sealed: dict[str, Path] = {}
    for path in sorted((EXTENSION_SOURCES / "src").rglob("*.ts")):
        if path.is_file():
            sealed[path.relative_to(EXTENSION_SOURCES / "src").as_posix()] = path
    for path in sorted((EXTENSION_SOURCES / "types").rglob("*.d.ts")):
        if path.is_file():
            sealed[f"types/{path.name}"] = path
    entries = []
    for relative, source in sorted(sealed.items()):
        digest = sha256_file(source)
        installed_name = relative if relative.startswith("types/") else relative.split("/")[-1]
        installed = target.installed_extension / installed_name
        item = {
            "path": installed_name,
            "sealed_source_path": (
                f"brainstem/prime-extension/{source.relative_to(EXTENSION_SOURCES).as_posix()}"
            ),
            "sealed_sha256": digest,
            "installed_sha256": sha256_file(installed) if installed.is_file() else None,
            "installed_matches_sealed": (installed.is_file() and sha256_file(installed) == digest),
        }
        expected = extension_bound.get(relative)
        if expected is not None:
            item["bound_sha256"] = expected
            item["installed_matches_bound"] = expected == item["installed_sha256"]
        entries.append(item)
    return entries


def build(target: Target, delta_file: Path) -> dict:
    host = host_files(target, delta_file)
    extension = extension_files(target)
    return {
        "schema": "second-brain.omp-host-deployment-manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Single machine-readable deployment record for the patched OMP host and the Second "
            "Brain extension: every file that must match, its rollback action, and the qualified "
            "launch entrypoint. Verification (scripts/run-omp-patched.ps1) and the activation card "
            "read this manifest instead of a hand-maintained file list."
        ),
        "host": {
            "name": "OMP",
            "version": HOST_VERSION,
            "sealed_package": str(target.sealed_package),
            "installed_package": str(target.installed_package),
            "entrypoint": "src/cli.ts",
            "bundled_entrypoint": "dist/cli.js",
            "bundled_entrypoint_note": (
                "The package's own bin maps `omp` to dist/cli.js, a bundle that does not carry the "
                "worker-cleanup patch. The qualified route is the source entrypoint below, started "
                "by scripts/run-omp-patched.ps1."
            ),
            "file_count": len(host),
            "files": host,
        },
        "extension": {
            "installed_root": str(target.installed_extension),
            "sealed_sources": str(EXTENSION_SOURCES / "src"),
            "file_count": len(extension),
            "files": extension,
        },
        "launcher": {
            "script": "scripts/run-omp-patched.ps1",
            "bun": str(BUN),
            "command": "bun <installed_package>/src/cli.ts <args>",
            "behaviour": (
                "Verify every host and extension hash against this manifest; refuse on any "
                "mismatch, then exec the qualified source entrypoint. Never installs or repairs."
            ),
        },
        "known_limitations": [
            "Type checking this exact candidate requires the pinned v18.2.6 workspace toolchain "
            "(check:types).",
            "Production-path lifecycle behaviour on the launcher (worker spawn, settlement, "
            "cancellation) is not covered by the manifest; it remains a separate gate.",
        ],
    }


def summary(manifest: dict) -> dict:
    host = manifest["host"]["files"]
    extension = manifest["extension"]["files"]
    return {
        "host_files": len(host),
        "host_roles": {
            role: sum(1 for item in host if item["role"] == role)
            for role in ("bound", "added", "changed")
        },
        "host_installed_matches_sealed": sum(
            1 for item in host if item["installed_matches_sealed"]
        ),
        "host_installed_matches_bound": sum(
            1 for item in host if item.get("installed_matches_bound")
        ),
        "extension_files": len(extension),
        "extension_installed_matches_sealed": sum(
            1 for item in extension if item["installed_matches_sealed"]
        ),
    }


def manifest_is_current(stored: dict, live: dict) -> bool:
    """Stored and live manifests describe the same installed bytes."""
    stored_files = {item["path"]: item["installed_sha256"] for item in stored["host"]["files"]}
    live_files = {item["path"]: item["installed_sha256"] for item in live["host"]["files"]}
    stored_ext = {item["path"]: item["installed_sha256"] for item in stored["extension"]["files"]}
    live_ext = {item["path"]: item["installed_sha256"] for item in live["extension"]["files"]}
    return stored_files == live_files and stored_ext == live_ext


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the manifest file")
    parser.add_argument("--check", action="store_true", help="verify the manifest is current")
    parser.add_argument("--delta", type=Path, default=None, help="recorded activation delta JSON")
    parser.add_argument(
        "--patch-dir",
        type=Path,
        default=DEFAULT_PATCH_DIR,
        help="patch record directory holding HASHES.txt (default: the sealed candidate)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="manifest path (default: <patch-dir>/DEPLOYMENT-MANIFEST.json)",
    )
    parser.add_argument(
        "--installed-host",
        type=Path,
        default=DEFAULT_INSTALLED_PACKAGE,
        help="host package the manifest compares against (default: the production install)",
    )
    parser.add_argument(
        "--installed-extension",
        type=Path,
        default=DEFAULT_INSTALLED_EXTENSION,
        help="extension root the manifest compares against (default: the production install)",
    )
    parser.add_argument(
        "--sealed-host",
        type=Path,
        default=DEFAULT_SEALED_PACKAGE,
        help=(
            "directory holding the intended host bytes (default: the sealed canary package); a "
            "successor points this at its staged intended-bytes tree"
        ),
    )
    args = parser.parse_args()

    target = Target(
        patch_dir=args.patch_dir,
        sealed_package=args.sealed_host,
        installed_package=args.installed_host,
        installed_extension=args.installed_extension,
    )
    manifest = build(target, delta_path(target.patch_dir, args.delta))
    rendered = json.dumps(manifest, indent=2) + "\n"
    manifest_path = args.out or target.manifest_path
    if args.write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(rendered, encoding="utf-8")
        print(f"wrote {manifest_path}")
    stats = summary(manifest)
    print(json.dumps(stats, indent=2))

    inconsistent = (
        manifest["host"]["file_count"] != stats["host_installed_matches_sealed"]
        or manifest["extension"]["file_count"] != stats["extension_installed_matches_sealed"]
    )
    if args.check:
        if not manifest_path.is_file():
            print("NO MANIFEST: run with --write")
            return 2
        stored = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest_is_current(stored, manifest) or inconsistent:
            print("MANIFEST STALE: regenerate with --write")
            return 1
        print("MANIFEST CURRENT: installed bytes match the recorded deployment")
        return 0
    return 1 if inconsistent else 0


if __name__ == "__main__":
    sys.exit(main())
