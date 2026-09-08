#!/usr/bin/env python3
"""Deterministic risk calibration from session telemetry & verification outcomes (plan §35, T3.2).

Joins session risk signals with verification outcomes (accuracy gate failure or test failure),
computes precision and recall of HIGH/CRITICAL classifications, fits per-signal weights via
numpy-free logistic regression (200 iterations of gradient descent, L2 regularization = 0.1),
and writes updated calibrated weights to [risk_weights] in config/verification.toml.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Ensure second_brain package can be imported
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from second_brain import paths  # noqa: E402
from second_brain.risk import SIGNAL_NAMES, assess_risk  # noqa: E402


def sigmoid(z: float) -> float:
    """Bounded numerically stable sigmoid function."""
    z = max(-500.0, min(500.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def fit_logistic_regression(
    X: list[list[float]],
    y: list[int],
    feature_names: list[str],
    iterations: int = 200,
    l2: float = 0.1,
    lr: float = 0.1,
    init_weights: float = 0.0,
) -> tuple[dict[str, float], float]:
    """Fit per-signal weights using numpy-free logistic regression.

    Pure Python: sigmoid, cross-entropy + L2 regularization, gradient descent.
    Returns (weights_dict, bias).
    """
    n_samples = len(X)
    n_features = len(feature_names)
    if n_samples == 0:
        return {name: 1.0 for name in feature_names}, 0.0

    weights = [float(init_weights)] * n_features
    bias = 0.0

    for _ in range(iterations):
        grad_w = [0.0] * n_features
        grad_b = 0.0

        for i in range(n_samples):
            z = bias + sum(weights[j] * X[i][j] for j in range(n_features))
            p = sigmoid(z)
            error = p - float(y[i])
            for j in range(n_features):
                grad_w[j] += error * X[i][j]
            grad_b += error

        for j in range(n_features):
            grad_w[j] = (grad_w[j] / n_samples) + l2 * weights[j]
            weights[j] -= lr * grad_w[j]

        grad_b = grad_b / n_samples
        bias -= lr * grad_b

    result_weights = {name: round(w, 4) for name, w in zip(feature_names, weights, strict=False)}
    return result_weights, round(bias, 4)


def compute_precision_recall(
    samples: list[dict],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute confusion matrix, precision, recall, and accuracy of HIGH/CRITICAL classifications.

    Evaluates predictions against verification failures (failed=1).
    """
    tp = fp = fn = tn = 0
    score_levels = ((9, "HIGH"), (6, "MEDIUM"), (3, "LOW"))

    for s in samples:
        signals = s["signals"]
        if weights is not None:
            score = sum(float(weights.get(sig["name"], 1.0)) * sig["points"] for sig in signals)
        else:
            score = sum(sig["points"] for sig in signals)

        level = "CRITICAL"
        for thresh, name in score_levels:
            if score < thresh:
                level = name

        predicted_high_or_critical = level in ("HIGH", "CRITICAL")
        actual_failed = bool(s.get("failed", 0))

        if predicted_high_or_critical and actual_failed:
            tp += 1
        elif predicted_high_or_critical and not actual_failed:
            fp += 1
        elif not predicted_high_or_critical and actual_failed:
            fn += 1
        else:
            tn += 1

    total = len(samples)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    accuracy = (tp + tn) / total if total > 0 else 0.0

    return {
        "total": total,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round(accuracy, 4),
    }


