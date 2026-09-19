"""Independent read-only post-exit checks for an OMP qualification run.

Reads the disposable home (read-only), re-reads the production baseline
checksums, re-runs the fixture test through the pinned interpreter, and
extracts the decisive trace markers. Writes only the evidence output file.

Usage:
    python post_exit_check.py --home-db <brain.sqlite> --prod-db <brain.sqlite> \
        --out <post-exit.json> --fixture <dir> --python <venv python> \
        --trace <boot.txt> [--trace <boot-c.txt> ...] [--label name]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

TRACE_MARKERS = (
    "route:policy",
    "begin:",
    "obligation:",
    "barrier:",
    "cleanup:",
    "isolation:",
    "backend:started",
    "publish:",
    "deliver:",
    "reap:",
    "observer-drain",
    "pre-quit",
)


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


def dump(db: Path, table: str, order: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order}")]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home-db", required=True)
    parser.add_argument("--prod-db", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--trace", action="append", default=[])
    parser.add_argument("--label", default="run")
    args = parser.parse_args()

    home = Path(args.home_db)
    prod = Path(args.prod_db)

    tasks = dump(home, "worker_tasks", "rowid")
    receipts = dump(home, "worker_lifecycle_receipts", "attempt_id, sequence")

    receipt_summaries = []
    per_attempt_sequences: dict[str, list[int]] = {}
    for row in receipts:
        try:
            payload = json.loads(row["payload_json"])
        except (ValueError, TypeError):
            payload = {}
        per_attempt_sequences.setdefault(row["attempt_id"], []).append(row["sequence"])
        receipt_summaries.append(
            {
                "attempt_id": row["attempt_id"],
                "sequence": row["sequence"],
                "recorded_at": row["recorded_at"],
                "receipt_sha256": row["receipt_sha256"],
                "executor_settled": payload.get("executor_settled"),
                "cleanup_complete": payload.get("cleanup_complete"),
                "outcome": payload.get("outcome"),
                "native_attempt_id": payload.get("native_attempt_id"),
                "agent_id": payload.get("agent_id"),
            }
        )

    contiguous = {
        attempt: sequences == list(range(1, len(sequences) + 1))
        for attempt, sequences in per_attempt_sequences.items()
    }

    after = {
        "worker_tasks": db_checksum(prod, "worker_tasks", ["task_id", "state", "packet_sha256"]),
        "worker_lifecycle_receipts": db_checksum(
            prod, "worker_lifecycle_receipts", ["attempt_id", "sequence", "receipt_sha256"]
        ),
    }

    fixture_test = subprocess.run(
        [args.python, "-m", "pytest", "test_calc.py", "-q"],
        cwd=args.fixture,
        capture_output=True,
        text=True,
        timeout=300,
    )

    traces = {}
    for trace in args.trace:
        path = Path(trace)
        if not path.exists():
            traces[str(path)] = {"exists": False}
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = [line for line in lines if any(marker in line for marker in TRACE_MARKERS)]
        traces[str(path)] = {
            "exists": True,
            "lines_total": len(lines),
            "sha256": sha256_file(path),
            "markers": selected,
        }

    worker = []
    for task in tasks:
        worker.append(
            {
                "task_id": task.get("task_id"),
                "state": task.get("state"),
                "logical_outcome": task.get("logical_outcome"),
                "writer_ownership": task.get("writer_ownership"),
                "executor_settled": task.get("executor_settled"),
                "cleanup_complete": task.get("cleanup_complete"),
                "attempt_id": task.get("attempt_id"),
                "native_attempt_id": task.get("native_attempt_id"),
                "agent_id": task.get("agent_id"),
                "host_generation": task.get("host_generation"),
                "lifecycle_sequence": task.get("lifecycle_sequence"),
                "project_id": task.get("project_id"),
                "accepted_at": task.get("accepted_at"),
                "updated_at": task.get("updated_at"),
            }
        )

    payload = {
        "label": args.label,
        "home_db": str(home),
        "home_db_sha256_at_check": sha256_file(home),
        "worker_tasks": worker,
        "receipts": receipt_summaries,
        "receipt_sequences_contiguous_1_to_n": contiguous,
        "production_before_and_after": {
            "after": after,
            "note": "compare with preflight.json production_before",
        },
        "fixture_after": {
            "exit_code": fixture_test.returncode,
            "stdout_tail": fixture_test.stdout[-800:],
            "green": fixture_test.returncode == 0,
            "sha256": {
                "calc.py": sha256_file(Path(args.fixture) / "calc.py"),
                "test_calc.py": sha256_file(Path(args.fixture) / "test_calc.py"),
            },
        },
        "traces": traces,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "label": args.label,
                "tasks": [
                    (
                        t["task_id"][:20],
                        t["state"],
                        t["writer_ownership"],
                        t["executor_settled"],
                        t["cleanup_complete"],
                    )
                    for t in worker
                ],
                "receipts": [
                    (r["attempt_id"], r["sequence"], r["executor_settled"], r["cleanup_complete"])
                    for r in receipt_summaries
                ],
                "fixture_green": payload["fixture_after"]["green"],
                "out": str(out),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
