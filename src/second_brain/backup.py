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
# Canonical knowledge (Git-versioned human-readable state).
CANONICAL_DIRS = (
    "memory",
    "experiences",
    "decisions",
    "projects",
    "skills",
    "engrams",
    "constitution",
    "config",
)
# Governance records the runtime treats as authoritative: promotion/version
# history, immune rollback history and frontier approvals decide whether a
# skill may act. They are not disposable by pathname even though they live
# under `state/` or beside canonical roots, so a backup that omits them
# silently weakens guard authority after a restore (audit F-03).
GOVERNANCE_DIRS = (
    "state/promotions",
    "immune",
    "frontier",
)
SNAPSHOT_DIRS = CANONICAL_DIRS + GOVERNANCE_DIRS
SNAPSHOT_FILES = ("VERSION",)
PERMITTED_ROOTS = frozenset((*SNAPSHOT_DIRS, *SNAPSHOT_FILES))
# The full SQLite file set: restoring must never leave a stale -wal/-shm next
# to the restored DB (SQLite would replay frames whose salts match).
DB_FILES = ("brain.sqlite", "brain.sqlite-wal", "brain.sqlite-shm")
DB_RELATIVE = "db/brain.sqlite"
DB_SIDECARS = ("db/brain.sqlite-wal", "db/brain.sqlite-shm")


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
    _verify_memory_references(home)
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
    try:
        _verify_memory_references(bdir, database_file=bdir / "brain.sqlite")
    except BackupError:
        shutil.rmtree(bdir)
        raise

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
            # `state/promotions` is governance authority (see GOVERNANCE_DIRS)
            # and is deliberately NOT in this list; the rest of state/, plus
            # db/telemetry/plasticity/sleep, is rebuildable runtime data.
            "derived": [
                "db",
                "state (except state/promotions)",
                "telemetry",
                "plasticity",
                "sleep",
            ],
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
        raise BackupError(f"Backup manifest db.file is not a plain file name: {file_name!r}")
    return file_name


def _db_source_path(backup_dir: Path, manifest: dict) -> Path:
    """The snapshot database inside the backup, proven safe to read.

    The source chain is validated exactly like a destination: a database file
    that is a symlink (or reached through one, or outside the backup root) is
    refused instead of being restored (audit F-05, source half).
    """
    name = _validate_db_file_name((manifest.get("db") or {}).get("file", "brain.sqlite"))
    try:
        return resolve_under(backup_dir, name, allow_missing=False)
    except ValueError as exc:
        raise BackupError(
            f"Backup restore rejected: database source {name!r} is not a safe file inside the "
            f"backup ({exc})."
        ) from exc


def _verify_db_hash(backup_dir: Path, manifest: dict) -> None:
    dbinfo = manifest.get("db") or {}
    dbfile = _db_source_path(backup_dir, manifest)
    if not dbfile.is_file():
        raise BackupError(f"Backup database file missing: {dbfile}")
    actual = sha256_file(dbfile)
    expected = dbinfo.get("sha256")
    if manifest.get("format", 1) >= 2 and (not isinstance(expected, str) or not expected.strip()):
        raise BackupError(
            "Backup manifest is missing the database sha256 (required for format 2): "
            "restore cannot prove the database it would install."
        )
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


def _inventory_under(root: Path, rel: str) -> set[str]:
    """Regular-file inventory below one backup entry, as POSIX-style rel paths."""
    target = root / rel
    if target.is_file():
        return {rel}
    found: set[str] = set()
    for item in target.rglob("*"):
        if item.is_symlink():
            raise BackupError(f"Backup restore rejected: symlink inside {rel}: {item.name}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise BackupError(
                f"Backup restore rejected: unsupported file type at {rel}/{item.name}"
            )
        found.add(item.relative_to(root).as_posix())
    return found


