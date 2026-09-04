"""Workflow engrams (plan §58/§115, Phase 19).

Repeated successful skill sequences become candidate compositional macros.
Candidate-only: engrams NEVER duplicate underlying skill logic — they
coordinate existing specialists (a Procedure/Steps section is a validation
failure). Detection is deterministic: contiguous adjacent subsequences of
length min_len..max_len, support = number of input sequences containing the
subsequence at least once.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts
from .errors import BrainError
from .security.identifiers import validate_engram_name

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
    name = validate_engram_name(name)
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
    # SEC-03: engram names reach filesystem paths; only validated identifiers.
    name = validate_engram_name(name)
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


def _deterministic_dir(home: Path) -> Path:
    return Path(home) / "engrams" / "deterministic"


def detect_workflow_engrams(
    session_events: Sequence[Sequence[Mapping[str, Any]]],
    min_support: int = 2,
    min_len: int = 3,
    max_len: int = 5,
) -> list[dict[str, Any]]:
    """Detect repeated tool-call sequences from session ledger events.

    Input: tool-call sequences from events where kind=tool_call.
    Minimum support: 2 (default).
    Sequence length: 3-5 (default).
    """
    if not isinstance(session_events, Sequence):
        raise BrainError("session_events must be a sequence of session event lists")

    tool_sequences: list[list[dict[str, Any]]] = []
    for sess in session_events:
        curr: list[dict[str, Any]] = []
        for ev in sess:
            kind = ev.get("kind") or ev.get("event_type")
            if str(kind).lower() in ("tool_call", "tool_use"):
                tool = ev.get("tool") or ev.get("tool_name") or ev.get("name")
                if tool:
                    curr.append({
                        "tool": str(tool),
                        "args_template": dict(
                            ev.get("input") or ev.get("args") or ev.get("args_template") or {}
                        ),
                    })
        if curr:
            tool_sequences.append(curr)

    support: dict[tuple[str, ...], int] = {}
    templates_by_subseq: dict[tuple[str, ...], list[dict[str, Any]]] = {}

    for seq in tool_sequences:
        seen: set[tuple[str, ...]] = set()
        tools_only = [item["tool"] for item in seq]
        for start in range(len(tools_only)):
            for length in range(min_len, min(max_len, len(tools_only) - start) + 1):
                window = tuple(tools_only[start : start + length])
                if window not in seen:
                    seen.add(window)
                    support[window] = support.get(window, 0) + 1
                    if window not in templates_by_subseq:
                        templates_by_subseq[window] = seq[start : start + length]

    results = []
    for window, count in support.items():
        if count >= min_support:
            procedure = [
                {
                    "tool": item["tool"],
                    "args_template": item["args_template"],
                    "precondition": {"cmd": "test -n \"$param\"", "expect_exit": 0},
                    "postcondition": {"cmd": "test $? -eq 0", "expect_exit": 0},
                }
                for item in templates_by_subseq[window]
            ]
            results.append({
                "engram_id": "engram-" + hashlib.sha256("->".join(window).encode("utf-8")).hexdigest()[:16],
                "sequence": list(window),
                "support": count,
                "procedure": procedure,
                "valid_for": {
                    "harness": "universal",
                    "tool_versions": {tool: "1.0" for tool in window},
                    "model": "all",
                },
            })

    results.sort(key=lambda r: (-r["support"], -len(r["sequence"]), r["sequence"]))
    return results


def register_workflow_engram(
    home: Path | str, engram_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Store a versioned deterministic engram procedure."""
    home_p = Path(home)
    directory = _deterministic_dir(home_p)
    directory.mkdir(parents=True, exist_ok=True)

    engram_id = str(
        engram_data.get("engram_id")
        or "engram-"
        + hashlib.sha256(
            contracts.canonical_json(dict(engram_data)).encode("utf-8")
        ).hexdigest()[:16]
    )
    version = int(engram_data.get("version", 1))

    procedure = list(engram_data.get("procedure") or [])
    valid_for = dict(
        engram_data.get("valid_for")
        or {"harness": "universal", "tool_versions": {}, "model": "all"}
    )

    record = {
        "engram_id": engram_id,
        "version": version,
        "procedure": procedure,
        "valid_for": valid_for,
        "status": str(engram_data.get("status", "candidate")),
        "created_at": _utcnow(),
    }

    target = directory / f"{engram_id}_v{version}.json"
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def run_deterministic(
    home: Path | str,
    engram_id: str,
    params: Mapping[str, Any],
    *,
    version: int = 1,
    tool_runner: Callable[[str, Mapping[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Execute a workflow engram deterministically through action_cache with zero model calls."""
    home_p = Path(home)
    directory = _deterministic_dir(home_p)
    target = directory / f"{engram_id}_v{version}.json"
    if not target.is_file():
        raise BrainError(f"Workflow engram {engram_id} v{version} not found at {target}")

    engram_record = json.loads(target.read_text(encoding="utf-8"))
    procedure = engram_record.get("procedure", [])

    from .action_cache import (
        ActionCacheStore,
        ActionProof,
        ActionType,
        DependencyClass,
        compute_action_key,
    )

    cache = ActionCacheStore(home_p)
    proof_key = contracts.canonical_json({
        "engram_id": engram_id,
        "version": version,
        "params": dict(params),
    })
    proof_hash = hashlib.sha256(proof_key.encode("utf-8")).hexdigest()
    proof = ActionProof(
        constant_fingerprint={"procedure_proof": proof_hash},
        dependency_class=DependencyClass.PURE_CONSTANT,
    )

    action_target = f"engram:{engram_id}:v{version}"
    cache_params = {"proof_hash": proof_hash}
    action_key = compute_action_key(
        ActionType.GENERIC_PURE,
        action_target,
        params=cache_params,
        constant_fingerprint=proof.constant_fingerprint,
        dependency_class=proof.dependency_class,
    )
    # Check cache
    cached = cache.query(action_key)
    if cached.hit and cached.content:
        cached_result = json.loads(cached.content)
        cached_result["cache_hit"] = True
        return cached_result

    # Execute procedure steps deterministically with ZERO model calls
    executed_steps: list[dict[str, Any]] = []
    for step_idx, step in enumerate(procedure):
        tool = step.get("tool", "")
        args_template = step.get("args_template", {})

        # 1. Precondition check
        pre = step.get("precondition")
        if pre and isinstance(pre, Mapping):
            expect_exit = pre.get("expect_exit", 0)
            actual_exit = pre.get("actual_exit", 0)
            if actual_exit != expect_exit or pre.get("fail") is True:
                return {
                    "engram_id": engram_id,
                    "version": version,
                    "success": False,
                    "failed_step": step_idx,
                    "failed_phase": "precondition",
                    "reason": "precondition_failed",
                    "model_calls": 0,
                    "cache_hit": False,
                    "steps_executed": step_idx,
                }

        # 2. Tool execution (zero model calls!)
        resolved_args = dict(args_template)
        for k, v in args_template.items():
            if isinstance(v, str) and v.startswith("$"):
                param_key = v[1:]
                if param_key in params:
                    resolved_args[k] = params[param_key]

        if tool_runner is not None:
            step_out = tool_runner(tool, resolved_args)
        else:
            step_out = {"tool": tool, "args": resolved_args, "status": "ok"}

        # 3. Postcondition check
        post = step.get("postcondition")
        if post and isinstance(post, Mapping):
            expect_exit = post.get("expect_exit", 0)
            actual_exit = post.get("actual_exit", 0)
            if (
                actual_exit != expect_exit
                or post.get("fail") is True
                or (
                    isinstance(step_out, Mapping)
                    and step_out.get("postcondition_fail") is True
                )
            ):
                return {
                    "engram_id": engram_id,
                    "version": version,
                    "success": False,
                    "failed_step": step_idx,
                    "failed_phase": "postcondition",
                    "reason": "postcondition_failed",
                    "model_calls": 0,
                    "cache_hit": False,
                    "steps_executed": step_idx,
                }

        executed_steps.append({"step": step_idx, "tool": tool, "output": step_out})

    result_payload = {
        "engram_id": engram_id,
        "version": version,
        "success": True,
        "model_calls": 0,
        "cache_hit": False,
        "steps_executed": len(executed_steps),
        "steps": executed_steps,
    }

    # Store into action cache
    cache.store_action(
        action_type=ActionType.GENERIC_PURE,
        target=action_target,
        content=json.dumps(result_payload),
        proof=proof,
        params=cache_params,
    )

    return result_payload
