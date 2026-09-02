"""Bounded Antigravity transcript task extraction (plan §13).

Reads only a bounded tail of the hook-provided `transcriptPath` JSONL to
identify the latest relevant user task:

- never loads the whole transcript on every invocation;
- ignores tool chatter when extracting the task;
- tolerates unknown/new event types;
- fails open (returns None) when task extraction is impossible;
- never persists raw transcript text into telemetry (caller's job).

Supported line shapes (tolerant, in order of preference):

1. `{"type": "user", "message": {"role": "user", "content": [text parts]}}`
2. `{"type": "user", "content": "..."}`
3. `{"role": "user", "content": "..."}`
4. `{"message": {"role": "user", "content": "..."}}`
5. `{"type": "user_message", "content": "..."}` (legacy synthetic shape)

Tool calls / tool results / assistant messages / system lines are never
treated as user intent. The parser reads the bounded tail (default last 200
lines / 128 KiB) and returns the content of the LAST user message found.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MAX_LINES = 200
DEFAULT_MAX_BYTES = 128 * 1024

_USER_TYPES = {"user", "user_message", "human", "prompt"}
_SKIP_TYPES = {"tool", "tool_call", "tool_result", "system", "assistant", "model"}


def _content_text(content: object) -> str | None:
    """Extract plain text from a content field that may be str or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(p for p in parts if p.strip()) or None
    return None


_REAL_USER_SOURCES = {"user_explicit", "user", "human"}
_REAL_USER_TYPES = {"user_input", "user", "user_message"}


def _unwrap_user_request(content: str) -> str:
    """Extract the task text from the real Antigravity <USER_REQUEST> wrapper."""
    import re

    m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.S)
    if m:
        return m.group(1).strip()
    # drop trailing <ADDITIONAL_METADATA>...</ADDITIONAL_METADATA> if present
    idx = content.find("<ADDITIONAL_METADATA>")
    if idx > 0:
        content = content[:idx]
    return content.strip()


def _line_user_text(line: dict) -> str | None:
    """Return the user task text from one parsed JSONL line, or None."""
    if not isinstance(line, dict):
        return None
    # Real Antigravity transcript schema: source/type based (e.g.
    # {"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>..."}).
    source = str(line.get("source") or "").strip().lower()
    line_type = str(line.get("type") or "").strip().lower()
    if source in _REAL_USER_SOURCES and line_type in _REAL_USER_TYPES:
        content = line.get("content")
        if isinstance(content, str) and content.strip():
            return _unwrap_user_request(content)
        return _content_text(content)
    if line_type == "user_input":
        content = line.get("content")
        if isinstance(content, str) and content.strip():
            return _unwrap_user_request(content)
    line_type = str(line.get("type") or "").strip().lower()
    if line_type in _SKIP_TYPES:
        return None

    # Shape 1/2: {"type": "user", "message": {...}} or {"type": "user", "content": ...}
    if line_type in _USER_TYPES:
        message = line.get("message")
        if isinstance(message, dict):
            text = _content_text(message.get("content"))
            if text:
                return text
        text = _content_text(line.get("content"))
        if text:
            return text
        # some transcripts put the text under "text"
        if isinstance(line.get("text"), str) and line["text"].strip():
            return line["text"]
        return None

    # Shape 3/4: {"role": "user", "content": ...} / {"message": {"role": "user", ...}}
    role = str(line.get("role") or "").strip().lower()
    if role == "user":
        message = line.get("message")
        if isinstance(message, dict):
            text = _content_text(message.get("content"))
            if text:
                return text
        text = _content_text(line.get("content"))
        if text:
            return text
        return None
    message = line.get("message")
    if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "user":
        return _content_text(message.get("content"))
    return None


def extract_latest_user_task(
    transcript_path: str | Path,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str | None:
    """Return the latest relevant user task from the bounded transcript tail.

    Fail-open: any I/O error, malformed JSON, or absent user message returns
    None. Reads at most the last `max_lines` lines (capped by `max_bytes`).
    """
    path = Path(transcript_path)
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
    except OSError:
        return None

    try:
        if size <= max_bytes:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        else:
            # Read only the bounded tail: seek to end - max_bytes.
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(max(0, size - max_bytes))
                fh.readline()  # drop partial first line
                lines = fh.readlines()
    except OSError:
        return None

    lines = lines[-max_lines:]
    latest: str | None = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            line = json.loads(raw)
        except (ValueError, TypeError):
            continue  # tolerate malformed lines
        text = _line_user_text(line)
        if text is not None:
            latest = text
    return latest

# Generic name for new callers; preserve the established public API.
extract_latest_task = extract_latest_user_task

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def extract_usage_tail(
    transcript_path: str | Path,
    max_bytes: int = 256 * 1024,
) -> list[dict]:
    """Extract assistant usage counters from a bounded JSONL transcript tail.

    Only UUIDs and the four source usage counters are returned.  Transcript
    content is never returned or persisted by this helper.  Malformed lines,
    non-assistant records, and all I/O failures are ignored (fail-open).
    """
    try:
        limit = max(0, int(max_bytes))
        if limit == 0:
            return []
        path = Path(transcript_path)
        if not path.is_file():
            return []
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            raw_tail = fh.read(limit)
    except (OSError, TypeError, ValueError):
        return []

    if size > limit:
        newline = raw_tail.find(b"\n")
        if newline < 0:
            return []
        raw_tail = raw_tail[newline + 1 :]

    try:
        text = raw_tail.decode("utf-8", errors="replace")
    except (UnicodeError, AttributeError):
        return []

    results: list[dict] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(line, dict):
            continue
        message = line.get("message")
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        line_type = str(line.get("type") or "").strip().lower()
        if role != "assistant" and line_type != "assistant":
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        uuid = line.get("uuid")
        if not isinstance(uuid, str) or not uuid.strip():
            continue
        result = {"uuid": uuid}
        for field in _USAGE_FIELDS:
            if field in usage:
                result[field] = usage[field]
        results.append(result)
    return results
