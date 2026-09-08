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
from collections.abc import Sequence
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

DEFAULT_CENTRAL_PATHS: tuple[str, ...] = (
    "src/second_brain/db.py",
    "src/second_brain/ledger.py",
    "src/second_brain/contracts.py",
    "migrations/",
)


def _load_verification_config(
    home: Path | str | None = None,
    repo: Path | str | None = None,
) -> dict:
    candidates: list[Path] = []
    if home is not None:
        candidates.append(Path(home) / "config" / "verification.toml")
    if repo is not None:
        candidates.append(Path(repo) / "config" / "verification.toml")
    try:
        from .paths import resolve_home

        candidates.append(resolve_home() / "config" / "verification.toml")
    except Exception:
        pass
    repo_root = Path(__file__).resolve().parent.parent.parent
    candidates.append(repo_root / "config" / "verification.toml")

    for candidate in candidates:
        if candidate.is_file():
            try:
                import tomllib

                return tomllib.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


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


def _compute_signals(
    repo: Path,
    files: list[str],
    central_paths: Sequence[str] | None = None,
) -> list[dict]:
    n = len(files)
    blast_points = 0 if n < _BLAST_THRESHOLDS[0] else (1 if n <= _BLAST_THRESHOLDS[1] else 2)
    signals = [
        _signal("blast_radius", n, blast_points, f"{n} file(s) touched"),
        _binary_signal(
            "centrality",
            [f for f in files if _is_central(f, central_paths=central_paths)],
            "central paths",
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


def _is_central(path: str, central_paths: Sequence[str] | None = None) -> bool:
    if central_paths is None:
        cfg = _load_verification_config()
        configured = cfg.get("risk", {}).get("central_paths")
        if configured is not None and isinstance(configured, (list, tuple)):
            central_paths = configured
        else:
            central_paths = DEFAULT_CENTRAL_PATHS
    p = _norm(path)
    parts = _parts(path)
    for target in central_paths:
        t = _norm(target)
        if not t:
            continue
        if t in p or p.startswith(t) or t.strip("/") in parts:
            return True
    return False


def _is_persistent(path: str) -> bool:
    return _has_part(path, "db") or "migration" in _norm(path)


def _mentions(path: str, needles: tuple[str, ...]) -> bool:
    lower = _norm(path).lower()
    return any(needle in lower for needle in needles)


def assess_risk(
    repo: Path,
    files_touched: list[str],
    user_criticality: str | None = None,
    home: Path | str | None = None,
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

    cfg = _load_verification_config(home=home, repo=repo)
    configured_central = cfg.get("risk", {}).get("central_paths")
    if configured_central is not None and isinstance(configured_central, (list, tuple)):
        central_paths = configured_central
    else:
        central_paths = DEFAULT_CENTRAL_PATHS

    signals = _compute_signals(Path(repo), files_touched, central_paths=central_paths)

    risk_weights = cfg.get("risk_weights")
    if risk_weights and isinstance(risk_weights, dict):
        score = sum(
            float(risk_weights.get(signal["name"], 1.0)) * signal["points"] for signal in signals
        )
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        elif isinstance(score, float):
            score = round(score, 2)
    else:
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
