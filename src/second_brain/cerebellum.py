"""Cerebellum: predictive workflow progress monitor (plan §39-40/§108, Phase 12).

Advisory-only, deterministic. From the working set (read ledger timeline,
requirement ledger, capsule files_touched) the Cerebellum predicts whether a
workflow is progressing, stalled, or looping, using simple expected-state
templates (plan §108): Scout should shrink candidates, tests should
discriminate hypotheses, verification should close requirements.

The acceptance-critical rule detects looping exploration: the same (path,
hash) read repeated >= 2 times with no new unique paths and no requirement
status change since the first read. The fixed baseline (naive threshold: same
path read >= 3 times) is provided for the plan §108 acceptance comparison —
the Cerebellum must flag looping earlier.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from .errors import BrainError
from .working_set import show_capsule, show_reads, show_requirements

MATERIAL_IMPORTANCES = frozenset({"critical", "high"})
_DONE_STATUSES = frozenset({"verified", "not_applicable"})

_TEST_WORDS = ("test", "passed", "failed", "pass", "fail")
_SCOUT_WORDS = ("scout", "explore")
_SEARCHISH_WORDS = ("search", "scout")
FIXED_BASELINE_REPEATS = 3


_T = TypeVar("_T")


def _load_or_none(loader: Callable[..., _T], *args: object) -> _T | None:
    try:
        return loader(*args)
    except BrainError:
        return None


def _paths(reads: list[dict]) -> list[str]:
    return [
        str(record["path"]) for record in reads if isinstance(record, dict) and record.get("path")
    ]


def _status_changed(requirements: list[dict]) -> bool:
    """Proxy for 'a status transition happened': any requirement whose status
    differs from the creation default 'unverified'."""
    return any(
        isinstance(entry, dict) and entry.get("status") != "unverified" for entry in requirements
    )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _looping(reads: list[dict], requirements: list[dict]) -> dict | None:
    """Same (path, hash) read >= 2 times, no new unique paths since the first
    read, and no requirement status change since the first read."""
    if _status_changed(requirements):
        return None
    seen: set[str] = set()
    seen_at_first: dict[tuple, set[str]] = {}
    first_idx: dict[tuple, int] = {}
    for idx, record in enumerate(reads):
        if not isinstance(record, dict) or not record.get("path"):
            continue
        path = str(record["path"])
        key = (path, record.get("hash"))
        if key in first_idx:
            window = _paths(reads[first_idx[key] + 1 : idx])
            if all(path_in_window in seen_at_first[key] for path_in_window in window):
                count = idx - first_idx[key] + 1
                return {
                    "name": "looping",
                    "detail": f"{path} (hash {record.get('hash')}) re-read {count} times "
                    "with no new unique paths and no status change since the first read",
                }
        else:
            first_idx[key] = idx
            seen_at_first[key] = set(seen)
        seen.add(path)
    return None


def _scout_should_shrink_candidates(reads: list[dict]) -> dict | None:
    """Scout/explore reads increase but new candidate paths stop appearing
    while a search/scout read repeats the same path >= 2 times."""
    scout_reads = [
        record
        for record in reads
        if isinstance(record, dict)
        and any(word in str(record.get("purpose") or "").lower() for word in _SCOUT_WORDS)
    ]
    if len(scout_reads) < 2:
        return None
    seen: set[str] = set()
    seen_at_first: dict[tuple, set[str]] = {}
    first_idx: dict[tuple, int] = {}
    for idx, record in enumerate(reads):
        if not isinstance(record, dict) or not record.get("path"):
            continue
        path = str(record["path"])
        purpose = str(record.get("purpose") or "").lower()
        key = (path, record.get("hash"))
        if key in first_idx and any(word in purpose for word in _SEARCHISH_WORDS):
            after = _paths(reads[idx + 1 :])
            if all(after_path in seen_at_first[key] for after_path in after):
                count = idx - first_idx[key] + 1
                return {
                    "name": "scout_should_shrink_candidates",
                    "detail": f"exploration stalled: {path} re-read {count} times and no "
                    "new candidate paths appeared after the repeat",
                }
        else:
            first_idx[key] = idx
            seen_at_first[key] = set(seen)
        seen.add(path)
    return None


def _test_should_discriminate_hypothesis(
    reads: list[dict], requirements: list[dict]
) -> dict | None:
    """Test evidence exists but the requirement stays unverified while the same
    file is re-read >= 2 times."""
    counts = Counter(_paths(reads))
    for entry in requirements:
        if not isinstance(entry, dict) or entry.get("status") != "unverified":
            continue
        evidence = [str(item) for item in entry.get("evidence") or []]
        mentions_tests = any(any(word in item.lower() for word in _TEST_WORDS) for item in evidence)
        if not mentions_tests:
            continue
        repeated = [(path, n) for path, n in counts.items() if n >= 2]
        if repeated:
            path, n = repeated[0]
            return {
                "name": "test_should_discriminate_hypothesis",
                "detail": f"requirement {entry.get('id')} has test evidence but stays "
                f"unverified while {path} was re-read {n} times",
            }
    return None


def _verification_should_close_requirements(
    reads: list[dict], requirements: list[dict]
) -> dict | None:
    """A material requirement has evidence and >= 3 reads touch the same file
    without a status transition."""
    counts = Counter(_paths(reads))
    for entry in requirements:
        if not isinstance(entry, dict):
            continue
        if entry.get("importance") not in MATERIAL_IMPORTANCES:
            continue
        if entry.get("status") in _DONE_STATUSES or not entry.get("evidence"):
            continue
        thrice = [(path, n) for path, n in counts.items() if n >= FIXED_BASELINE_REPEATS]
        if thrice:
            path, n = thrice[0]
            return {
                "name": "verification_should_close_requirements",
                "detail": f"material requirement {entry.get('id')} has evidence but is not "
                f"converging; {path} read {n} times without a status transition",
            }
    return None


def _fixed_looping(reads: list[dict]) -> bool:
    """Fixed baseline: same path read >= 3 times alone."""
    counts = Counter(_paths(reads))
    return any(count >= FIXED_BASELINE_REPEATS for count in counts.values())


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def assess_state(
    reads: list[dict],
    requirements: list[dict],
    files_touched: list[str] | None = None,
) -> dict:
    """Assess an in-memory session state.

    Returns ``{"progress": 'progressing'|'stalled'|'looping', "signals":
    [{name, detail}], "events": [{rule, expected, actual, detail}]}``.
    Deterministic; files_touched is accepted for API parity (rules use reads +
    requirements today).
    """
    signals: list[dict] = []
    events: list[dict] = []

    looping = _looping(reads, requirements)
    if looping is not None:
        signals.append(looping)
        events.append(
            {
                "rule": "looping",
                "expected": "candidate set converges to an edit",
                "actual": "same file re-read without new paths or status change",
                "detail": looping["detail"],
            }
        )
        return {"progress": "looping", "signals": signals, "events": events}

    rules = (
        _scout_should_shrink_candidates(reads),
        _test_should_discriminate_hypothesis(reads, requirements),
        _verification_should_close_requirements(reads, requirements),
    )
    expected = (
        "candidate files shrink to an edit location",
        "tests discriminate between hypotheses",
        "verification closes material requirements",
    )
    for rule, expectation in zip(rules, expected, strict=True):
        if rule is not None:
            signals.append(rule)
            events.append(
                {
                    "rule": rule["name"],
                    "expected": expectation,
                    "actual": "no progress observed on this path",
                    "detail": rule["detail"],
                }
            )

    progress = "stalled" if signals else "progressing"
    return {"progress": progress, "signals": signals, "events": events}


def assess_workflow(home: Path, session_id: str) -> dict:
    """Assess a session's workflow from the working set. Missing capsule or
    ledgers degrade to empty inputs (an empty session is 'progressing')."""
    reads = _load_or_none(show_reads, home, session_id) or []
    requirements = _load_or_none(show_requirements, home, session_id) or []
    capsule = _load_or_none(show_capsule, home, session_id) or {}
    result = assess_state(reads, requirements, capsule.get("files_touched") or [])
    result["session"] = session_id
    return result


def _first_flag_read(
    reads: list[dict], requirements: list[dict], files_touched: list[str]
) -> int | None:
    for k in range(1, len(reads) + 1):
        if assess_state(reads[:k], requirements, files_touched)["progress"] in (
            "looping",
            "stalled",
        ):
            return k
    return None


def _first_fixed_read(reads: list[dict]) -> int | None:
    for k in range(1, len(reads) + 1):
        if _fixed_looping(reads[:k]):
            return k
    return None


def eval_cerebellum(workflows: list[dict]) -> dict:
    """Score the Cerebellum vs the fixed baseline on labeled workflows.

    Each workflow: ``{label, outcome: 'looping'|'healthy', session_state:
    {reads, requirements, files_touched}}``. The Cerebellum predicts 'looping'
    when assessment is looping or stalled; the fixed baseline flags a path read
    >= 3 times. ``early_detection`` reports, per looping workflow, the read
    count at which each method first flags (None when never).
    """
    cerebellum_correct = 0
    fixed_correct = 0
    early_detection: list[dict] = []
    for workflow in workflows:
        label = str(workflow.get("label", "?"))
        outcome = workflow.get("outcome")
        state = workflow.get("session_state") or {}
        reads = state.get("reads") or []
        requirements = state.get("requirements") or []
        files_touched = state.get("files_touched") or []
        progress = assess_state(reads, requirements, files_touched)["progress"]
        cerebellum = "looping" if progress in ("looping", "stalled") else "healthy"
        fixed = "looping" if _fixed_looping(reads) else "healthy"
        if cerebellum == outcome:
            cerebellum_correct += 1
        if fixed == outcome:
            fixed_correct += 1
        if outcome == "looping":
            early_detection.append(
                {
                    "label": label,
                    "cerebellum_read": _first_flag_read(reads, requirements, files_touched),
                    "fixed_read": _first_fixed_read(reads),
                }
            )
    n = len(workflows)
    return {
        "n": n,
        "cerebellum_agreement": cerebellum_correct / n if n else 0.0,
        "fixed_agreement": fixed_correct / n if n else 0.0,
        "early_detection": early_detection,
    }
