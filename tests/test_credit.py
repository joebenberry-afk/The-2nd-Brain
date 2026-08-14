"""Tests for credit assignment (Phase 18)."""

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import credit, db, episodes, plasticity, router, skillforge
from second_brain.errors import BrainError

SKILL = "sqlite-migration-verifier"


def _episode(home, summary, trigger="", counter="", lesson=""):
    sections = {}
    if trigger:
        sections["Trigger signals"] = trigger
    if counter:
        sections["Counter-signals"] = counter
    if lesson:
        sections["Reusable lesson"] = lesson
    return episodes.create_episode(home, "correction", summary, sections=sections)


def _forge_and_shadow(home, name=SKILL):
    eids = [
        _episode(
            home,
            "sqlite migration failed",
            trigger="sqlite migration fail\nschema version mismatch",
            counter="fresh database",
            lesson="verify migrations apply idempotently",
        ),
        _episode(
            home,
            "pending migrations blocked",
            trigger="pending migration",
            counter="clean shutdown verified",
            lesson="check the schema_version table",
        ),
    ]
    skillforge.forge_candidate(home, name, eids)
    skillforge.shadow_candidate(home, name, trigger_cases=[], baseline_cases=[])


def _credit_rows(home):
    conn = db.connect(db.db_path(home))
    try:
        return conn.execute("SELECT * FROM credit_events ORDER BY credit_id").fetchall()
    finally:
        conn.close()


def _outcome(home, verified=True):
    return plasticity.record_outcome(home, "s1", {"verified_success": verified, "tool_calls": 5})


# ---------------------------------------------------------------------------
# NO_AUTO_REWARD invariant
# ---------------------------------------------------------------------------


def test_no_auto_reward(brain_home):
    _forge_and_shadow(brain_home)
    _outcome(brain_home, verified=True)  # task success
    router.route(brain_home, "sqlite migration failed with a schema version mismatch")  # routing
    assert len(_credit_rows(brain_home)) == 0  # nothing auto-created
    # Even repeated outcome+routing cycles create nothing.
    for _ in range(3):
        _outcome(brain_home, verified=True)
        router.route(brain_home, "pending migrations are blocking the upgrade")
    assert len(_credit_rows(brain_home)) == 0


# ---------------------------------------------------------------------------
# assign_credit
# ---------------------------------------------------------------------------


def test_assign_credit_explicit_paths_and_inference(brain_home):
    _forge_and_shadow(brain_home)
    mid = __import__("second_brain.semantic", fromlist=["add_memory"]).add_memory(
        brain_home, "restore hygiene rule", "body"
    )
    counts = credit.assign_credit(
        brain_home,
        "s1",
        direct=[SKILL],
        contributory=[mid, "scout"],
        correlated=["tool:ast-grep", "policy:risk-adaptive", "verification:brief"],
    )
    assert counts == {"direct": 1, "contributory": 2, "correlated": 3, "total": 6}
    rows = _credit_rows(brain_home)
    assert len(rows) == 6
    by_id = {(r["subject_id"], r["credit_level"]): r for r in rows}
    assert by_id[(SKILL, "direct")]["subject_kind"] == "skill"
    assert by_id[(mid, "contributory")]["subject_kind"] == "memory"
    assert by_id[("scout", "contributory")]["subject_kind"] == "scout"
    assert by_id[("tool:ast-grep", "correlated")]["subject_kind"] == "tool"
    assert by_id[("policy:risk-adaptive", "correlated")]["subject_kind"] == "policy"
    assert by_id[("verification:brief", "correlated")]["subject_kind"] == "verification"
    assert by_id[(SKILL, "direct")]["session_id"] == "s1"


def test_assign_credit_unknown_subject(brain_home):
    with pytest.raises(BrainError, match="Unknown credit subject"):
        credit.assign_credit(
            brain_home, "s1", direct=["mystery-thing"], contributory=[], correlated=[]
        )
    # candidate-dir skills also resolve as 'skill'.
    _forge_and_shadow(brain_home)
    assert credit._infer_kind(brain_home, SKILL) == "skill"
    with pytest.raises(BrainError, match="direct"):
        credit.assign_credit(brain_home, "s1", direct="not-a-list", contributory=[], correlated=[])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# credit_report
# ---------------------------------------------------------------------------


def test_credit_report_aggregation(brain_home):
    _forge_and_shadow(brain_home)
    credit.assign_credit(brain_home, "s1", direct=[SKILL], contributory=[], correlated=["tool:rg"])
    credit.assign_credit(brain_home, "s2", direct=[SKILL], contributory=["scout"], correlated=[])
    report = credit.credit_report(brain_home)
    assert report["total_events"] == 4
    by_id = {entry["subject_id"]: entry for entry in report["subjects"]}
    assert by_id[SKILL]["direct"] == 2
    assert by_id[SKILL]["total"] == 2
    assert by_id["scout"]["contributory"] == 1
    assert by_id["tool:rg"]["correlated"] == 1
    # Session filter.
    report_s1 = credit.credit_report(brain_home, session_id="s1")
    assert report_s1["total_events"] == 2
    assert report_s1["subjects"][0]["subject_id"] == SKILL


