"""Raw Tool Data (RTD) artifact store (plan §20/§21/§101).

Tool output that is too large for the active context is stored verbatim as a
content-addressed blob at ``<home>/state/artifacts/blobs/<sha256>.bin`` with
metadata at ``<home>/state/artifacts/meta/<sha256>.json``. Distillation is pure
and deterministic — identical input always yields identical distilled text —
so the raw bytes remain recoverable via :func:`expand` while context carries
only the distilled summary plus a recovery handle.

Never lossy-compress source edit regions (plan §21); this store keeps the exact
original bytes regardless of distillation.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .errors import BrainError

HANDLE_TEMPLATE = "[brain-artifact:sha256:{hash}]"
RECOVER_HINT_TEMPLATE = "Full output recoverable: /brain-expand {short}"

ARTIFACT_SCHEMA_VERSION = 1
HASH_LEN = 64
MIN_PREFIX_LEN = 8
MAX_FAILURE_LINES = 10
MAX_DISTILL_CHARS = 2000
DISTILL_KINDS: tuple[str, ...] = ("pytest", "git", "search", "test-log", "generic")

_PASSED_RE = re.compile(r"(\d+)\s+passed\b")
_FAILED_RE = re.compile(r"(\d+)\s+failed\b")
_ERROR_RE = re.compile(r"(\d+)\s+errors?\b")
_SKIPPED_RE = re.compile(r"(\d+)\s+skipped\b")

_HEX_CHARS = frozenset("0123456789abcdef")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _dirs(home: Path) -> tuple[Path, Path]:
    return Path(home) / "state" / "artifacts" / "blobs", Path(home) / "state" / "artifacts" / "meta"


def make_handle(hash: str) -> str:
    """The recovery handle for an artifact hash."""
    return HANDLE_TEMPLATE.format(hash=hash)


def recover_hint(hash: str) -> str:
    """The human/agent hint line pointing at /brain-expand."""
    return RECOVER_HINT_TEMPLATE.format(short=hash[:12])


# ---------------------------------------------------------------------------
# Distillers (pure and deterministic)
# ---------------------------------------------------------------------------


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _last_number(pattern: re.Pattern[str], text: str) -> int:
    values = [int(match.group(1)) for match in pattern.finditer(text)]
    return values[-1] if values else 0


def distill_pytest(text: str) -> str:
    """Deterministic pytest summary; falls back to generic when no markers."""
    patterns = (_PASSED_RE, _FAILED_RE, _ERROR_RE, _SKIPPED_RE)
    if not any(pattern.search(text) for pattern in patterns):
        return distill_generic(text)
    passed = _last_number(_PASSED_RE, text)
    failed = _last_number(_FAILED_RE, text)
    errors = _last_number(_ERROR_RE, text)
    skipped = _last_number(_SKIPPED_RE, text)
    out = f"pytest: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped"
    failures = [
        line
        for line in text.splitlines()
        if line.startswith("FAILED ") or line.startswith("ERROR ")
    ][:MAX_FAILURE_LINES]
    if failures:
        out += "\nFailures:\n" + "\n".join(f"  {line}" for line in failures)
    return out


def distill_git(text: str) -> str:
    """Deterministic git-log summary: entry count + first 50 subjects."""
    lines = _nonempty_lines(text)
    out = f"git log: {len(lines)} entries\n" + "\n".join(lines[:50])
    return out[:MAX_DISTILL_CHARS]


def distill_generic(text: str) -> str:
    """Deterministic generic summary: line/byte counts + head/tail."""
    lines = _nonempty_lines(text)
    head = "\n".join(lines[:5])
    tail = "\n".join(lines[-5:])
    out = f"{len(lines)} lines, {len(text.encode('utf-8'))} bytes\nhead:\n{head}\ntail:\n{tail}"
    return out[:MAX_DISTILL_CHARS]


def distill(text: str, kind: str, max_chars: int = MAX_DISTILL_CHARS) -> str:
    """Route to the right distiller and cap the result at ``max_chars``."""
    if kind == "pytest":
        out = distill_pytest(text)
    elif kind == "git":
        out = distill_git(text)
    else:  # search, test-log, generic, and unknown kinds
        out = distill_generic(text)
    return out[:max_chars]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _tmp_sibling(path: Path) -> Path:
    """Unique temp file in the target directory (no fixed .tmp collisions)."""
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    return Path(tmp_name)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_sibling(path)
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise BrainError(f"Could not write {path}: {exc}") from exc


def _write_text_atomic(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_sibling(path)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise BrainError(f"Could not write {path}: {exc}") from exc


def _validate_params(kind: str, tool: str, session: str | None) -> None:
    if not isinstance(kind, str) or not kind.strip():
        raise BrainError("kind must be a non-empty string")
    if not isinstance(tool, str):
        raise BrainError("tool must be a string")
    if session is not None and not isinstance(session, str):
        raise BrainError("session must be a string or None")


def _store(home: Path, data: bytes, text: str, kind: str, tool: str, session: str | None) -> dict:
    """Content-addressed atomic store. Idempotent for identical content."""
    _validate_params(kind, tool, session)
    sha = hashlib.sha256(data).hexdigest()
    blob_dir, meta_dir = _dirs(home)
    blob_path = blob_dir / f"{sha}.bin"
    meta_path = meta_dir / f"{sha}.json"
    if meta_path.exists():
        existing = blob_path.read_bytes() if blob_path.exists() else None
        if existing is None:
            raise BrainError(f"Corrupt artifact store: meta exists but blob is missing for {sha}")
        if existing != data:
            raise BrainError(f"sha256 collision for {sha}: existing blob differs from new content")
    else:
        _write_bytes_atomic(blob_path, data)
        meta = {
            "v": ARTIFACT_SCHEMA_VERSION,
            "hash": sha,
            "size": len(data),
            "created_at": _utcnow(),
            "kind": kind,
            "tool": tool,
            "session": session,
        }
        meta_text = json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        _write_text_atomic(meta_path, meta_text)
    return {
        "hash": sha,
        "size": len(data),
        "kind": kind,
        "tool": tool,
        "distilled": distill(text, kind),
        "handle": make_handle(sha),
        "path": str(blob_path),
    }


def store_text(
    home: Path,
    text: str,
    kind: str,
    tool: str = "",
    session: str | None = None,
) -> dict:
    """Store a text artifact. Returns {hash, size, kind, tool, distilled, handle, path}."""
    if not isinstance(text, str):
        raise BrainError("text must be a string")
    return _store(home, text.encode("utf-8"), text, kind, tool, session)


def store_file(
    home: Path,
    path: str | Path,
    kind: str,
    tool: str = "",
    session: str | None = None,
) -> dict:
    """Store a file's exact bytes; decode utf-8 (errors=replace) for distillation."""
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise BrainError(f"Cannot read {source}: {exc}") from exc
    return _store(home, data, data.decode("utf-8", errors="replace"), kind, tool, session)


