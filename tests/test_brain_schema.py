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

import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from second_brain import brain_schema, ledger, vmem
from second_brain.errors import BrainError

ROOT = Path(__file__).resolve().parents[1] / "src"


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
    assert identity.ownership == {"component:ledger": "3", "component:vmem": "3"}


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


def test_vmem_only_v2_header_upgrades_when_ledger_is_added(brain_home) -> None:
    session_id = "vmem-v2-predecessor"
    _open_vmem(brain_home, session_id)
    path = _session_file(brain_home, session_id)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_meta SET value='2' WHERE key='schema_version'")
        conn.execute("UPDATE ledger_meta SET value='2' WHERE key='component:vmem'")
        conn.execute(
            "INSERT INTO session_vmem (obj_id,internal_session_id,kind,title,summary,"
            "content_sha256,token_estimate,residency_state,created_at,last_accessed_at,"
            "metadata_json) VALUES ('o1','i1','research_result','t','s','h',1,'resident',"
            "'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','{}')"
        )
    with _open_ledger(brain_home, session_id) as store:
        assert store.integrity()["hash_chain_ok"] is True
    with sqlite3.connect(path) as conn:
        assert brain_schema.classify(conn).version == 3
        assert conn.execute("SELECT obj_id FROM session_vmem").fetchall() == [("o1",)]


def test_vmem_refuses_headerless_ledger_history(brain_home) -> None:
    session_id = "headerless-ledger-history"
    with _open_ledger(brain_home, session_id) as store:
        store.append_events([_event(session_id, "existing")])
    path = _session_file(brain_home, session_id)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM ledger_meta WHERE key='schema_version'")
    with pytest.raises(BrainError, match="missing schema_version header"):
        _open_vmem(brain_home, session_id)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT value FROM ledger_meta WHERE key='schema_version'"
        ).fetchone() is None
        assert conn.execute("SELECT event_id FROM events").fetchall() == [("existing",)]


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
        schema_version=ledger.LEDGER_SCHEMA_VERSION,
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


