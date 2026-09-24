"""V3 matched-arm measurement harness (VAL-01; evidence for PERF-01/02/03 and RET-02).

Arms share model, thinking level, prompt and corpus snapshot. Every run is a fresh
host process with a fresh copy of the snapshot, so no arm sees another arm's
deliveries, caches or ledger writes:

  native     omp --no-extensions
  inert      omp --no-extensions -e scripts/v3_inert_extension.ts   (hooks, no work)
  m00        omp --no-extensions -e <installed extension>  + production interpreter
  candidate  omp --no-extensions -e <this worktree's extension> + this worktree's venv

The canonical home is only read, once, through the SQLite backup API to build the
snapshot. Arm order is shuffled per repetition with a recorded seed. Timing is taken
from the harness clock at each stdout event line; model usage, provider response ids
and TTFT come from the host's own assistant message records.

Example:
  python scripts/v3_matched_arms.py --reps 2 --out outputs/reports/v3-s1/arms-pilot
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
SNAPSHOT_DIRS = ("config", "memory", "constitution", "templates")
MEMORY_TOKEN = "mem-a8d221e64549"

# RET-02 named regression prompts: verbatim from the M00 activation live arms
# (outputs/reports/m00-activation-20260924/live, 2026-09-24).
CONCISE = "In what order should database migrations be applied?"
INSTRUCTION_HEAVY = (
    "Answer from your current context only; do not read files or run shell commands. "
    "Question: in Second Brain, in what order should database migrations be applied? "
    "If your context contains a Second Brain memory packet, quote every memory id it lists "
    "(ids look like mem-xxxxxxxxxxxx). Then call the task tool exactly once with agent 'sonic' "
    "and the task 'Reply with exactly: CHILD-OK-391. Do no other work.' Call no tool other than "
    "task, plus hub only if you must wait for the child's result. Finish with exactly one line: "
    "RESULT <memory ids or NONE> CHILD <child reply or NONE>"
)
NO_BENEFIT = "Reply with exactly: NB-OK-17. Do not use any tools."
CASES = {
    "memory_concise": {"prompt": CONCISE, "token": MEMORY_TOKEN},
    "memory_instruction_heavy": {"prompt": INSTRUCTION_HEAVY, "token": MEMORY_TOKEN},
    "no_benefit": {"prompt": NO_BENEFIT, "token": None},
}
BRAIN_CUSTOM_PREFIX = "brain."


def _probe() -> Any:
    spec = importlib.util.spec_from_file_location(
        "native_noninterference_probe", WORKTREE / "scripts" / "native_noninterference_probe.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path, *, normalize_newlines: bool = False) -> str:
    data = path.read_bytes()
    if normalize_newlines:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}


def snapshot_corpus(source: Path, dest: Path) -> dict[str, Any]:
    """Copy one consistent corpus snapshot: SQLite backup + canonical text roots."""
    dest.mkdir(parents=True)
    (dest / "db").mkdir()
    src = sqlite3.connect(f"file:{(source / 'db' / 'brain.sqlite').as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(dest / "db" / "brain.sqlite")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for name in SNAPSHOT_DIRS:
        if (source / name).is_dir():
            shutil.copytree(source / name, dest / name)
    for marker in source.glob(".second-brain*"):
        if marker.is_file():
            shutil.copy2(marker, dest / marker.name)
    for name in ("VERSION",):
        if (source / name).is_file():
            shutil.copy2(source / name, dest / name)
    conn = sqlite3.connect(dest / "db" / "brain.sqlite")
    try:
        memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        schema = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        has_token = (
            conn.execute("SELECT 1 FROM memories WHERE memory_id = ?", (MEMORY_TOKEN,)).fetchone()
            is not None
        )
    finally:
        conn.close()
    return {
        "source": str(source),
        "db_sha256": _sha256(dest / "db" / "brain.sqlite"),
        "memories": memories,
        "schema_version": schema,
        "contains_regression_memory": has_token,
    }


def runtime_identity(python: Path) -> dict[str, Any]:
    """Imported source identity of an interpreter (PORT-02): what the arm really runs."""
    code = (
        "import json, pathlib, second_brain\n"
        "from second_brain import build_identity as b\n"
        "src = pathlib.Path(second_brain.__file__).resolve().parents[2]\n"
        "print(json.dumps({'module': second_brain.__file__, 'git_sha': b.git_sha(src),"
        " 'dirty': b.git_dirty(src), 'source_tree': b.source_tree_fingerprint(src)}))"
    )
    proc = subprocess.run(
        [str(python), "-c", code], capture_output=True, text=True, env=_clean_env(), check=False
    )
    if proc.returncode != 0:
        return {"python": str(python), "error": proc.stderr[-400:]}
    return {"python": str(python), **json.loads(proc.stdout)}


def extension_identity(entry: Path) -> dict[str, Any]:
    files = sorted(p for p in entry.parent.rglob("*.ts") if p.is_file())
    manifest = {p.relative_to(entry.parent).as_posix(): _sha256(p, normalize_newlines=True)
                for p in files}
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return {"entry": str(entry), "files": len(files), "lf_manifest_sha256": digest}


def run_once(
    omp: str,
    argv_tail: list[str],
    env: dict[str, str],
    timeout: int,
    raw_path: Path,
) -> dict[str, Any]:
    """Run one host process, stamping each JSON event line with the harness clock."""
    started = time.perf_counter()
    marks: dict[str, float] = {}
    lines: list[str] = []
    proc = subprocess.Popen(
        [omp, *argv_tail], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        env=env, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.stdout is not None
    timed_out = False
    for line in proc.stdout:
        now = round((time.perf_counter() - started) * 1000, 1)
        lines.append(line)
        if now > timeout * 1000:
            proc.kill()
            timed_out = True
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        role = (event.get("message") or {}).get("role") if isinstance(event, dict) else None
        key = f"{kind}:{role}" if role else str(kind)
        marks.setdefault(key, now)
    stderr = proc.stderr.read() if proc.stderr else ""
    rc = proc.wait()
    raw = "".join(lines)
    raw_path.write_text(raw, encoding="utf-8")
    return {
        "returncode": None if timed_out else rc,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "marks_ms": marks,
        "raw": raw,
        "stderr_tail": stderr[-400:],
    }


def usage_totals(raw: str) -> dict[str, Any]:
    """Sum the host's own per-request usage; keep provider response ids for reconciliation."""
    totals = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "reasoningTokens": 0}
    cost = 0.0
    requests: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        if event.get("type") != "message_end" or not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        usage = message.get("usage") or {}
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
        cost += float((usage.get("cost") or {}).get("total") or 0.0)
        requests.append(
            {"response_id": message.get("responseId"), "ttft": message.get("ttft"),
             "duration": message.get("duration"), "model": message.get("model")}
        )
    return {**totals, "cost_total": round(cost, 8), "requests": requests}


