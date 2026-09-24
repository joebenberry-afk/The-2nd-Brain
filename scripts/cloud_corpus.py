"""Memory-corpus seed for Brain homes that have no live database (cloud sessions).

The `memories` rows carry fields the canonical `memory/` files do not
(origin_class, authority_ceiling, strength and retrieval stats), and nothing
rebuilds rows from the files, so a fresh checkout's index would be empty.
`export` snapshots only the rows retrieval needs — no telemetry, sessions or
deliveries — and `load` restores them into an empty home; `memory reindex` then
rebuilds the derived index.

    python scripts/cloud_corpus.py export   # from the live home; commit the result
    python scripts/cloud_corpus.py load     # into $SECOND_BRAIN_HOME, only if empty
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from second_brain import db, paths

SEED = Path(__file__).with_name("cloud_corpus_seed.json")
# Parent tables before children: memory_sources references memories,
# memory_supersessions references memories.
TABLES = ("projects", "memories", "memory_versions", "memory_sources", "memory_supersessions")


def export(home: Path) -> int:
    conn = db.connect(db.db_path(home), readonly=True)
    try:
        schema = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        tables = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in TABLES
        }
    finally:
        conn.close()
    # Rows written on Windows store home-relative body paths with backslashes, which
    # Linux reads as one file name; "/" resolves on both.
    for table in ("memories", "memory_versions"):
        for row in tables[table]:
            if row.get("body_path"):
                row["body_path"] = row["body_path"].replace("\\", "/")
    seed = {
        "schema_version": schema,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tables": tables,
    }
    SEED.write_text(json.dumps(seed, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    counts = ", ".join(f"{t}={len(rows)}" for t, rows in tables.items())
    print(f"exported schema {schema}: {counts} -> {SEED}")
    return 0


def load(home: Path) -> int:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    dbfile = db.db_path(home)
    db.migrate(dbfile)
    conn = db.connect(dbfile)
    try:
        if conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]:
            print("corpus already present; seed not loaded")
            return 0
        for table in TABLES:
            rows = seed["tables"].get(table) or []
            if not rows:
                continue
            columns = sorted(rows[0])
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                [[row[c] for c in columns] for row in rows],
            )
        conn.commit()
    finally:
        conn.close()
    counts = ", ".join(f"{t}={len(seed['tables'].get(t) or [])}" for t in TABLES)
    print(f"loaded seed exported {seed['exported_at']} (schema {seed['schema_version']}): {counts}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or load the cloud memory-corpus seed.")
    parser.add_argument("command", choices=("export", "load"))
    args = parser.parse_args(argv)
    home = paths.resolve_home()
    return export(home) if args.command == "export" else load(home)


if __name__ == "__main__":
    sys.exit(main())