def _verify_permitted_roots(copied: list[str]) -> None:
    """Every declared entry must be a canonical Brain root, exactly once."""
    seen: set[str] = set()
    for rel in copied:
        if rel not in PERMITTED_ROOTS:
            raise BackupError(
                f"Backup restore rejected: {rel!r} is not a canonical Brain root "
                "and would not be installed."
            )
        if rel in seen:
            raise BackupError(f"Backup restore rejected: duplicate entry {rel!r}")
        seen.add(rel)


def _verify_closed_inventory(backup_dir: Path, manifest: dict, copied: list[str]) -> None:
    """The backup must contain exactly the declared inventory, nothing else.

    Format 2: the on-disk inventory and the manifest hash inventory must be
    equal in both directions. Format 1 (legacy, no per-file hashes): the
    on-disk inventory must still equal the declared `copied` closure, so an
    unlisted addition is refused even without hashes.
    """
    db_file_name = _validate_db_file_name((manifest.get("db") or {}).get("file", "brain.sqlite"))
    known_extras = {"manifest.json", db_file_name, f"{db_file_name}-wal", f"{db_file_name}-shm"}

    declared: set[str] = set()
    for rel in copied:
        declared |= _inventory_under(backup_dir, rel)

    actual: set[str] = set()
    for item in backup_dir.rglob("*"):
        if item.is_symlink() or item.is_dir():
            continue
        rel = item.relative_to(backup_dir).as_posix()
        if rel in known_extras:
            continue
        if not item.is_file():
            raise BackupError(f"Backup restore rejected: unsupported file type: {rel}")
        actual.add(rel)

    unlisted = sorted(actual - declared)
    if unlisted:
        preview = ", ".join(unlisted[:5]) + ("..." if len(unlisted) > 5 else "")
        raise BackupError(
            "Backup restore rejected: backup contains files outside the declared inventory "
            f"({len(unlisted)}): {preview}"
        )

    if manifest.get("format", 1) < 2:
        return

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BackupError("Backup manifest files must be an object")
    declared_hashes = {str(key).replace("\\", "/") for key in files}
    surplus = sorted(declared_hashes & known_extras)
    if surplus:
        raise BackupError(
            "Backup restore rejected: manifest hashes files that are not part of the declared "
            "inventory: " + ", ".join(surplus)
        )
    unhashed = sorted(declared - declared_hashes)
    if unhashed:
        preview = ", ".join(unhashed[:5]) + ("..." if len(unhashed) > 5 else "")
        raise BackupError(
            "Backup restore rejected: declared inventory is not covered by the manifest hash "
            f"inventory ({len(unhashed)}): {preview}"
        )


def _verify_memory_references(home: Path, *, database_file: Path | None = None) -> None:
    """Verify current and historical canonical files without mutating the database."""
    try:
        conn = db.connect(database_file or db.db_path(home), readonly=True)
    except sqlite3.Error as exc:
        raise BackupError(f"Cannot inspect canonical memory references: {exc}") from exc
    try:
        required = {"memories", "memory_versions"}
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('memories', 'memory_versions')"
            )
        }
        if not present and db.current_version(conn) < 3:
            return  # Supported backups predating semantic memory have no such references.
        if present != required:
            raise BackupError("Canonical memory reference tables are missing")
        rows = conn.execute(
            "SELECT body_path FROM memories WHERE body_path IS NOT NULL "
            "UNION SELECT body_path FROM memory_versions WHERE body_path IS NOT NULL"
        ).fetchall()
    except sqlite3.Error as exc:
        raise BackupError(f"Cannot inspect canonical memory references: {exc}") from exc
    finally:
        conn.close()
    for row in rows:
        rel = str(row["body_path"]).replace("\\", "/")
        try:
            target = resolve_under(home, rel, allow_missing=False)
            if not target.is_file():
                raise FileNotFoundError(rel)
        except (ValueError, OSError) as exc:
            raise BackupError(f"Canonical memory file is missing or unsafe: {rel!r}") from exc


