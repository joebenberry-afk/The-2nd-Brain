"""The real migration chain, described by what each version means.

A pin such as ``assert version == 26`` records that a number moved; it cannot say whether the
schema that number promises exists. These tests build a database at a named predecessor with the
**real** migration files, then migrate step by step and assert the structures each version
introduces — the reservation table (25), the notification outbox (26), the reservation lifecycle
columns (27) — together with the ordered remainder, the no-op at the head, and the restart after
an interrupted version.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from second_brain import db


def _numbers() -> list[int]:
    return [int(p.name[:4]) for p in db.migration_files()]


def _head() -> int:
    return max(_numbers())


def _above(version: int) -> list[int]:
    return [number for number in _numbers() if number > version]


def _chain(base: Path, upto: int) -> Path:
    """A migration directory holding the real chain through ``upto``."""
    target = base / f"migrations-through-{upto}"
    target.mkdir()
    for path in db.migration_files():
        if int(path.name[:4]) <= upto:
            shutil.copy2(path, target / path.name)
    return target


def _db_at(base: Path, version: int) -> Path:
    """A database whose real chain stops at ``version``."""
    dbfile = base / f"brain-{version}.sqlite"
    applied = db.migrate(dbfile, migrations_dir=_chain(base, version))
    assert applied == list(range(1, version + 1)), applied
    return dbfile


def _columns(dbfile: Path, table: str) -> set[str]:
    conn = db.connect(dbfile)
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _tables(dbfile: Path) -> set[str]:
    conn = db.connect(dbfile)
    try:
        return {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def _versions(dbfile: Path) -> list[int]:
    conn = db.connect(dbfile)
    try:
        return [row["version"] for row in conn.execute("SELECT version FROM schema_version")]
    finally:
        conn.close()


def _fingerprint(dbfile: Path) -> list[tuple[str, str, str]]:
    """Schema objects with their SQL: changes are visible, sameness is checkable."""
    conn = db.connect(dbfile)
    try:
        return [
            (row["type"], row["name"], row["sql"] or "")
            for row in conn.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )
        ]
    finally:
        conn.close()


def test_the_chain_is_contiguous_and_unique_through_the_head() -> None:
    numbers = _numbers()
    assert numbers == sorted(numbers)
    # A gap would mean a recorded version can never be reached again; a duplicate would make the
    # applied-version set ambiguous.
    assert numbers == list(range(1, len(numbers) + 1)), numbers
    # The versions this campaign added are present, not renumbered away.
    assert {24, 25, 26, 27} <= set(numbers)


def test_each_version_adds_the_structures_it_promises(tmp_path: Path) -> None:
    base = tmp_path / "stepwise"
    base.mkdir()
    dbfile = _db_at(base, 24)
    assert "budget_reservations" not in _tables(dbfile)
    assert "notification_pending" not in _columns(dbfile, "worker_task_meta")

    # 25: the reservation table, which is what makes reserve-before-dispatch durable.
    assert db.migrate(dbfile, migrations_dir=_chain(base, 25)) == [25]
    reservation_columns = _columns(dbfile, "budget_reservations")
    assert {
        "reservation_id",
        "session_id",
        "task_id",
        "role",
        "tokens",
        "created_at",
        "consumed_at",
    } <= reservation_columns
    # The lifecycle columns arrive only with 27, so 25 alone must not claim them.
    assert not {"episode_id", "cancelled_at", "resolution"} & reservation_columns
    # One reservation per (session, task): this is what makes reserving idempotent per attempt.
    conn = db.connect(dbfile)
    try:
        conn.execute(
            "INSERT INTO budget_reservations VALUES('r1','s','t','worker',5,'2026-01-01',NULL,NULL)"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO budget_reservations "
                "VALUES('r2','s','t','worker',5,'2026-01-01',NULL,NULL)"
            )
        conn.rollback()
    finally:
        conn.close()

    # 26: the outbox is additive, so a row written before it must survive with a default.
    conn = db.connect(dbfile)
    try:
        conn.execute(
            "INSERT INTO worker_task_meta(task_id, updated_at) VALUES('pre-outbox','2026-01-01')"
        )
        conn.commit()
    finally:
        conn.close()
    assert db.migrate(dbfile, migrations_dir=_chain(base, 26)) == [26]
    outbox_columns = _columns(dbfile, "worker_task_meta")
    assert {"notification_event_key", "notification_pending", "notification_delivered_at"} <= (
        outbox_columns
    )
    conn = db.connect(dbfile)
    try:
        row = conn.execute(
            "SELECT notification_pending FROM worker_task_meta WHERE task_id='pre-outbox'"
        ).fetchone()
        assert row["notification_pending"] == 0
    finally:
        conn.close()

    # 27: the reservation lifecycle, additive to the reservations already recorded.
    assert db.migrate(dbfile, migrations_dir=_chain(base, 27)) == [27]
    lifecycle_columns = _columns(dbfile, "budget_reservations")
    assert {
        "episode_id",
        "cancelled_at",
        "cancel_reason",
        "resolved_at",
        "resolution",
        "actual_tokens",
    } <= lifecycle_columns
    conn = db.connect(dbfile)
    try:
        row = conn.execute(
            "SELECT cancelled_at, consumed_at, resolution FROM budget_reservations "
            "WHERE task_id='t'"
        ).fetchone()
        assert (row["cancelled_at"], row["consumed_at"], row["resolution"]) == (None, None, None)
    finally:
        conn.close()

    # 28: runtime bindings join the control database; neither table enrolls an issuer.
    assert db.migrate(dbfile, migrations_dir=_chain(base, 28)) == [28]
    assert {"runtime_lineage", "episode_roots"} <= _tables(dbfile)
    assert {"issuer_generation", "runtime_generation", "evidence_sha256"} <= _columns(
        dbfile, "runtime_lineage"
    )
    assert db.pending_migrations(dbfile) == []


@pytest.mark.parametrize("predecessor", [24, 25, 26])
def test_a_predecessor_applies_the_ordered_remainder_exactly_once(
    tmp_path: Path, predecessor: int
) -> None:
    base = tmp_path / f"from-{predecessor}"
    base.mkdir()
    dbfile = _db_at(base, predecessor)

    assert db.pending_migrations(dbfile) == _above(predecessor)
    assert db.migrate(dbfile) == _above(predecessor)

    # Exactly one canonical result: the head is recorded once, with no duplicate version rows.
    versions = _versions(dbfile)
    assert versions == list(range(1, _head() + 1)), versions
    assert db.migrate(dbfile) == []


def test_reopening_a_current_database_is_a_no_op(tmp_path: Path) -> None:
    base = tmp_path / "reopen"
    base.mkdir()
    dbfile = _db_at(base, _head())
    before = _fingerprint(dbfile)

    assert db.migrate(dbfile) == []
    assert _fingerprint(dbfile) == before
    assert _versions(dbfile) == list(range(1, _head() + 1))

    # Sensitivity control: the fingerprint really does notice a schema change.
    conn = db.connect(dbfile)
    try:
        conn.execute("CREATE TABLE witness_probe(x INTEGER)")
        conn.commit()
    finally:
        conn.close()
    assert _fingerprint(dbfile) != before


def test_an_interrupted_version_rolls_back_and_restarts_to_one_canonical_result(
    tmp_path: Path,
) -> None:
    base = tmp_path / "interrupted"
    base.mkdir()
    dbfile = _db_at(base, 25)

    # The real files, with a defect appended to 26 after its own statements: the version's
    # transaction cannot commit, which is the same boundary a crash inside it would leave.
    broken = base / "migrations-broken"
    broken.mkdir()
    for path in db.migration_files():
        shutil.copy2(path, broken / path.name)
    outbox = broken / "0026_worker_notification_outbox.sql"
    outbox.write_text(
        outbox.read_text(encoding="utf-8")
        + "\nALTER TABLE notification_probe_missing ADD COLUMN x TEXT;\n",
        encoding="utf-8",
    )

    with pytest.raises((sqlite3.Error, db.MigrationError)):
        db.migrate(dbfile, migrations_dir=broken)

    # Nothing from 26 survived the failed version, and 26 is still pending.
    assert _versions(dbfile) == list(range(1, 26))
    assert not {"notification_event_key", "notification_pending"} & _columns(
        dbfile, "worker_task_meta"
    )
    assert db.pending_migrations(dbfile) == _above(25)

    # Restoring the real file bytes (fresh process semantics: a new call, new connection) resumes
    # deterministically and lands on exactly one canonical result.
    shutil.copy2(db.MIGRATIONS_DIR / "0026_worker_notification_outbox.sql", outbox)
    assert db.migrate(dbfile, migrations_dir=broken) == _above(25)
    assert _versions(dbfile) == list(range(1, _head() + 1))
    assert {"notification_event_key", "notification_pending", "notification_delivered_at"} <= (
        _columns(dbfile, "worker_task_meta")
    )


def test_lineage_upgrade_preserves_existing_attempt_and_reservation(tmp_path: Path) -> None:
    base = tmp_path / "upgrade-27"
    base.mkdir()
    dbfile = _db_at(base, 27)
    conn = db.connect(dbfile)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        conn.execute(
            "INSERT INTO worker_tasks(task_id,state,lease_expires_at,packet_sha256,updated_at,"
            "attempt_id,writer_ownership,host_session_id) VALUES(?,?,?,?,?,?,?,?)",
            ("task", "working", "2026-12-01", "abc", "2026-09-22", "attempt", "held", "root"),
        )
        conn.execute(
            "INSERT INTO worker_task_meta(task_id,session_id,updated_at) VALUES(?,?,?)",
            ("task", "root", "2026-09-22"),
        )
        conn.execute(
            "INSERT INTO budget_reservations("
            "reservation_id,session_id,task_id,role,tokens,created_at,episode_id,"
            "resolution,actual_tokens) VALUES(?,?,?,?,?,?,?,?,?)",
            ("reservation", "root", "task", "worker", 40, "2026-09-22", "episode", "unresolved", 0),
        )
        conn.commit()
    finally:
        conn.close()

    assert db.migrate(dbfile) == [28]
    assert db.migrate(dbfile) == []
    conn = db.connect(dbfile)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert tuple(
            conn.execute(
                "SELECT attempt_id,writer_ownership,host_session_id FROM worker_tasks "
                "WHERE task_id='task'"
            ).fetchone()
        ) == ("attempt", "held", "root")
        assert tuple(
            conn.execute(
                "SELECT tokens,resolution,actual_tokens FROM budget_reservations "
                "WHERE reservation_id='reservation'"
            ).fetchone()
        ) == (40, "unresolved", 0)
        assert (
            conn.execute("SELECT session_id FROM worker_task_meta WHERE task_id='task'").fetchone()[
                0
            ]
            == "root"
        )
    finally:
        conn.close()


def test_unresolved_historical_writer_blocks_upgrade_without_mutation(tmp_path: Path) -> None:
    base = tmp_path / "unresolved-upgrade"
    base.mkdir()
    dbfile = _db_at(base, 23)
    with db.connect(dbfile) as conn:
        conn.execute(
            "INSERT INTO worker_tasks("
            "task_id,state,lease_expires_at,packet_sha256,updated_at,attempt_id,"
            "access_intent,worktree_id,worktree_root,writer_ownership"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "unresolved",
                "WORKING",
                "2026-09-06",
                "a" * 64,
                "2026-09-05",
                "attempt-unresolved",
                "mutating",
                "b" * 64,
                "/historical/path",
                "quarantined",
            ),
        )
    before = _fingerprint(dbfile)
    for _ in range(2):
        with pytest.raises(db.MigrationError, match="unresolved historical holders"):
            db.migrate(dbfile)
        assert _versions(dbfile) == list(range(1, 24))
        assert _fingerprint(dbfile) == before
        with db.connect(dbfile) as conn:
            row = conn.execute(
                "SELECT attempt_id,writer_ownership FROM worker_tasks WHERE task_id='unresolved'"
            ).fetchone()
        assert tuple(row) == ("attempt-unresolved", "quarantined")


def test_historical_lineage_rows_survive_reopen_and_idempotent_upgrade(tmp_path: Path) -> None:
    base = tmp_path / "historical-lineage"
    base.mkdir()
    dbfile = _db_at(base, 27)
    assert db.migrate(dbfile) == [28]
    with db.connect(dbfile) as conn:
        conn.execute(
            "INSERT INTO runtime_lineage VALUES(?,?,?,?,?,?,?,?,?)",
            ("episode", "root", None, "root", "issuer", 1, 1, 1, "a" * 64),
        )
        conn.execute(
            "INSERT INTO episode_roots VALUES(?,?,?,?,?,?)",
            ("episode", "root", "issuer", 1, "root", 1),
        )
    schema_before = _fingerprint(dbfile)
    assert db.migrate(dbfile) == []
    assert _fingerprint(dbfile) == schema_before
    with db.connect(dbfile) as conn:
        assert tuple(conn.execute("SELECT * FROM runtime_lineage").fetchone()) == (
            "episode",
            "root",
            None,
            "root",
            "issuer",
            1,
            1,
            1,
            "a" * 64,
        )
        assert tuple(conn.execute("SELECT * FROM episode_roots").fetchone()) == (
            "episode",
            "root",
            "issuer",
            1,
            "root",
            1,
        )


def test_terminal_writer_history_keeps_identity_through_physical_upgrade(tmp_path: Path) -> None:
    base = tmp_path / "terminal-upgrade"
    base.mkdir()
    dbfile = _db_at(base, 23)
    with db.connect(dbfile) as conn:
        conn.execute(
            "INSERT INTO worker_tasks("
            "task_id,state,lease_expires_at,packet_sha256,updated_at,attempt_id,"
            "access_intent,worktree_id,worktree_root,writer_ownership"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "terminal",
                "COMPLETED",
                "2026-09-06",
                "a" * 64,
                "2026-09-05",
                "attempt-terminal",
                "mutating",
                "b" * 64,
                "/historical/path",
                "released",
            ),
        )
    assert db.migrate(dbfile) == _above(23)
    assert db.migrate(dbfile) == []
    with db.connect(dbfile) as conn:
        row = conn.execute(
            "SELECT attempt_id,worktree_id,worktree_root,writer_ownership "
            "FROM worker_tasks WHERE task_id='terminal'"
        ).fetchone()
        index_columns = [
            info["name"]
            for info in conn.execute("PRAGMA index_info(idx_worker_tasks_writer_physical)")
        ]
    assert tuple(row) == ("attempt-terminal", "b" * 64, "/historical/path", "released")
    assert index_columns == ["worktree_id"]
