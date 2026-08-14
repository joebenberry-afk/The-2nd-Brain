"""Shared identifier validation — the security boundary for simple names.

INV-01 / INV-02: project IDs, skill names, engram names, frontier change IDs,
proof task IDs and similar simple identifiers are NOT paths. A hostile value
must be REJECTED at this boundary, never silently sanitized into a different
valid value (sanitization creates collision and ambiguity risks).

The grammar is intentionally narrow::

    ^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$

Anything that could carry path semantics on any platform — separators
(/ and backslash), drive prefixes, UNC prefixes, traversal tokens (`.`/`..`),
absolute forms, glob metacharacters, control characters, newlines — is
rejected here, before it can influence a filesystem path, a generated
marker, or a glob expression.
"""

from __future__ import annotations

import re

from ..errors import BrainError

# Conservative identifier grammar (INV-01). Length cap 128 chars.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_RE = re.compile(r"^\\\\")
_MAX_LENGTH = 128


def _reasons(value: str) -> list[str]:
    """Return human-readable rejection reasons for a hostile value."""
    reasons: list[str] = []
    if any(ord(ch) < 32 for ch in value):
        reasons.append("control characters (including newlines) are not allowed")
    if "/" in value or "\\" in value:
        reasons.append("path separators are not allowed")
    if value.startswith("/") or _UNC_RE.match(value) or _WINDOWS_ABSOLUTE_RE.match(value):
        reasons.append("absolute/UNC paths are not allowed")
    if any(ch in value for ch in "*?[]"):
        reasons.append("glob metacharacters are not allowed")
    if "." in value:
        reasons.append("dots are not allowed")
    return reasons


def validate_identifier(value: object, *, kind: str = "identifier") -> str:
    """Validate one simple identifier and return it unchanged.

    Raises BrainError with a specific reason. Never mutates the value.
    """
    if not isinstance(value, str):
        raise BrainError(f"{kind} must be a string, got {type(value).__name__}")
    if not value:
        raise BrainError(f"{kind} must not be empty")
    if len(value) > _MAX_LENGTH:
        raise BrainError(f"{kind} is too long (max {_MAX_LENGTH} characters)")
    reasons = _reasons(value)
    if reasons:
        raise BrainError(f"Invalid {kind}: {reasons[0]}.")
    if not _IDENTIFIER_RE.fullmatch(value):
        raise BrainError(
            f"Invalid {kind}: must match {_IDENTIFIER_RE.pattern!r} "
            "(alphanumeric start, then letters/digits/hyphen/underscore)."
        )
    return value


# Purpose-specific wrappers: call sites communicate intent and one category can
# evolve without touching every caller.
def validate_project_id(value: object) -> str:
    return validate_identifier(value, kind="project ID")


def validate_skill_name(value: object) -> str:
    return validate_identifier(value, kind="skill name")


def validate_engram_name(value: object) -> str:
    return validate_identifier(value, kind="engram name")


def validate_frontier_id(value: object) -> str:
    # kind matches the codebase's existing "change_id" error vocabulary.
    return validate_identifier(value, kind="change_id")


def validate_proof_task_id(value: object) -> str:
    return validate_identifier(value, kind="proof task ID")


def validate_policy_id(value: object) -> str:
    return validate_identifier(value, kind="policy ID")


def validate_trigger_id(value: object) -> str:
    return validate_identifier(value, kind="trigger ID")
