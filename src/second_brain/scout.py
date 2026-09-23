"""Deterministic repository discovery and evidence map generation.

The pre-pass and evidence map do not spawn an agent or select a model.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import registry
from .errors import BrainError

# Evidence Map schema (plan §23) in canonical order.
EVIDENCE_MAP_FIELDS: tuple[str, ...] = (
    "task",
    "likely_edit_sites",
    "relevant_tests",
    "callers_dependencies",
    "architecture_context",
    "hotspot_risk_notes",
    "unknowns",
    "recommended_next_read",
    "source_freshness",
)

SECTION_TITLES: dict[str, str] = {
    "task": "Task",
    "likely_edit_sites": "Likely Edit Sites",
    "relevant_tests": "Relevant Tests",
    "callers_dependencies": "Callers / Dependencies",
    "architecture_context": "Architecture Context",
    "hotspot_risk_notes": "Hotspot / Risk Notes",
    "unknowns": "Unknowns",
    "recommended_next_read": "Recommended Next Read",
    "source_freshness": "Source Freshness",
}

RG_EXCLUDES: tuple[str, ...] = (
    "node_modules",
    ".venv",
    ".git",
    "dist",
    "build",
    "__pycache__",
)

SLUG_MAX = 40
SCAN_WORD_MIN = 4


def make_slug(task: str) -> str:
    """Slugify a task: lowercase, non-alphanumerics -> '-', max 40 chars."""
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")
    return slug[:SLUG_MAX].rstrip("-") or "scout"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_repo(home: Path, target: str | Path) -> Path:
    """Resolve a repo root: existing path, else a registered project key."""
    candidate = Path(target).expanduser()
    if candidate.exists():
        return candidate.resolve()
    try:
        project = registry.get_project(home, str(target))
    except Exception as exc:
        raise BrainError(
            f"Target {str(target)!r} is neither an existing path nor a registered project: {exc}"
        ) from exc
    if not project.repo_path:
        raise BrainError(f"Project {str(target)!r} has no repo_path")
    repo = Path(project.repo_path)
    if not repo.exists():
        raise BrainError(f"Project repo path is missing: {repo}")
    return repo.resolve()


# ---------------------------------------------------------------------------
# Deterministic pre-pass
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path | None, timeout: float) -> str | None:
    """Run a probe; return stdout on success (rc 0), else None. Never raises."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _git_probe(repo: Path) -> dict:
    probe: dict = {"branch": "unknown", "head": "unknown", "dirty": None, "error": None}
    branch = _run(["git", "-C", str(repo), "branch", "--show-current"], repo, 10)
    if branch is None:
        probe["error"] = "git probe failed"
    else:
        probe["branch"] = branch.strip() or "unknown"
    head = _run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], repo, 10)
    if head is not None:
        probe["head"] = head.strip()
    status = _run(["git", "-C", str(repo), "status", "--porcelain"], repo, 10)
    if status is not None:
        probe["dirty"] = bool(status.strip())
    return probe


