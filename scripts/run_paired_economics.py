"""Run paired economics tasks against an available host, using telemetry only."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from second_brain import economics, governor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "proof" / "tasks" / "economics"
RAW_DIR = ROOT / "outputs" / "reports" / "v2" / "economics" / "raw"
QUALIFICATION = ROOT / "outputs" / "reports" / "v2" / "v2-0" / "qualification.json"
HARNESS_EXECUTABLES = {"prime": "prime", "claude-code": "claude", "hermes": "hermes"}
MAX_PAIRS = 100


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def load_tasks() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        economics.validate_fixture(data)
        tasks.extend(data["tasks"])
    return tasks


def _telemetry_files(home: Path) -> set[Path]:
    path = home / "telemetry" / "agent-performance"
    return set(path.glob("*.jsonl")) if path.is_dir() else set()


def _wall_ms(path: Path) -> int | None:
    stamps: list[float] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line).get("ts")
                if isinstance(value, str):
                    stamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    except OSError:
        return None
    return round(max(stamps) - min(stamps)) if len(stamps) >= 2 else None

def _host_command(harness: str) -> list[str] | None:
    override = os.environ.get(f"SECOND_BRAIN_{harness.upper().replace('-', '_')}_COMMAND")
    if override:
        return shlex.split(override)
    executable = HARNESS_EXECUTABLES[harness]
    located = shutil.which(executable)
    if not located:
        return None
    return [located, "-p"] if harness == "claude-code" else [located]


def _run_host(command: list[str], prompt: str, worktree: Path, env: dict[str, str]) -> int | None:
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            cwd=worktree,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.returncode
def _acceptance(command: str, worktree: Path) -> bool | None:
    try:
        completed = subprocess.run(
            command,
            cwd=worktree,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.returncode == 0


def _run_one(harness: str, task: dict[str, Any], profile: str, command: list[str]) -> dict[str, Any] | None:
    run_id = f"{harness}-{task['task_id']}-{profile}-{_utc()}"
    with tempfile.TemporaryDirectory(prefix="second-brain-econ-") as temp:
        worktree = Path(temp) / "repo"
        telemetry_home = Path(temp) / "brain"
        added = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), task["repo_fixture_commit"]],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
        if added.returncode != 0:
            return None
        try:
            env = os.environ.copy()
            env.update(governor.get_profile_env(profile))
            env["SECOND_BRAIN_HOME"] = str(telemetry_home)
            before = _telemetry_files(telemetry_home)
            host_exit = _run_host(command, task["prompt"], worktree, env)
            after = sorted(
                _telemetry_files(telemetry_home) - before,
                key=lambda path: path.stat().st_mtime_ns,
            )
            telemetry = governor.parse_telemetry_session(after[-1]) if after else None
            acceptance_pass = _acceptance(task["acceptance"]["command"], worktree) if host_exit == 0 else None
            usage_capture = bool(
                telemetry
                and telemetry.model_turns > 0
                and (telemetry.input_tokens is not None or telemetry.output_tokens is not None)
            )
            config = economics.load_config(ROOT)
            dollars = None
            if telemetry is not None:
                if telemetry.cost_total_seen:
                    dollars = telemetry.cost_total
                elif telemetry.model:
                    dollars = economics.cost_per_run(
                        {
                            "input_tokens": telemetry.input_tokens,
                            "output_tokens": telemetry.output_tokens,
                            "cache_read_tokens": telemetry.cache_read_tokens,
                            "cache_write_tokens": telemetry.cache_write_tokens,
                        },
                        config.prices.get(telemetry.model),
                        multipliers={
                            "uncached_in": config.uncached_in,
                            "cache_read": config.cache_read,
                            "cache_write": config.cache_write,
                        },
                    )
            return {
                "run_id": run_id,
                "harness": harness,
                "task_id": task["task_id"],
                "profile": profile,
                "repo_fixture_commit": task["repo_fixture_commit"],
                "host_exit": host_exit,
                "usage_capture": usage_capture,
                "acceptance_pass": acceptance_pass,
                "telemetry": asdict(telemetry) if telemetry else None,
                "dollars": dollars,
                "wall_ms": _wall_ms(after[-1]) if after else None,
            }
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
            )

def _paired(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["task_id"], {})[record["profile"]] = record
    pairs = []
    for arms in grouped.values():
        if "OFF" not in arms or "ON" not in arms:
            continue
        off, on = arms["OFF"], arms["ON"]
        if not off["usage_capture"] or not on["usage_capture"]:
            continue
        def metrics(record: dict[str, Any]) -> dict[str, Any]:
            tel = record["telemetry"] or {}
            return {
                "tokens": tel.get("total_tokens"),
                "dollars": record.get("dollars"),
                "turns": tel.get("model_turns"),
                "wall_ms": record.get("wall_ms"),
                "pass": record.get("acceptance_pass"),
            }
        pairs.append({"off": metrics(off), "on": metrics(on)})
    return pairs


def run(harness: str, requested_profile: str, pair_count: int) -> dict[str, Any]:
    tasks = load_tasks()[:pair_count]
    command = _host_command(harness)
    records: list[dict[str, Any]] = []
    unavailable = command is None
    if command is not None:
        for task in tasks:
            for profile in ("OFF", "ON"):
                record = _run_one(harness, task, profile, command)
                if record is not None:
                    RAW_DIR.mkdir(parents=True, exist_ok=True)
                    (RAW_DIR / f"{record['run_id']}.json").write_text(
                        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
                    )
                    records.append(record)
    pairs = _paired(records)
    summary = {
        "harness": harness,
        "requested_profile": requested_profile,
        "requested_pairs": pair_count,
        "host_available": not unavailable,
        "usage_capture": bool(pairs),
        "pairs_recorded": len(pairs),
        "verdict": economics.verdict(pairs),
    }
    QUALIFICATION.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    try:
        loaded = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, json.JSONDecodeError):
        pass
    results = existing.get("results") if isinstance(existing.get("results"), list) else []
    results = [item for item in results if not isinstance(item, dict) or item.get("harness") != harness]
    results.append(summary)
    QUALIFICATION.write_text(
        json.dumps({"generated_at": datetime.now(UTC).isoformat(), "results": results}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded paired economics from host telemetry.")
    parser.add_argument("--harness", choices=sorted(HARNESS_EXECUTABLES), required=True)
    parser.add_argument("--profile", choices=("OFF", "ON"), required=True)
    parser.add_argument("--pairs", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.pairs <= MAX_PAIRS:
        parser.error(f"--pairs must be between 1 and {MAX_PAIRS}")
    print(json.dumps(run(args.harness, args.profile, args.pairs), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