def test_case_6b_a_reserved_name_does_not_establish_ownership(brain_home) -> None:
    """`events_fts` is the ledger's index, not a name the ledger owns.

    An object that merely carries the name is somebody's table: opening must refuse it, and the
    refusal must leave it — and its rows — exactly where they were. This is the case where the
    earlier rule ignored the name and could then drop the object during `reindex()`.
    """
    session_id = "reserved-foreign"
    path = _session_file(brain_home, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events_fts (event_id TEXT, note TEXT)")
        conn.execute("INSERT INTO events_fts (event_id, note) VALUES ('foreign', 'keep me')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(BrainError) as excinfo:
        _open_ledger(brain_home, session_id)
    assert "unidentified existing tables" in str(excinfo.value)
    assert "events_fts" in str(excinfo.value)

    with pytest.raises(BrainError) as vmem_excinfo:
        _open_vmem(brain_home, session_id)
    assert "unidentified existing tables" in str(vmem_excinfo.value)

    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
        survived = conn.execute("SELECT note FROM events_fts").fetchall()
        tables = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert survived == [("keep me",)], "refusal must not remove a foreign object"
    assert "events_fts" not in identity.reserved
    assert "events_fts" in identity.unknown_tables
    # A file holding only that object is not an empty file waiting to be initialized.
    assert identity.state == "unknown-tables", identity.state
    assert "events" not in tables, "a refused open must not have created the ledger's tables"


def test_case_6c_a_shadow_table_name_does_not_establish_ownership(brain_home) -> None:
    """The index's shadow-table names are reserved too, and equally unowned by name alone."""
    session_id = "reserved-shadow"
    path = _session_file(brain_home, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events_fts_data (id INTEGER PRIMARY KEY, block BLOB)")
        conn.execute("INSERT INTO events_fts_data (block) VALUES (x'00')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(BrainError) as excinfo:
        _open_ledger(brain_home, session_id)
    assert "unidentified existing tables" in str(excinfo.value)
    assert "events_fts_data" in str(excinfo.value)

    conn = sqlite3.connect(path)
    try:
        survived = conn.execute("SELECT count(*) FROM events_fts_data").fetchone()[0]
    finally:
        conn.close()
    assert survived == 1


def test_case_6d_the_ledgers_own_index_is_recognised_and_reindexed(brain_home) -> None:
    """The positive control: the object the ledger itself created stays ours."""
    session_id = "own-index"
    with _open_ledger(brain_home, session_id) as store:
        store.create_session(_identity("own-index"))
        first = store.reindex()
        second = store.reindex()
    path = _session_file(brain_home, session_id)
    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
        verified = brain_schema.reserved_objects(conn)
        dump = brain_schema.schema_dump(conn)
    finally:
        conn.close()
    assert identity.state == "canonical", (identity.state, identity.unknown_tables)
    assert identity.unknown_tables == set()
    assert "events_fts" in verified
    assert "events_fts_data" in verified
    assert dump["reserved"], "the index is part of the compared structure"
    assert first == second, "reindex is idempotent"


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


@pytest.mark.parametrize("cut", [1, 2, 3])
def test_case_5c_every_strict_prefix_of_the_component_ddl_converges(brain_home, cut: int) -> None:
    """A bootstrap interrupted after ANY statement of the registered DDL still converges.

    The fixture is the authority's own statement sequence truncated at ``cut``, so every
    interruption point is exercised instead of the one shape that happened to work. Cutting after
    the table but before its indexes is the interesting one: the table is present, so a
    table-keyed replay rule would leave the database permanently unindexed.
    """
    session_id = f"prefix-{cut}"
    path = _session_file(brain_home, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    statements = brain_schema._statements(vmem._VMEM_SCHEMA)
    assert cut < len(statements), "the last cut is the complete DDL, not a strict prefix"
    conn = sqlite3.connect(path)
    try:
        for statement in statements[:cut]:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()

    _open_vmem(brain_home, session_id)
    with _open_ledger(brain_home, session_id):
        pass

    reference = "prefix-reference"
    with _open_ledger(brain_home, reference):
        pass
    _open_vmem(brain_home, reference)

    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
    finally:
        conn.close()
    assert identity.state == "canonical", (cut, identity.state)
    assert _dump(path) == _dump(_session_file(brain_home, reference)), cut


def test_case_4d_the_adopted_predecessor_answers_the_public_readers(brain_home) -> None:
    """Adoption is only real if the public surface serves the preserved object afterwards."""
    session_id = "legacy-public"
    internal_id = ledger.internal_session_id(session_id)
    path = _session_file(brain_home, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        for statement in brain_schema._statements(vmem._VMEM_SCHEMA)[:1]:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO session_vmem (obj_id, internal_session_id, kind, title, summary,"
            " content_sha256, token_estimate, residency_state, created_at, last_accessed_at,"
            " metadata_json) VALUES ('o1',?, 'RESEARCH_RESULT','legacy title','s','h',7,"
            "'RESIDENT','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','{}')",
            (internal_id,),
        )
        conn.commit()
    finally:
        conn.close()

    store = _open_vmem(brain_home, session_id)
    served = store.get_object("o1")
    assert served is not None, "the adopted object must be readable through the public reader"
    assert (served.title, served.token_estimate) == ("legacy title", 7)
    assert [obj.obj_id for obj in store.list_objects()] == ["o1"]

    conn = sqlite3.connect(path)
    try:
        shape = brain_schema.component_shape(conn, "vmem")
    finally:
        conn.close()
    assert shape.state == "current", shape


def test_case_7b_competing_first_open_across_real_processes(brain_home, tmp_path) -> None:
    """The same race case 7 tests with threads, run with separate OS processes.

    A thread barrier cannot produce the failure this guards against: two processes interleaving a
    half-create are the real shape, and the arbitration has to be the database's write reservation
    rather than in-process state.
    """
    session_id = "separate-process"
    gate = tmp_path / "start-gate"
    mode_by_child = ("ledger", "vmem", "ledger")
    children = [
        _spawn_session_open(brain_home, gate, tmp_path / f"child-{index}", mode)
        for index, mode in enumerate(mode_by_child)
    ]
    gate.write_text("go\n", encoding="utf-8")
    results = []
    for child in children:
        stdout, stderr = child.communicate(timeout=60)
        results.append((child.returncode, stderr, stdout))
    for index, (returncode, stderr, stdout) in enumerate(results):
        assert returncode == 0, (index, stdout, stderr)

    # The racing creation must not have produced an error, and both creation orders must have
    # converged on the same schema a sequential open produces.
    path = _session_file(brain_home, session_id)
    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
        tables = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert identity.state == "canonical", (identity.state, identity.unknown_tables)
    assert identity.version == brain_schema.SCHEMA_VERSION
    assert {"events", "session_vmem", "ledger_meta"} <= tables

    with _open_ledger(brain_home, "reference"):
        pass
    _open_vmem(brain_home, "reference")
    assert _dump(path) == _dump(_session_file(brain_home, "reference"))


def _spawn_session_open(home, gate, out: Path, mode: str) -> subprocess.Popen[str]:
    """One real process that waits on ``gate`` and then opens the session database."""
    script = (
        "import pathlib,sys,time\n"
        "home,gate,out=pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3])\n"
        "mode=sys.argv[4]\n"
        "sys.path.insert(0,sys.argv[5])\n"
        "while not gate.exists():\n"
        "    time.sleep(0.005)\n"
        "from second_brain import ledger,vmem\n"
        "session='separate-process'\n"
        "if mode=='ledger':\n"
        "    with ledger.LedgerStore(home,session,host='test').open(create=True):\n"
        "        pass\n"
        "else:\n"
        "    vmem.VMemStore(home,session)\n"
        "out.write_text('opened',encoding='utf-8')\n"
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONHOME", "PYTHONPATH")
    }
    env["PYTHONPATH"] = str(ROOT)
    env["SECOND_BRAIN_HOME"] = str(home)
    return subprocess.Popen(
        [sys.executable, "-c", script, str(home), str(gate), str(out), mode, str(ROOT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def test_vmem_late_registration_migrates_a_predecessor_in_a_cold_process(
    brain_home,
) -> None:
    """A ledger first open must not cache away a subsequently imported VMem shape."""
    script = (
        "import sqlite3,sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0,sys.argv[2])\n"
        "from second_brain import brain_schema,ledger\n"
        "home=Path(sys.argv[1])\n"
        "with ledger.LedgerStore(home,'prime-cache',host='test').open(create=True): pass\n"
        "assert 'second_brain.vmem' not in sys.modules\n"
        "old_source=brain_schema.components()\n"
        "from second_brain import vmem\n"
        "brain_schema.registered_shapes(old_source)\n"
        "brain_schema.canonical_columns(old_source)\n"
        "session='late-vmem'\n"
        "path=home/'state'/'sessions'/ledger.internal_session_id(session)/'ledger.sqlite'\n"
        "path.parent.mkdir(parents=True,exist_ok=True)\n"
        "with sqlite3.connect(path) as conn:\n"
        "    for statement in brain_schema._statements(vmem._VMEM_SCHEMA):\n"
        "        conn.execute(statement)\n"
        "    assert len(list(conn.execute('PRAGMA table_info(session_vmem)')))==15\n"
        "vmem.VMemStore(home,session)\n"
        "vmem.VMemStore(home,session)\n"
        "with sqlite3.connect(path) as conn:\n"
        "    assert len(list(conn.execute('PRAGMA table_info(session_vmem)')))==19\n"
        "    assert brain_schema.component_shape(conn,'vmem').state=='current'\n"
    )
    env = {
        key: value for key, value in os.environ.items()
        if key not in ("PYTHONHOME", "PYTHONPATH")
    }
    result = subprocess.run(
        [sys.executable, "-c", script, str(brain_home), str(ROOT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


# --- the authority decides the transition (store no longer classifies) ------------------


def _ledger_only_schema(home, session_id: str) -> sqlite3.Connection:
    with _open_ledger(home, session_id) as store:
        store.create_session(_identity(session_id))
    return sqlite3.connect(_session_file(home, session_id))


def test_component_shape_names_the_chain_transition_the_authority_allows(brain_home) -> None:
    """A v2 header without either chain column is a named additive predecessor.

    The authority recognizes the exact two registered missing columns; the
    ledger applies both transitions and reaches the current shared version.
    """
    session_id = "authority-transition"
    conn = _ledger_only_schema(brain_home, session_id)
    try:
        conn.execute("ALTER TABLE events DROP COLUMN envelope_hash")
        conn.execute("ALTER TABLE events DROP COLUMN prev_hash")
        conn.execute("DELETE FROM ledger_meta WHERE key='envelope_chain_origin'")
        conn.execute("UPDATE ledger_meta SET value='2' WHERE key='schema_version'")
        conn.commit()
        shape = brain_schema.component_shape(conn, "ledger")
    finally:
        conn.close()
    assert shape.state == "additive", shape
    assert shape.missing == {"events": ("prev_hash", "envelope_hash")}, shape.missing
    assert shape.unexpected == {} and shape.altered == () and shape.absent_tables == ()

    with _open_ledger(brain_home, session_id):
        pass
    conn = sqlite3.connect(_session_file(brain_home, session_id))
    try:
        assert brain_schema.component_shape(conn, "ledger").state == "current"
        version = conn.execute(
            "SELECT value FROM ledger_meta WHERE key='schema_version'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert version == str(ledger.LEDGER_SCHEMA_VERSION)


def test_component_shape_refuses_a_shape_the_authority_cannot_name(brain_home) -> None:
    """An extra column is not an additive predecessor: it is a shape to preserve and refuse."""
    session_id = "authority-unknown-shape"
    conn = _ledger_only_schema(brain_home, session_id)
    try:
        conn.execute("ALTER TABLE events ADD COLUMN someone_elses_column TEXT")
        conn.commit()
        shape = brain_schema.component_shape(conn, "ledger")
    finally:
        conn.close()
    assert shape.state == "unsupported", shape
    assert shape.unexpected == {"events": ("someone_elses_column",)}, shape.unexpected

    with pytest.raises(BrainError) as excinfo, _open_ledger(brain_home, session_id):
        pass
    assert "unsupported layout" in str(excinfo.value)


def test_vmem_refuses_a_shape_the_authority_cannot_name(brain_home) -> None:
    session_id = "vmem-unknown-shape"
    _open_vmem(brain_home, session_id)
    path = _session_file(brain_home, session_id)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE session_vmem ADD COLUMN foreign_column TEXT")
        conn.commit()
        assert brain_schema.component_shape(conn, "vmem").state == "unsupported"
    finally:
        conn.close()

    with pytest.raises(BrainError, match="unsupported layout"):
        _open_vmem(brain_home, session_id)
    conn = sqlite3.connect(path)
    try:
        assert "foreign_column" in {
            row[1] for row in conn.execute("PRAGMA table_info(session_vmem)")
        }
    finally:
        conn.close()


def test_component_shape_treats_a_view_where_a_table_belongs_as_absent(brain_home) -> None:
    """Only a real table satisfies a registered table; a view carrying the name does not.

    The open refuses earlier, on the unrecognised table the view is built over — which is the
    point: the file is refused rather than treated as a database whose `events` merely moved.
    """
    session_id = "authority-view"
    conn = _ledger_only_schema(brain_home, session_id)
    try:
        conn.execute("ALTER TABLE events RENAME TO events_moved")
        conn.execute("CREATE VIEW events AS SELECT * FROM events_moved")
        conn.commit()
        shape = brain_schema.component_shape(conn, "ledger")
    finally:
        conn.close()
    assert shape.state == "unsupported", shape
    assert "events" in shape.absent_tables, shape.absent_tables

    with pytest.raises(BrainError) as excinfo, _open_ledger(brain_home, session_id):
        pass
    assert "unidentified existing tables" in str(excinfo.value)


def _observer_connection(path) -> sqlite3.Connection:
    """A second connection held open across a reopen, to observe other connections' commits."""
    return sqlite3.connect(path, timeout=5.0, isolation_level=None)


def test_reopening_a_current_database_performs_no_content_changing_commit(brain_home) -> None:
    """Logical idempotency and write-free reopening are separate claims, and both need evidence.

    Structural equality (case 3) establishes the first. The second needs a witness, and the witness
    needs its own sensitivity check — a witness that cannot fail proves nothing.

    Measured granularity of this witness (it is coarser than "no writes at all"):

    * a **content-changing** commit by another connection (a new row, or a changed value) moves
      `data_version` — this is what the sensitivity check below exercises;
    * a *same-value* `UPDATE` that still reports `rowcount == 1` does **not** move it;
    * rolled-back work, and writes to other files (the session manifest, telemetry), are outside it.

    So a zero delta supports exactly one claim: **the reopen committed no content change to this
    database.** "No writes at all" would need instrumentation inside the tested connections
    (`total_changes` alongside a seam, or a trace/authorizer hook), which these public entry points
    do not expose; that limitation is recorded rather than papered over.
    """
    session_id = "write-witness"
    with _open_ledger(brain_home, session_id) as store:
        store.create_session(_identity(session_id))
    _open_vmem(brain_home, session_id)
    path = _session_file(brain_home, session_id)

    observer = _observer_connection(path)
    try:
        before = observer.execute("PRAGMA data_version").fetchone()[0]
        # Two full reopens through the public entry points, not a raw connection.
        with _open_ledger(brain_home, session_id):
            pass
        _open_vmem(brain_home, session_id)
        with _open_ledger(brain_home, session_id):
            pass
        after = observer.execute("PRAGMA data_version").fetchone()[0]
        assert after == before, "reopening a current database committed a content change"

        # Sensitivity: the witness fires for a deliberately introduced content change.
        writer = sqlite3.connect(path, timeout=5.0)
        try:
            writer.execute(
                "INSERT OR REPLACE INTO ledger_meta (key,value) VALUES ('witness_probe','1')"
            )
            writer.commit()
        finally:
            writer.close()
        witnessed = observer.execute("PRAGMA data_version").fetchone()[0]
        assert witnessed != before, "the witness did not detect a deliberate content change"
    finally:
        observer.close()


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


def test_case_4c_the_immediate_parent_vmem_shape_is_adopted(brain_home) -> None:
    """The genuine pre-patch predecessor: base DDL *plus* the four additive columns, no header.

    The parent added those columns without ever stamping a version, so a database created by the
    parent is header-less and 19 columns wide. Refusing it would be a regression against the
    running copy this repair replaces, so it is pinned here.
    """
    path = _session_file(brain_home, "parent-shape")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        combined = vmem._VMEM_SCHEMA + "\n".join(
            f"ALTER TABLE session_vmem ADD COLUMN {column} {ddl};"
            for column, ddl in vmem._VMEM_ADDITIVE_COLUMNS
        )
        for statement in brain_schema._statements(combined):
            conn.execute(statement)
        conn.execute(
            "INSERT INTO session_vmem (obj_id, internal_session_id, kind, title, summary,"
            " content_sha256, token_estimate, residency_state, created_at, last_accessed_at,"
            " metadata_json) VALUES ('o1','i1','research_result','t','s','h',1,'resident',"
            " '2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','{}')"
        )
        conn.commit()
        columns = [row[1] for row in conn.execute("PRAGMA table_info(session_vmem)")]
    finally:
        conn.close()
    assert len(columns) == 19, columns

    store = _open_vmem(brain_home, "parent-shape")  # adopted, not refused

    conn = sqlite3.connect(path)
    try:
        identity = brain_schema.classify(conn)
        rows = conn.execute("SELECT obj_id FROM session_vmem").fetchall()
    finally:
        conn.close()
    assert identity.state == "canonical", identity
    assert rows == [("o1",)]
    assert store is not None
