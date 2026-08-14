"""brainctl — Python control CLI (plan §82).

Implemented in Phase 1: init, doctor, status, project add|list|status,
backup, restore. Later phases add capture/recall/sleep/skills/... commands.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import __version__, db, paths, registry
from . import backup as backup_mod
from . import doctor as doctor_mod
from .errors import BrainError


def _parser() -> argparse.ArgumentParser:
    # --home is accepted both before and after the subcommand. SUPPRESS keeps
    # the subparser default from clobbering a value given at the root level.
    home_parent = argparse.ArgumentParser(add_help=False)
    home_parent.add_argument(
        "--home",
        type=Path,
        default=argparse.SUPPRESS,
        help="Brain root (default: $SECOND_BRAIN_HOME)",
    )
    p = argparse.ArgumentParser(
        prog="brainctl", description="The Second Brain control CLI", parents=[home_parent]
    )
    p.add_argument("--version", action="version", version=f"brainctl {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[home_parent], help="initialize a Brain at the root")
    init.add_argument(
        "--force", action="store_true", help="initialize even if the directory is non-empty"
    )
    sub.add_parser("doctor", parents=[home_parent], help="run health checks")
    sub.add_parser("status", parents=[home_parent], help="show Brain status summary")

    pa = sub.add_parser("project", parents=[home_parent], help="project registry")
    ps = pa.add_subparsers(dest="project_command", required=True)
    padd = ps.add_parser(
        "add",
        parents=[home_parent],
        help="attach a repository (registry + manifest + marker)",
    )
    padd.add_argument("repo", type=Path)
    padd.add_argument("--name", default=None)
    padd.add_argument("--id", dest="project_id", default=None)
    padd.add_argument("--no-marker", action="store_true", help="skip the AGENTS.md marker block")
    padd.add_argument("--no-manifest", action="store_true", help="skip .brain/project.toml")
    plist = ps.add_parser("list", parents=[home_parent], help="list registered projects")
    plist.add_argument("--inactive", action="store_true")
    pstat = ps.add_parser("status", parents=[home_parent], help="status of one registered project")
    pstat.add_argument("key")
    pdet = ps.add_parser(
        "detach",
        parents=[home_parent],
        help="remove repo-side integration (marker/manifest) and deactivate",
    )
    pdet.add_argument("key")
    prem = ps.add_parser(
        "remove",
        parents=[home_parent],
        help="delete a registry row (keep brain dir unless --purge)",
    )
    prem.add_argument("key")
    prem.add_argument("--purge", action="store_true", help="also delete projects/<id>/")

    b = sub.add_parser("backup", parents=[home_parent], help="create a Brain backup")
    b.add_argument("--note", default=None)
    r = sub.add_parser("restore", parents=[home_parent], help="restore a Brain backup")
    r.add_argument("backup_dir", type=Path)
    r.add_argument("--force", action="store_true")

    tel = sub.add_parser("telemetry", parents=[home_parent], help="agent telemetry (Phase 2)")
    ts = tel.add_subparsers(dest="telemetry_command", required=True)
    trep = ts.add_parser("report", help="aggregate telemetry records")
    trep.add_argument("--since", default=None, help="only records with ts >= value")
    trep.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    ts.add_parser("validate", help="validate telemetry records")

    return p


def _home(args) -> Path:
    return args.home.resolve() if getattr(args, "home", None) else paths.resolve_home()


def _seed_defaults(home: Path) -> int:
    """Copy missing canonical seed files (VERSION, config, templates) from the package."""
    import shutil

    defaults = Path(__file__).resolve().parent / "defaults"
    if not defaults.is_dir():
        return 0
    seeded = 0
    for src in sorted(defaults.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(defaults)
        dst = home / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        seeded += 1
    return seeded


def cmd_init(args) -> int:
    home = _home(args)
    marker = (home / "VERSION").exists() or (home / "config" / "brain.toml").exists()
    if home.exists():
        content = [p for p in home.iterdir() if p.name != ".git"]
        if content and not marker and not args.force:
            print(
                f"Refusing: {home} exists, is non-empty, and is not a Brain. "
                "Re-run with --force only if you are certain this directory is meant "
                "to become a Brain.",
                file=sys.stderr,
            )
            return 2
    home.mkdir(parents=True, exist_ok=True)
    paths.ensure_layout(home)
    seeded = _seed_defaults(home)

    if not (home / ".git").exists():
        r = subprocess.run(["git", "init"], cwd=home, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"git init failed: {r.stderr.strip()}", file=sys.stderr)
            return 1

    applied = db.migrate(db.db_path(home))
    print(f"Brain initialized at {home}" + (f" (seeded {seeded} default files)" if seeded else ""))
    print(
        f"Database ready: {db.db_path(home)}"
        + (f" (applied migrations {applied})" if applied else " (already current)")
    )
    print("Next steps: `brainctl doctor`, `brainctl project add <repo>`, `brainctl status`")
    return 0


def cmd_doctor(args) -> int:
    result = doctor_mod.run_doctor(_home(args))
    print(doctor_mod.format_result(result))
    return 1 if result.failed else 0


def cmd_status(args) -> int:
    home = _home(args)
    print(f"Brain home:  {home}")
    vf = home / "VERSION"
    print(f"Version:     {vf.read_text(encoding='utf-8').strip() if vf.exists() else 'unknown'}")
    try:
        conn = db.connect(db.db_path(home))
        try:
            v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
            n_projects = conn.execute("SELECT COUNT(*) FROM projects WHERE active = 1").fetchone()[
                0
            ]
            print(f"DB:          {db.db_path(home)} (schema v{v}, {n_projects} active projects)")
        finally:
            conn.close()
    except Exception as exc:  # sqlite3.Error etc.
        print(f"DB:          unavailable ({exc})")
    backups = backup_mod.list_backups(home)
    print(f"Backups:     {len(backups)}" + (f", latest {backups[0].name}" if backups else ""))
    return 0


def cmd_project(args) -> int:
    home = _home(args)
    if args.project_command == "add":
        proj, created, changes = registry.attach_project(
            home,
            args.repo,
            name=args.name,
            project_id=args.project_id,
            with_marker=not args.no_marker,
            with_manifest=not args.no_manifest,
        )
        verb = "Attached" if created else "Already attached (refreshed)"
        print(f"{verb} project {proj.name!r} (id {proj.id})")
        print(f"Brain project dir: {proj.brain_project_path}")
        if changes.get("manifest_created"):
            print(f"Wrote manifest: {Path(args.repo) / '.brain' / 'project.toml'}")
        if changes.get("marker_added"):
            print(f"Added AGENTS.md marker: {Path(args.repo) / 'AGENTS.md'}")
        return 0
    if args.project_command == "list":
        projects = registry.list_projects(home, include_inactive=args.inactive)
        if not projects:
            print("No registered projects.")
            return 0
        for p in projects:
            print(f"{p.id}  {p.name}  {p.repo_path or '-'}")
        return 0
    if args.project_command == "status":
        st = registry.project_status(home, args.key)
        for k, v in st.items():
            print(f"{k:16s} {v}")
        return 0
    if args.project_command == "remove":
        out = registry.remove_project(home, args.key, purge=args.purge)
        print(f"Removed project {out['name']!r} (id {out['id']}); purged={out['purged']}")
        return 0
    if args.project_command == "detach":
        changes = registry.detach_project(home, args.key)
        print(f"Detached {changes['name']!r} (id {changes['id']})")
        for k in ("marker_removed", "agents_file_deleted", "manifest_removed", "deactivated"):
            if k in changes:
                print(f"{k:20s} {changes[k]}")
        return 0
    return 2


def cmd_telemetry(args) -> int:
    import json

    from . import telemetry

    home = _home(args)
    if args.telemetry_command == "report":
        rep = telemetry.report(home, since=args.since)
        if args.as_json:
            print(json.dumps(rep, indent=2, default=str))
        else:
            print(telemetry.format_report(rep))
        return 0
    if args.telemetry_command == "validate":
        result = telemetry.validate(home)
        print(
            f"{result['files']} files, {result['records']} records, {len(result['issues'])} issues"
        )
        for issue in result["issues"]:
            print(f"  {issue}")
        return 1 if result["issues"] else 0
    return 2


def cmd_backup(args) -> int:
    home = _home(args)
    bdir = backup_mod.create_backup(home, note=args.note)
    print(f"Backup created: {bdir}")
    return 0


def cmd_restore(args) -> int:
    home = _home(args)
    backup_mod.restore_backup(home, args.backup_dir, force=args.force)
    print(f"Restored from {args.backup_dir} into {home}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {
        "init": cmd_init,
        "doctor": cmd_doctor,
        "status": cmd_status,
        "project": cmd_project,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "telemetry": cmd_telemetry,
    }
    try:
        return handlers[args.command](args)
    except BrainError as exc:
        print(f"brainctl: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
