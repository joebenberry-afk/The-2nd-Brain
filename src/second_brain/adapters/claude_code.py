"""Claude Code native lifecycle hook adapter (P3a)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from .. import ledger


def _git_capture(cwd: object, args: list[str]) -> str | None:
    """Best-effort `git <args>` in cwd. Never raises; empty/error -> None."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = result.stdout.strip()
        return out or None
    except Exception:
        return None


def _extract_candidate_marker(text: str) -> tuple[str, str, str] | None:
    """Parse an opt-in ``second-brain-candidate`` block deterministically."""
    m = re.search(r"<!--second-brain-candidate\s*(.*?)-->", text, re.S)
    if not m:
        return None
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        normalized = key.strip().lower()
        if sep and normalized in ("title", "observation", "evidence"):
            fields[normalized] = value.strip()
    title = fields.get("title", "")
    observation = fields.get("observation", "")
    evidence = fields.get("evidence", "")
    if not title or not observation:
        return None
    return title, observation, evidence


def _claude_usage_cursor_path(home: Path, session_id: str) -> Path | None:
    try:
        return ledger.session_dir(home, session_id) / "claude-usage-cursor.json"
    except Exception:
        return None


def _read_claude_usage_cursor(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        cursor = value.get("last_uuid") if isinstance(value, dict) else None
        return cursor if isinstance(cursor, str) and cursor else None
    except Exception:
        return None


def _write_claude_usage_cursor(path: Path | None, uuid: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_uuid": uuid}, separators=(",", ":")), encoding="utf-8")


def _claude_usage_records(
    home: Path,
    session_id: str,
    transcript_path: object,
    cache_state: dict | None,
) -> None:
    if not isinstance(transcript_path, str) or not transcript_path:
        return
    from .. import antigravity_transcript, autoinject

    records = antigravity_transcript.extract_usage_tail(transcript_path)
    if not records:
        return
    cursor_path = _claude_usage_cursor_path(home, session_id)
    cursor = _read_claude_usage_cursor(cursor_path)
    start = 0
    if cursor:
        for index, record in enumerate(records):
            if record.get("uuid") == cursor:
                start = index + 1
                break
    seen: set[str] = set()
    for record in records[start:]:
        uuid = record.get("uuid")
        if not isinstance(uuid, str) or not uuid or uuid in seen:
            continue
        seen.add(uuid)
        fields: dict[str, object] = {
            "harness": "claude-code",
            "uuid": uuid,
            "cache_state": cache_state,
        }
        for source, target in (
            ("input_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("cache_read_input_tokens", "cache_read_tokens"),
            ("cache_creation_input_tokens", "cache_write_tokens"),
        ):
            if source in record:
                fields[target] = record[source]
        if autoinject._append_telemetry(home, session_id, "assistant_usage", fields) is not True:
            continue
        try:
            _write_claude_usage_cursor(cursor_path, uuid)
        except Exception:
            pass


def _claude_cache_state(payload: dict) -> dict | None:
    state: dict[str, object] = {}
    for field in ("cache_hit_ratio", "re_cached_tokens"):
        if field in payload:
            state[field] = payload[field]
    return state or None


def run(home: Path) -> int:
    """Claude Code native lifecycle hook adapter (P3a).

    Reads ONE JSON object from stdin - Claude Code's own hook payload
    shape: {session_id, cwd, hook_event_name, transcript_path,
    last_assistant_message (Stop only), prompt (UserPromptSubmit only),
    tool_name/tool_response (PostToolUse only), source (SessionStart only,
    one of startup/resume/clear/compact/fork), trigger (PreCompact only,
    manual/auto), custom_instructions (PreCompact only)}.

    SessionStart: register the harness (host="claude-code") via the same
    telemetry-based BrainLifecycle used by Antigravity/Codex - no ledger
    write, no memory retrieval, no context injection. Always prints "{}".

    PreCompact: writes a bounded resume snapshot (goal from the bounded
    transcript tail, git branch/commit/changed files) as one
    COMPACTION_STARTED ledger event, deduplicated by content hash, then
    runs the existing pre-compaction durability barrier. Never blocks
    compaction.

    Stop: fires once per assistant turn (Claude Code's SessionEnd, not
    Stop, is the real once-per-session event; out of scope for P3a).
    Records usage counters from the bounded transcript tail and a lightweight
    claude_code_stop_turn telemetry record every call. Writes a candidate
    memory only when the assistant's last message carries the opt-in
    `<!--second-brain-candidate-->` marker with non-empty evidence.

    Fail-open: any error or malformed input -> "{}", exit 0. Claude Code
    must never fail to start, compact, or finish a turn because the Brain
    is unavailable.
    """
    from .. import antigravity_transcript, autoinject, contracts

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except Exception:
        payload = None
    payload_dict = payload if isinstance(payload, dict) else {}

    try:
        event = str(payload_dict.get("hook_event_name") or "SessionStart")
        session_id = str(payload_dict.get("session_id") or "claude-anon")
        session_internal_id = ledger.internal_session_id(session_id)
    except Exception:
        print("{}")
        return 0
    cwd = payload_dict.get("cwd")

    try:
        resolved_project = autoinject._resolve_project_id(
            home, str(cwd) if cwd else None, None
        )
    except Exception:
        resolved_project = "default"

    session = contracts.BrainSessionIdentity(
        internal_session_id=session_internal_id,
        host="claude-code",
        host_session_id=session_id,
        project_id=resolved_project,
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=1,
    )

    if event == "SessionStart":
        # fail-open: telemetry is best-effort, never blocks startup
        with contextlib.suppress(Exception):
            autoinject.BrainLifecycle(home, session).start_session(session)
        print("{}")
        return 0

    if event == "PreCompact":
        with contextlib.suppress(Exception):
            autoinject.BrainLifecycle(home, session).start_session(session)

        transcript_path = payload_dict.get("transcript_path")
        goal = None
        if transcript_path:
            try:
                goal = antigravity_transcript.extract_latest_task(str(transcript_path))
            except Exception:
                goal = None
        custom_instructions = payload_dict.get("custom_instructions")
        if isinstance(custom_instructions, str) and custom_instructions.strip():
            custom_instructions = custom_instructions.strip()[:500]
        else:
            custom_instructions = None

        branch = commit = None
        changed_files: list[str] = []
        if cwd:
            branch = _git_capture(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
            commit = _git_capture(cwd, ["rev-parse", "HEAD"])
            diff_stat = _git_capture(cwd, ["diff", "--name-only", "HEAD"])
            if diff_stat:
                changed_files = diff_stat.splitlines()[:20]

        resume_packet = {
            "goal": goal,
            "custom_instructions": custom_instructions,
            "project_id": resolved_project,
            "cwd": str(cwd) if cwd else None,
            "branch": branch,
            "commit": commit,
            "files_changed": changed_files,
            "trigger": str(payload_dict.get("trigger") or "auto"),
            # Fields the P3a spec asks for that a mechanical hook cannot
            # honestly derive without model participation (no PreToolUse/
            # Requirement Ledger inference occurs here). Left explicit and
            # empty rather than fabricated - see brainstem/adapters/claude-code/README.md.
            "decisions": [],
            "blockers": [],
            "open_questions": [],
            "evidence_refs": [],
            "tests_run": [],
        }
        content_hash = contracts.stable_content_hash(resume_packet)

        try:
            store = ledger.LedgerStore(home, session_id, host="claude-code")
            # Ledger primary keys are ledger.internal_session_id() (full sha256
            # hex), which is now the SAME scheme as `session.internal_session_id`
            # (unified across every host adapter) - no separate reconciliation
            # needed before calling create_session with `session` directly.
            internal = session.internal_session_id
            with store.open(create=True):
                # INSERT OR REPLACE is idempotent; ignore best-effort
                with contextlib.suppress(Exception):
                    store.create_session(session)
                existing = store.search(
                    content_hash[:16], event_type="compaction_started", limit=1
                )
                if not existing:
                    event_obj = contracts.BrainLifecycleEvent(
                        seq=0,
                        event_id=f"precompact-{content_hash[:16]}",
                        internal_session_id=internal,
                        agent_id="claude-code",
                        event_type=contracts.LifecycleEventType.COMPACTION_STARTED,
                        timestamp=datetime.now(UTC).isoformat(),
                        surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
                        ignorable=False,
                        payload={**resume_packet, "content_sha256": content_hash},
                    )
                    store.append_events([event_obj])
                ledger.checkpoint_ledger(store)
        except Exception:
            pass  # fail-open: never block compaction

        print("{}")
        return 0

    if event == "UserPromptSubmit":
        prompt = payload_dict.get("prompt")
        try:
            prompt_bytes = prompt.encode("utf-8") if isinstance(prompt, str) else None
        except Exception:
            prompt_bytes = None
        if prompt_bytes is not None:
            with contextlib.suppress(Exception):
                autoinject._append_telemetry(
                    home,
                    session_id,
                    "claude_code_user_prompt",
                    {
                        "harness": "claude-code",
                        "prompt_bytes": len(prompt_bytes),
                        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
                    },
                )
        print("{}")
        return 0

    if event == "PostToolUse":
        tool_name = payload_dict.get("tool_name") or payload_dict.get("tool")
        output = payload_dict.get("tool_response")
        if output is None:
            output = payload_dict.get("output")
        try:
            if isinstance(output, str):
                output_bytes = output.encode("utf-8")
            else:
                output_bytes = json.dumps(
                    output, separators=(",", ":"), sort_keys=True, default=str
                ).encode("utf-8")
        except Exception:
            output_bytes = b""
        with contextlib.suppress(Exception):
            autoinject._append_telemetry(
                home,
                session_id,
                "claude_code_tool_result",
                {
                    "harness": "claude-code",
                    "tool": str(tool_name) if tool_name is not None else "unknown",
                    "output_bytes": len(output_bytes),
                    "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
                },
            )
        print("{}")
        return 0

    if event == "Stop":
        with contextlib.suppress(Exception):
            _claude_usage_records(
                home,
                session_id,
                payload_dict.get("transcript_path"),
                _claude_cache_state(payload_dict),
            )
        with contextlib.suppress(Exception):
            autoinject.BrainLifecycle(home, session).start_session(session)
            autoinject._append_telemetry(
                home,
                session_id,
                "claude_code_stop_turn",
                {"host": "claude-code", "project_id": resolved_project},
            )

        last_message = payload_dict.get("last_assistant_message")
        with contextlib.suppress(Exception):
            autoinject.BrainLifecycle(home, session).finalize_session(
                tool_call_args=payload_dict.get("tool_call_args")
                or payload_dict.get("tool_calls")
                or antigravity_transcript.extract_tool_call_args(
                    payload_dict.get("transcript_path")
                ),
                final_message=last_message,
            )
        if isinstance(last_message, str) and last_message.strip():
            candidate = _extract_candidate_marker(last_message)
            if candidate is not None:
                title, observation, evidence = candidate
                if evidence.strip():  # empirical claims require evidence (never fabricate)
                    try:
                        lifecycle = autoinject.BrainLifecycle(home, session)
                        content_key = hashlib.sha256(
                            (title + observation + evidence).encode("utf-8")
                        ).hexdigest()[:16]
                        marker_path = (
                            home
                            / "telemetry"
                            / "agent-performance"
                            / "claude-code-candidates-seen.jsonl"
                        )
                        seen = set()
                        if marker_path.exists():
                            seen = {
                                line.strip()
                                for line in marker_path.read_text(encoding="utf-8").splitlines()
                            }
                        if content_key not in seen:
                            lifecycle.writeback_candidate(
                                session_id=session_id,
                                project_id=resolved_project,
                                title=title,
                                observation=observation,
                                evidence=[{"ref": evidence, "kind": "evidence"}],
                            )
                            marker_path.parent.mkdir(parents=True, exist_ok=True)
                            with marker_path.open("a", encoding="utf-8") as f:
                                f.write(content_key + "\n")
                    except Exception:
                        pass  # fail-open: candidate writeback never blocks Stop

        print("{}")
        return 0

    print("{}")
    return 0
