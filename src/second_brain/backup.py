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
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, db, paths
from .errors import BackupError
from .security.paths import resolve_under

MANIFEST_FORMAT = 2
SUPPORTED_MANIFEST_FORMATS = (1, 2)
SNAPSHOT_DIRS = (
    "memory",
    "experiences",
    "decisions",
    "projects",
    "skills",
    "engrams",
    "constitution",
    "config",
)
SNAPSHOT_FILES = ("VERSION",)
# The full SQLite file set: restoring must never leave a stale -wal/-shm next
# to the restored DB (SQLite would replay frames whose salts match).
DB_FILES = ("brain.sqlite", "brain.sqlite-wal", "brain.sqlite-shm")


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_manifest(root: Path, copied: list[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for rel in copied:
        source = root / rel
        if source.is_file():
            files[rel.replace("\\", "/")] = sha256_file(source)
            continue
        for item in sorted(path for path in source.rglob("*") if path.is_file()):
            item_rel = str(item.relative_to(root)).replace("\\", "/")
            files[item_rel] = sha256_file(item)
    return files


def _git_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


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

    conn = db.connect(src_db, readonly=True)
    try:
        schema_version = db.current_version(conn)
    finally:
        conn.close()
    manifest = {
        "format": MANIFEST_FORMAT,
        "created_at": utcnow(),
        "note": note,
        "runtime": {"version": __version__, "git_sha": _git_sha(home)},
        "db": {
            "file": "brain.sqlite",
            "sha256": sha256_file(bdir / "brain.sqlite"),
            "schema_version": schema_version,
        },
        "canonical_paths": list(SNAPSHOT_DIRS),
        "excluded": {
            "derived": ["db", "state", "telemetry", "plasticity", "sleep"],
            "runtime": ["backups", "logs", "outputs"],
            "external_reference": ["brainstem", "src", "scripts", "tests", "templates"],
        },
        "copied": copied,
        "files": _file_manifest(bdir, copied),
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
    if manifest.get("format") not in SUPPORTED_MANIFEST_FORMATS:
        raise BackupError(
            f"Unsupported backup manifest format {manifest.get('format')!r} "
            f"(supported {SUPPORTED_MANIFEST_FORMATS})"
        )
    return manifest


def _validate_db_file_name(file_name: object) -> str:
    """The manifest db.file must be a plain file name (no path semantics)."""
    if not isinstance(file_name, str) or not file_name.strip():
        raise BackupError("Backup manifest db.file must be a non-empty string")
    if (
        any(ord(ch) < 32 for ch in file_name)
        or "/" in file_name
        or "\\" in file_name
        or ":" in file_name
        or file_name in (".", "..")
    ):
        raise BackupError(
            f"Backup manifest db.file is not a plain file name: {file_name!r}"
        )
    return file_name


def _verify_db_hash(backup_dir: Path, manifest: dict) -> None:
    dbinfo = manifest.get("db") or {}
    db_file_name = _validate_db_file_name(dbinfo.get("file", "brain.sqlite"))
    dbfile = backup_dir / db_file_name
    if not dbfile.exists():
        raise BackupError(f"Backup database file missing: {dbfile}")
    actual = sha256_file(dbfile)
    expected = dbinfo.get("sha256")
    if expected and actual != expected:
        raise BackupError(f"Backup DB hash mismatch: manifest {expected}, actual {actual}")


def _verify_file_hashes(backup_dir: Path, manifest: dict) -> None:
    if manifest.get("format") == 1:
        return
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BackupError("Backup manifest files must be an object")
    for rel, expected in files.items():
        if not isinstance(rel, str) or not isinstance(expected, str):
            raise BackupError("Backup manifest file hashes must be string pairs")
        try:
            source = resolve_under(backup_dir, rel, allow_missing=False)
        except ValueError as exc:
            raise BackupError(f"Backup file hash entry {rel!r} is unsafe ({exc})") from exc
        if not source.is_file():
            raise BackupError(f"Backup canonical file missing: {rel}")
        actual = sha256_file(source)
        if actual != expected:
            raise BackupError(
                f"Backup canonical file hash mismatch for {rel}: "
                f"manifest {expected}, actual {actual}"
            )


def _verify_memory_references(home: Path) -> None:
    conn = db.connect(db.db_path(home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT body_path FROM memories WHERE body_path IS NOT NULL "
            "UNION SELECT body_path FROM memory_versions WHERE body_path IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        rel = str(row["body_path"]).replace("\\", "/")
        try:
            target = resolve_under(home, rel, allow_missing=False)
        except (ValueError, FileNotFoundError) as exc:
            raise BackupError(
                f"Restored DB references missing canonical memory {rel!r}"
            ) from exc
        if not target.is_file():
            raise BackupError(f"Restored DB references missing canonical memory {rel!r}")


def _targets_exist(home: Path, copied: list[str] | None = None) -> list[str]:
    """Targets that contain real data (would actually be overwritten).

    Empty skeleton directories (e.g. a fresh layout with empty config/) are
    safe to overlay and are not reported.
    """
    present = []
    for name in DB_FILES:
        f = db.db_path(home).parent / name
        if f.exists() and f.stat().st_size > 0:
            present.append(f"db/{name}")
    for rel in copied if copied is not None else (*SNAPSHOT_DIRS, *SNAPSHOT_FILES):
        target = home / rel
        if not target.exists():
            continue
        if target.is_dir() and not any(
            item.is_file() and item.name != ".gitkeep" for item in target.rglob("*")
        ):
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


def _rollback_aside(home: Path, aside: Path, items: list[str]) -> None:
    """Move the moved-aside state back to its original locations."""
    for rel in items:
        src = aside / rel
        if src.exists():
            dst = home / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            shutil.move(str(src), str(dst))
    shutil.rmtree(aside, ignore_errors=True)


def _drop_stale_db_sidecars(home: Path) -> None:
    """Delete any -wal/-shm next to the freshly restored DB.

    Without this, SQLite would replay leftover WAL frames whose salts match
    the restored file (same lineage), silently resurrecting data that the
    restore was meant to remove.
    """
    for name in ("brain.sqlite-wal", "brain.sqlite-shm"):
        stale = db.db_path(home).parent / name
        if stale.exists():
            stale.unlink()


def _restore_plan(home: Path, backup_dir: Path, manifest: dict) -> list[tuple[str, Path, Path]]:
    """Preflight every manifest entry before ANY mutation (INV-07).

    Returns [(relative, source, destination)] where both source (inside the
    backup dir) and destination (inside the Brain home) are canonically
    proven contained, with symlinks rejected on both chains. A malformed
    manifest therefore fails before the current Brain state is touched.
    """
    copied = manifest.get("copied", [])
    if not isinstance(copied, list):
        raise BackupError("Backup manifest 'copied' must be a list")
    plan: list[tuple[str, Path, Path]] = []
    for rel in copied:
        if not isinstance(rel, str) or not rel.strip():
            raise BackupError(
                "Backup manifest entry must be a non-empty string (got "
                f"{type(rel).__name__})"
            )
        try:
            source = resolve_under(backup_dir, rel, allow_missing=False)
            destination = resolve_under(home, rel, allow_missing=True)
        except ValueError as exc:
            raise BackupError(
                f"Backup restore rejected: manifest entry {rel!r} is unsafe "
                f"({exc})."
            ) from exc
        if source.is_dir():
            # Reject symlinks anywhere inside a restored tree: a linked file
            # inside the backup could otherwise make restore READ outside the
            # backup root (and write that content into the Brain).
            try:
                for item in source.rglob("*"):
                    if item.is_symlink():
                        raise BackupError(
                            f"Backup restore rejected: symlink inside {rel}: {item.name}"
                        )
            except OSError as exc:
                raise BackupError(f"Backup entry {rel!r} cannot be scanned: {exc}") from exc
        plan.append((rel, source, destination))
    return plan


def restore_backup(home: Path, backup_dir: Path, *, force: bool = False) -> Path:
    """Restore a backup into `home`. Returns the backup dir on success.

    Refuses (without --force) when the target Brain has existing data that
    would be overwritten. With --force, existing data is moved aside first;
    if the restore then fails, the moved-aside state is rolled back so the
    target is preserved exactly as it was.

    Security (SEC-01): the manifest is untrusted. Every entry is validated
    and proven contained (source in the backup dir, destination in the Brain
    home) BEFORE any mutation; hostile entries abort the restore without
    touching the target.
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        raise BackupError(f"Backup directory not found: {backup_dir}")
    manifest = load_manifest(backup_dir)
    _verify_db_hash(backup_dir, manifest)
    _verify_file_hashes(backup_dir, manifest)

    home.mkdir(parents=True, exist_ok=True)
    # Preflight the complete restore plan before mutating anything.
    plan = _restore_plan(home, backup_dir, manifest)

    existing = _targets_exist(home, [rel for rel, _, _ in plan])
    if existing and not force:
        raise BackupError(
            "Target Brain already has data that restore would overwrite: "
            + ", ".join(existing)
            + ". Re-run with --force to move the current state aside first."
        )
    moved = None
    try:
        moved = _move_aside(home, existing) if existing else None
        src_db = backup_dir / _validate_db_file_name(
            manifest.get("db", {}).get("file", "brain.sqlite")
        )
        dst_db = db.db_path(home)
        dst_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_db, dst_db)
        _drop_stale_db_sidecars(home)
        for rel, src, destination in plan:
            if not src.exists():
                raise BackupError(f"Backup is incomplete (missing {rel})")
            if src.is_dir():
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(src, destination)
            else:
                shutil.copy2(src, destination)
        # Verify the restored copy is byte-identical to the snapshot.
        expected_hash = manifest.get("db", {}).get("sha256")
        if expected_hash and sha256_file(dst_db) != expected_hash:
            raise BackupError("Restored database failed byte-identity verification")
        # Bring restored DB to the current schema (upgrade path is idempotent).
        db.migrate(dst_db)
        _verify_memory_references(home)
        _drop_stale_db_sidecars(home)
        # The Brain root must be a Git repository (doctor requires it).
        if not (home / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=home, check=False)
    except Exception as exc:
        if moved is not None:
            _rollback_aside(home, moved, existing)
        raise BackupError(
            f"Restore failed ({exc}); the previous state was preserved in place."
        ) from exc
    return backup_dir
