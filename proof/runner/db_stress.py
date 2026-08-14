"""Small isolated SQLite writer stress used by the v4.3 recovery gate."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from second_brain import db, paths, semantic


def run(*, workers: int, per_worker: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="second-brain-db-stress-") as temporary:
        home = Path(temporary) / "brain"
        paths.ensure_layout(home)
        db.migrate(db.db_path(home))
        started = time.perf_counter()

        def write(worker: int) -> int:
            for index in range(per_worker):
                semantic.add_memory(
                    home,
                    f"stress {worker}-{index}",
                    f"isolated concurrency record {worker}-{index}",
                    scope="global",
                    grade="OBSERVED",
                )
            return per_worker

        with ThreadPoolExecutor(max_workers=workers) as pool:
            written = sum(pool.map(write, range(workers)))
        conn = db.connect(db.db_path(home))
        try:
            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()
        return {
            "workers": workers,
            "per_worker": per_worker,
            "written": written,
            "rows": count,
            "integrity_check": integrity,
            "foreign_key_check": foreign_keys,
            "wall_seconds": round(time.perf_counter() - started, 4),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--per-worker", type=int, default=25)
    args = parser.parse_args(argv)
    result = run(workers=args.workers, per_worker=args.per_worker)
    print(json.dumps(result, indent=2))
    return 0 if result["rows"] == result["written"] and result["integrity_check"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
