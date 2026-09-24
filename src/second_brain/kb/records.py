"""Brain records: one Markdown file per fact (V3 agent-native core).

A record file is canonical. Every field retrieval, views and currentness need lives in its
frontmatter, so the SQLite index and the per-project views are rebuildable from the files alone.

Standard library only, and no other Brain module is imported: hooks and the ``brain`` CLI load
this on their hot path.

File format::

    ---
    id: mem-5c3d70d84f4e
    title: Migration ordering
    type: gotcha
    scope: project
    project: second-brain
    status: current
    grade: TESTED
    recorded_at: 2026-08-16T18:12:48+00:00
    evidence:
      - src/second_brain/migrations@1a2b3c4d5e6f
    ---

    Apply migrations in numeric order.

Scalars are ``key: value`` on one line; list fields are ``key:`` followed by ``  - item`` lines;
empty lists and unset values are omitted. Unknown keys are preserved verbatim.
"""

from __future__ import annotations

import dataclasses
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RECORD_TYPES: tuple[str, ...] = (
    "fact",
    "decision",
    "gotcha",
    "procedure",
    "locator",
    "correction",
    "state",
)
SCOPES: tuple[str, ...] = ("project", "domain", "global")
STATUSES: tuple[str, ...] = ("candidate", "current", "superseded", "retracted")
ACTIVE_STATUSES: frozenset[str] = frozenset({"candidate", "current"})
GRADES: tuple[str, ...] = ("INFERRED", "OBSERVED", "TESTED", "VERIFIED", "HISTORICAL")
GRADE_RANK: dict[str, int] = {
    "HISTORICAL": -1,
    "INFERRED": 0,
    "OBSERVED": 1,
    "TESTED": 2,
    "VERIFIED": 3,
}
SUPERSESSION_KINDS: tuple[str, ...] = ("supersedes", "corrects", "invalidates")

_ID = re.compile(r"^[a-z]+-[0-9a-z]{6,32}$")
_TITLE_MAX = 200
# Frontmatter order on write; also the set of known keys.
_SCALARS: tuple[str, ...] = (
    "id",
    "title",
    "type",
    "scope",
    "project",
    "status",
    "grade",
    "attested",
    "valid_from",
    "recorded_at",
    "superseded_by",
    "supersession_kind",
    "supersession_reason",
    "superseded_at",
    "private",
    "origin",
    "authority",
)
_LISTS: tuple[str, ...] = (
    "domains",
    "supersedes",
    "conflicts",
    "evidence",
    "trigger_paths",
    "trigger_errors",
    "terms",
)
_BOOLS = frozenset({"attested", "private"})


class RecordError(ValueError):
    """A record file or value that violates the record contract."""


@dataclass
class Record:
    """One canonical Brain record."""

    id: str
    title: str
    type: str = "fact"
    scope: str = "project"
    project: str | None = None
    domains: tuple[str, ...] = ()
    status: str = "candidate"
    grade: str = "OBSERVED"
    #: Only an independent issuer can attest a grade; none exists in this build.
    attested: bool = False
    #: When the fact became true in the world (valid time), if known.
    valid_from: str | None = None
    #: When the Brain recorded it (system time).
    recorded_at: str = ""
    supersedes: tuple[str, ...] = ()
    #: Records this one disagrees with, unresolved (MEM-04): both stay visible, neither is pushed
    #: as a correction, and the brief marks them.
    conflicts: tuple[str, ...] = ()
    superseded_by: str | None = None
    supersession_kind: str | None = None
    supersession_reason: str | None = None
    #: Effective time of the supersession/invalidation.
    superseded_at: str | None = None
    evidence: tuple[str, ...] = ()
    trigger_paths: tuple[str, ...] = ()
    trigger_errors: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()
    private: bool = False
    origin: str | None = None
    authority: str = "advisory"
    body: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def effective_grade(self) -> str:
        """Grade that may affect trust: a claimed VERIFIED is TESTED unless attested."""
        if self.grade == "VERIFIED" and not self.attested:
            return "TESTED"
        return self.grade

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str = "mem") -> str:
    return f"{prefix}-{secrets.token_hex(6)}"


