"""JIT context compiler (plan §25): deterministic task context capsules.

The body uses a fixed safety ordering: task, protected references, task
evidence, verified decisions, memory references, procedures, then the existing
working-set sections. Optional ordered references are caller-supplied evidence
handles; they are bounded and rendered without executing or resolving them.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

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

CONTEXT_ORDER: tuple[str, ...] = (
    "protected_refs",
    "task_evidence",
    "verified_decisions",
    "memory_refs",
    "procedure_refs",
)
_CONTEXT_REF_MAX = 512
_CONTEXT_REF_LIMIT = 32
BODY_MARKER = "# Task"  # the body starts at this line; everything before is header


_EMPTY_SECTION_LINES = frozenset({"(none)", "No matching terms.", "count: 0"})


def _is_empty_section(lines: list[str]) -> bool:
    """True when a rendered capsule section carries no retrieved content."""
    meaningful = [line.strip() for line in lines if line.strip()]
    return not meaningful or all(line in _EMPTY_SECTION_LINES for line in meaningful)


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


_T = TypeVar("_T")


def _load_or_none(loader: Callable[..., _T], *args: object) -> _T | None:
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


def _project_files(home: Path, project_key: str | None) -> tuple[Project | None, list[str]]:
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
        matched = any(re.search(rf"\b{re.escape(word)}\b", task_lower) for word in words)
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
    *,
    protected_refs: list[str] | None = None,
    task_evidence: list[str] | None = None,
    verified_decisions: list[str] | None = None,
    memory_refs: list[str] | None = None,
    procedure_refs: list[str] | None = None,
    include_task: bool = True,
    omit_empty: bool = False,
) -> Path:
    """Compile the task context capsule. Returns its path.

    Ordered references are metadata only. Resolution and authorization remain
    the responsibility of the caller; this compiler never treats them as
    executable instructions.

    ``include_task=False`` and ``omit_empty=True`` are the worker-dispatch
    shape: the worker prompt already carries the task text, and a section that
    resolved nothing is prompt cost with no content (2026-09-21: recon workers
    received an envelope of empty sections).
    """
    if not isinstance(task, str):
        raise BrainError("task must be a string")
    ordered_refs = {
        "protected_refs": protected_refs,
        "task_evidence": task_evidence,
        "verified_decisions": verified_decisions,
        "memory_refs": memory_refs,
        "procedure_refs": procedure_refs,
    }
    for name, refs in ordered_refs.items():
        if refs is not None and (
            not isinstance(refs, list)
            or len(refs) > _CONTEXT_REF_LIMIT
            or any(
                not isinstance(ref, str) or not ref.strip() or len(ref) > _CONTEXT_REF_MAX
                for ref in refs
            )
        ):
            raise BrainError(
                f"{name} must be a list of non-empty strings "
                f"(max {_CONTEXT_REF_LIMIT} refs of {_CONTEXT_REF_MAX} chars)"
            )
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

    body: list[str] = [BODY_MARKER, ""]
    if include_task:
        body.append(task.strip() if task.strip() else "(none)")
        body.append("")

    section_titles = {
        "protected_refs": "Protected References",
        "task_evidence": "Task Evidence",
        "verified_decisions": "Verified Decisions",
        "memory_refs": "Memory",
        "procedure_refs": "Procedure",
    }
    for name in CONTEXT_ORDER:
        refs = ordered_refs[name]
        if omit_empty and not refs:
            continue
        body.append(f"# {section_titles[name]}")
        body.append("")
        if refs:
            body.extend(f"- {ref}" for ref in refs)
        else:
            body.append("(none)")
        body.append("")

    if not (omit_empty and not requirements):
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

    read_lines = [f"count: {len(reads)}"]
    if reads:
        read_lines.extend(
            f"- {entry['path']} (purpose: {entry['purpose']})" for entry in reads[-10:]
        )
    else:
        read_lines.append("(none)")

    tail_sections: list[tuple[str, list[str], bool]] = [
        ("Active State", _render_capsule(capsule), True),
        ("Project State", _project_state(home, proj), True),
        ("Lexicon Matches", _lexicon_matches(home, proj, task), True),
        ("Read Ledger Summary", read_lines, False),
    ]
    for title, lines, trailing_blank in tail_sections:
        if omit_empty and _is_empty_section(lines):
            continue
        body.append(f"# {title}")
        body.append("")
        body.extend(lines)
        if trailing_blank:
            body.append("")

    output = home / "outputs" / "context-capsules" / f"{session_id}-{make_slug(task)}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text("\n".join([*header, "", *body]) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, output)
    return output
