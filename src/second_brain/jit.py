"""JIT context compiler (plan §25): deterministic task context capsules.

Compiles the working set (capsule, requirement ledger, read ledger) plus
optional project state into one markdown capsule at
``outputs/context-capsules/<session-id>-<slug>.md``. No model, no network:
identical inputs produce an identical body; only the header's ``compiled_at``
timestamp changes between runs. Missing or corrupt working-set files degrade
to ``(none)`` markers instead of crashing.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from . import registry
from .errors import BrainError
from .registry import Project
from .working_set import (
    CAPSULE_LIST_FIELDS,
    session_dir,
    show_capsule,
    show_reads,
    show_requirements,
)

SLUG_MAX = 40
BODY_MARKER = "# Task"  # the body starts at this line; everything before is header


def make_slug(task: str) -> str:
    """Slugify a task: lowercase, non-alphanumerics -> '-', max 40 chars.

    Empty or all-punctuation tasks fall back to ``'task'``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")
    return slug[:SLUG_MAX].rstrip("-") or "task"


def _rel(home: Path, path: Path) -> str:
    try:
        return path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _load_or_none(loader, *args: object) -> dict | list | None:
    try:
        return loader(*args)
    except BrainError:
        return None


def _render_capsule(capsule: dict | None) -> list[str]:
    if capsule is None:
        return ["(none)"]
    lines = [
        f"objective: {capsule['objective']}",
        f"task_mode: {capsule['task_mode']}",
        f"risk: {capsule['risk']}",
    ]
    for field in CAPSULE_LIST_FIELDS:
        if capsule[field]:
            lines.append(f"{field}: {'; '.join(capsule[field])}")
    if capsule["verification"]:
        pairs = [f"{key}={value}" for key, value in capsule["verification"].items()]
        lines.append(f"verification: {'; '.join(pairs)}")
    if capsule["next_action"]:
        lines.append(f"next_action: {capsule['next_action']}")
    lines.append(f"updated_at: {capsule['updated_at']}")
    return lines


def _project_files(
    home: Path, project_key: str | None
) -> tuple[Project | None, list[str]]:
    """Resolve the project directory. Returns (proj, source_paths)."""
    if project_key is None:
        return None, []
    try:
        proj = registry.get_project(home, project_key)
    except BrainError:
        return None, []
    return proj, [f"projects/{proj.id}/current-state.md", f"projects/{proj.id}/lexicon.md"]


def _project_state(home: Path, proj: Project | None) -> list[str]:
    if proj is None:
        return ["(none)"]
    state_file = Path(home) / "projects" / proj.id / "current-state.md"
    try:
        if not state_file.is_file():
            return ["(none)"]
        text = state_file.read_text(encoding="utf-8").rstrip("\n")
    except OSError:
        return ["(none)"]
    return text.splitlines() if text else ["(none)"]


def _lexicon_matches(home: Path, proj: Project | None, task: str) -> list[str]:
    if proj is None:
        return ["(none)"]
    lex_file = Path(home) / "projects" / proj.id / "lexicon.md"
    try:
        if not lex_file.is_file():
            return ["(none)"]
        text = lex_file.read_text(encoding="utf-8")
    except OSError:
        return ["(none)"]
    lines = text.splitlines()
    headings = [i for i, line in enumerate(lines) if line.startswith("## ")]
    task_lower = task.lower()
    blocks: list[list[str]] = []
    for index in headings:
        term = lines[index][3:].strip()
        words = re.findall(r"[a-z0-9]+", term.lower())
        matched = any(
            re.search(rf"\b{re.escape(word)}\b", task_lower) for word in words
        )
        if not matched:
            continue
        end = next((j for j in headings if j > index), len(lines))
        block = lines[index:end]
        while block and not block[-1].strip():
            block.pop()
        blocks.append(block)
    if not blocks:
        return ["No matching terms."]
    out: list[str] = []
    for block in blocks:
        out.extend(block)
        out.append("")
    return out[:-1]  # drop the trailing separator blank line


def compile_context(
    home: Path,
    session_id: str,
    task: str,
    project_key: str | None = None,
) -> Path:
    """Compile the task context capsule. Returns its path."""
    if not isinstance(task, str):
        raise BrainError("task must be a string")
    session = session_dir(home, session_id)
    proj, project_sources = _project_files(home, project_key)

    header = [
        "# Task Context Capsule",
        "",
        f"compiled_at: {datetime.now(UTC).isoformat()}",
        "sources:",
        f"- {_rel(home, session / 'active-state.json')}",
        f"- {_rel(home, session / 'requirements.json')}",
        f"- {_rel(home, session / 'read-ledger.json')}",
        *[f"- {source}" for source in project_sources],
    ]

    capsule = _load_or_none(show_capsule, home, session_id)
    requirements = _load_or_none(show_requirements, home, session_id)
    reads = _load_or_none(show_reads, home, session_id) or []

    body: list[str] = []
    body.append(BODY_MARKER)
    body.append("")
    body.append(task.strip() if task.strip() else "(none)")
    body.append("")

    body.append("# Requirements")
    body.append("")
    if requirements:
        for entry in requirements:
            body.append(
                f"- {entry['id']} [{entry['importance']}/{entry['status']}] "
                f"{entry['requirement']}"
            )
            for evidence in entry["evidence"]:
                body.append(f"  - {evidence}")
    else:
        body.append("(none)")
    body.append("")

    body.append("# Active State")
    body.append("")
    body.extend(_render_capsule(capsule))
    body.append("")

    body.append("# Project State")
    body.append("")
    body.extend(_project_state(home, proj))
    body.append("")

    body.append("# Lexicon Matches")
    body.append("")
    body.extend(_lexicon_matches(home, proj, task))
    body.append("")

    body.append("# Read Ledger Summary")
    body.append("")
    body.append(f"count: {len(reads)}")
    if reads:
        for entry in reads[-10:]:
            body.append(f"- {entry['path']} (purpose: {entry['purpose']})")
    else:
        body.append("(none)")

    output = home / "outputs" / "context-capsules" / f"{session_id}-{make_slug(task)}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join([*header, "", *body]) + "\n", encoding="utf-8", newline="\n"
    )
    return output
