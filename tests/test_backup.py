import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from second_brain import backup as backup_mod
from second_brain import db, doctor, frontier, immune, paths, promotion, semantic
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
    assert manifest["format"] == 2
    assert manifest["db"]["file"] == "brain.sqlite"

    # restore into a fresh brain home
    home2 = tmp_path / "brain2"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home2))
    backup_mod.restore_backup(home2, bdir)
    conn = db.connect(db.db_path(home2))
    try:
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "orig"
    finally:
        conn.close()
    assert (home2 / "config" / "brain.toml").read_text(encoding="utf-8").find("orig") != -1
    checks = []
    doctor.check_layout(home2, checks)
    assert all(check.status == doctor.STATUS_OK for check in checks)


def test_backup_refuses_missing_canonical_memory_before_publishing(brain_home):
    memory_id = semantic.add_memory(
        brain_home, "Durable fact", "Keep its original body.", scope="global"
    )
    row = semantic.show_memory(brain_home, memory_id)["row"]
    (brain_home / row["body_path"]).unlink()

    with pytest.raises(BackupError):
        backup_mod.create_backup(brain_home)

    assert backup_mod.list_backups(brain_home) == []


def test_incomplete_snapshot_is_refused_before_creating_restore_target(brain_home, tmp_path):
    memory_id = semantic.add_memory(
        brain_home, "Durable fact", "Keep its original body.", scope="global"
    )
    relative = semantic.show_memory(brain_home, memory_id)["row"]["body_path"]
    snapshot = backup_mod.create_backup(brain_home)
    (snapshot / relative).unlink()
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].pop(str(relative).replace("\\", "/"))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = tmp_path / "must-stay-absent"

    with pytest.raises(BackupError):
        backup_mod.restore_backup(target, snapshot)

    assert not target.exists()


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
    with pytest.raises(BackupError):
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
    # A synthetic migration after the current v2 schema proves restore upgrades
    # rather than merely copying the snapshot.
    next_version = int(db.migration_files()[-1].name[:4]) + 1
    (extra / f"{next_version:04d}_extra.sql").write_text("CREATE TABLE extra_table (x INTEGER);")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", extra)
    backup_mod.restore_backup(home2, bdir)
    conn = db.connect(db.db_path(home2))
    try:
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


def test_format_two_preserves_all_canonical_roots(brain_home, tmp_path, monkeypatch):
    canonical_files = {
        "memory/semantic/manual.md": "memory",
        "experiences/successes/result.md": "experience",
        "decisions/global/decision.md": "decision",
        "skills/principles/rule.md": "skill",
        "engrams/active/procedure.md": "engram",
    }
    for rel, content in canonical_files.items():
        path = brain_home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    backup_dir = backup_mod.create_backup(brain_home)
    manifest = backup_mod.load_manifest(backup_dir)
    assert manifest["format"] == 2
    assert set(backup_mod.SNAPSHOT_DIRS) == set(manifest["canonical_paths"])

    restored = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(restored))
    backup_mod.restore_backup(restored, backup_dir)
    for rel, content in canonical_files.items():
        assert (restored / rel).read_text(encoding="utf-8") == content


def test_restore_rejects_modified_canonical_file(brain_home, tmp_path):
    source = brain_home / "memory/semantic/manual.md"
    source.write_text("trusted", encoding="utf-8")
    backup_dir = backup_mod.create_backup(brain_home)
    (backup_dir / "memory/semantic/manual.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(BackupError, match="canonical file hash mismatch"):
        backup_mod.restore_backup(tmp_path / "restored", backup_dir)


# ---------------------------------------------------------------------------
# Audit F-02: closed restore inventory
# ---------------------------------------------------------------------------


def test_restore_rejects_file_missing_from_hash_inventory(brain_home, tmp_path, monkeypatch):
    """A file added to a valid backup is refused; the manifest is untouched."""
    (brain_home / "constitution" / "marker.md").write_text("declared", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    (bdir / "constitution" / "unlisted-review-marker.md").write_text("unlisted", encoding="utf-8")
    target = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))

    with pytest.raises(BackupError, match="not covered by the manifest hash inventory"):
        backup_mod.restore_backup(target, bdir)

    assert not target.exists()  # refused before touching the destination