def _repowise_probe(repo: Path) -> dict:
    probe: dict = {
        "cli_available": False,
        "index_present": False,
        "freshness": "unknown",
        "error": None,
    }
    probe["cli_available"] = shutil.which("repowise") is not None
    probe["index_present"] = (repo / ".repowise").is_dir()
    if not probe["cli_available"]:
        return probe
    try:
        result = subprocess.run(
            ["repowise", "status"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=20,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        probe["error"] = f"repowise status failed: {exc}"
        return probe
    if result.returncode != 0:
        probe["error"] = "repowise status failed"
        return probe
    for line in result.stdout.splitlines():
        if "Last sync" in line:
            probe["freshness"] = line.strip()
            break
    return probe


def _task_words(task: str) -> list[str]:
    return [
        word for word in re.findall(r"[A-Za-z0-9_]+", task.lower()) if len(word) >= SCAN_WORD_MIN
    ]


def _rg_files(repo: Path, word: str) -> list[str] | None:
    cmd = ["rg", "-l", "-i", "--max-count", "1", word, "."]
    for pattern in RG_EXCLUDES:
        cmd += ["-g", f"!**/{pattern}/**"]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):
        return None
    # rc 1 = no matches: a valid result, not a failure.
    paths = []
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        if path.startswith("./") or path.startswith(".\\"):
            path = path[2:]
        paths.append(path.replace("\\", "/"))
    return sorted(paths)


def _candidate_pass(repo: Path, task: str, max_candidates: int) -> dict:
    words = _task_words(task)
    counts: dict[str, int] = {}
    errors: list[str] = []
    for word in words:
        matches = _rg_files(repo, word)
        if matches is None:
            errors.append(f"rg probe failed for word {word!r}")
            continue
        for path in matches:
            if len(counts) >= max_candidates:
                break
            counts[path] = counts.get(path, 0) + 1
        if len(counts) >= max_candidates:
            break
    return {"words": words, "files": counts, "errors": errors}


def deterministic_prepass(repo: Path, task: str, max_candidates: int = 10) -> dict:
    """Cheap deterministic reconnaissance. Subprocess probes never raise."""
    root = Path(repo).resolve()
    return {
        "git": _git_probe(root),
        "repowise": _repowise_probe(root),
        "candidates": _candidate_pass(root, task, max_candidates),
    }


# ---------------------------------------------------------------------------
# Evidence Map
# ---------------------------------------------------------------------------


def _render_freshness(prepass: dict) -> list[str]:
    git = prepass.get("git", {})
    repowise = prepass.get("repowise", {})
    lines = [
        f"- git branch: {git.get('branch', 'unknown')}",
        f"- git head: {git.get('head', 'unknown')}",
        f"- git dirty: {git.get('dirty')}",
        f"- repowise cli: {repowise.get('cli_available', False)}",
        f"- repowise index: {repowise.get('index_present', False)}",
        f"- repowise freshness: {repowise.get('freshness', 'unknown')}",
    ]
    if git.get("error"):
        lines.append(f"- git error: {git['error']}")
    if repowise.get("error"):
        lines.append(f"- repowise error: {repowise['error']}")
    return lines


def _render_appendix(prepass: dict) -> list[str]:
    candidates = prepass.get("candidates", {})
    words = candidates.get("words", [])
    files = candidates.get("files", {})
    errors = candidates.get("errors", [])
    lines = [
        f"- task words: {', '.join(words) if words else '(none)'}",
        "- candidates:",
    ]
    if files:
        for path, count in files.items():
            plural = "es" if count != 1 else ""
            lines.append(f"  - {path} ({count} match{plural})")
    else:
        lines.append("  (none)")
    if errors:
        lines.append("- probe errors:")
        lines.extend(f"  - {error}" for error in errors)
    return lines


def _render(repo: Path, task: str, prepass: dict) -> str:
    lines = ["# Evidence Map", ""]
    for field in EVIDENCE_MAP_FIELDS:
        lines.append(f"## {SECTION_TITLES[field]}")
        lines.append("")
        if field == "task":
            lines.append(task.strip() or "(none)")
        elif field == "source_freshness":
            lines.extend(_render_freshness(prepass))
        else:
            lines.append("(fill me)")
        lines.append("")
    lines.append("## Deterministic Pre-pass")
    lines.append("")
    lines.extend(_render_appendix(prepass))
    return "\n".join(lines) + "\n"


def write_evidence_map(repo: Path, task: str, prepass: dict, out_dir: Path) -> Path:
    """Write the Evidence Map atomically; numeric suffix on collision."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = make_slug(task)
    target = out_dir / f"{slug}.md"
    counter = 1
    while target.exists():
        target = out_dir / f"{slug}-{counter}.md"
        counter += 1
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_render(repo, task, prepass))
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write evidence map {target}: {exc}") from exc
    return target


# ---------------------------------------------------------------------------
