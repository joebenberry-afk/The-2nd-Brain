"""Canonical path containment and guarded destructive operations.

INV-03: every security-sensitive derived path must be PROVEN contained with
path-aware semantics (``relative_to`` after canonicalization), never with
string-prefix tests.

INV-04: Windows path semantics are first-class: absolute drive paths, UNC
paths and backslash separators are rejected lexically even on POSIX hosts so
the same manifest/identifier is safe on every platform.

INV-05: symlink escape is considered separately from lexical traversal; every
sensitive operation has an explicit symlink policy (default: reject).

INV-06: recursive deletion is a privileged operation guarded by
:func:`assert_safe_recursive_delete` immediately before the call.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path

from .identifiers import validate_identifier

_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_RE = re.compile(r"^\\\\")


def _validate_relative(relative: str) -> None:
    """Lexical validation of an untrusted relative path component.

    Rejects: NUL/control characters, backslash separators (Windows semantics
    are first-class even on POSIX hosts), drive prefixes, absolute POSIX
    paths, UNC prefixes, empty paths and `.`/`..` traversal parts.
    """
    if "\x00" in relative:
        raise ValueError("path contains NUL")
    if any(ord(ch) < 32 for ch in relative):
        raise ValueError("path contains control characters")
    if "\\" in relative:
        raise ValueError("backslash separators are not allowed")
    if ":" in relative:
        raise ValueError("drive/colon prefixes are not allowed")
    if relative.startswith("/") or _UNC_RE.match(relative) or _WINDOWS_ABSOLUTE_RE.match(relative):
        raise ValueError("absolute/UNC paths are not allowed")
    parts = Path(relative).parts
    if not parts:
        raise ValueError("path must not be empty")
    if any(part in (".", "..") for part in parts):
        raise ValueError("dot/traversal parts are not allowed")


def _is_link(path: Path) -> bool:
    """True when the path is a symlink (or, on Windows, a junction)."""
    if path.is_symlink():
        return True
    junction = getattr(path, "is_junction", None)
    return callable(junction) and bool(junction())


def _check_no_symlinks(root: Path, candidate: Path) -> None:
    """Reject when any lexical component from root to candidate is a symlink.

    ``candidate`` must already be lexically inside ``root`` (a canonical,
    already-resolved root). Missing components are not symlinks.
    """
    try:
        rel = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path {candidate} is not inside {root}") from exc
    current = root
    for part in rel.parts:
        current = current / part
        if _is_link(current):
            raise ValueError(f"symlink not allowed in path: {current}")


def resolve_under(
    root: Path | str,
    relative: str | os.PathLike[str],
    *,
    allow_missing: bool = False,
    allow_symlinks: bool = False,
) -> Path:
    """Prove ``root / relative`` is contained inside ``root`` and return it.

    - canonicalizes ``root``;
    - lexically rejects hostile relative values (absolute, drive, UNC,
      traversal, control characters);
    - for existing targets, resolves the candidate and proves containment
      (a symlink pointing outside fails containment and is rejected);
    - for missing targets (``allow_missing=True``), proves the deepest
      existing ancestor is contained and appends the validated leaf parts;
    - applies the symlink policy: by default any symlink on the chain from
      root to the candidate is rejected.

    Raises ValueError on any violation. The returned path is safe to use for
    the operation the caller guards.
    """
    if isinstance(relative, os.PathLike):
        relative = os.fspath(relative)
    if not isinstance(relative, str):
        raise TypeError(f"relative must be str or PathLike, got {type(relative).__name__}")
    _validate_relative(relative)

    root_path = Path(root)
    root_resolved = root_path.resolve(strict=False)
    candidate = root_resolved / Path(relative)

    # Symlink policy applies to every component of the chain, whether or not
    # the leaf exists yet (a symlinked parent can redirect a future write).
    if not allow_symlinks:
        _check_no_symlinks(root_resolved, candidate)

    exists = candidate.exists() or candidate.is_symlink()
    if exists:
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(root_resolved)
        except (ValueError, OSError) as exc:
            raise ValueError(
                f"path {relative!r} escapes {root_path} (or resolves outside it)"
            ) from exc
        return candidate

    if allow_missing:
        anchor = candidate
        while not anchor.exists() and anchor != root_resolved:
            anchor = anchor.parent
        try:
            anchor.resolve(strict=False).relative_to(root_resolved)
        except (ValueError, OSError) as exc:
            raise ValueError(
                f"path {relative!r} escapes {root_path} (or resolves outside it)"
            ) from exc
        return candidate

    raise ValueError(f"path does not exist: {candidate}")


def assert_safe_recursive_delete(
    target: Path | str,
    *,
    required_parent: Path | str,
    forbidden_roots: Sequence[Path | str] = (),
    expected_name: str | None = None,
) -> Path:
    """Guard for recursive deletion (INV-06). Raises ValueError on refusal.

    Requires, immediately before the caller's ``rmtree``:
    - target is canonically inside ``required_parent``;
    - target != required_parent;
    - target is not any forbidden root (e.g. the Brain root);
    - target is not a symlink and no chain component is a symlink;
    - target's leaf name matches ``expected_name`` when given.
    """
    target_path = Path(target)
    parent = Path(required_parent)
    if target_path == parent:
        raise ValueError(f"refusing to delete the required parent itself: {parent}")
    parent_resolved = parent.resolve(strict=True)
    target_resolved = target_path.resolve(strict=True)
    try:
        target_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(
            f"unsafe recursive delete refused: {target_path} is outside {parent}"
        ) from exc
    if _is_link(target_path):
        raise ValueError(f"unsafe recursive delete refused: {target_path} is a symlink")
    if expected_name is not None and target_path.name != expected_name:
        raise ValueError(
            f"unsafe recursive delete refused: expected {expected_name!r}, got {target_path.name!r}"
        )
    _check_no_symlinks(parent_resolved, target_resolved)
    for forbidden in forbidden_roots:
        if target_resolved == Path(forbidden).resolve(strict=False):
            raise ValueError(f"unsafe recursive delete refused: {target_path} is a forbidden root")
    return target_path


def validated_project_dir(home: Path | str, project_id: object) -> Path:
    """projects/<validated project id> with containment proof (SEC-02)."""
    pid = validate_identifier(project_id, kind="project ID")
    return resolve_under(Path(home) / "projects", pid, allow_missing=True)
