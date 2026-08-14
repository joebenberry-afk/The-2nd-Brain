"""Run the non-holdout retrieval scale curve in isolated temporary homes."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .retrieval import benchmark_retrieval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, action="append", required=True)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="second-brain-retrieval-") as temporary:
        root = Path(temporary)
        results = [
            benchmark_retrieval(size, root=root / str(size), seed=args.seed).as_dict()
            for size in args.size
        ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
