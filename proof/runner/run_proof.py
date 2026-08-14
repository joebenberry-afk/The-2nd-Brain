"""Run a small paired proof stage against predeclared JSON task fixtures."""

from __future__ import annotations

import argparse
import json
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .condition import Condition, pair_order, parse_condition
from .integrity import hash_tree
from .metrics import summarize
from .prime import run_prime
from .sanitize import sanitize_value
from .scoring import empty_record, run_oracle
from .workspace import copy_workspace


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", data) if isinstance(data, (dict, list)) else None
    if not isinstance(tasks, list) or not all(isinstance(item, dict) for item in tasks):
        raise ValueError(f"task file must contain a list or {{'tasks': [...]}}: {path}")
    return tasks


def _git_commit(path: Path) -> str | None:
    try:
        import subprocess

        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _telemetry_metrics(home: Path) -> dict[str, Any]:
    files = sorted((home / "telemetry" / "agent-performance").glob("*.jsonl"))
    records: list[dict[str, Any]] = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    records.append(item)
    contexts = [
        float(item["context_usage"]["percent"])
        for item in records
        if isinstance(item.get("context_usage"), dict)
        and isinstance(item["context_usage"].get("percent"), (int, float))
    ]
    tool_results = [item for item in records if item.get("kind") == "tool_result"]
    return {
        "tool_calls": sum(item.get("kind") == "tool_call" for item in records),
        "failed_tool_calls": sum(item.get("is_error") is True for item in tool_results),
        "peak_context_percent": max(contexts) if contexts else None,
        "telemetry_files": len(files),
        "session_shutdown": any(item.get("kind") == "session_shutdown" for item in records),
    }


def run_stage(
    *,
    task_file: Path,
    dataset: str,
    repo: Path,
    brain_home: Path,
    output: Path,
    conditions: list[Condition],
    seed: int,
    launcher: Path,
    extension: Path | None,
    model: str,
    thinking: str,
    offline: bool,
    timeout_s: float,
    limit: int | None = None,
) -> dict[str, Any]:
    task_file = task_file.resolve()
    repo = repo.resolve()
    brain_home = brain_home.resolve()
    output = output.resolve()
    launcher = launcher.resolve()
    extension = extension.resolve() if extension is not None else None
    tasks = [task for task in _load_tasks(task_file) if task.get("dataset", dataset) == dataset]
    if limit is not None:
        tasks = tasks[:limit]
    if not tasks:
        raise ValueError(f"no {dataset} tasks in {task_file}")
    if dataset == "holdout":
        raise RuntimeError("holdout execution is disabled until a frozen hash is supplied")
    output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    repo_commit = _git_commit(repo)
    with tempfile.TemporaryDirectory(prefix="second-brain-proof-") as temporary:
        temporary_root = Path(temporary)
        for task in tasks:
            task_id = str(task["task_id"])
            order = (
                conditions
                if len(conditions) < 2
                else pair_order(conditions[0], conditions[1], task_id, seed)
            )
            for order_index, condition in enumerate(order, start=1):
                workspace = copy_workspace(repo, temporary_root / f"{task_id}-{condition.value}")
                run_home = temporary_root / f"brain-{task_id}-{condition.value}"
                copy_workspace(brain_home, run_home)
                sessions = temporary_root / f"sessions-{task_id}-{condition.value}"
                start = _utc()
                result = run_prime(
                    condition=condition,
                    prompt=str(task["prompt"]),
                    cwd=workspace,
                    brain_home=run_home,
                    launcher=launcher,
                    model=model,
                    thinking=thinking,
                    extension=extension,
                    session_dir=sessions,
                    timeout_s=timeout_s,
                    offline=offline,
                )
                telemetry = _telemetry_metrics(run_home)
                oracle = run_oracle(workspace, dict(task["oracle"]), result.stdout)
                notes = (result.stderr or "")[-1000:]
                if condition is Condition.C1_OBSERVABILITY and (
                    telemetry["telemetry_files"] != 1 or not telemetry["session_shutdown"]
                ):
                    notes += " telemetry_integrity_failure"
                record = empty_record(
                    run_id=str(uuid.uuid4()),
                    task_id=task_id,
                    task_family=task.get("task_family"),
                    dataset=dataset,
                    condition=condition.value,
                    model=model,
                    repo_id=str(repo.resolve()),
                    repo_commit=repo_commit,
                    brain_commit=_git_commit(brain_home),
                    brain_snapshot=hash_tree(run_home),
                    order_index=order_index,
                    randomization_seed=seed,
                    start_utc=start,
                    end_utc=_utc(),
                    success=bool(result.exit_code == 0 and not result.timed_out and oracle.passed),
                    score=1.0 if oracle.passed else 0.0,
                    first_pass_success=bool(oracle.passed),
                    rework_iterations=0,
                    tool_calls=telemetry["tool_calls"],
                    failed_tool_calls=telemetry["failed_tool_calls"],
                    peak_context_percent=telemetry["peak_context_percent"],
                    wall_seconds=result.wall_seconds,
                    verifier="deterministic-oracle",
                    verifier_blinded=True,
                    oracle=oracle.detail,
                    notes=notes,
                )
                records.append(
                    sanitize_value(record, {"repo": str(repo), "brain": str(brain_home)})
                )
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return {"records": len(records), "summary": summarize(records), "output": str(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument(
        "--dataset", default="training", choices=("training", "calibration", "holdout")
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--brain-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--condition", action="append", required=True)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--extension", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--thinking", default="minimal")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    conditions = [parse_condition(value) for value in args.condition]
    if len(conditions) not in (1, 2):
        parser.error("provide one condition or exactly two paired conditions")
    result = run_stage(
        task_file=args.tasks,
        dataset=args.dataset,
        repo=args.repo,
        brain_home=args.brain_home,
        output=args.output,
        conditions=conditions,
        seed=args.seed,
        launcher=args.launcher,
        extension=args.extension,
        model=args.model,
        thinking=args.thinking,
        offline=args.offline,
        timeout_s=args.timeout_s,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
