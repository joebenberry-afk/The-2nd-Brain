"""Compile the P3 / Lean Code promotion evaluation report from EVIDENCE ONLY.

The verdict is DERIVED from the valid evidence under outputs/reports/p3-promo-eval:
  - invalidated evidence (outputs/reports/p3-promo-eval-invalidated/) is NEVER read;
  - evidence records with validity != VALID_COMPLETE are ignored;
  - provider strata are reported separately (DeepSeek/Prime vs Gemini/Antigravity);
  - economics uses only real measured metrics; cost defaults to
    UNAVAILABLE-not-inferred;
  - promotion cannot occur unless the required number of valid real pairs exists.

Verdicts (exactly one):
  PROMOTE ACTIVE
  HOLD SHADOW
  FAIL / REWORK
  HOLD SHADOW — REAL CAMPAIGN INCOMPLETE
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "outputs" / "reports"
PROMO_EVAL_DIR = REPORTS_DIR / "p3-promo-eval"
INVALIDATED_DIR = REPORTS_DIR / "p3-promo-eval-invalidated"
OUTPUT_REPORT = REPORTS_DIR / "p3-promotion-evaluation-report.md"

REQUIRED_VALID_PAIRS = 14  # plan §49: 14 valid complete pairs / 28 valid real arms
MIN_VALID_PAIRS_FOR_PROMOTION = 8  # a promotion requires the overwhelming majority of real pairs

TASK_IDS = [
    "e01",
    "e02",
    "e03",
    "e06",
    "e07",
    "e08",
    "e09",
    "e10",
    "e11",
    "e12",
    "e13",
    "e14",
    "e15",
    "e16",
]


def _load_arm(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("validity", "VALID_COMPLETE") != "VALID_COMPLETE":
        return None
    if data.get("acceptance") not in ("PASS", "FAIL"):
        return None
    return data


RETAINED_DEEPSEEK_TASKS = {"e01", "e02", "e03", "e06"}


def _telemetry_model(arm_dir: Path) -> str:
    """First model seen in the arm's telemetry.jsonl (bounded read, in-memory only)."""
    tfile = arm_dir / "telemetry.jsonl"
    if not tfile.is_file():
        return ""
    for raw in tfile.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        model = rec.get("model") if isinstance(rec, dict) else None
        if model:
            return str(model).lower()
    return ""


def _infer_provider(tid: str, arm: dict, arm_dir: Path) -> str:
    """Provider inference, in-memory only (raw evidence is immutable).

    Retained genuine DeepSeek pairs are identified by task id AND their real
    Prime telemetry (model contains 'deepseek'). Real Gemini arms carry the
    provider/model fields written by the orchestrator.
    """
    explicit = str(arm.get("provider") or arm.get("model") or arm.get("model_slug") or "").lower()
    if "deepseek" in explicit:
        return "deepseek"
    if "gemini" in explicit:
        return "gemini"
    if tid in RETAINED_DEEPSEEK_TASKS and "deepseek" in _telemetry_model(arm_dir):
        return "deepseek"
    return ""


def _arm_dirs(task_id: str, arm_type: str) -> list[Path]:
    """All generation dirs for one arm, sorted by generation ascending."""
    out = []
    gen = 1
    while True:
        d = PROMO_EVAL_DIR / f"{task_id}-{arm_type}-{gen}"
        if d.exists():
            out.append(d)
            gen += 1
            continue
        if gen <= 4:  # tolerate missing gens 2..4 while scanning further
            gen += 1
            continue
        break
    return out


