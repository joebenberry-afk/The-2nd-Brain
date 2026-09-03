"""T2.4 Injection placement slots: stable PREFIX and per-turn TAIL.

Two slots only:
1. PREFIX (session-constant):
   (1) Lean kernel (from lean_runtime / lean-code)
   (2) Skill descriptors (from visibility plan / skills.descriptors)
   (3) The two T1.6 commands
   (4) Project identity line: Project: <project_id>
   Rendered once at session start and never changed across turns.
   sha256(PREFIX) stored at session start; comparing later turns detects drift
   and logs prefix_drift=1.

2. TAIL (per-turn):
   [BRAIN_CONTEXT_DELTA], hot-context refs (VMem), freshness lines, Skill hydration bodies.
   Appended after the latest user message in the turn context.
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts, lean_runtime, skills

MEMORY_COMMANDS_TEXT = (
    'To remember: run `brainctl remember "<claim>" --evidence <path>`.\n'
    'To check: `brainctl recall "<question>"`.'
)

# Process-scoped cache of session -> sha256(PREFIX)
_SESSION_PREFIX_HASHES: dict[str, str] = {}


def format_skill_descriptors(descriptors_data: Any) -> str:
    """Render skill descriptors sorted by skill_id into bounded text."""
    if not descriptors_data:
        return ""
    if isinstance(descriptors_data, str):
        return descriptors_data.strip()
    if isinstance(descriptors_data, dict):
        parts: list[str] = []
        for skill_id in sorted(descriptors_data.keys()):
            val = descriptors_data[skill_id]
            if isinstance(val, dict):
                text = str(val.get("descriptor_text") or "").strip()
            else:
                text = str(val).strip()
            if text:
                parts.append(text)
        return "\n\n".join(parts)
    if isinstance(descriptors_data, (list, tuple)):
        parts = [str(x).strip() for x in descriptors_data if str(x).strip()]
        return "\n\n".join(parts)
    return ""


def format_hydrated_skills(hydrated_data: Any) -> str:
    """Render hydrated skill instructions sorted by skill_id."""
    if not hydrated_data:
        return ""
    if isinstance(hydrated_data, str):
        return hydrated_data.strip()
    if isinstance(hydrated_data, dict):
        parts: list[str] = []
        for skill_id in sorted(hydrated_data.keys()):
            val = str(hydrated_data[skill_id]).strip()
            if val:
                parts.append(val)
        return "\n\n".join(parts)
    if isinstance(hydrated_data, (list, tuple)):
        parts = [str(x).strip() for x in hydrated_data if str(x).strip()]
        return "\n\n".join(parts)
    return ""


def assemble_prefix(
    *,
    project_id: str,
    home: Path | None = None,
    role: str = "driver",
    lean_kernel: str | None = None,
    skill_descriptors: Any = None,
    task: str = "",
) -> str:
    """Assemble the session-constant PREFIX slot in exact specification order:

    (1) Lean kernel (from lean_runtime / lean-code)
    (2) Skill descriptors (from visibility plan)
    (3) The two T1.6 commands
    (4) Project identity line: Project: <project_id>
    """
    parts: list[str] = []

    # (1) Lean kernel
    kernel_text: str | None = None
    if lean_kernel is not None:
        kernel_text = lean_kernel.strip()
    elif home is not None:
        with contextlib.suppress(Exception):
            outcome = lean_runtime.decide_lean_runtime(home, role, task or "prefix")
            if outcome.decision == "inject" and outcome.kernel:
                kernel_text = lean_runtime.compose_lean_kernel_block(outcome.kernel)
    if kernel_text:
        parts.append(kernel_text)

    # (2) Skill descriptors
    desc_text: str = ""
    if skill_descriptors is not None:
        desc_text = format_skill_descriptors(skill_descriptors)
    elif home is not None:
        with contextlib.suppress(Exception):
            desc_map = skills.descriptors(home)
            desc_text = format_skill_descriptors(desc_map)
    if desc_text:
        parts.append(desc_text)

    # (3) The two T1.6 commands
    parts.append(MEMORY_COMMANDS_TEXT)

    # (4) Project identity line
    clean_proj = str(project_id or "default").strip()
    parts.append(f"Project: {clean_proj}")

    return "\n\n".join(parts)


def record_and_check_prefix_drift(
    home: Path | None,
    session_id: str,
    prefix: str,
) -> bool:
    """Compute sha256(PREFIX), compare with stored hash for session.

    Returns True if drift detected (prefix_drift=1), False if stable.
    Logs telemetry if home is available and drift occurred.
    """
    prefix_sha = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    stored_sha = _SESSION_PREFIX_HASHES.get(session_id)

    if stored_sha is None:
        _SESSION_PREFIX_HASHES[session_id] = prefix_sha
        return False

    if stored_sha != prefix_sha:
        # Emit telemetry
        if home is not None:
            _emit_drift_telemetry(home, session_id, stored_sha, prefix_sha)
        return True

    return False


def _emit_drift_telemetry(
    home: Path,
    session_id: str,
    expected_sha: str,
    actual_sha: str,
) -> None:
    with contextlib.suppress(Exception):
        tdir = home / "telemetry" / "agent-performance"
        tdir.mkdir(parents=True, exist_ok=True)
        rec = {
            "v": 2,
            "kind": "prefix_drift",
            "prefix_drift": 1,
            "session": session_id,
            "expected_sha": expected_sha,
            "actual_sha": actual_sha,
            "ts": datetime.now(UTC).isoformat(),
        }
        with (tdir / "prefix-drift.jsonl").open("a", encoding="utf-8") as f:
            f.write(contracts.canonical_json(rec) + "\n")


def assemble_tail(
    *,
    delta_context: str | None = None,
    hot_context_refs: str | None = None,
    freshness_lines: str | None = None,
    hydrated_skills: Any = None,
    budget_warning: str | None = None,
    lean_content: str | None = None,
) -> str:
    """Assemble the per-turn TAIL slot:

    Contents: [BRAIN_CONTEXT_DELTA], hot-context refs (VMem), freshness lines,
    Skill hydration bodies, T3.1 hard-budget warning, and T3.4 Lean opportunity content (if any).
    """
    parts: list[str] = []

    if delta_context and delta_context.strip():
        parts.append(delta_context.strip())

    if hot_context_refs and hot_context_refs.strip():
        parts.append(hot_context_refs.strip())

    if freshness_lines and freshness_lines.strip():
        # Avoid duplicating freshness lines if already in delta_context
        if not delta_context or freshness_lines.strip() not in delta_context:
            parts.append(freshness_lines.strip())

    skills_text = format_hydrated_skills(hydrated_skills)
    if skills_text:
        parts.append(skills_text)

    if budget_warning and budget_warning.strip():
        parts.append(budget_warning.strip())

    if lean_content and lean_content.strip():
        parts.append(lean_content.strip())
    return "\n\n".join(parts)


def append_tail_after_user_message(
    messages: list[dict[str, Any]],
    tail: str,
) -> list[dict[str, Any]]:
    """Append TAIL slot after the latest user message in messages list."""
    if not tail.strip():
        return list(messages)

    result = [dict(m) for m in messages]
    # Find last user message index
    last_user_idx = -1
    for idx in range(len(result) - 1, -1, -1):
        if result[idx].get("role") == "user":
            last_user_idx = idx
            break

    tail_msg = {"role": "context", "content": tail}
    if last_user_idx >= 0:
        result.insert(last_user_idx + 1, tail_msg)
    else:
        result.append(tail_msg)

    return result
