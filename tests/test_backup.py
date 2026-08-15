import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from second_brain import backup as backup_mod
from second_brain import db, paths
from second_brain.errors import BackupError


def _seed(home, marker):
    conn = db.connect(db.db_path(home))
    conn.execute(
        "INSERT INTO projects (id, name, created_at) VALUES (?, ?, '2026-01-01')",
        (f"p-{marker}", marker),
    )
    conn.commit()
    conn.close()
    (home / "config" / "brain.toml").write_text(f"schema_version = 1\nnote = {marker!r}\n")


def test_backup_roundtrip_into_empty_home(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home, note="roundtrip test")
    manifest = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == 1
    assert manifest["db"]["file"] == "brain.sqlite"

    # restore into a fresh brain home
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    backup_mod.restore_backup(home2, bdir)
    conn = db.connect(db.db_path(home2))
    try:
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "orig"
    finally:
        conn.close()
    assert (home2 / "config" / "brain.toml").read_text(encoding="utf-8").find("orig") != -1


def test_backup_db_is_consistent_snapshot(brain_home):
    _seed(brain_home, "snap")
    bdir = backup_mod.create_backup(brain_home)
    snap = sqlite3.connect(bdir / "brain.sqlite")
    try:
        assert snap.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert snap.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    finally:
        snap.close()