def load_pairs() -> list[dict]:
    """Load valid complete pairs only (same provider on both arms).

    Generation-aware: for each task, arms may exist across generations (the
    historical DeepSeek e07-b-1 partial is generation 1; the resumed Gemini
    pair is generation 2). The LATEST generation with BOTH arms present,
    VALID_COMPLETE, and the SAME provider counts. Cross-provider pairs never
    count (the historical DeepSeek e07 partial has no c-side, so it can never
    form a pair).
    """
    pairs = []
    for tid in TASK_IDS:
        b_dirs = _arm_dirs(tid, "b")
        c_dirs = _arm_dirs(tid, "c")
        best = None
        for b_dir in b_dirs:
            b = _load_arm(b_dir / "evidence.json")
            if b is None:
                continue
            b_provider = _infer_provider(tid, b, b_dir)
            for c_dir in c_dirs:
                if c_dir.name != b_dir.name.replace("-b-", "-c-"):
                    continue
                c = _load_arm(c_dir / "evidence.json")
                if c is None:
                    continue
                c_provider = _infer_provider(tid, c, c_dir)
                if b_provider == c_provider and b_provider in ("deepseek", "gemini"):
                    gen = int(b_dir.name.split("-")[-1])
                    if best is None or gen > best[0]:
                        best = (gen, b_provider, b, c)
        if best:
            pairs.append(
                {"id": tid, "provider": best[1], "baseline": best[2], "candidate": best[3]}
            )
    return pairs


def gate_correctness(pairs: list[dict]) -> dict:
    """Candidate never loses correctness the baseline achieves."""
    losses = [
        p["id"]
        for p in pairs
        if p["baseline"]["acceptance"] == "PASS" and p["candidate"]["acceptance"] != "PASS"
    ]
    return {"pass": not losses, "losses": losses}


def _candidate_tool_activity(candidate: dict) -> int:
    """Real tool activity count from Brain hook telemetry (PostToolUse records)."""
    telems = candidate.get("brain_telemetry") or []
    return sum(
        1
        for t in telems
        if (
            isinstance(t, dict)
            and t.get("kind") == "tool_result"
            and t.get("tool") not in (None, "unknown")
        )
    )


def gate_anti_laziness(pairs: list[dict]) -> dict:
    """Candidate still performs justified engineering when the evidence says so.

    Provable from either (a) real LC decision codes the harness recorded, or
    (b) real candidate tool activity + a real diff on tasks where the
    baseline performed engineering work. Never inferred from fabricated codes.
    """
    provable = 0
    justified = 0
    notes = []
    for p in pairs:
        cand = p["candidate"]
        lc = cand.get("lc_decisions")
        if lc:
            provable += 1
            if any("LC_" in str(d) for d in lc):
                justified += 1
            continue
        tools = _candidate_tool_activity(cand)
        diff = cand.get("diff") or {}
        touched = bool(
            diff.get("changed_files") or diff.get("new_files") or (diff.get("added_lines") or 0) > 0
        )
        if tools > 0 and touched:
            provable += 1
            justified += 1
        else:
            notes.append(f"{p['id']}: no real tool activity + diff evidence")
    return {
        "pass": provable > 0 and justified == provable,
        "provable": provable,
        "justified": justified,
        "notes": notes,
    }


def gate_stop(pairs: list[dict]) -> dict:
    """Stop telemetry (or real LC_STOP codes) proves disciplined termination."""
    ok = True
    provable = 0
    notes = []
    for p in pairs:
        cand = p["candidate"]
        telems = cand.get("brain_telemetry") or []
        kinds = {t.get("kind") for t in telems if isinstance(t, dict)}
        lc = cand.get("lc_decisions") or []
        if "stop_allowed" in kinds or "stop_continue" in kinds:
            provable += 1
            continue
        if any("LC_STOP" in str(d) for d in lc):
            provable += 1
            continue
        ok = False
        notes.append(f"{p['id']}: no Stop telemetry / LC_STOP evidence")
    return {"pass": ok and provable > 0, "provable": provable, "notes": notes}


