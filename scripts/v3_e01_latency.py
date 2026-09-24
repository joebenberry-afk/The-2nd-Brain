"""E01 pre-dispatch latency harness (PERF-02/PERF-04 evidence).

Measures, for the SAME host/model/prompt/corpus conditions:

  inert                    host hook-dispatch cost only (no Brain work)
  candidate-current        S2 head with the per-phase spawns (pre-E01 path)
  candidate-once           S2 head with one batched process per prompt
  candidate-helper-lazy    reused interpreter, started by the first prompt
  candidate-helper-eager   reused interpreter, started during host boot

Each run is ONE fresh host process that processes TWO prompts (cold = first
prompt after host start, warm = a later prompt in the same host session), so
cold/warm are measured under the same host boot conditions as the S1 pilot.
Every run gets a fresh copy of the corpus snapshot (no cross-arm state) and its
own trace file (`SECOND_BRAIN_E01_TRACE`), which both the extension and the
Python children append spans to.

Pre-dispatch = the harness clock at the host's `message_end` event for the user
message (the S1 definition), measured here per prompt index. Spans are
reconciled against that clock through the epoch timestamps both sides record.

Example:
  python scripts/v3_e01_latency.py --out outputs/reports/v3-s2/e01/pilot --reps 5
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]

# Prompt A is the cold prompt of the host session (minimal model work); prompt B
# is the warm one and needs a stored memory, so the same run also proves the
# designs keep delivering the same packet.
COLD_PROMPT = "Reply with exactly: E01-COLD."
WARM_PROMPT = "In what order should database migrations be applied?"
MEMORY_TOKEN = "mem-a8d221e64549"

ARM_SPECS: dict[str, dict[str, Any]] = {
    "inert": {"extension": "scripts/v3_inert_extension.ts", "brain": False, "env": {}},
    "candidate-current": {
        "extension": "candidate",
        "brain": True,
        "env": {"SECOND_BRAIN_TURN_MODE": "current"},
    },
    "candidate-once": {
        "extension": "candidate",
        "brain": True,
        "env": {"SECOND_BRAIN_TURN_MODE": "once"},
    },
    "candidate-helper-lazy": {
        "extension": "candidate",
        "brain": True,
        "env": {"SECOND_BRAIN_TURN_MODE": "helper", "SECOND_BRAIN_TURN_HELPER_START": "lazy"},
    },
    "candidate-helper-eager": {
        "extension": "candidate",
        "brain": True,
        "env": {
            "SECOND_BRAIN_TURN_MODE": "helper",
            "SECOND_BRAIN_TURN_HELPER_START": "session_start",
        },
    },
}


def _arms_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "v3_matched_arms", WORKTREE / "scripts" / "v3_matched_arms.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "native_noninterference_probe", WORKTREE / "scripts" / "native_noninterference_probe.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    # The ambient shell sets SECOND_BRAIN_HOME to the live home; every arm must
    # be explicitly pointed at its own snapshot (or nothing at all for inert).
    env.pop("SECOND_BRAIN_HOME", None)
    env.pop("SECOND_BRAIN_PYTHON", None)
    env.pop("SECOND_BRAIN_PROJECT", None)
    env.pop("SECOND_BRAIN_E01_TRACE", None)
    env.pop("SECOND_BRAIN_TURN_MODE", None)
    env.pop("SECOND_BRAIN_TURN_HELPER_START", None)
    return env


def run_host(
    omp: str,
    argv_tail: list[str],
    env: dict[str, str],
    timeout: int,
    raw_path: Path,
) -> dict[str, Any]:
    """Run one host process; stamp every stdout line on BOTH clocks."""
    perf0 = time.perf_counter()
    epoch0 = time.time() * 1000.0
    events: list[dict[str, Any]] = []
    lines: list[str] = []
    proc = subprocess.Popen(
        [omp, *argv_tail],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    timed_out = False
    for line in proc.stdout:
        perf_ms = (time.perf_counter() - perf0) * 1000.0
        epoch_ms = time.time() * 1000.0
        lines.append(line)
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message") if isinstance(event.get("message"), dict) else None
        events.append(
            {
                "type": event.get("type"),
                "role": message.get("role") if message else None,
                "perf_ms": round(perf_ms, 1),
                "epoch_ms": round(epoch_ms, 1),
            }
        )
        if perf_ms > timeout * 1000:
            proc.kill()
            timed_out = True
            break
    stderr = proc.stderr.read() if proc.stderr else ""
    rc = proc.wait()
    raw = "".join(lines)
    raw_path.write_text(raw, encoding="utf-8")
    return {
        "returncode": None if timed_out else rc,
        "wall_ms": round((time.perf_counter() - perf0) * 1000.0, 1),
        "launch_epoch_ms": epoch0,
        "events": events,
        "raw": raw,
        "stderr_tail": stderr[-600:],
    }


def user_message_marks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The user `message_end` marks, in order (cold first)."""
    return [event for event in events if event["type"] == "message_end" and event["role"] == "user"]


