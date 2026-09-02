"""Run bounded paired economics tasks against real hosts, using telemetry only."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from second_brain import economics, governor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "proof" / "tasks" / "economics"
RAW_DIR = ROOT / "outputs" / "reports" / "v2" / "economics" / "raw"
QUALIFICATION = ROOT / "outputs" / "reports" / "v2" / "v2-0" / "qualification.json"
HARNESS_EXECUTABLES = {"prime": "prime", "claude-code": "claude", "hermes": "hermes"}
PROFILE_TO_ABLATION = {"OFF": "A_BRAIN_OFF", "ON": "I_FULL_V1"}
MAX_PAIRS = 100
_REQUIRED_USAGE = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens")


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def profile_env(profile: str) -> dict[str, str]:
    """Resolve the explicit OFF/ON profile mapping without a KeyError."""
    try:
        ablation = PROFILE_TO_ABLATION[profile]
    except KeyError as exc:
        raise ValueError(f"unknown economics profile: {profile}") from exc
    return governor.get_profile_env(ablation)


def load_tasks() -> list[dict[str, Any]]:
    """Load and validate the complete seven-class, two-task fixture set."""
    expected = {"MICRO", "STANDARD", "DEEP", "DEBUG", "RESEARCH", "REVIEW", "HANDOFF"}
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    if {path.stem for path in paths} != expected or len(paths) != 7:
        raise ValueError("economics fixtures must contain exactly seven class files")
    tasks: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        economics.validate_fixture(data)
        tasks.extend(data["tasks"])
    ids = [task["task_id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("economics task IDs must be unique")
    return tasks


def _telemetry_files(home: Path) -> set[Path]:
    path = home / "telemetry" / "agent-performance"
    return set(path.glob("*.jsonl")) if path.is_dir() else set()


def _parse_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def aggregate_telemetry(paths: Iterable[Path]) -> dict[str, Any]:
    """Aggregate all host telemetry files from one attempt, preserving nulls."""
    totals: dict[str, Any] = {field: 0 for field in _REQUIRED_USAGE}
    seen: dict[str, bool] = {field: False for field in _REQUIRED_USAGE}
    nulls: dict[str, bool] = {field: False for field in _REQUIRED_USAGE}
    models: set[str] = set()
    model: str | None = None
    model_turns = 0
    tool_calls = 0
    saw_event = False
    stamps: list[float] = []
    for path in sorted(paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            saw_event = True
            stamp = _parse_ts(record.get("ts"))
            if stamp is not None:
                stamps.append(stamp)
            kind = record.get("kind")
            if kind == "tool_call":
                tool_calls += 1
            if kind not in {"assistant_usage", "model_invocation_completed"}:
                continue
            usage = record if kind == "assistant_usage" else record.get("usage")
            if not isinstance(usage, dict):
                continue
            model_turns += 1
            if isinstance(record.get("model"), str):
                model = record["model"]
                models.add(model)
            for field in _REQUIRED_USAGE:
                if field not in usage or usage[field] is None:
                    nulls[field] = True
                elif isinstance(usage[field], int) and not isinstance(usage[field], bool):
                    seen[field] = True
                    totals[field] += usage[field]
                else:
                    nulls[field] = True
    for field in _REQUIRED_USAGE:
        totals[field] = None if nulls[field] or not seen[field] else totals[field]
    totals.update({
        "model": model,
        "models": sorted(models),
        "mixed_model": len(models) > 1,
        "model_turns": model_turns if saw_event else None,
        "tool_calls": tool_calls if saw_event else None,
        "wall_ms": round(max(stamps) - min(stamps)) if len(stamps) >= 2 else None,
    })
    return totals


def _host_command(harness: str) -> list[str] | None:
    override = os.environ.get(f"SECOND_BRAIN_{harness.upper().replace('-', '_')}_COMMAND")
    if override:
        return shlex.split(override)
    located = shutil.which(HARNESS_EXECUTABLES[harness])
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
            env.update(profile_env(profile))
            env["SECOND_BRAIN_HOME"] = str(telemetry_home)
            before = _telemetry_files(telemetry_home)
            host_exit = _run_host(command, task["prompt"], worktree, env)
            after = _telemetry_files(telemetry_home) - before
            telemetry = aggregate_telemetry(after)
            usage_capture = bool(
                telemetry["model_turns"]
                and all(telemetry[field] is not None for field in _REQUIRED_USAGE)
            )
            config = economics.load_config(ROOT)
            dollars = None
            dollars_reason = None
            if not usage_capture:
                dollars_reason = "missing_usage"
            elif telemetry["mixed_model"]:
                dollars_reason = "mixed_model"
            elif telemetry["model"]:
                dollars = economics.cost_per_run(
                    {field: telemetry[field] for field in _REQUIRED_USAGE[:4]},
                    config.prices.get(telemetry["model"]),
                    multipliers={
                        "uncached_in": config.uncached_in,
                        "cache_read": config.cache_read,
                        "cache_write": config.cache_write,
                    },
                )
                if dollars is None:
                    dollars_reason = "missing_or_null_price"
            acceptance_pass = _acceptance(task["acceptance"]["command"], worktree) if host_exit == 0 else None
            return {
                "run_id": run_id,
                "harness": harness,
                "task_id": task["task_id"],
                "profile": profile,
                "repo_fixture_commit": task["repo_fixture_commit"],
                "host_exit": host_exit,
                "dollars_reason": dollars_reason,
                "acceptance_pass": acceptance_pass,
                "telemetry": telemetry,
                "dollars": dollars,
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
        def metrics(record: dict[str, Any]) -> dict[str, Any]:
            tel = record.get("telemetry") or {}
            return {
                "tokens": tel.get("total_tokens"),
                "dollars": record.get("dollars"),
                "turns": tel.get("model_turns"),
                "wall_ms": tel.get("wall_ms"),
                "pass": record.get("acceptance_pass"),
            }
        pairs.append({"off": metrics(arms["OFF"]), "on": metrics(arms["ON"])})
    return pairs


def _write_qualification(summary: dict[str, Any]) -> None:
    existing: dict[str, Any] = {}
    try:
        loaded = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, json.JSONDecodeError):
        pass
    economics_section = existing.get("economics")
    economics_section = dict(economics_section) if isinstance(economics_section, dict) else {}
    economics_section[summary["harness"]] = summary
    existing["economics"] = economics_section
    results = existing.get("results")
    if isinstance(results, list):
        results = [item for item in results if not isinstance(item, dict) or item.get("harness") != summary["harness"]]
        results.append(summary)
        existing["results"] = results
    existing["generated_at"] = datetime.now(UTC).isoformat()
    QUALIFICATION.parent.mkdir(parents=True, exist_ok=True)
    QUALIFICATION.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")


def run(harness: str, requested_profile: str, pair_count: int) -> dict[str, Any]:
    tasks = load_tasks()[:pair_count]
    command = _host_command(harness)
    records: list[dict[str, Any]] = []
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
        "profile_mapping": PROFILE_TO_ABLATION,
        "requested_pairs": pair_count,
        "host_available": command is not None,
        "usage_capture": any(pair["off"]["tokens"] is not None and pair["on"]["tokens"] is not None for pair in pairs),
        "pairs_recorded": len(pairs),
        "verdict": economics.verdict(pairs, config=economics.load_config(ROOT)),
    }
    _write_qualification(summary)
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
