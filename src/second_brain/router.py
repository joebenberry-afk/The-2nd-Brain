"""Skill router — sparse top-K, report-only route (plan §56/§113, Phase 17;
Phase 23: pool = active + candidate + shadow).

Ranks shadow skills (``skills/shadow/<name>/SKILL.md``) by a deterministic
score: +1 per positive trigger phrase matched in the task (case-insensitive
substring), -2 per negative trigger phrase, +1.5 when an adjacent name bigram
appears in the task, +0.25 per procedure-token overlap (capped 0.5, generic
stopwords excluded). Only skills with score >= 1.0 are selected, capped at
``max_active`` (sparse routing, plan §56) — resolved from
``config/skills.toml [router] max_active`` (fallback 3) unless the caller
passes an explicit cap (CLI ``--max-active``). The natural baseline is the
naive name-token match the plan says Brainstem must beat on trigger noise.

Phase 13: SKILL.md sections are cached per path with mtime_ns invalidation,
so each unchanged skill is read AT MOST ONCE per route() call and not at all
on later calls. The cache is a plain dict guarded by a lock (the router is a
single-process CLI; the lock only protects dict access).
"""

from __future__ import annotations

import itertools
import re
import threading
import tomllib
from pathlib import Path

from . import paths
from .errors import BrainError

POSITIVE_POINTS = 1.0
NEGATIVE_POINTS = -2.0
PROCEDURE_OVERLAP_POINTS = 0.25
PROCEDURE_CAP = 0.5
NAME_BIGRAM_POINTS = 1.5
SELECTION_THRESHOLD = 1.0
TOKEN_MIN_LEN = 4

# Generic tokens that must not count as procedure/name signal (they trigger
# noise on everyday tasks like "update the README").
STOPWORDS = {
    "update",
    "create",
    "make",
    "run",
    "check",
    "use",
    "add",
    "remove",
    "the",
    "with",
    "from",
    "this",
    "that",
    "will",
    "your",
    "their",
    "into",
    "file",
    "files",
    "test",
    "tests",
    "note",
    "notes",
    "team",
    "wiki",
    "site",
    "plan",
    "website",
    "marketing",
    "change",
    "changes",
    "patch",
}

_SECTION_TITLES = {
    "positive": "Positive Triggers",
    "negative": "Negative Triggers",
    "procedure": "Procedure",
}


LEVEL_PRIORITY = ("active", "candidate", "shadow")


def _level_dirs(home: Path) -> list[Path]:
    return [Path(home) / paths.SKILL_LEVEL_DIRS[level] for level in LEVEL_PRIORITY]


def _skill_level(home: Path, name: str) -> str | None:
    for level, directory in zip(LEVEL_PRIORITY, _level_dirs(home), strict=True):
        if (directory / name / "SKILL.md").exists():
            return level
    return None


def _all_skill_names(home: Path) -> list[str]:
    names: set[str] = set()
    for directory in _level_dirs(home):
        if directory.is_dir():
            names.update(p.name for p in directory.iterdir() if p.is_dir())
    return sorted(names)


def _shadow_dir(home: Path) -> Path:
    return Path(home) / paths.SKILL_LEVEL_DIRS["shadow"]


