"""Deterministic task oracles and normalized run-record construction."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OracleResult:
    passed: bool
    detail: str


def _file_text(workspace: Path, relative: str) -> str:
    path = (workspace / relative).resolve()
    if workspace.resolve() not in path.parents:
        raise ValueError(f"oracle path escapes workspace: {relative}")
    return path.read_text(encoding="utf-8")


def run_oracle(workspace: Path, oracle: dict[str, Any], response: str = "") -> OracleResult:
    """Evaluate a small safe oracle vocabulary; no shell commands are accepted."""
    kind = oracle.get("type")
    if kind == "response_equals":
        expected = str(oracle.get("text", ""))
        return OracleResult(response.strip() == expected, f"response_equals={expected!r}")
    if kind == "response_contains":
        expected = str(oracle.get("text", ""))
        return OracleResult(expected in response, f"response_contains={expected!r}")
    if kind == "file_contains":
        relative = str(oracle["path"])
        expected = str(oracle["text"])
        actual = _file_text(workspace, relative)
        return OracleResult(expected in actual, f"file_contains={relative!r}")
    if kind == "file_not_contains":
        relative = str(oracle["path"])
        forbidden = str(oracle["text"])
        actual = _file_text(workspace, relative)
        return OracleResult(forbidden not in actual, f"file_not_contains={relative!r}")
    if kind == "json_value":
        relative = str(oracle["path"])
        key = str(oracle["key"])
        actual = json.loads(_file_text(workspace, relative))
        return OracleResult(actual.get(key) == oracle.get("value"), f"json_value={key!r}")
    if kind == "all":
        children = [run_oracle(workspace, child, response) for child in oracle["items"]]
        return OracleResult(
            all(item.passed for item in children), "; ".join(item.detail for item in children)
        )
    raise ValueError(f"unknown deterministic oracle: {kind!r}")


def run_verifier(argv: list[str], cwd: Path, timeout_s: float = 30.0) -> OracleResult:
    """Run a predeclared argv verifier without invoking a shell."""
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
    detail = (completed.stdout + completed.stderr).strip()[-1000:]
    return OracleResult(completed.returncode == 0, detail)


def empty_record(**overrides: Any) -> dict[str, Any]:
    """Create the plan's normalized schema with null for unavailable data."""
    record: dict[str, Any] = {
        "run_id": None,
        "task_id": None,
        "task_family": None,
        "dataset": None,
        "condition": None,
        "model": None,
        "repo_id": None,
        "repo_commit": None,
        "brain_commit": None,
        "brain_snapshot": None,
        "order_index": None,
        "randomization_seed": None,
        "start_utc": None,
        "end_utc": None,
        "success": None,
        "score": None,
        "first_pass_success": None,
        "rework_iterations": None,
        "regressions": None,
        "critical_regressions": None,
        "wall_seconds": None,
        "tool_calls": None,
        "failed_tool_calls": None,
        "files_read": None,
        "files_touched": None,
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
        "peak_context_percent": None,
        "brain_retrieved_tokens": None,
        "brain_context_percent": None,
        "memories_considered": None,
        "memories_injected": None,
        "useful_memories": None,
        "irrelevant_memories": None,
        "stale_memories": None,
        "contradictions_surfaced": None,
        "skills_considered": None,
        "skills_selected": [],
        "skill_helpful": [],
        "skill_harmful": [],
        "episodes_created": [],
        "memories_changed": [],
        "promotions": [],
        "rollbacks": [],
        "verifier": None,
        "verifier_blinded": None,
        "oracle": None,
        "notes": "",
    }
    record.update(overrides)
    return record
