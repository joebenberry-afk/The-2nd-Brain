"""Request-diff normalization safety tests (S2 request-neutrality evidence).

`scripts/v3_matched_arms.py` must never be able to report two different provider requests as
identical. Its content view tokenizes only the run's own path strings; everything else — message
text, tool schemas, any other key — is compared verbatim. Exactly the declared transport paths
(provider-generated tool-call ids) are replaced, and only in the secondary transport view.

These tests pin that boundary against the review finding that a generic normalizer (any key named
``id``/``timestamp``, UUID/date/epoch substitutions in all strings) could mask real content.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS = REPO_ROOT / "scripts" / "v3_matched_arms.py"


def _harness() -> Any:
    spec = importlib.util.spec_from_file_location("v3_matched_arms_under_test", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": "deepseek-flash",
        "stream": True,
        "messages": [
            {"role": "system", "content": "SYSTEM TEXT"},
            {"role": "user", "content": "USER TEXT"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_task",
                    "parameters": {
                        "type": "object",
                        "properties": {"id": {"type": "string", "description": "task id"}},
                        "required": ["id"],
                    },
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


def _diff(harness: Any, before: dict[str, Any], after: dict[str, Any], run_dir: Path) -> dict:
    tokens = harness.path_tokens(run_dir, run_dir.parent, None, [])
    left = harness.normalize_request(before, tokens)
    right = harness.normalize_request(after, tokens)
    content = harness.diff_requests(
        harness.request_summary({**left, "payload": left["content"]}),
        harness.request_summary({**right, "payload": right["content"]}),
    )
    transport = harness.diff_requests(
        harness.request_summary({**left, "payload": left["transport"]}),
        harness.request_summary({**right, "payload": right["transport"]}),
    )
    return {"content": content, "transport": transport}


def test_tool_schema_property_named_id_still_diffs(tmp_path: Path) -> None:
    """A schema property literally named `id` is content, not a transport field."""
    harness = _harness()
    before = _payload()
    after = _payload()
    after["tools"][0]["function"]["parameters"]["properties"]["id"]["description"] = "changed"
    result = _diff(harness, before, after, tmp_path / "run0001")
    assert result["content"]["identical"] is False
    assert result["content"]["tools"]["changed"], result["content"]["tools"]
    # the transport view must not hide it either
    assert result["transport"]["identical"] is False
    # a schema property named `id` is reported as transport-like but never rewritten
    tokens = harness.path_tokens(tmp_path / "run0001", tmp_path, None, [])
    views = harness.normalize_request(before, tokens)
    assert views["report"]["unlisted_transport_like_keys"] == [
        "tools[*].function.parameters.properties.id"
    ]
    assert views["content"]["tools"][0]["function"]["parameters"]["properties"]["id"] == {
        "type": "string",
        "description": "task id",
    }


def test_uuid_and_date_inside_message_text_still_diff(tmp_path: Path) -> None:
    """UUIDs and timestamps inside model-visible text are content, not transport noise."""
    harness = _harness()
    before = _payload(
        messages=[
            {"role": "system", "content": "SYSTEM TEXT"},
            {
                "role": "user",
                "content": "memory 11111111-2222-3333-4444-555555555555 from 2026-01-02T03:04:05Z",
            },
        ]
    )
    after = _payload(
        messages=[
            {"role": "system", "content": "SYSTEM TEXT"},
            {
                "role": "user",
                "content": "memory 99999999-8888-7777-6666-555555555555 from 2026-01-03T03:04:05Z",
            },
        ]
    )
    result = _diff(harness, before, after, tmp_path / "run0001")
    assert result["content"]["identical"] is False
    assert result["content"]["messages"]["added"], result["content"]["messages"]
    assert result["content"]["messages"]["removed"], result["content"]["messages"]


def test_each_runs_own_paths_are_the_only_tokenized_text(tmp_path: Path) -> None:
    """Each side tokenizes its own run paths; nothing else in the text is rewritten."""
    harness = _harness()
    before = _payload(
        messages=[
            {"role": "system", "content": "SYSTEM TEXT"},
            {"role": "user", "content": f"cwd is {tmp_path / 'run0001' / 'proj'} today"},
        ]
    )
    after = _payload(
        messages=[
            {"role": "system", "content": "SYSTEM TEXT"},
            {"role": "user", "content": f"cwd is {tmp_path / 'run0002' / 'proj'} today"},
        ]
    )
    left = harness.normalize_request(
        before, harness.path_tokens(tmp_path / "run0001", tmp_path, None, [])
    )
    right = harness.normalize_request(
        after, harness.path_tokens(tmp_path / "run0002", tmp_path, None, [])
    )
    content = harness.diff_requests(
        harness.request_summary({**left, "payload": left["content"]}),
        harness.request_summary({**right, "payload": right["content"]}),
    )
    assert content["identical"] is True, json.dumps(content, indent=1)
    assert left["content"]["messages"][1]["content"] == "cwd is <CWD> today"
    # a path that is NOT this run's own run dir is not tokenized away: another run's dir
    # keeps its own name inside the work-dir token, so it still diffs
    stray = _payload(messages=[{"role": "user", "content": f"cwd is {tmp_path / 'run0003'}"}])
    stray_left = harness.normalize_request(
        stray, harness.path_tokens(tmp_path / "run0001", tmp_path, None, [])
    )
    stray_text = stray_left["content"]["messages"][0]["content"]
    assert "<WORK_DIR>" in stray_text and "run0003" in stray_text, stray_text


def test_declared_transport_paths_are_the_only_masked_difference(tmp_path: Path) -> None:
    """Tool-call ids differ per run: content view sees it, transport view deliberately not."""
    harness = _harness()
    before = _payload(
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_aaa", "function": {}}],
            },
            {"role": "tool", "tool_call_id": "call_aaa", "content": "RESULT"},
        ]
    )
    after = _payload(
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_bbb", "function": {}}],
            },
            {"role": "tool", "tool_call_id": "call_bbb", "content": "RESULT"},
        ]
    )
    result = _diff(harness, before, after, tmp_path / "run0001")
    assert result["content"]["identical"] is False
    assert result["transport"]["identical"] is True, json.dumps(result["transport"], indent=1)
    tokens = harness.path_tokens(tmp_path / "run0001", tmp_path, None, [])
    views = harness.normalize_request(before, tokens)
    assert views["report"]["transport"] == {
        "messages[*].tool_calls[*].id": 1,
        "messages[*].tool_call_id": 1,
    }


def test_undeclared_transport_like_paths_are_reported_not_masked(tmp_path: Path) -> None:
    """An unlisted `id`-ish path is left verbatim and reported for review."""
    harness = _harness()
    before = _payload(messages=[{"role": "tool", "content": "RESULT", "vendor_trace_id": "a"}])
    after = _payload(messages=[{"role": "tool", "content": "RESULT", "vendor_trace_id": "b"}])
    tokens = harness.path_tokens(tmp_path / "run0001", tmp_path, None, [])
    views = harness.normalize_request(before, tokens)
    assert "messages[*].vendor_trace_id" in views["report"]["unlisted_transport_like_keys"]
    assert views["content"]["messages"][0]["vendor_trace_id"] == "a"
    result = _diff(harness, before, after, tmp_path / "run0001")
    assert result["content"]["identical"] is False
    assert result["transport"]["identical"] is False
