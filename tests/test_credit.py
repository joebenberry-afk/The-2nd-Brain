"""Tests for credit assignment (Phase 18)."""

import json
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import credit, db, episodes, plasticity, router, skillforge, telemetry
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
    report = brain_home / "outputs" / "audits" / f"counterfactual-{SKILL}.md"
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
    assert list((brain_home / "outputs" / "audits").glob(f"counterfactual-{SKILL}.md"))
    assert len(_credit_rows(brain_home)) == before


# ---------------------------------------------------------------------------
# Counterfactual result (plan §44, observed effect)
# ---------------------------------------------------------------------------


def _starting_state(**overrides):
    state = {
        "task_hash": "t" * 64,
        "repository_state_hash": "r" * 64,
        "requirements_hash": "q" * 64,
        "model_config_hash": "m" * 64,
        "available_tools_hash": "o" * 64,
        "environment_hash": "e" * 64,
    }
    state.update(overrides)
    return state


def _verification(outcome="passed", ref="verify:brief-1"):
    return {"outcome": outcome, "evidence_ref": ref}


def _regressions(count=0, ref="pytest:full-suite-1"):
    return {"count": count, "evidence_ref": ref}


def _tokens(input=0, cache_read=0, cache_write=0, output=0, total=0, reasoning=None):
    return {
        "input": input,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": output,
        "total": total,
        "reasoning": reasoning,
    }


def _arm(run_id, *, success=True, tokens=None, tool_calls=1, wall_time_ms=100.0, **kw):
    return {
        "run_id": run_id,
        "success": success,
        "tokens": tokens or _tokens(input=100, output=50, total=150),
        "tool_calls": tool_calls,
        "wall_time_ms": wall_time_ms,
        "verification": kw.pop("verification", _verification()),
        "regressions": kw.pop("regressions", _regressions()),
    }


def test_counterfactual_result_full_comparison_and_deltas(brain_home):
    with_arm = _arm(
        "run-with-1",
        tokens=_tokens(input=500, cache_read=200, output=100, total=800),
        tool_calls=3,
        wall_time_ms=4200.0,
    )
    without_arm = _arm(
        "run-without-1",
        tokens=_tokens(input=900, cache_read=0, output=180, total=1080),
        tool_calls=6,
        wall_time_ms=9100.0,
    )
    result = credit.counterfactual_result(
        brain_home,
        evaluation_id="eval-1",
        intervention_type="skill",
        intervention_id="sqlite-migration-verifier",
        intervention_hash="h" * 64,
        starting_state=_starting_state(),
        with_arm=with_arm,
        without_arm=without_arm,
    )
    assert result["schema_version"] == 1
    assert result["intervention"] == {
        "type": "skill",
        "id": "sqlite-migration-verifier",
        "hash": "h" * 64,
    }
    assert result["starting_state_hash"] == credit._stable_hash(_starting_state())
    deltas = result["observed_effect"]["deltas"]
    assert deltas["success"] == "both_succeeded"
    assert deltas["tokens"]["total"] == 800 - 1080
    assert deltas["tokens"]["input"] == 500 - 900
    assert deltas["tokens"]["cache_read"] == 200
    assert deltas["tokens"]["reasoning"] is None
    assert deltas["tool_calls"] == 3 - 6
    assert deltas["wall_time_ms"] == 4200.0 - 9100.0
    assert deltas["verification"] == "same"
    assert deltas["regressions"] == 0
    assert result["evaluator_economics"]["evaluation_model_calls"] == 0
    assert result["evaluator_economics"]["bookkeeping_wall_time_ms"] >= 0
    target = (
        brain_home
        / "outputs"
        / "audits"
        / "counterfactual"
        / "skill"
        / "sqlite-migration-verifier-eval-1.json"
    )
    assert target.exists()


def test_counterfactual_result_reports_negative_effect_honestly(brain_home):
    """The skill making things WORSE must be reported as-is — no positive
    bias, no forced-good outcome."""
    with_arm = _arm(
        "run-with-2",
        success=False,
        tokens=_tokens(input=2000, output=400, total=2400),
        verification=_verification("failed"),
        regressions=_regressions(2),
    )
    without_arm = _arm(
        "run-without-2",
        success=True,
        tokens=_tokens(input=500, output=100, total=600),
        verification=_verification("passed"),
        regressions=_regressions(0),
    )
    result = credit.counterfactual_result(
        brain_home,
        evaluation_id="eval-2",
        intervention_type="skill",
        intervention_id="harmful-skill",
        intervention_hash="h" * 64,
        starting_state=_starting_state(),
        with_arm=with_arm,
        without_arm=without_arm,
    )
    deltas = result["observed_effect"]["deltas"]
    assert deltas["success"] == "without_only"
    assert deltas["tokens"]["total"] == 2400 - 600  # positive: WITH cost MORE
    assert deltas["verification"] == "passed->failed"
    assert deltas["regressions"] == 2