def _safe_destination(home: Path, rel: str) -> Path:
    """A restore destination inside the Brain home, proven contained.

    Uses the same containment boundary as manifest entries: absolute/drive/
    UNC/traversal values and any symlink (or Windows junction) on the chain
    are refused, so a linked `db/` cannot redirect writes outside the target
    (audit F-05).
    """
    try:
        return resolve_under(home, rel, allow_missing=True)
    except ValueError as exc:
        raise BackupError(
            f"Backup restore rejected: destination {rel!r} is not contained in the "
            f"Brain home ({exc})."
        ) from exc


def _db_destination_paths(home: Path) -> dict[str, Path]:
    """The database file and its sidecars, each proven contained before mutation."""
    return {rel: _safe_destination(home, rel) for rel in (DB_RELATIVE, *DB_SIDECARS)}


def _restore_destination_state(
    home: Path, plan: list[tuple[str, Path, Path]], db_paths: dict[str, Path]
) -> tuple[dict[str, str], dict[str, bool], set[Path]]:
    """What each destination looked like before the attempt.

    Returns (per-entry state, database presence, directories that already
    existed). ``absent`` entries are removed on rollback, ``empty_dir`` entries
    are restored to an empty directory, ``present`` entries are moved aside and
    put back. The directory set is what makes parent pruning exact: only
    directories the attempt itself created may be pruned.
    """
    state: dict[str, str] = {}
    for rel, _src, dest in plan:
        if dest.exists() and dest.is_dir() and not any(dest.iterdir()):
            state[rel] = "empty_dir"
        elif dest.exists() or dest.is_symlink():
            state[rel] = "present"
        else:
            state[rel] = "absent"
    db_state = {rel: path.exists() for rel, path in db_paths.items()}
    protected: set[Path] = set()
    for _rel, _src, dest in plan:
        current = dest.parent
        while current != home and home in current.parents:
            if current.exists():
                protected.add(current)
            current = current.parent
    for path in db_paths.values():
        current = path.parent
        while current != home and home in current.parents:
            if current.exists():
                protected.add(current)
            current = current.parent
    return state, db_state, protected


def _prune_empty_parents(home: Path, start: Path, protected: set[Path]) -> None:
    """Remove directories the failed restore created, up to the Brain home.

    Only directories that did not exist before the attempt are removed, so an
    originally empty parent (for example ``db/``) survives a failed restore.
    """
    current = start
    while current != home and current not in protected:
        if not current.is_dir() or any(current.iterdir()):
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _remove_created_paths(
    home: Path,
    state: dict[str, str],
    db_paths: dict[str, Path],
    db_state: dict[str, bool],
    protected: set[Path],
) -> None:
    """Undo exactly what a failed restore created or overwrote from nothing."""
    for rel, before in state.items():
        target = home / rel
        if before == "present":
            continue  # the moved-aside rollback puts it back
        if before == "empty_dir":
            if target.exists() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists() or target.is_symlink():
            target.unlink()
        _prune_empty_parents(home, target.parent, protected)
    for rel, path in db_paths.items():
        if db_state.get(rel):
            continue  # existed before; the moved-aside rollback restored it
        if path.exists() or path.is_symlink():
            path.unlink()
        _prune_empty_parents(home, path.parent, protected)


def _remove_created_layout(home: Path, protected: set[Path], layout_before: set[str]) -> None:
    """Remove the layout directories this attempt created, deepest first.

    ``MAJOR_DIRS`` entries are nested, so their top-level parents are created
    implicitly by ``mkdir(parents=True)``; pruning walks back up to the Brain
    home and stops at any directory that existed before the attempt.
    """
    created = [rel for rel in paths.MAJOR_DIRS if rel not in layout_before]
    for rel in sorted(created, key=lambda item: item.count("/"), reverse=True):
        _prune_empty_parents(home, home / rel, protected)