def test_restore_rejects_file_outside_declared_roots(brain_home, tmp_path, monkeypatch):
    (brain_home / "constitution" / "marker.md").write_text("declared", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    (bdir / "orphan.txt").write_text("not under any declared root", encoding="utf-8")
    target = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))

    with pytest.raises(BackupError, match="outside the declared inventory"):
        backup_mod.restore_backup(target, bdir)

    assert not target.exists()


def test_restore_rejects_noncanonical_root(brain_home, tmp_path):
    """Normally excluded runtime state cannot be smuggled in as a root."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    shutil.copytree(brain_home / "state", bdir / "state", dirs_exist_ok=True)
    manifest_path = bdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["copied"] = [*manifest["copied"], "state"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="not a canonical Brain root"):
        backup_mod.restore_backup(tmp_path / "restored", bdir)


def test_format_two_requires_database_hash(brain_home, tmp_path):
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    manifest_path = bdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["db"].pop("sha256")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="missing the database sha256"):
        backup_mod.restore_backup(tmp_path / "restored", bdir)


def test_legacy_format_one_restore_stays_possible_and_closed(brain_home, tmp_path, monkeypatch):
    """Legacy backups still restore, and are still closed to additions."""
    (brain_home / "constitution" / "marker.md").write_text("legacy", encoding="utf-8")
    (brain_home / "config" / "brain.toml").write_text(
        "schema_version = 1\nnote = 'legacy'\n", encoding="utf-8"
    )
    bdir = backup_mod.create_backup(brain_home)
    manifest_path = bdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format"] = 1
    manifest.pop("files", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    target = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))
    backup_mod.restore_backup(target, bdir)
    assert (target / "constitution" / "marker.md").read_text(encoding="utf-8") == "legacy"

    (bdir / "orphan.txt").write_text("unlisted", encoding="utf-8")
    with pytest.raises(BackupError, match="outside the declared inventory"):
        backup_mod.restore_backup(tmp_path / "restored2", bdir)


# ---------------------------------------------------------------------------
# Audit F-03: governance authority survives backup and restore
# ---------------------------------------------------------------------------


def _promote_to_active(home, name="curator"):
    from test_promotion import _approve, _bind, _evidence, _skill

    _skill(home, name=name)
    _evidence(home, name)
    _approve(home, name)
    _bind(home, name)
    assert promotion.promote(home, name, "shadow", "candidate")["promoted"] is True
    assert promotion.promote(home, name, "candidate", "active")["promoted"] is True


def test_backup_declares_governance_roots(brain_home):
    _promote_to_active(brain_home)
    manifest = backup_mod.load_manifest(backup_mod.create_backup(brain_home))

    assert set(backup_mod.GOVERNANCE_DIRS) <= set(manifest["canonical_paths"])
    assert "state/promotions" in manifest["copied"]


def test_backup_restore_preserves_promotion_authority(brain_home, tmp_path, monkeypatch):
    _promote_to_active(brain_home)
    bdir = backup_mod.create_backup(brain_home)
    restored = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(restored))

    backup_mod.restore_backup(restored, bdir)

    assert promotion.is_active(restored, "curator") is True
    assert promotion._last_active_version(restored, "curator") == 1
    assert promotion.authority_gaps(restored) == []
    assert promotion.demote(restored, "curator", "candidate", "round-trip check")["demoted"] is True
    result = promotion.promote(restored, "curator", "candidate", "active")
    assert result["promoted"] is False
    assert result["reason"] == "version_not_incremented"


def test_backup_restore_preserves_immune_history(brain_home, tmp_path, monkeypatch):
    from test_promotion import _rollback_record

    _promote_to_active(brain_home)
    _rollback_record(brain_home, "curator")
    bdir = backup_mod.create_backup(brain_home)
    restored = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(restored))

    backup_mod.restore_backup(restored, bdir)

    assert [r["policy_id"] for r in immune.rollback_log(restored)] == ["skill-curator"]
    guards, _details = promotion._guard_checks(restored, "curator")
    assert guards["immune_clear"] is False


def test_backup_restore_preserves_frontier_approval(brain_home, tmp_path, monkeypatch):
    from test_promotion import _approve, _skill

    _skill(brain_home, name="curator")
    _approve(brain_home, "curator")
    bdir = backup_mod.create_backup(brain_home)
    restored = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(restored))

    backup_mod.restore_backup(restored, bdir)

    review = frontier.latest_review(restored, "skill-curator-promotion")
    assert review is not None
    assert review.get("verdict") == "approve"


# ---------------------------------------------------------------------------
# Audit F-04: a failed restore leaves no state it created
# ---------------------------------------------------------------------------


def test_failed_restore_removes_paths_created_from_absence(brain_home, tmp_path, monkeypatch):
    (brain_home / "constitution" / "snapshot-only.md").write_text(
        "only in snapshot", encoding="utf-8"
    )
    bdir = backup_mod.create_backup(brain_home)
    target = tmp_path / "target"
    target.mkdir()
    paths.ensure_layout(target)
    db.migrate(db.db_path(target))
    (target / "config" / "brain.toml").write_text(
        "schema_version = 1\nnote = 'current'\n", encoding="utf-8"
    )
    shutil.rmtree(target / "constitution")  # the target has no constitution at all

    def boom(*args, **kwargs):
        raise RuntimeError("simulated late migration failure")

    monkeypatch.setattr(db, "migrate", boom)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))

    with pytest.raises(BackupError, match="preserved in place"):
        backup_mod.restore_backup(target, bdir, force=True)

    assert not (target / "constitution").exists()
    assert "current" in (target / "config" / "brain.toml").read_text(encoding="utf-8")
    assert list((target / "backups").glob("pre-restore-*")) == []


# ---------------------------------------------------------------------------
# Audit F-05: the database destination is contained like every other path
# ---------------------------------------------------------------------------


def test_restore_rejects_symlinked_database_directory(brain_home, tmp_path, monkeypatch):
    (brain_home / "constitution" / "marker.md").write_text("declared", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    target = tmp_path / "target"
    target.mkdir()
    paths.ensure_layout(target)
    outside = tmp_path / "outside-db"
    outside.mkdir()
    db_dir = target / "db"
    db_dir.mkdir(exist_ok=True)
    db_dir.rmdir()
    try:
        os.symlink(outside, db_dir, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(BackupError, match="not contained"):
        backup_mod.restore_backup(target, bdir)

    assert list(outside.iterdir()) == []  # nothing was written through the link


# ---------------------------------------------------------------------------
# Audit follow-up: failure boundaries found by the independent verification
# ---------------------------------------------------------------------------


def test_restore_rejects_file_appearing_after_inventory_check(brain_home, tmp_path, monkeypatch):
    """A file that appears between verification and copying is refused."""
    (brain_home / "constitution" / "marker.md").write_text("declared", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    real_check = backup_mod._verify_closed_inventory

    def check_then_add(backup_dir, manifest, copied):
        real_check(backup_dir, manifest, copied)
        (backup_dir / "constitution" / "late.md").write_text("late", encoding="utf-8")

    target = tmp_path / "restored"
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))
    monkeypatch.setattr(backup_mod, "_verify_closed_inventory", check_then_add)

    with pytest.raises(BackupError, match="appeared in the backup"):
        backup_mod.restore_backup(target, bdir)

    assert not (target / "constitution" / "late.md").exists()


def test_restore_rejects_surplus_database_hash_entry(brain_home, tmp_path):
    """The manifest may not hash files outside the declared inventory."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    manifest_path = bdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["brain.sqlite"] = backup_mod.sha256_file(bdir / "brain.sqlite")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="not part of the declared inventory"):
        backup_mod.restore_backup(tmp_path / "restored", bdir)