def write_risk_weights_to_toml(toml_path: Path, weights: dict[str, float]) -> None:
    """Write or update [risk_weights] in verification.toml without corrupting other tables."""
    if toml_path.is_file():
        lines = toml_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = ["schema_version = 1"]

    new_lines: list[str] = []
    in_risk_weights = False
    found = False

    for line in lines:
        stripped = line.strip()
        if stripped == "[risk_weights]":
            in_risk_weights = True
            found = True
            new_lines.append("[risk_weights]")
            for k in SIGNAL_NAMES:
                if k in weights:
                    new_lines.append(f"{k} = {weights[k]}")
            continue
        if in_risk_weights:
            if stripped.startswith("[") and stripped.endswith("]"):
                in_risk_weights = False
                new_lines.append("")
                new_lines.append(line)
            continue
        new_lines.append(line)

    if not found:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("[risk_weights]")
        for k in SIGNAL_NAMES:
            if k in weights:
                new_lines.append(f"{k} = {weights[k]}")

    toml_path.parent.mkdir(parents=True, exist_ok=True)
    toml_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def collect_session_data(home: Path, repo: Path | None = None) -> list[dict]:
    """Gather touched files from session events/telemetry, call assess_risk, join failure label."""
    home_path = Path(home)
    repo_path = Path(repo) if repo is not None else home_path

    session_map: dict[str, dict[str, Any]] = {}

    # 1. Scan state/sessions
    sessions_dir = home_path / "state" / "sessions"
    if sessions_dir.is_dir():
        for s_dir in sessions_dir.iterdir():
            if not s_dir.is_dir():
                continue
            s_id = s_dir.name
            capsule_file = s_dir / "active-state.json"
            if capsule_file.is_file():
                try:
                    cap = json.loads(capsule_file.read_text(encoding="utf-8"))
                    entry = session_map.setdefault(s_id, {"files_touched": set(), "failed": 0})
                    for f in cap.get("files_touched", []):
                        if isinstance(f, str) and f.strip():
                            entry["files_touched"].add(f.strip())
                    ver = cap.get("verification", {})
                    if isinstance(ver, dict) and (
                        ver.get("completion_allowed") is False
                        or ver.get("status") in ("failed", "blocked")
                    ):
                        entry["failed"] = 1
                except Exception:
                    pass

    # 2. Scan telemetry/agent-performance
    telemetry_dir = home_path / "telemetry" / "agent-performance"
    if telemetry_dir.is_dir():
        for t_file in sorted(telemetry_dir.glob("*.jsonl")):
            s_id = t_file.stem
            entry = session_map.setdefault(s_id, {"files_touched": set(), "failed": 0})
            try:
                lines = t_file.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue

                    # Check touched files
                    if "files_touched" in rec and isinstance(rec["files_touched"], list):
                        for f in rec["files_touched"]:
                            if isinstance(f, str) and f.strip():
                                entry["files_touched"].add(f.strip())
                    elif "files" in rec and isinstance(rec["files"], list):
                        for f in rec["files"]:
                            if isinstance(f, str) and f.strip():
                                entry["files_touched"].add(f.strip())

                    # Check verification failure: accuracy gate or test failure
                    kind = rec.get("kind")
                    if (
                        kind in ("stop_blocked", "stop_blocked_result")
                        or rec.get("completion_allowed") is False
                        or (
                            rec.get("status") in ("failed", "blocked")
                            and kind in ("accuracy_gate", "verification", "stop_boundary")
                        )
                    ):
                        entry["failed"] = 1
                    elif kind == "tool_result" and rec.get("is_error"):
                        tool = str(rec.get("tool", "")).lower()
                        cmd = str(rec.get("command", "")).lower()
                        if tool in ("test", "pytest") or "test" in cmd or "pytest" in cmd:
                            entry["failed"] = 1
                    elif (
                        rec.get("tests_passed") is False
                        or rec.get("test_failed") is True
                        or rec.get("failure_code") in ("TESTS_FAILED", "VERIFICATION_FAILED")
                    ):
                        entry["failed"] = 1
            except Exception:
                pass

    samples: list[dict] = []
    for s_id, data in sorted(session_map.items()):
        files = sorted(data["files_touched"])
        if not files:
            continue
        try:
            res = assess_risk(repo_path, files, home=home_path)
            samples.append(
                {
                    "session_id": s_id,
                    "files_touched": files,
                    "signals": res["signals"],
                    "risk_level": res["level"],
                    "risk_score": res["score"],
                    "failed": data["failed"],
                }
            )
        except Exception:
            pass

    return samples