def main(argv: list[str] | None = None) -> int:
    canonical = WORKTREE.parents[1] if WORKTREE.parent.name == ".worktrees" else WORKTREE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--corpus-home", default=str(canonical))
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--model", default="deepseek/deepseek-flash")
    ap.add_argument("--thinking", default="low")
    ap.add_argument(
        "--project-id",
        default="second-brain",
        help="host-observed project identity for Brain arms (the temp cwd is unregistered)",
    )
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--omp", default="omp")
    ap.add_argument("--arms", default="native,inert,m00,candidate")
    ap.add_argument("--cases", default=",".join(CASES))
    ap.add_argument(
        "--m00-extension",
        default=str(Path.home() / ".omp/agent/extensions/second-brain/index.ts"),
    )
    ap.add_argument("--m00-python", default=str(canonical / ".venv/Scripts/python.exe"))
    ap.add_argument(
        "--candidate-extension", default=str(WORKTREE / "brainstem/prime-extension/src/index.ts")
    )
    ap.add_argument("--candidate-python", default=str(WORKTREE / ".venv/Scripts/python.exe"))
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="v3-arms-"))
    probe = _probe()
    snapshot = work / "snapshot"
    corpus = snapshot_corpus(Path(args.corpus_home), snapshot)
    arms: dict[str, dict[str, Any]] = {
        "native": {"extension": None, "python": None},
        "inert": {"extension": WORKTREE / "scripts/v3_inert_extension.ts", "python": None},
        "m00": {"extension": Path(args.m00_extension), "python": Path(args.m00_python)},
        "candidate": {
            "extension": Path(args.candidate_extension), "python": Path(args.candidate_python),
        },
    }
    selected_arms = [a for a in args.arms.split(",") if a]
    selected_cases = [c for c in args.cases.split(",") if c]
    manifest = {
        "harness": "scripts/v3_matched_arms.py",
        "harness_sha256": _sha256(Path(__file__), normalize_newlines=True),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "omp_version": subprocess.run([args.omp, "--version"], capture_output=True, text=True,
                                      check=False).stdout.strip(),
        "model": args.model,
        "thinking": args.thinking,
        "project_id": args.project_id,
        "reps": args.reps,
        "seed": args.seed,
        "corpus": corpus,
        "cases": {c: CASES[c] for c in selected_cases},
        "arms": {
            name: {
                "extension": extension_identity(spec["extension"]) if spec["extension"] else None,
                "runtime": runtime_identity(spec["python"]) if spec["python"] else None,
            }
            for name, spec in arms.items() if name in selected_arms
        },
        "conditions": (
            "Every run is a fresh host process with a fresh copy of the corpus snapshot; "
            "no in-process warm state. rep 0 is the first run of each arm/case in this "
            "invocation (OS file cache cold for that arm); later reps are OS-cache warm."
        ),
    }
    rng = random.Random(args.seed)
    runs: list[dict[str, Any]] = []
    for case in selected_cases:
        spec_case = CASES[case]
        if spec_case["token"] and not corpus["contains_regression_memory"]:
            runs.append({"case": case, "status": "NOT_RUN", "reason": "memory absent from corpus"})
            continue
        for rep in range(args.reps):
            order = list(selected_arms)
            rng.shuffle(order)
            for position, arm in enumerate(order):
                spec = arms[arm]
                # Same-length paths for every arm: the cwd is model-visible, so an
                # arm name in it would skew the input-token comparison.
                run_dir = work / f"run{len(runs):04d}"
                (run_dir / "proj").mkdir(parents=True)
                env = _clean_env()
                tail = ["-p", "--mode", "json", "--model", args.model, "--thinking", args.thinking,
                        "--no-session", "--session-dir", str(run_dir / "sessions"),
                        "--cwd", str(run_dir / "proj"), "--no-extensions"]
                if spec["extension"] is not None:
                    tail += ["-e", str(spec["extension"])]
                if spec["python"] is not None:
                    home = run_dir / "home"
                    shutil.copytree(snapshot, home)
                    env["SECOND_BRAIN_HOME"] = str(home)
                    env["SECOND_BRAIN_PYTHON"] = str(spec["python"])
                    env["SECOND_BRAIN_PROJECT"] = args.project_id
                tail.append(spec_case["prompt"])
                raw_path = out / f"{case}-{arm}-{rep}.jsonl"
                result = run_once(args.omp, tail, env, args.timeout, raw_path)
                raw = result.pop("raw")
                summary = probe.summarize_arm(raw, token=spec_case["token"])
                brain_messages = [m for m in summary.get("custom_messages", [])
                                  if str(m.get("customType", "")).startswith(BRAIN_CUSTOM_PREFIX)]
                runs.append({
                    "case": case, "arm": arm, "rep": rep, "order_position": position,
                    "returncode": result["returncode"], "wall_ms": result["wall_ms"],
                    "marks_ms": result["marks_ms"], "stderr_tail": result["stderr_tail"],
                    "brain_custom_messages": [
                        {"customType": m.get("customType"), "chars": m.get("chars")}
                        for m in brain_messages
                    ],
                    "brain_visible_chars": sum(int(m.get("chars") or 0) for m in brain_messages),
                    "memory_delivered": bool(
                        spec_case["token"]
                        and summary.get("token_evidence", {}).get("injected_context_records")
                    ),
                    "tool_calls": summary.get("other_tool_calls", []),
                    "spawned_agents": summary.get("spawned_agents", []),
                    "final_text": summary.get("final_text", []),
                    "usage": usage_totals(raw),
                })
                print(json.dumps({k: runs[-1][k] for k in
                                  ("case", "arm", "rep", "wall_ms", "brain_visible_chars",
                                   "memory_delivered")}), flush=True)
    aggregate: dict[str, Any] = {}
    for case in selected_cases:
        for arm in selected_arms:
            rows = [r for r in runs if r.get("case") == case and r.get("arm") == arm]
            if not rows:
                continue
            walls = [r["wall_ms"] for r in rows]
            prep = [r["marks_ms"]["message_end:user"] for r in rows
                    if "message_end:user" in r["marks_ms"]]
            prep_median = round(statistics.median(prep), 1) if prep else None
            aggregate[f"{case}/{arm}"] = {
                "n": len(rows),
                "failures": sum(1 for r in rows if r["returncode"] != 0),
                "wall_ms_median": round(statistics.median(walls), 1),
                "to_user_message_end_ms_median": prep_median,
                "brain_visible_chars": [r["brain_visible_chars"] for r in rows],
                "memory_delivered": [r["memory_delivered"] for r in rows],
                "input_tokens": [r["usage"]["input"] + r["usage"]["cacheRead"] for r in rows],
                "cost_total": round(sum(r["usage"]["cost_total"] for r in rows), 6),
            }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "runs.json").write_text(json.dumps(runs, indent=1), encoding="utf-8")
    (out / "aggregate.json").write_text(json.dumps(aggregate, indent=1), encoding="utf-8")
    print(json.dumps(aggregate, indent=1))
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
