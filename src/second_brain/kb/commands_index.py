"""`brain` index commands (q, show, add, edit, supersede, retire, promote, index)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import index, projects, records
from .records import RecordError


def handle_q(args: argparse.Namespace) -> int:
    """Search query command."""
    from .cli import home_from

    home = home_from(args)
    proj = projects.resolve(home, Path(args.cwd or "."), args.project)

    query = " ".join(args.query)
    if not query.strip():
        print("(no matching records)", file=sys.stderr)
        return 1

    try:
        results = index.search(
            home,
            query,
            proj,
            all_projects=args.all_projects,
            include_history=args.history,
            as_of=args.as_of,
            limit=args.limit,
        )
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2

    if not results:
        print("(no matching records)", file=sys.stderr)
        return 1

    if args.json:
        output = []
        for hit in results:
            output.append(
                {
                    "id": hit.record.id,
                    "title": hit.record.title,
                    "type": hit.record.type,
                    "status": hit.record.status,
                    "grade": hit.record.effective_grade,
                    "score": hit.score,
                    "matched": hit.matched,
                }
            )
        print(json.dumps(output))
    else:
        for hit in results:
            print(index.render_hit(hit))

    return 0


def handle_show(args: argparse.Namespace) -> int:
    """Show a record by id."""
    from .cli import home_from

    home = home_from(args)

    try:
        record = records.load(home, args.id)
    except RecordError:
        return 1

    if args.json:
        # Serialize record as JSON
        data = {
            "id": record.id,
            "title": record.title,
            "type": record.type,
            "scope": record.scope,
            "project": record.project,
            "status": record.status,
            "grade": record.grade,
            "effective_grade": record.effective_grade,
            "recorded_at": record.recorded_at,
            "valid_from": record.valid_from,
            "evidence": list(record.evidence),
            "trigger_paths": list(record.trigger_paths),
            "trigger_errors": list(record.trigger_errors),
            "terms": list(record.terms),
            "domains": list(record.domains),
            "private": record.private,
            "body": record.body,
        }
        print(json.dumps(data))
    else:
        print(records.dumps(record), end="")

    return 0


def handle_add(args: argparse.Namespace) -> int:
    """Add a new record."""
    from .cli import home_from

    home = home_from(args)
    proj = projects.resolve(home, Path(args.cwd or "."), args.project)

    # Determine scope
    scope = args.scope
    if scope is None:
        scope = "project" if proj else "global"
    if scope == "project" and not proj:
        print("brain: no project resolved; pass --project or --scope global", file=sys.stderr)
        return 2

    # Get body
    body = ""
    if args.body_file:
        if args.body_file == "-":
            body = sys.stdin.read()
        else:
            try:
                body = Path(args.body_file).read_text(encoding="utf-8")
            except OSError as e:
                print(f"brain: {e}", file=sys.stderr)
                return 2
    elif args.body:
        body = args.body

    try:
        record = index.add(
            home,
            title=args.title,
            body=body,
            type=args.type,
            scope=scope,
            project=proj.id if proj else None,
            domains=tuple(args.domain),
            grade=args.grade,
            evidence=tuple(args.evidence),
            trigger_paths=tuple(args.trigger_path),
            trigger_errors=tuple(args.trigger_error),
            terms=tuple(args.term),
            valid_from=args.valid_from,
            private=args.private,
        )
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"id": record.id}))
    else:
        print(record.id)

    return 0


def handle_promote(args: argparse.Namespace) -> int:
    """Promote a candidate to current."""
    from .cli import home_from

    home = home_from(args)

    try:
        record = index.promote(home, args.id, reason=args.reason)
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"id": record.id, "status": record.status}))
    else:
        print(f"{record.id} current")

    return 0


def handle_supersede(args: argparse.Namespace) -> int:
    """Supersede one record with another."""
    from .cli import home_from

    home = home_from(args)

    try:
        old_rec, new_rec = index.supersede(
            home,
            args.old,
            by=args.by,
            reason=args.reason,
            kind=args.kind,
            effective_at=args.effective_at,
        )
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"old": old_rec.id, "new": new_rec.id, "status": old_rec.status}))
    else:
        print(f"{old_rec.id} superseded by {new_rec.id}")

    return 0


def handle_retire(args: argparse.Namespace) -> int:
    """Retire (invalidate) a record."""
    from .cli import home_from

    home = home_from(args)

    try:
        record = index.retire(home, args.id, reason=args.reason, effective_at=args.effective_at)
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"id": record.id, "status": record.status}))
    else:
        print(f"{record.id} invalidated")

    return 0


def handle_index(args: argparse.Namespace) -> int:
    """Refresh or rebuild the index."""
    from .cli import home_from

    home = home_from(args)

    try:
        report = index.rebuild(home) if args.rebuild else index.refresh(home)
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "added": report.added,
                    "updated": report.updated,
                    "removed": report.removed,
                    "errors": report.errors,
                }
            )
        )
    else:
        print(
            f"added {report.added} updated {report.updated} removed {report.removed} "
            f"errors {len(report.errors)}"
        )
        for error in report.errors:
            print(error, file=sys.stderr)

    return 0


def handle_edit(args: argparse.Namespace) -> int:
    """Change a record's type, title, valid time, evidence or triggers."""
    from .cli import home_from

    home = home_from(args)
    try:
        record = index.edit(
            home,
            args.id,
            type=args.type,
            title=args.title,
            valid_from=args.valid_from,
            add_evidence=tuple(args.evidence),
            add_trigger_errors=tuple(args.trigger_error),
            add_trigger_paths=tuple(args.trigger_path),
            add_terms=tuple(args.term),
        )
    except RecordError as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2
    print(
        json.dumps({"id": record.id, "type": record.type}) if args.json else f"{record.id} edited"
    )
    return 0


