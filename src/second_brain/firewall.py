"""
Observation Firewall: keep giant tool output out of model context.

Plan §5: Phase 2 — Observation Firewall.
Implements deterministic reducers in Brain core for common high-volume outputs
(test runners, compiler/type checkers, git, search/grep, JSON, process logs,
build/package managers, and doctor verification).

All reducers are pure and deterministic. Raw bulky output is stored verbatim
in the content-addressed artifact store and given a lossless recovery handle.
Safety invariants (§5.5): never drop failures, error locations, exit codes,
or failing test names.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import artifacts

MAX_DISTILL_CHARS = 4000
MAX_SECTIONS = 15

# Common failure and location regex patterns
_PYTEST_PASSED_RE = re.compile(r"(\d+)\s+passed\b")
_PYTEST_FAILED_RE = re.compile(r"(\d+)\s+failed\b")
_PYTEST_ERROR_RE = re.compile(r"(\d+)\s+errors?\b")
_PYTEST_SKIPPED_RE = re.compile(r"(\d+)\s+skipped\b")

_PYRIGHT_ERROR_RE = re.compile(r"(\d+)\s+errors?,\s*(\d+)\s+warnings?,\s*(\d+)\s+informations?")
_FILE_LINE_RE = re.compile(r"([a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+):(\d+)(?::(\d+))?")
_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE)
_GIT_STAT_RE = re.compile(
    r"(\d+)\s+files?\s+changed(?:,\s*(\d+)\s+insertions?\(\+\))?(?:,\s*(\d+)\s+deletions?\(-\))?"
)


@dataclass
class ReducerResult:
    """
    Standard return packet for all Observation Firewall reducers (§5.1).
    """
    summary: str
    high_value_sections: list[str] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    raw_object_ref: str = ""
    reduction_ratio: float = 0.0
    lossless_retrieval_handle: str = ""
    distilled_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "high_value_sections": self.high_value_sections,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "raw_object_ref": self.raw_object_ref,
            "reduction_ratio": round(self.reduction_ratio, 4),
            "lossless_retrieval_handle": self.lossless_retrieval_handle,
            "distilled_text": self.distilled_text,
        }


# ---------------------------------------------------------------------------
# Specialized Deterministic Reducers (§5.1)
# ---------------------------------------------------------------------------


def reduce_pytest(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for pytest and test runner outputs.

    Extracts: counts (passed, failed, errors, skipped), failure blocks, tracebacks.
    """
    lines = text.splitlines()
    passed = 0
    failed = 0
    errors = 0
    skipped = 0

    for match in _PYTEST_PASSED_RE.finditer(text):
        passed = int(match.group(1))
    for match in _PYTEST_FAILED_RE.finditer(text):
        failed = int(match.group(1))
    for match in _PYTEST_ERROR_RE.finditer(text):
        errors = int(match.group(1))
    for match in _PYTEST_SKIPPED_RE.finditer(text):
        skipped = int(match.group(1))

    error_count = failed + errors
    high_value: list[str] = []

    # Extract failed test header lines and failure summaries
    in_failures = False
    current_failure: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            high_value.append(stripped)
        elif stripped.startswith("=== FAILURES ===") or stripped.startswith("=== ERRORS ==="):
            in_failures = True
        elif stripped.startswith("=== short test summary info ==="):
            in_failures = False

        if in_failures and stripped:
            if stripped.startswith("___") and stripped.endswith("___"):
                if current_failure:
                    high_value.append("\n".join(current_failure[:8]))
                    current_failure = []
                current_failure.append(stripped)
            elif current_failure and len(current_failure) < 10:
                current_failure.append(stripped)

    if current_failure:
        high_value.append("\n".join(current_failure[:8]))

    # Deduplicate and cap high-value sections
    seen = set()
    deduped_sections = []
    for sec in high_value:
        if sec not in seen:
            seen.add(sec)
            deduped_sections.append(sec)
        if len(deduped_sections) >= MAX_SECTIONS:
            break

    summary = f"pytest: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped"
    return summary, deduped_sections, error_count, 0