def calibrate(
    home: Path,
    repo: Path | None = None,
    iterations: int = 200,
    l2: float = 0.1,
    lr: float = 0.1,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Calibrate risk weights from session telemetry in home.

    Fits per-signal weights via logistic regression and writes to verification.toml.
    """
    home_path = Path(home)
    repo_path = Path(repo) if repo is not None else home_path
    samples = collect_session_data(home_path, repo_path)

    feature_names = list(SIGNAL_NAMES)
    baseline_metrics = compute_precision_recall(samples, weights=None)

    if samples:
        X = [
            [
                float(next((s["points"] for s in sample["signals"] if s["name"] == feat), 0))
                for feat in feature_names
            ]
            for sample in samples
        ]
        y = [int(sample["failed"]) for sample in samples]
        weights, bias = fit_logistic_regression(
            X, y, feature_names, iterations=iterations, l2=l2, lr=lr, init_weights=0.0
        )
    else:
        weights = {feat: 1.0 for feat in feature_names}
        bias = 0.0

    calibrated_metrics = compute_precision_recall(samples, weights=weights)

    toml_path = home_path / "config" / "verification.toml"
    if not dry_run:
        write_risk_weights_to_toml(toml_path, weights)

    return {
        "home": str(home_path),
        "repo": str(repo_path),
        "sample_count": len(samples),
        "baseline_metrics": baseline_metrics,
        "calibrated_metrics": calibrated_metrics,
        "weights": weights,
        "bias": bias,
        "config_path": str(toml_path),
        "dry_run": dry_run,
    }


def print_summary(result: dict[str, Any]) -> None:
    """Print a clean summary table of signals, weights, and precision/recall metrics."""
    samples = result["sample_count"]
    base = result["baseline_metrics"]
    cal = result["calibrated_metrics"]
    weights = result["weights"]

    print("=" * 64)
    print("                 Risk Calibration Summary")
    print("=" * 64)
    print(f"Home: {result['home']}")
    print(f"Total Sessions Analyzed: {samples}")
    if samples > 0:
        failures = sum(1 for _ in range(base["tp"] + base["fn"]))
        successes = samples - failures
        print(f"Verification Outcomes: {failures} failed, {successes} passed")
    print()
    print("Performance Metrics (HIGH/CRITICAL vs Verification Failures):")
    print("  Baseline (Unweighted):")
    print(f"    Precision: {base['precision'] * 100:.1f}% ({base['tp']}/{base['tp'] + base['fp']})")
    print(f"    Recall:    {base['recall'] * 100:.1f}% ({base['tp']}/{base['tp'] + base['fn']})")
    print(f"    Accuracy:  {base['accuracy'] * 100:.1f}%")
    print("  Calibrated:")
    print(f"    Precision: {cal['precision'] * 100:.1f}% ({cal['tp']}/{cal['tp'] + cal['fp']})")
    print(f"    Recall:    {cal['recall'] * 100:.1f}% ({cal['tp']}/{cal['tp'] + cal['fn']})")
    print(f"    Accuracy:  {cal['accuracy'] * 100:.1f}%")
    print()
    print("Calibrated Signal Weights ([risk_weights]):")
    print(f"  {'Signal':<20} {'Weight':<10}")
    print(f"  {'-' * 20} {'-' * 10}")
    for name in SIGNAL_NAMES:
        w = weights.get(name, 1.0)
        print(f"  {name:<20} {w:.4f}")
    print()
    if result["dry_run"]:
        print("[Dry Run] Weights computed but not written to config.")
    else:
        print(f"Written updated weights to {result['config_path']}")
    print("=" * 64)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate risk weights from session telemetry and verification outcomes."
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Second Brain home directory (defaults to SECOND_BRAIN_HOME or ~/.second_brain)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Target git repository path (defaults to home)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=200,
        help="Gradient descent iterations (default: 200)",
    )
    parser.add_argument(
        "--l2",
        type=float,
        default=0.1,
        help="L2 regularization parameter (default: 0.1)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=0.1,
        help="Learning rate (default: 0.1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute weights and metrics without writing to verification.toml",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output results as JSON",
    )

    args = parser.parse_args()
    home = args.home if args.home is not None else paths.resolve_home()
    repo = args.repo if args.repo is not None else home

    result = calibrate(
        home=home,
        repo=repo,
        iterations=args.iterations,
        l2=args.l2,
        lr=args.lr,
        dry_run=args.dry_run,
    )

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print_summary(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
