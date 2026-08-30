"""P3 Promotion Campaign Orchestrator — REAL external Antigravity agents only.

This script is an ORCHESTRATOR. It can never implement task solutions and can
never invent economics:

- task prompts come from the frozen fixture `TASK.md`;
- every arm is executed by a REAL external Antigravity agent process (`agy`);
- acceptance comes from the deterministic JUDGE.md oracle executed AFTER the
  agent run (anti-tamper: pristine oracle restored from the fixture);
- usage/tokens/turns/tools come ONLY from the real `agy` stream-json output
  and the Brain's hook telemetry;
- evidence is written only when the validity guards pass (see `validate_arm`).

If the external Antigravity CLI is unavailable, the runner stops at
READY_FOR_REAL_CAMPAIGN and prints the exact manual next action. It never
simulates a run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = (
    REPO_ROOT / "brainstem" / "prime-extension" / "tests" / "fixtures" / "lean-opportunity-tasks"
)
REPORTS_ROOT = REPO_ROOT / "outputs" / "reports" / "p3-promo-eval"
FROZEN_ENV_FILE = REPORTS_ROOT / "frozen-environment.json"

AGY_ENV = "P3_AGY_CMD"  # override for the agy executable path
AGY_MODEL_ENV = "P3_AGY_MODEL"  # exact frozen model slug
AGY_EFFORT_ENV = "P3_AGY_EFFORT"  # exact frozen effort
AGY_TIMEOUT_ENV = "P3_AGY_TIMEOUT_S"  # per-arm timeout (default 1200s)
AGY_PRINT_TIMEOUT_ENV = "P3_AGY_PRINT_TIMEOUT_S"  # agy --print-timeout (default 900s)
AGY_SKIP_PERMISSIONS_ENV = "P3_AGY_SKIP_PERMISSIONS"  # "1" = pass --dangerously-skip-permissions
AGY_PROJECT_ENV = "P3_AGY_PROJECT"  # optional Antigravity project id/name for hook wiring

# Frozen campaign order (plan §32). e01/e02/e03/e06 are retained genuine
# DeepSeek/Prime pairs — the runner never re-executes them, only reconciles.
TASKS = [
    ("e01", "e01-deploy-profiles", "deepseek", "OFF_FIRST"),
    ("e02", "e02-price-formatting", "deepseek", "ON_FIRST"),
    ("e03", "e03-log-pipeline", "deepseek", "OFF_FIRST"),
    ("e06", "e06-customer-sort", "deepseek", "OFF_FIRST"),
    ("e07", "e07-jsonc-config", "gemini", "ON_FIRST"),
    ("e08", "e08-call-count-analysis", "gemini", "OFF_FIRST"),
    ("e09", "e09-release-table", "gemini", "ON_FIRST"),
    ("e10", "e10-net-amount", "gemini", "OFF_FIRST"),
    ("e11", "e11-greet-trim", "gemini", "ON_FIRST"),
    ("e12", "e12-math-double", "gemini", "OFF_FIRST"),
    ("e13", "e13-crash-safe-store", "gemini", "ON_FIRST"),
    ("e14", "e14-debug-toggle", "gemini", "OFF_FIRST"),
    ("e15", "e15-order-validation", "gemini", "ON_FIRST"),
    ("e16", "e16-title-config", "gemini", "OFF_FIRST"),
]

MIN_WALL_MS = 10_000  # a real agent run cannot complete in less than 10s


def run_cmd(
    cmd: list[str] | str, cwd: Path, timeout: int = 300, shell: bool = False
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout, shell=shell
    )


def setup_workspace(fixture_dir: Path, target_dir: Path) -> None:
    """Fresh git-initialized arm copy with a baseline commit. No solution data."""
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    shutil.copytree(fixture_dir, target_dir, dirs_exist_ok=True)
    run_cmd(["git", "init", "-b", "main"], cwd=target_dir)
    run_cmd(["git", "config", "user.email", "eval@second-brain.local"], cwd=target_dir)
    run_cmd(["git", "config", "user.name", "P3 Eval"], cwd=target_dir)
    run_cmd(["git", "add", "-A"], cwd=target_dir)
    run_cmd(["git", "commit", "-m", "baseline"], cwd=target_dir)


def _judge_commands(fixture_dir: Path) -> list[str]:
    judge_text = (fixture_dir / "JUDGE.md").read_text(encoding="utf-8")
    cmds = []
    for line in judge_text.splitlines():
        m = re.match(r"^\s*\d+\.\s*`([^`]+)`", line)
        if m:
            cmds.append(m.group(1).replace("<FIXTURE_SOURCE>", str(fixture_dir)))
    return cmds


def run_acceptance(fixture_dir: Path, workdir: Path) -> list[dict]:
    """Restore pristine oracles then run every numbered JUDGE command."""
    for oracle in ("tests/test.js", "verify.js"):
        src = fixture_dir / oracle
        if src.is_file():
            dst = workdir / oracle
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    results = []
    for cmd in _judge_commands(fixture_dir):
        r = run_cmd(cmd, cwd=workdir, shell=True)
        results.append({"command": cmd, "exit": r.returncode})
    return results


def parse_agy_stream(text: str) -> dict:
    """Extract conversation id + usage from `agy --output-format stream-json`.

    The real CLI emits snake_case events: top-level `conversation_id` and
    `usage` objects with `input_tokens`/`output_tokens`/`thinking_tokens`/
    `cache_read_tokens`/`total_tokens` (camelCase variants tolerated too).
    Returns {} when nothing real is present (arm must be rejected).
    """
    out: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        for key in ("conversationId", "conversation_id"):
            if obj.get(key):
                out.setdefault("conversation_id", obj[key])
        # The real CLI nests usage inside step_update / result objects.
        usage = obj.get("usage") or obj.get("usageMetadata") or {}
        if not usage:
            for nested in ("step_update", "result"):
                inner = obj.get(nested)
                if isinstance(inner, dict):
                    usage = inner.get("usage") or inner.get("usageMetadata") or {}
                    if usage:
                        break
        if isinstance(usage, dict):
            for key in ("input_tokens", "outputTokens", "inputTokens"):
                if usage.get(key) is not None and out.get("input_tokens") is None:
                    out["input_tokens"] = usage[key]
            for key in ("output_tokens", "outputTokens"):
                if usage.get(key) is not None and out.get("output_tokens") is None:
                    out["output_tokens"] = usage[key]
            for key in ("cache_read_tokens", "cacheReadTokens"):
                if usage.get(key) is not None and out.get("cache_read_tokens") is None:
                    out["cache_read_tokens"] = usage[key]
            for key in ("total_tokens", "totalTokens"):
                if usage.get(key) is not None and out.get("total_tokens") is None:
                    out["total_tokens"] = usage[key]
    return out


def _arm_dir(task_id: str, arm_type: str, provider: str) -> Path:
    """Next generation-aware arm dir, preserving other-provider evidence.

    The historical DeepSeek e07-b-1 partial must never be overwritten, and a
    pair's two arms must share the same generation: if EITHER arm's dir at a
    generation holds evidence from a different provider, both arms skip that
    generation (Gemini e07 pair lands in e07-b-2/e07-c-2).
    """
    sibling_type = "c" if arm_type == "b" else "b"
    gen = 1
    while True:
        d = REPORTS_ROOT / f"{task_id}-{arm_type}-{gen}"
        sibling = REPORTS_ROOT / f"{task_id}-{sibling_type}-{gen}"

        def _occupied(p: Path) -> bool:
            if not p.exists():
                return False
            ev = p / "evidence.json"
            if not ev.is_file():
                return False
            try:
                data = json.loads(ev.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return False
            existing = str(data.get("provider") or data.get("model") or "").lower()
            if not existing:
                # old-schema arms: infer from the real telemetry model field
                tfile = p / "telemetry.jsonl"
                if tfile.is_file():
                    for raw in tfile.read_text(encoding="utf-8", errors="replace").splitlines():
                        try:
                            rec = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(rec, dict) and rec.get("model"):
                            existing = str(rec["model"]).lower()
                            break
            return existing not in ("", provider)

        if _occupied(d) or _occupied(sibling):
            gen += 1
            continue
        return d


def _arm_done(d: Path) -> bool:
    """True when the arm dir already holds a VALID_COMPLETE evidence record."""
    ev = d / "evidence.json"
    if not ev.is_file():
        return False
    try:
        data = json.loads(ev.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("validity") == "VALID_COMPLETE"


def validate_arm(arm: dict) -> list[str]:
    """Validity guards (plan §35). Returns a list of rejection reasons."""
    problems = []
    if not arm.get("conversation_id"):
        problems.append("no real Antigravity conversation ID")
    if not arm.get("run_artifact_path"):
        problems.append("no model result artifact")
    usage = arm.get("usage") or {}
    if not any(isinstance(v, (int, float)) and v > 0 for v in usage.values()):
        problems.append("usage is empty/absent (no real model execution evidence)")
    if not arm.get("model_slug"):
        problems.append("model slug missing")
    if (arm.get("wall_ms") or 0) < MIN_WALL_MS:
        problems.append(f"wall time {arm.get('wall_ms')}ms is impossible for a real agent run")
    if arm.get("acceptance") != "PASS":
        problems.append(f"acceptance is {arm.get('acceptance')!r} (oracle failed)")
    if arm.get("lean_state") not in ("OFF", "ON"):
        problems.append("lean state missing/unresolved")
    if not arm.get("brain_telemetry"):
        problems.append("no Brain hook telemetry captured")
    tool_records = [
        t for t in arm.get("brain_telemetry", [])
        if (
            isinstance(t, dict)
            and t.get("kind") == "tool_result"
            and t.get("tool") not in (None, "unknown")
        )
    ]
    if not tool_records:
        problems.append("no real tool activity recorded in hook telemetry")
    lean_telems = [
        t for t in arm.get("lean_telemetry", [])
        if isinstance(t, dict) and t.get("lean_decision") is not None
    ]
    if arm["lean_state"] == "ON":
        if not any(t.get("lean_decision") == "inject" for t in lean_telems):
            problems.append("Lean ON telemetry cannot prove kernel injection")
        elif not any(
            (t.get("lean_kernel_chars") or 0) >= 800
            for t in lean_telems
            if t.get("lean_decision") == "inject"
        ):
            problems.append("Lean ON kernel injection has no canonical kernel size proof")
    else:
        if any(t.get("lean_decision") == "inject" for t in lean_telems):
            problems.append("Lean OFF telemetry cannot prove kernel omission (inject seen)")
    return problems


def invoke_agy(prompt_file: Path, workdir: Path, artifact_path: Path, arm: dict) -> tuple[int, str]:
    """Invoke the REAL external Antigravity agent; returns (exit_code, stdout)."""
    agy = os.environ.get(AGY_ENV, "agy")
    model = os.environ[AGY_MODEL_ENV]
    effort = os.environ.get(AGY_EFFORT_ENV, "")
    project = os.environ.get(AGY_PROJECT_ENV, "").strip()
    timeout = int(os.environ.get(AGY_TIMEOUT_ENV, "1200"))
    print_timeout = int(os.environ.get(AGY_PRINT_TIMEOUT_ENV, "900"))
    cmd = [
        agy,
        "--add-dir",
        str(workdir),
        "-p",
        prompt_file.read_text(encoding="utf-8"),
        "--output-format",
        "stream-json",
        "--model",
        model,
        "--print-timeout",
        f"{print_timeout}s",
    ]
    if project:
        cmd += ["--project", project]
    if effort:
        cmd += ["--effort", effort]
    if os.environ.get(AGY_SKIP_PERMISSIONS_ENV, "").strip().lower() in ("1", "true", "yes"):
        cmd += ["--dangerously-skip-permissions"]
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    # Deterministic per-arm Lean isolation through process env (plan §16).
    env["SECOND_BRAIN_LEAN"] = "advisory" if arm["lean_state"] == "ON" else "off"
    env["SECOND_BRAIN_AUTOINJECT_MODE"] = "active"
    proc = subprocess.Popen(
        cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        arm["timeout"] = True
    artifact_path.write_text(stdout, encoding="utf-8", errors="replace")
    if stderr:
        (artifact_path.with_suffix(".stderr")).write_text(
            stderr[:200_000], encoding="utf-8", errors="replace"
        )
    return proc.returncode, stdout


def run_arm(task_id: str, slug: str, arm_type: str, provider: str, tmp_root: Path) -> dict:
    """One real arm. Never writes solution files; only orchestrates."""
    fixture_dir = FIXTURES_ROOT / slug
    workdir = tmp_root / f"{task_id}_{arm_type}"
    setup_workspace(fixture_dir, workdir)

    lean_state = "ON" if arm_type == "c" else "OFF"
    prompt_file = fixture_dir / "TASK.md"
    arm: dict = {
        "run_id": f"{slug}-{arm_type}-run1",
        "task_id": task_id,
        "slug": slug,
        "arm_type": arm_type,
        "provider": provider,
        "lean_state": lean_state,
        "model_slug": os.environ.get(AGY_MODEL_ENV, ""),
        "conversation_id": "",
        "started_at": datetime.now(UTC).isoformat(),
        "wall_ms": 0,
        "agy_exit": None,
        "usage": {},
        "acceptance": "PENDING",
        "judge": [],
        "diff": {"changed_files": [], "added_lines": 0, "deleted_lines": 0, "new_files": []},
        "brain_telemetry": [],
        "lean_telemetry": [],
        "validity": "PENDING",
        "rejections": [],
        "cost": "UNAVAILABLE-not-inferred",
    }

    report_dir = _arm_dir(task_id, arm_type, provider)
    report_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = report_dir / "agy-stream.jsonl"
    try:
        arm["run_artifact_path"] = str(artifact_path.relative_to(REPO_ROOT))
    except ValueError:
        arm["run_artifact_path"] = str(artifact_path)

    started = time.time()
    exit_code, stdout = invoke_agy(prompt_file, workdir, artifact_path, arm)
    arm["wall_ms"] = int((time.time() - started) * 1000)
    arm["agy_exit"] = exit_code

    stream = parse_agy_stream(stdout)
    arm["conversation_id"] = stream.get("conversation_id", "")
    arm["usage"] = {
        "input_tokens": stream.get("input_tokens"),
        "output_tokens": stream.get("output_tokens"),
        "cache_read_tokens": stream.get("cache_read_tokens"),
        "total_tokens": stream.get("total_tokens"),
    }

    # Deterministic acceptance oracle (post-run; pristine oracle restored).
    arm["judge"] = run_acceptance(fixture_dir, workdir)
    arm["acceptance"] = "PASS" if all(j["exit"] == 0 for j in arm["judge"]) else "FAIL"

    # Engineering surface vs baseline commit.
    numstat = run_cmd(["git", "diff", "--numstat", "HEAD"], cwd=workdir)
    nameonly = run_cmd(["git", "diff", "--name-only", "HEAD"], cwd=workdir)
    status = run_cmd(["git", "status", "--porcelain"], cwd=workdir)
    arm["diff"]["changed_files"] = [
        f.strip() for f in nameonly.stdout.splitlines() if f.strip()
    ]
    arm["diff"]["new_files"] = [
        line.strip()[3:] for line in status.stdout.splitlines() if line.startswith("??")
    ]
    for line in numstat.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            arm["diff"]["added_lines"] += int(parts[0])
            arm["diff"]["deleted_lines"] += int(parts[1])

    # Brain + Lean hook telemetry (bounded metadata only).
    brain_home = os.environ.get("SECOND_BRAIN_HOME")
    if brain_home:
        tfile = Path(brain_home) / "telemetry" / "agent-performance" / "antigravity-hooks.jsonl"
        if tfile.is_file():
            for raw in tfile.read_text(encoding="utf-8", errors="replace").splitlines():
                if not raw.strip():
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if rec.get("session") == arm["conversation_id"]:
                    arm["brain_telemetry"].append(rec)
                    if rec.get("kind") == "preinvocation":
                        arm["lean_telemetry"].append(
                            {
                                "lean_decision": rec.get("lean_decision"),
                                "lean_reason": rec.get("lean_reason"),
                                "lean_mode": rec.get("lean_mode"),
                                "lean_eval_source": rec.get("lean_eval_source"),
                                "lean_kernel_chars": rec.get("lean_kernel_chars"),
                                "autoinject_mode": rec.get("autoinject_mode"),
                                "packet_tokens": rec.get("packet_tokens"),
                            }
                        )

    rejections = validate_arm(arm)
    arm["validity"] = "REJECTED" if rejections else "VALID_COMPLETE"
    arm["rejections"] = rejections
    arm["finished_at"] = datetime.now(UTC).isoformat()

    (report_dir / "evidence.json").write_text(json.dumps(arm, indent=2), encoding="utf-8")
    return arm


def preflight() -> tuple[bool, list[str]]:
    """Check the external Antigravity CLI is available and the env is frozen."""
    problems = []
    agy = os.environ.get(AGY_ENV, "agy")
    if shutil.which(agy) is None:
        problems.append(
            f"external Antigravity CLI '{agy}' not found on PATH "
            f"(set {AGY_ENV} to the agy executable when available)"
        )
    if not os.environ.get(AGY_MODEL_ENV):
        problems.append(
            f"exact frozen model slug required via {AGY_MODEL_ENV} (run `agy models` and freeze it)"
        )
    return (not problems, problems)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--preflight", action="store_true", help="check readiness and print the exact blocker"
    )
    ap.add_argument("--dry-run", action="store_true", help="show the next unfinished pair and exit")
    ap.add_argument(
        "--limit", type=int, default=0, help="max Gemini/Antigravity pairs to execute (0 = all)"
    )
    args = ap.parse_args()

    ok, problems = preflight()
    if args.preflight or not ok:
        print("=== P3 Campaign Preflight ===")
        for p in problems:
            print("BLOCKER:", p)
        if ok:
            print("READY_FOR_REAL_CAMPAIGN")
        else:
            print("STATUS: STOP AT READY_FOR_REAL_CAMPAIGN")
            print("MANUAL NEXT ACTION:")
            print("  1. Install the Antigravity CLI (`agy`); authenticate.")
            print(
                "  2. Run `agy models`; freeze the exact Gemini 3.7 Flash slug via "
                + AGY_MODEL_ENV
                + "."
            )
            print("  3. Freeze the campaign Brain snapshot + adapter hash (plan §27).")
            print("  4. Re-run: python scripts/run_p3_promotion_campaign.py")
        return 0 if args.preflight else 1

    if args.dry_run:
        for tid, slug, provider, order in TASKS:
            if provider == "deepseek":
                b = REPORTS_ROOT / f"{tid}-b-1" / "evidence.json"
                c = REPORTS_ROOT / f"{tid}-c-1" / "evidence.json"
                state = "OK" if b.exists() and c.exists() else "MISSING"
                print(f"{tid} {slug}: deepseek retained pair {state}")
            else:
                print(f"{tid} {slug}: gemini pending (order={order})")
        return 0

    tmp_root = REPO_ROOT / "outputs" / "scratch" / "p3-campaign-runs"
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        completed = 0
        executed = 0
        for tid, slug, provider, order in TASKS:
            if provider == "deepseek":
                b = REPORTS_ROOT / f"{tid}-b-1" / "evidence.json"
                c = REPORTS_ROOT / f"{tid}-c-1" / "evidence.json"
                if b.exists() and c.exists():
                    completed += 1
                    print(f"[{tid}] retained DeepSeek pair OK")
                continue
            if args.limit and executed >= args.limit:
                print(f"--limit {args.limit} reached; remaining pairs deferred.")
                break
            b_dir = _arm_dir(tid, "b", "gemini")
            c_dir = _arm_dir(tid, "c", "gemini")
            if _arm_done(b_dir) and _arm_done(c_dir):
                completed += 1
                print(f"[{tid}] {slug} already complete ({b_dir.name}/{c_dir.name})")
                continue
            print(f"[{tid}] {slug} -> EXECUTING order={order} ...")
            if order == "ON_FIRST":
                if not _arm_done(c_dir):
                    run_arm(tid, slug, "c", "gemini", tmp_root)
                if not _arm_done(b_dir):
                    run_arm(tid, slug, "b", "gemini", tmp_root)
            else:
                if not _arm_done(b_dir):
                    run_arm(tid, slug, "b", "gemini", tmp_root)
                if not _arm_done(c_dir):
                    run_arm(tid, slug, "c", "gemini", tmp_root)
            completed += 1
            executed += 1
        print(f"Campaign progress: {completed}/14 pairs accounted.")
        return 0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
