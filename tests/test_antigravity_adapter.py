"""Antigravity harness adapter acceptance tests — OFFICIAL hook contract.

The fixtures below follow the current official Antigravity hook payload
shapes (exa.hooks_pb protobuf JSON mapping, camelCase):

  common       : conversationId, workspacePaths, transcriptPath,
                 artifactDirectoryPath
  PreInvocation: preInvocationHookArgs{invocationNum, initialNumSteps}
  PostInvocation: postInvocationHookArgs{invocationNum, initialNumSteps}
  PostToolUse  : postToolHookArgs{stepIdx, toolCall{name,args}, error}
  Stop         : stopHookArgs{executionNum, terminationReason, error,
                 fullyIdle}

Result contracts asserted:

  PreInvocation with context -> {"injectSteps": [{"ephemeralMessage": ...}]}
  PreInvocation no injection  -> {}
  PostInvocation              -> {}
  PostToolUse                 -> {}
  Stop incomplete material    -> {"decision": "continue", "reason": ...}
  Stop complete               -> {"decision": "stop", "reason": ...}
  No Brain-internal debug fields ever leak into the hook response.

AutoInject visibility follows the canonical mode resolution
(SECOND_BRAIN_AUTOINJECT_* env > config/autoinject.toml > default shadow),
never a wrapper-local default. Lean influence comes only from the canonical
skill file through the harness-neutral lean_runtime helper.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import lean_runtime, semantic, working_set

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_SKILL = REPO_ROOT / "skills" / "candidates" / "lean-code" / "SKILL.md"
WORKSPACE = Path(r"C:\work\p3-proj")


def _run_cli(
    home: Path,
    *args: str,
    stdin: str = "",
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        input=stdin,
        timeout=120,
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "brain"


@pytest.fixture
def brain(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Brain with a registered project workspace + one curated memory."""
    from conftest import make_brain

    make_brain(home, monkeypatch)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / ".git").mkdir(exist_ok=True)
    r = _run_cli(
        home,
        "project",
        "add",
        str(WORKSPACE),
        "--name",
        "proj-agy",
        "--id",
        "proj-agy",
        "--no-marker",
        "--no-manifest",
    )
    assert r.returncode == 0, r.stderr
    mid = semantic.add_memory(
        home,
        "Migration ordering",
        "apply migrations in numeric order",
        scope="project",
        project_id="proj-agy",
        grade="TESTED",
    )
    semantic.curate(home, mid, status="current")
    return home


def _hook(
    home: Path,
    payload: dict,
    env_extra: dict[str, str] | None = None,
) -> dict:
    r = _run_cli(
        home,
        "autoinject",
        "antigravity-hook",
        stdin=json.dumps(payload),
        env_extra=env_extra,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _pre_invocation_payload(conversation: str = "agy-conv-1", transcript: str = "") -> dict:
    return {
        "conversationId": conversation,
        "workspacePaths": [str(WORKSPACE)],
        "transcriptPath": transcript,
        "artifactDirectoryPath": str(WORKSPACE / ".artifacts"),
        "modelName": "gemini-3.7-flash",
        "preInvocationHookArgs": {"invocationNum": 1, "initialNumSteps": 10},
    }


def _transcript(tmp_path: Path, *user_messages: str) -> Path:
    p = tmp_path / "transcript.jsonl"
    lines: list[dict[str, object]] = [
        {"type": "system", "content": "session bootstrap"},
        {"type": "tool_result", "content": "ignored tool chatter"},
    ]
    for _idx, msg in enumerate(user_messages):
        lines.append(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": msg}]},
            }
        )
        lines.append({"type": "assistant", "content": "ok"})
    p.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------- PreInvocation


def test_preinvocation_official_payload_injects_ephemeral_message(
    brain: Path, tmp_path: Path
) -> None:
    """L1: official camelCase payload -> injectSteps[].ephemeralMessage."""
    tr = _transcript(tmp_path, "migration ordering rules")
    out = _hook(
        brain,
        _pre_invocation_payload(transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "active"},
    )
    assert "injectSteps" in out
    assert len(out["injectSteps"]) == 1
    ep = out["injectSteps"][0]["ephemeralMessage"]
    assert "[BRAIN_CONTEXT_DELTA v1]" in ep
    assert "Migration ordering" in ep
    # contract: no Brain-internal debug fields leak into the response
    assert set(out.keys()) == {"injectSteps"}