def _residual_state(
    home: Path,
    state: dict[str, str],
    db_paths: dict[str, Path],
    db_state: dict[str, bool],
) -> list[str]:
    """Paths a failed restore created and could not remove."""
    if not home.exists():
        return []
    residue = [rel for rel, before in state.items() if before == "absent" and (home / rel).exists()]
    for rel, path in db_paths.items():
        if not db_state.get(rel) and path.exists():
            residue.append(rel)
    return residue


def _targets_exist(
    home: Path, copied: list[str] | None = None, db_paths: dict[str, Path] | None = None
) -> list[str]:
    """Targets that contain real data (would actually be overwritten).

    Empty skeleton directories (e.g. a fresh layout with empty config/) are
    safe to overlay and are not reported.
    """
    present = []
    for name in DB_FILES:
        f = (db_paths.get(f"db/{name}") if db_paths else None) or (db.db_path(home).parent / name)
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
    """Move existing state into a pre-restore directory, or put it all back.

    A failure part-way through must not leave the target missing data, so the
    items already moved are restored before the error is raised.
    """
    stamps = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    aside = paths.backups_dir(home) / f"pre-restore-{stamps}"
    aside.mkdir(parents=True)
    moved: list[str] = []
    for rel in items:
        src = home / rel
        if not src.exists():
            continue
        dst = aside / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(dst))
        except OSError as exc:
            _rollback_aside(home, aside, moved)
            if moved and not all((home / rel).exists() for rel in moved):
                raise BackupError(
                    f"Could not move {rel} aside ({exc}) and the partial move could not be "
                    f"undone; the moved state is preserved under {aside}."
                ) from exc
            raise
        moved.append(rel)
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


def _drop_stale_db_sidecars(db_paths: dict[str, Path]) -> None:
    """Delete any -wal/-shm next to the freshly restored DB.

    Without this, SQLite would replay leftover WAL frames whose salts match
    the restored file (same lineage), silently resurrecting data that the
    restore was meant to remove.
    """
    for rel in DB_SIDECARS:
        stale = db_paths.get(rel)
        if stale is not None and stale.exists():
            stale.unlink()


