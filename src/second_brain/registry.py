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
from .security.identifiers import validate_project_id
from .security.paths import assert_safe_recursive_delete, validated_project_dir

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


def remote_identity(git_remote: str) -> str:
    """Stable id derived from the normalized Git remote (plan §10 priority 2).

    Strips trailing '.git' and lowercases so the same remote on a different
    machine/path resolves to the same project id.
    """
    norm = git_remote.strip().lower()
    if norm.endswith(".git"):
        norm = norm[:-4]
    norm = norm.rstrip("/")
    return hashlib.sha256(f"remote:{norm}".encode()).hexdigest()


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
    # Identity priority (plan §10): explicit manifest -> manual --id -> git
    # remote normalized -> repo root path hash. Never the directory name.
    remote = detect_git_remote(rp)
    explicit = detect_explicit_id(rp)
    if explicit:
        pid = explicit
    elif project_id:
        pid = project_id
    elif remote:
        pid = remote_identity(remote)
    else:
        pid = path_hash(rp)
    if not pid or not pid.strip():
        raise BrainError("Could not determine a project id")
    # SEC-02/SEC-06: every identity source (manifest id, manual --id, git
    # remote hash, path hash) passes the identifier boundary before it can
    # influence a filesystem path or generated marker. Hostile ids are
    # rejected, never sanitized.
    pid = validate_project_id(pid)
    pname = (name or Path(rp).name or pid).strip() or pid
    brain_dir = validated_project_dir(home, pid)
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
    target = validated_project_dir(home, pid)
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
    rw: dict[str, bool] = {}
    if p.repo_path and Path(p.repo_path).exists():
        rw = detect_repowise(p.repo_path)
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
        "repowise_cli": str(rw.get("cli_available", False)),
        "repowise_index": str(rw.get("index_present", False)),
        "repowise_policy": p.repo_intelligence,
    }


# ---------------------------------------------------------------------------
# Phase 3 — project integration (plan §99): .brain/project.toml write-back and
# a minimal, fenced AGENTS.md marker block. Idempotent attach; safe detach.
# ---------------------------------------------------------------------------

MARKER_BEGIN = "<!-- The-Second-Brain:begin id={pid} -->"
MARKER_END = "<!-- The-Second-Brain:end -->"

MARKER_BODY = """## The Second Brain

Canonical Brain: `%SECOND_BRAIN_HOME%`.

For substantive work:
- current repo/tests outrank memory;
- use targeted Brain recall;
- do not preload the Brain;
- use Brainstem signals where available;
- preserve durable validated learning.
"""

MANIFEST_TEMPLATE = """# Managed by The Second Brain (brainctl project attach). Safe to edit.
schema_version = 1
id = "{id}"
name = "{name}"
brain_enabled = true
repository_is_authoritative = true

[meta]
managed_by = "second-brain"

[performance]
default_mode = "standard"
context_policy = "adaptive"
repo_intelligence = "repowise-preferred"
verification_policy = "risk-adaptive"

[automation]
brainstem = true
improvement_radar = true
experience_observer = true

[tools]
repowise = "auto"
ast_grep = "auto"
sz_tool = "auto"
"""


def _agents_marker_block(pid: str) -> str:
    return f"{MARKER_BEGIN.format(pid=pid)}\n{MARKER_BODY}{MARKER_END}\n"


def _append_marker(agents_path: Path, pid: str) -> bool:
    """Append (or skip, when already present) the marker block. Returns changed.

    The block is always appended as ``"\n" + block``. ``_remove_marker``
    removes exactly that span, so detach restores the file byte-for-byte.
    """
    if agents_path.exists():
        # newline="" reads raw bytes (no CRLF->LF translation) so detach can
        # restore the file byte-for-byte on Windows.
        with agents_path.open(encoding="utf-8", newline="") as f:
            text = f.read()
        if "The-Second-Brain:begin id=" in text:
            return False  # idempotent: a marker already exists
        text += "\n" + _agents_marker_block(pid)
    else:
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n" + _agents_marker_block(pid)
    agents_path.write_text(text, encoding="utf-8", newline="")
    return True


def _remove_marker(agents_path: Path) -> tuple[bool, str]:
    """Remove the Second Brain marker block. Returns (changed, remaining_text).

    Removes exactly the span attach appended (including the one preceding
    newline), leaving the original file bytes untouched. A malformed marker
    (missing end fence) is left alone rather than risk deleting user content.
    """
    if not agents_path.exists():
        return False, ""
    with agents_path.open(encoding="utf-8", newline="") as f:
        text = f.read()
    begin = "<!-- The-Second-Brain:begin"
    idx = text.find(begin)
    if idx == -1:
        return False, text
    end_idx = text.find(MARKER_END, idx)
    if end_idx == -1:
        return False, text
    block_end = end_idx + len(MARKER_END)
    if text[block_end : block_end + 1] == "\n":
        block_end += 1  # the block's own trailing newline belongs to the block
    start = idx - 1 if idx > 0 and text[idx - 1] == "\n" else idx
    remaining = text[:start] + text[block_end:]
    return True, remaining


