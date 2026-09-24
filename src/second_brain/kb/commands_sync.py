"""`brain` sync commands (share, sync)."""

from __future__ import annotations

import argparse
import sys

from . import sync
from .records import RecordError


def handle_share(args: argparse.Namespace) -> int:
    """Share a record with domains."""
    from .cli import home_from

    home = home_from(args)
    record_id = args.id
    domains = tuple(args.domain)
    reason = args.reason

    try:
        result = sync.share(home, record_id, domains=domains, reason=reason)
        print(f"{record_id} shared with {','.join(result.domains)}")
        return 0
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def handle_sync(args: argparse.Namespace) -> int:
    """Sync records with git."""
    from .cli import home_from

    home = home_from(args)
    message = args.message
    push = not args.no_push

    try:
        report = sync.sync(home, message=message, push=push)

        # Print main status
        pulled_str = "yes" if report.pulled else "no"
        pushed_str = "yes" if report.pushed else "no"
        print(f"committed {report.committed}; pulled {pulled_str}; pushed {pushed_str}")

        # Print notes
        for note in report.notes:
            print(note)

        # Print conflict if any
        if report.conflict:
            print(f"conflict: {report.conflict}")
            return 1

        return 0
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def register(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Register all sync commands."""

    # share command
    share_parser = sub.add_parser("share", parents=[common], help="Share a record with domains")
    share_parser.add_argument("id", help="Record id")
    share_parser.add_argument(
        "--domain", action="append", default=[], help="Domain tag (can be repeated)"
    )
    share_parser.add_argument("--reason", required=True, help="Reason for sharing")
    share_parser.set_defaults(func=handle_share)

    # sync command
    sync_parser = sub.add_parser("sync", parents=[common], help="Sync records with git")
    sync_parser.add_argument("--message", default=None, help="Commit message")
    sync_parser.add_argument("--no-push", action="store_true", help="Skip push after pull")
    sync_parser.set_defaults(func=handle_sync)
