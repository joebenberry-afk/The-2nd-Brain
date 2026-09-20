"""Run the host-patch attempt-settlement tests outside the OMP workspace.

The host patch tests normally run inside a full v18.2.6 workspace where
``@oh-my-pi/pi-utils`` resolves from the package's own dependencies. This
script builds a disposable harness (a tsconfig ``paths`` stub for the one
external import) so the same test file can be executed against

  * the sealed host module that is installed today, and
  * the candidate host module in this repository,

without touching the installation or the workspace. The sealed run is the
failing-before evidence: it rewrites an accepted outcome when cleanup reports
a cancellation, which the durable ledger rejects as OUTCOME_CONFLICT
(audit finding F-06).

Usage:
    python scripts/run_host_settlement_tests.py
    python scripts/run_host_settlement_tests.py --module candidate
    python scripts/run_host_settlement_tests.py --module sealed --keep
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19"
CANDIDATE_MODULE = PATCH_DIR / "host" / "attempt-settlement.ts"
TEST_FILE = PATCH_DIR / "tests" / "attempt-settlement-outcome.test.ts"
_OMP_PACKAGES = Path.home() / ".bun/install/global/node_modules/@oh-my-pi"
_ATTEMPT_SETTLEMENT_REL = "src/task/attempt-settlement.ts"
SEALED_MODULES = (
    _OMP_PACKAGES / "pi-coding-agent" / _ATTEMPT_SETTLEMENT_REL,
    _OMP_PACKAGES / "pi-coding-agent-canary" / _ATTEMPT_SETTLEMENT_REL,
)
BUN_CANDIDATES = (
    Path.home() / ".bun/bin/bun.exe",
    Path.home() / ".bun/bin/bun",
)

TSCONFIG = {
    "compilerOptions": {
        "baseUrl": ".",
        "paths": {"@oh-my-pi/pi-utils": ["stubs/pi-utils.ts"]},
    }
}
STUB = (
    "export const logger = {\n"
    "\twarn: (..._args: unknown[]): void => {},\n"
    "\tinfo: (..._args: unknown[]): void => {},\n"
    "\terror: (..._args: unknown[]): void => {},\n"
    "\tdebug: (..._args: unknown[]): void => {},\n"
    "};\n"
)


def find_bun() -> Path:
    for candidate in BUN_CANDIDATES:
        if candidate.is_file():
            return candidate
    found = shutil.which("bun")
    if found:
        return Path(found)
    raise SystemExit("bun not found; install bun or pass --bun")


def sealed_module() -> Path:
    for candidate in SEALED_MODULES:
        if candidate.is_file():
            return candidate
    raise SystemExit("no sealed attempt-settlement.ts found under the OMP install")


def build_harness(root: Path, module: Path) -> None:
    (root / "stubs").mkdir(parents=True)
    (root / "src" / "task").mkdir(parents=True)
    (root / "tests" / "host-patch").mkdir(parents=True)
    (root / "tsconfig.json").write_text(json.dumps(TSCONFIG, indent=2) + "\n", encoding="utf-8")
    (root / "stubs" / "pi-utils.ts").write_text(STUB, encoding="utf-8")
    (root / "src" / "task" / "attempt-settlement.ts").write_bytes(module.read_bytes())
    (root / "tests" / "host-patch" / TEST_FILE.name).write_text(
        TEST_FILE.read_text(encoding="utf-8"), encoding="utf-8"
    )


def run(bun: Path, module: Path, label: str, keep: bool) -> int:
    root = Path(tempfile.mkdtemp(prefix=f"host-settlement-{label}-"))
    build_harness(root, module)
    print(f"[{label}] module: {module}")
    print(f"[{label}] harness: {root}")
    proc = subprocess.run(
        [str(bun), "test", "tests/host-patch"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    tail = "\n".join(line for line in proc.stdout.splitlines() if line.strip())[-1500:]
    print(tail)
    if proc.returncode != 0:
        print(f"[{label}] stderr tail: {proc.stderr.strip()[-400:]}")
    print(f"[{label}] exit={proc.returncode}")
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", choices=("candidate", "sealed", "both"), default="both")
    parser.add_argument("--bun", type=Path, default=None)
    parser.add_argument("--keep", action="store_true", help="keep the disposable harness")
    args = parser.parse_args()

    bun = args.bun or find_bun()
    results: dict[str, int] = {}
    if args.module in ("sealed", "both"):
        results["sealed"] = run(bun, sealed_module(), "sealed", args.keep)
    if args.module in ("candidate", "both"):
        results["candidate"] = run(bun, CANDIDATE_MODULE, "candidate", args.keep)

    print(json.dumps(results, indent=2))
    if args.module == "both":
        # The sealed module is expected to fail (that is the defect); the candidate
        # must pass. Report the pair, not a single exit code.
        ok = results.get("candidate") == 0 and results.get("sealed") != 0
        print(
            "PASS (candidate passes, sealed demonstrates the defect)" if ok else "UNEXPECTED RESULT"
        )
        return 0 if ok else 1
    return results.get(args.module, 1)


if __name__ == "__main__":
    sys.exit(main())
