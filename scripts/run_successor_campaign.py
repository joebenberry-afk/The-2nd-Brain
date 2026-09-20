"""Run the bounded successor qualification campaign against a staged layout.

Steps, in order (each writes its evidence into ``--out``):

1. ``preflight``   - create the disposable Brain home and fixture, register the
                     project, prove the fixture starts red, snapshot the home
                     configuration manifest;
2. ``session-1``   - isolated worker A admitted, B refused while A holds the
                     writer, patch applied, terminal receipt with settlement and
                     cleanup, release;
3. ``post-exit-1`` - independent read-only checks (fixture green, receipt
                     sequences contiguous, production checksums unchanged);
4. ``session-2``   - isolated successor admitted against the released baseline;
5. ``post-exit-2`` - the same independent checks.

Nothing outside ``--stage`` and ``--out`` is written: the child's user root is
redirected into the stage (``USERPROFILE``/``HOME``), the Brain home, fixture,
profile session store, run directories and traces are all disposable, and the
production database is opened read-only for comparison only.

    python scripts/run_successor_campaign.py --stage %TEMP%/omp-successor-.../staged \
        --out outputs/reports/omp-successor-qualification-<stamp> --all
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "scripts" / "omp-canary"
PYTHON = Path(sys.executable)
BUN = Path.home() / ".bun" / "bin" / "bun.exe"
SUCCESSOR_DIR = REPO_ROOT / "docs" / "integrations" / "omp-host-patch-2026-09-19-successor"
HISTORICAL_PROMPTS = Path(os.environ.get("TEMP", "")) / "omp-canary29g"
PROD_DB = REPO_ROOT.parent.parent / "db" / "brain.sqlite"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    return env


def run(command: list[str], label: str, timeout: float | None = None) -> dict:
    started = time.time()
    process = subprocess.run(
        command, capture_output=True, text=True, env=clean_env(), timeout=timeout
    )
    return {
        "label": label,
        "argv": command,
        "exit_code": process.returncode,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
        "seconds": round(time.time() - started, 2),
    }


def stage_paths(stage: Path) -> dict:
    manifest = json.loads((stage / "STAGE-MANIFEST.json").read_text(encoding="utf-8"))
    return {
        "root": stage,
        "manifest": manifest,
        "host": Path(manifest["host"]["package"]),
        "extension": stage / "extension",
        "userhome": Path(manifest["user_root"]["root"]),
        "brain_home": stage / "brain-home",
        "fixture": stage / "fixture",
        "prompts": stage / "prompts",
    }


def prepare_prompts(paths: dict) -> dict[str, Path]:
    prompts = paths["prompts"]
    prompts.mkdir(parents=True, exist_ok=True)
    copied = {}
    for source_name, target_name in (
        ("supervisor-prompt.txt", "supervisor-prompt.txt"),
        ("supervisor-c-prompt.txt", "supervisor-c-prompt.txt"),
    ):
        source = HISTORICAL_PROMPTS / source_name
        target = prompts / target_name
        if not target.is_file():
            shutil.copyfile(source, target)
        copied[target_name] = target
    return copied


def base_spec(paths: dict, out_dir: Path, name: str) -> dict:
    userhome = paths["userhome"]
    return {
        "name": name,
        "run_dir": str(out_dir / name),
        "home": str(paths["brain_home"]),
        "fixture": str(paths["fixture"]),
        "prompt_file": str(paths["prompts"] / "supervisor-prompt.txt"),
        "trace_file": str(out_dir / f"{name}-boot.txt"),
        "profile": "canary-settlement",
        "bun": str(BUN),
        "cli": str(paths["host"] / "src" / "cli.ts"),
        "extension": [str(paths["extension"] / "index.ts")],
        "hashes_file": str(SUCCESSOR_DIR / "HASHES.txt"),
        "hashes_base": str(paths["root"]),
        "identities_file": str(SUCCESSOR_DIR / "RUN-IDENTITIES.json"),
        "python": str(PYTHON),
        "watcher_script": str(TOOLS / "db_watch.py"),
        "extra_env": {
            "SECOND_BRAIN_HOME": str(paths["brain_home"]),
            "SECOND_BRAIN_PYTHON": str(PYTHON),
            "OM_CANARY_FORCE_ISOLATED": "1",
            "OM_CANARY_ISOLATION": "1",
            "USERPROFILE": str(userhome),
            "HOME": str(userhome),
        },
        "hold_prefix": None,
        "coordinator": None,
        "timeout_seconds": 900,
        "watcher_timeout_seconds": 1800,
        "watcher_ready_timeout_seconds": 30,
        "post_exit_grace_seconds": 3,
        "sessions_root": str(
            userhome / ".omp" / "profiles" / "canary-settlement" / "agent" / "sessions"
        ),
        "session_glob": "**/*.jsonl",
        "schema_expected": 24,
        "expect": {"state_1": True, "state_2": True, "child_exit": 0},
    }


def fixture_identity(paths: dict) -> dict[str, str]:
    identity: dict[str, str] = {}
    for name in ("calc.py", "test_calc.py"):
        digest = sha256_file(paths["fixture"] / name)
        if digest is None:
            raise SystemExit(f"fixture file missing before launch: {paths['fixture'] / name}")
        identity[str(paths["fixture"] / name)] = digest
    return identity


def preflight(paths: dict, out_dir: Path) -> dict:
    record = run(
        [
            str(PYTHON),
            str(TOOLS / "preflight_run.py"),
            "--home",
            str(paths["brain_home"]),
            "--fixture",
            str(paths["fixture"]),
            "--project-id",
            "omp-successor-bounded",
            "--prod-db",
            str(PROD_DB),
            "--python",
            str(PYTHON),
            "--workdir",
            str(REPO_ROOT),
            "--out",
            str(out_dir / "preflight.json"),
        ],
        "preflight",
        timeout=600,
    )
    return record


def launch(out_dir: Path, spec: dict, label: str) -> dict:
    spec_path = out_dir / f"{label}-spec.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return run(
        [
            str(PYTHON),
            str(TOOLS / "launch_run.py"),
            "--spec",
            str(spec_path),
        ],
        label,
        timeout=spec["timeout_seconds"] + 300,
    )


def post_exit(paths: dict, out_dir: Path, session_name: str) -> dict:
    return run(
        [
            str(PYTHON),
            str(TOOLS / "post_exit_check.py"),
            "--home-db",
            str(paths["brain_home"] / "db" / "brain.sqlite"),
            "--prod-db",
            str(PROD_DB),
            "--out",
            str(out_dir / f"post-exit-{session_name}.json"),
            "--fixture",
            str(paths["fixture"]),
            "--python",
            str(PYTHON),
            "--trace",
            str(out_dir / f"{session_name}-boot.txt"),
            "--label",
            f"successor-{session_name}",
        ],
        f"post-exit-{session_name}",
        timeout=300,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--steps",
        default="all",
        help="comma-separated subset of: preflight,session-1,post-exit-1,session-2,post-exit-2",
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="attempt suffix appended to run names, so a re-run never reuses a run directory",
    )
    args = parser.parse_args()

    paths = stage_paths(args.stage)
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    prepare_prompts(paths)
    steps = (
        ["preflight", "session-1", "post-exit-1", "session-2", "post-exit-2"]
        if args.steps == "all"
        else [step.strip() for step in args.steps.split(",") if step.strip()]
    )

    summary_path = out_dir / "campaign-summary.json"
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.is_file()
        else {
            "schema": "second-brain.omp-successor-campaign.v1",
            "started_at": datetime.now(UTC).isoformat(),
            "stage": str(args.stage),
            "steps": [],
        }
    )

    for step in steps:
        if step == "preflight":
            record = preflight(paths, out_dir)
        elif step == "session-1":
            name = f"session-1{args.suffix}"
            spec = base_spec(paths, out_dir, name)
            spec["fixture_identity"] = fixture_identity(paths)
            spec["preflight_file"] = str(out_dir / "preflight.json")
            record = launch(out_dir, spec, name)
        elif step == "session-2":
            name = f"session-2{args.suffix}"
            spec = base_spec(paths, out_dir, name)
            spec["prompt_file"] = str(paths["prompts"] / "supervisor-c-prompt.txt")
            spec["fixture_identity"] = fixture_identity(paths)
            spec["preflight_file"] = str(out_dir / "preflight.json")
            record = launch(out_dir, spec, name)
        elif step.startswith("post-exit-"):
            which = step.replace("post-exit-", "")
            record = post_exit(paths, out_dir, f"session-{which}{args.suffix}")
        summary["steps"].append(record)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: record[k] for k in ("label", "exit_code", "seconds")}, indent=2))

    summary["finished_at"] = datetime.now(UTC).isoformat()
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