def test_counterfactual_result_rejects_same_run_id(brain_home):
    arm = _arm("same-run")
    with pytest.raises(BrainError, match="genuinely separate runs"):
        credit.counterfactual_result(
            brain_home,
            evaluation_id="eval-3",
            intervention_type="skill",
            intervention_id="scout",
            intervention_hash="h" * 64,
            starting_state=_starting_state(),
            with_arm=arm,
            without_arm=dict(arm),
        )


def test_counterfactual_result_rejects_invalid_intervention_type(brain_home):
    with pytest.raises(BrainError, match="intervention_type"):
        credit.counterfactual_result(
            brain_home,
            evaluation_id="eval-4",
            intervention_type="prompt_template",  # not one of the frozen §44 classes
            intervention_id="x",
            intervention_hash="h" * 64,
            starting_state=_starting_state(),
            with_arm=_arm("w1"),
            without_arm=_arm("w2"),
        )


def test_counterfactual_result_rejects_invalid_verification_outcome(brain_home):
    bad = _arm("w1", verification={"outcome": "great", "evidence_ref": "x"})
    with pytest.raises(BrainError, match=r"verification\.outcome"):
        credit.counterfactual_result(
            brain_home,
            evaluation_id="eval-5",
            intervention_type="skill",
            intervention_id="scout",
            intervention_hash="h" * 64,
            starting_state=_starting_state(),
            with_arm=bad,
            without_arm=_arm("w2"),
        )


def test_counterfactual_result_rejects_negative_token_counts(brain_home):
    bad = _arm("w1", tokens=_tokens(input=-5))
    with pytest.raises(BrainError, match="non-negative integer"):
        credit.counterfactual_result(
            brain_home,
            evaluation_id="eval-6",
            intervention_type="skill",
            intervention_id="scout",
            intervention_hash="h" * 64,
            starting_state=_starting_state(),
            with_arm=bad,
            without_arm=_arm("w2"),
        )


def test_counterfactual_result_rejects_incomplete_starting_state(brain_home):
    incomplete = _starting_state()
    del incomplete["environment_hash"]
    with pytest.raises(BrainError, match="starting_state"):
        credit.counterfactual_result(
            brain_home,
            evaluation_id="eval-7",
            intervention_type="skill",
            intervention_id="scout",
            intervention_hash="h" * 64,
            starting_state=incomplete,
            with_arm=_arm("w1"),
            without_arm=_arm("w2"),
        )


def test_counterfactual_result_zero_regressions_measured_not_placeholder(brain_home):
    result = credit.counterfactual_result(
        brain_home,
        evaluation_id="eval-8",
        intervention_type="skill",
        intervention_id="scout",
        intervention_hash="h" * 64,
        starting_state=_starting_state(),
        with_arm=_arm("w1", regressions=_regressions(0, ref="pytest:run-with-8")),
        without_arm=_arm("w2", regressions=_regressions(0, ref="pytest:run-without-8")),
    )
    assert result["with_arm"]["regressions"] == {"count": 0, "evidence_ref": "pytest:run-with-8"}
    assert result["observed_effect"]["deltas"]["regressions"] == 0


def test_is_counterfactual_result_current_treatment_identity(brain_home):
    result = credit.counterfactual_result(
        brain_home,
        evaluation_id="eval-9",
        intervention_type="skill",
        intervention_id="scout",
        intervention_hash="version-a",
        starting_state=_starting_state(),
        with_arm=_arm("w1"),
        without_arm=_arm("w2"),
    )
    assert credit.is_counterfactual_result_current(result, "version-a") is True
    # The intervention materially changed (new hash): stale evidence must not
    # silently describe the new version.
    assert credit.is_counterfactual_result_current(result, "version-b") is False


def test_counterfactual_result_persists_bounded_json_no_raw_content(brain_home):
    result = credit.counterfactual_result(
        brain_home,
        evaluation_id="eval-10",
        intervention_type="skill",
        intervention_id="scout",
        intervention_hash="h" * 64,
        starting_state=_starting_state(),
        with_arm=_arm("w1"),
        without_arm=_arm("w2"),
    )
    target = brain_home / "outputs" / "audits" / "counterfactual" / "skill" / "scout-eval-10.json"
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored == result
    # Bounded: evidence is references/hashes, never raw transcript text.
    assert len(stored["with_arm"]["verification"]["evidence_ref"]) < 200
    assert "tool output" not in json.dumps(stored).lower()


def test_counterfactual_result_harness_neutral_across_intervention_types(brain_home):
    """One evaluator, not five: every frozen §44 class flows through the same
    counterfactual_result() with no special-casing."""
    for intervention_type, intervention_id in (
        ("skill", "scout-skill"),
        ("memory", "mem-abc123"),
        ("routing_policy", "sparse-top-k"),
        ("scout", "scout"),
        ("verification_policy", "risk-adaptive-ladder"),
    ):
        result = credit.counterfactual_result(
            brain_home,
            evaluation_id=f"eval-{intervention_type}",
            intervention_type=intervention_type,
            intervention_id=intervention_id,
            intervention_hash="h" * 64,
            starting_state=_starting_state(),
            with_arm=_arm(f"w1-{intervention_type}"),
            without_arm=_arm(f"w2-{intervention_type}"),
        )
        assert result["intervention"]["type"] == intervention_type