def write_project_manifest(repo_path: str, pid: str, name: str) -> bool:
    """Write .brain/project.toml unless one already exists. Returns created."""
    manifest = Path(repo_path) / ".brain" / "project.toml"
    if manifest.exists():
        return False
    manifest.parent.mkdir(parents=True, exist_ok=True)
    content = MANIFEST_TEMPLATE.replace("{id}", pid).replace("{name}", name)
    manifest.write_text(content, encoding="utf-8", newline="\n")
    return True


def detect_repowise(repo_path: str) -> dict[str, bool]:
    import shutil

    return {
        "cli_available": shutil.which("repowise") is not None,
        "index_present": (Path(repo_path) / ".repowise").exists(),
    }


def attach_project(
    home: Path,
    repo_path: str | Path,
    *,
    name: str | None = None,
    project_id: str | None = None,
    with_marker: bool = True,
    with_manifest: bool = True,
) -> tuple[Project, bool, dict[str, bool]]:
    """Full project attach (plan §99): registry + manifest + AGENTS marker.

    Returns (project, created, changes). Safe: never overwrites an existing
    .brain/project.toml; never touches AGENTS.md content outside our fenced
    block; re-attach is a no-op for already-applied steps.
    """
    rp = normalize_repo_path(repo_path)
    proj, created = add_project(home, rp, name=name, project_id=project_id)
    changes: dict[str, bool] = {"registered_created": created}
    if with_manifest:
        changes["manifest_created"] = write_project_manifest(rp, proj.id, proj.name)
    if with_marker:
        changes["marker_added"] = _append_marker(Path(rp) / "AGENTS.md", proj.id)
    return proj, created, changes


def detach_project(home: Path, key: str) -> dict[str, bool | str]:
    """Reverse repo-side integration. Returns a change report.

    Removes our fenced AGENTS.md marker block (byte-exact restoration,
    including CRLF line endings), removes .brain/project.toml only when it is
    Brain-managed, and deactivates the registry row. User content is preserved;
    user-owned manifests are left untouched.
    """
    proj = get_project(home, key)
    if not proj.repo_path:
        raise BrainError(f"Project {proj.name!r} has no repo_path to detach")
    rp = Path(proj.repo_path)
    if not rp.exists():
        raise BrainError(f"Repository path no longer exists: {rp}")
    changes: dict[str, bool | str] = {"id": proj.id, "name": proj.name}

    agents = rp / "AGENTS.md"
    removed, remaining = _remove_marker(agents)
    changes["marker_removed"] = removed
    if removed:
        # Write the remaining content back even when whitespace-only: we never
        # delete a file the user may still care about.
        agents.write_text(remaining, encoding="utf-8", newline="")

    manifest = rp / ".brain" / "project.toml"
    if manifest.exists():
        import tomllib

        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
            managed = (
                isinstance(data.get("meta"), dict)
                and data["meta"].get("managed_by") == "second-brain"
            )
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise BrainError(f"Invalid project manifest {manifest}: {exc}") from exc
        if managed:
            manifest.unlink()
            changes["manifest_removed"] = True
        else:
            changes["manifest_removed"] = False

    conn = db.connect(db.db_path(home))
    try:
        conn.execute("UPDATE projects SET active = 0 WHERE id = ?", (proj.id,))
        conn.commit()
    finally:
        conn.close()
    changes["deactivated"] = True
    return changes


def remove_project(home: Path, key: str, *, purge: bool = False) -> dict[str, str]:
    """Delete a registry row (rollback completeness). The canonical
    projects/<id>/ directory is kept unless --purge is given."""
    import shutil

    proj = get_project(home, key)
    # SEC-02: purge is a privileged recursive delete. Validate the target
    # BEFORE the row is deleted and immediately before the rmtree. Never
    # trust the stored path; prove it is the exact registered project
    # directory beneath projects/.
    brain_dir: Path | None = None
    if purge and proj.brain_project_path:
        candidate = Path(proj.brain_project_path)
        if candidate.exists():
            try:
                brain_dir = assert_safe_recursive_delete(
                    candidate,
                    required_parent=Path(home) / "projects",
                    forbidden_roots=(home, Path(home) / "projects"),
                    expected_name=proj.id,
                )
            except ValueError as exc:
                raise BrainError(f"Unsafe purge target refused: {exc}") from exc
    conn = db.connect(db.db_path(home))
    try:
        conn.execute("DELETE FROM projects WHERE id = ?", (proj.id,))
        conn.commit()
    finally:
        conn.close()
    out = {"id": proj.id, "name": proj.name, "purged": "False"}
    if brain_dir is not None:
        shutil.rmtree(brain_dir)
        out["purged"] = "True"
    return out