def test_restore_refuses_without_force(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    paths.ensure_layout(home2)
    db.migrate(db.db_path(home2))
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    with pytest.raises(BackupError, match="--force"):
        backup_mod.restore_backup(home2, bdir)


def test_restore_force_moves_current_aside(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    paths.ensure_layout(home2)
    db.migrate(db.db_path(home2))
    _seed(home2, "current")
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    backup_mod.restore_backup(home2, bdir, force=True)
    # current data moved aside, backup data restored
    conn = db.connect(db.db_path(home2))
    try:
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "orig"
    finally:
        conn.close()
    asides = list((home2 / "backups").glob("pre-restore-*"))
    assert len(asides) == 1
    aside_db = sqlite3.connect(asides[0] / "db" / "brain.sqlite")
    try:
        assert aside_db.execute("SELECT name FROM projects").fetchone()[0] == "current"
    finally:
        aside_db.close()


def test_corrupt_db_hash_refused(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    (bdir / "brain.sqlite").write_bytes(b"tampered")
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    with pytest.raises(BackupError, match="hash mismatch"):
        backup_mod.restore_backup(home2, bdir)


def test_restore_verifies_restored_db_byte_identity(brain_home, tmp_path, monkeypatch):
    """The restored file itself is verified against the manifest sha256; a
    corrupted copy must fail the restore, never silently pass."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    paths.ensure_layout(home2)
    db.migrate(db.db_path(home2))
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))

    real_copy2 = shutil.copy2

    def corrupting_copy2(src, dst, *a, **kw):
        real_copy2(src, dst, *a, **kw)
        if Path(dst).name == "brain.sqlite":
            with open(dst, "ab") as f:
                f.write(b"corruption")

    monkeypatch.setattr(backup_mod.shutil, "copy2", corrupting_copy2)
    with pytest.raises(BackupError, match="byte-identity"):
        backup_mod.restore_backup(home2, bdir, force=True)
    # the previous state was rolled back in place, not left corrupt
    conn = db.connect(db.db_path(home2))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_not_a_backup_raises(tmp_path, monkeypatch):
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    with pytest.raises(BackupError, match="manifest"):
        backup_mod.restore_backup(home2, tmp_path)


def test_restore_applies_pending_migrations(brain_home, tmp_path, monkeypatch):
    """A backup restored under newer code is upgraded to the current schema."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)

    extra = tmp_path / "migs"
    extra.mkdir()
    # 0008: the real migration set ends at 0007 (Phase 6 memory index); the
    # custom migration must sort AFTER it to be "pending" on restore.
    (extra / "0008_extra.sql").write_text("CREATE TABLE extra_table (x INTEGER);")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", extra)
    backup_mod.restore_backup(home2, bdir)
    conn = db.connect(db.db_path(home2))
    try:
        v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        assert v == 8
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "extra_table" in tables
    finally:
        conn.close()


def test_list_backups_sorted(brain_home):
    assert backup_mod.list_backups(brain_home) == []
    b1 = backup_mod.create_backup(brain_home)
    b2 = backup_mod.create_backup(brain_home)
    backups = backup_mod.list_backups(brain_home)
    assert backups[0] == b2
    assert backups[1] == b1


def test_restore_drops_stale_wal_shm(brain_home, tmp_path, monkeypatch):
    """A stale -wal/-shm must never survive a restore (WAL replay would
    resurrect moved-aside data when salts match)."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    paths.ensure_layout(home2)
    db.migrate(db.db_path(home2))
    _seed(home2, "current")
    # simulate uncheckpointed WAL state next to the target DB
    (db.db_path(home2).parent / "brain.sqlite-wal").write_bytes(b"stale-wal-frames")
    (db.db_path(home2).parent / "brain.sqlite-shm").write_bytes(b"stale-shm")
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))

    backup_mod.restore_backup(home2, bdir, force=True)

    assert not (db.db_path(home2).parent / "brain.sqlite-wal").exists()
    assert not (db.db_path(home2).parent / "brain.sqlite-shm").exists()
    conn = db.connect(db.db_path(home2))
    try:
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "orig"
    finally:
        conn.close()
    # the stale files were moved aside, not destroyed
    asides = list((home2 / "backups").glob("pre-restore-*"))
    assert len(asides) == 1
    assert (asides[0] / "db" / "brain.sqlite-wal").exists()
    assert (asides[0] / "db" / "brain.sqlite-shm").exists()


def test_restore_failure_rolls_back_aside(brain_home, tmp_path, monkeypatch):
    """If restore fails mid-way, the target must be preserved in place."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    paths.ensure_layout(home2)
    db.migrate(db.db_path(home2))
    _seed(home2, "current")
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))

    def boom(*a, **kw):
        raise RuntimeError("simulated failure during upgrade")

    monkeypatch.setattr(db, "migrate", boom)
    with pytest.raises(BackupError, match="preserved in place"):
        backup_mod.restore_backup(home2, bdir, force=True)

    conn = db.connect(db.db_path(home2))
    try:
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "current"
    finally:
        conn.close()
    # rollback removed the empty aside dir
    assert list((home2 / "backups").glob("pre-restore-*")) == []


def test_restore_git_inits_target(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    backup_mod.restore_backup(home2, bdir)
    assert (home2 / ".git").exists()


# ---------------------------------------------------------------------------
# SEC-01: manifest path escape / unsafe restore
# ---------------------------------------------------------------------------


def _hostile_manifest(bdir, entries):
    """Rewrite the manifest's 'copied' list in place (keeps db hash valid)."""
    manifest_path = bdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["copied"] = entries
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    "entry",
    [
        "../outside",
        "..\\outside",
        "config/../../outside",
        "/absolute",
        "C:\\outside",
        "\\server\\share",
        "..",
        ".",
    ],
)
def test_restore_rejects_hostile_manifest_entries(brain_home, tmp_path, monkeypatch, entry):
    """SEC-T022..T026: hostile manifest entries abort before any mutation."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    _hostile_manifest(bdir, [entry])

    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    db.migrate(db.db_path(home2))
    marker = home2 / "config" / "brain.toml"
    marker.write_text("schema_version = 1\nnote = 'current'\n", encoding="utf-8")

    with pytest.raises(BackupError, match="unsafe"):
        backup_mod.restore_backup(home2, bdir, force=True)
    # Nothing was moved aside or overwritten; the target is untouched.
    assert "current" in marker.read_text(encoding="utf-8")
    assert list((home2 / "backups").glob("pre-restore-*")) == []


def test_restore_rejects_hostile_db_file_name(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    manifest_path = bdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["db"]["file"] = "../../evil.sqlite"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    db.migrate(db.db_path(home2))
    with pytest.raises(BackupError, match=r"db\.file"):
        backup_mod.restore_backup(home2, bdir)


def test_restore_cannot_delete_outside_brain_root(brain_home, tmp_path, monkeypatch):
    """SEC-T029: a manifest cannot make restore recursively delete outside."""
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    # The entry is relative to the restore root; `..` must not reach victim.
    _hostile_manifest(bdir, ["../victim"])

    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    with pytest.raises(BackupError, match="unsafe"):
        backup_mod.restore_backup(home2, bdir, force=True)
    assert (victim / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_rejects_symlink_escape_in_tree(brain_home, tmp_path, monkeypatch):
    """SEC-T027: a symlink inside a restored directory tree is rejected."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    outside = tmp_path / "outside-content"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    target_dir = bdir / "config"
    link = target_dir / "leak"
    try:
        kwargs = {"target_is_directory": True} if os.name == "nt" else {}
        os.symlink(outside, link, **kwargs)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")

    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    with pytest.raises(BackupError, match="symlink"):
        backup_mod.restore_backup(home2, bdir)


def test_restore_rejects_symlinked_destination(brain_home, tmp_path, monkeypatch):
    """SEC-T027b: a destination chain that resolves outside is refused."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    outside = tmp_path / "outside-home"
    outside.mkdir()
    # Replace the freshly laid-out empty projects/ dir with a symlink.
    (home2 / "projects").rmdir()
    try:
        kwargs = {"target_is_directory": True} if os.name == "nt" else {}
        os.symlink(outside, home2 / "projects", **kwargs)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(BackupError, match="unsafe"):
        backup_mod.restore_backup(home2, bdir, force=True)


def test_restore_empty_copied_entry_rejected(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    _hostile_manifest(bdir, [""])
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    with pytest.raises(BackupError, match="non-empty string"):
        backup_mod.restore_backup(home2, bdir)


def test_restore_non_string_copied_entry_rejected(brain_home, tmp_path, monkeypatch):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    _hostile_manifest(bdir, ["config", 42])
    home2 = tmp_path / "brain2"
    home2.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    paths.ensure_layout(home2)
    with pytest.raises(BackupError, match="non-empty string"):
        backup_mod.restore_backup(home2, bdir)
