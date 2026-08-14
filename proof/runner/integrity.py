"""Hashes and immutability checks for campaign inputs and outputs."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path


class IntegrityError(RuntimeError):
    """Raised when a frozen campaign input changes."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def hash_tree(root: Path, *, exclude: Iterable[str] = ()) -> str:
    """Hash relative paths and bytes in stable order."""
    excluded = {Path(item).as_posix().rstrip("/") for item in exclude}
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if any(relative == item or relative.startswith(item + "/") for item in excluded):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def freeze_hash(path: Path, expected: str) -> str:
    """Verify a frozen file and return its current hash."""
    if not path.is_file():
        raise IntegrityError(f"frozen input missing: {path}")
    actual = sha256_path(path)
    if actual != expected:
        raise IntegrityError(f"frozen input changed: {path}")
    return actual


def write_hash(path: Path, target: Path) -> str:
    """Write one newline-terminated hash atomically and return it."""
    digest = sha256_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(f"{digest}  {target.name}\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return digest
