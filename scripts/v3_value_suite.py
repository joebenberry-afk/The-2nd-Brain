"""V3 agent-experience value suite: does Brain reduce total agent work at equal quality?

Value, not delivery. Two classes of dev-grade tasks live in
``outputs/reports/v3-agent-experience/value/tasks.jsonl``:

- ``memory``     - a live-corpus memory (or several) answers the task outright; a
                   native agent can still succeed by hunting the repository.
- ``no_benefit`` - self-contained work where no stored memory can help.

Arms (one host process per run, fresh Brain home, fresh repository copy as cwd):

- ``native``    - ``--no-extensions``: the host as shipped.
- ``v3``        - ``--no-extensions -e <worktree>/brainstem/omp-v3/index.ts`` against a fresh copy
                  of the snapshot home plus the worktree's ``records/`` and ``projects/``, with
                  views compiled and the run's cwd mapped to the project (agent-native V3).
- ``candidate`` - ``--no-extensions -e <worktree>/brainstem/prime-extension/src/index.ts``
                  with a disposable snapshot home carrying the candidate's shipped
                  ``config/``, ``SECOND_BRAIN_PYTHON=<worktree venv>``,
                  ``SECOND_BRAIN_PROJECT=second-brain``.
- ``m00``       - optional: installed production extension + production interpreter
                  against the live snapshot config (baseline for regression reading).

Every run records correctness (deterministic regex check on the final answer), the
provider usage the host reported, the number of model requests, tool calls by name -
the parent's from the event stream, subagents' from their session files - wall time,
Brain-visible characters, and per-memory deliveries read from the run's own home.
Unknown usage stays null, never 0. Failures are retained, never retried.

Usage:
    python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value/smoke \
        --reps 1 --tasks VG-M05,VG-N02
    python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value \
        --reps 3 --arms native,candidate
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
CANONICAL_HOME = WORKTREE.parents[1] if WORKTREE.parent.name == ".worktrees" else WORKTREE
DEFAULT_TASKS = WORKTREE / "outputs/reports/v3-agent-experience/value/tasks.jsonl"
CLASSES = ("memory", "no_benefit")
ARM_CHOICES = ("native", "candidate", "m00", "v3")
USAGE_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "reasoningTokens")
BRAIN_CUSTOM_PREFIX = "brain."
#: The custom-message type the extension uses for the injected memory packet.
INJECTED_CONTEXT_CUSTOM_TYPE = "brain.autoinject.packet"
# Custom messages that carry memory into the model: the legacy packet and the V3 brief.
INJECTED_CONTEXT_CUSTOM_TYPES = frozenset({INJECTED_CONTEXT_CUSTOM_TYPE, "brain.v3.brief"})

#: Directories never copied into a run's cwd. ``memory``/``db``/``state``/``telemetry``
#: are the Brain's own store (a run must not read answers out of the database it is
#: being measured against); ``outputs/reports/v3-s2`` holds the frozen held-out set
#: and is off limits by contract.
REPO_EXCLUDE_DIRS = (
    ".venv",
    ".git",
    ".worktrees",
    "node_modules",
    "__pycache__",
    ".hypothesis",
    ".pytest_cache",
    ".ruff_cache",
    "db",
    "state",
    "telemetry",
    "memory",
    "outputs/reports/v3-s2",
    "outputs/reports/v3-agent-experience",
)

PASS_RULE = (
    "Memory tasks pass when the candidate shows a net reduction over native in either "
    "total provider tokens (input+output) or total tool calls - paired per task, median of "
    "the candidate-minus-native deltas < 0 - with candidate correctness not below native. "
    "No-benefit tasks pass when the paired median delta for BOTH tokens and tool calls is "
    "<= 0 plus the configured slack, with candidate correctness not below native. "
    "The campaign passes only when both classes pass."
)


# ---------------------------------------------------------------------------
# Reused harness helpers (scripts/v3_matched_arms.py) and small utilities
# ---------------------------------------------------------------------------


def _arms() -> Any:
    spec = importlib.util.spec_from_file_location(
        "v3_matched_arms", WORKTREE / "scripts" / "v3_matched_arms.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_env() -> dict[str, str]:
    """Environment without the machine's known-bad Python variables."""
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}


def sha256_file(path: Path, *, normalize_newlines: bool = False) -> str:
    return str(_arms()._sha256(path, normalize_newlines=normalize_newlines))


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def load_tasks(path: Path) -> list[dict[str, Any]]:
    """Read the task file: one JSON object per line (id, class, prompt, check.groups)."""
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        check = obj.get("check") or {}
        groups = [[str(alt) for alt in group] for group in (check.get("groups") or [])]
        if not groups or any(not group for group in groups):
            raise ValueError(f"{path}:{number}: every task needs non-empty check.groups")
        klass = str(obj["class"])
        if klass not in CLASSES:
            raise ValueError(f"{path}:{number}: unknown class {klass!r}")
        task_id = str(obj["id"])
        if task_id in seen:
            raise ValueError(f"{path}:{number}: duplicate id {task_id!r}")
        seen.add(task_id)
        tasks.append(
            {
                "id": task_id,
                "class": klass,
                "prompt": str(obj["prompt"]),
                "memory_ids": [str(m) for m in obj.get("memory_ids") or []],
                "groups": groups,
                "note": str(obj.get("note") or ""),
            }
        )
    return tasks


def select_tasks(tasks: Sequence[dict[str, Any]], ids: str, classes: str) -> list[dict[str, Any]]:
    wanted_ids = [item for item in (ids or "").split(",") if item]
    wanted_classes = [item for item in (classes or "").split(",") if item]
    selected = [
        task
        for task in tasks
        if (not wanted_ids or task["id"] in wanted_ids)
        and (not wanted_classes or task["class"] in wanted_classes)
    ]
    if wanted_ids:
        missing = sorted(set(wanted_ids) - {task["id"] for task in selected})
        if missing:
            raise ValueError(f"unknown task ids: {', '.join(missing)}")
    if not selected:
        raise ValueError("task selection is empty")
    return selected


# ---------------------------------------------------------------------------
# Scoring surface (unit-tested; no host involved)
# ---------------------------------------------------------------------------


def answer_matches(text: str, groups: Sequence[Sequence[str]]) -> dict[str, Any]:
    """Every group must be matched by at least one of its alternatives (case-insensitive)."""
    missing: list[list[str]] = []
    for group in groups:
        if not any(re.search(pattern, text, re.IGNORECASE) for pattern in group):
            missing.append(list(group))
    return {"ok": not missing and bool(text.strip()), "missing_groups": missing}


def answer_blocks(messages: Sequence[str]) -> str:
    """The final answer to check: the last non-empty assistant text block."""
    for text in reversed(list(messages)):
        if text.strip():
            return text
    return ""


