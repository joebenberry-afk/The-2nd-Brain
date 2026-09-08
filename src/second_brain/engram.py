"""Workflow engrams (plan §58/§115, Phase 19).

Repeated successful skill sequences become candidate compositional macros.
Candidate-only: engrams NEVER duplicate underlying skill logic — they
coordinate existing specialists (a Procedure/Steps section is a validation
failure). Detection is deterministic: contiguous adjacent subsequences of
length min_len..max_len, support = number of input sequences containing the
subsequence at least once.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts
from .errors import BrainError
from .security.identifiers import validate_engram_name
from .security.paths import resolve_under

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


_CACHE_POLICIES = frozenset({"none", "read_only"})
_STEP_EFFECTS = frozenset({"read", "write", "unknown"})
_CONDITION_KEYS = frozenset({"predicate", "args_template", "expect_exit"})


class _WorkflowFailure(Exception):
    def __init__(
        self,
        *,
        step: int,
        phase: str,
        reason: str,
        steps: list[dict[str, Any]],
    ) -> None:
        super().__init__(reason)
        self.step = step
        self.phase = phase
        self.reason = reason
        self.steps = steps


def _workflow_path(home: Path, engram_id: str, version: int, *, allow_missing: bool) -> Path:
    validate_engram_name(engram_id)
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise BrainError("workflow version must be a positive integer")
    relative = f"engrams/deterministic/{engram_id}_v{version}.json"
    try:
        return resolve_under(home, relative, allow_missing=allow_missing)
    except (OSError, ValueError) as exc:
        raise BrainError(f"Unsafe workflow engram path: {exc}") from exc


def _resolve_template(value: Any, params: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if not key or key not in params:
            raise BrainError(f"Missing workflow parameter {key!r}")
        return params[key]
    if isinstance(value, Mapping):
        return {str(key): _resolve_template(item, params) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_template(item, params) for item in value]
    return value


def _runner_result(
    result: Any,
    *,
    expected_tool: str,
    phase: str,
    require_read_only: bool,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise BrainError(f"{phase} executor returned a non-object result")
    if result.get("tool") != expected_tool:
        raise BrainError(f"{phase} executor returned the wrong tool identity")
    exit_code = result.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise BrainError(f"{phase} executor must return an integer exit_code")
    side_effect = result.get("side_effect")
    if not isinstance(side_effect, bool):
        raise BrainError(f"{phase} executor must declare side_effect")
    if require_read_only and side_effect:
        raise BrainError("read_only workflow executor reported a side effect")
    return dict(result)


def _validate_condition(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != _CONDITION_KEYS:
        raise BrainError(f"{label} must contain exactly predicate, args_template, and expect_exit")
    if not isinstance(value["predicate"], str) or not value["predicate"].strip():
        raise BrainError(f"{label}.predicate must be a non-empty string")
    if not isinstance(value["args_template"], Mapping):
        raise BrainError(f"{label}.args_template must be an object")
    expected = value["expect_exit"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise BrainError(f"{label}.expect_exit must be an integer")


def _validate_procedure(
    procedure: Any, cache_policy: str, cache_inputs: Any
) -> list[dict[str, Any]]:
    if not isinstance(procedure, list) or not procedure:
        raise BrainError("workflow procedure must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    for index, raw_step in enumerate(procedure):
        if not isinstance(raw_step, Mapping):
            raise BrainError(f"workflow step {index} must be an object")
        allowed = {
            "tool",
            "args_template",
            "effect",
            "expected_exit",
            "precondition",
            "postcondition",
        }
        if set(raw_step) - allowed:
            raise BrainError(f"workflow step {index} has unsupported fields")
        tool = raw_step.get("tool")
        args_template = raw_step.get("args_template", {})
        if not isinstance(tool, str) or not tool.strip():
            raise BrainError(f"workflow step {index}.tool must be a non-empty string")
        if not isinstance(args_template, Mapping):
            raise BrainError(f"workflow step {index}.args_template must be an object")
        expected_exit = raw_step.get("expected_exit", 0)
        if isinstance(expected_exit, bool) or not isinstance(expected_exit, int):
            raise BrainError(f"workflow step {index}.expected_exit must be an integer")
        for phase in ("precondition", "postcondition"):
            condition = raw_step.get(phase)
            if condition is not None:
                _validate_condition(condition, f"workflow step {index}.{phase}")
        effect = raw_step.get("effect")
        if effect is not None and effect not in _STEP_EFFECTS:
            raise BrainError(f"workflow step {index}.effect is invalid")
        if cache_policy == "read_only" and effect != "read":
            raise BrainError("read_only workflow steps must declare effect='read'")
        normalized.append({str(key): value for key, value in raw_step.items()})
    if cache_policy == "read_only" and (
        not isinstance(cache_inputs, list)
        or not cache_inputs
        or any(not isinstance(key, str) or not key for key in cache_inputs)
        or len(set(cache_inputs)) != len(cache_inputs)
    ):
        raise BrainError("read_only workflows require distinct cache_inputs")
    return normalized


def _load_workflow(home: Path, engram_id: str, version: int) -> dict[str, Any]:
    target = _workflow_path(home, engram_id, version, allow_missing=False)
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrainError(f"Invalid workflow engram {engram_id} v{version}") from exc
    if not isinstance(record, dict):
        raise BrainError("Workflow engram must be a JSON object")
    if record.get("engram_id") != engram_id or record.get("version") != version:
        raise BrainError("Workflow engram identity does not match requested version")
    digest = record.pop("content_sha256", None)
    expected = hashlib.sha256(contracts.canonical_json(record).encode("utf-8")).hexdigest()
    record["content_sha256"] = digest
    if digest != expected:
        raise BrainError("Workflow engram content digest mismatch")
    record["procedure"] = _validate_procedure(
        record.get("procedure"), record.get("cache_policy", "none"), record.get("cache_inputs")
    )
    return record


def detect_workflow_engrams(
    session_events: Sequence[Sequence[Mapping[str, Any]]],
    min_support: int = 2,
    min_len: int = 3,
    max_len: int = 5,
) -> list[dict[str, Any]]:
    """Detect repeated successful tool-call sequences with source provenance.

    A tool call is eligible only when its event includes an observed
    ``result.exit_code == 0``. Detection never invents predicates, versions,
    harnesses, or model compatibility.
    """
    if not isinstance(session_events, Sequence):
        raise BrainError("session_events must be a sequence of session event lists")
    if (
        isinstance(min_support, bool)
        or not isinstance(min_support, int)
        or min_support < 1
        or isinstance(min_len, bool)
        or not isinstance(min_len, int)
        or min_len < 1
        or isinstance(max_len, bool)
        or not isinstance(max_len, int)
        or max_len < min_len
    ):
        raise BrainError("invalid workflow detection bounds")

    tool_sequences: list[dict[str, Any]] = []
    for session_index, sess in enumerate(session_events):
        if not isinstance(sess, Sequence):
            raise BrainError(f"session {session_index} must be a sequence")
        curr: list[dict[str, Any]] = []
        session_id = f"session-{session_index}"
        for event_index, ev in enumerate(sess):
            if not isinstance(ev, Mapping):
                raise BrainError(f"session {session_index} event {event_index} must be an object")
            if ev.get("session") or ev.get("session_id"):
                session_id = str(ev.get("session") or ev.get("session_id"))
            kind = ev.get("kind") or ev.get("event_type")
            if str(kind).lower() not in ("tool_call", "tool_use"):
                continue
            tool = ev.get("tool") or ev.get("tool_name") or ev.get("name")
            result = ev.get("result") or ev.get("tool_result") or ev.get("output")
            if (
                not isinstance(tool, str)
                or not tool.strip()
                or not isinstance(result, Mapping)
                or result.get("exit_code") != 0
            ):
                continue
            args = ev.get("input") or ev.get("args") or ev.get("args_template") or {}
            if not isinstance(args, Mapping):
                continue
            curr.append(
                {
                    "tool": tool,
                    "args_template": dict(args),
                    "source_ref": {"session_id": session_id, "event_index": event_index},
                }
            )
        if curr:
            tool_sequences.append({"items": curr, "session_id": session_id})

    support: dict[tuple[str, ...], int] = {}
    templates_by_subseq: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    sources_by_subseq: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for sequence in tool_sequences:
        seq = sequence["items"]
        seen: set[tuple[str, ...]] = set()
        tools_only = [item["tool"] for item in seq]
        for start in range(len(tools_only)):
            for length in range(min_len, min(max_len, len(tools_only) - start) + 1):
                window = tuple(tools_only[start : start + length])
                if window in seen:
                    continue
                seen.add(window)
                support[window] = support.get(window, 0) + 1
                templates_by_subseq.setdefault(window, seq[start : start + length])
                sources_by_subseq.setdefault(window, []).append(
                    {
                        "session_id": sequence["session_id"],
                        "steps": [item["source_ref"] for item in seq[start : start + length]],
                    }
                )

    results: list[dict[str, Any]] = []
    for window, count in support.items():
        if count < min_support:
            continue
        procedure = [
            {"tool": item["tool"], "args_template": item["args_template"]}
            for item in templates_by_subseq[window]
        ]
        results.append(
            {
                "engram_id": "engram-"
                + hashlib.sha256("->".join(window).encode("utf-8")).hexdigest()[:16],
                "sequence": list(window),
                "support": count,
                "procedure": procedure,
                "provenance": sources_by_subseq[window],
            }
        )
    results.sort(key=lambda r: (-r["support"], -len(r["sequence"]), r["sequence"]))
    return results


def register_workflow_engram(home: Path | str, engram_data: Mapping[str, Any]) -> dict[str, Any]:
    """Store one immutable, versioned deterministic workflow engram."""
    if not isinstance(engram_data, Mapping):
        raise BrainError("engram_data must be an object")
    home_p = Path(home)
    raw_id = engram_data.get("engram_id")
    if raw_id is None:
        raw_id = (
            "engram-"
            + hashlib.sha256(
                contracts.canonical_json(dict(engram_data)).encode("utf-8")
            ).hexdigest()[:16]
        )
    engram_id = validate_engram_name(raw_id)
    raw_version = engram_data.get("version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version <= 0:
        raise BrainError("workflow version must be a positive integer")
    cache_policy = engram_data.get("cache_policy", "none")
    if cache_policy not in _CACHE_POLICIES:
        raise BrainError("cache_policy must be 'none' or 'read_only'")
    cache_inputs = engram_data.get("cache_inputs")
    procedure = _validate_procedure(engram_data.get("procedure"), cache_policy, cache_inputs)
    status = engram_data.get("status", "candidate")
    if not isinstance(status, str) or not status.strip():
        raise BrainError("workflow status must be a non-empty string")
    allowed = {
        "engram_id",
        "version",
        "procedure",
        "cache_policy",
        "cache_inputs",
        "provenance",
        "valid_for",
        "status",
    }
    if set(engram_data) - allowed:
        raise BrainError("workflow engram contains unsupported fields")
    record: dict[str, Any] = {
        "engram_id": engram_id,
        "version": raw_version,
        "procedure": procedure,
        "cache_policy": cache_policy,
        "status": status,
        "created_at": _utcnow(),
    }
    if cache_policy == "read_only":
        if not isinstance(cache_inputs, list):
            raise BrainError("read_only workflows require distinct cache_inputs")
        record["cache_inputs"] = list(cache_inputs)
    for key in ("provenance", "valid_for"):
        if key in engram_data:
            if not isinstance(engram_data[key], (Mapping, list)):
                raise BrainError(f"workflow {key} must be an object or list")
            record[key] = engram_data[key]
    try:
        contracts.canonical_json(record)
    except (TypeError, ValueError) as exc:
        raise BrainError("workflow engram metadata must be JSON-safe") from exc
    record["content_sha256"] = hashlib.sha256(
        contracts.canonical_json(record).encode("utf-8")
    ).hexdigest()
    target = _workflow_path(home_p, engram_id, raw_version, allow_missing=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = None
            handle.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    except FileExistsError as exc:
        raise BrainError(
            f"Workflow engram version already exists: {engram_id} v{raw_version}"
        ) from exc
    except OSError as exc:
        raise BrainError(f"Could not write workflow engram {target}") from exc
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
    return record


def _input_hashes(home: Path, params: Mapping[str, Any], keys: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for key in keys:
        value = params.get(key)
        if not isinstance(value, str) or not value:
            raise BrainError(f"cache input parameter {key!r} must be a non-empty path")
        try:
            path = resolve_under(home, value, allow_missing=False)
        except (OSError, ValueError) as exc:
            raise BrainError(f"Unsafe cache input {value!r}: {exc}") from exc
        if not path.is_file():
            raise BrainError(f"cache input is not a regular file: {value!r}")
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _failure_result(
    engram_id: str,
    version: int,
    *,
    step: int,
    phase: str,
    reason: str,
    steps: list[dict[str, Any]],
    cache_hit: bool = False,
) -> dict[str, Any]:
    return {
        "engram_id": engram_id,
        "version": version,
        "success": False,
        "failed_step": step,
        "failed_phase": phase,
        "reason": reason,
        "model_calls": 0,
        "cache_hit": cache_hit,
        "steps_executed": 0 if cache_hit else len(steps),
        "steps": steps,
    }


def _run_condition(
    condition: Mapping[str, Any],
    params: Mapping[str, Any],
    predicate_runner: Callable[[str, Mapping[str, Any]], Any] | None,
    *,
    phase: str,
) -> bool:
    if predicate_runner is None:
        raise BrainError(f"{phase} requires a predicate_runner")
    predicate = condition["predicate"]
    args = _resolve_template(condition["args_template"], params)
    if not isinstance(args, Mapping):
        raise BrainError(f"{phase} resolved arguments must be an object")
    try:
        raw = predicate_runner(predicate, args)
    except Exception as exc:
        raise BrainError(f"{phase} executor failed: {exc}") from exc
    result = _runner_result(
        raw,
        expected_tool=predicate,
        phase=phase,
        require_read_only=True,
    )
    return result["exit_code"] == condition["expect_exit"]


def _run_preconditions(
    procedure: list[dict[str, Any]],
    params: Mapping[str, Any],
    predicate_runner: Callable[[str, Mapping[str, Any]], Any] | None,
) -> int | None:
    for step_index, step in enumerate(procedure):
        condition = step.get("precondition")
        if isinstance(condition, Mapping) and not _run_condition(
            condition, params, predicate_runner, phase=f"step {step_index} precondition"
        ):
            return step_index
    return None


def _execute_steps(
    procedure: list[dict[str, Any]],
    params: Mapping[str, Any],
    tool_runner: Callable[[str, Mapping[str, Any]], Any],
    predicate_runner: Callable[[str, Mapping[str, Any]], Any] | None,
    *,
    read_only: bool,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for step_index, step in enumerate(procedure):
        condition = step.get("precondition")
        if isinstance(condition, Mapping) and not _run_condition(
            condition, params, predicate_runner, phase=f"step {step_index} precondition"
        ):
            raise _WorkflowFailure(
                step=step_index,
                phase="precondition",
                reason="precondition_failed",
                steps=steps,
            )
        tool = step["tool"]
        args = _resolve_template(step.get("args_template", {}), params)
        if not isinstance(args, Mapping):
            raise BrainError(f"step {step_index} resolved arguments must be an object")
        try:
            raw = tool_runner(tool, args)
        except Exception as exc:
            raise _WorkflowFailure(
                step=step_index, phase="tool", reason=f"tool_executor_failed: {exc}", steps=steps
            ) from exc
        output = _runner_result(
            raw,
            expected_tool=tool,
            phase=f"step {step_index} tool",
            require_read_only=read_only,
        )
        entry = {"step": step_index, "tool": tool, "args": dict(args), "output": output}
        steps.append(entry)
        expected_exit = step.get("expected_exit", 0)
        if output["exit_code"] != expected_exit:
            raise _WorkflowFailure(
                step=step_index,
                phase="tool",
                reason="tool_failed",
                steps=steps,
            )
        condition = step.get("postcondition")
        if isinstance(condition, Mapping) and not _run_condition(
            condition, params, predicate_runner, phase=f"step {step_index} postcondition"
        ):
            raise _WorkflowFailure(
                step=step_index,
                phase="postcondition",
                reason="postcondition_failed",
                steps=steps,
            )
    return steps


def _run_cached_postconditions(
    procedure: list[dict[str, Any]],
    params: Mapping[str, Any],
    predicate_runner: Callable[[str, Mapping[str, Any]], Any] | None,
) -> int | None:
    for step_index, step in enumerate(procedure):
        condition = step.get("postcondition")
        if isinstance(condition, Mapping) and not _run_condition(
            condition, params, predicate_runner, phase=f"step {step_index} postcondition"
        ):
            return step_index
    return None


def run_deterministic(
    home: Path | str,
    engram_id: str,
    params: Mapping[str, Any],
    *,
    version: int = 1,
    tool_runner: Callable[[str, Mapping[str, Any]], Any] | None = None,
    predicate_runner: Callable[[str, Mapping[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Execute an immutable workflow through an explicit local executor boundary."""
    if tool_runner is None:
        raise BrainError("run_deterministic requires an approved tool_runner")
    if not isinstance(params, Mapping):
        raise BrainError("workflow params must be an object")
    try:
        contracts.canonical_json(dict(params))
    except (TypeError, ValueError) as exc:
        raise BrainError("workflow params must be JSON-safe") from exc
    home_p = Path(home)
    record = _load_workflow(home_p, engram_id, version)
    procedure = record["procedure"]
    cache_policy = record.get("cache_policy", "none")
    if (
        any(
            isinstance(step.get("precondition"), Mapping)
            or isinstance(step.get("postcondition"), Mapping)
            for step in procedure
        )
        and predicate_runner is None
    ):
        raise BrainError("workflow predicates require an approved predicate_runner")

    def successful_result(steps: list[dict[str, Any]], cache_hit: bool) -> dict[str, Any]:
        return {
            "engram_id": engram_id,
            "version": version,
            "success": True,
            "model_calls": 0,
            "cache_hit": cache_hit,
            "steps_executed": len(steps),
            "steps": steps,
        }

    def execute_once() -> str:
        try:
            steps = _execute_steps(
                procedure,
                params,
                tool_runner,
                predicate_runner,
                read_only=cache_policy == "read_only",
            )
        except _WorkflowFailure as failure:
            raise failure
        return json.dumps(successful_result(steps, False), ensure_ascii=False)

    if cache_policy != "read_only":
        try:
            return json.loads(execute_once())
        except _WorkflowFailure as failure:
            return _failure_result(
                engram_id,
                version,
                step=failure.step,
                phase=failure.phase,
                reason=failure.reason,
                steps=failure.steps,
            )

    from .action_cache import (
        ActionCacheStore,
        ActionProof,
        ActionType,
        DependencyClass,
        compute_action_key,
    )

    input_hashes = _input_hashes(home_p, params, record["cache_inputs"])
    proof = ActionProof(
        input_hashes=input_hashes,
        verification_predicate="deterministic_read",
        dependency_class=DependencyClass.FILE_SET,
    )
    target = f"engram:{engram_id}:v{version}"
    cache_key = compute_action_key(
        ActionType.FILE_READ,
        target,
        params=dict(params),
        input_hashes=input_hashes,
        verification_predicate=proof.verification_predicate,
        dependency_class=proof.dependency_class,
    )
    try:
        with ActionCacheStore(home_p) as cache:
            content, cache_hit, _ = cache.get_or_execute(
                ActionType.FILE_READ,
                target,
                execute_once,
                params=dict(params),
                proof=proof,
            )
            result = json.loads(content)
            if not isinstance(result, dict):
                raise BrainError("cached workflow result must be an object")
            if cache_hit:
                phase = "precondition"
                failed = _run_preconditions(procedure, params, predicate_runner)
                if failed is None:
                    phase = "postcondition"
                    failed = _run_cached_postconditions(procedure, params, predicate_runner)
                if failed is not None:
                    cache.invalidate_by_key(cache_key)
                    return _failure_result(
                        engram_id,
                        version,
                        step=failed,
                        phase=phase,
                        reason=f"{phase}_failed",
                        steps=result.get("steps", []),
                        cache_hit=True,
                    )
            result["cache_hit"] = cache_hit
            if cache_hit:
                result["steps_executed"] = 0
            return result
    except _WorkflowFailure as failure:
        return _failure_result(
            engram_id,
            version,
            step=failure.step,
            phase=failure.phase,
            reason=failure.reason,
            steps=failure.steps,
        )
