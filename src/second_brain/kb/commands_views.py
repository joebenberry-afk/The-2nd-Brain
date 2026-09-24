"""`brain` view commands (brief, views, match-error, convert, import-native)."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

from . import cli, convert, projects, records, views


def _handle_brief(args: argparse.Namespace) -> int:
    """Render and print the project brief."""
    home = cli.home_from(args)
    project = projects.resolve(home, Path(args.cwd or os.getcwd()), args.project)

    # Load records
    all_records, _ = records.load_all(home)

    # Load native memory if specified
    native_text = None
    if args.native_memory:
        try:
            native_path = Path(args.native_memory)
            native_text = native_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass

    # Render brief
    budget = args.budget if args.budget else views.BRIEF_TOKEN_BUDGET
    brief = views.render_brief(all_records, project, native_text=native_text, budget=budget)

    # Print (empty → print nothing, exit 0)
    if brief:
        print(brief)
    return 0


def _handle_views(args: argparse.Namespace) -> int:
    """Compile views for all projects."""
    home = cli.home_from(args)

    # Compile views
    result = views.compile_views(home)

    # Print summary
    for key in sorted(result.keys()):
        paths = result[key]
        print(f"{key}: {len(paths)} files")

    return 0


def _handle_match_error(args: argparse.Namespace) -> int:
    """Match an error text to a correction record."""
    home = cli.home_from(args)
    project = projects.resolve(home, Path(args.cwd or os.getcwd()), args.project)

    # Get error text
    error_text = args.text or ""
    if args.stdin:
        error_text = sys.stdin.read()

    error_text = error_text.strip()
    if not error_text:
        return 1

    # Try to load correction table from compiled views
    corr_file = home / "views" / (project.id if project else "_none") / "corrections.json"
    table = []
    if corr_file.is_file():
        with contextlib.suppress(OSError, UnicodeDecodeError, json.JSONDecodeError):
            table = json.loads(corr_file.read_text(encoding="utf-8"))

    # If no compiled table, compute on the fly
    if not table:
        all_records, _ = records.load_all(home)
        table = views.correction_table(all_records)

    # Match
    match = views.match_error(table, error_text, project)
    if match:
        text = match.get("text", "")
        rec_id = match.get("id", "")
        print(f"{text} [{rec_id}]")
        return 0

    return 1


def _handle_convert(args: argparse.Namespace) -> int:
    """Convert legacy database to records."""
    if not args.from_db or not args.legacy_home:
        print("brain: convert requires --from-db and --legacy-home", file=sys.stderr)
        return 2

    db_path = args.from_db
    legacy_home = Path(args.legacy_home)
    out_home_arg = args.out or args.home or os.environ.get("SECOND_BRAIN_HOME")
    out_home = Path(out_home_arg) if out_home_arg else None

    if not out_home:
        print("brain: set --out or SECOND_BRAIN_HOME", file=sys.stderr)
        return 2

    # Run conversion
    dry_run = args.dry_run or False
    report = convert.convert(db_path, legacy_home, out_home, dry_run=dry_run)

    # Print report
    print(f"Written: {report.written}")
    print(f"Skipped: {len(report.skipped)}")
    if report.by_status:
        for status in sorted(report.by_status.keys()):
            print(f"  {status}: {report.by_status[status]}")
    if report.errors:
        print(f"Errors: {len(report.errors)}")
        for err in report.errors[:10]:
            print(f"  {err}")
        if len(report.errors) > 10:
            print(f"  ... and {len(report.errors) - 10} more")
        return 1
    return 0


def _handle_import_native(args: argparse.Namespace) -> int:
    """Import bullet points from MEMORY.md."""
    if not args.path:
        print("brain: import-native requires PATH", file=sys.stderr)
        return 2

    home = cli.home_from(args)
    project = projects.resolve(home, Path(args.cwd or os.getcwd()), args.project)

    memory_path = Path(args.path)
    dry_run = args.dry_run or False

    # Import
    new_ids = convert.import_native(
        home, memory_path, project.id if project else None, dry_run=dry_run
    )

    # Print new ids
    for rec_id in new_ids:
        print(rec_id)

    return 0


def register(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Register view commands."""

    # brief
    brief_parser = sub.add_parser("brief", parents=[common], help="Render project brief")
    brief_parser.add_argument(
        "--native-memory", default=None, help="Path to MEMORY.md for deduplication"
    )
    brief_parser.add_argument("--budget", type=int, default=None, help="Token budget")
    brief_parser.set_defaults(func=_handle_brief)

    # views
    views_parser = sub.add_parser("views", parents=[common], help="Compile all project views")
    views_parser.set_defaults(func=_handle_views)

    # match-error
    match_error_parser = sub.add_parser(
        "match-error", parents=[common], help="Match error to correction"
    )
    match_error_parser.add_argument("text", nargs="?", default=None, help="Error text")
    match_error_parser.add_argument("--stdin", action="store_true", help="Read from stdin")
    match_error_parser.set_defaults(func=_handle_match_error)

    # convert
    convert_parser = sub.add_parser(
        "convert", parents=[common], help="Convert legacy database to records"
    )
    convert_parser.add_argument("--from-db", required=True, help="Legacy database path")
    convert_parser.add_argument("--legacy-home", required=True, help="Legacy Brain home")
    convert_parser.add_argument("--out", default=None, help="Output Brain home")
    convert_parser.add_argument("--dry-run", action="store_true", help="Dry run")
    convert_parser.set_defaults(func=_handle_convert)

    # import-native
    import_native_parser = sub.add_parser(
        "import-native", parents=[common], help="Import from MEMORY.md"
    )
    import_native_parser.add_argument("path", help="Path to MEMORY.md")
    import_native_parser.add_argument("--dry-run", action="store_true", help="Dry run")
    import_native_parser.set_defaults(func=_handle_import_native)
