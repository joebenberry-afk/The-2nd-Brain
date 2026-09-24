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


#: How long a write lock held by another process is waited for before giving up.
LOCK_TIMEOUT_S = 5.0

_SCHEMA = """
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
"""


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=LOCK_TIMEOUT_S)
    try:
        conn.executescript(_SCHEMA)
        if (
            conn.execute("SELECT value FROM kb_meta WHERE key = 'schema_version'").fetchone()
            is None
        ):
            conn.execute("INSERT INTO kb_meta (key, value) VALUES ('schema_version', '1')")
            conn.commit()
    except BaseException:
        conn.close()
        raise
    return conn


def connect(home: Path) -> sqlite3.Connection:
    """Open the derived index, creating it if missing.

    The index is derived from the record files, so a corrupted file is discarded and rebuilt
    instead of failing the caller. A lock held elsewhere is waited for up to LOCK_TIMEOUT_S and
    then raised (``sqlite3.OperationalError``) — callers report it; they never answer as if
    nothing matched.
    """
    path = index_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _open(path)
    except sqlite3.DatabaseError as exc:
        if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower():
            raise
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        return _open(path)


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


RELATIVE_FLOOR = 0.5


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

        # Relevance floor: BM25 is relative to the corpus, so a hit that scores less than
        # half as well as the best one is incidental overlap on a common word, not a second
        # answer. Pull stays short (fewer lines for the agent to read) and never empty when
        # anything matched.
        if results and results[0].score < 0:
            top = results[0].score
            results = [hit for hit in results if hit.score / top >= RELATIVE_FLOOR]
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
        when = record.superseded_at[:10] if record.superseded_at else "?"
        if record.superseded_by:
            line += f" (superseded by {record.superseded_by} on {when})"
        else:
            line += f" (invalidated on {when})"

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


def promote(home: Path, record_id: str, *, reason: str, actor: str | None = None) -> Record:
    """Promote a candidate record to current."""
    import os

    record = records.load(home, record_id)

    if record.status != "candidate":
        raise RecordError(f"{record_id}: only candidate records can be promoted")
    if not record.evidence:
        raise RecordError("promotion needs evidence")
    if not reason.strip():
        raise RecordError("promotion reason required")

    # Determine actor
    if actor is None:
        actor = os.environ.get("BRAIN_ACTOR")
    if actor is None:
        actor = os.environ.get("USER") or os.environ.get("USERNAME")
    if actor is None:
        actor = "unknown"

    # Update the record
    updated = records.replace(
        record,
        status="current",
        extra={
            **record.extra,
            "promoted_at": records.now_iso(),
            "promotion_reason": reason,
            "promoted_by": actor,
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
        msg = (
            f"WEAKER_REPLACEMENT: {new_grade} cannot replace {old_grade}; "
            "record the disagreement with `brain conflict` instead"
        )
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

    # Write new record first (with supersedes list); a supersession resolves their conflict.
    new_supersedes = list(new_record.supersedes)
    if old_id not in new_supersedes:
        new_supersedes.append(old_id)
    new_updated = records.replace(
        new_record,
        supersedes=tuple(new_supersedes),
        conflicts=tuple(c for c in new_record.conflicts if c != old_id),
    )
    records.save(home, new_updated)

    # Write old record (mark as superseded)
    old_updated = records.replace(
        old_record,
        conflicts=tuple(c for c in old_record.conflicts if c != by),
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


def conflict(home: Path, a_id: str, b_id: str, *, reason: str) -> tuple[Record, Record]:
    """Record that two active records disagree and evidence has not settled it (MEM-04).

    Both stay visible and searchable; the brief marks them and neither is pushed as a
    correction. Superseding one with the other resolves the pair.
    """
    if not reason.strip():
        raise RecordError("conflict reason required")
    if a_id == b_id:
        raise RecordError("a record cannot conflict with itself")
    a, b = records.load(home, a_id), records.load(home, b_id)
    for rec in (a, b):
        if not rec.active:
            raise RecordError(f"{rec.id}: only active records can be in conflict")
    note = f"{records.now_iso()} {reason.strip()}"
    a_new = records.replace(
        a,
        conflicts=tuple(dict.fromkeys([*a.conflicts, b.id])),
        extra={**a.extra, "conflict_note": note},
    )
    b_new = records.replace(
        b,
        conflicts=tuple(dict.fromkeys([*b.conflicts, a.id])),
        extra={**b.extra, "conflict_note": note},
    )
    records.save(home, a_new)
    records.save(home, b_new)
    refresh(home)
    from . import views

    views.compile_views(home)
    return a_new, b_new


def edit(
    home: Path,
    record_id: str,
    *,
    type: str | None = None,
    title: str | None = None,
    valid_from: str | None = None,
    add_evidence: tuple[str, ...] = (),
    add_trigger_errors: tuple[str, ...] = (),
    add_trigger_paths: tuple[str, ...] = (),
    add_terms: tuple[str, ...] = (),
) -> Record:
    """Change a record's description, never its standing.

    Type, title, valid time, evidence, triggers and terms may change. Status, grade, scope and
    supersession have their own guarded commands (promote, supersede, retire), so an edit can
    neither raise trust nor widen who sees a record.
    """
    record = records.load(home, record_id)
    if not record.active:
        raise RecordError(f"{record_id}: only active records can be edited")

    def extend(current: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*current, *(item.strip() for item in extra if item.strip())]))

    changes: dict[str, object] = {
        "evidence": extend(record.evidence, add_evidence),
        "trigger_errors": extend(record.trigger_errors, add_trigger_errors),
        "trigger_paths": extend(record.trigger_paths, add_trigger_paths),
        "terms": extend(record.terms, add_terms),
        "extra": {**record.extra, "edited_at": records.now_iso()},
    }
    if type is not None:
        changes["type"] = type
    if title is not None:
        changes["title"] = title
    if valid_from is not None:
        records.parse_time(valid_from)
        changes["valid_from"] = valid_from
    updated = records.replace(record, **changes)
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
