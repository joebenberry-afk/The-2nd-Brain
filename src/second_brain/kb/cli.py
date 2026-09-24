"""``brain`` — the V3 agent-facing command line (lean: stdlib + ``second_brain.kb`` only).

Subcommands are registered by the command modules; each exposes
``register(subparsers) -> None`` and sets ``func`` on its parsers. Every handler receives the
parsed namespace and returns an exit code: 0 success, 1 nothing found / refused, 2 usage or
contract error.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import commands_index, commands_views


def home_from(args: argparse.Namespace) -> Path:
    raw = args.home or os.environ.get("SECOND_BRAIN_HOME")
    if not raw:
        raise SystemExit("brain: set SECOND_BRAIN_HOME or pass --home")
    return Path(raw)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", default=None, help="Brain home (default: $SECOND_BRAIN_HOME)")
    common.add_argument("--project", default=None, help="project id (default: resolved from --cwd)")
    common.add_argument("--cwd", default=None, help="working directory for project resolution")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    parser = argparse.ArgumentParser(prog="brain", description="Second Brain V3 agent command line")
    sub = parser.add_subparsers(dest="command", required=True)
    commands_index.register(sub, common)
    commands_views.register(sub, common)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