def run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    """The scalar metrics a paired comparison uses; null when the host never reported it."""
    usage = run.get("provider_usage") or {}
    inp, out = usage.get("input"), usage.get("output")
    # Numeric, not int: a merged subagent total is a real measurement whatever its type.
    tokens = (
        inp + out if isinstance(inp, (int, float)) and isinstance(out, (int, float)) else None
    )
    return {
        "tokens_in_out": tokens,
        "tokens_all": usage.get("tokens_all"),
        "tool_calls": run.get("tool_calls_total"),
        "model_requests": run.get("model_requests"),
        "correct": bool(run.get("correct")),
    }


def paired_deltas(
    runs: Sequence[dict[str, Any]],
    tasks: Sequence[dict[str, Any]],
    arms: Sequence[str],
    accessor: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    """Per task: median of each arm over reps, and the candidate-minus-native delta."""
    native, candidate = arms[0], arms[1] if len(arms) > 1 else arms[0]
    rows: list[dict[str, Any]] = []
    for task in tasks:
        row: dict[str, Any] = {"task": task["id"], "class": task["class"]}
        for arm in (native, candidate):
            values = [
                accessor(run)
                for run in runs
                if run.get("task") == task["id"] and run.get("arm") == arm
            ]
            usable = [value for value in values if isinstance(value, (int, float))]
            row[f"{arm}_values"] = values
            row[f"{arm}_median"] = float(statistics.median(usable)) if usable else None
            row[f"{arm}_runs"] = len(values)
            row[f"{arm}_complete"] = len(usable) == len(values) and bool(values)
        base, arm_value = row[f"{native}_median"], row[f"{candidate}_median"]
        row["delta"] = (
            float(arm_value - base)
            if isinstance(base, (int, float)) and isinstance(arm_value, (int, float))
            else None
        )
        row["paired"] = row["delta"] is not None
        rows.append(row)
    return rows


def deltas_of(rows: Sequence[dict[str, Any]]) -> list[float]:
    return [float(row["delta"]) for row in rows if isinstance(row.get("delta"), (int, float))]


def bootstrap_ci(
    values: Sequence[float], seed: int, iters: int = 2000, alpha: float = 0.05
) -> list[float] | None:
    """Percentile bootstrap CI of the median; None when fewer than two values."""
    usable = [float(value) for value in values]
    if len(usable) < 2:
        return None
    rng = random.Random(seed)
    n = len(usable)
    medians = sorted(
        statistics.median([usable[rng.randrange(n)] for _ in range(n)]) for _ in range(iters)
    )
    low = medians[max(0, int((alpha / 2) * iters) - 1)]
    high = medians[min(iters - 1, int((1 - alpha / 2) * iters))]
    return [float(low), float(high)]


def correctness_rate(runs: Sequence[dict[str, Any]], arm: str) -> dict[str, Any]:
    rows = [run for run in runs if run.get("arm") == arm]
    ok = [run for run in rows if run.get("correct")]
    graded = [run for run in rows if run.get("status") == "ok"]
    return {
        "runs": len(rows),
        "graded": len(graded),
        "correct": len(ok),
        "rate": round(len(ok) / len(rows), 4) if rows else None,
    }


def class_summary(
    runs: Sequence[dict[str, Any]],
    tasks: Sequence[dict[str, Any]],
    arms: Sequence[str],
    seed: int,
    bootstrap_iters: int,
) -> dict[str, Any]:
    """Paired class table for the two campaign metrics plus correctness."""
    out: dict[str, Any] = {}
    for klass in CLASSES:
        class_tasks = [task for task in tasks if task["class"] == klass]
        if not class_tasks:
            continue
        entry: dict[str, Any] = {"tasks": [task["id"] for task in class_tasks]}
        # Correctness is a per-class statement: the pass rule reads one class's rate
        # against that same class's rate, never the campaign-wide average.
        class_ids = {task["id"] for task in class_tasks}
        class_runs = [run for run in runs if run.get("task") in class_ids]
        for metric in ("tokens_in_out", "tool_calls"):
            rows = paired_deltas(
                runs, class_tasks, arms, lambda run, metric=metric: run_metrics(run)[metric]
            )
            deltas = deltas_of(rows)
            entry[metric] = {
                "metric": metric,
                "paired_tasks": len(deltas),
                "unpaired_tasks": [row["task"] for row in rows if not row["paired"]],
                "median_delta": float(statistics.median(deltas)) if deltas else None,
                "median_native": _median_of(rows, f"{arms[0]}_median"),
                "median_candidate": _median_of(rows, f"{arms[1]}_median"),
                "ci": bootstrap_ci(deltas, seed, bootstrap_iters),
                "per_task": [
                    {
                        "task": row["task"],
                        "native_median": row[f"{arms[0]}_median"],
                        "candidate_median": row[f"{arms[1]}_median"],
                        "delta": row["delta"],
                    }
                    for row in rows
                ],
            }
        entry["correctness"] = {
            arm: correctness_rate(class_runs, arm) for arm in arms
        }
        out[klass] = entry
    return out


def _median_of(rows: Sequence[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    return float(statistics.median(values)) if values else None


def evaluate_pass_rule(
    summary: dict[str, Any],
    arms: Sequence[str],
    slack_tokens: float = 0.0,
    slack_tool_calls: float = 0.0,
) -> dict[str, Any]:
    """Apply the stated pass rule to a class summary; reasons are printer-ready."""
    reasons: list[str] = []
    verdict: dict[str, Any] = {"pass_rule": PASS_RULE, "slack": {
        "tokens": slack_tokens, "tool_calls": slack_tool_calls}}
    for klass, slack in (("memory", None), ("no_benefit", (slack_tokens, slack_tool_calls))):
        entry = summary.get(klass)
        if not entry:
            verdict[klass] = {"pass": False, "reasons": [f"class {klass} not measured"]}
            reasons.append(f"{klass}: not measured")
            continue
        tokens = entry["tokens_in_out"]["median_delta"]
        calls = entry["tool_calls"]["median_delta"]
        native_rate = entry["correctness"][arms[0]]["rate"]
        candidate_rate = entry["correctness"][arms[1]]["rate"]
        non_inferior = (
            native_rate is not None and candidate_rate is not None and candidate_rate >= native_rate
        )
        missing = [metric for metric, value in (("tokens", tokens), ("tool_calls", calls))
                   if value is None]
        if missing or not non_inferior:
            passed = False
        elif slack is None:
            passed = bool((tokens < 0) or (calls < 0))
        else:
            passed = bool(tokens <= slack[0] and calls <= slack[1])
        entry_reasons: list[str] = []
        if missing:
            entry_reasons.append(f"unpaired metrics: {', '.join(missing)}")
        if not non_inferior:
            entry_reasons.append(
                f"correctness {candidate_rate} below native {native_rate}"
            )
        if not entry_reasons and slack is None and not passed:
            entry_reasons.append(
                f"no reduction: median delta tokens={tokens}, tool_calls={calls}"
            )
        if not entry_reasons and slack is not None and not passed:
            entry_reasons.append(
                f"measurable increase: median delta tokens={tokens}, tool_calls={calls} "
                f"against slack {slack}"
            )
        verdict[klass] = {"pass": passed, "reasons": entry_reasons}
        reasons.append(f"{klass}: {'pass' if passed else 'fail'}")
    verdict["pass"] = all(verdict[klass]["pass"] for klass in CLASSES if klass in verdict)
    verdict["reasons"] = reasons
    return verdict


# ---------------------------------------------------------------------------
# Host-stream and session reading
# ---------------------------------------------------------------------------


def _iter_events(raw: str) -> Any:
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def assistant_text_blocks(raw: str) -> list[str]:
    """Text of every assistant message the host streamed, in order."""
    blocks: list[str] = []
    for event in _iter_events(raw):
        if event.get("type") != "message_end":
            continue
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            blocks.append(content)
            continue
        if not isinstance(content, list):
            continue
        text = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
        if text.strip():
            blocks.append(text)
    return blocks


def stream_tool_calls(raw: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in _iter_events(raw):
        if event.get("type") != "tool_execution_start":
            continue
        name = str(event.get("toolName") or "")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


def stream_custom_messages(raw: str) -> list[dict[str, Any]]:
    """Brain-authored custom messages (deduped: the host emits start and end)."""
    seen: dict[tuple[str, int], None] = {}
    out: list[dict[str, Any]] = []
    for event in _iter_events(raw):
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "custom":
            continue
        custom_type = str(message.get("customType") or "")
        if not custom_type.startswith(BRAIN_CUSTOM_PREFIX):
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        key = (custom_type, len(text))
        if key in seen:
            continue
        seen[key] = None
        out.append(
            {
                "customType": custom_type,
                "chars": len(text),
                "text_head": text[:4000],
                "memory_ids": sorted(set(re.findall(r"mem-[0-9a-f]{12}", text))),
            }
        )
    return out


def session_inventory(session_dir: Path) -> dict[str, Any]:
    """Usage, tool calls and roles of every session file under one run's session dir.

    The parent session is streamed on stdout as well, so the summary separates root
    files (``root: true``) from subagent files: subagent usage and tool calls are the
    only ones taken from disk, which keeps the total free of double counting.
    """
    files = sorted(session_dir.rglob("*.jsonl")) if session_dir.is_dir() else []
    sessions: list[dict[str, Any]] = []
    for path in files:
        usage: dict[str, int] = {}
        reported: dict[str, int] = {}
        tool_calls: dict[str, int] = {}
        cost = 0.0
        cost_reported = 0
        assistant_messages = 0
        root = True
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            kind = record.get("type")
            if kind == "session":
                root = "parentSession" not in record
                continue
            if kind != "message":
                continue
            message = record.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            assistant_messages += 1
            fields = message.get("usage")
            if isinstance(fields, dict):
                for field in USAGE_FIELDS:
                    value = fields.get(field)
                    if isinstance(value, int) and not isinstance(value, bool):
                        usage[field] = usage.get(field, 0) + value
                        reported[field] = reported.get(field, 0) + 1
                total = fields.get("cost")
                if isinstance(total, dict) and isinstance(total.get("total"), (int, float)):
                    cost += float(total["total"])
                    cost_reported += 1
            for part in message.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "toolCall":
                    name = str(part.get("name") or "")
                    if name:
                        tool_calls[name] = tool_calls.get(name, 0) + 1
        sessions.append(
            {
                "file": path.relative_to(session_dir).as_posix(),
                "root": root,
                "assistant_messages": assistant_messages,
                "tool_calls": tool_calls,
                "usage": {field: usage.get(field) for field in USAGE_FIELDS},
                "usage_reported": {field: reported.get(field, 0) for field in USAGE_FIELDS},
                "cost_reported": cost_reported,
                "cost_total": round(cost, 8) if cost_reported else None,
            }
        )
    subagents = [session for session in sessions if not session["root"]]

    def complete(session: dict[str, Any], reported: int) -> bool:
        """True when every assistant message of a child request reported that counter."""
        return session["assistant_messages"] > 0 and session["assistant_messages"] == reported

    merged: dict[str, Any] = {}
    for field in USAGE_FIELDS:
        if subagents and all(
            complete(session, session["usage_reported"][field]) for session in subagents
        ):
            merged[field] = sum(int(session["usage"][field]) for session in subagents)
        else:
            # One child request that never reported the field makes the total unknown;
            # summing only the children that did would understate the arm's real usage.
            merged[field] = None
    calls: dict[str, int] = {}
    for session in subagents:
        for name, count in session["tool_calls"].items():
            calls[name] = calls.get(name, 0) + count
    cost_total = (
        round(sum(float(session["cost_total"]) for session in subagents), 8)
        if subagents and all(complete(session, session["cost_reported"]) for session in subagents)
        else None
    )
    return {
        "files": len(sessions),
        "root_files": sum(1 for session in sessions if session["root"]),
        "subagent_files": len(subagents),
        "sessions": sessions,
        "subagent_usage": merged,
        "subagent_tool_calls": calls,
        "subagent_tool_calls_total": sum(calls.values()),
        "subagent_assistant_messages": sum(
            session["assistant_messages"] for session in subagents
        ),
        "subagent_cost_total": cost_total,
    }


def reset_home_deliveries(home: Path) -> dict[str, Any]:
    """Clear the snapshot's delivery history so every run starts with a clean ledger.

    The snapshot carries the live home's past deliveries, which would otherwise be
    counted as this run's own work (and could mask a run that delivered nothing).
    Retrieval counts and heat stay: they are corpus state, not per-run bookkeeping.
    """
    db = home / "db" / "brain.sqlite"
    if not db.is_file():
        return {"available": False, "deleted": 0}
    con = sqlite3.connect(db)
    try:
        before = con.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
        con.execute("DELETE FROM deliveries")
        con.commit()
    finally:
        con.close()
    return {"available": True, "deleted": int(before)}


def read_deliveries(home: Path, memory_ids: Sequence[str]) -> dict[str, Any]:
    """Per-memory deliveries this run's own home recorded (parent and subagents)."""
    db = home / "db" / "brain.sqlite"
    if not db.is_file():
        return {
            "available": False,
            "rows": 0,
            "per_memory": {},
            "expected": {m: 0 for m in memory_ids},
        }
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT memory_id, root_session_id, agent_session_id, delivered_at FROM deliveries"
        ).fetchall()
    finally:
        con.close()
    per_memory: dict[str, int] = {}
    sessions: set[str] = set()
    for memory_id, _root, agent, _at in rows:
        per_memory[str(memory_id)] = per_memory.get(str(memory_id), 0) + 1
        sessions.add(str(agent))
    return {
        "available": True,
        "rows": len(rows),
        "per_memory": per_memory,
        "expected": {m: per_memory.get(m, 0) for m in memory_ids},
        "agent_sessions": sorted(sessions),
    }


# ---------------------------------------------------------------------------
# Corpus, home and cwd preparation
# ---------------------------------------------------------------------------


def _repo_ignore(source: Path, excludes: Sequence[str]) -> Callable[[str, list[str]], set[str]]:
    """Ignore exactly the excluded relative paths (and bytecode) in a copytree walk."""
    excluded = {Path(rel).as_posix() for rel in excludes}
    root = source.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        try:
            rel = Path(directory).resolve().relative_to(root)
        except ValueError:
            return set()
        skip = {
            name
            for name in names
            if (rel / name).as_posix() in excluded or name.endswith(".pyc")
        }
        return skip

    return ignore


def copy_repo(source: Path, dest: Path, excludes: Sequence[str]) -> dict[str, Any]:
    """Copy the repository (minus Brain state and the held-out set) into a run cwd.

    The source is a live checkout, so a locked file must not sink a run: robocopy is
    tried first (it reports exit codes 8-15 for partial copies), and any partial or
    failed copy falls back to ``shutil.copytree`` with the same exclusion set. The
    fallback records how many entries it could not read.
    """
    dest.mkdir(parents=True, exist_ok=True)
    absolute = [str(source / rel) for rel in excludes]
    method = "robocopy" if os.name == "nt" else "copytree"
    returncode: int | None = None
    fallback: dict[str, Any] | None = None
    if os.name == "nt":
        argv = [
            "robocopy",
            str(source),
            str(dest),
            "/E",
            "/MT:16",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
            "/R:1",
            "/W:1",
            "/XF",
            "*.pyc",
            "/XD",
            *absolute,
        ]
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        returncode = proc.returncode
        if returncode >= 8:  # robocopy exit codes 0-7 are success
            fallback = {"robocopy_returncode": returncode, "stdout_tail": proc.stdout[-400:]}
    if os.name != "nt" or fallback is not None:
        method = "robocopy+copytree" if fallback else "copytree"
        errors: list[str] = []
        try:
            shutil.copytree(
                source,
                dest,
                dirs_exist_ok=True,
                ignore=_repo_ignore(source, excludes),
                ignore_dangling_symlinks=True,
            )
        except shutil.Error as exc:
            errors = [str(item) for item in exc.args[0]] if exc.args else []
        if fallback is not None:
            fallback["unreadable_entries"] = len(errors)
            fallback["unreadable_sample"] = errors[:5]
    files = sum(1 for path in dest.rglob("*") if path.is_file())
    if files == 0:
        raise RuntimeError(f"repository copy produced no files: {source} -> {dest}")
    return {
        "source": str(source),
        "dest": str(dest),
        "method": method,
        "returncode": returncode,
        "fallback": fallback,
        "excluded": list(excludes),
        "files": files,
    }


def overlay_config(home: Path, config_dir: Path) -> dict[str, Any]:
    """Apply the candidate branch's shipped config files over a snapshot home."""
    applied: list[dict[str, Any]] = []
    for path in sorted(config_dir.glob("*.toml")):
        target = home / "config" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        applied.append(
            {"file": path.name, "sha256": sha256_file(path, normalize_newlines=True)}
        )
    return {"dir": str(config_dir), "files": applied}


def token_hits(text: str, tokens: Sequence[str]) -> dict[str, bool]:
    """Which expected memory ids appear verbatim in a text (retrieval-coverage aid)."""
    return {token: token in text for token in tokens}


TEXT_SUFFIXES = (
    ".py", ".ts", ".md", ".json", ".jsonl", ".toml", ".ps1", ".txt", ".yml", ".yaml",
    ".sql", ".cfg", ".ini", ".js", ".mjs", ".cjs", ".css", ".html", ".cmd", ".sh",
)


def text_corpus(roots: Sequence[Path], limit_bytes: int = 2_000_000) -> str:
    """Concatenated text of every readable text file under the given roots."""
    chunks: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > limit_bytes:
                    continue
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def anchor_scan(
    tasks: Sequence[dict[str, Any]], repo_root: Path, memory_root: Path
) -> dict[str, Any]:
    """Construct validity per task: can the check be met from the repo copy, and from memory?

    Native must be able to succeed by hunting (``repo_all``), and the memory packet must
    be able to answer outright (``memory_all``); a task failing either is a harness defect,
    not a measurement.
    """
    repo_text = text_corpus([repo_root])
    memory_text = text_corpus([memory_root]) if memory_root.is_dir() else ""
    per_task: dict[str, Any] = {}
    for task in tasks:
        repo_hits = [
            any(re.search(alt, repo_text, re.IGNORECASE) for alt in group)
            for group in task["groups"]
        ]
        memory_hits = [
            any(re.search(alt, memory_text, re.IGNORECASE) for alt in group)
            for group in task["groups"]
        ]
        per_task[task["id"]] = {
            "class": task["class"],
            "groups": len(task["groups"]),
            "repo_groups_matched": sum(repo_hits),
            "repo_all": all(repo_hits),
            "memory_groups_matched": sum(memory_hits),
            "memory_all": all(memory_hits),
            "repo_chars": len(repo_text),
            "memory_chars": len(memory_text),
        }
    return {
        "repo_root": str(repo_root),
        "memory_root": str(memory_root),
        "per_task": per_task,
        "memory_tasks_answerable_in_repo": sum(
            1
            for task in tasks
            if task["class"] == "memory" and per_task[task["id"]]["repo_all"]
        ),
        "memory_tasks_covered_by_memory": sum(
            1
            for task in tasks
            if task["class"] == "memory" and per_task[task["id"]]["memory_all"]
        ),
        "memory_task_count": sum(1 for task in tasks if task["class"] == "memory"),
    }


def probe_decisions(
    python: Path, snapshot: Path, work: Path, repo: Path, tasks: Sequence[dict[str, Any]],
    config_dir: Path | None, project_id: str, timeout: int, out_dir: Path,
) -> dict[str, Any]:
    """Ask the candidate's own decision path what each task would inject (no model calls).

    Mirrors ``turn-bridge.ts``: ``python -m second_brain turn prepare`` with the same
    phases, budget, project and cwd the extension uses.
    """
    results: list[dict[str, Any]] = []
    for task in tasks:
        home = work / f"probe-{task['id']}"
        shutil.copytree(snapshot, home)
        reset_home_deliveries(home)
        overlay = overlay_config(home, config_dir) if config_dir is not None else None
        env = clean_env()
        env["SECOND_BRAIN_HOME"] = str(home)
        env["SECOND_BRAIN_PROJECT"] = project_id
        argv = [
            str(python),
            "-m",
            "second_brain",
            "turn",
            "prepare",
            "--session",
            f"value-probe-{task['id']}",
            "--task",
            task["prompt"],
            "--branch",
            "main",
            "--role",
            "worker",
            "--budget-tokens",
            "256",
            "--phases",
            "capsule,render,autoinject",
            "--agent",
            "value-probe",
            "--project",
            project_id,
            "--cwd",
            str(repo),
            "--json",
        ]
        started = time.perf_counter()
        proc = subprocess.run(
            argv, capture_output=True, text=True, env=env, cwd=home, timeout=timeout, check=False
        )
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        payload: dict[str, Any] = {}
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            payload = {}
        autoinject = payload.get("autoinject")
        autoinject = autoinject if isinstance(autoinject, dict) else {}
        packet = str(autoinject.get("packet") or "")
        timings = payload.get("timings_ms")
        timings = timings if isinstance(timings, dict) else {}
        deliveries = read_deliveries(home, task["memory_ids"])
        results.append(
            {
                "task": task["id"],
                "class": task["class"],
                "returncode": proc.returncode,
                "wall_ms": elapsed,
                "phases_ok": payload.get("phases_ok"),
                "decision": autoinject.get("decision"),
                "reason": autoinject.get("reason"),
                "candidate_ids": autoinject.get("candidate_ids") or [],
                "selected_ids": autoinject.get("selected_ids") or [],
                "packet_tokens": autoinject.get("packet_tokens"),
                "packet_memory_ids": sorted(set(re.findall(r"mem-[0-9a-f]{12}", packet))),
                "expected_present": token_hits(packet, task["memory_ids"]),
                "delivered_expected": deliveries["expected"],
                "delivered_rows": deliveries["rows"],
                "timings_ms": timings,
                "overlay": None if overlay is None else len(overlay["files"]),
                "stderr_tail": proc.stderr[-300:],
            }
        )
    inventory = {
        "python": str(python),
        "tasks": len(results),
        "memory_tasks_injecting": sum(
            1
            for row in results
            if row["class"] == "memory"
            and (
                row["decision"] == "INJECT"
                or any(row["delivered_expected"].values())
                or any(row["expected_present"].values())
            )
        ),
        "memory_tasks_with_expected_memory_in_packet": sum(
            1
            for row in results
            if row["class"] == "memory" and any(row["expected_present"].values())
        ),
        "no_benefit_tasks_delivering": sum(
            1 for row in results if row["class"] == "no_benefit" and row["delivered_rows"]
        ),
        "results": results,
    }
    (out_dir / "probe.json").write_text(json.dumps(inventory, indent=1), encoding="utf-8")
    return inventory


# ---------------------------------------------------------------------------
# Arms and runs
# ---------------------------------------------------------------------------


def build_arms(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    return {
        "native": {"extension": None, "python": None, "config_dir": None},
        "candidate": {
            "extension": Path(args.candidate_extension),
            "python": Path(args.candidate_python),
            "config_dir": Path(args.candidate_config_dir),
        },
        "m00": {
            "extension": Path(args.m00_extension),
            "python": Path(args.m00_python),
            "config_dir": None,
        },
        "v3": {
            "extension": Path(args.v3_extension),
            "python": Path(args.candidate_python),
            "config_dir": None,
            "v3": True,
        },
    }


def prepare_v3_home(
    home: Path, worktree: Path, project_id: str, cwd: Path, python: Path
) -> dict[str, Any]:
    """Give a run's Brain home the V3 records/projects and compiled views for its cwd.

    Shared records only (``records/private`` stays on the machine that owns it). The run's
    fresh repository copy is mapped to ``project_id`` by an extra manifest, so the brief the
    extension reads is the one a real session in that project would get.
    """
    target = home / "records"
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted((worktree / "records").glob("*.md")):
        shutil.copy2(path, target / path.name)
        copied += 1
    shutil.copytree(worktree / "projects", home / "projects", dirs_exist_ok=True)
    manifest = home / "projects" / "_value-suite" / "project.toml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        f'id = "{project_id}"\nname = "{project_id}"\npaths = ["{cwd.as_posix()}"]\n',
        encoding="utf-8",
    )
    done = subprocess.run(
        [str(python), "-m", "second_brain.kb", "views", "--home", str(home)],
        capture_output=True,
        text=True,
        check=False,
        env={**clean_env(), "SECOND_BRAIN_HOME": str(home)},
    )
    return {
        "records": copied,
        "views_returncode": done.returncode,
        "views_stderr": done.stderr[-500:],
    }


def run_host(
    omp: str,
    spec: dict[str, Any],
    prompt: str,
    run_dir: Path,
    snapshot: Path,
    repo_source: Path,
    repo_excludes: Sequence[str],
    args: argparse.Namespace,
    raw_dir: Path,
    label: str,
) -> dict[str, Any]:
    """One host process: fresh cwd copy, fresh Brain home, one prompt."""
    cwd = run_dir / "proj"
    sessions_dir = run_dir / "sessions"
    repo_copy = copy_repo(repo_source, cwd, repo_excludes)
    env = clean_env()
    env.pop("SECOND_BRAIN_LEAN", None)
    tail = [
        "-p",
        "--mode",
        "json",
        "--model",
        args.model,
        "--thinking",
        args.thinking,
        "--session-dir",
        str(sessions_dir),
        "--cwd",
        str(cwd),
        "--no-extensions",
    ]
    if spec["extension"] is not None:
        tail += ["-e", str(spec["extension"])]
    home: Path | None = None
    overlay: dict[str, Any] | None = None
    if spec["python"] is not None:
        home = run_dir / "home"
        shutil.copytree(snapshot, home)
        reset_home_deliveries(home)
        if spec["config_dir"] is not None:
            overlay = overlay_config(home, spec["config_dir"])
        if spec.get("v3"):
            overlay = {
                "v3": prepare_v3_home(home, WORKTREE, args.project_id, cwd, spec["python"])
            }
        env["SECOND_BRAIN_HOME"] = str(home)
        env["SECOND_BRAIN_PYTHON"] = str(spec["python"])
        env["SECOND_BRAIN_PROJECT"] = args.project_id
    tail.append(prompt)
    raw_path = raw_dir / f"{label}.jsonl"
    result = _arms().run_once(omp, tail, env, args.timeout, raw_path)
    raw = result.pop("raw", "")
    return {
        "cwd": str(cwd),
        "sessions_dir": str(sessions_dir),
        "home": str(home) if home is not None else None,
        "overlay": overlay,
        "repo_copy": repo_copy,
        "raw": raw,
        "result": result,
    }


def measure_run(
    task: dict[str, Any],
    arm: str,
    rep: int,
    label: str,
    host: dict[str, Any],
) -> dict[str, Any]:
    """Turn one host result into a run record (metrics only; no interpretation)."""
    raw: str = host["raw"]
    result: dict[str, Any] = host["result"]
    usage = _arms().usage_totals(raw)
    sessions = session_inventory(Path(host["sessions_dir"]))
    parent_calls = stream_tool_calls(raw)
    parent_totals = dict(usage["totals"])
    subagent_usage = sessions["subagent_usage"]
    has_subagents = sessions["subagent_files"] > 0

    def merged_field(field: str) -> Any:
        """Parent stream plus subagent sessions; a subagent file that never reported
        the field makes the total unknown, never a quiet partial sum."""
        parent_value = parent_totals.get(field)
        if not has_subagents:
            return parent_value
        return _sum_optional(parent_value, subagent_usage.get(field))

    provider_usage = {field: merged_field(field) for field in USAGE_FIELDS}
    provider_usage["tokens_all"] = _sum_known(
        [merged_field(field) for field in ("input", "output", "cacheRead", "cacheWrite")]
    )
    provider_usage["cost_total"] = (
        _sum_optional(usage.get("cost_total"), sessions["subagent_cost_total"])
        if has_subagents
        else usage.get("cost_total")
    )
    tool_calls = dict(parent_calls)
    for name, count in sessions["subagent_tool_calls"].items():
        tool_calls[name] = tool_calls.get(name, 0) + count
    custom = stream_custom_messages(raw)
    answer = answer_blocks(assistant_text_blocks(raw))
    check = answer_matches(answer, task["groups"])
    status = "ok"
    if result.get("returncode") is None:
        status = "timeout"
    elif result.get("returncode") != 0:
        status = "error"
    deliveries = read_deliveries(Path(host["home"]), task["memory_ids"]) if host["home"] else {
        "available": False,
        "rows": 0,
        "per_memory": {},
        "expected": {m: 0 for m in task["memory_ids"]},
        "agent_sessions": [],
    }
    expected_injected = {
        memory: any(
            memory in message["memory_ids"]
            for message in custom
            if message["customType"] in INJECTED_CONTEXT_CUSTOM_TYPES
        )
        for memory in task["memory_ids"]
    }
    return {
        "task": task["id"],
        "class": task["class"],
        "arm": arm,
        "rep": rep,
        "label": label,
        "status": status,
        "returncode": result.get("returncode"),
        "wall_ms": result.get("wall_ms"),
        "run_dir": str(Path(host["cwd"]).parent),
        "cwd": host["cwd"],
        "home": host["home"],
        "config_overlay": host["overlay"],
        "repo_copy": {
            key: host["repo_copy"][key]
            for key in ("method", "files", "excluded", "fallback")
        },
        "correct": check["ok"],
        "check": check,
        "answer": answer[:2000],
        "tool_calls": tool_calls,
        "tool_calls_total": sum(tool_calls.values()),
        "tool_calls_parent": parent_calls,
        "subagent_tool_calls": sessions["subagent_tool_calls"],
        "model_requests": int(usage["request_count"]) + int(
            sessions["subagent_assistant_messages"]
        ),
        "model_requests_parent": int(usage["request_count"]),
        "subagent_sessions": sessions["subagent_files"],
        "provider_usage": provider_usage,
        "provider_usage_parent": usage,
        "provider_usage_subagents": sessions["subagent_usage"],
        "usage_fields_reported": usage["fields_reported"],
        "brain_custom_messages": custom,
        "brain_visible_chars": sum(int(message["chars"]) for message in custom),
        "brain_memory_ids": sorted(
            {memory for message in custom for memory in message["memory_ids"]}
        ),
        "memory_ids_expected_injected": expected_injected,
        "memory_delivered_expected": sorted(
            memory for memory, count in deliveries["expected"].items() if count
        ),
        "deliveries": {
            "rows": deliveries["rows"],
            "per_memory": deliveries["per_memory"],
            "expected": deliveries["expected"],
            "agent_sessions": deliveries["agent_sessions"],
        },
        "stderr_tail": result.get("stderr_tail"),
    }


def error_run_record(
    task: dict[str, Any],
    arm: str,
    rep: int,
    label: str,
    run_dir: Path,
    exc: BaseException,
) -> dict[str, Any]:
    """One run whose measurement failed: the failure is kept, its counts stay unknown.

    ``run_host``/``measure_run`` can raise after the host already did work, so a
    fabricated 0 would enter the paired medians as a measured "did nothing" run.
    The record still counts as an incorrect run of its class.
    """
    return {
        "task": task["id"],
        "class": task["class"],
        "arm": arm,
        "rep": rep,
        "label": label,
        "status": "error",
        "run_dir": str(run_dir),
        "error": f"{type(exc).__name__}: {exc}",
        "correct": False,
        "check": {"ok": False, "missing_groups": task["groups"]},
        "answer": "",
        "tool_calls": {},
        "tool_calls_total": None,
        "model_requests": None,
        "provider_usage": {field: None for field in USAGE_FIELDS} | {
            "tokens_all": None,
            "cost_total": None,
        },
        "brain_custom_messages": [],
        "brain_visible_chars": 0,
        "brain_memory_ids": [],
        "memory_delivered_expected": [],
        "deliveries": {
            "rows": 0,
            "per_memory": {},
            "expected": {},
            "agent_sessions": [],
        },
    }


def _sum_optional(*values: Any) -> Any:
    usable = [value for value in values if isinstance(value, (int, float))]
    if not usable:
        return None
    if any(value is None for value in values):
        # A field one side never reported cannot be presented as a partial total.
        return None
    if all(isinstance(value, int) for value in usable):
        # Token counters are integers; keeping the type keeps the sum readable as one.
        return int(sum(usable))
    return round(float(sum(usable)), 8)


def _sum_known(values: Sequence[Any]) -> Any:
    usable = [value for value in values if isinstance(value, (int, float))]
    if not usable or any(value is None for value in values):
        return None
    return int(sum(usable))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def render_report(
    manifest: dict[str, Any],
    summary: dict[str, Any],
    verdict: dict[str, Any],
    runs: Sequence[dict[str, Any]],
    command: str,
) -> str:
    lines: list[str] = []
    lines.append("# V3 agent-experience value suite")
    lines.append("")
    lines.append(f"- command: `{command}`")
    lines.append(
        "- full campaign command: `python scripts/v3_value_suite.py "
        f"--out {manifest['value_dir']} --reps 3 --arms native,candidate "
        f"--seed {manifest['seed']} --model {manifest['model']} "
        f"--thinking {manifest['thinking']}`"
    )
    lines.append(f"- model: `{manifest['model']}` (thinking `{manifest['thinking']}`)")
    lines.append(f"- arms: {', '.join(manifest['arms_order'])}; reps: {manifest['reps']}")
    lines.append(
        f"- tasks: {manifest['task_count']} ("
        + ", ".join(f"{count} {klass}" for klass, count in manifest["task_classes"].items())
        + ")"
    )
    lines.append(f"- omp: {manifest['omp_version']}")
    lines.append(f"- verdict: **{'PASS' if verdict['pass'] else 'FAIL'}**")
    lines.append("")
    lines.append("## Method and caveats")
    lines.append("")
    probe = manifest.get("probe") or {}
    lines.append(
        "- cwd per run: a fresh copy of "
        f"`{manifest['repo_copy_source']}` minus {', '.join(manifest['repo_excludes'])}. "
        "The Brain's own store (`memory/`, `db/`, `state/`, `telemetry/`) is excluded so a "
        "run cannot read answers out of the database it is measured against, and the frozen "
        "held-out set is excluded by contract. `outputs/reports` otherwise stays in the copy "
        "as legitimate hunting ground."
    )
    lines.append(
        "- home per run: a fresh copy of the corpus snapshot"
        + (
            " with the candidate's shipped config applied over it (files listed in "
            "`manifest.json/arms/candidate`)."
            if manifest["arms"].get("candidate", {}).get("config_dir")
            else "."
        )
    )
    lines.append(
        "- unknown usage stays null: a field some side never reported is never presented as "
        "a partial sum. Metrics compare `input+output` tokens (cache reads billed separately "
        "are recorded in `provider_usage.tokens_all`) and total tool calls."
    )
    lines.append(
        "- failures (timeouts, non-zero exits, harness errors) are retained as rows with "
        f"`correct=false`; a harness error reports its counts as unknown, never as a measured 0. "
        f"Run status counts: {manifest.get('run_status')}."
    )
    if probe:
        lines.append(
            "- retrieval coverage before any model call (`probe.json`, decision path only): "
            f"{probe['memory_tasks_injecting']}/{probe['memory_task_count']} memory tasks "
            f"inject, {probe['memory_tasks_with_expected_memory_in_packet']} carry the expected "
            f"memory id in the packet, {probe['no_benefit_tasks_delivering']} no-benefit tasks "
            "delivered anything."
        )
        lines.append(
            "- answer anchors (`anchors.json`): "
            f"{probe['memory_tasks_answerable_in_repo']}/{probe['memory_task_count']} memory "
            "tasks are answerable from the repository copy by hunting (native can succeed) and "
            f"{probe['memory_tasks_covered_by_memory']}/{probe['memory_task_count']} are covered "
            "by the memory store; anchor defects: "
            f"{', '.join(probe['anchor_defects']) or 'none'}."
        )
    lines.append("")
    lines.append("## Pass rule")
    lines.append("")
    lines.append(PASS_RULE)
    lines.append("")
    lines.append("## Class results (paired per task, candidate - native)")
    lines.append("")
    lines.append(
        "| class | metric | native median | candidate median | median delta | "
        "bootstrap 95% CI | tasks paired |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for klass in CLASSES:
        entry = summary.get(klass)
        if not entry:
            continue
        for metric in ("tokens_in_out", "tool_calls"):
            block = entry[metric]
            ci = block["ci"]
            ci_text = f"[{ci[0]:.1f}, {ci[1]:.1f}]" if ci else "n/a"
            lines.append(
                f"| {klass} | {metric} | {_fmt(block['median_native'])} | "
                f"{_fmt(block['median_candidate'])} | {_fmt(block['median_delta'])} | "
                f"{ci_text} | {block['paired_tasks']} |"
            )
        correctness = entry["correctness"]
        for arm, stats in correctness.items():
            lines.append(
                f"| {klass} | correct ({arm}) | {stats['correct']}/{stats['runs']} | "
                f"rate {stats['rate']} | - | - | - |"
            )
    lines.append("")
    lines.append("## Verdict detail")
    lines.append("")
    for klass in CLASSES:
        block = verdict.get(klass)
        if not block:
            continue
        lines.append(f"- **{klass}**: {'PASS' if block['pass'] else 'FAIL'}")
        for reason in block["reasons"]:
            lines.append(f"  - {reason}")
    lines.append("")
    lines.append("## Brain overhead and delivery coverage")
    lines.append("")
    lines.append(
        "| task | class | arm | injected chars | memories injected | "
        "deliveries (expected) | tool calls | tokens (in+out) | status |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for run in runs:
        usage = run_metrics(run)
        deliveries = run["deliveries"]["expected"]
        lines.append(
            f"| {run['task']} | {run['class']} | {run['arm']} | {run['brain_visible_chars']} | "
            f"{', '.join(run['brain_memory_ids']) or '-'} | {_delivery_text(deliveries)} | "
            f"{usage['tool_calls']} | {usage['tokens_in_out']} | {run['status']} |"
        )
    lines.append("")
    lines.append("## Raw artifacts")
    lines.append("")
    lines.append(f"- manifest: `{manifest['out']}/manifest.json`")
    lines.append(f"- runs: `{manifest['out']}/runs.json`")
    lines.append(f"- summary: `{manifest['out']}/summary.json`")
    lines.append(f"- per-run model streams: `{manifest['out']}/raw/`")
    if manifest.get("probe") is not None:
        lines.append(f"- decision probe (no model calls): `{manifest['out']}/probe.json`")
    lines.append("")
    return "\n".join(lines)


def _relative_to_worktree(path: Path) -> str:
    try:
        return path.relative_to(WORKTREE).as_posix()
    except ValueError:
        return str(path)


def _delivery_text(deliveries: dict[str, Any]) -> str:
    if not deliveries:
        return "-"
    return ", ".join(f"{memory}:{count}" for memory, count in deliveries.items())


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", required=True, help="output directory for this campaign")
    ap.add_argument("--tasks-file", default=str(DEFAULT_TASKS))
    ap.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    ap.add_argument("--classes", default="", help="comma-separated classes (default: all)")
    ap.add_argument("--arms", default="native,candidate")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--model", default="deepseek/deepseek-flash")
    ap.add_argument("--thinking", default="low")
    ap.add_argument("--project-id", default="second-brain")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--omp", default="omp")
    ap.add_argument("--corpus-home", default=str(CANONICAL_HOME))
    ap.add_argument(
        "--repo-source",
        default=None,
        help=(
            "repository copied into each run's cwd (default: this worktree - the candidate's "
            "own checkout). Every run's hunting ground is a fresh copy of it."
        ),
    )
    ap.add_argument(
        "--candidate-extension",
        default=str(WORKTREE / "brainstem/prime-extension/src/index.ts"),
    )
    ap.add_argument("--candidate-python", default=str(WORKTREE / ".venv/Scripts/python.exe"))
    ap.add_argument(
        "--candidate-config-dir",
        default=str(WORKTREE / "config"),
        help="the candidate branch's shipped config directory (applied over the snapshot home)",
    )
    ap.add_argument(
        "--v3-extension",
        default=str(WORKTREE / "brainstem/omp-v3/index.ts"),
        help="the standalone V3 OMP extension (arm v3)",
    )
    ap.add_argument(
        "--m00-extension",
        default=str(Path.home() / ".omp/agent/extensions/second-brain/index.ts"),
    )
    ap.add_argument(
        "--m00-python", default=str(CANONICAL_HOME / ".venv/Scripts/python.exe")
    )
    ap.add_argument("--slack-tokens", type=float, default=0.0)
    ap.add_argument("--slack-tool-calls", type=float, default=0.0)
    ap.add_argument("--bootstrap-iters", type=int, default=2000)
    ap.add_argument("--probe", dest="probe", action="store_true", default=True)
    ap.add_argument("--no-probe", dest="probe", action="store_false")
    ap.add_argument("--probe-only", action="store_true", help="decisions only; no model calls")
    ap.add_argument("--probe-timeout", type=int, default=120)
    ap.add_argument("--keep-work", action="store_true", help="keep the temp work directory")
    ap.add_argument("--work-dir", default=None)
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    command = (
        " ".join(["python", "scripts/v3_value_suite.py", *sys.argv[1:]])
        if argv is None
        else "python scripts/v3_value_suite.py " + " ".join(argv)
    )

    tasks = select_tasks(load_tasks(Path(args.tasks_file)), args.tasks, args.classes)
    arms_spec = build_arms(args)
    arms_order = [arm for arm in args.arms.split(",") if arm]
    unknown = [arm for arm in arms_order if arm not in arms_spec]
    if unknown:
        print(f"unknown arms: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if len(arms_order) < 2:
        print("need at least two arms for a paired comparison", file=sys.stderr)
        return 2

    work = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="v3-value-"))
    work.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    snapshot = work / "snapshot"
    expected_memories = sorted({token for task in tasks for token in task["memory_ids"]})
    corpus = _arms().snapshot_corpus(Path(args.corpus_home), snapshot, tokens=expected_memories)
    repo_source = Path(args.repo_source) if args.repo_source else WORKTREE
    excludes: list[str] = list(REPO_EXCLUDE_DIRS)
    for candidate in (out, raw_dir):
        try:
            rel = candidate.resolve().relative_to(repo_source.resolve()).as_posix()
        except ValueError:
            continue
        if rel not in excludes:
            excludes.append(rel)

    manifest: dict[str, Any] = {
        "harness": "scripts/v3_value_suite.py",
        "harness_sha256": sha256_file(Path(__file__), normalize_newlines=True),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "out": str(out),
        "value_dir": _relative_to_worktree(DEFAULT_TASKS.parent),
        "command": command,
        "omp_version": subprocess.run(
            [args.omp, "--version"], capture_output=True, text=True, check=False
        ).stdout.strip(),
        "model": args.model,
        "thinking": args.thinking,
        "project_id": args.project_id,
        "reps": args.reps,
        "seed": args.seed,
        "arms_order": arms_order,
        "task_count": len(tasks),
        "task_classes": {
            klass: sum(1 for task in tasks if task["class"] == klass) for klass in CLASSES
        },
        "tasks": tasks,
        "pass_rule": PASS_RULE,
        "corpus": corpus,
        "expected_memories": expected_memories,
        "repo_excludes": excludes,
        "repo_copy_source": str(repo_source),
        "probe": None,
        "arms": {},
        "notes": (
            "Every run is a fresh host process with a fresh copy of the corpus snapshot and a "
            "fresh copy of the repository as cwd; failures are retained, never retried. Runs "
            "are interleaved by seeded shuffle within each rep."
        ),
    }
    arms_module = _arms()
    for arm in arms_order:
        spec = arms_spec[arm]
        manifest["arms"][arm] = {
            "extension": (
                arms_module.extension_identity(spec["extension"])
                if spec["extension"] is not None
                else None
            ),
            "runtime": (
                arms_module.runtime_identity(spec["python"])
                if spec["python"] is not None
                else None
            ),
            "config_dir": str(spec["config_dir"]) if spec["config_dir"] else None,
            "home": (
                "fresh copy of the corpus snapshot"
                + (" with the candidate's shipped config" if spec["config_dir"] else "")
                if spec["python"] is not None
                else "none (no Brain)"
            ),
        }

    probe: dict[str, Any] | None = None
    if args.probe:
        candidate_python = Path(args.candidate_python)
        probe_repo = work / "probe-repo"
        copy_repo(repo_source, probe_repo, excludes)
        probe = probe_decisions(
            candidate_python,
            snapshot,
            work,
            probe_repo,
            tasks,
            Path(args.candidate_config_dir),
            args.project_id,
            args.probe_timeout,
            out,
        )
        anchors = anchor_scan(tasks, probe_repo, snapshot / "memory")
        (out / "anchors.json").write_text(json.dumps(anchors, indent=1), encoding="utf-8")
        manifest["probe"] = {
            "path": str(out / "probe.json"),
            "anchors_path": str(out / "anchors.json"),
            "anchor_defects": [
                task_id
                for task_id, row in anchors["per_task"].items()
                if row["class"] == "memory" and not row["repo_all"]
            ],
            "memory_tasks_answerable_in_repo": anchors["memory_tasks_answerable_in_repo"],
            "memory_tasks_covered_by_memory": anchors["memory_tasks_covered_by_memory"],
            "memory_task_count": anchors["memory_task_count"],
            "memory_tasks_injecting": probe["memory_tasks_injecting"],
            "memory_tasks_with_expected_memory_in_packet": probe[
                "memory_tasks_with_expected_memory_in_packet"
            ],
            "no_benefit_tasks_delivering": probe["no_benefit_tasks_delivering"],
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    if args.probe_only:
        print(json.dumps(manifest["probe"], indent=1))
        return 0

    rng = random.Random(args.seed)
    runs: list[dict[str, Any]] = []
    run_index = 0
    for rep in range(args.reps):
        schedule = [(task, arm) for task in tasks for arm in arms_order]
        rng.shuffle(schedule)
        for position, (task, arm) in enumerate(schedule):
            label = f"{task['id']}-{arm}-R{rep}"
            # Equal-length, arm-neutral directories: the cwd is model-visible, so an
            # arm or task name in it would skew the input-token comparison.
            run_dir = work / f"run{run_index:04d}"
            run_index += 1
            run_dir.mkdir(parents=True, exist_ok=True)
            started = time.time()
            try:
                host = run_host(
                    args.omp,
                    arms_spec[arm],
                    task["prompt"],
                    run_dir,
                    snapshot,
                    repo_source,
                    excludes,
                    args,
                    raw_dir,
                    label,
                )
                record = measure_run(task, arm, rep, label, host)
            except Exception as exc:
                record = error_run_record(task, arm, rep, label, run_dir, exc)
            record["order_position"] = position
            record["started_epoch"] = round(started, 3)
            runs.append(record)
            print(
                f"{label}: status={record['status']} correct={record['correct']} "
                f"tools={record.get('tool_calls_total')} "
                f"tokens={run_metrics(record)['tokens_in_out']} "
                f"brain_chars={record['brain_visible_chars']}",
                flush=True,
            )
            (out / "runs.json").write_text(json.dumps(runs, indent=1), encoding="utf-8")

    summary = class_summary(runs, tasks, arms_order, args.seed, args.bootstrap_iters)
    verdict = evaluate_pass_rule(summary, arms_order, args.slack_tokens, args.slack_tool_calls)
    manifest.update(
        {
            "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "runs": len(runs),
            "run_status": {
                status: sum(1 for run in runs if run["status"] == status)
                for status in sorted({run["status"] for run in runs})
            },
            "work_dir": str(work),
        }
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps({"summary": summary, "verdict": verdict}, indent=1), encoding="utf-8"
    )
    (out / "REPORT.md").write_text(
        render_report(manifest, summary, verdict, runs, command), encoding="utf-8"
    )
    print(json.dumps(verdict, indent=1))
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
