"""Per-project views compiled from records: the session brief and the correction table.

Brief: ≤600 tokens, current status only, ordered by section type, deterministic.
Correction table: error signature → correction record, for constant-time matches in adapters.
"""

from __future__ import annotations

import contextlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from . import projects, records

BRIEF_TOKEN_BUDGET = 600
CORRECTION_TOKEN_BUDGET = 80


def estimate_tokens(text: str) -> int:
    """Estimate tokens as ceil(len(text) / 4)."""
    return math.ceil(len(text) / 4)


def render_brief(
    recs: list[records.Record],
    project: projects.Project | None,
    *,
    native_text: str | None = None,
    budget: int = BRIEF_TOKEN_BUDGET,
) -> str:
    """Render a project brief from current, visible records.

    - Selects status == "current", projects.visible(r, project), effective_grade != HISTORICAL
    - fact records only when effective_grade is TESTED or higher
    - Sections: Active work, Decisions, Gotchas, Where things are, Procedures, Facts
    - Within each section, sort by (valid_from or recorded_at) descending, then id
    - Line: "- {title} [{id}]" plus " (observed)" when effective_grade is OBSERVED or INFERRED
    - Native text dedupe: skip if normalized title is substring of normalized native_text
    - Budget: add lines while estimate_tokens <= budget, always leaving room for footer
    - Nothing selected → ""
    - Same input → byte-identical output
    """
    # Filter: current status, visible to project, not HISTORICAL
    selected = []
    for r in recs:
        if r.status != "current":
            continue
        if not projects.visible(r, project):
            continue
        if r.effective_grade == "HISTORICAL":
            continue
        selected.append(r)

    if not selected:
        return ""

    # Normalize native text for deduplication
    native_norm = ""
    if native_text:
        native_norm = " ".join(native_text.casefold().split()).rstrip(".")

    # Categorize by type
    type_to_records: dict[str, list[records.Record]] = {}
    for r in selected:
        if r.type not in type_to_records:
            type_to_records[r.type] = []
        type_to_records[r.type].append(r)

    # Sort each category: by (valid_from or recorded_at) descending, then id
    for records_list in type_to_records.values():
        records_list.sort(
            key=lambda r: (
                -(records.parse_time(r.valid_from or r.recorded_at).timestamp()),
                r.id,
            )
        )

    # Sections in order: (section_header, record_types, include_marker_fn)
    sections = [
        ("Active work", ["state"], lambda r: True),
        ("Decisions", ["decision"], lambda r: True),
        ("Gotchas", ["gotcha", "correction"], lambda r: True),
        ("Where things are", ["locator"], lambda r: True),
        ("Procedures", ["procedure"], lambda r: True),
        (
            "Facts",
            ["fact"],
            lambda r: records.GRADE_RANK.get(r.effective_grade, 0) >= 2,
        ),
    ]

    # Build the brief
    project_name = project.name or project.id if project else "no project"
    header = (
        f"# Brain brief — {project_name}\n"
        'Current records, advisory — verify before relying. Ask: brain q "<topic>" · '
        "record learnings: brain add"
    )

    blocks: list[tuple[str, list[str]]] = []
    for section_header, type_list, include_marker_fn in sections:
        section_lines: list[str] = []
        for record_type in type_list:
            for r in type_to_records.get(record_type, []):
                if record_type == "fact" and not include_marker_fn(r):
                    continue
                r_norm = " ".join(r.title.casefold().split()).rstrip(".")
                if native_norm and r_norm in native_norm:
                    continue
                marker = " (observed)" if r.effective_grade in ("OBSERVED", "INFERRED") else ""
                section_lines.append(f"- {r.title} [{r.id}]{marker}")
        if section_lines:
            blocks.append((f"## {section_header}", section_lines))

    total = sum(len(lines) for _, lines in blocks)
    if total == 0:
        return ""

    def footer(remaining: int) -> list[str]:
        return [f'(+{remaining} more current records — brain q "<topic>")'] if remaining else []

    # Greedy, in order: a line is kept only if the whole brief, including the footer for
    # whatever is still left out, stays within the budget. The first line that does not fit
    # ends the brief, so the order of what is shown never changes.
    parts = [header]
    shown = 0
    for section_header, lines in blocks:
        opened = False
        for line in lines:
            candidate = [*parts, *([] if opened else ["", section_header]), line]
            if estimate_tokens("\n".join(candidate + footer(total - shown - 1))) > budget:
                return "\n".join(parts + footer(total - shown))
            parts = candidate
            opened = True
            shown += 1
    return "\n".join(parts)


@dataclass
class _CorrectionEntry:
    """Internal representation of a correction table entry."""

    id: str
    scope: str
    project: str | None
    domains: list[str]
    errors: list[str]
    text: str


def correction_table(recs: list[records.Record]) -> list[dict]:
    """Build a correction table from current, high-grade corrections/gotchas.

    Entries with status == "current", type in {correction, gotcha}, non-empty trigger_errors,
    GRADE_RANK[effective_grade] >= 2. Returns list[dict] sorted by id.
    """
    entries = []

    for r in recs:
        if r.status != "current":
            continue
        if r.type not in ("correction", "gotcha"):
            continue
        if not r.trigger_errors:
            continue
        if records.GRADE_RANK.get(r.effective_grade, -1) < 2:
            continue

        # Build text: title, and if room, first sentence of body
        text = r.title
        if r.body:
            first_sentence = r.body.split(".")[0].strip()
            if first_sentence:
                text_candidate = f"{r.title}: {first_sentence}"
                if len(text_candidate) <= CORRECTION_TOKEN_BUDGET * 4:
                    text = text_candidate
        # Cut to budget
        if len(text) > CORRECTION_TOKEN_BUDGET * 4:
            text = text[: CORRECTION_TOKEN_BUDGET * 4 - 1] + "…"

        entry = {
            "id": r.id,
            "scope": r.scope,
            "project": r.project or "",
            "domains": list(r.domains),
            "errors": list(r.trigger_errors),
            "text": text,
        }
        entries.append(entry)

    # Sort by id
    entries.sort(key=lambda e: e["id"])
    return entries