def register(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Register all index commands."""

    # q command
    q_parser = sub.add_parser("q", parents=[common], help="Search records")
    q_parser.add_argument("query", nargs="+", help="Search query terms")
    q_parser.add_argument("--all-projects", action="store_true", help="Search all projects")
    q_parser.add_argument("--history", action="store_true", help="Include superseded records")
    q_parser.add_argument("--as-of", default=None, help="Search as of time (ISO-8601)")
    q_parser.add_argument("--limit", type=int, default=3, help="Max results (1-10, default 3)")
    q_parser.set_defaults(func=handle_q)

    # show command
    show_parser = sub.add_parser("show", parents=[common], help="Show a record")
    show_parser.add_argument("id", help="Record id")
    show_parser.set_defaults(func=handle_show)

    # add command
    add_parser = sub.add_parser("add", parents=[common], help="Add a new record")
    add_parser.add_argument("title", help="Record title")
    add_parser.add_argument("--type", required=True, help="Record type")
    add_parser.add_argument("--body", default="", help="Record body text")
    add_parser.add_argument("--body-file", default=None, help="Read body from file (- for stdin)")
    add_parser.add_argument("--scope", default=None, help="Scope (project/domain/global)")
    add_parser.add_argument("--domain", action="append", default=[], help="Domain tag")
    add_parser.add_argument("--grade", default="OBSERVED", help="Grade")
    add_parser.add_argument("--evidence", action="append", default=[], help="Evidence item")
    add_parser.add_argument("--trigger-path", action="append", default=[], help="Trigger path")
    add_parser.add_argument("--trigger-error", action="append", default=[], help="Trigger error")
    add_parser.add_argument("--term", action="append", default=[], help="Search term")
    add_parser.add_argument("--valid-from", default=None, help="Valid from (ISO-8601)")
    add_parser.add_argument("--private", action="store_true", help="Mark as private")
    add_parser.set_defaults(func=handle_add)

    # promote command
    promote_parser = sub.add_parser(
        "promote", parents=[common], help="Promote candidate to current"
    )
    promote_parser.add_argument("id", help="Record id")
    promote_parser.add_argument("--reason", required=True, help="Promotion reason")
    promote_parser.set_defaults(func=handle_promote)

    # supersede command
    supersede_parser = sub.add_parser("supersede", parents=[common], help="Supersede a record")
    supersede_parser.add_argument("old", metavar="OLD", help="Old record id")
    supersede_parser.add_argument("--by", required=True, help="New record id")
    supersede_parser.add_argument("--reason", required=True, help="Supersession reason")
    supersede_parser.add_argument("--kind", default="supersedes", help="Kind (supersedes/corrects)")
    supersede_parser.add_argument("--effective-at", default=None, help="Effective time (ISO-8601)")
    supersede_parser.set_defaults(func=handle_supersede)

    # retire command
    retire_parser = sub.add_parser("retire", parents=[common], help="Retire (invalidate) a record")
    retire_parser.add_argument("id", help="Record id")
    retire_parser.add_argument("--reason", required=True, help="Retirement reason")
    retire_parser.add_argument("--effective-at", default=None, help="Effective time (ISO-8601)")
    retire_parser.set_defaults(func=handle_retire)

    edit_parser = sub.add_parser(
        "edit", parents=[common], help="Change type/title/evidence/triggers (never standing)"
    )
    edit_parser.add_argument("id", help="Record id")
    edit_parser.add_argument("--type", default=None, choices=records.RECORD_TYPES)
    edit_parser.add_argument("--title", default=None)
    edit_parser.add_argument("--valid-from", default=None, help="When it became true (ISO-8601)")
    edit_parser.add_argument("--evidence", action="append", default=[], help="Add evidence")
    edit_parser.add_argument(
        "--trigger-error", action="append", default=[], help="Add an error pattern (re: for regex)"
    )
    edit_parser.add_argument("--trigger-path", action="append", default=[], help="Add a path glob")
    edit_parser.add_argument("--term", action="append", default=[], help="Add a search term")
    edit_parser.set_defaults(func=handle_edit)

    # index command
    index_parser = sub.add_parser("index", parents=[common], help="Manage the index")
    index_parser.add_argument("--rebuild", action="store_true", help="Rebuild the index")
    index_parser.set_defaults(func=handle_index)
