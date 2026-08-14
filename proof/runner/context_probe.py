"""Negative-control probe for context/retrieval integration claims."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from second_brain import db, jit, monitor, paths, semantic, working_set


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="second-brain-context-") as temporary:
        home = Path(temporary) / "brain"
        paths.ensure_layout(home)
        db.migrate(db.db_path(home))
        working_set.init_capsule(home, "probe", "retrieve the WAL lesson")
        memory_id = semantic.add_memory(
            home,
            "WAL lesson",
            "The WAL lesson is to remove stale sidecars before restore.",
            scope="global",
            grade="VERIFIED",
        )
        capsule = jit.compile_context(home, "probe", "retrieve the WAL lesson")
        body = capsule.read_text(encoding="utf-8")
        pressure = monitor._context_pressure([{"context_usage": {"percent": 55}}])
        return {
            "memory_id": memory_id,
            "semantic_search_matches": len(semantic.search_memories(home, "WAL lesson")),
            "memory_id_in_jit_capsule": memory_id in body,
            "context_pressure_at_55_pct": pressure["strength"],
            "configured_green_until_pct": 60,
            "configured_yellow_until_pct": 75,
            "configured_orange_until_pct": 85,
        }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