def _install_verified_file(destination: Path, source: Path, rel: str, expected: str | None) -> None:
    """Copy one declared file and prove the installed bytes match the manifest."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if expected is not None and sha256_file(destination) != expected:
        raise BackupError(
            f"Restored file {rel} does not match the manifest hash "
            "(the backup changed while it was being restored)."
        )


def _install_tree(
    backup_dir: Path, destination: Path, source: Path, rel: str, manifest: dict
) -> None:
    """Install exactly the declared files below one root, verifying each copy.

    The inventory was verified before any mutation; this walks the source tree
    again as it copies, so a file that appears in the backup between those two
    moments is refused instead of being installed unverified, and every
    installed file is proved byte-identical to its declared hash.
    """
    files = manifest.get("files")
    if destination.exists():
        shutil.rmtree(destination)
    if not isinstance(files, dict):
        # Legacy format 1 has no hash inventory: root closure only (documented).
        shutil.copytree(source, destination)
        return
    destination.mkdir(parents=True, exist_ok=True)
    prefix = rel.rstrip("/") + "/"
    installed = 0
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise BackupError(f"Backup restore rejected: symlink inside {rel}: {item.name}")
        if item.is_dir():
            (destination / item.relative_to(source)).mkdir(parents=True, exist_ok=True)
            continue
        rel_key = item.relative_to(backup_dir).as_posix()
        expected = files.get(rel_key)
        if expected is None:
            raise BackupError(
                f"Backup restore rejected: {rel_key} appeared in the backup after it was "
                "verified (the backup changed during the restore)."
            )
        _install_verified_file(destination / item.relative_to(source), item, rel_key, expected)
        installed += 1
    declared = sum(1 for key in files if key.startswith(prefix))
    if installed != declared:
        raise BackupError(
            f"Backup restore rejected: {rel} installed {installed} files but the manifest "
            f"declares {declared}."
        )


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
                f"Backup manifest entry must be a non-empty string (got {type(rel).__name__})"
            )
        try:
            source = resolve_under(backup_dir, rel, allow_missing=False)
            destination = resolve_under(home, rel, allow_missing=True)
        except ValueError as exc:
            raise BackupError(
                f"Backup restore rejected: manifest entry {rel!r} is unsafe ({exc})."
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
    src_db = _db_source_path(backup_dir, manifest)
    _verify_file_hashes(backup_dir, manifest)
    if manifest["format"] >= 2:
        _verify_memory_references(backup_dir, database_file=src_db)

    # Preflight the complete restore plan before mutating anything.
    plan = _restore_plan(home, backup_dir, manifest)
    copied = [rel for rel, _, _ in plan]
    _verify_permitted_roots(copied)
    _verify_closed_inventory(backup_dir, manifest, copied)
    db_paths = _db_destination_paths(home)

    home_existed = home.exists()
    home.mkdir(parents=True, exist_ok=True)
    state, db_state, protected = _restore_destination_state(home, plan, db_paths)
    existing = _targets_exist(home, copied, db_paths)
    if existing and not force:
        raise BackupError(
            "Target Brain already has data that restore would overwrite: "
            + ", ".join(existing)
            + ". Re-run with --force to move the current state aside first."
        )
    layout_before = {rel for rel in paths.MAJOR_DIRS if (home / rel).exists()}
    git_before = (home / ".git").exists()
    moved = None
    try:
        moved = _move_aside(home, existing) if existing else None
        dst_db = db_paths[DB_RELATIVE]
        dst_db.parent.mkdir(parents=True, exist_ok=True)
        _install_verified_file(dst_db, src_db, DB_RELATIVE, manifest.get("db", {}).get("sha256"))
        _drop_stale_db_sidecars(db_paths)
        for rel, src, destination in plan:
            if not src.exists():
                raise BackupError(f"Backup is incomplete (missing {rel})")
            if src.is_dir():
                _install_tree(backup_dir, destination, src, rel, manifest)
            else:
                _install_verified_file(
                    destination, src, rel, (manifest.get("files") or {}).get(rel)
                )
        # Verify the restored copy is byte-identical to the snapshot.
        expected_hash = manifest.get("db", {}).get("sha256")
        if expected_hash and sha256_file(dst_db) != expected_hash:
            raise BackupError("Restored database failed byte-identity verification")
        # Bring restored DB to the current schema (upgrade path is idempotent).
        db.migrate(dst_db)
        _verify_memory_references(home)
        _drop_stale_db_sidecars(db_paths)
        paths.ensure_layout(home)
        # The Brain root must be a Git repository (doctor requires it).
        if not git_before:
            subprocess.run(["git", "init", "-q"], cwd=home, check=False)
    except Exception as exc:
        if moved is not None:
            _rollback_aside(home, moved, existing)
        _remove_created_paths(home, state, db_paths, db_state, protected)
        # Remove the layout this attempt created (and the Git repo, if it created one).
        _remove_created_layout(home, protected, layout_before)
        if not git_before and (home / ".git").is_dir():
            shutil.rmtree(home / ".git", ignore_errors=True)
        if not home_existed and home.is_dir() and not any(home.iterdir()):
            home.rmdir()
        residue = _residual_state(home, state, db_paths, db_state)
        if residue:
            preview = ", ".join(residue[:5]) + ("..." if len(residue) > 5 else "")
            raise BackupError(
                f"Restore failed ({exc}); rollback could not restore the target exactly. "
                f"Residual paths created by the attempt: {preview}. "
                "Inspect the target before using it."
            ) from exc
        raise BackupError(
            f"Restore failed ({exc}); the previous state was preserved in place."
        ) from exc
    return backup_dir
