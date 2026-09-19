"""Read-only disposable-DB watcher for OMP worker-settlement qualification runs.

Purpose
-------
Observe, without writing to the database, the durable state transitions the
qualification evidence requires:

- *state-1*: the first poll at which a newly created worker attempt has at
  least one lifecycle receipt and has NOT yet reached terminal settlement.
- *state-2*: the first poll at which that attempt has a receipt with
  ``cleanup_complete == true`` (terminal settlement for the attempt).

Snapshots are page-consistent copies produced with the SQLite backup API from
a read-only source connection; task and receipt reads are taken from the copy
inside a single transaction. The watcher never reconstructs a missed snapshot
from later rows: if the first observation of an attempt is already terminal,
it reports ``state_1_missing`` instead of fabricating state-1.

Usage
-----
    python db_watch.py --db <brain.sqlite> --outdir <dir> \
        [--stop-file <path>] [--interval 0.2] [--timeout 1800] [--label name]

Exit code is 0 when the watcher ran to its stop condition (success or
timeout); 2 on unusable arguments; 3 when the database never appeared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def connect_ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def read_snapshot(db: Path, out_sqlite: Path) -> dict:
    """Copy the DB read-only (backup API) and read one consistent snapshot."""
    src = connect_ro(db)
    try:
        if out_sqlite.exists():
            out_sqlite.unlink()
        dst = sqlite3.connect(out_sqlite)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    conn = connect_ro(out_sqlite)
    try:
        conn.execute("BEGIN")
        tasks = [dict(row) for row in conn.execute("SELECT * FROM worker_tasks ORDER BY rowid")]
        receipts = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM worker_lifecycle_receipts ORDER BY attempt_id, sequence",
            )
        ]
        conn.execute("COMMIT")
    finally:
        conn.close()
    return {"tasks": tasks, "receipts": receipts}


def receipt_summary(rows: list[dict]) -> list[dict]:
    summary = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (ValueError, TypeError):
            payload = {}
        summary.append(
            {
                "attempt_id": row["attempt_id"],
                "sequence": row["sequence"],
                "recorded_at": row["recorded_at"],
                "receipt_sha256": row["receipt_sha256"],
                "executor_settled": payload.get("executor_settled"),
                "cleanup_complete": payload.get("cleanup_complete"),
                "outcome": payload.get("outcome"),
            }
        )
    return summary


class WatchState:
    def __init__(self, db: Path, outdir: Path, label: str) -> None:
        self.db = db
        self.outdir = outdir
        self.label = label
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.started_at = time.time()
        self.baseline_attempts: set[str] = set()
        self.attempt_id: str | None = None
        self.state1: dict | None = None
        self.state2: dict | None = None
        self.state1_missing = False
        self.state2_missing = False
        self.max_sequence_seen: dict[str, int] = {}
        self.polls = 0
        self.stop_reason = "unknown"
        self.live_db_sha256_at_start: str | None = None

    def baseline(self) -> None:
        conn = connect_ro(self.db)
        try:
            rows = conn.execute(
                "SELECT DISTINCT attempt_id FROM worker_lifecycle_receipts",
            ).fetchall()
            self.baseline_attempts = {row[0] for row in rows}
        finally:
            conn.close()
        self.live_db_sha256_at_start = sha256_file(self.db) if self.db.exists() else None
        (self.outdir / "watcher-start.json").write_text(
            json.dumps(
                {
                    "label": self.label,
                    "db": str(self.db),
                    "started_at_unix": self.started_at,
                    "started_at_iso": time.strftime(
                        "%Y-%m-%dT%H:%M:%S", time.localtime(self.started_at)
                    ),
                    "baseline_attempts": sorted(self.baseline_attempts),
                    "live_db_sha256_at_start": self.live_db_sha256_at_start,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def poll(self) -> None:
        self.polls += 1
        conn = connect_ro(self.db)
        try:
            conn.execute("BEGIN")
            receipt_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM worker_lifecycle_receipts ORDER BY attempt_id, sequence",
                )
            ]
            conn.execute("COMMIT")
        finally:
            conn.close()

        per_attempt: dict[str, list[dict]] = {}
        for row in receipt_rows:
            per_attempt.setdefault(row["attempt_id"], []).append(row)
        for attempt, rows in per_attempt.items():
            self.max_sequence_seen[attempt] = max(
                self.max_sequence_seen.get(attempt, 0), max(r["sequence"] for r in rows)
            )

        if self.attempt_id is None:
            new_attempts = [
                attempt for attempt in per_attempt if attempt not in self.baseline_attempts
            ]
            if not new_attempts:
                return
            # Choose the attempt with the earliest first receipt; ties by attempt id.
            self.attempt_id = min(
                new_attempts,
                key=lambda attempt: (per_attempt[attempt][0]["recorded_at"], attempt),
            )

        rows = per_attempt.get(self.attempt_id, [])
        if not rows:
            return

        terminal_row = next(
            (
                row
                for row in rows
                if json.loads(row["payload_json"] or "{}").get("cleanup_complete") is True
            ),
            None,
        )

        if self.state1 is None and not self.state1_missing:
            if terminal_row is not None:
                # First observation is already terminal: the intermediate state was missed.
                self.state1_missing = True
            else:
                snapshot = read_snapshot(self.db, self.outdir / "state-1.sqlite")
                self.state1 = {
                    "captured_at_unix": time.time(),
                    "captured_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "attempt_id": self.attempt_id,
                    "sqlite": str(self.outdir / "state-1.sqlite"),
                    "tasks": snapshot["tasks"],
                    "receipts": receipt_summary(snapshot["receipts"]),
                    "phase": "receipt-after-first-sequence-before-terminal",
                }
                (self.outdir / "state-1.json").write_text(
                    json.dumps(self.state1, indent=2), encoding="utf-8"
                )

        if terminal_row is not None and self.state2 is None:
            snapshot = read_snapshot(self.db, self.outdir / "state-2.sqlite")
            self.state2 = {
                "captured_at_unix": time.time(),
                "captured_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "attempt_id": self.attempt_id,
                "terminal_sequence": terminal_row["sequence"],
                "sqlite": str(self.outdir / "state-2.sqlite"),
                "tasks": snapshot["tasks"],
                "receipts": receipt_summary(snapshot["receipts"]),
                "phase": "terminal-cleanup-complete",
            }
            (self.outdir / "state-2.json").write_text(
                json.dumps(self.state2, indent=2), encoding="utf-8"
            )

    def finish(self, reason: str) -> dict:
        self.stop_reason = reason
        if self.attempt_id is not None:
            if self.state1 is None:
                self.state1_missing = True
            if self.state2 is None:
                self.state2_missing = True
        stopped_at = time.time()
        record = {
            "label": self.label,
            "db": str(self.db),
            "started_at_unix": self.started_at,
            "stopped_at_unix": stopped_at,
            "duration_seconds": round(stopped_at - self.started_at, 3),
            "stop_reason": reason,
            "polls": self.polls,
            "baseline_attempts": sorted(self.baseline_attempts),
            "watched_attempt": self.attempt_id,
            "state_1_captured": self.state1 is not None,
            "state_1_missing": self.state1_missing,
            "state_2_captured": self.state2 is not None,
            "state_2_missing": self.state2_missing,
            "state_1_file": self.state1["sqlite"] if self.state1 else None,
            "state_2_file": self.state2["sqlite"] if self.state2 else None,
            "terminal_sequence": self.state2["terminal_sequence"] if self.state2 else None,
            "max_sequence_seen": self.max_sequence_seen,
            "live_db_sha256_at_start": self.live_db_sha256_at_start,
            "db_sha256_at_finish": sha256_file(self.db) if self.db.exists() else None,
        }
        (self.outdir / "watcher.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--stop-file", default=None)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--label", default="watcher")
    args = parser.parse_args()

    db = Path(args.db)
    deadline = time.time() + args.timeout
    state = WatchState(db, Path(args.outdir), args.label)

    waited_for_db = 0.0
    while not db.exists() and time.time() < deadline:
        time.sleep(args.interval)
        waited_for_db += args.interval
    if not db.exists():
        print(json.dumps({"error": "database never appeared", "db": str(db)}))
        return 3

    state.baseline()

    while time.time() < deadline:
        try:
            state.poll()
        except sqlite3.OperationalError as error:
            # A busy/transient error is not a snapshot; retry after the interval.
            if "locked" not in str(error).lower() and "unable to open" not in str(error).lower():
                raise
        if state.state2 is not None:
            state.finish("terminal-state-captured")
            print(
                json.dumps(
                    {
                        "watcher": str(Path(args.outdir) / "watcher.json"),
                        "stop": "terminal-state-captured",
                    }
                )
            )
            return 0
        if args.stop_file and Path(args.stop_file).exists():
            state.finish("stop-file")
            print(
                json.dumps(
                    {"watcher": str(Path(args.outdir) / "watcher.json"), "stop": "stop-file"}
                )
            )
            return 0
        time.sleep(args.interval)

    state.finish("timeout")
    print(json.dumps({"watcher": str(Path(args.outdir) / "watcher.json"), "stop": "timeout"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
