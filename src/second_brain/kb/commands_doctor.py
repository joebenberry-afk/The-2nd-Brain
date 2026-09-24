"""`brain doctor` command."""

from __future__ import annotations

import argparse
import json
import sys

from . import cli, doctor


def handle_doctor(args: argparse.Namespace) -> int:
    """Run health check and report."""
    home = cli.home_from(args)
    use_json = args.json or False

    try:
        report = doctor.check(home)

        if use_json:
            # JSON output
            output = {
                "errors": report.errors,
                "warnings": report.warnings,
                "sizes": report.sizes,
            }
            print(json.dumps(output, indent=2))
        else:
            # Human-readable output
            print(f"errors ({len(report.errors)})")
            for error in report.errors:
                print(f"  {error}")

            print(f"\nwarnings ({len(report.warnings)})")
            for warning in report.warnings:
                print(f"  {warning}")

            print("\nsizes")
            for name, size_bytes in report.sizes.items():
                print(f"  {name} {size_bytes}")

        # Exit 1 if there are errors, else 0
        return 1 if report.errors else 0
    except Exception as e:
        print(f"brain: {e}", file=sys.stderr)
        return 2


def register(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Register doctor command."""
    doctor_parser = sub.add_parser(
        "doctor",
        parents=[common],
        help="Run health check",
    )
    doctor_parser.set_defaults(func=handle_doctor)
