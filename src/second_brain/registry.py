"""Project registry (plan §10, §130).

Identity priority (plan §10):
1. explicit `.brain/project.toml` ID (read-only detection; writing the manifest
   is Phase 3);
2. Git remote normalized;
3. repo root path hash;
4. manual fallback (--id / --name).
Never identify a project solely by directory name.
"""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .errors import BrainError

PROJECT_FILES = (
    "project.toml",
    "overview.md",
    "current-state.md",
    "architecture.md",
    "lexicon.md",
    "decisions.md",
    "known-issues.md",
    "knowledge-gaps.md",
    "simplification-debt.md",
    "rejected-findings.md",
    "roadmap.md",
    "references.md",
)


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    repo_path: str | None
    git_remote: str | None
    created_at: str
    last_seen_at: str | None
    brain_project_path: str | None
    default_mode: str
    repo_intelligence: str
    verification_policy: str
    active: bool


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def normalize_repo_path(repo_path: str | Path) -> str:
    p = Path(repo_path).expanduser().resolve()
    if not p.exists():
        raise BrainError(f"Repository path does not exist: {p}")
    return str(p)


def path_hash(repo_path: str) -> str:
    """Stable id derived from the normalized repo root path."""
    return hashlib.sha256(normalize_repo_path(repo_path).lower().encode("utf-8")).hexdigest()


def detect_git_remote(repo_path: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().splitlines()[0]
    return None


def detect_explicit_id(repo_path: str) -> str | None:
    """Read `.brain/project.toml` if present (project identity priority 1).

    The file must be valid TOML with a non-empty string `id`. Everything else is
    ignored here (full manifest handling is Phase 3).
    """
    manifest = Path(repo_path) / ".brain" / "project.toml"
    if not manifest.exists():
        return None
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BrainError(f"Invalid project manifest {manifest}: {exc}") from exc
    pid = data.get("id")
    if not isinstance(pid, str) or not pid.strip():
        raise BrainError(f"Project manifest {manifest} has no non-empty string 'id'")
    return pid.strip()


def row_to_project(row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        repo_path=row["repo_path"],
        git_remote=row["git_remote"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        brain_project_path=row["brain_project_path"],
        default_mode=row["default_mode"],
        repo_intelligence=row["repo_intelligence"],
        verification_policy=row["verification_policy"],
        active=bool(row["active"]),
    )


def add_project(
    home: Path,
    repo_path: str | Path,
    *,
    name: str | None = None,
    project_id: str | None = None,
) -> tuple[Project, bool]:
    """Register a repository. Returns (project, created: bool).

    Safe by default: raises BrainError on missing paths or invalid manifests.
    Re-registering an existing project refreshes last_seen_at and is a no-op
    otherwise (idempotent).
    """
    rp = normalize_repo_path(repo_path)
    pid = detect_explicit_id(rp) or project_id or path_hash(rp)
    if not pid or not pid.strip():
        raise BrainError("Could not determine a project id")
    pname = (name or Path(rp).name or pid).strip() or pid
    remote = detect_git_remote(rp)
    brain_dir = Path(home) / "projects" / pid
    now = utcnow()

    conn = db.connect(db.db_path(home))
    try:
        existing = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO projects
                   (id, name, repo_path, git_remote, created_at, last_seen_at,
                    brain_project_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pid, pname, rp, remote, now, now, str(brain_dir)),
            )
            conn.commit()
            created = True
        else:
            conn.execute(
                "UPDATE projects SET last_seen_at = ?, active = 1 WHERE id = ?",
                (now, pid),
            )
            conn.commit()
            created = False
            pname = existing["name"]
        return _make_project_dir(home, pid, pname, rp), created
    finally:
        conn.close()


def _make_project_dir(home: Path, pid: str, name: str, repo_path: str) -> Project:
    """Create the canonical projects/<id>/ directory from templates (idempotent)."""
    templates = Path(home) / "templates" / "project"
    target = Path(home) / "projects" / pid
    target.mkdir(parents=True, exist_ok=True)
    for fname in PROJECT_FILES:
        dst = target / fname
        if dst.exists():
            continue
        src = templates / fname
        text = src.read_text(encoding="utf-8") if src.exists() else f"# {fname}\n"
        dst.write_text(
            text.replace("{id}", pid)
            .replace("{name}", name)
            .replace("{repo_path}", repo_path.replace("\\", "/")),
            encoding="utf-8",
            newline="\n",
        )
    conn = db.connect(db.db_path(home))
    try:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise BrainError(f"Project {pid} vanished during registration")
        return row_to_project(row)
    finally:
        conn.close()


def list_projects(home: Path, *, include_inactive: bool = False) -> list[Project]:
    conn = db.connect(db.db_path(home))
    try:
        q = "SELECT * FROM projects"
        if not include_inactive:
            q += " WHERE active = 1"
        q += " ORDER BY last_seen_at DESC"
        return [row_to_project(r) for r in conn.execute(q).fetchall()]
    finally:
        conn.close()


def get_project(home: Path, key: str) -> Project:
    conn = db.connect(db.db_path(home))
    try:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (key,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM projects WHERE id LIKE ? ORDER BY last_seen_at DESC",
                (key + "%",),
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ? ORDER BY last_seen_at DESC",
                (key,),
            ).fetchone()
        if row is None:
            raise BrainError(f"No registered project matches {key!r}")
        return row_to_project(row)
    finally:
        conn.close()


def project_status(home: Path, key: str) -> dict[str, str]:
    p = get_project(home, key)
    return {
        "id": p.id,
        "name": p.name,
        "repo_path": p.repo_path or "-",
        "repo_exists": str(Path(p.repo_path).exists()) if p.repo_path else "n/a",
        "brain_dir": p.brain_project_path or "-",
        "brain_dir_exists": (
            str(Path(p.brain_project_path).exists()) if p.brain_project_path else "n/a"
        ),
        "created_at": p.created_at,
        "last_seen_at": p.last_seen_at or "-",
        "active": str(p.active),
    }