def test_counterfactual_result_predicted_vs_observed_distinct(brain_home):
    _forge_and_shadow(brain_home)
    predicted = credit.counterfactual_eval(
        brain_home,
        SKILL,
        [{"text": "sqlite migration failed with a schema version mismatch", "expect": [SKILL]}],
    )
    result = credit.counterfactual_result(
        brain_home,
        evaluation_id="eval-predicted",
        intervention_type="skill",
        intervention_id=SKILL,
        intervention_hash="h" * 64,
        starting_state=_starting_state(),
        with_arm=_arm("w1"),
        without_arm=_arm("w2"),
        predicted_effect=predicted,
    )
    assert result["predicted_effect"] == predicted
    assert result["predicted_effect"] is not result["observed_effect"]
    assert "routed_change" not in json.dumps(result["observed_effect"])


def test_ordinary_flow_creates_no_counterfactual_evidence(brain_home):
    """§44: not required on every task. Ordinary credit/routing flows must
    never force a counterfactual campaign."""
    _forge_and_shadow(brain_home)
    plasticity.record_outcome(brain_home, "s1", {"verified_success": True, "tool_calls": 2})
    router.route(brain_home, "sqlite migration failed with a schema version mismatch")
    credit.assign_credit(brain_home, "s1", direct=[SKILL], contributory=[], correlated=[])
    assert not (brain_home / "outputs" / "audits" / "counterfactual").exists()


def _write_telemetry_records(home, session_id, records):
    directory = telemetry.telemetry_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    lines = [json.dumps({"session": session_id, **record}) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_arm_from_telemetry_uses_real_session_usage(brain_home):
    session_id = "2026-08-26T00-00-00-000Z_test-session"
    _write_telemetry_records(
        brain_home,
        session_id,
        [
            {"v": 2, "kind": "session_start", "ts": "2026-08-26T00:00:00.000Z"},
            {
                "v": 3,
                "kind": "assistant_usage",
                "ts": "2026-08-26T00:00:05.000Z",
                "provider": "test",
                "model": "test-model",
                "input_tokens": 300,
                "output_tokens": 120,
                "cache_read_tokens": 100,
                "cache_write_tokens": 0,
                "total_tokens": 420,
            },
            {
                "v": 3,
                "kind": "assistant_usage",
                "ts": "2026-08-26T00:00:07.000Z",
                "provider": "test",
                "model": "test-model",
                "input_tokens": 50,
                "output_tokens": 10,
                "cache_read_tokens": 40,
                "cache_write_tokens": 0,
                "total_tokens": 60,
            },
            {
                "v": 2,
                "kind": "tool_call",
                "ts": "2026-08-26T00:00:04.000Z",
                "tool": "bash",
                "id": "1",
                "input_bytes": 12,
            },
            {
                "v": 2,
                "kind": "tool_call",
                "ts": "2026-08-26T00:00:06.000Z",
                "tool": "read",
                "id": "2",
                "input_bytes": 12,
            },
            {
                "v": 2,
                "kind": "session_shutdown",
                "ts": "2026-08-26T00:00:10.000Z",
                "reason": "done",
            },
        ],
    )
    arm = credit.arm_from_telemetry(
        brain_home,
        session_id,
        success=True,
        verification=_verification(),
        regressions=_regressions(0),
    )
    assert arm["run_id"] == session_id
    assert arm["tokens"]["input"] == 350
    assert arm["tokens"]["cache_read"] == 140
    assert arm["tokens"]["output"] == 130
    assert arm["tokens"]["total"] == 480
    assert arm["tokens"]["reasoning"] is None  # never fabricated when absent
    assert arm["tool_calls"] == 2
    assert arm["wall_time_ms"] == pytest.approx(10000.0, abs=1.0)


def test_arm_from_telemetry_rejects_absent_session(brain_home):
    """A session with no (or fewer than two timestamped) telemetry records
    must be rejected, never silently reported as a zero-valued arm."""
    with pytest.raises(BrainError, match="No measurable telemetry"):
        credit.arm_from_telemetry(
            brain_home,
            "session-that-never-ran",
            success=True,
            verification=_verification(),
            regressions=_regressions(0),
        )


def test_arm_from_telemetry_rejects_single_record_session(brain_home):
    """One timestamped record cannot yield a real wall-time span."""
    session_id = "single-record-session"
    _write_telemetry_records(
        brain_home,
        session_id,
        [{"v": 2, "kind": "session_start", "ts": "2026-08-26T00:00:00.000Z"}],
    )
    with pytest.raises(BrainError, match="No measurable telemetry"):
        credit.arm_from_telemetry(
            brain_home,
            session_id,
            success=True,
            verification=_verification(),
            regressions=_regressions(0),
        )


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
