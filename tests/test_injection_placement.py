"""Tests for T2.4: Stable prefix / tail injection slots.

Enforces:
1. PREFIX (session-constant):
   - Lean kernel, skill descriptors, the two T1.6 commands, project identity line.
   - Rendered once at session start and never changed across turns.
   - sha256(PREFIX) stored at session start; comparing later turns detects drift
     and logs prefix_drift=1.
2. TAIL (per-turn):
   - [BRAIN_CONTEXT_DELTA], hot-context refs (VMem), freshness lines, skill hydration bodies.
   - Appended after the latest user message in the turn context.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from second_brain import injection_slots, semantic

REPO_ROOT = Path(__file__).resolve().parent.parent
HERMES_PLUGIN = REPO_ROOT / "brainstem" / "adapters" / "hermes" / "hermes_plugin.py"


def _seed_skill(home: Path, name: str, purpose: str, body: str) -> Path:
    skill_dir = home / "skills" / "active" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"---\nname: {name}\nversion: 1.0.0\n---\n\n"
        f"# Purpose\n{purpose}\n\n"
        f"# Instructions\n{body}\n"
    )
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir / "SKILL.md"


def _seed_lean_skill(home: Path) -> Path:
    skill_dir = home / "skills" / "active" / "lean-code"
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "---\nname: lean-code\nversion: 1.0.0\n---\n\n"
        "# Purpose\nLean code discipline.\n\n"
        "# Runtime Kernel\nWrite minimal code. No unnecessary abstractions.\n"
    )
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir / "SKILL.md"


def _run_antigravity_hook(home: Path, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), "autoinject", "antigravity-hook"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=home,
        env=env,
        timeout=30,
    )


def test_prefix_is_byte_identical_across_turns(brain_home: Path) -> None:
    _seed_lean_skill(brain_home)
    _seed_skill(brain_home, "skill-a", "Skill A purpose.", "Skill A instructions.")

    # 1. Test assemble_prefix directly across turns
    session_id = "test-session-prefix-1"
    project_id = "proj-alpha"

    p1 = injection_slots.assemble_prefix(
        home=brain_home,
        project_id=project_id,
        role="driver",
    )
    sha1 = hashlib.sha256(p1.encode("utf-8")).hexdigest()
    drift1 = injection_slots.record_and_check_prefix_drift(brain_home, session_id, p1)
    assert drift1 is False, "Turn 1 must not report prefix drift"

    p2 = injection_slots.assemble_prefix(
        home=brain_home,
        project_id=project_id,
        role="driver",
    )
    sha2 = hashlib.sha256(p2.encode("utf-8")).hexdigest()
    drift2 = injection_slots.record_and_check_prefix_drift(brain_home, session_id, p2)

    assert sha1 == sha2, "PREFIX must be byte-identical across turns"
    assert drift2 is False, "Turn 2 must not report prefix drift"

    # Verify telemetry / drift detection when PREFIX actually drifts
    p_drifted = p2 + "\nUnexpected drift"
    drift3 = injection_slots.record_and_check_prefix_drift(brain_home, session_id, p_drifted)
    assert drift3 is True, "Altered prefix must report prefix_drift=1"

    # Verify Hermes plugin pre_llm_call maintains byte-identical prefix on turn 1 & 2
    import importlib.util
    spec = importlib.util.spec_from_file_location("sb_hermes_plugin", HERMES_PLUGIN)
    assert spec is not None and spec.loader is not None
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = plugin
    spec.loader.exec_module(plugin)

    class FakeCtx:
        profile_name = "Brain-Dev"
        def __init__(self, settings: dict[str, Any]) -> None:
            self.settings = settings
            self.hooks: dict[str, Any] = {}
            self.middleware: dict[str, Any] = {}
            self.tools: dict[str, Any] = {}
        def register_hook(self, name: str, cb: Any) -> None:
            self.hooks[name] = cb
        def register_middleware(self, name: str, cb: Any) -> None:
            self.middleware[name] = cb
        def register_tool(self, **kwargs: Any) -> None:
            self.tools[kwargs["name"]] = kwargs

    ctx = FakeCtx({
        "brain_home": str(brain_home),
        "brain_python": sys.executable,
        "bot_name": "Brain-Dev",
        "bot_role": "driver",
        "project_id": project_id,
        "repo_root": str(REPO_ROOT),
    })
    plugin.register(ctx)
    pre_llm = ctx.hooks["pre_llm_call"]

    res_turn1 = pre_llm(
        session_id="hermes-session-turns",
        user_message="Turn 1 user task",
        turn_id="turn-1",
    )
    assert res_turn1 is not None
    assert "system_prompt" in res_turn1, "Turn 1 must inject PREFIX into system_prompt"
    sys_prompt1 = res_turn1["system_prompt"]
    h1 = hashlib.sha256(sys_prompt1.encode("utf-8")).hexdigest()

    res_turn2 = pre_llm(
        session_id="hermes-session-turns",
        user_message="Turn 2 user task",
        turn_id="turn-2",
    )
    assert res_turn2 is not None
    # Turn 2 should either omit system_prompt or provide identical system_prompt
    if "system_prompt" in res_turn2 and res_turn2["system_prompt"]:
        h2 = hashlib.sha256(res_turn2["system_prompt"].encode("utf-8")).hexdigest()
        assert h1 == h2, "Hermes system prompt PREFIX must be byte-identical across turns"


def test_delta_goes_to_tail(brain_home: Path) -> None:
    _seed_lean_skill(brain_home)
    _seed_skill(brain_home, "search-skill", "Search skill purpose.", "Detailed search instructions.")
    semantic.add_memory(
        brain_home,
        "Delta Memory Title",
        "Delta memory observation for test.",
        project_id="proj-beta",
        grade="TESTED",
    )

    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    (brain_home / "config" / "skills.toml").write_text(
        '[visibility]\nmode = "enforced"\n', encoding="utf-8"
    )

    # 1. Verify assemble_prefix contains constant items and NOT dynamic delta items
    prefix = injection_slots.assemble_prefix(
        home=brain_home,
        project_id="proj-beta",
        role="driver",
    )

    # PREFIX must contain the 4 session-constant items
    assert "[second-brain-lean-code-kernel]" in prefix
    assert "Search skill purpose." in prefix
    assert 'To remember: run `brainctl remember "<claim>" --evidence <path>`.' in prefix
    assert 'To check: `brainctl recall "<question>"`. ' in prefix or 'To check: `brainctl recall "<question>"`.`' in prefix or 'To check: `brainctl recall "<question>"`.`' in prefix or 'To check: `brainctl recall "<question>"`. ' in prefix or 'To check: `brainctl recall "<question>"`.' in prefix
    assert "Project: proj-beta" in prefix

    # PREFIX must NOT contain dynamic tail items
    assert "[BRAIN_CONTEXT_DELTA" not in prefix
    assert "freshness:" not in prefix
    assert "Detailed search instructions." not in prefix

    # 2. Verify assemble_tail contains dynamic items
    tail = injection_slots.assemble_tail(
        delta_context="[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-123\nfreshness: VERIFIED_CURRENT\n",
        hot_context_refs="hot-ref-1",
        freshness_lines="Evidence: note.txt@abc12345 unchanged since 2026-09-03",
        hydrated_skills={"search-skill": "Detailed search instructions."},
    )

    assert "[BRAIN_CONTEXT_DELTA" in tail
    assert "freshness: VERIFIED_CURRENT" in tail
    assert "hot-ref-1" in tail
    assert "Detailed search instructions." in tail
    # TAIL must NOT contain the static prefix commands or project identity
    assert "Project: proj-beta" not in tail
    assert "To remember: run `brainctl remember" not in tail

    # 3. Verify appending tail after user message
    user_msg = {"role": "user", "content": "How do I search?"}
    messages = [
        {"role": "system", "content": "System prompt"},
        user_msg,
    ]
    placed_messages = injection_slots.append_tail_after_user_message(messages, tail)
    assert len(placed_messages) == 3 or (
        len(placed_messages) == 2 and tail in placed_messages[1]["content"]
    )
    # The last or user message must be followed by or contain the tail
    if len(placed_messages) == 3:
        assert placed_messages[1]["role"] == "user"
        assert placed_messages[2]["content"] == tail
    else:
        assert placed_messages[1]["content"].endswith(tail)


def test_antigravity_session_start_delivers_prefix(brain_home: Path) -> None:
    """CLI (_cmd_antigravity_hook) SessionStart: renders the documented
    {systemPrompt, injectSteps, prefix} contract, PREFIX contains the lean
    kernel + T1.6 commands + project identity line, and sha256(PREFIX) is
    recorded for later drift comparison."""
    _seed_lean_skill(brain_home)
    payload = {
        "conversationId": "agy-session-start-1",
        "workspacePaths": [],
        "sessionStartHookArgs": {},
        "modelName": "gemini-3.7-flash-high",
    }
    result = _run_antigravity_hook(brain_home, payload)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert set(out) == {"systemPrompt", "injectSteps", "prefix"}
    assert out["systemPrompt"] == out["prefix"]
    assert out["injectSteps"] == [{"ephemeralMessage": out["prefix"]}]
    assert "[second-brain-lean-code-kernel]" in out["prefix"]
    assert 'To remember: run `brainctl remember "<claim>" --evidence <path>`.' in out["prefix"]
    assert "Project:" in out["prefix"]

    hook_log = brain_home / "telemetry" / "agent-performance" / "antigravity-hooks.jsonl"
    assert hook_log.is_file()
    records = [json.loads(line) for line in hook_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    session_start = next(r for r in records if r["kind"] == "session_start")
    assert session_start["prefix_drift"] == 0
    assert session_start["prefix_sha256"] == hashlib.sha256(out["prefix"].encode("utf-8")).hexdigest()


def test_antigravity_session_start_fail_open_on_bare_home(tmp_path: Path) -> None:
    """CLI (_cmd_antigravity_hook) SessionStart: a bare brain home (no
    skills/config seeded at all -- the realistic failure mode for a fresh
    workspace) never crashes or exits non-zero; it degrades to whatever
    PREFIX is still assemble-able (T1.6 commands + project line, no lean
    kernel) rather than raising past the fail-open try/except."""
    bare_home = tmp_path / "bare-brain"
    bare_home.mkdir()
    payload = {
        "conversationId": "agy-session-start-bare",
        "workspacePaths": [],
        "sessionStartHookArgs": {},
    }
    result = _run_antigravity_hook(bare_home, payload)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    if out:
        assert set(out) == {"systemPrompt", "injectSteps", "prefix"}
        assert "[second-brain-lean-code-kernel]" not in out["prefix"]
        assert "Project:" in out["prefix"]
    else:
        assert out == {}
