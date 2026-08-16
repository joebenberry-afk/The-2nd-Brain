"""Bounded Antigravity transcript task extraction tests (plan §21).

Uses sanitized transcript shapes derived from the real Antigravity
transcript.jsonl structure (JSONL lines with typed entries; user messages
carry role/content parts).
"""

from __future__ import annotations

import json

from second_brain import antigravity_transcript as at


def _write(tmp_path, lines, name="transcript.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(rec) for rec in lines) + "\n", encoding="utf-8")
    return p


def _user(text: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def test_initial_prompt(tmp_path) -> None:
    p = _write(
        tmp_path,
        [
            {"type": "system", "content": "boot"},
            _user("implement deploy profiles"),
            {"type": "assistant", "content": "I will."},
        ],
    )
    assert at.extract_latest_user_task(p) == "implement deploy profiles"


def test_followup_prompt_wins(tmp_path) -> None:
    p = _write(
        tmp_path,
        [
            _user("first task"),
            {"type": "assistant", "content": "done"},
            _user("follow-up: fix the price formatting"),
            {"type": "assistant", "content": "ok"},
        ],
    )
    assert at.extract_latest_user_task(p) == "follow-up: fix the price formatting"


def test_tool_chatter_ignored(tmp_path) -> None:
    p = _write(
        tmp_path,
        [
            _user("sort customers"),
            {"type": "tool_result", "content": "output of a huge command"},
            {"type": "tool", "content": "run_command"},
            {"type": "assistant", "content": "checking"},
            _user("confirm the sort is stable"),
        ],
    )
    assert at.extract_latest_user_task(p) == "confirm the sort is stable"


def test_subagent_shape(tmp_path) -> None:
    p = _write(
        tmp_path,
        [
            {"type": "user", "content": "subagent task: inspect routes"},
            {"type": "assistant", "content": "done"},
        ],
    )
    assert at.extract_latest_user_task(p) == "subagent task: inspect routes"


def test_truncated_malformed_last_line(tmp_path) -> None:
    p = _write(tmp_path, [_user("valid task")])
    with open(p, "a", encoding="utf-8") as f:
        f.write("{broken json\n")
    assert at.extract_latest_user_task(p) == "valid task"


def test_large_transcript_bounded_tail(tmp_path) -> None:
    lines = []
    for i in range(5000):
        lines.append(_user(f"task {i}") if i % 50 == 0 else {"type": "tool", "content": "x" * 200})
    p = _write(tmp_path, lines)
    result = at.extract_latest_user_task(p, max_lines=200)
    assert result == "task 4950"


def test_no_user_message(tmp_path) -> None:
    p = _write(tmp_path, [{"type": "tool", "content": "x"}, {"type": "system", "content": "s"}])
    assert at.extract_latest_user_task(p) is None


def test_missing_file(tmp_path) -> None:
    assert at.extract_latest_user_task(tmp_path / "nope.jsonl") is None


def test_empty_file(tmp_path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert at.extract_latest_user_task(p) is None