def parse_time(value: str) -> datetime:
    """ISO-8601 (trailing ``Z`` allowed) as an aware UTC datetime; naive means UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip().removesuffix("Z"))
    except ValueError as exc:
        raise RecordError(f"not an ISO-8601 time: {value!r}") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def validate(record: Record) -> list[str]:
    """Contract violations, empty when the record is valid."""
    errors: list[str] = []
    if not _ID.match(record.id):
        errors.append(f"id {record.id!r} must match {_ID.pattern}")
    if not record.title.strip() or len(record.title) > _TITLE_MAX:
        errors.append(f"title must be 1..{_TITLE_MAX} characters")
    if record.type not in RECORD_TYPES:
        errors.append(f"type must be one of {', '.join(RECORD_TYPES)}")
    if record.scope not in SCOPES:
        errors.append(f"scope must be one of {', '.join(SCOPES)}")
    if record.scope == "project" and not record.project:
        errors.append("scope project requires project")
    if record.status not in STATUSES:
        errors.append(f"status must be one of {', '.join(STATUSES)}")
    if record.grade not in GRADES:
        errors.append(f"grade must be one of {', '.join(GRADES)}")
    if record.status == "superseded":
        if record.supersession_kind not in SUPERSESSION_KINDS:
            errors.append("superseded record requires supersession_kind")
        elif (record.supersession_kind == "invalidates") != (record.superseded_by is None):
            errors.append("invalidates has no superseded_by; other kinds require it")
        if not record.supersession_reason:
            errors.append("superseded record requires supersession_reason")
        if not record.superseded_at:
            errors.append("superseded record requires superseded_at")
    for name in ("valid_from", "recorded_at", "superseded_at"):
        value = getattr(record, name)
        if value:
            try:
                parse_time(value)
            except RecordError as exc:
                errors.append(f"{name}: {exc}")
    if not record.recorded_at:
        errors.append("recorded_at is required")
    return errors


def dumps(record: Record) -> str:
    """Serialize deterministically (fixed key order, LF line endings)."""
    lines = ["---"]
    for name in _SCALARS:
        value = getattr(record, name)
        if value is None or value == "":
            continue
        if name in _BOOLS:
            if not value:
                continue
            value = "true"
        if name == "authority" and value == "advisory":
            continue
        lines.append(f"{name}: {_one_line(value)}")
    for name in _LISTS:
        items = getattr(record, name)
        if items:
            lines.append(f"{name}:")
            lines.extend(f"  - {_one_line(item)}" for item in items)
    for key in sorted(record.extra):
        lines.append(f"{key}: {_one_line(record.extra[key])}")
    lines.append("---")
    body = record.body.strip("\n")
    return "\n".join(lines) + "\n\n" + (body + "\n" if body else "")


def loads(text: str) -> Record:
    """Parse one record file. Raises RecordError on a malformed file; does not validate."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise RecordError("missing frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
        if end == -1 or text[end + 4 :].strip():
            raise RecordError("unterminated frontmatter")
    head = text[4:end]
    body = text[end + 5 :].strip("\n")
    scalars: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    current_list: str | None = None
    for raw in head.split("\n"):
        if not raw.strip():
            continue
        if raw.startswith("  - ") and current_list is not None:
            lists[current_list].append(raw[4:].strip())
            continue
        key, sep, value = raw.partition(":")
        key = key.strip()
        if not sep or not key or raw[0].isspace():
            raise RecordError(f"bad frontmatter line: {raw!r}")
        value = value.strip()
        if key in _LISTS:
            current_list = key
            lists[key] = []
            if value:  # tolerate "key: a, b" written by hand
                lists[key] = [item.strip() for item in value.split(",") if item.strip()]
            continue
        current_list = None
        scalars[key] = value
    if "id" not in scalars or "title" not in scalars:
        raise RecordError("frontmatter requires id and title")
    known: dict[str, object] = {}
    extra: dict[str, str] = {}
    for key, value in scalars.items():
        if key in _BOOLS:
            known[key] = value.lower() == "true"
        elif key in _SCALARS:
            known[key] = value or None
        elif key == "created_at":  # legacy memory files
            known.setdefault("recorded_at", value)
        else:
            extra[key] = value
    for key, items in lists.items():
        known[key] = tuple(items)
    record = Record(id=str(known.pop("id")), title=str(known.pop("title")), body=body)
    for key, value in known.items():
        if value is not None:
            setattr(record, key, value)
    record.extra = extra
    return record


def read(path: Path) -> Record:
    return loads(path.read_text(encoding="utf-8"))


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def records_dir(home: Path) -> Path:
    return Path(home) / "records"


def private_dir(home: Path) -> Path:
    """Where ``private: true`` records live: inside records/, but gitignored, so they are
    searchable locally and never leave the machine through ``brain sync``."""
    return records_dir(home) / "private"


def _placed(home: Path, record_id: str, private: bool) -> Path:
    return (private_dir(home) if private else records_dir(home)) / f"{record_id}.md"


def record_path(home: Path, record_id: str) -> Path:
    """The file holding a record: the private copy when one exists, else the shared one."""
    private = _placed(home, record_id, True)
    return private if private.is_file() else _placed(home, record_id, False)


def save(home: Path, record: Record) -> Path:
    """Validate and write one record where its privacy says; returns its path.

    Changing ``private`` moves the file: the new copy is written first, then the old one is
    removed, so a crash in between leaves a duplicate (reported by ``load_all``), never a loss.
    """
    errors = validate(record)
    if errors:
        raise RecordError(f"{record.id}: " + "; ".join(errors))
    path = _placed(home, record.id, record.private)
    write_atomic(path, dumps(record))
    other = _placed(home, record.id, not record.private)
    other.unlink(missing_ok=True)
    return path


def load(home: Path, record_id: str) -> Record:
    path = record_path(home, record_id)
    if not path.is_file():
        raise RecordError(f"unknown record {record_id!r}")
    return read(path)


def load_all(home: Path) -> tuple[list[Record], list[str]]:
    """Every parseable, valid record (shared and private) plus one error line per rejected
    file. A record file in the wrong place for its ``private`` flag, or one id present in both
    places, is rejected: a private fact must never sit where sync would publish it."""
    records: list[Record] = []
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for directory, private in ((records_dir(home), False), (private_dir(home), True)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            label = f"private/{path.name}" if private else path.name
            try:
                record = read(path)
            except (OSError, UnicodeDecodeError, RecordError) as exc:
                errors.append(f"{label}: {exc}")
                continue
            problems = validate(record)
            if record.id != path.stem:
                problems.append(f"id {record.id!r} does not match file name")
            if record.private != private:
                problems.append(
                    "private record outside records/private"
                    if record.private
                    else "shared record inside records/private"
                )
            if record.id in seen:
                problems.append(f"duplicate of {seen[record.id]}")
            if problems:
                errors.append(f"{label}: " + "; ".join(problems))
                continue
            seen[record.id] = path
            records.append(record)
    return records, errors


def replace(record: Record, **changes: object) -> Record:
    return dataclasses.replace(record, **changes)  # type: ignore[arg-type]
