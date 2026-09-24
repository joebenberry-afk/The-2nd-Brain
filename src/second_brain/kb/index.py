"""Derived SQLite FTS5 index for Brain records (V3 core).

The index is rebuilt from the record files on every search; it is never canonical.
It powers full-text search with ranking and record metadata.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import projects, records
from .records import Record, RecordError


def index_path(home: Path) -> Path:
    """Path to the derived SQLite database."""
    return Path(home) / "db" / "kb.sqlite"


def connect(home: Path) -> sqlite3.Connection:
    """Create connection; initialize schema if missing."""
    path = index_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kb_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS kb_records (
            id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
            id UNINDEXED,
            title,
            terms,
            body,
            tokenize='unicode61'
        );
    """)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM kb_meta WHERE key = 'schema_version'")
    result = cursor.fetchone()
    if result is None:
        cursor.execute("INSERT INTO kb_meta (key, value) VALUES ('schema_version', '1')")
        conn.commit()
    return conn


@dataclass
class RefreshReport:
    """Result of a refresh operation."""

    added: int
    updated: int
    removed: int
    errors: list[str]


STOPWORDS = frozenset(
    {
        "the",
        "and",
        "what",
        "which",
        "how",
        "does",
        "did",
        "with",
        "for",
        "from",
        "this",
        "that",
        "these",
        "those",
        "into",
        "about",
        "please",
        "tell",
        "show",
        "give",
        "explain",
        "need",
        "want",
        "use",
        "using",
        "make",
        "can",
        "could",
        "would",
        "should",
        "will",
        "just",
        "only",
        "also",
        "any",
        "all",
        "some",
        "our",
        "your",
        "you",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "not",
        "but",
        "why",
        "when",
        "where",
        "who",
        "there",
        "here",
        "then",
        "than",
        "them",
        "they",
        "its",
        "been",
        "being",
        "more",
        "most",
        "other",
        "such",
        "very",
        "reply",
        "answer",
        "line",
        "lines",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "by",
        "or",
        "an",
        "as",
        "is",
        "be",
        "go",
        "do",
        "if",
        "up",
        "out",
        "at",
        "to",
        "in",
        "on",
        "it",
        "he",
        "she",
        "we",
        "me",
    }
)


def tokens(text: str) -> list[str]:
    """Extract tokens from text: 3+ alphanumeric, lowercased, no stopwords, duplicates removed."""
    found = re.findall(r"[a-z0-9]{3,}", text.casefold())
    seen = set()
    result = []
    for token in found:
        if token not in STOPWORDS and token not in seen:
            result.append(token)
            seen.add(token)
    return result


def refresh(home: Path) -> RefreshReport:
    """Refresh index from record files: insert/update/delete as needed."""
    conn = connect(home)
    try:
        loaded_records, load_errors = records.load_all(home)

        # Build a set of currently indexed records and their SHA256s
        cursor = conn.cursor()
        cursor.execute("SELECT id, sha256 FROM kb_records")
        indexed = {row[0]: row[1] for row in cursor.fetchall()}

        # Build a map of current records and their SHA256s
        import hashlib

        current = {}
        for record in loaded_records:
            record_bytes = records.dumps(record).encode("utf-8")
            sha = hashlib.sha256(record_bytes).hexdigest()
            current[record.id] = (sha, record_bytes, record)

        # Determine what changed
        added = 0
        updated = 0
        removed = 0

        with conn:
            # Insert or update
            for record_id, (sha, _record_bytes, record) in current.items():
                text_content = records.dumps(record)
                if record_id not in indexed:
                    # New record
                    conn.execute(
                        "INSERT INTO kb_records (id, sha256, text) VALUES (?, ?, ?)",
                        (record_id, sha, text_content),
                    )
                    added += 1
                elif indexed[record_id] != sha:
                    # Updated record
                    conn.execute(
                        "UPDATE kb_records SET sha256 = ?, text = ? WHERE id = ?",
                        (sha, text_content, record_id),
                    )
                    updated += 1

            # Delete records whose files are gone
            for record_id in indexed:
                if record_id not in current:
                    conn.execute("DELETE FROM kb_records WHERE id = ?", (record_id,))
                    removed += 1

            # Keep the FTS rows in step with kb_records: only changed and removed ids.
            changed = [
                record
                for record_id, (sha, _bytes, record) in current.items()
                if indexed.get(record_id) != sha
            ]
            gone = [record_id for record_id in indexed if record_id not in current]
            for record_id in [r.id for r in changed] + gone:
                conn.execute("DELETE FROM kb_fts WHERE id = ?", (record_id,))
            for record in changed:
                conn.execute(
                    "INSERT INTO kb_fts (id, title, terms, body) VALUES (?, ?, ?, ?)",
                    (record.id, record.title, _terms_text(record), record.body),
                )

        return RefreshReport(added=added, updated=updated, removed=removed, errors=load_errors)
    finally:
        conn.close()


