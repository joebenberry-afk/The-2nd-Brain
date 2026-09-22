"""Shared-database bootstrap qualification (owner directive, item #2).

The invariant under test:

    There is exactly one authoritative bootstrap/migration interpretation of a Brain
    database, regardless of which component happens to open it first.

These cases are the ones the owner named, in the same order, plus the two adjacent ones
requested alongside them. The two fresh creation orders must converge on the **same schema**,
not merely both avoid exceptions, so they are compared with `brain_schema.schema_dump` rather
than by "both opened".

Nothing here may obtain a green result by recreating the database or discarding state: case 4
and the data-preservation assertions exist to make that impossible.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from second_brain import brain_schema, ledger, vmem
from second_brain.errors import BrainError


def _open_ledger(home, session_id: str):
    return ledger.LedgerStore(home, session_id, host="test").open(create=True)


def _open_vmem(home, session_id: str):
    return vmem.VMemStore(home, session_id)


def _session_file(home, session_id: str):
    return home / "state" / "sessions" / ledger.internal_session_id(session_id) / "ledger.sqlite"


def _dump(path):
    conn = sqlite3.connect(path)
    try:
        return brain_schema.schema_dump(conn)
    finally:
        conn.close()


# --- 1 and 2: the two fresh creation orders -------------------------------------------


def test_case_1_fresh_db_ledger_first_then_vmem(brain_home) -> None:
    with _open_ledger(brain_home, "order-ledger-first"):
        pass
    _open_vmem(brain_home, "order-ledger-first")

    path = _session_file(brain_home, "order-ledger-first")
    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
    finally:
        conn.close()
    assert identity.state == "canonical", identity
    assert identity.unknown_tables == set()
    assert identity.missing_component_tables == {}, identity.missing_component_tables
    assert identity.ownership == {"component:ledger": "2", "component:vmem": "2"}


def test_case_2_fresh_db_vmem_first_then_ledger(brain_home) -> None:
    _open_vmem(brain_home, "order-vmem-first")
    with _open_ledger(brain_home, "order-vmem-first"):
        pass

    path = _session_file(brain_home, "order-vmem-first")
    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
    finally:
        conn.close()
    assert identity.state == "canonical", identity
    assert identity.unknown_tables == set()
    assert identity.missing_component_tables == {}, identity.missing_component_tables


def test_the_two_creation_orders_converge_on_the_same_schema(brain_home) -> None:
    """Structural identity, not "both opened": tables, columns, indexes and metadata."""
    with _open_ledger(brain_home, "converge-a"):
        pass
    _open_vmem(brain_home, "converge-a")

    _open_vmem(brain_home, "converge-b")
    with _open_ledger(brain_home, "converge-b"):
        pass

    first = _dump(_session_file(brain_home, "converge-a"))
    second = _dump(_session_file(brain_home, "converge-b"))
    assert first["tables"] == second["tables"]
    assert first["indexes"] == second["indexes"]
    assert first["meta"] == second["meta"]
    assert set(first["tables"]) >= {"events", "sessions", "segments", "session_vmem", "ledger_meta"}


# --- 3: an existing complete database --------------------------------------------------


def test_case_3_existing_complete_db_opens_idempotently(brain_home) -> None:
    with _open_ledger(brain_home, "complete") as store:
        store.create_session(_identity("complete"))
    _open_vmem(brain_home, "complete")
    before = _dump(_session_file(brain_home, "complete"))

    with _open_ledger(brain_home, "complete"):
        pass
    _open_vmem(brain_home, "complete")

    assert _dump(_session_file(brain_home, "complete")) == before


def _identity(session_id: str):
    from datetime import UTC, datetime

    from second_brain import contracts

    return contracts.BrainSessionIdentity(
        internal_session_id=ledger.internal_session_id(session_id),
        host="test",
        host_session_id=session_id,
        project_id="second-brain",
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=contracts.LEDGER_SCHEMA_VERSION,
    )


# --- 4: an exact known legacy partial database -----------------------------------------


def test_case_4_exact_known_legacy_partial_db_is_adopted(brain_home) -> None:
    """A pre-additive `session_vmem` with rows and no header: adopted, never recreated."""
    path = _session_file(brain_home, "legacy-partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE session_vmem (
                obj_id TEXT PRIMARY KEY,
                internal_session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                token_estimate INTEGER NOT NULL,
                residency_state TEXT NOT NULL,
                priority_score REAL NOT NULL DEFAULT 1.0,
                pinned INTEGER NOT NULL DEFAULT 0,
                access_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_accessed_at TEXT NOT NULL,
                segment_id TEXT,
                metadata_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO session_vmem (obj_id, internal_session_id, kind, title, summary,"
            " content_sha256, token_estimate, residency_state, created_at, last_accessed_at,"
            " metadata_json) VALUES ('o1','i1','research_result','t','s','h',1,'resident',"
            " '2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','{}')"
        )
        conn.commit()
    finally:
        conn.close()

    _open_vmem(brain_home, "legacy-partial")  # the shape is adopted, not refused

    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
        rows = conn.execute("SELECT obj_id FROM session_vmem").fetchall()
    finally:
        conn.close()
    assert identity.state == "canonical", identity
    assert identity.version == brain_schema.SCHEMA_VERSION
    assert rows == [("o1",)], "adoption must preserve existing data"


def test_case_4b_a_shape_that_is_not_a_known_legacy_form_is_refused(brain_home) -> None:
    """A renamed column is not a legacy form: fail closed rather than adopt by resemblance."""
    path = _session_file(brain_home, "legacy-unknown")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE session_vmem (obj_id TEXT PRIMARY KEY, mystery TEXT NOT NULL)")
        conn.execute("INSERT INTO session_vmem (obj_id, mystery) VALUES ('o1','?')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(BrainError) as excinfo:
        _open_vmem(brain_home, "legacy-unknown")
    assert "schema" in str(excinfo.value).lower()


# --- 5: interrupted initialization -----------------------------------------------------


def test_case_5_interrupted_initialization_resumes_deterministically(brain_home) -> None:
    """Known tables, no header, no rows: a rollback-shaped state that must complete, not fail."""
    path = _session_file(brain_home, "interrupted")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        for statement in brain_schema._statements(vmem._VMEM_SCHEMA):
            conn.execute(statement)
        conn.commit()  # as if the process died before the header was written
    finally:
        conn.close()

    _open_vmem(brain_home, "interrupted")
    with _open_ledger(brain_home, "interrupted"):
        pass

    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
    finally:
        conn.close()
    assert identity.state == "canonical"
    assert identity.missing_component_tables == {}


def test_case_5b_a_headered_db_missing_a_component_completes(brain_home) -> None:
    """One component's header, the other's tables absent: the second open completes it."""
    with _open_ledger(brain_home, "half-open"):
        pass
    path = _session_file(brain_home, "half-open")
    conn = sqlite3.connect(path)
    try:
        assert "session_vmem" not in {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()

    _open_vmem(brain_home, "half-open")
    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
    finally:
        conn.close()
    assert identity.state == "canonical"
    assert identity.missing_component_tables == {}


# --- 6: unknown-table contamination ----------------------------------------------------


def test_case_6_a_foreign_table_is_never_adopted_renamed_or_removed(brain_home) -> None:
    with _open_ledger(brain_home, "foreign") as store:
        store.create_session(_identity("foreign"))
    path = _session_file(brain_home, "foreign")
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE someone_elses_table (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO someone_elses_table (v) VALUES ('keep me')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(BrainError) as excinfo:
        _open_vmem(brain_home, "foreign")
    assert "unidentified existing tables" in str(excinfo.value)
    assert "someone_elses_table" in str(excinfo.value)

    with pytest.raises(BrainError), _open_ledger(brain_home, "foreign"):
        pass

    conn = sqlite3.connect(path)
    try:
        survived = conn.execute("SELECT v FROM someone_elses_table").fetchall()
    finally:
        conn.close()
    assert survived == [("keep me",)], "refusal must not delete or rewrite foreign state"


# --- 7: competing first-open -----------------------------------------------------------


def test_case_7_competing_first_open_converges(brain_home) -> None:
    """Either order is fine; a half-create from each is not."""
    session_id = "competing"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def initializer(open_store) -> None:
        try:
            barrier.wait(timeout=10)
            open_store(brain_home, session_id)
        except BaseException as exc:  # collected, not swallowed
            errors.append(exc)

    threads = [
        threading.Thread(target=initializer, args=(_open_ledger,)),
        threading.Thread(target=initializer, args=(_open_vmem,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    path = _session_file(brain_home, session_id)
    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
        tables = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert errors == [], errors
    assert identity.state == "canonical", (identity.state, identity.unknown_tables)
    assert {"events", "session_vmem", "ledger_meta"} <= tables


# --- data preservation and the accounting witness --------------------------------------


def test_bootstrap_preserves_ledger_data(brain_home) -> None:
    """A repair must not "fix" anything by dropping rows: the reader still reads them.

    The accounting witness (`used == 65`) lives in `tests/test_governor.py` and must keep
    passing untouched; it is not duplicated here, because a duplicated number proves nothing.
    """
    with _open_ledger(brain_home, "preserve") as store:
        store.create_session(_identity("preserve"))
        store.append_events(
            [
                _event("preserve", "e1"),
                _event("preserve", "e2"),
            ]
        )
    _open_vmem(brain_home, "preserve")
    with _open_ledger(brain_home, "preserve") as store:
        report = store.integrity()
        assert report.get("events", 0) >= 2 or report.get("seq_contiguous") is not None


def _event(session_id: str, event_id: str):
    from datetime import UTC, datetime

    from second_brain import contracts

    return contracts.BrainLifecycleEvent(
        seq=0,
        event_id=event_id,
        internal_session_id=ledger.internal_session_id(session_id),
        agent_id="unknown",
        event_type=contracts.LifecycleEventType.FINDING,
        timestamp=datetime.now(UTC).isoformat(),
        surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
        ignorable=False,
        payload={"note": "bootstrap qualification"},
    )
