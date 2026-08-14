"""Skill Forge (plan §60-61/§112, Phase 16).

Episode -> pattern -> candidate skill -> evals -> shadow. Candidates only:
nothing is installed or promoted automatically (promotion is a later phase).

A candidate lives at ``skills/candidates/<name>/SKILL.md`` with the ten §60
sections. Evals are deterministic and structural: trigger boundaries, a
structural workflow smoke test, regression re-checks, and static security
review. Shadowing (moving candidate -> skills/shadow/<name>) is refused unless
every gate passes.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import episodes
from .errors import BrainError

REQUIRED_SECTIONS: tuple[str, ...] = (
    "purpose",
    "positive_triggers",
    "negative_triggers",
    "inputs",
    "procedure",
    "tools",
    "safety",
    "verification",
    "output",
    "references",
)

_SECTION_TITLES = {name: name.replace("_", " ").title() for name in REQUIRED_SECTIONS}

# Which placeholder tokens are allowed in which section (validate_candidate).
_ALLOWED_PLACEHOLDERS = {
    "inputs": {"(fill me)"},
    "tools": {"(fill me)"},
    "output": {"(fill me)"},
    "safety": {"(review required)"},
    "verification": {"(eval required)"},
}

_DANGEROUS_TOKENS = ("rm -rf", "del /s")
_DISK_FORMAT_RE = re.compile(r"\bformat\s+[a-zA-Z]:(\s|/|$)|\bformat\s+\S+\s*/(q|fs|v):")
_SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9]{12,}|api_key\s*[:=]\s*\S{12,}")
_EXFIL_URL_RE = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)\S+")
_INJECTION_PHRASES = ("ignore previous", "must not follow")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _candidates_dir(home: Path) -> Path:
    return Path(home) / "skills" / "candidates"


def _shadow_dir(home: Path) -> Path:
    return Path(home) / "skills" / "shadow"


def _skill_path(home: Path, name: str) -> Path:
    return _candidates_dir(home) / name / "SKILL.md"


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


def _section_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _union_lines(sections: list[str]) -> list[str]:
    out: list[str] = []
    for section in sections:
        for line in _section_lines(section):
            if line not in out:
                out.append(line)
    return out


# ---------------------------------------------------------------------------
# Forge
# ---------------------------------------------------------------------------


def forge_candidate(home: Path, name: str, episode_ids: list[str]) -> Path:
    """Build a candidate SKILL.md from episodes. Collision-safe: never
    overwrites an existing candidate (retries with a -N suffix)."""
    if not isinstance(name, str) or not name.strip():
        raise BrainError("name must be a non-empty string")
    if (
        not isinstance(episode_ids, list)
        or not episode_ids
        or any(not isinstance(eid, str) for eid in episode_ids)
    ):
        raise BrainError("episode_ids must be a non-empty list of strings")
    shown = []
    summaries = []
    trigger_sections = []
    counter_sections = []
    lessons = []
    evidence_refs: list[str] = []
    for episode_id in episode_ids:
        item = episodes.show_episode(home, episode_id)
        shown.append(item)
        sections = _parse_sections(item["body"])
        summaries.append(item["row"]["summary"])
        if sections.get("Trigger signals"):
            trigger_sections.append(sections["Trigger signals"])
        if sections.get("Counter-signals"):
            counter_sections.append(sections["Counter-signals"])
        if sections.get("Reusable lesson"):
            for line in _section_lines(sections["Reusable lesson"]):
                if line not in lessons:
                    lessons.append(line)
        refs = item["row"].get("evidence_refs")
        if refs:
            try:
                parsed = json.loads(refs)
            except json.JSONDecodeError:
                parsed = []
            evidence_refs.extend(str(ref) for ref in parsed if isinstance(ref, str))

    purpose = "\n".join(f"- {summary}" for summary in summaries)
    positive = _union_lines(trigger_sections) or ["(none)"]
    negative = _union_lines(counter_sections) or ["(none)"]
    procedure = "\n".join(f"{i}. {lesson}" for i, lesson in enumerate(lessons, start=1))
    if not lessons:
        procedure = "(no reusable lessons yet)"

    lines = [
        "---",
        f"name: {name}",
        "status: candidate",
        "source_episodes:",
        *[f"- {eid}" for eid in episode_ids],
        f"created_at: {_utcnow()}",
        "---",
        "",
    ]
    body = {
        "purpose": purpose,
        "positive_triggers": "\n".join(positive),
        "negative_triggers": "\n".join(negative),
        "inputs": "(fill me)",
        "procedure": procedure,
        "tools": "(fill me)",
        "safety": "(review required)",
        "verification": "(eval required)",
        "output": "(fill me)",
        "references": "\n".join(
            [
                *[f"- episode {eid}" for eid in episode_ids],
                *[f"- evidence {ref}" for ref in evidence_refs],
            ]
        ),
    }
    for section in REQUIRED_SECTIONS:
        lines.append(f"# {_SECTION_TITLES[section]}")
        lines.append("")
        lines.append(body[section])
        lines.append("")

    target_dir = _allocate_dir(_candidates_dir(home), name)
    target = target_dir / "SKILL.md"
    fd, tmp = tempfile.mkstemp(dir=target_dir, prefix="SKILL.md.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write candidate skill {target}: {exc}") from exc
    return target


def _allocate_dir(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    candidate = parent / name
    counter = 1
    while True:
        try:
            candidate.mkdir()  # exclusive: FileExistsError on collision
            return candidate
        except FileExistsError:
            candidate = parent / f"{name}-{counter}"
            counter += 1


# ---------------------------------------------------------------------------
# Validation and evals
# ---------------------------------------------------------------------------


def _candidate_sections(home: Path, name: str) -> dict[str, str]:
    path = _skill_path(home, name)
    if not path.exists():
        raise BrainError(f"No candidate skill {name!r} at {path}")
    return _parse_sections(path.read_text(encoding="utf-8"))


def validate_candidate(home: Path, name: str) -> dict:
    """Structural plan §60 check: all ten sections present, non-empty, and free
    of placeholders except where explicitly allowed."""
    sections = _candidate_sections(home, name)
    missing = [
        _SECTION_TITLES[section]
        for section in REQUIRED_SECTIONS
        if _SECTION_TITLES[section] not in sections
    ]
    issues: list[str] = []
    for section in REQUIRED_SECTIONS:
        title = _SECTION_TITLES[section]
        if title in missing:
            continue
        content = sections[title]
        if not content.strip():
            issues.append(f"section {title!r} is empty")
            continue
        allowed = _ALLOWED_PLACEHOLDERS.get(section, set())
        for line in _section_lines(content):
            lowered = line.lower()
            if "(fill me)" in lowered and "(fill me)" not in allowed:
                issues.append(f"section {title!r} contains '(fill me)' (not allowed here)")
            if "(review required)" in lowered and "(review required)" not in allowed:
                issues.append(f"section {title!r} contains '(review required)' (not allowed here)")
            if "(eval required)" in lowered and "(eval required)" not in allowed:
                issues.append(f"section {title!r} contains '(eval required)' (not allowed here)")
            if re.search(r"\bTBD\b|\bTODO\b", line):
                issues.append(f"section {title!r} contains TBD/TODO")
    return {"ok": not missing and not issues, "missing_sections": missing, "issues": issues}


def _trigger_phrases(home: Path, name: str, section: str) -> list[str]:
    sections = _candidate_sections(home, name)
    title = _SECTION_TITLES[section]
    phrases = []
    for line in _section_lines(sections.get(title, "")):
        if line in ("(none)", "(fill me)"):
            continue
        if line.startswith("- "):
            line = line[2:]
        elif line == "-":
            continue
        phrases.append(line)
    return phrases


def _triggers(text: str, positive: list[str], negative: list[str]) -> bool:
    lowered = text.lower()
    has_positive = any(phrase.lower() in lowered for phrase in positive)
    has_negative = any(phrase.lower() in lowered for phrase in negative)
    return has_positive and not has_negative


def trigger_eval(home: Path, name: str, cases: list[dict]) -> dict:
    """Boundary eval: a case triggers iff ANY positive phrase matches and NO
    negative phrase matches (case-insensitive substring)."""
    positive = _trigger_phrases(home, name, "positive_triggers")
    negative = _trigger_phrases(home, name, "negative_triggers")
    results = []
    failed = 0
    for case in cases:
        text = str(case.get("text", ""))
        expect = case.get("expect")
        predicted = "trigger" if _triggers(text, positive, negative) else "no_trigger"
        ok = predicted == expect
        failed += 0 if ok else 1
        results.append(
            {
                "text": text,
                "expect": expect,
                "predicted": predicted,
                "ok": ok,
            }
        )
    return {
        "total": len(cases),
        "passed": len(cases) - failed,
        "failed": failed,
        "results": results,
    }


def _procedure_steps(home: Path, name: str) -> int:
    sections = _candidate_sections(home, name)
    procedure = sections.get(_SECTION_TITLES["procedure"], "")
    return len(re.findall(r"(?m)^\s*\d+\.\s+", procedure))


def workflow_eval(home: Path, name: str, scenarios: list[dict]) -> dict:
    """Structural procedural smoke test: the procedure must have >= 1 numbered
    step and every scenario must provide non-empty steps. 'pass' scenarios
    must satisfy the structure; 'fail' scenarios must not. Honest note: actual
    procedure execution is the caller's job."""
    steps = _procedure_steps(home, name)
    results = []
    failed = 0
    for scenario in scenarios:
        scenario_steps = scenario.get("steps") or []
        expect = scenario.get("expect")
        predicted = (
            "pass"
            if (steps >= 1 and isinstance(scenario_steps, list) and scenario_steps)
            else "fail"
        )
        ok = predicted == expect
        failed += 0 if ok else 1
        results.append(
            {
                "name": scenario.get("name", "?"),
                "predicted": predicted,
                "expect": expect,
                "ok": ok,
            }
        )
    return {
        "structural": True,
        "procedure_steps": steps,
        "total": len(scenarios),
        "passed": len(scenarios) - failed,
        "failed": failed,
        "results": results,
        "note": "structural workflow eval only; procedure execution is the caller's job",
    }


