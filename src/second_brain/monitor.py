"""Metacognitive monitor (plan §34/§107, Phase 11).

Shadow-only confidence categories: from a session trajectory (capsule,
requirement ledger, read ledger, telemetry, git state) produce three coarse
confidences — epistemic, execution, verification — via 11 deterministic
signals. Categories first (LOW/MEDIUM/HIGH), no fake precision. All math is
integer strengths (0/1/2) summed per axis; thresholds 0-2 HIGH, 3-5 MEDIUM,
>=6 LOW.

Also provides the plan §107 baseline: the basic heuristic (any failed command
or any material-unverified requirement -> LOW) and :func:`eval_monitor`, which
scores monitor vs basic vs the honest random expectation (0.5, not simulated).
"""

from __future__ import annotations

from collections import Counter

CONFIDENCE_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH")
AXES: tuple[str, ...] = ("epistemic", "execution", "verification")

MATERIAL_IMPORTANCES = frozenset({"critical", "high"})
_DONE_STATUSES = frozenset({"verified", "not_applicable"})

_VERIFIER_WORDS = ("reject", "disagree", "verifier")
_FLAKY_WORDS = ("flaky", "intermittent", "nondeterministic")


def _level(score: int) -> str:
    if score <= 2:
        return "HIGH"
    if score <= 5:
        return "MEDIUM"
    return "LOW"


def _evidence_texts(requirements: list[dict]) -> list[str]:
    out = []
    for entry in requirements:
        if not isinstance(entry, dict):
            continue
        for item in entry.get("evidence") or []:
            out.append(str(item))
    return out


def _failed_commands(telemetry: list[dict]) -> dict:
    n = sum(
        1
        for record in telemetry
        if isinstance(record, dict)
        and record.get("kind") == "tool_result"
        and record.get("is_error")
    )
    strength = 0 if n == 0 else (1 if n == 1 else 2)
    return {
        "name": "failed_commands",
        "value": n,
        "strength": strength,
        "effect": "execution",
        "detail": f"{n} tool_result error(s)",
    }


def _repeated_reads(reads: list[dict]) -> dict:
    counts = Counter(
        (record.get("path"), record.get("hash"))
        for record in reads
        if isinstance(record, dict) and record.get("path")
    )
    repeated = sum(1 for count in counts.values() if count > 1)
    strength = 0 if repeated == 0 else (1 if repeated <= 2 else 2)
    return {
        "name": "repeated_reads",
        "value": repeated,
        "strength": strength,
        "effect": "epistemic",
        "detail": f"{repeated} distinct path+hash pair(s) read more than once",
    }


def _untested_requirements(requirements: list[dict]) -> dict:
    n = sum(
        1
        for entry in requirements
        if isinstance(entry, dict)
        and entry.get("importance") in MATERIAL_IMPORTANCES
        and entry.get("status") not in _DONE_STATUSES
    )
    strength = 0 if n == 0 else (1 if n == 1 else 2)
    return {
        "name": "untested_requirements",
        "value": n,
        "strength": strength,
        "effect": "verification",
        "detail": f"{n} material requirement(s) not verified/not_applicable",
    }


def _hypothesis_reversals(capsule: dict) -> dict:
    n = len(capsule.get("current_hypotheses") or [])
    strength = 2 if n >= 6 else (1 if n >= 3 else 0)
    return {
        "name": "hypothesis_reversals",
        "value": n,
        "strength": strength,
        "effect": "epistemic",
        "detail": f"{n} current hypothes(es) recorded",
    }


def _open_questions(capsule: dict) -> dict:
    n = len(capsule.get("open_questions") or [])
    strength = 0 if n == 0 else (1 if n <= 2 else 2)
    return {
        "name": "open_questions",
        "value": n,
        "strength": strength,
        "effect": "epistemic",
        "detail": f"{n} open question(s)",
    }


def _evidence_word_signal(name: str, texts: list[str], words: tuple[str, ...]) -> dict:
    hits = [text for text in texts if any(word in text.lower() for word in words)]
    if hits:
        return {
            "name": name,
            "value": len(hits),
            "strength": 2,
            "effect": "verification",
            "detail": f"{len(hits)} evidence entr(ies) mention {', '.join(words)}",
        }
    return {
        "name": name,
        "value": 0,
        "strength": 0,
        "effect": "verification",
        "detail": "no matching evidence",
    }


def _speculative_edits(capsule: dict) -> dict:
    n = len(capsule.get("files_touched") or [])
    strength = 2 if n > 10 else (1 if n > 5 else 0)
    return {
        "name": "speculative_edits",
        "value": n,
        "strength": strength,
        "effect": "execution",
        "detail": f"{n} file(s) touched",
    }


def _context_pressure(telemetry: list[dict]) -> dict:
    percents = []
    for record in telemetry:
        if not isinstance(record, dict):
            continue
        usage = record.get("context_usage")
        if isinstance(usage, dict) and isinstance(usage.get("percent"), (int, float)):
            percents.append(float(usage["percent"]))
    maximum = max(percents) if percents else 0.0
    strength = 0 if maximum <= 50 else (1 if maximum <= 80 else 2)
    return {
        "name": "context_pressure",
        "value": maximum,
        "strength": strength,
        "effect": "execution",
        "detail": f"max context usage {maximum:.0f}%",
    }