def read_trace(path: Path) -> dict[str, Any]:
    """Parse one run's trace file into launch-relative spans."""
    records: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    spans: list[dict[str, Any]] = []
    for record in records:
        if record.get("t") != "span":
            continue
        # Extension spans carry their payload under `fields`; Python `phase`
        # records are already flat. Accept both shapes.
        payload = record.get("fields") if isinstance(record.get("fields"), dict) else record
        if "start_ms" not in payload or "end_ms" not in payload:
            continue
        mono = float(record.get("mono_ms") or 0.0)
        start_ms = float(payload["start_ms"])
        end_ms = float(payload["end_ms"])
        start_wall = float(record["wall_ms"]) - (mono - start_ms)
        spans.append(
            {
                "name": payload.get("name"),
                "pid": record.get("pid"),
                "start_epoch_ms": round(start_wall, 3),
                "end_epoch_ms": round(start_wall + (end_ms - start_ms), 3),
                "duration_ms": round(end_ms - start_ms, 3),
                "fields": {k: v for k, v in payload.items() if k not in ("start_ms", "end_ms")},
            }
        )
    return {"records": records, "spans": spans}


def span_totals(spans: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [span for span in spans if span["name"] == name]


def summarize_spans(trace: dict[str, Any], launch_epoch: float) -> dict[str, Any]:
    """Per-span-name aggregate; occurrences stay ordered (cold, then warm).

    A two-prompt host run emits each hook/phase span twice, so the COLD
    occurrence must be addressable on its own (`first_*`).
    """
    spans_by_name: dict[str, list[dict[str, Any]]] = {}
    for span in trace["spans"]:
        spans_by_name.setdefault(str(span["name"]), []).append(span)
    summary: dict[str, Any] = {}
    for name, spans in sorted(spans_by_name.items()):
        spans.sort(key=lambda span: span["start_epoch_ms"])
        durations = [span["duration_ms"] for span in spans]
        first = spans[0]
        entry: dict[str, Any] = {
            "count": len(spans),
            "total_ms": round(sum(durations), 3),
            "median_ms": round(statistics.median(durations), 3),
            "max_ms": round(max(durations), 3),
            "first_start_rel_ms": round(first["start_epoch_ms"] - launch_epoch, 3),
            "first_duration_ms": first["duration_ms"],
            "first_end_rel_ms": round(first["end_epoch_ms"] - launch_epoch, 3),
        }
        if len(spans) > 1:
            entry["second_duration_ms"] = spans[1]["duration_ms"]
        summary[name] = entry
    return summary


ANCHOR_KEYS = (
    "session",
    "agent_start",
    "turn_start",
    "agent_end",
    "message_start:user",
    "message_end:user",
    "message_end:assistant",
)


def anchor_map(events: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """First occurrence of each host anchor, on the harness clock."""
    anchors: dict[str, dict[str, float]] = {}
    for event in events:
        key = f"{event['type']}:{event['role']}" if event["role"] else str(event["type"])
        if key in ANCHOR_KEYS and key not in anchors:
            anchors[key] = {"perf_ms": event["perf_ms"], "epoch_ms": event["epoch_ms"]}
    return anchors


def prompt_costs(events: list[dict[str, Any]], launch_epoch: float) -> list[dict[str, Any]]:
    """Cold/warm pre-dispatch per prompt index, on both clocks."""
    marks = user_message_marks(events)
    costs = []
    for index, mark in enumerate(marks):
        costs.append(
            {
                "index": index,
                "pre_dispatch_ms": mark["perf_ms"],
                "pre_dispatch_rel_epoch_ms": round(mark["epoch_ms"] - launch_epoch, 1),
            }
        )
    return costs


def turn2_metrics(
    events: list[dict[str, Any]],
    anchors: dict[str, dict[str, float]],
    span_summary: dict[str, Any],
) -> dict[str, Any] | None:
    """Warm-prompt (index 1) cost with turn 1's model time excluded.

    `warm_pre_dispatch_ms` (launch -> 2nd user message_end) contains turn 1's
    whole model/tool run, so it cannot isolate the Brain's per-prompt cost. This
    metric starts at the first `agent_end` (turn 1 fully finished) and ends at
    the second user `message_end`: nothing of turn 1's model work is inside it.
    """
    marks = user_message_marks(events)
    first_turn_end = anchors.get("agent_end", {}).get("perf_ms")
    if len(marks) < 2 or first_turn_end is None:
        return None
    hook = span_summary.get("before_agent_start.hook", {})
    batched = span_summary.get("before_agent_start.turn_bridge", {})
    phases = {
        name: span_summary[name]["second_duration_ms"]
        for name in PHASE_SPANS
        if span_summary.get(name, {}).get("second_duration_ms") is not None
    }
    first_user_end = anchors.get("message_end:user", {}).get("perf_ms")
    return {
        "turn2_pre_dispatch_ms": round(marks[1]["perf_ms"] - first_turn_end, 1),
        "turn2_hook_ms": hook.get("second_duration_ms"),
        "turn2_batched_ms": batched.get("second_duration_ms"),
        "turn2_phases_ms": phases,
        "turn1_model_ms": (
            round(first_turn_end - first_user_end, 1) if first_user_end is not None else None
        ),
    }


def reconcile_cold(
    cold_cost_ms: float,
    cold_mark_epoch: float,
    launch_epoch: float,
    trace: dict[str, Any],
) -> dict[str, Any]:
    """Attribute launch -> cold message_end to non-overlapping spans.

    Every span is launch-relative; overlapping spans (a concurrent background
    bridge inside the hook) are merged so the union is counted once.
    """
    total = cold_mark_epoch - launch_epoch
    intervals: list[tuple[float, float]] = []
    for span in trace["spans"]:
        start = span["start_epoch_ms"] - launch_epoch
        end = span["end_epoch_ms"] - launch_epoch
        if end <= 0 or start >= total:
            continue
        intervals.append((max(start, 0.0), min(end, total)))
    covered = 0.0
    if intervals:
        merged: list[list[float]] = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        covered = sum(end - start for start, end in merged)
    hook = span_totals(trace["spans"], "before_agent_start.hook")
    hook_duration = hook[0]["duration_ms"] if hook else None
    hook_rel = round(hook[0]["start_epoch_ms"] - launch_epoch, 3) if hook else None
    tail = round(total - (hook_rel + hook_duration), 3) if hook else None
    return {
        "launch_to_cold_message_end_ms": round(total, 3),
        "spans_union_ms": round(covered, 3),
        "unattributed_ms": round(total - covered, 3),
        "unattributed_share": round((total - covered) / total, 4) if total > 0 else None,
        "hook_start_rel_ms": hook_rel,
        "hook_duration_ms": hook_duration,
        "after_hook_ms": tail,
        "cold_mark_perf_ms": cold_cost_ms,
    }


#: Extension spans that are BLOCKING work inside `before_agent_start` (the host
#: awaits the hook), split by design so the same table serves all arms.
PHASE_SPANS = (
    "before_agent_start.turn_bridge",
    "before_agent_start.capsule_ensure",
    "before_agent_start.hot_context_render",
    "before_agent_start.autoinject",
    "before_agent_start.recall_brief",
    "turn_helper.start",
)
#: Concurrent work an attribution table must account for separately.
BACKGROUND_SPANS = (
    "bg.visibility_plan",
    "bg.environment_assessment",
    "bg.ledger_mirror",
    "bg.p4_pulse",
)


def cold_attribution(row: dict[str, Any]) -> dict[str, Any]:
    """One run's cold-prompt breakdown: anchors, blocking phases, overlap."""
    spans = row.get("span_summary", {})
    hook = spans.get("before_agent_start.hook")
    phases = {name: spans[name]["first_duration_ms"] for name in PHASE_SPANS if name in spans}
    hook_start = hook["first_start_rel_ms"] if hook else None
    hook_end = hook["first_end_rel_ms"] if hook else None
    background_overlap = 0.0
    background_detail: dict[str, float] = {}
    if hook_start is not None and hook_end is not None:
        for name in BACKGROUND_SPANS:
            entry = spans.get(name)
            if entry is None:
                continue
            start = entry["first_start_rel_ms"]
            end = entry["first_end_rel_ms"]
            overlap = max(0.0, min(end, hook_end) - max(start, hook_start))
            if overlap > 0:
                background_detail[name] = round(overlap, 3)
                background_overlap += overlap
    phases_sum = sum(phases.values())
    return {
        "arm": row["arm"],
        "rep": row["rep"],
        "cold_total_ms": row.get("cold_pre_dispatch_ms"),
        "anchors": row.get("anchors", {}),
        "hook_start_rel_ms": hook_start,
        "hook_ms": hook["first_duration_ms"] if hook else None,
        "phases_ms": phases,
        "phases_sum_ms": round(phases_sum, 3),
        "hook_residual_ms": (round(hook["first_duration_ms"] - phases_sum, 3) if hook else None),
        "bg_overlap_ms": round(background_overlap, 3),
        "bg_overlap_detail": background_detail,
        "session_start_hook_ms": spans.get("session_start.hook", {}).get("first_duration_ms"),
    }


def reconcile_arm(
    arm: str, rows: list[dict[str, Any]], baseline_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Paired cold-prompt reconciliation against the inert baseline."""
    pairs = []
    ordered = sorted(rows, key=lambda r: r["rep"])
    baseline_ordered = sorted(baseline_rows, key=lambda r: r["rep"])
    for row, base in zip(ordered, baseline_ordered, strict=False):
        cand_anchors = row.get("anchors", {})
        base_anchors = base.get("anchors", {})
        if "agent_start" not in cand_anchors or "agent_start" not in base_anchors:
            continue
        if "message_end:user" not in cand_anchors or "message_end:user" not in base_anchors:
            continue
        attribution = cold_attribution(row)
        delta_total = row["cold_pre_dispatch_ms"] - base["cold_pre_dispatch_ms"]
        delta_boot = cand_anchors["agent_start"]["perf_ms"] - base_anchors["agent_start"]["perf_ms"]
        cand_after = (
            cand_anchors["message_end:user"]["perf_ms"] - cand_anchors["agent_start"]["perf_ms"]
        )
        base_after = (
            base_anchors["message_end:user"]["perf_ms"] - base_anchors["agent_start"]["perf_ms"]
        )
        delta_after = cand_after - base_after
        hook_ms = attribution["hook_ms"] or 0.0
        explained = hook_ms + delta_boot
        pairs.append(
            {
                **attribution,
                "baseline_cold_total_ms": base["cold_pre_dispatch_ms"],
                "delta_total_ms": round(delta_total, 1),
                "delta_boot_ms": round(delta_boot, 1),
                "delta_after_agent_start_ms": round(delta_after, 1),
                "explained_ms": round(explained, 1),
                "explained_share": round(explained / delta_total, 3) if delta_total else None,
                "boot_share": round(delta_boot / delta_total, 3) if delta_total else None,
            }
        )
    if not pairs:
        return {"arm": arm, "paired": [], "note": "no comparable inert pairs"}

    def median(key: str) -> float | None:
        values = [pair[key] for pair in pairs if pair.get(key) is not None]
        return round(statistics.median(values), 1) if values else None

    phases: dict[str, float] = {}
    for name in PHASE_SPANS:
        values = [pair["phases_ms"][name] for pair in pairs if name in pair["phases_ms"]]
        if values:
            phases[name] = round(statistics.median(values), 1)
    return {
        "arm": arm,
        "n": len(pairs),
        "paired": pairs,
        "median_cold_total_ms": median("cold_total_ms"),
        "median_delta_total_ms": median("delta_total_ms"),
        "median_delta_boot_ms": median("delta_boot_ms"),
        "median_delta_after_agent_start_ms": median("delta_after_agent_start_ms"),
        "median_hook_ms": median("hook_ms"),
        "median_hook_start_rel_ms": median("hook_start_rel_ms"),
        "median_phases_ms": phases,
        "median_phases_sum_ms": median("phases_sum_ms"),
        "median_hook_residual_ms": median("hook_residual_ms"),
        "median_bg_overlap_ms": median("bg_overlap_ms"),
        "median_session_start_hook_ms": median("session_start_hook_ms"),
        "median_explained_ms": median("explained_ms"),
        "median_explained_share": median("explained_share"),
        "median_boot_share": median("boot_share"),
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    canonical = WORKTREE.parents[1] if WORKTREE.parent.name == ".worktrees" else WORKTREE
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--corpus-home", default=str(canonical))
    parser.add_argument("--out", required=True)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--model", default="deepseek/deepseek-flash")
    parser.add_argument("--thinking", default="low")
    parser.add_argument("--project-id", default="second-brain")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--omp", default="omp")
    parser.add_argument(
        "--arms", default="inert,candidate-current,candidate-once,candidate-helper-lazy"
    )
    parser.add_argument(
        "--candidate-extension",
        default=str(WORKTREE / "brainstem/prime-extension/src/index.ts"),
    )
    parser.add_argument("--candidate-python", default=str(WORKTREE / ".venv/Scripts/python.exe"))
    parser.add_argument(
        "--candidate-config-dir",
        default=str(WORKTREE / "config"),
        help="the candidate's shipped config; overlaid on every Brain arm's home so the run "
        "measures the configuration that would be deployed, not the live home's",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=0.0,
        help="idle pause before each run so a previous run's background children cannot "
        "overlap the next host's startup",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="v3-e01-"))
    arms = _arms_module()
    probe = _probe_module()
    snapshot = work / "snapshot"
    corpus = arms.snapshot_corpus(Path(args.corpus_home), snapshot)

    selected = [name for name in args.arms.split(",") if name]
    for name in selected:
        if name not in ARM_SPECS:
            raise SystemExit(f"unknown arm: {name}")
    manifest = {
        "harness": "scripts/v3_e01_latency.py",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "omp_version": subprocess.run(
            [args.omp, "--version"], capture_output=True, text=True, check=False
        ).stdout.strip(),
        "model": args.model,
        "thinking": args.thinking,
        "project_id": args.project_id,
        "reps": args.reps,
        "seed": args.seed,
        "corpus": corpus,
        "prompts": {"cold": COLD_PROMPT, "warm": WARM_PROMPT},
        "arms": {name: ARM_SPECS[name] for name in selected},
        "candidate_python": args.candidate_python,
        "candidate_config": {
            path.name: arms._sha256(path, normalize_newlines=True)
            for path in sorted(Path(args.candidate_config_dir).glob("*.toml"))
        },
        "conditions": (
            "One fresh host process per run, two prompts per process (index 0 = cold, "
            "index 1 = warm), fresh corpus snapshot per run, trace file per run."
        ),
    }

    rng = random.Random(args.seed)
    runs: list[dict[str, Any]] = []
    for rep in range(args.reps):
        order = list(selected)
        rng.shuffle(order)
        for position, arm in enumerate(order):
            spec = ARM_SPECS[arm]
            run_dir = work / f"run{len(runs):04d}"
            (run_dir / "proj").mkdir(parents=True)
            env = clean_env()
            ext = (
                str(WORKTREE / spec["extension"])
                if spec["extension"] != "candidate"
                else args.candidate_extension
            )
            tail = [
                "-p",
                "--mode",
                "json",
                "--model",
                args.model,
                "--thinking",
                args.thinking,
                "--no-session",
                "--session-dir",
                str(run_dir / "sessions"),
                "--cwd",
                str(run_dir / "proj"),
                "--no-extensions",
                "-e",
                ext,
                COLD_PROMPT,
                WARM_PROMPT,
            ]
            trace_path = run_dir / "e01-trace.jsonl"
            if spec["brain"]:
                home = run_dir / "home"
                shutil.copytree(snapshot, home)
                shutil.copytree(args.candidate_config_dir, home / "config", dirs_exist_ok=True)
                env["SECOND_BRAIN_HOME"] = str(home)
                env["SECOND_BRAIN_PYTHON"] = args.candidate_python
                env["SECOND_BRAIN_PROJECT"] = args.project_id
                env["SECOND_BRAIN_E01_TRACE"] = str(trace_path)
                env.update(spec["env"])
            time.sleep(args.settle_seconds)
            result = run_host(args.omp, tail, env, args.timeout, out / f"{arm}-{rep}.jsonl")
            raw = result.pop("raw")
            costs = prompt_costs(result["events"], result["launch_epoch_ms"])
            trace = read_trace(trace_path)
            summary = probe.summarize_arm(raw, token=MEMORY_TOKEN)
            brain_messages = [
                message
                for message in summary.get("custom_messages", [])
                if str(message.get("customType", "")).startswith("brain.")
            ]
            record: dict[str, Any] = {
                "arm": arm,
                "rep": rep,
                "order_position": position,
                "returncode": result["returncode"],
                "wall_ms": result["wall_ms"],
                "launch_epoch_ms": round(result["launch_epoch_ms"], 1),
                "prompt_costs": costs,
                "brain_visible_chars": sum(int(m.get("chars") or 0) for m in brain_messages),
                "memory_delivered": bool(
                    summary.get("token_evidence", {}).get("injected_context_records")
                ),
                "anchors": anchor_map(result["events"]),
                "span_summary": summarize_spans(trace, result["launch_epoch_ms"]),
                "event_count": len(result["events"]),
                "stderr_tail": result["stderr_tail"],
            }
            if len(costs) >= 2:
                record["cold_pre_dispatch_ms"] = costs[0]["pre_dispatch_ms"]
                record["warm_pre_dispatch_ms"] = costs[1]["pre_dispatch_ms"]
                record["turn2"] = turn2_metrics(
                    result["events"], record["anchors"], record["span_summary"]
                )
                cold_mark = user_message_marks(result["events"])[0]
                record["cold_reconciliation"] = reconcile_cold(
                    cold_mark["perf_ms"], cold_mark["epoch_ms"], result["launch_epoch_ms"], trace
                )
            runs.append(record)
            print(
                json.dumps(
                    {
                        "arm": arm,
                        "rep": rep,
                        "cold_ms": record.get("cold_pre_dispatch_ms"),
                        "warm_ms": record.get("warm_pre_dispatch_ms"),
                        "turn2_ms": (record.get("turn2") or {}).get("turn2_pre_dispatch_ms"),
                        "turn2_hook_ms": (record.get("turn2") or {}).get("turn2_hook_ms"),
                        "brain_chars": record["brain_visible_chars"],
                        "memory": record["memory_delivered"],
                    }
                ),
                flush=True,
            )

    aggregate: dict[str, Any] = {}
    for arm in selected:
        rows = [row for row in runs if row["arm"] == arm]
        cold = [row["cold_pre_dispatch_ms"] for row in rows if "cold_pre_dispatch_ms" in row]
        warm = [row["warm_pre_dispatch_ms"] for row in rows if "warm_pre_dispatch_ms" in row]
        aggregate[arm] = {
            "n": len(rows),
            "failures": sum(1 for row in rows if row["returncode"] != 0),
            "cold_ms": cold,
            "warm_ms": warm,
            "cold_median_ms": round(statistics.median(cold), 1) if cold else None,
            "warm_median_ms": round(statistics.median(warm), 1) if warm else None,
            "brain_visible_chars": [row["brain_visible_chars"] for row in rows],
            "memory_delivered": [row["memory_delivered"] for row in rows],
            "span_medians_ms": _span_medians(rows),
        }

    for arm in selected:
        rows = [row for row in runs if row["arm"] == arm]
        turn2 = [row["turn2"] for row in rows if row.get("turn2") is not None]
        if not turn2:
            continue
        aggregate[arm]["turn2_pre_dispatch_ms"] = [
            entry["turn2_pre_dispatch_ms"] for entry in turn2
        ]
        aggregate[arm]["turn2_hook_ms"] = [entry["turn2_hook_ms"] for entry in turn2]
        aggregate[arm]["turn2_batched_ms"] = [entry["turn2_batched_ms"] for entry in turn2]
        aggregate[arm]["turn2_median_ms"] = round(
            statistics.median([entry["turn2_pre_dispatch_ms"] for entry in turn2]), 1
        )
        hooks = [entry["turn2_hook_ms"] for entry in turn2 if entry["turn2_hook_ms"] is not None]
        aggregate[arm]["turn2_hook_median_ms"] = (
            round(statistics.median(hooks), 1) if hooks else None
        )

    inert_turn2 = aggregate.get("inert", {}).get("turn2_pre_dispatch_ms")
    if inert_turn2:
        inert_turn2_sorted = sorted(inert_turn2)
        for arm in selected:
            values = aggregate[arm].get("turn2_pre_dispatch_ms")
            if not values or arm == "inert":
                continue
            paired = [
                value - base
                for value, base in zip(sorted(values), inert_turn2_sorted, strict=False)
            ]
            aggregate[arm]["turn2_incremental_ms"] = round(statistics.median(paired), 1)

    inert_cold = aggregate.get("inert", {}).get("cold_median_ms")
    inert_warm = aggregate.get("inert", {}).get("warm_median_ms")
    for arm, data in aggregate.items():
        if arm == "inert":
            continue
        if inert_cold is not None and data["cold_median_ms"] is not None:
            data["cold_incremental_ms"] = round(data["cold_median_ms"] - inert_cold, 1)
        if inert_warm is not None and data["warm_median_ms"] is not None:
            data["warm_incremental_ms"] = round(data["warm_median_ms"] - inert_warm, 1)

    reconciliation: dict[str, Any] = {}
    if "inert" in aggregate:
        inert_rows = [row for row in runs if row["arm"] == "inert"]
        for arm in selected:
            if arm == "inert":
                continue
            reconciliation[arm] = reconcile_arm(
                arm, [row for row in runs if row["arm"] == arm], inert_rows
            )

    (out / "reconciliation.json").write_text(json.dumps(reconciliation, indent=1), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "runs.json").write_text(json.dumps(runs, indent=1), encoding="utf-8")
    (out / "aggregate.json").write_text(json.dumps(aggregate, indent=1), encoding="utf-8")
    print(json.dumps(aggregate, indent=1))
    shutil.rmtree(work, ignore_errors=True)
    return 0


def _span_medians(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Median per-span durations across the runs of one arm."""
    collected: dict[str, list[float]] = {}
    for row in rows:
        for name, stats in row.get("span_summary", {}).items():
            collected.setdefault(name, []).append(stats["median_ms"])
    return {name: round(statistics.median(values), 3) for name, values in sorted(collected.items())}


if __name__ == "__main__":
    sys.exit(main())