def regression_eval(home: Path, name: str, baseline_cases: list[dict]) -> dict:
    """Baseline cases must ALL still pass trigger_eval — any fail is a
    regression."""
    result = trigger_eval(home, name, baseline_cases)
    return {
        "regression": result["failed"] > 0,
        "total": result["total"],
        "failed": result["failed"],
        "results": result["results"],
    }


def security_review(home: Path, name: str) -> dict:
    """Static heuristics over SKILL.md: shell-dangerous tokens, secret
    patterns, network exfiltration shapes, instruction-injection phrasing."""
    path = _skill_path(home, name)
    text = path.read_text(encoding="utf-8")
    findings: list[dict] = []
    lowered = text.lower()

    for token in _DANGEROUS_TOKENS:
        if token.lower() in lowered:
            findings.append({"category": "destructive", "detail": f"contains {token!r}"})
    for match in _DISK_FORMAT_RE.finditer(lowered):
        findings.append(
            {
                "category": "destructive",
                "detail": f"disk-format command at offset {match.start()}",
            }
        )
    for match in _SECRET_RE.finditer(text):
        findings.append(
            {"category": "secret", "detail": f"secret-like value at offset {match.start()}"}
        )
    for line in text.splitlines():
        if (
            "|" in line
            and any(tool in line.lower() for tool in ("curl", "wget", "invoke-webrequest"))
            and _EXFIL_URL_RE.search(line)
        ):
            findings.append(
                {
                    "category": "exfiltration",
                    "detail": f"download piped to a shell: {line.strip()[:80]!r}",
                }
            )
    for phrase in _INJECTION_PHRASES:
        if phrase in lowered:
            findings.append({"category": "instruction-injection", "detail": f"contains {phrase!r}"})

    return {"passed": not findings, "findings": findings}