def _terms_text(record: Record) -> str:
    """The FTS ``terms`` column: explicit terms, triggers, domains and the record type."""
    return " ".join(
        [
            *record.terms,
            *record.trigger_errors,
            *record.trigger_paths,
            *record.domains,
            record.type,
        ]
    )


def rebuild(home: Path) -> RefreshReport:
    """Delete the index file and refresh."""
    index_path(home).unlink(missing_ok=True)
    return refresh(home)


@dataclass
class Hit:
    """Search result with the matched record, rank, and which tokens matched."""

    record: Record
    score: float
    matched: tuple[str, ...]


def search(
    home: Path,
    query: str,
    project: projects.Project | None,
    *,
    all_projects: bool = False,
    include_history: bool = False,
    as_of: str | None = None,
    limit: int = 3,
) -> list[Hit]:
    """Full-text search with ranking and filtering."""
    from datetime import datetime

    # Tokenize query
    toks = tokens(query)
    if not toks:
        return []

    # Clamp limit
    limit = max(1, min(10, limit))

    # Parse as_of if given
    as_of_dt: datetime | None = None
    if as_of:
        as_of_dt = records.parse_time(as_of)
        # Check it's not in the future
        now = records.parse_time(records.now_iso())
        if as_of_dt > now:
            raise RecordError(f"as_of time cannot be in the future: {as_of}")

    # Refresh the index
    refresh(home)

    conn = connect(home)
    try:
        # Build FTS query
        fts_expr = " OR ".join(f'"{t}"*' for t in toks)

        # FTS search with BM25 ranking
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, bm25(kb_fts, 0.0, 5.0, 3.0, 1.0) FROM kb_fts WHERE kb_fts MATCH ? "
            "ORDER BY 2 LIMIT 200",
            (fts_expr,),
        )
        candidates = cursor.fetchall()

        # Filter and rank results
        results: list[Hit] = []
        for candidate_id, bm25_score in candidates:
            try:
                record = records.load(home, candidate_id)
            except RecordError:
                continue

            # Check scope visibility
            if not all_projects and not projects.visible(record, project):
                continue

            # Check time and status filters
            if as_of_dt:
                # Include if start <= as_of_dt
                # (active or superseded with superseded_at > as_of_dt)
                start = record.valid_from or record.recorded_at
                start_dt = records.parse_time(start)
                if start_dt > as_of_dt:
                    continue
                if record.status == "retracted":
                    continue
                if record.status == "superseded":
                    if record.superseded_at:
                        superseded_dt = records.parse_time(record.superseded_at)
                        if superseded_dt <= as_of_dt:
                            continue
                    else:
                        continue
            else:
                # Default: only active records
                if not include_history and not record.active:
                    continue

            # Check matching rule: need enough matched tokens
            # Extract all words from title + terms + body
            all_text = f"{record.title} {_terms_text(record)} {record.body}".casefold()
            words = re.findall(r"[a-z0-9]{3,}", all_text)
            matched_list = []
            for tok in toks:
                for word in words:
                    if word.startswith(tok):
                        matched_list.append(tok)
                        break

            min_matched = 1 if len(toks) <= 2 else 2
            if len(matched_list) < min_matched:
                continue

            results.append(Hit(record=record, score=bm25_score, matched=tuple(matched_list)))

        # Return first limit results
        return results[:limit]
    finally:
        conn.close()


