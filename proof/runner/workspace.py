"""Fresh task-workspace copies with conservative derived-data exclusion."""

from __future__ import annotations

import shutil
from pathlib import Path

DERIVED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "db",
    "state",
    "telemetry",
    "plasticity",
    "sleep",
    "outputs",
    ".repowise",
}


def copy_workspace(source: Path, target: Path, *, root: Path | None = None) -> Path:
    """Copy a fixture or repository into a fresh target directory.

    SEC-07: when ``root`` is given, the target must be proven contained under
    it before any filesystem write (the proof runner passes the trusted
    temporary root). Symlinks are not copied.
    """
    source = source.resolve()
    target = target.resolve()
    if root is not None:
        try:
            target.relative_to(Path(root).resolve(strict=False))
        except ValueError as exc:
            raise ValueError(
                f"workspace target {target} is outside the trusted root {root}"
            ) from exc
    if not source.is_dir():
        raise FileNotFoundError(source)
    if target == source or source in target.parents:
        raise ValueError("workspace target must not be inside the source workspace")

    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in DERIVED_DIRS}

    shutil.copytree(source, target, ignore=ignore, symlinks=False)
    return target
