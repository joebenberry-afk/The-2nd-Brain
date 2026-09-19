"""Preflight for an OMP qualification run.

Creates/validates the disposable Brain home and fixture repository, records the
production baseline checksums, and proves the fixture starts red (the bug the
worker must fix). Read-only with respect to production. Writes only inside the
disposable home/fixture and the evidence output file.

Usage:
    python preflight_run.py --home <dir> --fixture <dir> --project-id <id> \
        --prod-db <brain.sqlite> --python <venv python> --workdir <repo> \
        --out <preflight.json> [--fixture-repo <already registered repo>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BUGGY_CALC = "def add(left, right):\n    return left - right\n"
TEST_CALC = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def db_checksum(db: Path, table: str, cols: list[str]) -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {cols[0]}").fetchall()
    finally:
        conn.close()
    payload = "\n".join(
        "|".join("" if value is None else str(value) for value in row) for row in rows
    )
    return {"rows": len(rows), "sha256": hashlib.sha256(payload.encode()).hexdigest()}


def db_count(db: Path, table: str) -> int:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def schema_version(db: Path) -> int | None:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT value FROM schema_version ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return int(row[0]) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def run_brainctl(python: str, workdir: Path, home: Path, argv: list[str]) -> dict:
    result = subprocess.run(
        [python, "-m", "second_brain", *argv, "--home", str(home)],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=600,
        env={
            **{k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")},
            "SECOND_BRAIN_HOME": str(home),
        },
    )
    return {
        "argv": argv,
        "exit_code": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-2000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--prod-db", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    home = Path(args.home)
    fixture = Path(args.fixture)
    python = args.python
    workdir = Path(args.workdir)
    prod = Path(args.prod_db)
    actions: list[dict] = []

    if not (home / "db" / "brain.sqlite").exists():
        actions.append({"action": "init", **run_brainctl(python, workdir, home, ["init"])})

    actions.append({"action": "doctor", **run_brainctl(python, workdir, home, ["doctor"])})

    if not fixture.exists():
        fixture.mkdir(parents=True)
        (fixture / "calc.py").write_text(BUGGY_CALC, encoding="utf-8")
        (fixture / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
        actions.append({"action": "fixture-created", "path": str(fixture)})
    if not (fixture / ".brain" / "project.toml").exists():
        actions.append(
            {
                "action": "project-add",
                **run_brainctl(
                    python, workdir, home, ["project", "add", "--id", args.project_id, str(fixture)]
                ),
            }
        )

    pre_test = subprocess.run(
        [python, "-m", "pytest", "test_calc.py", "-q"],
        cwd=fixture,
        capture_output=True,
        text=True,
        timeout=300,
    )

    db = home / "db" / "brain.sqlite"
    payload = {
        "home": str(home),
        "fixture": str(fixture),
        "project_id": args.project_id,
        "schema_version": schema_version(db),
        "home_counts": {
            "worker_tasks": db_count(db, "worker_tasks"),
            "worker_lifecycle_receipts": db_count(db, "worker_lifecycle_receipts"),
        },
        "production_before": {
            "worker_tasks": db_checksum(
                prod, "worker_tasks", ["task_id", "state", "packet_sha256"]
            ),
            "worker_lifecycle_receipts": db_checksum(
                prod, "worker_lifecycle_receipts", ["attempt_id", "sequence", "receipt_sha256"]
            ),
        },
        "fixture_sha256": {
            "calc.py": sha256_file(fixture / "calc.py"),
            "test_calc.py": sha256_file(fixture / "test_calc.py"),
        },
        "fixture_starts_red": {
            "exit_code": pre_test.returncode,
            "stdout_tail": pre_test.stdout[-800:],
            "stderr_tail": pre_test.stderr[-400:],
            "red": pre_test.returncode != 0,
        },
        "actions": actions,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "home_counts": payload["home_counts"],
                "production_before": payload["production_before"],
                "fixture_starts_red": payload["fixture_starts_red"]["red"],
                "out": str(out),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
