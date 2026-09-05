"""Runtime build identity (plan §9, P2): stop reporting a stale package
version for a qualified v2 build, and let one call prove exactly which
code, adapter, and schema are running.

Every surface (VERSION, pyproject.toml, __version__, doctor, status,
Prime runtime-ready telemetry) must agree; this module is the single
source every one of them reads.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from . import __version__, db

# The exact commit the v2 architecture was independently verified against
# (outputs/reports/v2/final/release-report.md). Never rewritten; repairs on
# brain/v2-burnin-repair build on top of it without amending it.
QUALIFICATION_BASELINE_SHA = "4af64affdf4f1ec07b9483b67f440394d2853b32"

PRIME_EXTENSION_SOURCE_DIRS = ("src", "types")


def _run(cmd: list[str], cwd: Path, timeout: float = 10) -> str | None:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def repo_root_for(home: Path) -> Path | None:
    """The Git repository root that contains `home`, if any."""
    out = _run(["git", "rev-parse", "--show-toplevel"], cwd=home)
    return Path(out) if out else None


def git_sha(repo: Path) -> str | None:
    return _run(["git", "rev-parse", "HEAD"], cwd=repo)


def git_dirty(repo: Path) -> bool | None:
    out = _run(["git", "status", "--porcelain"], cwd=repo)
    return None if out is None else len(out) > 0


def adapter_build_fingerprint(repo: Path) -> str | None:
    """sha256 over every Prime extension source file's own sha256, sorted by
    relative path -- the same manifest shape the installer verifies against
    (scripts/install-prime-extension.ps1), so this fingerprint changes iff
    the deployed extension bytes would change."""
    ext_root = repo / "brainstem" / "prime-extension"
    if not ext_root.is_dir():
        return None
    entries: list[str] = []
    for rel in PRIME_EXTENSION_SOURCE_DIRS:
        src = ext_root / rel
        if not src.is_dir():
            continue
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append(f"{path.relative_to(ext_root).as_posix()}\t{digest}")
    if not entries:
        return None
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def source_tree_fingerprint(repo: Path) -> str | None:
    """Bind product, package data, verifier, regression, and dependency bytes."""
    if not (repo / "src").is_dir() or not (repo / "pyproject.toml").is_file():
        return None
    entries: list[str] = []
    try:
        for directory in ("src", "scripts", "tests"):
            for path in (repo / directory).rglob("*"):
                if (
                    path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix not in {".pyc", ".pyo"}
                ):
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    entries.append(f"{path.relative_to(repo).as_posix()}\t{digest}")
        for name in ("pyproject.toml", "uv.lock"):
            path = repo / name
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries.append(f"{name}\t{digest}")
    except OSError:
        return None
    return hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()


def configuration_fingerprint(home: Path) -> str | None:
    """Bind actual configuration bytes without exposing their contents."""
    root = home / "config"
    if not root.is_dir():
        return None
    entries: list[str] = []
    try:
        for path in root.rglob("*"):
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries.append(f"{path.relative_to(root).as_posix()}\t{digest}")
    except OSError:
        return None
    return (
        hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest() if entries else None
    )


def db_schema_version(home: Path) -> int | None:
    dbfile = db.db_path(home)
    if not dbfile.exists():
        return None
    conn = db.connect(dbfile, readonly=True)
    try:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
        return int(row["v"])
    finally:
        conn.close()


def describe(home: Path) -> dict:
    """One dict every surface (doctor, status, qualification tooling) reads,
    so there is exactly one place a build-identity field is computed."""
    repo = repo_root_for(home)
    sha = git_sha(repo) if repo else None
    return {
        "package_version": __version__,
        "git_sha": sha,
        "dirty": git_dirty(repo) if repo else None,
        "db_schema_version": db_schema_version(home),
        "adapter_build_fingerprint": adapter_build_fingerprint(repo) if repo else None,
        "qualification_baseline_sha": QUALIFICATION_BASELINE_SHA,
        "qualification_baseline_current": sha == QUALIFICATION_BASELINE_SHA,
    }
