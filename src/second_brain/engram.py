"""Workflow engrams (plan §58/§115, Phase 19).

Repeated successful skill sequences become candidate compositional macros.
Candidate-only: engrams NEVER duplicate underlying skill logic — they
coordinate existing specialists (a Procedure/Steps section is a validation
failure). Detection is deterministic: contiguous adjacent subsequences of
length min_len..max_len, support = number of input sequences containing the
subsequence at least once.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .errors import BrainError

NON_RESPONSIBILITIES = "This engram duplicates NO skill logic; execute referenced skills instead."
FORBIDDEN_SECTIONS = ("Procedure", "Steps")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _candidates_dir(home: Path) -> Path:
    return Path(home) / "engrams" / "candidates"


def _skill_dirs(home: Path) -> tuple[Path, Path]:
    return Path(home) / "skills" / "shadow", Path(home) / "skills" / "candidates"


def _skill_exists(home: Path, name: str) -> bool:
    return any((directory / name).is_dir() for directory in _skill_dirs(home))


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


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_engrams(
    sequences: list[list[str]],
    min_support: int = 2,
    min_len: int = 2,
    max_len: int = 5,
) -> list[dict]:
    """Count contiguous adjacent subsequences (lengths min_len..max_len) across
    skill-activation sequences. Support = number of distinct sequences that
    contain the subsequence at least once (overlapping windows deduped per
    sequence). Ordered by (support DESC, length DESC, sequence)."""
    if not isinstance(sequences, list):
        raise BrainError("sequences must be a list of skill-name lists")
    support: dict[tuple[str, ...], int] = {}
    example_tasks: dict[tuple[str, ...], list[int]] = {}
    for index, sequence in enumerate(sequences):
        if not isinstance(sequence, list) or any(not isinstance(s, str) for s in sequence):
            raise BrainError(f"sequence {index} must be a list of skill-name strings")
        seen: set[tuple[str, ...]] = set()
        for start in range(len(sequence)):
            for length in range(min_len, min(max_len, len(sequence) - start) + 1):
                window = tuple(sequence[start : start + length])
                if window not in seen:
                    seen.add(window)
                    support[window] = support.get(window, 0) + 1
                    example_tasks.setdefault(window, []).append(index)
    results = [
        {
            "sequence": list(window),
            "support": count,
            "example_tasks": example_tasks[window],
        }
        for window, count in support.items()
        if count >= min_support
    ]
    results.sort(
        key=lambda item: (
            -item["support"],
            -len(item["sequence"]),
            item["sequence"],
        )
    )
    return results


# ---------------------------------------------------------------------------
# Write / validate
# ---------------------------------------------------------------------------


def _reserve_exclusive(path: Path) -> int | None:
    """Open with O_CREAT|O_EXCL; returns an fd or None when the name is taken."""
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def write_engram(
    home: Path,
    name: str,
    skills: list[str],
    source_sequences: list[list[str]],
    trigger_note: str = "",
) -> Path:
    """Write a candidate engram file. Collision-safe: never overwrites (retries
    with a -N suffix). References must resolve to existing skills."""
    if not isinstance(name, str) or not name.strip():
        raise BrainError("name must be a non-empty string")
    if (
        not isinstance(skills, list)
        or not skills
        or any(not isinstance(skill, str) or not skill for skill in skills)
    ):
        raise BrainError("skills must be a non-empty list of strings")
    if not isinstance(source_sequences, list) or not source_sequences:
        raise BrainError("source_sequences must be a non-empty list")
    missing = [skill for skill in skills if not _skill_exists(home, skill)]
    if missing:
        raise BrainError(f"Referenced skill(s) do not exist: {', '.join(missing)}")

    trigger = trigger_note.strip() if trigger_note.strip() else "(infer from first skill)"
    evidence_lines = ["- " + " -> ".join(sequence) for sequence in source_sequences]
    lines = [
        "---",
        f"name: {name}",
        "status: candidate",
        f"skills: {json.dumps(skills)}",
        f"sources: {len(source_sequences)}",
        f"created_at: {_utcnow()}",
        "---",
        "",
        "# References",
        "",
        *[f"- {skill}" for skill in skills],
        "",
        "# Trigger",
        "",
        trigger,
        "",
        "# Evidence",
        "",
        *evidence_lines,
        "",
        "# Non-responsibilities",
        "",
        NON_RESPONSIBILITIES,
        "",
    ]
    content = "\n".join(lines).rstrip() + "\n"

    directory = _candidates_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.md"
    counter = 1
    while True:
        fd = _reserve_exclusive(target)
        if fd is not None:
            break
        target = directory / f"{name}-{counter}.md"
        counter += 1
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    except OSError as exc:
        raise BrainError(f"Could not write engram {target}: {exc}") from exc
    return target


def _engram_file(home: Path, name: str) -> Path:
    path = _candidates_dir(home) / f"{name}.md"
    if not path.exists():
        raise BrainError(f"No candidate engram {name!r} at {path}")
    return path


def validate_engram(home: Path, name: str) -> dict:
    """Structural checks: all referenced skills exist, no Procedure/Steps
    section, and non-empty evidence."""
    path = _engram_file(home, name)
    text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    skills: list[str] = []
    if text.startswith("---"):
        frontmatter = text.split("---", 2)[1]
        for line in frontmatter.splitlines():
            if line.startswith("skills:"):
                try:
                    parsed = json.loads(line[len("skills:") :].strip())
                except json.JSONDecodeError:
                    parsed = []
                skills = [str(item) for item in parsed] if isinstance(parsed, list) else []
    missing = [skill for skill in skills if not _skill_exists(home, skill)]
    if missing:
        issues.append(f"referenced skill(s) missing: {', '.join(missing)}")
    sections = _parse_sections(text)
    for forbidden in FORBIDDEN_SECTIONS:
        if forbidden in sections:
            issues.append(f"forbidden section {forbidden!r} present (engrams must not carry logic)")
    evidence = sections.get("Evidence", "")
    if not evidence.strip():
        issues.append("Evidence section is empty")
    return {"ok": not issues, "issues": issues}


def list_engrams(home: Path) -> list[str]:
    directory = _candidates_dir(home)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))