def test_preinvocation_no_context_empty_object(brain: Path, tmp_path: Path) -> None:
    """L2: irrelevant task -> {} (empty compatible object)."""
    tr = _transcript(tmp_path, "unrelated recipe for chocolate cookies")
    out = _hook(
        brain,
        _pre_invocation_payload(conversation="agy-conv-irrel", transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "active"},
    )
    assert out == {}


def test_preinvocation_no_task_context_empty_object(brain: Path) -> None:
    """No transcript + no legacy fields -> {} (not BRAIN_UNAVAILABLE)."""
    out = _hook(brain, _pre_invocation_payload(conversation="agy-conv-notask"))
    assert out == {}


def test_preinvocation_shadow_mode_no_model_visible_packet(brain: Path, tmp_path: Path) -> None:
    """Shadow -> {} regardless of context (canonical mode semantics)."""
    tr = _transcript(tmp_path, "migration ordering rules")
    out = _hook(
        brain,
        _pre_invocation_payload(transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "shadow"},
    )
    assert out == {}


def test_preinvocation_config_mode_active_without_env(brain: Path, tmp_path: Path) -> None:
    """Config/autoinject.toml mode=active, no env -> injection allowed."""
    cfg = brain / "config" / "autoinject.toml"
    cfg.write_text('[autoinject]\nmode = "active"\n', encoding="utf-8")
    tr = _transcript(tmp_path, "migration ordering rules")
    out = _hook(brain, _pre_invocation_payload(conversation="agy-conv-cfg", transcript=str(tr)))
    assert "injectSteps" in out


def test_preinvocation_env_override_off(brain: Path, tmp_path: Path) -> None:
    """Env override off -> {} even though config says active."""
    tr = _transcript(tmp_path, "migration ordering rules")
    out = _hook(
        brain,
        _pre_invocation_payload(conversation="agy-conv-off", transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "off"},
    )
    assert out == {}


def test_preinvocation_dedup_same_session(brain: Path, tmp_path: Path) -> None:
    """Same conversation+task -> packet deduped; only {} or kernel-only response."""
    tr = _transcript(tmp_path, "migration ordering rules")
    first = _hook(
        brain,
        _pre_invocation_payload(transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "active"},
    )
    assert "injectSteps" in first
    second = _hook(
        brain,
        _pre_invocation_payload(transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "active"},
    )
    assert second == {} or (
        "injectSteps" in second
        and "[BRAIN_CONTEXT_DELTA v1]" not in second["injectSteps"][0]["ephemeralMessage"]
    )


# ---------------------------------------------------------------- Other events


def test_post_invocation_empty_object(brain: Path) -> None:
    payload = {
        "conversationId": "agy-conv-1",
        "workspacePaths": [str(WORKSPACE)],
        "modelName": "gemini-3.7-flash",
        "postInvocationHookArgs": {"invocationNum": 2, "initialNumSteps": 10},
    }
    assert _hook(brain, payload) == {}


