"""Tests for the JIT context compiler (plan §25)."""

import pytest

from second_brain import brainstem, jit, registry, semantic
from second_brain import working_set as ws
from second_brain.errors import BrainError


def _body(text: str) -> str:
    """Everything from the '# Task' section heading on (header stripped)."""
    assert "# Task" in text
    return "# Task" + text.split("\n# Task", 1)[1]


def _compile(brain_home, session_id, task, **kwargs):
    path = jit.compile_context(brain_home, session_id, task, **kwargs)
    return path, path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Determinism and structure
# ---------------------------------------------------------------------------


def test_compile_is_deterministic_in_body(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective", task_mode="DEEP")
    ws.add_requirement(brain_home, "s1", "Req one", importance="critical")
    ws.add_evidence(brain_home, "s1", "REQ-001", "covered by tests")
    p1, t1 = _compile(brain_home, "s1", "Implement the capsule")
    p2, t2 = _compile(brain_home, "s1", "Implement the capsule")
    assert p1 == p2
    # Only the header's compiled_at may differ; the body must be identical.
    assert _body(t1) == _body(t2)
    assert t1.startswith("# Task Context Capsule")
    assert "compiled_at:" in t1.split("\n# Task", 1)[0]


def test_header_lists_sources(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    _, text = _compile(brain_home, "s1", "Task")
    head = text.split("\n# Task", 1)[0]
    assert "compiled_at:" in head
    assert "sources:" in head
    assert "state/sessions/s1/active-state.json" in head
    assert "state/sessions/s1/requirements.json" in head
    assert "state/sessions/s1/read-ledger.json" in head


def test_output_path_and_slug(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    path, _ = _compile(brain_home, "s1", "Fix the Bug!")
    assert path.parent == brain_home / "outputs" / "context-capsules"
    assert path.name == "s1-fix-the-bug.md"


def test_make_slug():
    assert jit.make_slug("Hello, World!") == "hello-world"
    assert jit.make_slug("A B C") == "a-b-c"
    assert jit.make_slug("") == "task"
    assert jit.make_slug("   !!! ") == "task"
    assert jit.make_slug("café") == "caf"
    long_slug = jit.make_slug("word " * 30)
    assert len(long_slug) <= jit.SLUG_MAX
    assert long_slug == long_slug.rstrip("-")


# ---------------------------------------------------------------------------
# Section content
# ---------------------------------------------------------------------------


def test_no_state_compiles_with_none_markers(brain_home):
    _, text = _compile(brain_home, "fresh", "Any task")
    body = _body(text)
    assert "# Task\n\nAny task" in body
    assert "# Requirements\n\n(none)" in body
    assert "# Active State\n\n(none)" in body
    assert "# Project State\n\n(none)" in body
    assert "# Lexicon Matches\n\n(none)" in body
    assert "# Read Ledger Summary\n\ncount: 0\n(none)" in body
    # Deterministic even with no state at all.
    _, t2 = _compile(brain_home, "fresh", "Any task")
    assert _body(t2) == body


def test_task_section_empty_task(brain_home):
    _, text = _compile(brain_home, "fresh", "   ")
    assert "# Task\n\n(none)" in _body(text)


def test_requirements_section_format(brain_home):
    ws.add_requirement(brain_home, "s1", "Handle edge cases", importance="critical")
    ws.add_evidence(brain_home, "s1", "REQ-001", "unit test proves it")
    ws.add_requirement(brain_home, "s1", "Nice to have")
    _, text = _compile(brain_home, "s1", "Task")
    body = _body(text)
    assert "- REQ-001 [critical/unverified] Handle edge cases" in body
    assert "  - unit test proves it" in body
    assert "- REQ-002 [normal/unverified] Nice to have" in body


def test_active_state_section_compact(brain_home):
    ws.init_capsule(
        brain_home,
        "s1",
        "Objective text",
        task_mode="DEBUG",
        risk="HIGH",
        constraints=["c1", "c2"],
    )
    ws.update_capsule(brain_home, "s1", verification={"tests": "passed"}, next_action="run pytest")
    _, text = _compile(brain_home, "s1", "Task")
    body = _body(text)
    assert "objective: Objective text" in body
    assert "task_mode: DEBUG" in body
    assert "risk: HIGH" in body
    assert "constraints: c1; c2" in body
    assert "verification: tests=passed" in body
    assert "next_action: run pytest" in body
    assert "updated_at:" in body
    # Empty lists are omitted.
    assert "confirmed_facts:" not in body
    assert "open_questions:" not in body


def test_project_state_included(brain_home, repo):
    proj, _ = registry.add_project(brain_home, repo, project_id="proj-a")
    state = brain_home / "projects" / proj.id / "current-state.md"
    state.write_text("# Current State\n\n## Status\n\nGreen.\n", encoding="utf-8")
    _, text = _compile(brain_home, "s1", "Task", project_key=proj.id)
    body = _body(text)
    assert "# Project State\n\n# Current State\n\n## Status\n\nGreen." in body
    head = text.split("\n# Task", 1)[0]
    assert f"projects/{proj.id}/current-state.md" in head


def test_project_missing_key_degrades_to_none(brain_home):
    _, text = _compile(brain_home, "s1", "Task", project_key="does-not-exist")
    body = _body(text)
    assert "# Project State\n\n(none)" in body
    assert "# Lexicon Matches\n\n(none)" in body


def test_lexicon_matches_positive_and_negative(brain_home, repo):
    proj, _ = registry.add_project(brain_home, repo, project_id="lex-proj")
    lex = brain_home / "projects" / proj.id / "lexicon.md"
    lex.write_text(
        "# Lexicon\n"
        "## Active State Capsule\nDefinition: per-session state object.\n"
        "## Telemetry Hook\nDefinition: runtime interception point.\n",
        encoding="utf-8",
    )
    _, text = _compile(brain_home, "s1", "inspect the capsule", project_key=proj.id)
    body = _body(text)
    assert "## Active State Capsule" in body
    assert "Definition: per-session state object." in body
    assert "## Telemetry Hook" not in body

    _, text2 = _compile(brain_home, "s1", "just formatting prose", project_key=proj.id)
    assert "No matching terms." in _body(text2)


def test_lexicon_whole_word_match(brain_home, repo):
    proj, _ = registry.add_project(brain_home, repo, project_id="lex-proj")
    lex = brain_home / "projects" / proj.id / "lexicon.md"
    lex.write_text("## Cap\nDefinition: limited.\n", encoding="utf-8")
    _, text = _compile(brain_home, "s1", "handle capsule wiring", project_key=proj.id)
    assert "## Cap" not in _body(text)  # "cap" is not a whole word in "capsule"


def test_read_ledger_summary_count_and_last_ten(brain_home, tmp_path):
    for i in range(12):
        ws.record_read(brain_home, "s1", f"path/{i}.py", f"purpose {i}")
    _, text = _compile(brain_home, "s1", "Task")
    body = _body(text)
    assert "count: 12" in body
    assert "(purpose: purpose 0)" not in body
    assert "(purpose: purpose 1)" not in body
    for i in range(2, 12):
        assert f"path/{i}.py (purpose: purpose {i})" in body


def test_corrupt_capsule_degrades_to_none(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    path = brain_home / "state" / "sessions" / "s1" / "active-state.json"
    path.write_text("{broken", encoding="utf-8")
    _, text = _compile(brain_home, "s1", "Task")
    assert "# Active State\n\n(none)" in _body(text)


def test_ordered_protected_evidence_decision_memory_procedure_context(brain_home):
    memory_id = semantic.add_memory(
        brain_home,
        "Protected ordering memory",
        "Verified ordering evidence.",
        grade="VERIFIED",
    )
    semantic.curate(brain_home, memory_id, status="current", verify=False)
    decision = brainstem.decide(
        brain_home,
        brainstem.BrainstemSignals(task_class="verification", risk_class="HIGH"),
        session_id="s1",
        task_id="ordering-gate",
    )
    _, text = _compile(
        brain_home,
        "s1",
        "Implement the ordering gate",
        protected_refs=[f"memory:{memory_id}@v1"],
        task_evidence=["REQ-001:evidence:pytest"],
        verified_decisions=[f"decision:{decision.decision_ref}"],
        memory_refs=[f"memory:{memory_id}@v1"],
        procedure_refs=["skills/review/SKILL.md#Procedure"],
    )
    body = _body(text)
    positions = [
        body.index("# Task"),
        body.index("# Protected References"),
        body.index("# Task Evidence"),
        body.index("# Verified Decisions"),
        body.index("# Memory"),
        body.index("# Procedure"),
        body.index("# Requirements"),
        body.index("# Active State"),
    ]
    assert positions == sorted(positions)
    assert f"- memory:{memory_id}@v1" in body
    assert f"- decision:{decision.decision_ref}" in body


def test_compile_rejects_non_string_task(brain_home):
    with pytest.raises(BrainError, match="task"):
        jit.compile_context(brain_home, "s1", 42)  # type: ignore[arg-type]
