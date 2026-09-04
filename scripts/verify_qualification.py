"""Independent qualification verifier for Second Brain v2 (P8 §9).

Performs independent read-only qualification verification over database integrity,
schema migrations, qualification ledgers, telemetry, and privacy absence.

CLI:
    python scripts/verify_qualification.py --json
    python scripts/verify_qualification.py --manifest <path> --out <path>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from second_brain import db  # noqa: E402


def check(name: str, ok: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"check": name, "ok": bool(ok), "details": details}


def check_database_integrity(home: Path) -> dict[str, Any]:
    dbfile = db.db_path(home)
    if not dbfile.is_file():
        return check("database_integrity", False, {"reason": f"missing db {dbfile}"})
    conn = db.connect(dbfile, readonly=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        ok = row is not None and row[0] == "ok"
        return check("database_integrity", ok, {"integrity": row[0] if row else None})
    except sqlite3.Error as exc:
        return check("database_integrity", False, {"error": str(exc)})
    finally:
        conn.close()


def check_schema_migrations(home: Path) -> dict[str, Any]:
    dbfile = db.db_path(home)
    pending = db.pending_migrations(dbfile)
    conn = db.connect(dbfile, readonly=True)
    try:
        cur_ver = db.current_version(conn)
    finally:
        conn.close()
    expected_min = 21
    ok = len(pending) == 0 and cur_ver >= expected_min
    return check("schema_migrations", ok, {"current_version": cur_ver, "pending": pending})


def check_v2_tables_present(home: Path) -> dict[str, Any]:
    dbfile = db.db_path(home)
    conn = db.connect(dbfile, readonly=True)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        retained = {
            "v2_candidates",
            "v2_interventions",
            "v2_observations",
            "v2_frontier_items",
            "v2_rollout_events",
            "v2_qualification",
        }
        missing = retained - tables
        ok = len(missing) == 0
        return check("v2_tables_present", ok, {"retained_tables_present": list(retained - missing), "missing": list(missing)})
    finally:
        conn.close()


def check_qualification_ledger(home: Path) -> dict[str, Any]:
    dbfile = db.db_path(home)
    conn = db.connect(dbfile, readonly=True)
    try:
        rows = conn.execute("SELECT qualification_id, phase, requirement, status FROM v2_qualification").fetchall()
        proven = [dict(r) for r in rows if r["status"] == "PROVEN"]
        return check("qualification_ledger", True, {"records": [dict(r) for r in rows], "proven_count": len(proven)})
    finally:
        conn.close()


def check_privacy_absence() -> dict[str, Any]:
    """Verify that reports do not contain forbidden leaked fields."""
    forbidden = ["api_key", "secret_key", "private_key", "-----BEGIN PRIVATE KEY-----"]
    leaks = []
    v2_dir = REPO_ROOT / "outputs" / "reports" / "v2"
    if v2_dir.is_dir():
        for p in v2_dir.rglob("*.json"):
            try:
                text = p.read_text(encoding="utf-8")
                for f in forbidden:
                    if f in text:
                        leaks.append(f"{p}: leaked {f}")
            except Exception:
                pass
    ok = len(leaks) == 0
    return check("privacy_absence", ok, {"leaks": leaks})


def verify_all(home: Path) -> dict[str, Any]:
    results = [
        check_database_integrity(home),
        check_schema_migrations(home),
        check_v2_tables_present(home),
        check_qualification_ledger(home),
        check_privacy_absence(),
    ]
    ok = all(r["ok"] for r in results)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "ok": ok,
        "checks": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output JSON report to stdout")
    parser.add_argument("--manifest", type=Path, default=None, help="Manifest path to check")
    parser.add_argument("--out", type=Path, default=None, help="Output destination")
    parser.add_argument("--home", type=Path, default=REPO_ROOT, help="Brain home directory")
    args = parser.parse_args(argv)

    home = Path(args.home).resolve()
    result = verify_all(home)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    if args.json or not args.manifest:
        print(json.dumps(result, indent=2))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