def _tokens(text: str) -> set[str]:
    return set(re.findall(rf"[a-z0-9]{{{TOKEN_MIN_LEN},}}", text.lower()))


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("# "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = line[2:].strip()
            buffer = []
        else:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def _phrases(section_text: str) -> list[str]:
    phrases = []
    for line in section_text.splitlines():
        line = line.strip()
        if not line or line in ("(none)", "(fill me)"):
            continue
        if line.startswith("- "):
            line = line[2:]
        elif line == "-":
            continue
        phrases.append(line)
    return phrases


# SKILL.md section cache: path -> (mtime_ns, parsed sections). Each
# unchanged skill file is read at most once per route() call and skipped on
# later calls (Phase 13). Single-process CLI; the lock only guards dict
# access so concurrent route() calls cannot corrupt the cache.
_SECTION_CACHE: dict[Path, tuple[int, dict[str, str]]] = {}
_SECTION_CACHE_LOCK = threading.Lock()


def _clear_skill_section_cache() -> None:
    """Drop all cached SKILL.md sections (tests; also safe at runtime)."""
    with _SECTION_CACHE_LOCK:
        _SECTION_CACHE.clear()


def _skill_sections(home: Path, name: str) -> dict[str, str]:
    for directory in _level_dirs(home):
        path = directory / name / "SKILL.md"
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            continue
        with _SECTION_CACHE_LOCK:
            cached = _SECTION_CACHE.get(path)
            if cached is not None and cached[0] == mtime_ns:
                return cached[1]
        sections = _parse_sections(path.read_text(encoding="utf-8"))
        with _SECTION_CACHE_LOCK:
            _SECTION_CACHE[path] = (mtime_ns, sections)
        return sections
    raise BrainError(f"No skill {name!r} under skills/active|candidate|shadow")


def _name_tokens(name: str) -> set[str]:
    return _tokens(name.replace("-", " ").replace("_", " "))


def _score_skill(home: Path, name: str, task_lower: str, task_tokens: set[str]) -> float:
    """Deterministic shadow score.

    Trigger phrases are the primary signal (+1 each). Negative phrases
    subtract 2 each. A skill-name bigram (adjacent name tokens) in the task
    is a strong explicit signal (+1.5). Generic procedure/name tokens are a
    weak tiebreaker only (0.25 each, capped 0.5), and generic stopwords
    never count. Selection requires score >= SELECTION_THRESHOLD so a
    mention like "migration of the marketing website" does not route.
    """
    sections = _skill_sections(home, name)
    score = 0.0
    positive = _phrases(sections.get(_SECTION_TITLES["positive"], ""))
    negative = _phrases(sections.get(_SECTION_TITLES["negative"], ""))
    for phrase in positive:
        if phrase.lower() in task_lower:
            score += POSITIVE_POINTS
    for phrase in negative:
        if phrase.lower() in task_lower:
            score += NEGATIVE_POINTS

    name_words = re.findall(r"[a-z0-9]+", name.replace("-", " ").replace("_", " ").lower())
    bigrams = set(itertools.pairwise(name_words))  # adjacent in NAME order
    task_word_list = re.findall(r"[a-z0-9]+", task_lower)
    task_bigrams = set(itertools.pairwise(task_word_list))
    if bigrams & task_bigrams:
        score += NAME_BIGRAM_POINTS

    proc = _skill_sections(home, name).get(_SECTION_TITLES["procedure"], "")
    proc_tokens = _tokens(proc) - STOPWORDS
    overlap = len((task_tokens - STOPWORDS) & proc_tokens) * PROCEDURE_OVERLAP_POINTS
    score += min(overlap, PROCEDURE_CAP)

    name_set = set(name_words)
    name_bonus = len((task_tokens - STOPWORDS) & (name_set - STOPWORDS))
    score += (
        NAME_BIGRAM_POINTS
        if name_bonus and not (bigrams & task_bigrams) and len(name_words) < 3
        else 0.0
    )
    return round(score, 2)


def _router_max_active(home: Path) -> int:
    """[router] max_active from <home>/config/skills.toml, default 3.

    Same tomllib pattern as working_set._material_gate_blocks. Invalid or
    absent values fall back to 3 (fail-safe: sparse routing stays sparse).
    """
    try:
        cfg = tomllib.loads((Path(home) / "config" / "skills.toml").read_text(encoding="utf-8"))
        value = (cfg.get("router") or {}).get("max_active", 3)
    except (OSError, tomllib.TOMLDecodeError):
        return 3
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return 3
    return value


def route(
    home: Path,
    task: str,
    *,
    max_active: int | None = None,
    skills: list[str] | None = None,
) -> dict:
    """Rank skills for `task` (Phase 23: active > candidate > shadow pool).
    Deterministic; report-only — routing never substitutes content.

    Degenerate input never raises: a blank/whitespace-only task (including
    exotic whitespace like U+0085) routes to nothing rather than blocking.

    ``max_active`` (Phase 13): explicit cap (CLI ``--max-active``). When
    None (default), resolved from ``config/skills.toml [router] max_active``;
    invalid or missing config values fall back to 3.

    ``skills`` (Phase 18): an explicit skill-name list override so callers can
    route over a filtered set (e.g. counterfactuals) without touching the
    filesystem. Defaults to all skills across active/candidate/shadow.
    """
    if not isinstance(task, str):
        raise BrainError("task must be a string")
    if max_active is None:
        max_active = _router_max_active(home)
    if not isinstance(max_active, int) or isinstance(max_active, bool) or max_active <= 0:
        raise BrainError("max_active must be a positive integer")
    if skills is not None and (
        not isinstance(skills, list) or any(not isinstance(s, str) or not s for s in skills)
    ):
        raise BrainError("skills must be a list of non-empty strings or None")
    if not task.strip():
        return {"selected": [], "scores": {}, "shadow": True}
    names = sorted(skills) if skills is not None else _all_skill_names(home)
    task_lower = task.lower()
    task_tokens = _tokens(task)
    scores = {name: _score_skill(home, name, task_lower, task_tokens) for name in names}
    selected = sorted(
        (name for name, score in scores.items() if score >= SELECTION_THRESHOLD),
        key=lambda name: (-scores[name], name),
    )[:max_active]
    return {"selected": selected, "scores": scores, "shadow": True}


def natural_baseline(home: Path, task: str) -> list[str]:
    """Model-natural routing proxy: skills whose NAME tokens (len >= 4) appear
    in the task. Naive — it is the baseline Brainstem must beat on trigger
    noise (plan §113)."""
    names = _all_skill_names(home)
    task_tokens = _tokens(task)
    return [name for name in names if _name_tokens(name) & task_tokens]


def _metrics(predictions: dict[str, list[str]], tasks: list[dict]) -> dict:
    precision_sum = 0.0
    recall_sum = 0.0
    f1_sum = 0.0
    noise = 0
    for task in tasks:
        expected = set(task.get("expect") or [])
        predicted = set(predictions.get(str(task.get("text", "")), []))
        true_positive = len(predicted & expected)
        precision = true_positive / len(predicted) if predicted else 0.0
        recall = true_positive / len(expected) if expected else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        precision_sum += precision
        recall_sum += recall
        f1_sum += f1
        noise += len(predicted - expected)
    n = len(tasks)
    return {
        "precision": round(precision_sum / n, 4) if n else 0.0,
        "recall": round(recall_sum / n, 4) if n else 0.0,
        "f1": round(f1_sum / n, 4) if n else 0.0,
        "noise": noise,
    }


def eval_router(home: Path, tasks: list[dict]) -> dict:
    """Compare Brainstem routing vs the natural baseline on labeled tasks
    {text, expect: [names]}: per-method average precision/recall/f1 plus total
    noise (selected-but-not-expected)."""
    router_predictions: dict[str, list[str]] = {}
    natural_predictions: dict[str, list[str]] = {}
    for task in tasks:
        text = str(task.get("text", ""))
        router_predictions[text] = route(home, text)["selected"]
        natural_predictions[text] = natural_baseline(home, text)
    return {
        "router": _metrics(router_predictions, tasks),
        "natural": _metrics(natural_predictions, tasks),
    }
