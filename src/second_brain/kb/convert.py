"""Convert legacy Brain V2 SQLite database to V3 record files.

Reads from legacy home directory and SQLite database, writes records to new home.
Supports import_native from Claude Code MEMORY.md files.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import records


@dataclass
class ConvertReport:
    """Report from a conversion run."""

    written: int
    skipped: list[str]
    by_status: dict[str, int]
    errors: list[str]


def convert(
    db_path: str | Path,
    legacy_home: Path,
    out_home: Path,
    *,
    dry_run: bool = False,
) -> ConvertReport:
    """Convert the legacy ``memories`` store (schema ≤ 29) into record files.

    The legacy database is opened read-only and never changed. Existing record files in
    ``out_home`` are never overwritten, so a re-run only reports them as ``exists``. Values the
    legacy store never held (record type, valid time) are left at their defaults rather than
    guessed; a legacy row that cannot form a valid record is reported, not written.
    """
    report = ConvertReport(written=0, skipped=[], by_status={}, errors=[])
    try:
        conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        report.errors.append(f"cannot open {db_path}: {exc}")
        return report
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "memories" not in tables:
            report.errors.append("no memories table")
            return report
        rows = [dict(r) for r in conn.execute("SELECT * FROM memories ORDER BY memory_id")]
        sources: dict[str, list[dict]] = {}
        if "memory_sources" in tables:
            for r in conn.execute("SELECT * FROM memory_sources ORDER BY id"):
                sources.setdefault(r["memory_id"], []).append(dict(r))
        links: dict[str, dict] = {}
        if "memory_supersessions" in tables:
            links = {
                r["old_memory_id"]: dict(r)
                for r in conn.execute("SELECT * FROM memory_supersessions")
            }
    except sqlite3.Error as exc:
        report.errors.append(f"cannot read {db_path}: {exc}")
        return report
    finally:
        conn.close()

    replaced: dict[str, list[str]] = {}
    for old_id, link in links.items():
        if link.get("new_memory_id"):
            replaced.setdefault(link["new_memory_id"], []).append(old_id)

    for row in rows:
        memory_id = str(row.get("memory_id") or "")
        if records.record_path(out_home, memory_id).is_file():
            report.skipped.append(f"{memory_id}: exists")
            continue
        try:
            rec = _record_from_row(
                row,
                legacy_home,
                links.get(memory_id),
                sources.get(memory_id, []),
                tuple(sorted(replaced.get(memory_id, []))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            report.errors.append(f"{memory_id}: {exc}")
            continue
        problems = records.validate(rec)
        if problems:
            report.errors.append(f"{memory_id}: " + "; ".join(problems))
            continue
        if not dry_run:
            records.write_atomic(records.record_path(out_home, memory_id), records.dumps(rec))
        report.written += 1
        report.by_status[rec.status] = report.by_status.get(rec.status, 0) + 1
    return report


_UNKNOWN_PROJECTS = ("", "default", "unknown")


def _legacy_body(legacy_home: Path, row: dict) -> str:
    body_path = row.get("body_path")
    if body_path:
        try:
            text = (legacy_home / str(body_path).replace("\\", "/")).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = None
        if text is not None:
            text = text.replace("\r\n", "\n")
            if text.startswith("---\n") and "\n---" in text[3:]:
                text = text[3:].split("\n---", 1)[1]
            return text.strip()
    return str(row.get("summary") or "").strip()


def _evidence(sources: list[dict]) -> tuple[str, ...]:
    items: list[str] = []
    for src in sources:
        path = str(src.get("path") or "").strip()
        blob = str(src.get("blob_sha") or "").strip()
        repo = str(src.get("repo_id") or "").strip()
        if path:
            item = f"{path}@{blob[:12]}" if blob else path
            if repo:
                item += f" (repo {repo})"
        else:
            item = str(src.get("source_ref") or "").strip()
        if item:
            items.append(item)
    return tuple(dict.fromkeys(items))


def _record_from_row(
    row: dict,
    legacy_home: Path,
    link: dict | None,
    sources: list[dict],
    supersedes: tuple[str, ...],
) -> records.Record:
    extra: dict[str, str] = {}
    title = " ".join(str(row["title"]).split())
    if len(title) > records._TITLE_MAX:
        title = title[: records._TITLE_MAX - 1] + "…"
        extra["legacy_title_truncated"] = "true"

    scope = str(row["scope"])
    raw_project = str(row.get("project_id") or "").strip()
    project: str | None = raw_project if raw_project.lower() not in _UNKNOWN_PROJECTS else None
    if scope == "project" and project is None:
        project = "unknown"  # stays invisible: fail closed, never widened

    status = {"current": "current", "candidate": "candidate", "labile": "candidate"}.get(
        str(row["status"]), str(row["status"])
    )
    if row["status"] == "labile":
        extra["legacy_status"] = "labile"
    if row["status"] == "archived":
        status = "retracted"
        extra["legacy_status"] = "archived"

    grade = str(row["evidence_grade"])
    if grade == "REJECTED":
        grade, status = "HISTORICAL", "retracted"
        extra["legacy_grade"] = "REJECTED"
    if row.get("grade_attestation"):
        extra["legacy_attestation"] = "present"

    kind = reason = superseded_by = superseded_at = None
    if status == "superseded":
        if link is not None:
            kind = str(link["kind"])
            reason = str(link["reason"])
            superseded_by = link.get("new_memory_id") or None
            superseded_at = str(link["effective_at"])
        else:
            kind = "invalidates"
            reason = "legacy status superseded; replacement not recorded"
            superseded_at = str(row["updated_at"])

    return records.Record(
        id=str(row["memory_id"]),
        title=title,
        type="fact",
        scope=scope,
        project=project,
        status=status,
        grade=grade,
        attested=False,
        recorded_at=str(row["created_at"]),
        supersedes=supersedes,
        superseded_by=superseded_by,
        supersession_kind=kind,
        supersession_reason=reason,
        superseded_at=superseded_at,
        evidence=_evidence(sources),
        origin=row.get("origin_class") or None,
        authority=str(row.get("authority_ceiling") or "advisory"),
        body=_legacy_body(legacy_home, row),
        extra=extra,
    )


def import_native(
    home: Path,
    memory_md: Path,
    project: str | None = None,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Import bullet points from a Claude Code MEMORY.md into records.

    Each bullet line (- or *) becomes a candidate fact record with:
    - grade: OBSERVED
    - scope: project (if project given) else global
    - evidence: native-memory:{filename}
    - title: the bullet text, cut to 200 chars

    Skips bullets whose normalized text equals an existing record title in home.
    Returns list of new record ids.
    """
    new_ids = []

    try:
        text = memory_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return new_ids

    # Load existing records to check for duplicates
    existing_records, _ = records.load_all(home)
    existing_titles = {" ".join(r.title.casefold().split()) for r in existing_records}

    # Parse bullet points
    file_name = memory_md.name
    for line in text.split("\n"):
        line = line.rstrip()
        if not line.startswith(("- ", "* ")):
            continue

        # Extract bullet text
        bullet_text = line[2:].strip()
        if not bullet_text:
            continue

        # Normalize for deduplication
        normalized = " ".join(bullet_text.casefold().split())
        if normalized in existing_titles:
            continue

        # Create record
        rec = records.Record(
            id=records.new_id("mem"),
            title=bullet_text[: records._TITLE_MAX],
            type="fact",
            scope="project" if project else "global",
            project=project,
            status="candidate",
            grade="OBSERVED",
            recorded_at=records.now_iso(),
            evidence=(f"native-memory:{file_name}",),
        )

        # Validate
        errors = records.validate(rec)
        if errors:
            continue

        # Write (if not dry-run)
        if not dry_run:
            try:
                records.save(home, rec)
            except records.RecordError:
                continue

        new_ids.append(rec.id)

    return new_ids
