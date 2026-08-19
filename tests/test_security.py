"""Regression tests for the shared security boundary (plan §5-§6).

Covers SEC-T001..SEC-T020 equivalents: identifier validation and canonical
path containment with Windows-first lexical rejection and symlink policy.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from second_brain.errors import BrainError
from second_brain.security.identifiers import validate_identifier
from second_brain.security.paths import assert_safe_recursive_delete, resolve_under

VALID = [
    "project-1",
    "project_test",
    "brain-v43",
    "combat_ai",
    "skill001",
    "frontier-2026",
    "a",
    "A",
    "0",
    "x" * 128,
]

INVALID = [
    "",
    ".",
    "..",
    "../x",
    "..\\x",
    "x/y",
    "x\\y",
    "/absolute",
    "C:\absolute",
    "C:/absolute",
    "\\\\server\\share",
    "a\nb",
    "a\rb",
    "a\x00b",
    "a*b",
    "a?b",
    "a[b]",
    "-lead",
    "_lead",
    "x" * 129,
    "a.b",
    "a b",
    "a:b",
    "a\tb",
]


# ---------------------------------------------------------------------------
# Identifier validation (SEC-T001..T019 identifier half)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", VALID)
def test_valid_identifiers_accepted(value: str) -> None:
    assert validate_identifier(value) == value


@pytest.mark.parametrize("value", INVALID)
def test_invalid_identifiers_rejected(value: str) -> None:
    with pytest.raises(BrainError):
        validate_identifier(value)


def test_identifier_non_string_rejected() -> None:
    with pytest.raises(BrainError):
        validate_identifier(42)  # type: ignore[arg-type]
    with pytest.raises(BrainError):
        validate_identifier(None)  # type: ignore[arg-type]


def test_purpose_specific_wrappers() -> None:
    from second_brain.security import (
        validate_engram_name,
        validate_frontier_id,
        validate_policy_id,
        validate_project_id,
        validate_proof_task_id,
        validate_skill_name,
        validate_trigger_id,
    )

    for wrapper in (
        validate_project_id,
        validate_skill_name,
        validate_engram_name,
        validate_frontier_id,
        validate_proof_task_id,
        validate_policy_id,
        validate_trigger_id,
    ):
        assert wrapper("ok-name") == "ok-name"
        with pytest.raises(BrainError, match="Invalid"):
            wrapper("../escape")


# ---------------------------------------------------------------------------
# Canonical path containment (SEC-T019, T020 and Windows forms)
# ---------------------------------------------------------------------------


def _make_tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "f.txt").write_text("x", encoding="utf-8")


@pytest.mark.parametrize(
    "relative",
    [
        "../x",
        "..\\x",
        "sub/../../x",
        "..",
        ".",
        "",
        "/abs",
        "C:\\abs",
        "C:/abs",
        "\\\\server\\share",
        "a\\b",
        "a:b",
        "sub/..",
        "\x00bad",
    ],
)
def test_resolve_under_rejects_hostile_relative(tmp_path: Path, relative: str) -> None:
    _make_tree(tmp_path)
    with pytest.raises(ValueError):
        resolve_under(tmp_path, relative, allow_missing=True)


def test_resolve_under_accepts_contained_paths(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    result = resolve_under(tmp_path, "sub/f.txt")
    assert result == tmp_path.resolve() / "sub" / "f.txt"
    assert result.is_file()
    missing = resolve_under(tmp_path, "sub/new-dir", allow_missing=True)
    assert missing == tmp_path.resolve() / "sub" / "new-dir"
    assert not missing.exists()
    with pytest.raises(ValueError, match="does not exist"):
        resolve_under(tmp_path, "sub/absent.txt")


def test_resolve_under_sibling_prefix_not_mistaken(tmp_path: Path) -> None:
    """SEC-T019: a sibling that merely shares a string prefix is not 'inside'."""
    root = tmp_path / "proj"
    sibling = tmp_path / "project-other"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(ValueError):
        resolve_under(root, "../project-other/x", allow_missing=True)
    with pytest.raises(ValueError):
        resolve_under(root, ".." + os.sep + "project-other", allow_missing=True)


def test_resolve_under_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        kwargs = {"target_is_directory": True} if os.name == "nt" else {}
        os.symlink(outside, link, **kwargs)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="symlink"):
        resolve_under(tmp_path, "link/f.txt")
    with pytest.raises(ValueError, match="symlink"):
        resolve_under(tmp_path, "link/new-file", allow_missing=True)


def test_resolve_under_rejects_internal_symlink_policy(tmp_path: Path) -> None:
    """Even a symlink that stays inside the root is rejected by default."""
    (tmp_path / "real").mkdir()
    link = tmp_path / "inlink"
    try:
        kwargs = {"target_is_directory": True} if os.name == "nt" else {}
        os.symlink(tmp_path / "real", link, **kwargs)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="symlink"):
        resolve_under(tmp_path, "inlink/x.txt", allow_missing=True)
    # Explicit opt-in allows it (documented exception).
    result = resolve_under(tmp_path, "inlink", allow_symlinks=True)
    assert result.name == "inlink"


# ---------------------------------------------------------------------------
# Guarded recursive delete (SEC-T033..T036 helpers)
# ---------------------------------------------------------------------------


def test_safe_recursive_delete_valid(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    (target / "f").write_text("x", encoding="utf-8")
    result = assert_safe_recursive_delete(
        target, required_parent=tmp_path, expected_name="proj", forbidden_roots=[tmp_path]
    )
    assert result == target


def test_safe_recursive_delete_refuses_parent_itself(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="parent itself"):
        assert_safe_recursive_delete(tmp_path, required_parent=tmp_path)


def test_safe_recursive_delete_refuses_outside(tmp_path: Path) -> None:
    outside = tmp_path.parent / "unrelated-delete-target"
    outside.mkdir(exist_ok=True)
    try:
        with pytest.raises(ValueError, match="outside"):
            assert_safe_recursive_delete(outside, required_parent=tmp_path)
    finally:
        outside.rmdir()


def test_safe_recursive_delete_refuses_wrong_name(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    with pytest.raises(ValueError, match="expected"):
        assert_safe_recursive_delete(target, required_parent=tmp_path, expected_name="other")


def test_safe_recursive_delete_refuses_symlink_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "proj-link"
    try:
        kwargs = {"target_is_directory": True} if os.name == "nt" else {}
        os.symlink(outside, link, **kwargs)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="symlink"):
        assert_safe_recursive_delete(link, required_parent=tmp_path, expected_name="proj-link")


def test_safe_recursive_delete_refuses_forbidden_root(tmp_path: Path) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    with pytest.raises(ValueError, match="forbidden"):
        assert_safe_recursive_delete(inner, required_parent=tmp_path, forbidden_roots=[inner])


def test_constitution_never_written_by_brain_commands(tmp_path):
    """Filesystem invariant: no real CLI write path may touch constitution/.

    Exercises a spread of genuinely write-heavy brainctl commands against a
    throwaway Brain home and asserts every file under constitution/ is
    byte-identical afterwards and that no new path appeared. Fails loudly if
    a future change adds an automatic constitution writer.
    """
    import hashlib
    import os
    import subprocess
    import sys

    home = tmp_path / "brain"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env["SECOND_BRAIN_HOME"] = str(home)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "second_brain", "--home", str(home), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    assert run("init").returncode == 0

    const = home / "constitution"
    const.mkdir(parents=True, exist_ok=True)
    (const / "INTEGRITY_SENTINEL.md").write_text("sentinel\n", encoding="utf-8")

    def snapshot() -> dict[str, str]:
        return {
            str(p.relative_to(const)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(const.rglob("*"))
            if p.is_file()
        }

    before = snapshot()
    assert "INTEGRITY_SENTINEL.md" in before

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=False, capture_output=True)

    # Write-heavy real commands: registry, memory, ledger, artifacts, capsule,
    # requirements, telemetry, plasticity, backup. Each mutates Brain state.
    blob = tmp_path / "blob.txt"
    blob.write_text("artifact payload\n", encoding="utf-8")

    # Genuinely mutating commands only (registry, memory, capsule, requirement
    # ledger, artifact store, session ledger, episode capture, backup).
    write_commands: list[list[str]] = [
        ["project", "add", str(repo)],
        ["memory", "add", "--title", "t", "--body", "b"],
        ["capsule", "init", "sess-const", "objective"],
        ["requirements", "add", "sess-const", "a requirement"],
        ["artifact", "store", "--kind", "generic", str(blob)],
        ["ledger", "init", "--session", "sess-const"],
        ["episodes", "create", "--session", "sess-const"],
        ["backup"],
    ]
    succeeded = [" ".join(cmd[:2]) for cmd in write_commands if run(*cmd).returncode == 0]
    assert len(succeeded) >= 6, (
        f"too few mutating commands succeeded to make this meaningful: {succeeded}"
    )

    after = snapshot()
    assert set(after) == set(before), (
        f"constitution/ file set changed: added={set(after) - set(before)} "
        f"removed={set(before) - set(after)}"
    )
    for name, digest in before.items():
        assert after[name] == digest, f"constitution/{name} was modified by a Brain command"