def match_error(
    table: list[dict], error_text: str, project: projects.Project | None
) -> dict | None:
    """Find the best matching correction entry for an error.

    An entry is eligible when the record it represents (id, title, scope, project, domains)
    is visible to project. A pattern starting with "re:" is a case-insensitive regex
    (invalid regexes skipped); otherwise a casefolded substring match. Returns the eligible
    entry with the longest matching pattern; ties → smallest id.
    """
    # Reconstruct record data from entry to check visibility
    best: tuple[int, str, dict] | None = None  # (pattern_len, id, entry)

    for entry in table:
        # Reconstruct record enough to check visibility
        r = records.Record(
            id=entry["id"],
            title=entry.get("text", "").split(":")[0].strip(),
            scope=entry.get("scope", "project"),
            project=entry.get("project") or None,
            domains=tuple(entry.get("domains", [])),
            recorded_at="2026-01-01T00:00:00+00:00",  # dummy
        )

        # Check visibility
        if not projects.visible(r, project):
            continue

        # Try to match each error in the entry
        for error_pattern in entry.get("errors", []):
            match_len = 0

            if error_pattern.startswith("re:"):
                # Regex pattern
                try:
                    pattern = error_pattern[3:].strip()
                    if re.search(pattern, error_text, re.IGNORECASE):
                        match_len = len(pattern)
                except re.error:
                    # Invalid regex, skip
                    continue
            else:
                # Substring match (casefolded)
                error_lower = error_text.casefold()
                pattern_lower = error_pattern.casefold()
                if pattern_lower in error_lower:
                    match_len = len(error_pattern)

            if match_len > 0 and (
                best is None
                or match_len > best[0]
                or (match_len == best[0] and entry["id"] < best[1])
            ):
                best = (match_len, entry["id"], entry)

    return best[2] if best else None


def compile_views(home: Path) -> dict[str, list[str]]:
    """Recompile every project's views and write files.

    - Load all records with records.load_all(home)
    - For every project in projects.load_projects(home) plus key "_none" (project None):
      - Write <home>/views/<key>/brief.md with render_brief
      - Write <home>/views/<key>/corrections.json with entries visible to that project
      - Use records.write_atomic for writes
    - Remove views/<key>/ directories for keys no longer present (only brief.md/corrections.json)
    - Return {key: [paths written]}
    """
    written_paths: dict[str, list[str]] = {}

    # Load records
    all_records, load_errors = records.load_all(home)
    if load_errors:
        # Log errors but continue
        pass

    # Load projects
    project_list = projects.load_projects(home)
    project_keys = {p.id for p in project_list}
    project_keys.add("_none")  # Add None key

    # Map: project id → Project (or None for _none)
    project_map: dict[str, projects.Project | None] = {p.id: p for p in project_list}
    project_map["_none"] = None

    # Generate views for each project
    for key in sorted(project_keys):
        project = project_map[key]
        views_dir = Path(home) / "views" / key
        written = []

        # Write brief.md
        brief = render_brief(all_records, project)
        brief_path = views_dir / "brief.md"
        if brief:
            records.write_atomic(brief_path, brief + "\n")
        else:
            records.write_atomic(brief_path, "")
        written.append(str(brief_path))

        # Write corrections.json
        corrections = correction_table(all_records)
        # Filter to entries visible to this project
        visible_corrections = []
        for entry in corrections:
            r = records.Record(
                id=entry["id"],
                title="",
                scope=entry.get("scope", "project"),
                project=entry.get("project") or None,
                domains=tuple(entry.get("domains", [])),
                recorded_at="2026-01-01T00:00:00+00:00",
            )
            if projects.visible(r, project):
                visible_corrections.append(entry)

        corr_path = views_dir / "corrections.json"
        if visible_corrections:
            records.write_atomic(
                corr_path,
                json.dumps(visible_corrections, indent=1, sort_keys=True) + "\n",
            )
        else:
            # Write empty array
            records.write_atomic(corr_path, "[]\n")
        written.append(str(corr_path))

        written_paths[key] = written

    # Project map for hosts that cannot parse TOML (the OMP extension): normalized paths.
    project_index = [
        {
            "id": p.id,
            "name": p.name,
            "paths": sorted({projects.normalize_path(path) for path in p.paths}),
            "git_remote": p.git_remote,
        }
        for p in sorted(project_list, key=lambda item: item.id)
    ]
    records.write_atomic(
        Path(home) / "views" / "projects.json",
        json.dumps(project_index, indent=1, sort_keys=True) + "\n",
    )

    # Clean up stale directories
    views_base = Path(home) / "views"
    if views_base.is_dir():
        for old_key_dir in views_base.iterdir():
            if old_key_dir.is_dir():
                key = old_key_dir.name
                if key not in project_keys:
                    # Remove only brief.md and corrections.json
                    brief_file = old_key_dir / "brief.md"
                    corr_file = old_key_dir / "corrections.json"
                    brief_file.unlink(missing_ok=True)
                    corr_file.unlink(missing_ok=True)
                    # Remove directory if empty
                    with contextlib.suppress(OSError):
                        old_key_dir.rmdir()

    return written_paths
