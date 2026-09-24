"""Project identity and record visibility for the V3 core (stdlib only).

Projects are declared by the canonical ``projects/<id>/project.toml`` manifests::

    id = "second-brain"
    name = "The Second Brain"
    repo_path = "C:/Users/assas/Documents/The-Second-Brain"
    paths = ["/home/user/The-2nd-Brain"]          # optional: the same repo on other machines
    git_remote = "github.com/joebenberry-afk/the-2nd-brain"   # optional
    domains = ["ue4ss"]                            # optional: shared-knowledge tags

Resolution order for a working directory: explicit id (argument or ``BRAIN_PROJECT``) → the
longest declared path containing the directory → the git ``origin`` remote → none. Scope is
enforced here, before any ranking (RET-01).
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .records import Record


@dataclass(frozen=True)
class Project:
    id: str
    name: str = ""
    paths: tuple[str, ...] = ()
    git_remote: str | None = None
    domains: tuple[str, ...] = ()


_UNKNOWN = frozenset({"", "default", "unknown"})


def normalize_path(value: str) -> str:
    """Comparable form of a local path from either OS: forward slashes, no trailing slash,
    case-folded when it is a Windows path."""
    text = value.strip()
    if re.match(r"^[A-Za-z]:[\\/]", text) or "\\" in text:
        return PureWindowsPath(text).as_posix().rstrip("/").casefold()
    return PurePosixPath(text).as_posix().rstrip("/") or "/"


def normalize_remote(url: str) -> str:
    """``git@github.com:o/r.git`` / ``https://user@github.com/o/r`` → ``github.com/o/r``."""
    text = url.strip()
    text = re.sub(r"^[a-z+]+://", "", text)
    text = re.sub(r"^[^@/]+@", "", text)
    text = text.replace(":", "/", 1) if re.match(r"^[^/]+:[^/]", text) else text
    text = text.removesuffix("/").removesuffix(".git")
    return text.casefold()


def load_projects(home: Path) -> list[Project]:
    projects: list[Project] = []
    for manifest in sorted((Path(home) / "projects").glob("*/project.toml")):
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        project_id = str(data.get("id") or manifest.parent.name)
        paths = [str(data["repo_path"])] if data.get("repo_path") else []
        paths.extend(str(p) for p in data.get("paths") or [] if isinstance(p, str))
        remote = data.get("git_remote")
        projects.append(
            Project(
                id=project_id,
                name=str(data.get("name") or project_id),
                paths=tuple(paths),
                git_remote=normalize_remote(remote) if isinstance(remote, str) else None,
                domains=tuple(str(d) for d in data.get("domains") or [] if isinstance(d, str)),
            )
        )
    return projects


def git_remote_for(cwd: Path) -> str | None:
    """The ``origin`` URL of the repository containing ``cwd``, read from its git config."""
    for directory in (cwd, *cwd.parents):
        dotgit = directory / ".git"
        if dotgit.is_file():  # worktree or submodule: "gitdir: <path>"
            target = dotgit.read_text(encoding="utf-8").partition("gitdir:")[2].strip()
            gitdir = (directory / target).resolve()
            common = gitdir / "commondir"
            if common.is_file():
                gitdir = (gitdir / common.read_text(encoding="utf-8").strip()).resolve()
            config = gitdir / "config"
        elif dotgit.is_dir():
            config = dotgit / "config"
        else:
            continue
        try:
            text = config.read_text(encoding="utf-8")
        except OSError:
            return None
        section = re.search(r'\[remote "origin"\](.*?)(?:\n\[|\Z)', text, re.S)
        if section:
            url = re.search(r"^\s*url\s*=\s*(.+)$", section.group(1), re.M)
            if url:
                return url.group(1).strip()
        return None
    return None


def resolve(home: Path, cwd: Path | None = None, explicit: str | None = None) -> Project | None:
    """The project a caller works in, or None when it cannot be established."""
    projects = load_projects(home)
    wanted = explicit or os.environ.get("BRAIN_PROJECT")
    if wanted:
        return next((p for p in projects if p.id == wanted), Project(id=wanted, name=wanted))
    if cwd is None:
        return None
    here = normalize_path(str(Path(cwd).resolve()))
    best: tuple[int, Project] | None = None
    for project in projects:
        for declared in project.paths:
            root = normalize_path(declared)
            contains = here == root or here.startswith(root + "/")
            if contains and (best is None or len(root) > best[0]):
                best = (len(root), project)
    if best is not None:
        return best[1]
    remote = git_remote_for(Path(cwd).resolve())
    if remote:
        key = normalize_remote(remote)
        return next((p for p in projects if p.git_remote == key), None)
    return None


def visible(record: Record, project: Project | None) -> bool:
    """Whether a caller in ``project`` may see ``record`` at all (before ranking)."""
    if record.scope == "global":
        return True
    project_id = project.id if project is not None else ""
    if record.scope == "project":
        return bool(project_id) and project_id not in _UNKNOWN and record.project == project_id
    # domain: tagged records are shared by tag; untagged (legacy) records keep the legacy rule —
    # visible when either side has no known project, or the projects match.
    if record.domains:
        declared = set(project.domains) if project is not None else set()
        return bool(declared & set(record.domains)) or (
            bool(project_id) and record.project == project_id
        )
    record_project = (record.project or "").strip().lower()
    return (
        project_id.strip().lower() in _UNKNOWN
        or record_project in _UNKNOWN
        or record.project == project_id
    )
