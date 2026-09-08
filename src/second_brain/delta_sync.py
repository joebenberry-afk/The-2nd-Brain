"""
Delta Sync & Compact Cache Invalidation.

Plan §8: Phase 5 — Delta Sync & Compact Cache Invalidation.
Upgrades memory delivery from full payload re-transmission to minimal incremental sync.

Key Capabilities (§8.1 - §8.5):
- Memory delta generation: ADD, MODIFY, REMOVE, SUPERSEDE, TOMBSTONE, UNCHANGED.
- Emits zero tokens when memories are unchanged.
- Emits structured minimal patches for updates (≤20% token overhead of full resend).
- Verified delta application with canonical hash verification and fail-open recovery.
- Recipient deduplication across multi-agent driver/worker turns.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .contracts import (
    PacketItem,
    estimate_tokens,
    stable_content_hash,
)
from .errors import BrainError


class DeltaType(StrEnum):
    ADD = "ADD"
    MODIFY = "MODIFY"
    REMOVE = "REMOVE"
    SUPERSEDE = "SUPERSEDE"
    TOMBSTONE = "TOMBSTONE"
    UNCHANGED = "UNCHANGED"


@dataclass
class MemoryDeltaPacket:
    """A minimal structured memory delta packet (§8.3)."""

    target_memory_id: str
    base_version: int
    target_version: int
    delta_type: DeltaType
    patch_payload: dict[str, Any] = field(default_factory=dict)
    target_canonical_hash: str = ""
    reason: str = ""
    token_size_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_memory_id": self.target_memory_id,
            "base_version": self.base_version,
            "target_version": self.target_version,
            "delta_type": self.delta_type.value,
            "patch_payload": self.patch_payload,
            "target_canonical_hash": self.target_canonical_hash,
            "reason": self.reason,
            "token_size_estimate": self.token_size_estimate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryDeltaPacket:
        return cls(
            target_memory_id=data["target_memory_id"],
            base_version=int(data["base_version"]),
            target_version=int(data["target_version"]),
            delta_type=DeltaType(data["delta_type"]),
            patch_payload=data.get("patch_payload", {}),
            target_canonical_hash=data.get("target_canonical_hash", ""),
            reason=data.get("reason", ""),
            token_size_estimate=int(data.get("token_size_estimate", 0)),
        )


def _item_to_dict(item: PacketItem | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, PacketItem):
        return {
            "memory_id": item.memory_id,
            "version": item.version,
            "status": item.status.value,
            "confidence": item.confidence.value,
            "title": item.title,
            "observation": item.observation,
            "guidance": item.guidance,
            "evidence": item.evidence,
            "supersedes": list(item.supersedes) if item.supersedes else None,
        }
    return dict(item)


def compute_canonical_hash(item_dict: dict[str, Any]) -> str:
    """Compute deterministic canonical hash for a memory item dict."""
    return stable_content_hash(item_dict)


def compute_memory_delta(
    base: PacketItem | dict[str, Any] | None,
    target: PacketItem | dict[str, Any] | None,
    reason: str = "",
    *,
    home: Path | str | None = None,
) -> MemoryDeltaPacket:
    """
    Compute minimal structured delta between base and target memory items (§8.2, §8.3).
    """
    if base is None and target is None:
        raise BrainError("Both base and target cannot be None")

    if base is None and target is not None:
        t_dict = _item_to_dict(target)
        t_hash = compute_canonical_hash(t_dict)
        token_estimate = estimate_tokens(json.dumps(t_dict), home=home)
        return MemoryDeltaPacket(
            target_memory_id=t_dict["memory_id"],
            base_version=0,
            target_version=int(t_dict.get("version", 1)),
            delta_type=DeltaType.ADD,
            patch_payload=t_dict,
            target_canonical_hash=t_hash,
            reason=reason or "initial_delivery",
            token_size_estimate=token_estimate,
        )

    if base is not None and target is None:
        b_dict = _item_to_dict(base)
        return MemoryDeltaPacket(
            target_memory_id=b_dict["memory_id"],
            base_version=int(b_dict.get("version", 1)),
            target_version=int(b_dict.get("version", 1)) + 1,
            delta_type=DeltaType.TOMBSTONE,
            patch_payload={"status": "tombstone"},
            target_canonical_hash="",
            reason=reason or "deleted_or_tombstoned",
            token_size_estimate=15,
        )

    assert base is not None and target is not None
    b_dict = _item_to_dict(base)
    t_dict = _item_to_dict(target)

    b_hash = compute_canonical_hash(b_dict)
    t_hash = compute_canonical_hash(t_dict)

    if b_hash == t_hash:
        return MemoryDeltaPacket(
            target_memory_id=t_dict["memory_id"],
            base_version=int(b_dict.get("version", 1)),
            target_version=int(t_dict.get("version", 1)),
            delta_type=DeltaType.UNCHANGED,
            patch_payload={},
            target_canonical_hash=t_hash,
            reason="identical_content",
            token_size_estimate=0,
        )

    # Compute minimal diff
    patch: dict[str, Any] = {}
    for key, val in t_dict.items():
        if b_dict.get(key) != val:
            patch[key] = val

    delta_type = DeltaType.SUPERSEDE if t_dict.get("supersedes") else DeltaType.MODIFY
    token_estimate = estimate_tokens(json.dumps(patch), home=home)

    return MemoryDeltaPacket(
        target_memory_id=t_dict["memory_id"],
        base_version=int(b_dict.get("version", 1)),
        target_version=int(t_dict.get("version", 1)),
        delta_type=delta_type,
        patch_payload=patch,
        target_canonical_hash=t_hash,
        reason=reason or "incremental_update",
        token_size_estimate=token_estimate,
    )


def apply_delta(
    base: PacketItem | dict[str, Any] | None,
    delta: MemoryDeltaPacket,
    verify_hash: bool = True,
) -> dict[str, Any]:
    """
    Apply delta packet to base memory representation (§8.5).
    Fails open / raises BrainError if target hash verification fails.
    """
    if delta.delta_type == DeltaType.UNCHANGED:
        if base is None:
            raise BrainError("Cannot apply UNCHANGED delta to None base")
        return _item_to_dict(base)

    if delta.delta_type == DeltaType.ADD:
        res = dict(delta.patch_payload)
        if verify_hash and delta.target_canonical_hash:
            actual_hash = compute_canonical_hash(res)
            if actual_hash != delta.target_canonical_hash:
                raise BrainError(
                    f"Delta hash mismatch for ADD: "
                    f"expected {delta.target_canonical_hash}, got {actual_hash}"
                )
        return res

    if delta.delta_type in (DeltaType.TOMBSTONE, DeltaType.REMOVE):
        return {
            "memory_id": delta.target_memory_id,
            "version": delta.target_version,
            "status": "tombstone",
        }

    if base is None:
        raise BrainError(f"Cannot apply {delta.delta_type.value} delta without base memory")

    res = _item_to_dict(base)
    res.update(delta.patch_payload)

    if verify_hash and delta.target_canonical_hash:
        actual_hash = compute_canonical_hash(res)
        if actual_hash != delta.target_canonical_hash:
            raise BrainError(
                f"Delta hash mismatch: expected {delta.target_canonical_hash}, "
                f"got {actual_hash}. Refresh required."
            )

    return res


def render_delta_sync_text(deltas: list[MemoryDeltaPacket]) -> str:
    """
    Render human/model-readable Delta Sync block.
    Emits nothing if all deltas are UNCHANGED.
    """
    active_deltas = [d for d in deltas if d.delta_type != DeltaType.UNCHANGED]
    if not active_deltas:
        return ""

    lines = ["[BRAIN_DELTA_SYNC v1]"]
    lines.append("Minimal incremental memory updates applied to your session:")
    for d in active_deltas:
        if d.delta_type == DeltaType.ADD:
            lines.append(f"+ [ADD] {d.target_memory_id} (v{d.target_version})")
            for k, v in d.patch_payload.items():
                if k not in ("memory_id", "version"):
                    lines.append(f"    {k}: {str(v)[:120]}")
        elif d.delta_type in (DeltaType.MODIFY, DeltaType.SUPERSEDE):
            line_hdr = (
                f"~ [{d.delta_type.value}] {d.target_memory_id} "
                f"(v{d.base_version} -> v{d.target_version})"
            )
            lines.append(line_hdr)
            for k, v in d.patch_payload.items():
                lines.append(f"    {k}: {str(v)[:120]}")
        elif d.delta_type in (DeltaType.TOMBSTONE, DeltaType.REMOVE):
            lines.append(f"- [TOMBSTONE] {d.target_memory_id} (v{d.base_version} revoked)")

    return "\n".join(lines)


_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _delta_state_path(home: Path, session_id: str) -> Path:
    if (
        not isinstance(session_id, str)
        or not _SESSION_ID_RE.fullmatch(session_id)
        or session_id in (".", "..")
    ):
        raise BrainError(f"Invalid session id {session_id!r}: path traversal")
    return home / "state" / "sessions" / session_id / "delta-sync.json"


def _load_delta_state(
    path: Path, session_id: str
) -> dict[tuple[str, str, str], dict[str, Any]] | None:
    """Load state; ``None`` means malformed and must not be overwritten."""
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict) or raw.get("version") != 1:
            return None
        stored_session = raw.get("session_id")
        if stored_session is not None and stored_session != session_id:
            return None
        rows = raw.get("delivered")
        if not isinstance(rows, list):
            return None
        result: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                return None
            recipient = row.get("recipient")
            memory_id = row.get("memory_id")
            item = row.get("item")
            if (
                not isinstance(recipient, str)
                or not isinstance(memory_id, str)
                or not isinstance(item, dict)
            ):
                return None
            result[(session_id, recipient, memory_id)] = dict(item)
        return result
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _save_delta_state(
    path: Path,
    session_id: str,
    delivered: dict[tuple[str, str, str], dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"recipient": recipient, "memory_id": memory_id, "item": item}
        for (sid, recipient, memory_id), item in delivered.items()
        if sid == session_id
    ]
    payload = {"version": 1, "session_id": session_id, "delivered": rows}
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


class DeltaSyncEngine:
    """Session-level Delta Sync tracker (§8.4)."""

    def __init__(
        self,
        home: Path | str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.home = Path(home) if home is not None else None
        # (session_id, recipient, memory_id) -> dict[str, Any] (last delivered state)
        self._delivered: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._loaded_sessions: set[str] = set()
        self._corrupt_sessions: set[str] = set()
        if self.home is not None and session_id is not None:
            self._load_session(session_id)

    def _load_session(self, session_id: str) -> None:
        if self.home is None or session_id in self._loaded_sessions:
            return
        path = _delta_state_path(self.home, session_id)
        loaded = _load_delta_state(path, session_id)
        if loaded is None:
            self._corrupt_sessions.add(session_id)
        else:
            self._delivered.update(loaded)
        self._loaded_sessions.add(session_id)

    def sync_memories(
        self,
        session_id: str,
        target_items: list[PacketItem | dict[str, Any]],
        recipient: str = "driver",
    ) -> tuple[list[MemoryDeltaPacket], str]:
        """
        Compute deltas for a batch of target items against what was previously delivered.
        """
        if self.home is not None:
            self._load_session(session_id)
        deltas: list[MemoryDeltaPacket] = []
        for item in target_items:
            t_dict = _item_to_dict(item)
            mem_id = t_dict["memory_id"]
            key = (session_id, recipient, mem_id)
            base_dict = self._delivered.get(key)

            delta = compute_memory_delta(base_dict, t_dict, home=self.home)
            deltas.append(delta)

            # Update delivered memory state
            self._delivered[key] = t_dict

        if self.home is not None and session_id not in self._corrupt_sessions:
            _save_delta_state(_delta_state_path(self.home, session_id), session_id, self._delivered)
        rendered = render_delta_sync_text(deltas)
        return deltas, rendered


class DisclosureLevel(StrEnum):
    REPO = "REPO"  # Level 0: Project name, module listing (~50 tokens)
    MODULE = "MODULE"  # Level 1: Module overview, symbol signatures (~150 tokens)
    SYMBOL = "SYMBOL"  # Level 2: Specific function/class signature + docstring (~300 tokens)
    EXCERPT = "EXCERPT"  # Level 3: Targeted slice of relevant code (~600 tokens)
    FULL = "FULL"  # Level 4: Full source file


def progressive_disclose(
    content: str,
    level: DisclosureLevel | str = DisclosureLevel.SYMBOL,
    *,
    symbol_name: str | None = None,
    max_lines: int = 40,
) -> str:
    """
    Format content progressively to avoid premature full-file injection (Plan §4 R5).
    """
    lvl = level if isinstance(level, DisclosureLevel) else DisclosureLevel(str(level).upper())
    lines = content.splitlines()

    if lvl == DisclosureLevel.FULL:
        return content

    if lvl == DisclosureLevel.REPO:
        return f"[Repository Overview: {len(lines)} lines total]"

    if lvl == DisclosureLevel.MODULE:
        # Extract import and def/class lines
        symbols = [
            ln.strip() for ln in lines if ln.strip().startswith(("def ", "class ", "export "))
        ]
        return f"Module Symbols ({len(symbols)} total):\n" + "\n".join(
            f"  - {s[:80]}" for s in symbols[:20]
        )

    if lvl == DisclosureLevel.SYMBOL:
        if symbol_name:
            matched = []
            capturing = False
            non_ident = (" ", "\t", "#", '"""', "'''")
            for ln in lines:
                if f"def {symbol_name}" in ln or f"class {symbol_name}" in ln:
                    capturing = True
                elif capturing and len(matched) > 1 and ln and not ln.startswith(non_ident):
                    break
                if capturing:
                    matched.append(ln)
                    if len(matched) >= max_lines:
                        matched.append("    ... [remaining lines omitted]")
                        break
            if matched:
                return "\n".join(matched)
        # Fallback to first max_lines
        suffix = f"\n... ({len(lines) - max_lines} lines omitted)" if len(lines) > max_lines else ""
        return "\n".join(lines[:max_lines]) + suffix

    if lvl == DisclosureLevel.EXCERPT:
        suffix = f"\n... ({len(lines) - max_lines} lines omitted)" if len(lines) > max_lines else ""
        return "\n".join(lines[:max_lines]) + suffix

    return content
