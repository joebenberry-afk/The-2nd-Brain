"""Snapshot or verify extension-only candidate bytes; this is not an approval.

All paths are explicit. No host package, installed profile, or canonical Brain home
is selected by default. A separately authorized installer decides whether to copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "second-brain.extension-candidate-manifest.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path, *, source: bool) -> dict[str, str]:
    """Match the existing installer layout: flat TS plus types/*.d.ts."""
    src = root / "src" if source else root
    files = [*src.glob("*.ts"), *(root / "types").glob("*.d.ts")]
    if not files or not (src / "index.ts").is_file():
        raise ValueError("extension index.ts is missing")
    return {
        (f"types/{path.name}" if path.parent.name == "types" else path.name): sha256_file(path)
        for path in sorted(files)
    }


def snapshot(source_root: Path) -> dict:
    return {"schema": SCHEMA, "files": _inventory(source_root, source=True)}


def verify(manifest: dict, source_root: Path, installed_root: Path) -> None:
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("files"), dict):
        raise ValueError("extension candidate manifest schema is unsupported")
    recorded = manifest["files"]
    if recorded != _inventory(source_root, source=True):
        raise ValueError("candidate source bytes differ from manifest")
    if recorded != _inventory(installed_root, source=False):
        raise ValueError("installed extension inventory or bytes differ from candidate")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="snapshot candidate sources")
    mode.add_argument("--check", action="store_true", help="verify source and installed bytes")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--installed-root", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.write:
        record = snapshot(args.source_root)
        with args.manifest.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        print("candidate snapshot written; not an approval")
        return 0
    if args.installed_root is None:
        parser.error("--check requires --installed-root")
    record = json.loads(args.manifest.read_text(encoding="utf-8"))
    verify(record, args.source_root, args.installed_root)
    print("extension candidate bytes match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
