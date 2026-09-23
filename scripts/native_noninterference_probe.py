"""Native-orchestration non-interference probe (M00-NATIVE-ORCH-01).

Explicitly invoked evidence tool, not part of any runtime path. It runs the
installed host CLI in print/JSON mode against two extension conditions
(Second Brain absent vs. loaded from this repository) and compares only what
the *host* surfaced: whether a native single spawn and a native batch spawn
completed, and whether any Brain-side interference marker appeared.

Safety properties (do not relax them):
  * every arm runs with ``--no-session`` into a throwaway session directory;
  * the project directory is an empty temp directory;
  * the Brain-on arm gets a disposable ``SECOND_BRAIN_HOME``, so no arm can
    read or write live Second Brain state;
  * the probe never loads a production extension by default, and when it is
    asked to load one (``--installed``) that arm also gets the disposable home;
  * the disposable brain home is removed unless ``--keep-home`` is passed.

Usage:
    python scripts/native_noninterference_probe.py --out docs/intake/m00-evidence
    python scripts/native_noninterference_probe.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SINGLE_PROMPT = (
    "Call the task tool exactly once, with agent 'sonic' and task "
    "'Reply with exactly: PROBE-OK. Do no other work.' Do not call any other tool. "
    "Then output one line of the form: RESULT <subagent id or status>"
)
BATCH_PROMPT = (
    "Call the task tool exactly once with a tasks array of exactly two items, both "
    "with agent 'sonic' and names ProbeA and ProbeB, each tasked with "
    "'Reply with exactly: PROBE-OK. Do no other work.' Do not call any other tool. "
    "Then output one line of the form: RESULT <how many subagent results you received>"
)

# Markers that mean Second Brain interfered with host orchestration. The set is
# derived from the removed governed-orchestration subsystem, so its absence in a
# Brain-on run is the observation this probe exists to make.
INTERFERENCE_MARKERS = (
    "UNAUTHORIZED_COORDINATOR",
    "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE",
    "BRAIN_WORKER_ADMISSION",
    "brain_worker_admission",
    "driver_contract_",
    "orchestrator_policy_violation",
    "reserved_budget_required",
)

# Proves the extractor can see interference at all; a probe that cannot detect a
# marker is not evidence of its absence. Exercised by --self-test.
SELF_TEST_SAMPLE = "\n".join(
    [
        json.dumps(
            {
                "type": "tool_execution_start",
                "toolName": "task",
                "args": {"tasks": [{"name": "A", "agent": "sonic"}]},
            }
        ),
        json.dumps(
            {
                "type": "tool_execution_end",
                "toolName": "task",
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE",
                        }
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "RESULT none"}],
                },
            }
        ),
    ]
)


def _spawn_names(args: dict) -> tuple[list[str], list[str]]:
    """(names, agents) requested in one task-tool call, single or batch shape."""
    tasks = args.get("tasks")
    if isinstance(tasks, list):
        return (
            [str(t.get("name", "")) for t in tasks if isinstance(t, dict)],
            [str(t.get("agent", "")) for t in tasks if isinstance(t, dict)],
        )
    if args.get("task") is not None:
        return ([str(args.get("name", ""))], [str(args.get("agent", ""))])
    return ([], [])


def summarize_arm(raw: str) -> dict[str, Any]:
    """Host-observable summary of one arm's JSON event stream."""
    spawns: list[dict[str, Any]] = []
    other_tools: list[str] = []
    final_text: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "tool_execution_start":
            name = event.get("toolName")
            if name == "task":
                names, agents = _spawn_names(event.get("args") or {})
                spawns.append({"names": names, "agents": agents})
            else:
                other_tools.append(str(name))
        elif kind == "tool_execution_end" and event.get("toolName") == "task":
            text = json.dumps(event.get("result"))
            if spawns:
                spawns[-1]["result"] = text[:300]
                spawns[-1]["refused"] = "Spawned" not in text
        elif kind == "message_end" and (event.get("message") or {}).get("role") == "assistant":
            for part in (event["message"].get("content") or []):
                if part.get("type") == "text":
                    final_text.append(str(part.get("text", "")))

    markers = {name: raw.count(name) for name in INTERFERENCE_MARKERS}
    return {
        "spawn_calls": len(spawns),
        "spawns": spawns,
        "spawned_agents": [n for s in spawns if not s.get("refused") for n in s["names"]],
        "refused_spawns": [n for s in spawns if s.get("refused") for n in s["names"]],
        "other_tool_calls": other_tools,
        "final_text": final_text[-1:] if final_text else [],
        "interference_markers": {k: v for k, v in markers.items() if v},
        "interference_total": sum(markers.values()),
    }


