"""Deterministic, explainable risk controller (plan §35, Phase 7 §103).

Assesses the risk of touching a set of files via nine weighted signals
(0-2 points each, max 18). Every signal carries a human-readable detail string
so the verdict is explainable: score -> LOW/MEDIUM/HIGH/CRITICAL with an
optional user-criticality override that can only raise the level.

All subprocess probes (git hotspot) are error-graced: a missing repo or a
non-git directory never raises, it yields a 0-point hotspot signal with
detail "unavailable".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import BrainError

RISK_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

SIGNAL_NAMES: tuple[str, ...] = (
    "blast_radius",
    "centrality",
    "concurrency",
    "persistence",
    "security_boundary",
    "public_api",
    "data_loss",
    "config_scope",
    "hotspot",
)

_GIT_TIMEOUT = 15.0
_MAX_HOTSPOT_COMMITS = 20
_BLAST_THRESHOLDS = (2, 5)  # <2 -> 0, 2-5 -> 1, >5 -> 2
_SCORE_LEVELS = (
    (9, "HIGH"),
    (6, "MEDIUM"),
    (3, "LOW"),
)  # score<3 LOW, <6 MEDIUM, <9 HIGH, else CRITICAL


def _norm(path: str) -> str:
    """Forward-slash normalized, case-preserved path for substring matching."""
    return str(path).replace("\\", "/")


def _parts(path: str) -> list[str]:
    return [part for part in _norm(path).split("/") if part]


def _has_part(path: str, name: str) -> bool:
    return name in _parts(path)


def _signal(name: str, value: int, points: int, detail: str) -> dict:
    return {"name": name, "value": value, "points": points, "detail": detail}


def _binary_signal(name: str, matched: list[str], matched_by: str) -> dict:
    if matched:
        shown = ", ".join(sorted(matched)[:3])
        return _signal(name, 1, 2, f"{matched_by}: {shown}")
    return _signal(name, 0, 0, f"no {matched_by} paths")


def _hotspot_signal(repo: Path, files: list[str]) -> dict:
    """Max commit churn per touched file via `git log --oneline -20 -- <file>`."""
    if not files:
        return _signal("hotspot", 0, 0, "no files touched")
    max_commits = 0
    max_file: str | None = None
    for file in files:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "log", "--oneline", "-20", "--", file],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
                errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            return _signal("hotspot", 0, 0, "unavailable")
        if result.returncode != 0:
            return _signal("hotspot", 0, 0, "unavailable")
        commits = len([line for line in result.stdout.splitlines() if line.strip()])
        if commits > max_commits:
            max_commits, max_file = commits, file
    if max_commits > 5:
        points = 2
    elif max_commits > 0:
        points = 1
    else:
        points = 0
    detail = (
        f"{max_file} has {max_commits} commits in last {_MAX_HOTSPOT_COMMITS}"
        if max_file is not None
        else "no git history"
    )
    return _signal("hotspot", max_commits, points, detail)


def _compute_signals(repo: Path, files: list[str]) -> list[dict]:
    n = len(files)
    blast_points = 0 if n < _BLAST_THRESHOLDS[0] else (1 if n <= _BLAST_THRESHOLDS[1] else 2)
    signals = [
        _signal("blast_radius", n, blast_points, f"{n} file(s) touched"),
        _binary_signal(
            "centrality",
            [f for f in files if _is_central(f)],
            "central paths (db/ registry constitution config src/second_brain)",
        ),
        _binary_signal(
            "concurrency",
            [f for f in files if _mentions(f, ("lock", "process", "daemon", "ownership"))],
            "concurrency-sensitive",
        ),
        _binary_signal(
            "persistence",
            [f for f in files if _is_persistent(f)],
            "persistent paths (db/ migrations)",
        ),
        _binary_signal(
            "security_boundary",
            [f for f in files if _mentions(f, ("constitution", "immune", "secrets", "security"))],
            "security-sensitive",
        ),
        _binary_signal(
            "public_api",
            [f for f in files if "cli.py" in _norm(f) or "prime-extension" in _norm(f)],
            "public API paths",
        ),
        _binary_signal(
            "data_loss",
            [f for f in files if _mentions(f, ("backup", "restore", "delete", "unlink", "rmtree"))],
            "data-loss",
        ),
        _binary_signal(
            "config_scope",
            [f for f in files if _has_part(f, "config")],
            "config paths",
        ),
        _hotspot_signal(repo, files),
    ]
    return signals


def _is_central(path: str) -> bool:
    p = _norm(path)
    parts = _parts(path)
    return (
        _has_part(path, "db")
        or _has_part(path, "registry")
        or _has_part(path, "constitution")
        or _has_part(path, "config")
        or "registry" in p
        or parts[:2] == ["src", "second_brain"]
    )


def _is_persistent(path: str) -> bool:
    return _has_part(path, "db") or "migration" in _norm(path)


def _mentions(path: str, needles: tuple[str, ...]) -> bool:
    lower = _norm(path).lower()
    return any(needle in lower for needle in needles)


def assess_risk(
    repo: Path,
    files_touched: list[str],
    user_criticality: str | None = None,
) -> dict:
    """Score the risk of touching `files_touched` in `repo`.

    Returns ``{"level", "score", "signals", "user_criticality"}``. Never
    raises for missing repos or non-git directories (hotspot degrades to
    "unavailable").
    """
    if not isinstance(files_touched, list) or any(
        not isinstance(item, str) for item in files_touched
    ):
        raise BrainError("files_touched must be a list of strings")
    signals = _compute_signals(Path(repo), files_touched)
    score = sum(signal["points"] for signal in signals)
    level = "CRITICAL"
    for threshold, name in _SCORE_LEVELS:  # descending: 9->HIGH, 6->MEDIUM, 3->LOW
        if score < threshold:
            level = name
    if user_criticality in RISK_LEVELS and RISK_LEVELS.index(user_criticality) > RISK_LEVELS.index(
        level
    ):
        level = user_criticality
    return {
        "level": level,
        "score": score,
        "signals": signals,
        "user_criticality": user_criticality,
    }
