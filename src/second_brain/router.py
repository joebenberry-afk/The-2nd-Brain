"""Skill router — sparse top-K, SHADOW route only (plan §56/§113, Phase 17).

Ranks shadow skills (``skills/shadow/<name>/SKILL.md``) by a deterministic
score: +1 per positive trigger phrase matched in the task (case-insensitive
substring), -2 per negative trigger phrase, +0.5 for procedure-token overlap,
+1 if any skill-name token appears. Only skills with score > 0 are selected,
capped at ``max_active`` (sparse routing, plan §56). The natural baseline is
the naive name-token match the plan says Brainstem must beat on trigger noise.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

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


def _shadow_dir(home: Path) -> Path:
    return Path(home) / "skills" / "shadow"


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


def _skill_sections(home: Path, name: str) -> dict[str, str]:
    path = _shadow_dir(home) / name / "SKILL.md"
    if not path.exists():
        raise BrainError(f"No shadow skill {name!r} at {path}")
    return _parse_sections(path.read_text(encoding="utf-8"))


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


def route(home: Path, task: str, *, max_active: int = 3) -> dict:
    """Rank shadow skills for `task`. Deterministic; shadow-only.

    Degenerate input never raises: a blank/whitespace-only task (including
    exotic whitespace like U+0085) routes to nothing rather than blocking.
    """
    if not isinstance(task, str):
        raise BrainError("task must be a string")
    if not isinstance(max_active, int) or isinstance(max_active, bool) or max_active <= 0:
        raise BrainError("max_active must be a positive integer")
    if not task.strip():
        return {"selected": [], "scores": {}, "shadow": True}
    directory = _shadow_dir(home)
    names = sorted(p.name for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []
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
    directory = _shadow_dir(home)
    names = sorted(p.name for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []
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