def run_arm(
    name: str,
    *,
    prompt: str,
    extension: Path | None,
    brain_home: Path | None,
    brain_python: Path,
    model: str,
    omp: str,
    timeout: int,
    workdir: Path,
) -> dict[str, Any]:
    tmp = workdir / name
    (tmp / "proj").mkdir(parents=True, exist_ok=True)
    cmd = [
        omp,
        "-p",
        "--mode",
        "json",
        "--model",
        model,
        "--no-session",
        "--session-dir",
        str(tmp / "sessions"),
        "--cwd",
        str(tmp / "proj"),
        "--no-extensions",
    ]
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    if extension is not None:
        assert brain_home is not None
        cmd += ["-e", str(extension)]
        env["SECOND_BRAIN_HOME"] = str(brain_home)
        env["SECOND_BRAIN_PYTHON"] = str(brain_python)
    cmd.append(prompt)

    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc = None
        raw_out = (
            exc.stdout.decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else exc.stdout
        )
        out = raw_out or ""
        err = f"TIMEOUT after {timeout}s"
    wall = round(time.time() - started, 1)
    (tmp / "raw.jsonl").write_text(out, encoding="utf-8")
    (tmp / "stderr.txt").write_text(err, encoding="utf-8")

    summary = summarize_arm(out)
    summary.update(
        {
            "arm": name,
            "extension": str(extension) if extension else None,
            "returncode": rc,
            "wall_seconds": wall,
            "raw_path": str(tmp / "raw.jsonl"),
            "stderr_tail": err[-400:],
        }
    )
    return summary


def build_arms(
    extension: Path | None, installed: Path | None
) -> list[tuple[str, str, Path | None]]:
    arms: list[tuple[str, str, Path | None]] = [
        ("brain_off_single", SINGLE_PROMPT, None),
        ("brain_on_single", SINGLE_PROMPT, extension),
        ("brain_off_batch", BATCH_PROMPT, None),
        ("brain_on_batch", BATCH_PROMPT, extension),
    ]
    if installed is not None:
        # Sensitivity control: the pre-removal build installed on this host. Its
        # refusal of the same prompt is what makes the candidate arms' clean
        # result meaningful rather than an artefact of an insensitive probe.
        arms.append(("installed_build_single", SINGLE_PROMPT, installed))
    return arms


