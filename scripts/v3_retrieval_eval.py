"""V3 S2 retrieval/decision evaluation (PERF-01, RET-02, RET-05 dev evidence).

Runs the real per-turn decision pipeline over a JSONL case file against a read-only
snapshot of the live corpus and reports, per case, whether the decision matched the
expectation, plus the aggregate retrieval (recall) and abstention (false-injection)
metrics, the injected packet token count and the per-call latency.

The live corpus is never written: the SQLite database is copied through the backup API
from a ``?mode=ro`` handle and the canonical text roots are copied, into a fresh temp
home (same method as ``scripts/v3_matched_arms.py::snapshot_corpus``). Every write the
pipeline performs (deliveries, telemetry, decisions, memories) lands in that temp home.

The same file is used for both arms, so the interpreter decides which source runs:

  candidate  env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe \\
                 scripts/v3_retrieval_eval.py --cases outputs/reports/v3-s2/dev/cases.jsonl
  m00        env -u PYTHONHOME -u PYTHONPATH \
             C:/Users/assas/Documents/The-Second-Brain/.venv/Scripts/python.exe \
                 scripts/v3_retrieval_eval.py --cases outputs/reports/v3-s2/dev/cases.jsonl

Case file format (one JSON object per line; unknown keys are ignored):

  {"id": "D01", "category": "no_benefit_overlap", "prompt": "...", "expect": []}
  {"id": "D02", "category": "memory_short", "prompt": "...", "expect": ["mem-..."]}

``expect`` lists the memory ids the case needs. An empty list declares a case that must
abstain. Optional per-case keys: ``project_id``, ``cwd``, ``role``, ``agent``, ``note``.

Exit status is 0 when every case passes and 1 otherwise (so a held-out run is a gate);
``--report PATH`` additionally writes the full machine-readable report.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ID = "second-brain"
DEFAULT_ROLE = "worker"
DEFAULT_AGENT = "driver"
SNAPSHOT_DIRS = ("config", "memory", "constitution", "templates")
# Warm-up query: a token that cannot match any memory, on a throwaway session, so the
# process-level one-time costs (FTS5 module create, config load, first migration check)
# are paid outside the measured cases.
WARMUP_PROMPT = "zzzzq-warmup-no-such-memory"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_corpus(source: Path, dest: Path) -> dict[str, Any]:
    """Copy one consistent corpus snapshot: SQLite backup + canonical text roots.

    Read-only against ``source``: the database is opened ``?mode=ro`` and copied with
    SQLite's online backup API; the text roots are copied, never modified.
    """
    dest.mkdir(parents=True, exist_ok=True)
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
    for name in ("state", "telemetry", "outputs", "engrams", "experiences"):
        (dest / name).mkdir(exist_ok=True)
    for name in ("VERSION",):
        if (source / name).is_file():
            shutil.copy2(source / name, dest / name)
    conn = sqlite3.connect(dest / "db" / "brain.sqlite")
    try:
        memories = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        schema = int(
            conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        )
        tagged = int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_index WHERE COALESCE(tags, '') <> ''"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return {
        "source": str(source),
        "db_sha256": _sha256(dest / "db" / "brain.sqlite"),
        "memories": memories,
        "schema_version": schema,
        "tagged_memories": tagged,
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:  # fail loudly: a malformed case file is a bug
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        prompt = case.get("prompt")
        expect = case.get("expect")
        forbid = case.get("forbid", [])
        if not isinstance(prompt, str) or not prompt.strip():
            raise SystemExit(f"{path}:{lineno}: 'prompt' must be a non-empty string")
        if not isinstance(expect, list) or not all(isinstance(v, str) for v in expect):
            raise SystemExit(f"{path}:{lineno}: 'expect' must be a list of memory ids")
        if not isinstance(forbid, list) or not all(isinstance(v, str) for v in forbid):
            raise SystemExit(f"{path}:{lineno}: 'forbid' must be a list of memory ids")
        case["forbid"] = forbid
        case.setdefault("id", f"case-{lineno}")
        case.setdefault("category", "uncategorised")
        cases.append(case)
    if not cases:
        raise SystemExit(f"{path}: no cases")
    return cases


def _runtime_identity() -> dict[str, Any]:
    import second_brain

    module = Path(second_brain.__file__).resolve()
    src = module.parents[1]
    return {"module": str(module), "interpreter": sys.executable, "src_root": str(src)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the S2 retrieval/decision eval")
    parser.add_argument("--cases", required=True, help="JSONL case file")
    parser.add_argument(
        "--source-home",
        default=None,
        help="Brain root to snapshot (default: $SECOND_BRAIN_HOME or the canonical home)",
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--role", default=DEFAULT_ROLE)
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    parser.add_argument("--cwd", default=None, help="host cwd passed to project resolution")
    parser.add_argument("--reps", type=int, default=1, help="repetitions per case")
    parser.add_argument("--warmup", action="store_true", help="one unmeasured warm-up call")
    parser.add_argument("--temp-root", default=None, help="where to place the snapshot")
    parser.add_argument("--keep", action="store_true", help="keep the temp snapshot")
    parser.add_argument("--report", default=None, help="write the full JSON report here")
    parser.add_argument("--quiet", action="store_true", help="aggregate only")
    args = parser.parse_args(argv)

    from second_brain import autoinject, contracts, paths

    source_home = Path(args.source_home) if args.source_home else paths.resolve_home()
    case_file = Path(args.cases)
    cases = _load_cases(case_file)

    temp_parent = Path(args.temp_root) if args.temp_root else None
    run_dir = Path(
        tempfile.mkdtemp(prefix="s2-retrieval-eval-", dir=str(temp_parent) if temp_parent else None)
    )
    home = run_dir / "home"
    started = time.perf_counter()
    snapshot = snapshot_corpus(source_home, home)
    snapshot_ms = (time.perf_counter() - started) * 1000.0

    def call_case(case: dict[str, Any], rep: int) -> dict[str, Any]:
        session_id = f"s2eval-{case['id']}-r{rep}"
        lifecycle = autoinject.BrainLifecycle(home)
        t0 = time.perf_counter()
        decision = lifecycle.prepare_injection(
            case["prompt"],
            project_id=case.get("project_id", args.project_id),
            agent_id=case.get("agent", args.agent),
            role_profile=case.get("role", args.role),
            session_id=session_id,
            branch_id="main",
            cwd=case.get("cwd", args.cwd),
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        packet = autoinject.render_packet(decision)
        return {
            "session_id": session_id,
            "decision": decision.decision.value,
            "reason": decision.reason.value if decision.reason is not None else None,
            "candidate_ids": list(decision.candidate_ids),
            "selected_ids": list(decision.selected_ids),
            "packet_tokens": decision.packet_token_size,
            "packet_chars": len(packet) if packet is not None else 0,
            "latency_ms": latency_ms,
            "injected": decision.decision is contracts.InjectionDecision.INJECT,
        }

    warmup_ms: float | None = None
    if args.warmup:
        t0 = time.perf_counter()
        warmup_case = {
            "id": "warmup",
            "prompt": WARMUP_PROMPT,
            "project_id": args.project_id,
        }
        call_case(warmup_case, 0)
        warmup_ms = (time.perf_counter() - t0) * 1000.0

    results: list[dict[str, Any]] = []
    for case in cases:
        expect = list(case["expect"])
        forbid = list(case.get("forbid", []))
        for rep in range(max(1, args.reps)):
            observed = call_case(case, rep)
            selected = observed["selected_ids"]
            candidates = observed["candidate_ids"]
            missing = [mid for mid in expect if mid not in selected]
            infringed = [mid for mid in forbid if mid in selected]
            if infringed:
                verdict, failure = "fail", "forbidden_memory_injected"
            elif expect and observed["injected"] and not missing:
                verdict, failure = "pass", None
            elif expect and not observed["injected"]:
                verdict, failure = "fail", "no_injection_miss"
            elif expect and missing:
                # Attribute the miss: was the required memory even retrieved?
                verdict = "fail"
                failure = (
                    "decision_stage_miss"
                    if all(mid in candidates for mid in missing)
                    else "retrieval_stage_miss"
                )
            elif not expect and observed["injected"]:
                verdict, failure = "fail", "false_injection"
            else:
                verdict, failure = "pass", None
            row = {
                "id": case["id"],
                "category": case.get("category"),
                "rep": rep,
                "expect": expect,
                "forbid": forbid,
                "verdict": verdict,
                "failure": failure,
                **observed,
            }
            results.append(row)
            if not args.quiet:
                print(
                    f"{row['id']:<4} r{rep} {row['category']:<24} {row['decision']:<11} "
                    f"reason={row['reason'] or '-':<18} selected={','.join(selected) or '-':<16} "
                    f"cand={len(candidates):<2} pkt_tok={row['packet_tokens'] or 0:<5} "
                    f"{row['latency_ms']:>7.1f} ms  {verdict.upper()}"
                    + (f" ({failure})" if failure else "")
                )

    memory_rows = [r for r in results if r["expect"]]
    no_benefit_rows = [r for r in results if not r["expect"]]
    recovered = [r for r in memory_rows if r["verdict"] == "pass"]
    false_injections = [r for r in no_benefit_rows if r["failure"] == "false_injection"]
    forbidden_rows = [r for r in results if r["failure"] == "forbidden_memory_injected"]
    latencies = sorted(r["latency_ms"] for r in results)
    injected_tokens = [r["packet_tokens"] for r in results if r["injected"] and r["packet_tokens"]]

    def pct(values: list[float], q: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
        return values[index]

    summary = {
        "cases_file": str(case_file),
        "cases": len(cases),
        "reps": max(1, args.reps),
        "project_id": args.project_id,
        "role": args.role,
        "runtime": _runtime_identity(),
        "snapshot": snapshot,
        "snapshot_ms": snapshot_ms,
        "warmup_ms": warmup_ms,
        "memory_cases": {
            "n": len(memory_rows),
            "recovered": len(recovered),
            "recall": (len(recovered) / len(memory_rows)) if memory_rows else None,
            "missed": sorted({r["id"] for r in memory_rows if r["verdict"] != "pass"}),
        },
        "no_benefit_cases": {
            "n": len(no_benefit_rows),
            "false_injections": len(false_injections),
            "false_injection_rate": (
                (len(false_injections) / len(no_benefit_rows)) if no_benefit_rows else None
            ),
            "offenders": sorted(
                f"{r['id']}:{','.join(r['selected_ids'])}" for r in false_injections
            ),
        },
        "forbidden_memories": {
            "violations": len(forbidden_rows),
            "offenders": sorted(
                f"{r['id']}:{','.join(sorted(set(r['forbid']) & set(r['selected_ids'])))}"
                for r in forbidden_rows
            ),
        },
        "latency_ms": {
            "median": statistics.median(latencies) if latencies else None,
            "p95": pct(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "packet_tokens": {
            "median": statistics.median(injected_tokens) if injected_tokens else None,
            "max": max(injected_tokens) if injected_tokens else None,
        },
        "decision_stage_misses": sorted(
            {r["id"] for r in results if r["failure"] == "decision_stage_miss"}
        ),
        "retrieval_stage_misses": sorted(
            {r["id"] for r in results if r["failure"] == "retrieval_stage_miss"}
        ),
        "failures": sorted(
            f"{r['id']}:{r['failure']}" for r in results if r["verdict"] != "pass"
        ),
        "results": results,
    }

    print()
    print(f"runtime        : {summary['runtime']['module']}")
    print(
        f"snapshot       : {snapshot['memories']} memories, schema {snapshot['schema_version']}, "
        f"db {snapshot['db_sha256'][:16]}, tagged {snapshot['tagged_memories']} "
        f"({snapshot_ms:.0f} ms copy)"
    )
    if warmup_ms is not None:
        print(f"warmup         : {warmup_ms:.1f} ms")
    print(
        f"memory cases   : {summary['memory_cases']['recovered']}/{summary['memory_cases']['n']} "
        f"recall={summary['memory_cases']['recall']} missed={summary['memory_cases']['missed']}"
    )
    print(
        f"no-benefit     : {summary['no_benefit_cases']['false_injections']} false injection(s) "
        f"of {summary['no_benefit_cases']['n']} "
        f"rate={summary['no_benefit_cases']['false_injection_rate']} "
        f"{summary['no_benefit_cases']['offenders']}"
    )
    print(
        f"latency ms     : median={summary['latency_ms']['median']:.1f} "
        f"p95={summary['latency_ms']['p95']:.1f} max={summary['latency_ms']['max']:.1f}"
        if latencies
        else "latency ms     : none"
    )
    print(f"failures       : {summary['failures']}")
    if args.report:
        Path(args.report).write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"report         : {args.report}")

    if args.keep:
        print(f"snapshot home  : {home}")
    else:
        # The pipeline's module-level cascade caches one SQLite connection per home;
        # release it first, or Windows keeps the snapshot's database file locked. The
        # M00 comparison source predates the release API, so fall back to its mapping.
        retriever = getattr(autoinject, "_CASCADE", None)
        release = getattr(retriever, "close_cached_connections", None)
        if callable(release):
            release(home)
        else:
            cache = getattr(retriever, "_cache_connections", None)
            stale = cache.pop(str(home.resolve()), None) if isinstance(cache, dict) else None
            if stale is not None:
                with contextlib.suppress(sqlite3.Error, OSError):
                    stale.close()
        try:
            shutil.rmtree(run_dir)
        except OSError as exc:  # a still-open handle must be visible, not silent
            print(f"snapshot home  : {home} (not removed: {exc})")
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