def test_restore_rejects_symlinked_database_source(brain_home, tmp_path, monkeypatch):
    """A snapshot whose database is a symlink outside the backup is refused."""
    (brain_home / "constitution" / "marker.md").write_text("declared", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    outside = tmp_path / "outside-db"
    outside.mkdir()
    (outside / "brain.sqlite").write_bytes((bdir / "brain.sqlite").read_bytes())
    (bdir / "brain.sqlite").unlink()
    try:
        os.symlink(outside / "brain.sqlite", bdir / "brain.sqlite")
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(BackupError, match="not a safe file inside the backup"):
        backup_mod.restore_backup(tmp_path / "restored", bdir)


def test_failed_restore_keeps_preexisting_empty_parent(brain_home, tmp_path, monkeypatch):
    """An originally empty db/ directory survives a failed restore."""
    (brain_home / "constitution" / "snapshot-only.md").write_text("snapshot", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    target = tmp_path / "target"
    target.mkdir()
    paths.ensure_layout(target)
    (target / "db").mkdir(exist_ok=True)
    shutil.rmtree(target / "constitution")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(db, "migrate", boom)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))

    with pytest.raises(BackupError):
        backup_mod.restore_backup(target, bdir, force=True)

    assert (target / "db").is_dir()  # existed empty before the attempt
    assert not (target / "db" / "brain.sqlite").exists()


