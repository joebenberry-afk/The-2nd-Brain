"""One bounded production qualification run against the activated runtime.

Purpose: prove the installed OMP runtime loads the activated bytes and executes
the repaired settlement path - admission, held ownership, executor settlement,
cleanup completion, terminal receipt, ownership release. It is not a second
qualification campaign: the exact successor bytes were already qualified in the
stage, and this run only establishes that production is running them.

Production state touched: none by design. The Brain home and the fixture are
disposable, and the OMP profile is the real one (a production run has to use the
production configuration); the session artifacts OMP writes there are its normal
runtime state.

    python scripts/run_production_smoke.py --pack outputs/reports/omp-activation-<stamp> \
        --identities docs/integrations/omp-host-patch-2026-09-19-production/RUN-IDENTITIES.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "scripts" / "omp-canary"
PYTHON = Path(sys.executable)
BUN = Path.home() / ".bun" / "bin" / "bun.exe"
RETAL_CLI = Path.home() / ".bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/src/cli.ts"
INSTALLED_EXTENSION = Path.home() / ".omp/agent/extensions/second-brain"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], timeout: float | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    process = subprocess.run(command, capture_output=True, text=True, env=env, timeout=timeout)
    return {
        "argv": command,
        "exit_code": process.returncode,
        "stdout_tail": process.stdout[-1500:],
        "stderr_tail": process.stderr[-1500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--identities", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--suffix", default="", help="attempt suffix for a fresh run directory")
    args = parser.parse_args()
    pack: Path = args.pack
    pack.mkdir(parents=True, exist_ok=True)

    home = Path(os.environ.get("TEMP", "")) / "omp-production-smoke" / "brain-home"
    fixture = Path(os.environ.get("TEMP", "")) / "omp-production-smoke" / "fixture"
    prompts = Path(os.environ.get("TEMP", "")) / "omp-production-smoke" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    historical = Path(os.environ.get("TEMP", "")) / "omp-canary29g"
    prompt = prompts / "supervisor-prompt.txt"
    if not prompt.is_file():
        import shutil

        shutil.copyfile(historical / "supervisor-prompt.txt", prompt)

    preflight = run(
        [
            str(PYTHON), str(TOOLS / "preflight_run.py"),
            "--home", str(home), "--fixture", str(fixture),
            "--project-id", "omp-production-smoke",
            "--prod-db", str(REPO_ROOT.parent.parent / "db" / "brain.sqlite"),
            "--python", str(PYTHON), "--workdir", str(REPO_ROOT),
            "--out", str(pack / "smoke-preflight.json"),
        ],
        timeout=600,
    )

    spec = {
        "name": "production-smoke",
        "run_dir": str(pack / f"smoke-session{args.suffix}"),
        "home": str(home),
        "fixture": str(fixture),
        "prompt_file": str(prompt),
        "trace_file": str(pack / f"smoke{args.suffix}-boot.txt"),
        "profile": "canary-settlement",
        "bun": str(BUN),
        "cli": str(RETAL_CLI),
        "extension": [str(INSTALLED_EXTENSION / "index.ts")],
        "hashes_file": str(pack / "IDENTITIES-HASHES.txt"),
        "hashes_base": str(REPO_ROOT),
        "identities_file": str(args.identities),
        "python": str(PYTHON),
        "watcher_script": str(TOOLS / "db_watch.py"),
        "extra_env": {
            "SECOND_BRAIN_HOME": str(home),
            "SECOND_BRAIN_PYTHON": str(PYTHON),
            "OM_CANARY_FORCE_ISOLATED": "1",
            "OM_CANARY_ISOLATION": "1",
        },
        "hold_prefix": None,
        "coordinator": None,
        "timeout_seconds": args.timeout,
        "watcher_timeout_seconds": 1800,
        "watcher_ready_timeout_seconds": 30,
        "post_exit_grace_seconds": 3,
        "sessions_root": str(
            Path.home() / ".omp/profiles/canary-settlement/agent/sessions"
        ),
        "session_glob": "**/*.jsonl",
        "schema_expected": 24,
        "preflight_file": str(pack / "smoke-preflight.json"),
        "fixture_identity": {
            str(fixture / "calc.py"): sha256_file(fixture / "calc.py"),
            str(fixture / "test_calc.py"): sha256_file(fixture / "test_calc.py"),
        },
        "expect": {"state_1": True, "state_2": True, "child_exit": 0},
    }
    # The launcher rehashes every file in hashes_file before spawn; bind exactly
    # the files this run loads.
    bind_lines = [
        f"{sha256_file(RETAL_CLI)} {RETAL_CLI}",
        f"{sha256_file(INSTALLED_EXTENSION / 'index.ts')} "
        f"{INSTALLED_EXTENSION / 'index.ts'}",
    ]
    (pack / "IDENTITIES-HASHES.txt").write_text("\n".join(bind_lines) + "\n", encoding="utf-8")

    spec_path = pack / "smoke-spec.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    session = run(
        [str(PYTHON), str(TOOLS / "launch_run.py"), "--spec", str(spec_path)],
        timeout=args.timeout + 300,
    )
    post = run(
        [
            str(PYTHON), str(TOOLS / "post_exit_check.py"),
            "--home-db", str(home / "db" / "brain.sqlite"),
            "--prod-db", str(REPO_ROOT.parent.parent / "db" / "brain.sqlite"),
            "--out", str(pack / "smoke-post-exit.json"),
            "--fixture", str(fixture),
            "--python", str(PYTHON),
            "--trace", str(pack / f"smoke{args.suffix}-boot.txt"),
            "--label", "production-smoke",
        ],
        timeout=300,
    )
    summary = {
        "schema": "second-brain.omp-production-smoke.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "home": str(home),
        "fixture": str(fixture),
        "preflight_exit": preflight["exit_code"],
        "session_exit": session["exit_code"],
        "post_exit_exit": post["exit_code"],
        "session_stdout_tail": session["stdout_tail"],
        "session_stderr_tail": session["stderr_tail"],
    }
    (pack / "production-smoke.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "preflight_exit": preflight["exit_code"],
                "session_exit": session["exit_code"],
                "post_exit_exit": post["exit_code"],
            },
            indent=2,
        )
    )
    return 0 if session["exit_code"] == 0 and post["exit_code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
