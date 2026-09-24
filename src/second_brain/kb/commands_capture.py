"""`brain` capture commands (capture, review, accept, reject)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import capture, cli
from .records import RecordError


def handle_capture(args: argparse.Namespace) -> int:
    """Capture tool events and git trailers into proposals."""
    home = cli.home_from(args)
    dry_run = args.dry_run or False

    try:
        # Capture events
        report = capture.capture_events(home, dry_run=dry_run)

        # Capture git for each --git repo
        git_repos = args.git or []
        for repo_str in git_repos:
            repo = Path(repo_str)
            git_proposals = capture.capture_git(home, repo, dry_run=dry_run)
            report.proposals.extend(git_proposals)

        # Print summary
        if report.proposals:
            print(f"proposed {len(report.proposals)} (skipped {report.skipped})")
            for rec_id in report.proposals:
                try:
                    inbox_file = capture.inbox_dir(home) / f"{rec_id}.md"
                    rec = capture.records.read(inbox_file)
                except (OSError, RecordError):
                    continue
                print(f"{rec_id} {rec.title}")
        else:
            print(f"proposed 0 (skipped {report.skipped})")

        return 0
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def handle_review(args: argparse.Namespace) -> int:
    """Review inbox, stale evidence, and candidate queue."""
    from datetime import UTC, datetime, timedelta

    home = cli.home_from(args)
    do_capture = not args.no_capture

    try:
        # Capture if requested
        if do_capture:
            capture.capture_events(home, dry_run=False)
            git_repos = args.git or []
            for repo_str in git_repos:
                repo = Path(repo_str)
                capture.capture_git(home, repo, dry_run=False)

        # Load inbox
        inbox_records = capture.inbox(home)

        # Check stale evidence
        stale = capture.stale_evidence(home)

        # Load all records to count candidates and find recently promoted
        all_records, _ = capture.records.load_all(home)
        candidate_count = sum(1 for r in all_records if r.status == "candidate")

        # Find recently promoted records (within last 7 days)
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=7)
        recently_promoted = []
        for r in all_records:
            if "promoted_at" in r.extra:
                try:
                    promoted_at = capture.records.parse_time(r.extra["promoted_at"])
                    if promoted_at >= cutoff:
                        promoted_by = r.extra.get("promoted_by", "unknown")
                        recently_promoted.append((r.id, promoted_by, r.title))
                except Exception:
                    pass

        # Print inbox
        print(f"inbox ({len(inbox_records)})")
        for rec in inbox_records:
            print(f"  {rec.id} [{rec.type}] {rec.title}")

        # Print stale evidence
        print(f"\nstale evidence ({len(stale)})")
        for rec_id, evidence, reason in stale:
            print(f"  {rec_id} {evidence} {reason}")

        # Print recently promoted
        print(f"\nrecently promoted ({len(recently_promoted)})")
        for rec_id, promoted_by, title in recently_promoted:
            print(f"  {rec_id} {promoted_by} {title}")

        # Print candidates awaiting promote
        print(f"\ncandidates awaiting promote ({candidate_count})")

        return 0
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def handle_accept(args: argparse.Namespace) -> int:
    """Accept one or more proposals."""
    home = cli.home_from(args)

    try:
        for rec_id in args.id:
            capture.accept(home, rec_id)
            print(f"{rec_id} accepted")
        return 0
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def handle_reject(args: argparse.Namespace) -> int:
    """Reject a proposal with a reason."""
    home = cli.home_from(args)

    if not args.reason:
        print("brain: reject requires --reason", file=sys.stderr)
        return 2

    try:
        capture.reject(home, args.id, reason=args.reason)
        print(f"{args.id} rejected")
        return 0
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def register(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Register capture commands."""

    # capture
    capture_parser = sub.add_parser(
        "capture",
        parents=[common],
        help="Capture tool events and git trailers into proposals",
    )
    capture_parser.add_argument(
        "--git",
        action="append",
        default=[],
        help="Git repository to capture trailers from (repeatable)",
    )
    capture_parser.add_argument("--dry-run", action="store_true", help="Dry run")
    capture_parser.set_defaults(func=handle_capture)

    # review
    review_parser = sub.add_parser(
        "review",
        parents=[common],
        help="Review inbox, stale evidence, and candidate queue",
    )
    review_parser.add_argument(
        "--git",
        action="append",
        default=[],
        help="Git repository to capture trailers from (repeatable)",
    )
    review_parser.add_argument(
        "--no-capture",
        action="store_true",
        help="Skip capture step",
    )
    review_parser.set_defaults(func=handle_review)

    # accept
    accept_parser = sub.add_parser(
        "accept",
        parents=[common],
        help="Accept one or more proposals",
    )
    accept_parser.add_argument("id", nargs="+", help="Record id(s) to accept")
    accept_parser.set_defaults(func=handle_accept)

    # reject
    reject_parser = sub.add_parser(
        "reject",
        parents=[common],
        help="Reject a proposal",
    )
    reject_parser.add_argument("id", help="Record id to reject")
    reject_parser.add_argument("--reason", required=True, help="Rejection reason")
    reject_parser.set_defaults(func=handle_reject)
