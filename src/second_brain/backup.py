"""Backup and restore of the Brain (plan §126-127, §1 Phase 1).

Backup layout (all under backups/, derived data - not Git-versioned):

    backups/backup-<UTC timestamp>/
        manifest.json        {format: 1, created_at, note, db: {file, sha256}, copied: [...]}
        brain.sqlite         consistent DB snapshot (sqlite3 backup API)
        config/              copy
        constitution/        copy
        projects/            copy
        VERSION              copy

Restore refuses to overwrite an existing Brain unless --force is given; with
--force the current state is moved aside (never deleted) to
backups/pre-restore-<timestamp>/ first.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from . import db, paths
from .errors import BackupError

MANIFEST_FORMAT = 1
SNAPSHOT_DIRS = ("config", "constitution", "projects")
SNAPSHOT_FILES = ("VERSION",)


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_db(src: Path, dst: Path) -> None:
    """Consistent online snapshot via sqlite3's backup API (works with WAL)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = db.connect(src)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def create_backup(home: Path, *, note: str | None = None) -> Path:
    """Create a timestamped backup. Returns the backup directory."""
    stamps = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    bdir = paths.backups_dir(home) / f"backup-{stamps}"
    if bdir.exists():
        raise BackupError(f"Backup directory already exists: {bdir}")
    bdir.mkdir(parents=True)

    src_db = db.db_path(home)
    if not src_db.exists():
        raise BackupError(f"Database not found at {src_db}; run `brainctl init` first")
    _snapshot_db(src_db, bdir / "brain.sqlite")

    copied: list[str] = []
    for rel in SNAPSHOT_DIRS:
        src = home / rel
        if src.exists():
            shutil.copytree(src, bdir / rel)
            copied.append(rel)
    for rel in SNAPSHOT_FILES:
        src = home / rel
        if src.exists():
            shutil.copy2(src, bdir / rel)
            copied.append(rel)

    manifest = {
        "format": MANIFEST_FORMAT,
        "created_at": utcnow(),
        "note": note,
        "db": {"file": "brain.sqlite", "sha256": sha256_file(bdir / "brain.sqlite")},
        "copied": copied,
    }
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return bdir


def list_backups(home: Path) -> list[Path]:
    bdir = paths.backups_dir(home)
    if not bdir.exists():
        return []
    return sorted(
        (p for p in bdir.iterdir() if p.is_dir() and p.name.startswith("backup-")),
        reverse=True,
    )


def load_manifest(backup_dir: Path) -> dict:
    mf = backup_dir / "manifest.json"
    if not mf.exists():
        raise BackupError(f"Not a Brain backup (missing manifest.json): {backup_dir}")
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupError(f"Corrupt backup manifest {mf}: {exc}") from exc
    if manifest.get("format") != MANIFEST_FORMAT:
        raise BackupError(
            f"Unsupported backup manifest format {manifest.get('format')!r} "
            f"(expected {MANIFEST_FORMAT})"
        )
    return manifest


def _verify_db_hash(backup_dir: Path, manifest: dict) -> None:
    dbinfo = manifest.get("db") or {}
    dbfile = backup_dir / dbinfo.get("file", "brain.sqlite")
    if not dbfile.exists():
        raise BackupError(f"Backup database file missing: {dbfile}")
    actual = sha256_file(dbfile)
    expected = dbinfo.get("sha256")
    if expected and actual != expected:
        raise BackupError(f"Backup DB hash mismatch: manifest {expected}, actual {actual}")


def _targets_exist(home: Path) -> list[str]:
    """Targets that contain real data (would actually be overwritten).

    Empty skeleton directories (e.g. a fresh layout with empty config/) are
    safe to overlay and are not reported.
    """
    present = []
    dbf = db.db_path(home)
    if dbf.exists() and dbf.stat().st_size > 0:
        present.append("db/brain.sqlite")
    for rel in (*SNAPSHOT_DIRS, *SNAPSHOT_FILES):
        target = home / rel
        if not target.exists():
            continue
        if target.is_dir() and not any(target.iterdir()):
            continue
        present.append(rel)
    return present


def _move_aside(home: Path, items: list[str]) -> Path:
    stamps = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    aside = paths.backups_dir(home) / f"pre-restore-{stamps}"
    aside.mkdir(parents=True)
    for rel in items:
        src = home / rel
        if src.exists():
            dst = aside / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
    return aside


def restore_backup(home: Path, backup_dir: Path, *, force: bool = False) -> Path:
    """Restore a backup into `home`. Returns the backup dir on success.

    Refuses (without --force) when the target Brain has existing data that
    would be overwritten. With --force, existing data is moved aside first.
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        raise BackupError(f"Backup directory not found: {backup_dir}")
    manifest = load_manifest(backup_dir)
    _verify_db_hash(backup_dir, manifest)

    home.mkdir(parents=True, exist_ok=True)
    existing = _targets_exist(home)
    if existing and not force:
        raise BackupError(
            "Target Brain already has data that restore would overwrite: "
            + ", ".join(existing)
            + ". Re-run with --force to move the current state aside first."
        )
    moved = _move_aside(home, existing) if existing else None

    try:
        src_db = backup_dir / manifest.get("db", {}).get("file", "brain.sqlite")
        dst_db = db.db_path(home)
        dst_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_db, dst_db)
        for rel in manifest.get("copied", []):
            src = backup_dir / rel
            if not src.exists():
                raise BackupError(f"Backup is incomplete (missing {rel})")
            if src.is_dir():
                if (home / rel).exists():
                    shutil.rmtree(home / rel)
                shutil.copytree(src, home / rel)
            else:
                shutil.copy2(src, home / rel)
        # Verify the restored copy is byte-identical to the snapshot.
        expected_hash = manifest.get("db", {}).get("sha256")
        if expected_hash and sha256_file(dst_db) != expected_hash:
            raise BackupError("Restored database failed byte-identity verification")
        # Bring restored DB to the current schema (upgrade path is idempotent).
        db.migrate(dst_db)
    except Exception as exc:
        raise BackupError(
            f"Restore failed ({exc}); current state was moved aside to {moved}."
        ) from exc
    return backup_dir