def reduce_compiler(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for compiler and type-checker outputs.
    (pyright, mypy, tsc, rustc, gcc, clang, ruff).
    """
    lines = text.splitlines()
    error_lines: list[str] = []
    warning_lines: list[str] = []
    errors = 0
    warnings = 0

    # Pyright summary pattern
    pyright_match = None
    for match in _PYRIGHT_ERROR_RE.finditer(text):
        pyright_match = match
    if pyright_match:
        errors = int(pyright_match.group(1))
        warnings = int(pyright_match.group(2))

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if "error" in lower and not lower.startswith("0 errors"):
            if not pyright_match and (
                "error:" in lower or "error [" in lower or " error " in lower
            ):
                errors += 1
            if len(error_lines) < MAX_SECTIONS:
                error_lines.append(stripped)
        elif "warning" in lower and not lower.startswith("0 warnings"):
            if not pyright_match and ("warning:" in lower or " warning " in lower):
                warnings += 1
            if len(warning_lines) < 5:
                warning_lines.append(stripped)

    high_value = error_lines + warning_lines
    summary = f"compiler/typecheck: {errors} errors, {warnings} warnings"
    return summary, high_value[:MAX_SECTIONS], errors, warnings


def reduce_git(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for git output (diff, status, log).
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "git: empty output", [], 0, 0

    high_value: list[str] = []
    first = lines[0].lower()

    # Git diff
    diff_files = [
        line for line in lines if line.startswith("diff --git") or line.startswith("+++ ")
    ]
    stat_match = None
    for line in lines:
        m = _GIT_STAT_RE.search(line)
        if m:
            stat_match = m

    if diff_files or stat_match or first.startswith("diff "):
        changed = len(diff_files)
        stat_desc = stat_match.group(0) if stat_match else f"{changed} files changed"
        summary = f"git diff: {stat_desc}"
        high_value = diff_files[:MAX_SECTIONS]
        return summary, high_value, 0, 0

    # Git status
    lower_text = text.lower()
    if (
        "on branch" in first
        or "changes to be committed" in lower_text
        or "untracked files" in lower_text
    ):
        status_items = [
            line for line in lines
            if line.startswith("modified:")
            or line.startswith("new file:")
            or line.startswith("deleted:")
            or line.startswith("both modified:")
            or "\t" in line
        ]
        summary = f"git status: {len(status_items)} changed entries"
        high_value = status_items[:MAX_SECTIONS]
        return summary, high_value, 0, 0

    # Git log
    summary = f"git log: {len(lines)} entries"
    high_value = lines[:MAX_SECTIONS]
    return summary, high_value, 0, 0


def reduce_search(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for grep, ripgrep, find, and code search outputs.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    count = len(lines)
    if count == 0:
        return "search: 0 matches", [], 0, 0

    matched_files = set()
    for line in lines:
        m = _FILE_LINE_RE.match(line)
        if m:
            matched_files.add(m.group(1))

    file_count = len(matched_files)
    file_info = f" across {file_count} files" if file_count > 0 else ""
    summary = f"search: {count} matches{file_info}"
    high_value = lines[:MAX_SECTIONS]
    return summary, high_value, 0, 0


def reduce_json(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for large JSON payloads.
    """
    high_value: list[str] = []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            summary = f"json: list with {len(data)} items"
            if data:
                first_elem = data[0]
                if isinstance(first_elem, dict):
                    keys = list(first_elem.keys())[:10]
                    high_value.append(f"item[0] keys: {keys}")
                high_value.append(f"sample: {json.dumps(first_elem, ensure_ascii=False)[:300]}")
        elif isinstance(data, dict):
            keys = list(data.keys())
            summary = f"json: object with {len(keys)} top-level keys ({', '.join(keys[:8])})"
            for k in keys[:MAX_SECTIONS]:
                v = data[k]
                v_repr = f"len={len(v)}" if isinstance(v, (list, dict)) else str(v)[:60]
                high_value.append(f"{k}: {v_repr}")
        else:
            summary = f"json: scalar value ({type(data).__name__})"
            high_value.append(str(data)[:200])
        return summary, high_value, 0, 0
    except (json.JSONDecodeError, ValueError) as exc:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return f"json: invalid JSON ({exc})", lines[:5], 1, 0


def reduce_process_logs(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for process logs and stack traces.
    Preserves exact exceptions, tracebacks, and error lines.
    """
    lines = text.splitlines()
    high_value: list[str] = []
    errors = 0
    warnings = 0

    in_traceback = False
    current_tb: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if _TRACEBACK_RE.search(line):
            in_traceback = True
            current_tb = [stripped]
            errors += 1
            continue

        if in_traceback:
            current_tb.append(stripped)
            # End of Python traceback is typically the exception line (e.g. ValueError: ...)
            is_tb_end = (
                not stripped.startswith("File ")
                and not stripped.startswith("line ")
                and ":" in stripped
            )
            if is_tb_end and len(current_tb) > 1:
                high_value.append("\n".join(current_tb[:12]))
                current_tb = []
                in_traceback = False
            continue

        lower = stripped.lower()
        if "error" in lower or "fatal" in lower or "critical" in lower or "exception" in lower:
            errors += 1
            if len(high_value) < MAX_SECTIONS:
                high_value.append(stripped)
        elif "warn" in lower:
            warnings += 1
            if len(high_value) < MAX_SECTIONS and len(high_value) < 5:
                high_value.append(stripped)

    if current_tb:
        high_value.append("\n".join(current_tb[:12]))

    summary = f"process log: {len(lines)} lines, {errors} errors, {warnings} warnings"
    return summary, high_value[:MAX_SECTIONS], errors, warnings


def reduce_build_output(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for build and package manager output (pip, npm, cargo).
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    errors = 0
    warnings = 0
    high_value: list[str] = []

    for line in lines:
        lower = line.lower()
        if "error" in lower or "failed" in lower or "npm err!" in lower:
            errors += 1
            if len(high_value) < MAX_SECTIONS:
                high_value.append(line)
        elif "warn" in lower:
            warnings += 1
            if len(high_value) < MAX_SECTIONS and len(high_value) < 5:
                high_value.append(line)
        elif "successfully installed" in lower or "built in" in lower:
            high_value.append(line)

    summary = f"build output: {len(lines)} lines, {errors} errors, {warnings} warnings"
    return summary, high_value[:MAX_SECTIONS], errors, warnings


def reduce_doctor(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic reducer for Brain doctor and health check outputs.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    errors = 0
    warnings = 0
    passes = 0
    high_value: list[str] = []

    for line in lines:
        lower = line.lower()
        if "failed" in lower or "[fail]" in lower or "error" in lower:
            errors += 1
            high_value.append(line)
        elif "warning" in lower or "[warn]" in lower:
            warnings += 1
            high_value.append(line)
        elif "ok" in lower or "[pass]" in lower or "pass" in lower:
            passes += 1

    summary = f"doctor: {passes} passed, {errors} failed, {warnings} warnings"
    return summary, high_value[:MAX_SECTIONS], errors, warnings


def reduce_generic(text: str) -> tuple[str, list[str], int, int]:
    """
    Deterministic fallback generic reducer: line/byte counts + head/tail.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    head = lines[:5]
    tail = lines[-5:] if len(lines) > 5 else []
    omitted = f"... ({len(lines) - 10} lines omitted) ..."
    high_value = head + ([omitted] if len(lines) > 10 else []) + tail
    summary = f"generic output: {len(lines)} lines, {len(text.encode('utf-8'))} bytes"
    return summary, high_value, 0, 0


# ---------------------------------------------------------------------------
# Reducer Registry & Auto-Detection (§5.1)
# ---------------------------------------------------------------------------

REDUCER_MAP: dict[str, Callable[[str], tuple[str, list[str], int, int]]] = {
    "pytest": reduce_pytest,
    "compiler": reduce_compiler,
    "git": reduce_git,
    "search": reduce_search,
    "json": reduce_json,
    "logs": reduce_process_logs,
    "build": reduce_build_output,
    "doctor": reduce_doctor,
    "generic": reduce_generic,
}


def register_reducer(
    kind: str,
    reducer_fn: Callable[[str], tuple[str, list[str], int, int]],
) -> None:
    """Register a custom deterministic reducer."""
    REDUCER_MAP[kind.lower()] = reducer_fn


def detect_kind(text: str, command: str = "", tool: str = "") -> str:
    """
    Auto-detect the most specific reducer kind from command, tool, or output heuristics.
    """
    cmd = command.strip().lower()
    t = tool.strip().lower()

    if cmd:
        first_token = cmd.split()[0]
        if first_token in ("pytest", "py.test", "vitest", "jest"):
            return "pytest"
        if first_token in ("pyright", "mypy", "tsc", "gcc", "clang", "rustc", "ruff"):
            return "compiler"
        if first_token == "git":
            return "git"
        if first_token in ("rg", "grep", "find", "ast-grep"):
            return "search"
        if first_token in ("pip", "npm", "cargo", "yarn", "uv", "pnpm", "make"):
            return "build"
        if "doctor" in cmd:
            return "doctor"

    if t in ("pytest", "test"):
        return "pytest"
    if t in ("git",):
        return "git"
    if t in ("rg", "grep", "search"):
        return "search"

    # Text-based heuristics
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "json"
        except Exception:
            pass

    if _TRACEBACK_RE.search(text) or "Traceback (most recent call last):" in text:
        return "logs"

    if (
        _PYTEST_PASSED_RE.search(text)
        or _PYTEST_FAILED_RE.search(text)
        or "=== FAILURES ===" in text
    ):
        return "pytest"

    if _PYRIGHT_ERROR_RE.search(text) or "error TS" in text or "error[E" in text:
        return "compiler"

    if text.startswith("diff --git") or "On branch " in text:
        return "git"

    return "generic"


# ---------------------------------------------------------------------------
# Main Observation Firewall Entrypoint (§5.1, §5.2, §5.5)
# ---------------------------------------------------------------------------


def reduce_observation(
    text: str,
    kind: str | None = None,
    command: str = "",
    tool: str = "",
    session: str | None = None,
    home: Path | None = None,
    max_chars: int = MAX_DISTILL_CHARS,
) -> ReducerResult:
    """
    Observation Firewall entrypoint:
    1. Detect or use specified kind.
    2. Deterministically distill text into summary and high-value sections.
    3. Store full raw content in content-addressed artifact store (if home provided).
    4. Return structured ReducerResult with lossless retrieval handle.
    5. Fails open on unexpected error.
    """
    raw_bytes = text.encode("utf-8")
    raw_size = len(raw_bytes)
    sha = hashlib.sha256(raw_bytes).hexdigest()
    handle = artifacts.make_handle(sha)

    # Store in backing store if brain home is available
    raw_ref = sha
    if home is not None:
        try:
            stored = artifacts.store_text(
                home, text, kind=kind or "generic", tool=tool, session=session
            )
            raw_ref = stored["hash"]
            handle = stored["handle"]
            artifacts.add_ref(
                home, stored["hash"], owner=f"firewall:{session}" if session else "firewall:none"
            )
        except Exception:
            # Backing store error must not crash execution (fail-open)
            pass

    try:
        resolved_kind = kind if (kind and kind in REDUCER_MAP) else detect_kind(text, command, tool)
        reducer_fn = REDUCER_MAP.get(resolved_kind, reduce_generic)
        summary, high_value, error_count, warning_count = reducer_fn(text)

        # Build distilled representation
        sections_block = "\n".join(f"  {sec}" for sec in high_value) if high_value else "  (none)"
        distilled = (
            f"[SECOND_BRAIN_FIREWALL:kind={resolved_kind}]\n"
            f"Summary: {summary}\n"
            f"Key Sections:\n{sections_block}\n"
            f"Raw Artifact: {handle} ({raw_size} bytes)\n"
            f"{artifacts.recover_hint(sha)}"
        )
        if len(distilled) > max_chars:
            hint_suffix = f"\n... [truncated to {max_chars} chars, see {handle}]"
            distilled = distilled[:max_chars] + hint_suffix

        distilled_size = len(distilled.encode("utf-8"))
        reduction_ratio = max(0.0, 1.0 - (distilled_size / max(raw_size, 1)))

        return ReducerResult(
            summary=summary,
            high_value_sections=high_value,
            error_count=error_count,
            warning_count=warning_count,
            raw_object_ref=raw_ref,
            reduction_ratio=reduction_ratio,
            lossless_retrieval_handle=handle,
            distilled_text=distilled,
        )
    except Exception as exc:
        # Safety / fail-open fallback: return minimal summary without losing raw ref
        fallback_summary = f"reducer error ({exc}): fallback generic"
        fallback_distilled = f"{text[:max_chars]}\n[Raw Artifact: {handle}]"
        return ReducerResult(
            summary=fallback_summary,
            high_value_sections=[],
            error_count=1,
            warning_count=0,
            raw_object_ref=raw_ref,
            reduction_ratio=0.0,
            lossless_retrieval_handle=handle,
            distilled_text=fallback_distilled,
        )


def expand_observation(home: Path, ref_or_handle: str) -> str:
    """
    Losslessly expand a reduced observation by hash, prefix, or [brain-artifact:sha256:hash] handle.
    """
    # Extract hash from handle if present
    target = ref_or_handle.strip()
    if target.startswith("[brain-artifact:sha256:") and target.endswith("]"):
        target = target[len("[brain-artifact:sha256:"):-1]
    elif target.startswith("/brain-expand "):
        target = target[len("/brain-expand "):].strip()

    raw_bytes = artifacts.expand(home, target)
    return raw_bytes.decode("utf-8", errors="replace")