def render_hit(hit: Hit) -> str:
    """Render a hit as a single line (≤ 240 chars)."""
    record = hit.record
    line = f"{record.id} [{record.type} {record.status}/{record.effective_grade}] {record.title}"

    # Add first evidence if any
    if record.evidence:
        line += f" — {record.evidence[0]}"

    # Add supersession info if applicable
    if record.status == "superseded":
        superseded_by = record.superseded_by or "nothing"
        superseded_at = record.superseded_at[:10] if record.superseded_at else ""
        line += f" (superseded by {superseded_by} on {superseded_at})"

    # Truncate if needed
    if len(line) > 240:
        line = line[:237] + "…"

    return line


def add(
    home: Path,
    *,
    title: str,
    body: str,
    type: str,
    scope: str,
    project: str | None,
    domains: tuple[str, ...] = (),
    grade: str = "OBSERVED",
    evidence: tuple[str, ...] = (),
    trigger_paths: tuple[str, ...] = (),
    trigger_errors: tuple[str, ...] = (),
    terms: tuple[str, ...] = (),
    valid_from: str | None = None,
    private: bool = False,
) -> Record:
    """Add a new record (candidate status)."""
    if grade == "VERIFIED":
        raise RecordError("VERIFIED requires independent attestation; record TESTED")

    record = Record(
        id=records.new_id(),
        title=title,
        body=body,
        type=type,
        scope=scope,
        project=project,
        domains=domains,
        grade=grade,
        evidence=evidence,
        trigger_paths=trigger_paths,
        trigger_errors=trigger_errors,
        terms=terms,
        valid_from=valid_from,
        private=private,
        status="candidate",
        recorded_at=records.now_iso(),
    )

    records.save(home, record)
    refresh(home)
    from . import views

    views.compile_views(home)
    return record


def promote(home: Path, record_id: str, *, reason: str) -> Record:
    """Promote a candidate record to current."""
    record = records.load(home, record_id)

    if record.status != "candidate":
        raise RecordError(f"{record_id}: only candidate records can be promoted")
    if not record.evidence:
        raise RecordError("promotion needs evidence")
    if not reason.strip():
        raise RecordError("promotion reason required")

    # Update the record
    updated = records.replace(
        record,
        status="current",
        extra={
            **record.extra,
            "promoted_at": records.now_iso(),
            "promotion_reason": reason,
        },
    )

    records.save(home, updated)
    refresh(home)
    from . import views

    views.compile_views(home)
    return updated