def store_bytes(
    home: Path,
    data: bytes,
    kind: str,
    tool: str = "",
    session: str | None = None,
) -> dict:
    """Store exact raw BYTES (P3-F: byte-exact stdin preservation).

    Python's text-mode stdin applies universal-newline translation
    (CRLF -> LF), which would change the stored bytes vs what the host
    sent — breaking content-addressed sha256 recovery for multi-line
    Windows tool output. Callers that must preserve EXACT bytes (the RTD
    preserver) read sys.stdin.buffer and pass bytes here; the text form
    (decoded, errors=replace) is used only for the distilled preview."""
    if not isinstance(data, bytes):
        raise BrainError("data must be bytes")
    return _store(home, data, data.decode("utf-8", errors="replace"), kind, tool, session)


def expand(home: Path, hash_or_prefix: str) -> bytes:
    """Return the exact stored bytes for a full hash or unique prefix (>=8 hex)."""
    if not isinstance(hash_or_prefix, str):
        raise BrainError(f"Unknown artifact {hash_or_prefix!r}")
    key = hash_or_prefix.strip().lower()
    if (
        len(key) < MIN_PREFIX_LEN
        or len(key) > HASH_LEN
        or any(char not in _HEX_CHARS for char in key)
    ):
        raise BrainError(f"Unknown artifact {hash_or_prefix!r}")
    _, meta_dir = _dirs(home)
    matches = sorted(
        meta.stem
        for meta in meta_dir.glob("*.json")
        if len(meta.stem) == HASH_LEN and meta.stem.startswith(key)
    )
    if not matches:
        raise BrainError(f"Unknown artifact {hash_or_prefix!r}")
    if len(matches) > 1:
        raise BrainError(f"Ambiguous artifact prefix {key!r}: candidates: {', '.join(matches)}")
    blob_path = meta_dir.parent / "blobs" / f"{matches[0]}.bin"
    try:
        return blob_path.read_bytes()
    except OSError as exc:
        raise BrainError(f"Cannot read artifact blob {blob_path}: {exc}") from exc


def _load_meta(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrainError(f"Corrupt artifact meta {path}: {exc}") from exc
    err = f"Corrupt artifact meta {path}"
    if not isinstance(data, dict):
        raise BrainError(f"{err}: expected a JSON object")
    if data.get("v") != ARTIFACT_SCHEMA_VERSION:
        raise BrainError(f"{err}: unsupported schema version")
    if not isinstance(data.get("hash"), str) or len(data["hash"]) != HASH_LEN:
        raise BrainError(f"{err}: hash must be {HASH_LEN} hex chars")
    if not isinstance(data.get("size"), int) or data["size"] < 0:
        raise BrainError(f"{err}: size must be a non-negative integer")
    if not isinstance(data.get("created_at"), str) or not data["created_at"]:
        raise BrainError(f"{err}: created_at must be a non-empty string")
    if not isinstance(data.get("kind"), str) or not data["kind"]:
        raise BrainError(f"{err}: kind must be a non-empty string")
    if not isinstance(data.get("tool"), str):
        raise BrainError(f"{err}: tool must be a string")
    if data.get("session") is not None and not isinstance(data["session"], str):
        raise BrainError(f"{err}: session must be a string or null")
    return data


def list_artifacts(home: Path) -> list[dict]:
    """All artifact metadata, newest first."""
    _, meta_dir = _dirs(home)
    artifacts = [_load_meta(path) for path in sorted(meta_dir.glob("*.json"))]
    artifacts.sort(key=lambda meta: (meta["created_at"], meta["hash"]), reverse=True)
    return artifacts