def test_failed_restore_removes_layout_it_created(brain_home, tmp_path, monkeypatch):
    """A failure after the layout step leaves no skeleton the attempt created."""
    (brain_home / "constitution" / "snapshot-only.md").write_text("snapshot", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    target = tmp_path / "brand-new-target"

    def boom(*args, **kwargs):
        raise RuntimeError("simulated git init failure")

    monkeypatch.setattr(backup_mod.subprocess, "run", boom)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))

    with pytest.raises(BackupError):
        backup_mod.restore_backup(target, bdir)

    assert not target.exists()


def test_failed_restore_restores_previously_empty_directory(brain_home, tmp_path, monkeypatch):
    """A directory that existed empty is empty again after a failed restore."""
    (brain_home / "constitution" / "snapshot-only.md").write_text("snapshot", encoding="utf-8")
    bdir = backup_mod.create_backup(brain_home)
    target = tmp_path / "target"
    target.mkdir()
    paths.ensure_layout(target)
    (target / "constitution").mkdir(exist_ok=True)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(db, "migrate", boom)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))

    with pytest.raises(BackupError):
        backup_mod.restore_backup(target, bdir, force=True)

    assert (target / "constitution").is_dir()
    assert list((target / "constitution").iterdir()) == []


def test_move_aside_failure_leaves_target_intact(brain_home, tmp_path, monkeypatch):
    """A failure while moving state aside must not lose the target's data."""
    _seed(brain_home, "orig")
    bdir = backup_mod.create_backup(brain_home)
    target = tmp_path / "target"
    target.mkdir()
    paths.ensure_layout(target)
    db.migrate(db.db_path(target))
    _seed(target, "current")

    real_move = shutil.move
    calls = {"n": 0}

    def flaky_move(src, dst, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated move failure")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup_mod.shutil, "move", flaky_move)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(target))

    with pytest.raises(BackupError):
        backup_mod.restore_backup(target, bdir, force=True)

    conn = db.connect(db.db_path(target))
    try:
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "current"
    finally:
        conn.close()
    assert list((target / "backups").glob("pre-restore-*")) == []