# ---------------------------------------------------------------------------
# Shadow (gate only; no install/promotion)
# ---------------------------------------------------------------------------


def shadow_candidate(
    home: Path,
    name: str,
    trigger_cases: list[dict],
    baseline_cases: list[dict],
) -> Path:
    """Move skills/candidates/<name> -> skills/shadow/<name> only when
    validate, security review, trigger and regression evals all pass. Refuses
    otherwise; never installs anywhere else."""
    reasons: list[str] = []
    validation = validate_candidate(home, name)
    if not validation["ok"]:
        reasons.append(
            f"validation failed: {validation['issues'] or validation['missing_sections']}"
        )
    security = security_review(home, name)
    if not security["passed"]:
        reasons.append(f"security review failed: {[f['category'] for f in security['findings']]}")
    trigger = trigger_eval(home, name, trigger_cases)
    if trigger["failed"]:
        reasons.append(f"trigger eval failed {trigger['failed']}/{trigger['total']}")
    regression = regression_eval(home, name, baseline_cases)
    if regression["regression"]:
        reasons.append(f"regression eval failed {regression['failed']}/{regression['total']}")
    if reasons:
        raise BrainError(f"Refusing to shadow {name!r}: {'; '.join(reasons)}")

    source = _candidates_dir(home) / name
    target = _shadow_dir(home) / name
    if not source.is_dir():
        raise BrainError(f"No candidate {name!r} at {source}")
    if target.exists():
        raise BrainError(f"Shadow target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return target


def list_candidates(home: Path) -> list[str]:
    directory = _candidates_dir(home)
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_dir())


def list_shadow(home: Path) -> list[str]:
    directory = _shadow_dir(home)
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_dir())
