"""Fail-closed sanitization for proof records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"(?:sk|pk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?:ghp|github_pat|xox[baprs])-?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
)


class SecretDetected(ValueError):
    """Raised when a record would persist a credential-like value."""


def assert_public(text: str) -> None:
    """Reject likely credentials instead of attempting lossy redaction."""
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise SecretDetected("credential-like value detected in proof output")


def sanitize_text(text: str, roots: Mapping[str, str] | None = None) -> str:
    """Replace known machine roots, then reject secrets."""
    result = text
    for label, root in (roots or {}).items():
        if root:
            result = result.replace(root, f"<{label}>").replace(
                root.replace("\\", "/"), f"<{label}>"
            )
    assert_public(result)
    return result


def sanitize_value(value: Any, roots: Mapping[str, str] | None = None) -> Any:
    """Recursively sanitize JSON-compatible values."""
    if isinstance(value, str):
        return sanitize_text(value, roots)
    if isinstance(value, Mapping):
        return {str(key): sanitize_value(item, roots) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item, roots) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item, roots) for item in value]
    return value
