"""One authority for what a shared per-session Brain database is.

`state/sessions/<internal_id>/ledger.sqlite` is opened by more than one component —
`LedgerStore` (events, segments, metadata) and `VMemStore` (resident objects) — and until
now each of them decided *on its own* what an unfamiliar database meant. Whichever opened
first effectively defined reality:

    LedgerStore: "these tables aren't mine" -> refuse the file
    VMemStore:   "I got here first"         -> initialize a partial database

A session whose file VMemStore created first could therefore become permanently
ledger-less. The rule this module implements is the invariant that closes that class:

    There is exactly one authoritative bootstrap/migration interpretation of a Brain
    database, regardless of which component happens to open it first.

Ownership of responsibilities is deliberate:

* **This module owns the decision** — what database is this, and which transition is legal.
  It owns the canonical version, the registry of known component tables, the compatibility
  and adoption rules, and the shared ownership rows.
* **Components own their DDL and their data operations.** Each registers its schema once
  (`register`), so there is one source per component and one authority overall — never a
  mutual allowlist where each store carries a copy of the other's tables.

Nothing here writes data rows, and nothing here decides anything about a table it does not
recognise: arbitrary unknown tables are refused by name rather than adopted, renamed or
deleted.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .errors import BrainError

#: Canonical schema version of the shared database. Belongs to the *database*, not to a
#: component: a component that needs a newer shape must migrate through this authority.
SCHEMA_VERSION = 2

#: Versions this authority recognises as predecessors with a migration path. A database at
#: one of these versions is left for its owning component to migrate, never re-stamped here.
MIGRATABLE_VERSIONS = frozenset({1})

#: The shared metadata and ownership table. Both components create it; this module is the
#: only place that decides what may live in it.
META_TABLE = "ledger_meta"

#: Tables that belong to the shared database but are not part of its canonical schema:
#: SQLite's own bookkeeping and the ledger's full-text index.
_IGNORED_PREFIXES = ("sqlite_",)
CANONICAL_TABLES: dict[str, tuple[str, ...]] = {
    "ledger": (
        "agents",
        "deliveries",
        "events",
        "object_refs",
        "request_epochs",
        "request_fingerprints",
        "segments",
        "sessions",
    ),
    "vmem": ("session_vmem",),
}

_IGNORED_NAMES = frozenset(
    {"events_fts", "events_fts_data", "events_fts_idx", "events_fts_content",
     "events_fts_docsize", "events_fts_config"}
)


@dataclass(frozen=True)
class Component:
    """A registered component schema: its name, its tables, and the DDL that creates them."""

    name: str
    tables: tuple[str, ...]
    ddl: str


@dataclass
class DatabaseIdentity:
    """What the shared database currently is, as classified by this authority."""

    state: str
    version: int | None
    tables: set[str] = field(default_factory=set)
    unknown_tables: set[str] = field(default_factory=set)
    missing_component_tables: dict[str, tuple[str, ...]] = field(default_factory=dict)
    ownership: dict[str, str] = field(default_factory=dict)
    has_rows: bool = False

_REGISTRY: dict[str, Component] = {}


def register(name: str, tables: tuple[str, ...], ddl: str) -> None:
    """Register one component's schema. Called once, at that component's import time.

    Registering twice with a different schema is a programming error, not a runtime
    condition: it would mean two definitions of the same component in one process.
    """
    canonical = CANONICAL_TABLES.get(name)
    declared = tuple(sorted(t for t in tables if t != META_TABLE))
    if canonical is not None and declared != tuple(sorted(canonical)):
        raise BrainError(
            f"shared schema: component {name!r} declares {declared} but the authority "
            f"recognises {tuple(sorted(canonical))}"
        )
    existing = _REGISTRY.get(name)
    if existing is not None and (existing.tables, existing.ddl) != (tuple(tables), ddl):
        raise BrainError(f"shared schema: component {name!r} registered twice with different DDL")
    _REGISTRY[name] = Component(name=name, tables=tuple(tables), ddl=ddl)


def components() -> dict[str, Component]:
    """Every registered component, in a deterministic order."""
    return {name: _REGISTRY[name] for name in sorted(_REGISTRY)}


def known_tables(components_map: dict[str, Component] | None = None) -> frozenset[str]:
    """Every table this authority recognises as belonging to the shared database."""
    source = components_map if components_map is not None else components()
    tables = {META_TABLE}
    for name in CANONICAL_TABLES:
        tables.update(CANONICAL_TABLES[name])
    for component in source.values():
        tables.update(component.tables)
    return frozenset(tables)


def classify(
    conn: sqlite3.Connection,
    components_map: dict[str, Component] | None = None,
) -> DatabaseIdentity:
    """Read what the database is. No writes, no decisions, no exceptions for legality.

    States, and what each means:

    ``empty``                no objects at all — a file that will become a database
    ``partial``              known tables exist but the shared version header does not
    ``canonical``            the shared version header is current; component tables may be
                             absent (each component adds its own when it first opens)
    ``legacy-version``       the header names a version with a migration path; the owning
                             component migrates it, this authority only fills missing tables
    ``unknown-tables``       at least one table belongs to nobody registered here
    ``unsupported-version``  the header names a version this runtime does not serve
    """
    source = components_map if components_map is not None else components()
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    }
    identity = DatabaseIdentity(state="empty", version=None, tables=set(tables))
    ignored = {
        name for name in tables
        if name.startswith(_IGNORED_PREFIXES) or name in _IGNORED_NAMES
    }
    known = known_tables(source)
    identity.unknown_tables = {name for name in tables - ignored - known}

    if not (tables - ignored):
        identity.state = "empty"
        return identity

    version_text: str | None = None
    if META_TABLE in tables:
        columns = [tuple(row)[1] for row in conn.execute(f"PRAGMA table_info({META_TABLE})")]
        if columns and (len(columns) < 2 or str(columns[0]).casefold() != "key"):
            identity.state = "malformed-meta"
            return identity
        row = conn.execute(
            f"SELECT value FROM {META_TABLE} WHERE key='schema_version'"
        ).fetchone()
        version_text = row[0] if row is not None else None
        identity.ownership = {
            str(key): str(value)
            for key, value in conn.execute(
                f"SELECT key,value FROM {META_TABLE} WHERE key LIKE 'component:%'"
            )
        }
    if version_text is not None:
        try:
            identity.version = int(version_text)
        except (TypeError, ValueError):
            identity.state = "malformed-meta"
            return identity

    if identity.unknown_tables:
        identity.state = "unknown-tables"
        return identity

    rows = 0
    for name in sorted(tables & known):
        try:
            rows += int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
        except sqlite3.Error:  # a shape we cannot read is a state, not a crash
            identity.state = "malformed-meta"
            return identity
    identity.has_rows = rows > 0

    for name, component in source.items():
        missing = tuple(table for table in component.tables if table not in tables)
        if missing:
            identity.missing_component_tables[name] = missing

    if version_text is None:
        identity.state = "partial"
    elif identity.version == SCHEMA_VERSION:
        identity.state = "canonical"
    elif identity.version in MIGRATABLE_VERSIONS:
        identity.state = "legacy-version"
    else:
        identity.state = "unsupported-version"
    return identity


def ensure(
    conn: sqlite3.Connection,
    *,
    component: str,
    create: bool,
    header: dict[str, str] | None = None,
    components_map: dict[str, Component] | None = None,
) -> DatabaseIdentity:
    """Bring the shared database to a state ``component`` may open, or refuse by name.

    The caller must hold a write reservation (``BEGIN IMMEDIATE``) so that inspection and
    transition happen under one lock: two components racing to initialize cannot interleave
    a half-create from each. This function never commits or rolls back — the caller owns the
    transaction, so an interrupted initialization rolls back to the state it started from.
    """
    source = components_map if components_map is not None else components()
    if component not in source:
        raise BrainError(f"shared schema: component {component!r} is not registered")
    identity = classify(conn, source)

    if identity.state == "unknown-tables":
        raise BrainError(
            "ledger schema unsupported: unidentified existing tables: "
            + ", ".join(sorted(identity.unknown_tables))
        )
    if identity.state == "malformed-meta":
        raise BrainError("ledger schema unsupported: malformed application metadata")
    if identity.state == "unsupported-version":
        raise BrainError(
            f"ledger schema {identity.version} unsupported; runtime requires {SCHEMA_VERSION}"
        )
    if identity.state == "legacy-version":
        own_missing = component in identity.missing_component_tables
        if own_missing:
            for statement in _statements(source[component].ddl):
                conn.execute(statement)
        return classify(conn, source)

    if identity.state == "partial":
        if identity.has_rows and not _is_known_legacy_shape(conn, identity, source):
            # Known tables carrying data, no version header, and a shape this authority does
            # not recognise: fail closed rather than guess a migration. Adoption is allowed
            # only through the explicit rule below.
            raise BrainError("ledger missing schema_version header with existing data")
        if not create:
            raise BrainError("ledger not initialized (schema not ready)")
    elif identity.state == "empty":
        if not create:
            raise BrainError("ledger not initialized (schema not ready)")

    # Only the calling component's tables are created here. A component that created another
    # component's tables would enlarge its blast radius for no gain: whichever opens second adds
    # what is missing, and both orders converge on the same schema.
    own_missing = (
        component in identity.missing_component_tables or identity.state in ("empty", "partial")
    )
    if own_missing:
        for statement in _statements(source[component].ddl):
            conn.execute(statement)

    _ensure_metadata(conn, source, header or {})
    final = classify(conn, source)
    if final.state != "canonical":
        raise BrainError(
            f"ledger initialization did not produce the supported schema (state {final.state})"
        )
    return final


def _ensure_metadata(
    conn: sqlite3.Connection,
    source: dict[str, Component],
    header: dict[str, str],
) -> None:
    """Write the shared version and component-ownership rows, idempotently."""
    rows: dict[str, str] = {"schema_version": str(SCHEMA_VERSION)}
    for key, value in header.items():
        if key != "schema_version":
            rows.setdefault(key, value)
    existing = {
        str(key): str(value)
        for key, value in conn.execute(f"SELECT key,value FROM {META_TABLE}")
    }
    for key, value in rows.items():
        if key not in existing:
            conn.execute(f"INSERT INTO {META_TABLE} (key,value) VALUES (?,?)", (key, value))
        elif existing[key] != value and key == "schema_version":
            conn.execute(f"UPDATE {META_TABLE} SET value=? WHERE key=?", (value, key))
    for name in sorted(source):
        key = f"component:{name}"
        value = str(SCHEMA_VERSION)
        if key not in existing:
            conn.execute(f"INSERT INTO {META_TABLE} (key,value) VALUES (?,?)", (key, value))


_CANONICAL_COLUMNS: dict[str, list[str]] = {}


def canonical_columns(source: dict[str, Component] | None = None) -> dict[str, list[str]]:
    """The column list each canonical table must have, derived from the registered DDL."""
    global _CANONICAL_COLUMNS
    if _CANONICAL_COLUMNS:
        return _CANONICAL_COLUMNS
    components_map = source if source is not None else components()
    conn = sqlite3.connect(":memory:")
    try:
        for name in sorted(components_map):
            for statement in _statements(components_map[name].ddl):
                conn.execute(statement)
        columns: dict[str, list[str]] = {}
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            columns[str(table)] = [
                str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')
            ]
        _CANONICAL_COLUMNS = columns
        return columns
    finally:
        conn.close()


def _is_known_legacy_shape(
    conn: sqlite3.Connection,
    identity: DatabaseIdentity,
    source: dict[str, Component],
) -> bool:
    """Whether a header-less database is an *exact* legacy shape this authority may adopt.

    The rule is deliberately narrow, and it is the only door for adoption: every table present
    must be one this authority knows, and its columns must be a **prefix** of that table's
    canonical columns — i.e. a known table that predates additive columns, and nothing else.
    A foreign table, a renamed column or a reordered shape is refused by name instead.
    """
    canonical = canonical_columns(source)
    known = known_tables(source)
    for name in sorted(identity.tables):
        if name.startswith(_IGNORED_PREFIXES) or name in _IGNORED_NAMES:
            continue
        if name not in known or name not in canonical:
            return False
        present = [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{name}")')]
        expected = canonical[name]
        if not present or present != expected[: len(present)]:
            return False
    return True


def _statements(ddl: str) -> list[str]:
    """Split a component DDL script into statements, without importing a schema helper."""
    statements: list[str] = []
    current: list[str] = []
    for line in ddl.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def schema_dump(conn: sqlite3.Connection) -> dict[str, Any]:
    """A structural fingerprint of the shared database, for equivalence comparisons.

    Compares what actually defines a schema — tables, their columns, indexes, foreign keys —
    plus the shared version and ownership rows. Used by tests and by any caller that needs to
    assert two databases converged rather than merely both opening.
    """
    tables = sorted(
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(row[0]).startswith(_IGNORED_PREFIXES) and str(row[0]) not in _IGNORED_NAMES
    )
    dump: dict[str, Any] = {"tables": {}, "indexes": {}, "meta": {}}
    for name in tables:
        dump["tables"][name] = [
            (str(row[1]), str(row[2]), int(row[3]), row[4])
            for row in conn.execute(f'PRAGMA table_info("{name}")')
        ]
        dump["indexes"][name] = sorted(
            (
                str(row[1]),
                bool(row[2]),
                [str(part[2]) for part in conn.execute(f'PRAGMA index_info("{row[1]}")')],
            )
            for row in conn.execute(f'PRAGMA index_list("{name}")')
        )
    if META_TABLE in tables:
        dump["meta"] = {
            str(key): str(value)
            for key, value in conn.execute(
                f"SELECT key,value FROM {META_TABLE} "
                "WHERE key='schema_version' OR key LIKE 'component:%'"
            )
        }
    return dump