def _stale_source(git_info: dict) -> dict:
    dirty = bool(git_info.get("dirty"))
    uncommitted = int(git_info.get("uncommitted_files") or 0)
    if uncommitted > 5:
        return {
            "name": "stale_source",
            "value": uncommitted,
            "strength": 2,
            "effect": "epistemic",
            "detail": f"{uncommitted} uncommitted file(s)",
        }
    if dirty:
        return {
            "name": "stale_source",
            "value": 1,
            "strength": 1,
            "effect": "epistemic",
            "detail": "working tree dirty",
        }
    return {
        "name": "stale_source",
        "value": 0,
        "strength": 0,
        "effect": "epistemic",
        "detail": "working tree clean",
    }


def _search_depth(reads: list[dict]) -> dict:
    n = sum(
        1
        for record in reads
        if isinstance(record, dict) and "search" in str(record.get("purpose") or "").lower()
    )
    strength = 2 if n >= 10 else (1 if n >= 5 else 0)
    return {
        "name": "search_depth",
        "value": n,
        "strength": strength,
        "effect": "epistemic",
        "detail": f"{n} read(s) with a search purpose",
    }


def assess_confidence(
    capsule: dict,
    requirements: list[dict],
    reads: list[dict],
    telemetry_records: list[dict],
    git_info: dict,
) -> dict:
    """Category confidence from one trajectory.

    Returns ``{"epistemic", "execution", "verification", "scores", "signals"}``
    where each signal is ``{name, value, strength, effect, detail}`` and
    ``scores`` holds the per-axis strength sums. Deterministic.
    """
    evidence_texts = _evidence_texts(requirements)
    signals = [
        _failed_commands(telemetry_records),
        _repeated_reads(reads),
        _untested_requirements(requirements),
        _hypothesis_reversals(capsule),
        _open_questions(capsule),
        _evidence_word_signal("verifier_disagreement", evidence_texts, _VERIFIER_WORDS),
        _evidence_word_signal("flaky_tests", evidence_texts, _FLAKY_WORDS),
        _speculative_edits(capsule),
        _context_pressure(telemetry_records),
        _stale_source(git_info),
        _search_depth(reads),
    ]
    scores = {axis: 0 for axis in AXES}
    for signal in signals:
        scores[signal["effect"]] += signal["strength"]
    return {
        "epistemic": _level(scores["epistemic"]),
        "execution": _level(scores["execution"]),
        "verification": _level(scores["verification"]),
        "scores": scores,
        "signals": signals,
    }


def basic_heuristic(
    capsule: dict,
    requirements: list[dict],
    reads: list[dict],
    telemetry_records: list[dict],
    git_info: dict,
) -> str:
    """Plan §107 baseline: any failed command or any material-unverified
    requirement -> LOW, else HIGH."""
    failed = any(
        isinstance(record, dict) and record.get("kind") == "tool_result" and record.get("is_error")
        for record in telemetry_records
    )
    untested = any(
        isinstance(entry, dict)
        and entry.get("importance") in MATERIAL_IMPORTANCES
        and entry.get("status") not in _DONE_STATUSES
        for entry in requirements
    )
    return "LOW" if (failed or untested) else "HIGH"


def eval_monitor(trajectories: list[dict]) -> dict:
    """Score monitor vs basic heuristic vs the honest random expectation.

    Each trajectory: ``{label, outcome: 'good'|'bad', capsule, requirements,
    reads, telemetry, git}``. The monitor predicts 'bad' when any axis is LOW;
    the basic heuristic predicts 'bad' when it returns LOW. Random accuracy is
    reported as the 0.5 expectation — never simulated.
    """
    monitor_correct = 0
    basic_correct = 0
    monitor_predictions: dict[str, str] = {}
    basic_predictions: dict[str, str] = {}
    outcomes: dict[str, str] = {}
    for trajectory in trajectories:
        label = str(trajectory.get("label", "?"))
        outcome = str(trajectory.get("outcome", "good"))
        capsule = trajectory.get("capsule") or {}
        requirements = trajectory.get("requirements") or []
        reads = trajectory.get("reads") or []
        telemetry = trajectory.get("telemetry") or []
        git_info = trajectory.get("git") or {}
        confidence = assess_confidence(capsule, requirements, reads, telemetry, git_info)
        monitor = "bad" if any(confidence[axis] == "LOW" for axis in AXES) else "good"
        basic = (
            "bad"
            if basic_heuristic(capsule, requirements, reads, telemetry, git_info) == "LOW"
            else "good"
        )
        monitor_predictions[label] = monitor
        basic_predictions[label] = basic
        outcomes[label] = outcome
        if monitor == outcome:
            monitor_correct += 1
        if basic == outcome:
            basic_correct += 1
    n = len(trajectories)
    return {
        "n": n,
        "monitor_agreement": monitor_correct / n if n else 0.0,
        "basic_agreement": basic_correct / n if n else 0.0,
        "random_expectation": 0.5,
        "monitor_predictions": monitor_predictions,
        "basic_predictions": basic_predictions,
        "outcomes": outcomes,
    }
