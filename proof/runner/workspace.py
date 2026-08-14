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


def copy_workspace(source: Path, target: Path) -> Path:
    """Copy a fixture or repository into a fresh target directory."""
    source = source.resolve()
    target = target.resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    if target == source or source in target.parents:
        raise ValueError("workspace target must not be inside the source workspace")

    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in DERIVED_DIRS}

    shutil.copytree(source, target, ignore=ignore)
    return target