def supersede(
    home: Path,
    old_id: str,
    *,
    by: str,
    reason: str,
    kind: str = "supersedes",
    effective_at: str | None = None,
) -> tuple[Record, Record]:
    """Supersede one record with another (old, new)."""
    # Validate inputs
    if not reason.strip():
        raise RecordError("supersede reason required")
    if kind not in ("supersedes", "corrects"):
        raise RecordError("kind must be supersedes or corrects (use retire to invalidate)")
    if by == old_id:
        raise RecordError("cannot supersede a record with itself")

    # Load records
    old_record = records.load(home, old_id)
    new_record = records.load(home, by)

    # Check both are active
    if not old_record.active:
        raise RecordError(f"{old_id}: cannot supersede inactive record")
    if not new_record.active:
        raise RecordError(f"{by}: cannot supersede with inactive record")

    # Parse effective_at
    if effective_at is None:
        effective_at = records.now_iso()
    else:
        try:
            effective_dt = records.parse_time(effective_at)
            now = records.parse_time(records.now_iso())
            if effective_dt > now:
                raise RecordError(f"effective_at cannot be in the future: {effective_at}")
        except RecordError:
            raise

    # Check grade rank
    new_grade = new_record.effective_grade
    old_grade = old_record.effective_grade
    if records.GRADE_RANK.get(new_grade, 0) < records.GRADE_RANK.get(old_grade, 0):
        msg = f"WEAKER_REPLACEMENT: {new_grade} cannot replace {old_grade}"
        raise RecordError(msg)

    # Check scope compatibility
    if old_record.scope == "global":
        if new_record.scope != "global":
            raise RecordError("SCOPE_MISMATCH: global record requires global replacement")
    elif old_record.scope == "project":
        # New must be visible to old's project
        old_proj = projects.Project(id=old_record.project or "", name="")
        if not projects.visible(new_record, old_proj):
            raise RecordError("SCOPE_MISMATCH: new record not visible to old record's project")
    elif old_record.scope == "domain":
        # New must be global or domain with superset of old's domains
        if new_record.scope == "global":
            pass  # OK
        elif new_record.scope == "domain":
            old_domains = set(old_record.domains)
            new_domains = set(new_record.domains)
            if not old_domains.issubset(new_domains):
                raise RecordError(
                    "SCOPE_MISMATCH: new domain record must have superset of old domains"
                )
            # Also check project match when old has no domains
            if not old_domains and old_record.project != new_record.project:
                raise RecordError("SCOPE_MISMATCH: project mismatch for legacy domain record")
        else:
            raise RecordError("SCOPE_MISMATCH: domain record requires global or domain replacement")

    # Write new record first (with supersedes list)
    new_supersedes = list(new_record.supersedes)
    if old_id not in new_supersedes:
        new_supersedes.append(old_id)
    new_updated = records.replace(new_record, supersedes=tuple(new_supersedes))
    records.save(home, new_updated)

    # Write old record (mark as superseded)
    old_updated = records.replace(
        old_record,
        status="superseded",
        superseded_by=by,
        supersession_kind=kind,
        supersession_reason=reason,
        superseded_at=effective_at,
    )
    records.save(home, old_updated)

    refresh(home)
    from . import views

    views.compile_views(home)
    return old_updated, new_updated


def retire(home: Path, record_id: str, *, reason: str, effective_at: str | None = None) -> Record:
    """Retire (invalidate) a record."""
    record = records.load(home, record_id)

    if not record.active:
        raise RecordError(f"{record_id}: cannot retire inactive record")
    if not reason.strip():
        raise RecordError("retire reason required")

    if effective_at is None:
        effective_at = records.now_iso()
    elif records.parse_time(effective_at) > records.parse_time(records.now_iso()):
        raise RecordError(f"effective_at cannot be in the future: {effective_at}")

    updated = records.replace(
        record,
        status="superseded",
        supersession_kind="invalidates",
        supersession_reason=reason,
        superseded_at=effective_at,
    )

    records.save(home, updated)
    refresh(home)
    from . import views

    views.compile_views(home)
    return updated


def successor(home: Path, record_id: str) -> str | None:
    """Follow the supersession chain; return the current record id or None if invalidated."""
    visited = set()
    current = record_id

    for _ in range(64):
        if current in visited:
            raise RecordError(f"supersession loop detected at {current}")
        visited.add(current)

        try:
            record = records.load(home, current)
        except RecordError:
            return None

        if record.status != "superseded":
            # It's active or retracted
            if record.active:
                return current
            else:
                return None

        # Follow the chain
        if record.supersession_kind == "invalidates":
            return None
        if not record.superseded_by:
            return None

        current = record.superseded_by

    raise RecordError(f"supersession chain too long for {record_id}")
