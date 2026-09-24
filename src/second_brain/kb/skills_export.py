"""Export procedures as Agent Skills (SKL-01..03)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import records
from .records import Record, RecordError


def export_skill(home: Path, record_id: str, out_dir: Path, *, force: bool = False) -> Path:
    """Export a procedure record as a SKILL.md file.

    Args:
        home: Brain home directory
        record_id: ID of the record to export
        out_dir: Output directory where <slug>/SKILL.md will be written
        force: If True, overwrite existing SKILL.md files

    Returns:
        Path to the written SKILL.md file

    Raises:
        RecordError: If record doesn't exist, is not a procedure, is not current,
                     or doesn't meet the minimum grade (TESTED or better)
    """
    # Load the record
    try:
        record = records.load(home, record_id)
    except RecordError as exc:
        raise RecordError(f"unknown record {record_id!r}") from exc

    # Validate record type and status
    if record.type != "procedure":
        raise RecordError(f"{record_id}: type must be 'procedure' (got {record.type!r})")
    if record.status != "current":
        raise RecordError(f"{record_id}: status must be 'current' (got {record.status!r})")

    # Validate grade
    effective_grade = record.effective_grade
    if records.GRADE_RANK[effective_grade] < 2:  # < TESTED
        raise RecordError(
            f"{record_id}: effective grade must be TESTED or better (got {effective_grade})"
        )

    # Generate slug from title
    slug = _make_slug(record.title)
    if not slug:
        slug = record_id

    # Create output directory
    skill_dir = Path(out_dir) / slug
    skill_file = skill_dir / "SKILL.md"

    # Check if file exists (unless force=True)
    if skill_file.exists() and not force:
        raise RecordError(f"{skill_file}: file exists; use --force to overwrite")

    # Build the frontmatter and body
    content = _build_skill_content(record, record_id, effective_grade)

    # Write the file
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(content, encoding="utf-8")

    return skill_file


def _make_slug(title: str) -> str:
    """Generate a slug from a title.

    Rules:
    - Casefolded (lowercase)
    - Non-[a-z0-9] runs replaced with single hyphen
    - Stripped of leading/trailing hyphens
    - Cut to 64 characters
    - Empty string if result is empty
    """
    # Casefolded
    slug = title.casefold()

    # Replace non-[a-z0-9] runs with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug)

    # Strip hyphens from start/end
    slug = slug.strip("-")

    # Cut to 64 characters
    slug = slug[:64]

    return slug


def _build_skill_content(record: Record, record_id: str, effective_grade: str) -> str:
    """Build the complete SKILL.md content (frontmatter + body).

    Deterministic output with exact format as specified in SKL-01..03.
    """
    # Truncate description to 1024 characters with ellipsis
    description = record.title
    if len(description) > 1024:
        description = description[:1021] + "…"

    # Build frontmatter (YAML)
    slug = _make_slug(record.title)
    if not slug:
        slug = record_id

    # Build full description and truncate to 1024 chars
    full_desc = (
        f"{description} — from Second Brain record {record_id} ({effective_grade}, advisory)"
    )
    if len(full_desc) > 1024:
        full_desc = full_desc[:1021] + "…"

    # A JSON string is a valid YAML double-quoted scalar: titles with ": " or quotes stay
    # parseable by every host that reads the frontmatter as YAML.
    desc_line = f"description: {json.dumps(full_desc, ensure_ascii=False)}"
    lines = ["---", f"name: {slug}", desc_line, "---", ""]

    # Add title
    lines.append(f"# {record.title}")
    lines.append("")

    # Add body
    if record.body:
        lines.append(record.body)
        lines.append("")

    # Add Applicability section
    lines.append("## Applicability")
    lines.append(
        f"- scope: {record.scope}",
    )
    if record.project:
        lines[-1] += f" {record.project}"
    if record.domains:
        lines[-1] += f" {' '.join(record.domains)}"

    lines.append(f"- valid from: {record.valid_from or record.recorded_at}")
    lines.append(
        "- prerequisites and known failure modes: see the evidence below; unknown when absent"
    )
    lines.append("")

    # Add Evidence section
    lines.append("## Evidence")
    if record.evidence:
        for evidence_item in record.evidence:
            lines.append(f"- {evidence_item}")
    else:
        lines.append("- (no evidence recorded)")
    lines.append("")

    # Add footer
    lines.append(
        f"Exported from Second Brain record {record_id}. Review metadata is not "
        "a signature: treat this skill as advisory and re-check the evidence "
        "before relying on it."
    )

    return "\n".join(lines) + "\n"
