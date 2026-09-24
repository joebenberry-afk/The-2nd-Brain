"""``brain`` skills commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cli, skills_export
from .records import RecordError


def handle_export_skill(args: argparse.Namespace) -> int:
    """Export a procedure record as a SKILL.md file."""
    home = cli.home_from(args)
    record_id = args.id
    out_dir = Path(args.dir)
    force = args.force or False

    try:
        skill_path = skills_export.export_skill(home, record_id, out_dir, force=force)
        print(str(skill_path))
        return 0
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def register(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Register skills commands."""

    # export-skill
    export_parser = sub.add_parser(
        "export-skill",
        parents=[common],
        help="Export a procedure as a SKILL.md file",
    )
    export_parser.add_argument("id", help="Record id to export")
    export_parser.add_argument("--dir", required=True, help="Output directory")
    export_parser.add_argument("--force", action="store_true", help="Overwrite existing SKILL.md")
    export_parser.set_defaults(func=handle_export_skill)
