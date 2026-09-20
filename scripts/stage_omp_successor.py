"""Stage the repaired OMP successor in a disposable layout.

Production carries the sealed settlement module (audit finding F-06, repaired in
the repository only), so the repaired candidate is qualified in an isolated
stage that uses the intended deployment layout:

    <root>/host        the sealed canary package, overlaid with the eight
                       repository host-patch sources at their target paths
    <root>/extension    the repository extension sources in the installed flat
                       layout (src/*.ts flat, types/*.d.ts)

Nothing here touches production: the stage is a copy, and the production
installation, configuration and Brain home are never modified. Run it, verify
the printed summary, then point a deployment manifest and the launcher at the
stage (scripts/generate_omp_deployment_manifest.py --installed-host/--installed-extension,
scripts/run-omp-patched.ps1 -ManifestPath).

    python scripts/stage_omp_successor.py --root %TEMP%/omp-successor
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19"
HOST_SOURCES = PATCH_DIR / "host"
LIVE_USER_CONFIG = Path.home() / ".omp/agent/config.yml"
EXTENSION_SOURCES = REPO_ROOT / "brainstem" / "prime-extension"
SEALED_PACKAGE = Path.home() / ".bun/install/global/node_modules/@oh-my-pi/pi-coding-agent-canary"

# The deployed host delta as recorded at activation, extended with the files the
# patch sources replace. Keys are patch-source names, values are host-relative
# target paths (src/ is prepended when staging).
HOST_TARGETS = {
    "job-manager.ts": "async/job-manager.ts",
    "agent-session.ts": "session/agent-session.ts",
    "isolation-runner.ts": "task/isolation-runner.ts",
    "worktree.ts": "task/worktree.ts",
    "main.ts": "main.ts",
    "runner.ts": "extensibility/extensions/runner.ts",
    "types.ts": "extensibility/extensions/types.ts",
    "attempt-settlement.ts": "task/attempt-settlement.ts",
}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def intended_targets() -> dict[str, Path]:
    """host-relative path -> source of the intended bytes.

    The intended tree covers every host file the successor binds: the eight
    repository patch sources (which carry the repairs) plus the recorded
    activation delta and predecessor binds that have no repository source, whose
    intended bytes are the sealed package's own.
    """
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import generate_omp_deployment_manifest as generator

    host_binds, _extension = generator.bound_hashes(PATCH_DIR)
    delta = json.loads(generator.delta_path(PATCH_DIR).read_text(encoding="utf-8"))
    for name in delta.get("applied_added", []) + delta.get("applied_changed", []):
        host_binds.setdefault(f"src/{name}", "")
    patch_sources = {f"src/{target}": HOST_SOURCES / name for name, target in HOST_TARGETS.items()}
    targets: dict[str, Path] = {}
    for relative in sorted(host_binds):
        source = patch_sources.get(relative, SEALED_PACKAGE / relative)
        if not source.is_file():
            raise SystemExit(f"no source for bound host file {relative}")
        targets[relative] = source
    return targets


GLOBAL_OH_MY_PI = Path.home() / ".bun/install/global/node_modules/@oh-my-pi"
CANARY_PACKAGE_NAME = "pi-coding-agent-canary"


def stage_host(root: Path) -> tuple[list[dict], Path]:
    """Stage the host package inside a global-install node_modules tree.

    bun resolves ``@oh-my-pi/*`` by walking up from the entrypoint, so the host
    package has to live at ``<global>/node_modules/@oh-my-pi/<package>`` with its
    sibling runtime packages next to it - the shape the production install has.
    """
    global_root = root / "global" / "node_modules" / "@oh-my-pi"
    if (root / "global").exists():
        shutil.rmtree(root / "global")
    global_root.mkdir(parents=True)
    host = global_root / CANARY_PACKAGE_NAME
    shutil.copytree(SEALED_PACKAGE, host, symlinks=False)
    intended_root = root / "host-source"
    if intended_root.exists():
        shutil.rmtree(intended_root)
    rows = []
    for relative, source in sorted(intended_targets().items()):
        destination = host / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        intended = intended_root / relative
        intended.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, intended)
        rows.append(
            {
                "intended_source": (
                    source.relative_to(REPO_ROOT).as_posix()
                    if str(source).startswith(str(REPO_ROOT))
                    else f"<sealed-package>/{relative}"
                ),
                "host_target": relative,
                "sha256": sha256_file(destination),
            }
        )
    return rows, host


def stage_global_deps(root: Path) -> list[dict]:
    """Stage the sibling @oh-my-pi runtime packages the host resolves by name."""
    global_root = root / "global" / "node_modules" / "@oh-my-pi"
    rows: list[dict] = []
    for source in sorted(GLOBAL_OH_MY_PI.iterdir()):
        if not source.is_dir() or source.name == CANARY_PACKAGE_NAME:
            continue
        destination = global_root / source.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)
        files = sum(1 for path in destination.rglob("*") if path.is_file())
        size = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
        rows.append(
            {
                "package": source.name,
                "source": str(source),
                "staged": str(destination),
                "files": files,
                "bytes": size,
                "tree_sha256": tree_digest(destination),
            }
        )
    return rows


def stage_extension(root: Path) -> list[dict]:
    extension = root / "extension"
    if extension.exists():
        shutil.rmtree(extension)
    extension.mkdir(parents=True)
    rows = []
    for source in sorted((EXTENSION_SOURCES / "src").glob("*.ts")):
        destination = extension / source.name
        shutil.copyfile(source, destination)
        rows.append(
            {
                "source": f"brainstem/prime-extension/src/{source.name}",
                "staged": source.name,
                "sha256": sha256_file(destination),
            }
        )
    types_dir = extension / "types"
    types_dir.mkdir()
    for source in sorted((EXTENSION_SOURCES / "types").glob("*.d.ts")):
        destination = types_dir / source.name
        shutil.copyfile(source, destination)
        rows.append(
            {
                "source": f"brainstem/prime-extension/types/{source.name}",
                "staged": f"types/{source.name}",
                "sha256": sha256_file(destination),
            }
        )
    return rows


BUN_CACHE = Path.home() / ".bun/install/cache/@oh-my-pi"
RUNTIME_VERSION_SUFFIX = "@18.2.6@@@1"


def tree_digest(root: Path) -> str:
    """sha256 over sorted (relative path, file digest) pairs - a bounded tree id."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            digest.update((sha256_file(path) or "").encode())
            digest.update(b"\n")
    return digest.hexdigest()


def stage_bun_cache(root: Path) -> list[dict]:
    """Give the relocated user root the runtime packages the child resolves there.

    bun's native-addon loader resolves ``@oh-my-pi/pi-natives`` through the
    user's bun cache rather than through the package copy, so a relocated user
    root must carry the 18.2.6 runtime set or the child cannot start. Packages
    are recorded as tree digests; they are inputs to the staged runtime, not part
    of the candidate's source identity.
    """
    cache_root = root / "userhome" / ".bun" / "install" / "cache" / "@oh-my-pi"
    cache_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for source in sorted(BUN_CACHE.glob(f"*{RUNTIME_VERSION_SUFFIX}")):
        if not source.is_dir():
            continue
        destination = cache_root / source.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)
        files = sum(1 for path in destination.rglob("*") if path.is_file())
        size = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
        rows.append(
            {
                "package": source.name,
                "source": str(source),
                "staged": str(destination),
                "files": files,
                "bytes": size,
                "tree_sha256": tree_digest(destination),
            }
        )
    return rows


def link_global_vendors(root: Path) -> list[dict]:
    """Mirror the third-party packages by junction instead of copying them.

    Vendored packages are unmodified inputs, not part of the candidate; they are
    referenced in place (read-only) and recorded with a tree digest, while the
    ``@oh-my-pi`` set that carries the repairs is materialized. A junction keeps
    the resolution shape bun needs without duplicating 1.2 GB into the stage.
    """
    global_root = root / "global" / "node_modules"
    rows: list[dict] = []
    for source in sorted(GLOBAL_OH_MY_PI.parent.iterdir()):
        if not source.is_dir() or source.name == "@oh-my-pi":
            continue
        destination = global_root / source.name
        if destination.exists():
            continue
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
            capture_output=True,
            text=True,
        )
        rows.append(
            {
                "package": source.name,
                "source": str(source),
                "staged": str(destination),
                "mode": "junction" if result.returncode == 0 else "unavailable",
                "detail": (result.stdout or result.stderr).strip()[:200],
                "tree_sha256": tree_digest(source) if result.returncode == 0 else None,
            }
        )
    return rows


def stage_user_root(root: Path) -> dict:
    """A disposable user root so the run writes no production profile state.

    The child's USERPROFILE is redirected here, which moves every ``<user>/.omp``
    path (profile session store, default-profile config) into the stage. The
    default-profile config is copied so the runtime still resolves its model
    settings, the profile directory exists but is empty, and no provider or env
    file is present.
    """
    userhome = root / "userhome"
    if userhome.exists():
        shutil.rmtree(userhome)
    agent_dir = userhome / ".omp" / "agent"
    agent_dir.mkdir(parents=True)
    profile_agent = userhome / ".omp" / "profiles" / "canary-settlement" / "agent"
    profile_agent.mkdir(parents=True)
    config = agent_dir / "config.yml"
    shutil.copyfile(LIVE_USER_CONFIG, config)
    return {
        "root": str(userhome),
        "default_profile_user_config": str(config),
        "default_profile_user_config_sha256": sha256_file(config),
        "profile_dir": str(profile_agent.parent),
        "profile_agent_dir": str(profile_agent),
        "copied_from": str(LIVE_USER_CONFIG),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="disposable stage root")
    args = parser.parse_args()

    root: Path = args.root
    root.mkdir(parents=True, exist_ok=True)
    host_rows, host_package = stage_host(root)
    extension_rows = stage_extension(root)
    user_root = stage_user_root(root)
    cache_rows = stage_bun_cache(root)
    global_rows = stage_global_deps(root)
    vendor_rows = link_global_vendors(root)

    sealed_module = sha256_file(SEALED_PACKAGE / "src" / "task" / "attempt-settlement.ts")
    staged_module = sha256_file(root / "host" / "src" / "task" / "attempt-settlement.ts")
    manifest = {
        "schema": "second-brain.omp-successor-stage.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "host": {
            "source_package": str(SEALED_PACKAGE),
            "package": str(host_package),
            "intended_tree": str(root / "host-source"),
            "overlays": host_rows,
            "attempt_settlement": {
                "sealed_sha256": sealed_module,
                "staged_sha256": staged_module,
                "repaired": sealed_module != staged_module,
            },
        },
        "extension": {"root": str(root / "extension"), "files": extension_rows},
        "user_root": user_root,
        "runtime_cache": cache_rows,
        "global_dependencies": global_rows,
        "vendor_packages": vendor_rows,
        "production_untouched": True,
    }
    (root / "STAGE-MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "root": str(root),
                "host_overlays": len(host_rows),
                "extension_files": len(extension_rows),
                "settlement_repaired_in_stage": manifest["host"]["attempt_settlement"]["repaired"],
                "manifest": str(root / "STAGE-MANIFEST.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