def test_post_tool_use_nested_tool_call_empty_object(brain: Path) -> None:
    """PostToolUse parses real nested toolCall{name,args}; returns {}."""
    payload = {
        "conversationId": "agy-conv-1",
        "workspacePaths": [str(WORKSPACE)],
        "modelName": "gemini-3.7-flash",
        "postToolHookArgs": {
            "stepIdx": 3,
            "toolCall": {"name": "run_command", "args": {"command": "node tests/test.js"}},
            "error": "",
        },
    }
    assert _hook(brain, payload) == {}
    # telemetry recorded tool name
    tfile = brain / "telemetry" / "agent-performance" / "antigravity-hooks.jsonl"
    lines = [
        json.loads(line)
        for line in tfile.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tool_records = [line for line in lines if line.get("kind") == "tool_result"]
    assert tool_records and tool_records[-1]["tool"] == "run_command"


def test_stop_incomplete_material_requirement_continues(brain: Path) -> None:
    session = "agy-req-sess-1"
    working_set.add_requirement(
        brain, session, "All database queries must use prepared statements", importance="critical"
    )
    payload = {
        "conversationId": session,
        "workspacePaths": [str(WORKSPACE)],
        "modelName": "gemini-3.7-flash",
        "stopHookArgs": {
            "executionNum": 1,
            "terminationReason": "",
            "error": "",
            "fullyIdle": True,
        },
    }
    out = _hook(brain, payload)
    assert out["decision"] == "continue"
    assert "prepared statements" in out["reason"]


def test_stop_complete_allows_termination(brain: Path) -> None:
    session = "agy-req-sess-2"
    req = working_set.add_requirement(brain, session, "fix title config", importance="critical")
    working_set.add_evidence(brain, session, req["id"], "verify.js passed")
    working_set.set_requirement_status(brain, session, req["id"], "verified")
    payload = {
        "conversationId": session,
        "workspacePaths": [str(WORKSPACE)],
        "modelName": "gemini-3.7-flash",
        "stopHookArgs": {
            "executionNum": 1,
            "terminationReason": "",
            "error": "",
            "fullyIdle": True,
        },
    }
    out = _hook(brain, payload)
    assert out["decision"] == "stop"


def test_stop_non_normal_termination_no_forced_loop(brain: Path) -> None:
    session = "agy-req-sess-3"
    working_set.add_requirement(brain, session, "fix crash", importance="critical")
    payload = {
        "conversationId": session,
        "workspacePaths": [str(WORKSPACE)],
        "modelName": "gemini-3.7-flash",
        "stopHookArgs": {
            "executionNum": 1,
            "terminationReason": "max-steps",
            "error": "",
            "fullyIdle": False,
        },
    }
    out = _hook(brain, payload)
    assert out["decision"] == "stop"


# ---------------------------------------------------------------- Fail open


def test_malformed_input_fail_open(brain: Path) -> None:
    r = _run_cli(brain, "autoinject", "antigravity-hook", stdin="{broken json")
    assert r.returncode == 0
    assert json.loads(r.stdout) == {}


def test_uninitialized_brain_fail_open(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_pre_invocation_payload())
    r = _run_cli(empty, "autoinject", "antigravity-hook", stdin=payload)
    assert r.returncode == 0
    assert json.loads(r.stdout) == {}


# ---------------------------------------------------------------- Lean parity


def _seed_lean_skill(brain: Path, level: str) -> None:
    target = brain / "skills" / level / "lean-code"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANDIDATE_SKILL, target / "SKILL.md")
    lean_runtime.reset_lean_kernel_cache()


@pytest.mark.parametrize(
    "level,env_lean,expect_kernel",
    [
        ("candidates", None, False),  # candidate + no eval override -> inert
        ("candidates", "off", False),  # candidate + off -> inert
        ("candidates", "advisory", True),  # candidate + advisory -> kernel visible
        ("active", None, True),  # active -> kernel visible
        ("active", "off", False),  # active + off -> inert
    ],
)
def test_lean_kernel_visibility(
    brain: Path, tmp_path: Path, level: str, env_lean: str | None, expect_kernel: bool
) -> None:
    _seed_lean_skill(brain, level)
    tr = _transcript(tmp_path, "migration ordering rules")
    env_extra = {"SECOND_BRAIN_AUTOINJECT_MODE": "active"}
    if env_lean:
        env_extra["SECOND_BRAIN_LEAN"] = env_lean
    payload = _pre_invocation_payload(
        conversation=f"agy-lean-{level}-{env_lean}", transcript=str(tr)
    )
    out = _hook(brain, payload, env_extra)
    if not expect_kernel:
        assert out == {} or lean_runtime.LEAN_KERNEL_MARKER not in out.get("injectSteps", [{}])[
            0
        ].get("ephemeralMessage", "")
    else:
        ep = out["injectSteps"][0]["ephemeralMessage"]
        assert lean_runtime.LEAN_KERNEL_MARKER in ep
        assert "LEAN CODE:" in ep


def test_lean_retired_no_kernel(brain: Path, tmp_path: Path) -> None:
    _seed_lean_skill(brain, "retired")
    tr = _transcript(tmp_path, "migration ordering rules")
    out = _hook(
        brain,
        _pre_invocation_payload(conversation="agy-lean-retired", transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "active", "SECOND_BRAIN_LEAN": "advisory"},
    )
    ep = out.get("injectSteps", [{}])[0].get("ephemeralMessage", "")
    assert lean_runtime.LEAN_KERNEL_MARKER not in ep


def test_lean_kernel_single_source(brain: Path, tmp_path: Path) -> None:
    """Kernel text comes from the canonical skill file, not a constant."""
    _seed_lean_skill(brain, "active")
    tr = _transcript(tmp_path, "migration ordering rules")
    out = _hook(
        brain,
        _pre_invocation_payload(conversation="agy-lean-source", transcript=str(tr)),
        {"SECOND_BRAIN_AUTOINJECT_MODE": "active"},
    )
    ep = out["injectSteps"][0]["ephemeralMessage"]
    canonical = lean_runtime.extract_runtime_kernel(CANDIDATE_SKILL.read_text(encoding="utf-8"))
    assert canonical is not None
    assert canonical in ep
    # kernel char count unchanged (865)
    assert len(canonical) == 865