def verdicts(arms: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {str(a["arm"]): a for a in arms}
    on_single = by_name.get("brain_on_single", {})
    on_batch = by_name.get("brain_on_batch", {})
    off_single = by_name.get("brain_off_single", {})
    control = by_name.get("installed_build_single")

    def spawned(arm: dict[str, Any], count: int) -> bool:
        return len(arm.get("spawned_agents") or []) == count

    return {
        "C1_native_single_spawn_succeeds": bool(spawned(on_single, 1)),
        "C2_native_batch_spawn_succeeds": bool(spawned(on_batch, 2)),
        "C5_no_brain_settlement_permission_needed": bool(
            spawned(on_single, 1) and not on_single.get("interference_total")
        ),
        "C6_no_unauthorized_coordinator": "UNAUTHORIZED_COORDINATOR"
        not in (on_single.get("interference_markers") or {}),
        "C7_no_worker_admission_required": bool(spawned(on_single, 1)),
        "C8_no_budget_reservation_prerequisite": "reserved_budget_required"
        not in (on_single.get("interference_markers") or {}),
        "C9_no_coordinator_instruction_injection": not any(
            k in (on_single.get("interference_markers") or {})
            for k in ("driver_contract_", "orchestrator_policy_violation")
        ),
        "C12_brain_on_matches_brain_off_spawn_semantics": (
            [s["names"] for s in (on_single.get("spawns") or [])]
            == [s["names"] for s in (off_single.get("spawns") or [])]
            and bool(spawned(on_single, 1))
            and bool(spawned(off_single, 1))
        ),
        "probe_sensitivity_demonstrated": (
            None
            if control is None
            else not spawned(control, 1) and bool(control.get("interference_total"))
        ),
    }


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(repo / "docs/intake/m00-evidence"))
    ap.add_argument("--model", default="deepseek/deepseek-flash")
    ap.add_argument("--extension", default=str(repo / "brainstem/prime-extension/src/index.ts"))
    ap.add_argument("--omp", default="omp")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--brain-python", default=sys.executable)
    ap.add_argument(
        "--installed", default="", help="pre-removal extension entry, for a sensitivity control"
    )
    ap.add_argument(
        "--keep-home", action="store_true", help="keep the disposable brain home for inspection"
    )
    ap.add_argument(
        "--self-test", action="store_true", help="check the extractor, run no host process"
    )
    args = ap.parse_args(argv)

    if args.self_test:
        seen = summarize_arm(SELF_TEST_SAMPLE)
        print(json.dumps(seen, indent=2))
        ok = (
            seen["interference_total"] == 1
            and seen["spawn_calls"] == 1
            and seen["refused_spawns"] == ["A"]
            and seen["spawned_agents"] == []
        )
        print(
            f"extractor: markers={seen['interference_total']} "
            f"spawns={seen['spawn_calls']} refused={seen['refused_spawns']} ok={ok}"
        )
        return 0 if ok else 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(args.extension)
    installed = Path(args.installed) if args.installed else None
    workdir = Path(tempfile.mkdtemp(prefix="ni-arms-"))
    stamp = time.strftime("%Y%m%d")
    # Every arm gets its own disposable brain home, and each arm's raw stream is
    # copied beside the JSON. A single shared home could not attribute extension
    # activity to an arm (the installed control also writes there), and a payload
    # that only points at temp files is not evidence a later session can open.
    stream_dir = out_dir / f"native-noninterference-{stamp}"
    stream_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for name, prompt, ext in build_arms(extension, installed):
        print(f"[arm] {name} extension={ext}", file=sys.stderr)
        home = Path(tempfile.mkdtemp(prefix=f"ni-brain-home-{name}-")) if ext else None
        try:
            row = run_arm(
                name,
                prompt=prompt,
                extension=ext,
                brain_home=home,
                brain_python=Path(args.brain_python),
                model=args.model,
                omp=args.omp,
                timeout=args.timeout,
                workdir=workdir,
            )
            if home is not None:
                # Does the extension actually run in THIS arm? A loaded but inert
                # extension would make a clean result meaningless.
                row["brain_home_files"] = sorted(
                    str(f.relative_to(home)) for f in home.rglob("*") if f.is_file()
                )[:40]
            stream = Path(str(row["raw_path"]))
            archived = stream_dir / f"{name}.jsonl"
            if stream.is_file():
                shutil.copyfile(stream, archived)
                row["raw_stream"] = str(archived.relative_to(out_dir.parent.parent))
        finally:
            if home is not None and not args.keep_home:
                shutil.rmtree(home, ignore_errors=True)
        results.append(row)

    payload = {
        "probe": "native-noninterference",
        "date": stamp,
        "model": args.model,
        "extension": str(extension),
        "installed_control": str(installed) if installed else None,
        "arm_workdir": str(workdir),
        "arms": results,
        "verdicts": verdicts(results),
    }
    (out_dir / f"native-noninterference-{stamp}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    for row in results:
        print(
            f"{row['arm']}: rc={row['returncode']} wall={row['wall_seconds']}s "
            f"spawn_calls={row['spawn_calls']} spawned={row['spawned_agents']} "
            f"refused={row['refused_spawns']} interference={row['interference_total']}"
        )
    print(json.dumps(payload["verdicts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