# ---------------------------------------------------------------------------
# Counterfactual
# ---------------------------------------------------------------------------


def test_counterfactual_deterministic_and_report(brain_home):
    _forge_and_shadow(brain_home)
    tasks = [
        {"text": "sqlite migration failed with a schema version mismatch", "expect": [SKILL]},
        {"text": "deploy the frontend build", "expect": []},
        {"text": "pending migrations are blocking the upgrade", "expect": [SKILL]},
    ]
    first = credit.counterfactual_eval(brain_home, SKILL, tasks)
    second = credit.counterfactual_eval(brain_home, SKILL, tasks)
    assert first == second
    assert first["tasks_affected"] == 2
    assert first["tasks_unaffected"] == 1
    for task in first["tasks"]:
        assert task["delta_tools"] == 0
    report = brain_home / "outputs" / "reports" / f"counterfactual-{SKILL}.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "skill: sqlite-migration-verifier" in text
    assert "tasks: 3" in text


def test_counterfactual_unknown_skill(brain_home):
    with pytest.raises(BrainError, match="No shadow skill"):
        credit.counterfactual_eval(brain_home, "ghost-skill", [])


def test_skills_override_router_equivalence(brain_home):
    """Routing with an explicit skills list equals routing a home that has only
    those skills shadowed."""
    _forge_and_shadow(brain_home)
    other = brain_home / "other-home"
    _forge_and_shadow(other, name=SKILL)
    task = "sqlite migration failed with a schema version mismatch"
    override = router.route(brain_home, task, skills=[SKILL])
    direct = router.route(other, task)
    assert override == direct
    # Backward compatibility: skills=None behaves like the default.
    assert router.route(brain_home, task) == router.route(brain_home, task, skills=None)
    with pytest.raises(BrainError, match="skills"):
        router.route(brain_home, task, skills="nope")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# eval_skill_credit: inert recommendations
# ---------------------------------------------------------------------------


def test_eval_skill_credit_recommendations_only(brain_home):
    _forge_and_shadow(brain_home)  # sqlite-migration-verifier
    other_eids = [
        _episode(
            brain_home,
            "wal replay corruption after restore",
            trigger="wal replay corruption",
            lesson="drop stale sidecar files",
        ),
    ]
    skillforge.forge_candidate(brain_home, "wal-restore-verifier", other_eids)
    skillforge.shadow_candidate(
        brain_home, "wal-restore-verifier", trigger_cases=[], baseline_cases=[]
    )
    tasks = [
        # direct: expectation contains the skill.
        {"text": "sqlite migration failed with a schema version mismatch", "expect": [SKILL]},
        # contributory: both skills selected together; removing SKILL changes the set.
        {"text": "sqlite migration failed and wal replay corruption appeared", "expect": []},
        # unaffected: nothing selected either way.
        {"text": "deploy the frontend build", "expect": []},
    ]
    before = len(_credit_rows(brain_home))
    result = credit.eval_skill_credit(brain_home, SKILL, tasks)
    assert len(_credit_rows(brain_home)) == before  # nothing written
    assert result["recommendations"]["direct"] == 1
    assert result["recommendations"]["contributory"] == 1
    assert result["recommendations"]["correlated"] == 0
    assert "nothing was written" in result["note"]
    # The counterfactual report file exists, but no credit rows were created.
    assert list((brain_home / "outputs" / "reports").glob(f"counterfactual-{SKILL}.md"))
    assert len(_credit_rows(brain_home)) == before


# ---------------------------------------------------------------------------
# Hypothesis: report consistent with events
# ---------------------------------------------------------------------------

_ID_POOL = ["mem-a1", "mem-b2", "tool:rg", "scout", "verification:brief", "policy:p1"]


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(_ID_POOL), st.sampled_from(("direct", "contributory", "correlated"))
        ),
        min_size=0,
        max_size=12,
    )
)
def test_random_assignments_consistent(brain_home, assignments):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    direct = [sid for sid, level in assignments if level == "direct"]
    contributory = [sid for sid, level in assignments if level == "contributory"]
    correlated = [sid for sid, level in assignments if level == "correlated"]
    if direct or contributory or correlated:
        counts = credit.assign_credit(
            home, "s", direct=direct, contributory=contributory, correlated=correlated
        )
        assert counts["total"] == len(assignments)
    report = credit.credit_report(home)
    assert report["total_events"] == len(assignments)
    expected: dict[str, int] = {}
    for sid, _level in assignments:
        expected[sid] = expected.get(sid, 0) + 1
    assert sum(entry["total"] for entry in report["subjects"]) == len(assignments)