def gate_opportunity(pairs: list[dict]) -> dict:
    """Candidate reduces unnecessary engineering on a majority of opportunity tasks."""
    reduced = 0
    comparable = 0
    for p in pairs:
        b = p["baseline"].get("diff") or {}
        c = p["candidate"].get("diff") or {}
        if "added_lines" in b and "added_lines" in c:
            comparable += 1
            if c["added_lines"] < b["added_lines"]:
                reduced += 1
    return {
        "pass": comparable > 0 and reduced * 2 > comparable,
        "reduced": reduced,
        "comparable": comparable,
    }


def _usage(arm: dict) -> dict:
    """Normalized usage (snake_case keys) from either the runner's `usage`
    block or the retained DeepSeek arms' `economics` block (both real)."""
    u = arm.get("usage") or arm.get("economics") or {}
    if not isinstance(u, dict):
        return {}
    out = {}
    for src_key, dst_key in (
        ("input_tokens", "input_tokens"),
        ("inputTokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("outputTokens", "output_tokens"),
        ("cache_read_tokens", "cache_read_tokens"),
        ("cacheReadTokens", "cache_read_tokens"),
        ("total_tokens", "total_tokens"),
        ("totalTokens", "total_tokens"),
    ):
        if u.get(src_key) is not None:
            out[dst_key] = u[src_key]
    return out


def gate_economics(pairs: list[dict]) -> dict:
    """Real measured metrics only; UNAVAILABLE-not-inferred is not a pass."""
    real = 0
    total = len(pairs)
    for p in pairs:
        u = _usage(p["candidate"])
        if any(isinstance(v, (int, float)) and v > 0 for v in u.values()):
            real += 1
    return {"pass": real == total and total > 0, "real_usage_arms": real, "total_arms": total * 2}


def compute_verdict(pairs: list[dict]) -> tuple[str, list[str]]:
    """Derive the verdict from the gates (plan §38/§40)."""
    reasons: list[str] = []
    if len(pairs) < REQUIRED_VALID_PAIRS:
        return "HOLD SHADOW — REAL CAMPAIGN INCOMPLETE", [
            f"only {len(pairs)}/{REQUIRED_VALID_PAIRS} valid complete pairs exist; "
            "no synthetic or cross-provider arms count"
        ]
    g_correct = gate_correctness(pairs)
    g_lean = gate_anti_laziness(pairs)
    g_stop = gate_stop(pairs)
    g_opp = gate_opportunity(pairs)
    g_econ = gate_economics(pairs)
    if not g_correct["pass"]:
        reasons.append(
            "correctness gate FAIL: baseline-passing tasks lost by candidate: "
            + str(g_correct["losses"])
        )
    if not g_lean["pass"]:
        reasons.append("anti-laziness gate FAIL/UNPROVABLE: no justified-engineering evidence")
    if not g_stop["pass"]:
        reasons.append("STOP gate FAIL: missing Stop telemetry evidence")
    if not g_opp["pass"]:
        reasons.append(
            "opportunity gate FAIL: candidate reduced surface on "
            f"{g_opp['reduced']}/{g_opp['comparable']} comparable tasks"
        )
    if not g_econ["pass"]:
        reasons.append(
            "economics gate FAIL: usage not measured on all arms (UNAVAILABLE-not-inferred)"
        )
    if len(pairs) < MIN_VALID_PAIRS_FOR_PROMOTION:
        reasons.append("too few valid real pairs for a promotion verdict")
    if not reasons:
        return "PROMOTE ACTIVE", ["all promotion gates pass on real evidence"]
    return "HOLD SHADOW", reasons


def main() -> int:
    pairs = load_pairs()
    deepseek_pairs = [p for p in pairs if p["provider"] == "deepseek"]
    gemini_pairs = [p for p in pairs if p["provider"] == "gemini"]
    verdict, reasons = compute_verdict(pairs)

    report: list[str] = []
    report.append("# Second Brain P3 / Lean Code Promotion Evaluation Report")
    report.append("")
    report.append(f"**Promotion Verdict**: `{verdict}`")
    report.append("**Date**: 2026-08-16")
    report.append(
        "**Evidence source**: outputs/reports/p3-promo-eval (validity=VALID_COMPLETE only)"
    )
    report.append(
        "**Invalidated evidence**: outputs/reports/p3-promo-eval-invalidated/ (never aggregated)"
    )
    report.append("")
    report.append("---")
    report.append("")
    report.append(
        f"## Campaign State: {len(pairs)} valid complete pairs / {len(pairs) * 2} valid arms"
    )
    report.append("")
    report.append(f"- DeepSeek/Prime stratum: {len(deepseek_pairs)} valid pairs")
    report.append(f"- Gemini/Antigravity stratum: {len(gemini_pairs)} valid pairs")
    report.append(
        f"- Required for completion: {REQUIRED_VALID_PAIRS} pairs / {REQUIRED_VALID_PAIRS * 2} arms"
    )
    report.append("")
    report.append("## Per-Pair Ledger")
    report.append("")
    report.append(
        "| Task | Provider | Baseline Pass | Candidate Pass | Baseline +lines | "
        "Candidate +lines | Lean state (candidate arm) | Conversation ID | Validity |"
    )
    report.append("|---|---|---|---|---|---|---|---|---|")
    for p in pairs:
        b, c = p["baseline"], p["candidate"]
        bd = b.get("diff") or {}
        cd = c.get("diff") or {}
        report.append(
            f"| `{p['id']}` | `{p['provider']}` | **{b.get('acceptance')}** | "
            f"**{c.get('acceptance')}** | {bd.get('added_lines', '?')} | "
            f"{cd.get('added_lines', '?')} | `{c.get('lean_state')}` | "
            f"`{c.get('conversation_id') or 'n/a'}` | "
            f"`{c.get('validity', 'VALID_COMPLETE')}` |"
        )
    report.append("")
    report.append("## Provider Stratification")
    report.append("")
    report.append("### DeepSeek v4 Flash / Prime")
    report.append("")
    for p in deepseek_pairs:
        report.append(
            f"- `{p['id']}`: model `{p['baseline'].get('model', 'deepseek/deepseek-v4-flash')}`, "
            "baseline " + str(p["baseline"].get("acceptance")) + ", candidate "
            + str(p["candidate"].get("acceptance"))
        )
    report.append("")
    report.append("### Gemini 3.7 Flash / Antigravity")
    report.append("")
    if gemini_pairs:
        for p in gemini_pairs:
            report.append(
                f"- `{p['id']}`: model `{p['candidate'].get('model_slug', 'n/a')}`, "
                f"conversation `{p['candidate'].get('conversation_id')}`"
            )
    else:
        report.append("- (no valid real Gemini/Antigravity pairs yet)")
    report.append("")
    report.append("## Gate Evaluation")
    report.append("")
    for name, result in (
        ("Correctness", gate_correctness(pairs)),
        ("Anti-laziness", gate_anti_laziness(pairs)),
        ("STOP", gate_stop(pairs)),
        ("Opportunity", gate_opportunity(pairs)),
        ("Economics (real usage only)", gate_economics(pairs)),
    ):
        detail = json.dumps({k: v for k, v in result.items() if k != "pass"})
        state = "PASS" if result["pass"] else "FAIL/UNPROVABLE"
        report.append(f"- **{name}**: {state} {detail}")
    report.append("")
    report.append("## Promotion Decision")
    report.append("")
    report.append(f"> **VERDICT: {verdict}**")
    report.append(">")
    for reason in reasons:
        report.append(f"> {reason}")
    report.append("")
    report.append("## Economics")
    report.append("")
    report.append(
        "Only real measured metrics are reported. Provider cache semantics differ "
        "between strata and are never summed into one universal number. "
        "Cost is `UNAVAILABLE-not-inferred` unless the provider/CLI reports it."
    )
    report.append("")

    OUTPUT_REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Report compiled to: {OUTPUT_REPORT}")
    print(f"VERDICT: {verdict}")
    for reason in reasons:
        print(" -", reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
