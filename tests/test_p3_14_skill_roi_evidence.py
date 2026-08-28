"""Tests for P3.14 Skill ROI evidence composition (plan §3 P3.14).

record_from_evidence() must compose existing P3.10/P3.11/P3.13 evidence into
one version-bound Skill ROI record, never fabricate a missing measurement,
and reject stale (version-mismatched) evidence.
"""

import hashlib
import json

import pytest

from second_brain import credit, gardener, paths, skillforge
from second_brain.gardener import MeasurementState, SkillHealth, SkillROILedger

SKILL = "roi-probe-skill"


def _make_skill(home, name=SKILL, level="shadow", body="content"):
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"# {title}\n\n- {body}"
        for title in (
            "Purpose",
            "Positive Triggers",
            "Negative Triggers",
            "Inputs",
            "Procedure",
            "Tools",
            "Safety",
            "Verification",
            "Output",
            "References",
        )
    )
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\nstatus: {level}\nversion: 1\n---\n\n{sections}\n", encoding="utf-8"
    )
    return directory


def _seed_radar_candidate(home, candidate_id, expected_benefit_tokens):
    radar_dir = home / "state" / "radar"
    radar_dir.mkdir(parents=True, exist_ok=True)
    path = radar_dir / "candidates.json"
    candidates = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    candidates.append(
        {
            "candidate_id": candidate_id,
            "candidate_type": "REPEATED_READ",
            "status": "candidate",
            "promotion_eligible": False,
            "expected_benefit_tokens": expected_benefit_tokens,
            "reason_codes": ["REPEATED_READ"],
            "telemetry_evidence_refs": [],
        }
    )
    path.write_text(json.dumps(candidates, indent=2) + "\n", encoding="utf-8")


def _passing_evaluation_payload(baseline_total, candidate_total):
    baseline_output = 50
    candidate_output = 50
    return {
        "evaluation_id": f"eval-{SKILL}",
        "task_id": "task-roi-probe",
        "task_hash": "t" * 64,
        "repository_state_hash": "r" * 64,
        "baseline": {
            "input_tokens": baseline_total - baseline_output,
            "output_tokens": baseline_output,
        },
        "candidate": {
            "input_tokens": candidate_total - candidate_output,
            "output_tokens": candidate_output,
        },
        "quality": {
            "correctness": True,
            "requirements": True,
            "protected_values": True,
            "regressions": False,
            "verification": True,
        },
        "gates": {
            "trigger": {"failed": 0},
            "workflow": {"structural": True, "failed": 0},
            "regression": {"regression": False, "failed": 0},
            "security": {"passed": True},
        },
    }


def _counterfactual_arm(run_id, total_tokens):
    return {
        "run_id": run_id,
        "success": True,
        "tokens": {
            "input": total_tokens - 20,
            "cache_read": 0,
            "cache_write": 0,
            "output": 20,
            "total": total_tokens,
            "reasoning": None,
        },
        "tool_calls": 1,
        "wall_time_ms": 100.0,
        "verification": {"outcome": "passed", "evidence_ref": "verify:x"},
        "regressions": {"count": 0, "evidence_ref": "pytest:x"},
    }


def _starting_state():
    return {
        "task_hash": "t" * 64,
        "repository_state_hash": "r" * 64,
        "requirements_hash": "q" * 64,
        "model_config_hash": "m" * 64,
        "available_tools_hash": "o" * 64,
        "environment_hash": "e" * 64,
    }


# ---------------------------------------------------------------------------
# Composition: estimate + measurement
# ---------------------------------------------------------------------------


def test_record_from_evidence_composes_estimate_and_p3_11_measurement(brain_home):
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="radar", source_ref="candidate-roi-1", owner="steward"
    )
    _seed_radar_candidate(brain_home, "candidate-roi-1", expected_benefit_tokens=600)
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 700))

    ledger = SkillROILedger(brain_home)
    record = ledger.record_from_evidence(brain_home, SKILL)

    assert record["measurement_state"] == MeasurementState.MEASURED.value
    assert record["estimated_tokens_saved"] == 600
    assert record["estimate_evidence_ref"] == "radar:candidate-roi-1"
    assert record["measured_tokens_saved"] == 300  # 1000 - 700
    assert record["measured_evidence_ref"].startswith("evaluation:")
    assert record["candidate_evaluation_ref"]
    assert record["estimation_error"] == 300 - 600
    assert record["comparison"] == "estimate_optimistic"  # measured fell well short of estimate
    assert record["record_id"] is not None
    assert record["economics"] == {
        "model_calls": 0,
        "tool_calls": 0,
        "tokens": 0,
        "bookkeeping_wall_time_ms": record["economics"]["bookkeeping_wall_time_ms"],
    }

    summary = ledger.get_summary(SKILL)
    assert summary.invocations == 1
    assert summary.net_tokens_saved == 300


def test_record_from_evidence_is_idempotent_for_same_evidence(brain_home):
    """Composing the same immutable evidence file twice must not
    double-count the measurement in the ledger arithmetic."""
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="frontier", source_ref="manual", owner="steward"
    )
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 700))

    ledger = SkillROILedger(brain_home)
    first = ledger.record_from_evidence(brain_home, SKILL)
    second = ledger.record_from_evidence(brain_home, SKILL)

    assert first["record_id"] == second["record_id"]
    summary = ledger.get_summary(SKILL)
    assert summary.invocations == 1
    assert summary.net_tokens_saved == 300  # not 600


def test_record_from_evidence_prefers_counterfactual_over_evaluation(brain_home):
    """P3.13 remains the authority for observed measurements; P3.14 must
    prefer it over the older P3.11 single-evaluation figure when both
    exist for the current version."""
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="frontier", source_ref="manual", owner="steward"
    )
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 700))
    _skill_path = skillforge.skill_path(brain_home, SKILL)
    assert _skill_path is not None
    skill_version = skillforge.lifecycle_content_hash(_skill_path)

    credit.counterfactual_result(
        brain_home,
        evaluation_id="eval-cf-1",
        intervention_type="skill",
        intervention_id=SKILL,
        intervention_hash=skill_version,
        starting_state=_starting_state(),
        with_arm=_counterfactual_arm("with-1", 400),
        without_arm=_counterfactual_arm("without-1", 900),
    )

    ledger = SkillROILedger(brain_home)
    record = ledger.record_from_evidence(brain_home, SKILL)

    assert (
        record["measured_tokens_saved"] == 500
    )  # 900 - 400, from counterfactual, not 300 from eval
    assert record["measured_evidence_ref"].startswith("counterfactual:")
    assert record["candidate_evaluation_ref"] is None  # counterfactual path doesn't set this


# ---------------------------------------------------------------------------
# Negative controls: no fabrication, staleness rejection
# ---------------------------------------------------------------------------


def test_record_from_evidence_rejects_stale_evaluation_version(brain_home):
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="radar", source_ref="candidate-roi-2", owner="steward"
    )
    _seed_radar_candidate(brain_home, "candidate-roi-2", expected_benefit_tokens=400)
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 700))

    # Skill content changes after evaluation: the recorded evaluation is now
    # bound to a version that no longer exists.
    skill_file = skillforge.skill_path(brain_home, SKILL)
    assert skill_file is not None
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "\n# Extra\n\nchanged\n", encoding="utf-8"
    )

    ledger = SkillROILedger(brain_home)
    record = ledger.record_from_evidence(brain_home, SKILL)

    # Stale evaluation rejected; estimate still available -> estimated_only.
    assert record["measured_tokens_saved"] is None
    assert record["measurement_state"] == MeasurementState.ESTIMATED_ONLY.value
    assert record["estimated_tokens_saved"] == 400
    assert record["comparison"] == "inconclusive"
    assert record["record_id"] is None  # estimated_only never inserts a ledger row


def test_record_from_evidence_accepts_legacy_raw_hash_evaluation(brain_home):
    """A real pre-P3.12 evaluation.json bound with the OLD raw (non
    lifecycle-normalized) content hash must still be accepted as current
    when the file bytes genuinely haven't changed — this is the exact
    situation the real read-reuse skill is in."""
    directory = _make_skill(brain_home, level="candidate")
    skill_file = directory / "SKILL.md"
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="frontier", source_ref="manual", owner="steward"
    )
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 850))

    # Simulate a pre-P3.12 evaluation: its stored hash used the raw
    # (non-lifecycle-normalized) scheme.
    evaluation_path = directory / "evaluation.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    raw_hash = hashlib.sha256(skill_file.read_bytes()).hexdigest()
    evaluation["candidate_content_sha256"] = raw_hash
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")

    ledger = SkillROILedger(brain_home)
    record = ledger.record_from_evidence(brain_home, SKILL)

    assert record["measurement_state"] == MeasurementState.MEASURED.value
    assert record["measured_tokens_saved"] == 150


def test_record_from_evidence_estimated_only_not_counted_as_measured(brain_home):
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="radar", source_ref="candidate-roi-3", owner="steward"
    )
    _seed_radar_candidate(brain_home, "candidate-roi-3", expected_benefit_tokens=250)
    # No evaluation, no counterfactual result recorded at all.

    ledger = SkillROILedger(brain_home)
    record = ledger.record_from_evidence(brain_home, SKILL)

    assert record["measurement_state"] == MeasurementState.ESTIMATED_ONLY.value
    assert record["estimated_tokens_saved"] == 250
    assert record["measured_tokens_saved"] is None
    assert record["record_id"] is None
    summary = ledger.get_summary(SKILL)
    assert summary.invocations == 0  # estimated_only never presented as measured ROI


def test_record_from_evidence_unavailable_when_nothing_exists(brain_home):
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="frontier", source_ref="manual", owner="steward"
    )
    # No radar lineage, no evaluation, no counterfactual result.

    ledger = SkillROILedger(brain_home)
    record = ledger.record_from_evidence(brain_home, SKILL)

    assert record["measurement_state"] == MeasurementState.UNAVAILABLE.value
    assert record["estimated_tokens_saved"] is None
    assert record["measured_tokens_saved"] is None
    assert record["comparison"] == "inconclusive"
    assert record["record_id"] is None


def test_record_from_evidence_measured_zero_is_valid_not_unavailable(brain_home):
    """A legitimately measured zero must remain a valid 0 measurement, not
    be reclassified as unavailable/unknown."""
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="frontier", source_ref="manual", owner="steward"
    )
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 1000))

    ledger = SkillROILedger(brain_home)
    record = ledger.record_from_evidence(brain_home, SKILL)

    assert record["measurement_state"] == MeasurementState.MEASURED.value
    assert record["measured_tokens_saved"] == 0
    assert record["record_id"] is not None
    assert record["comparison"] == "measured_approximately_zero"
    summary = ledger.get_summary(SKILL)
    assert summary.invocations == 1
    assert summary.total_tokens_saved == 0


def test_record_from_evidence_unknown_skill_raises(brain_home):
    from second_brain.errors import BrainError

    ledger = SkillROILedger(brain_home)
    with pytest.raises(BrainError, match="No skill"):
        ledger.record_from_evidence(brain_home, "ghost-skill")


# ---------------------------------------------------------------------------
# Comparison classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("estimated", "measured", "state", "expected"),
    [
        (100, -50, MeasurementState.MEASURED, "measured_negative"),
        (100, 10, MeasurementState.MEASURED, "measured_approximately_zero"),
        (100, 500, MeasurementState.MEASURED, "estimate_pessimistic"),
        (500, 100, MeasurementState.MEASURED, "estimate_optimistic"),
        (500, 480, MeasurementState.MEASURED, "estimate_accurate"),
        (None, 300, MeasurementState.MEASURED, "inconclusive"),
        (100, None, MeasurementState.ESTIMATED_ONLY, "inconclusive"),
        (None, None, MeasurementState.UNAVAILABLE, "inconclusive"),
    ],
)
def test_classify_comparison_variants(estimated, measured, state, expected):
    assert gardener._classify_comparison(estimated, measured, state) == expected


# ---------------------------------------------------------------------------
# Existing arithmetic and health classification preserved
# ---------------------------------------------------------------------------


def test_get_summary_excludes_non_measured_rows(brain_home):
    other = "roi-probe-skill-two"
    _make_skill(brain_home, name=other)
    skillforge.bind_candidate(
        brain_home, other, source_type="radar", source_ref="candidate-roi-4", owner="steward"
    )
    _seed_radar_candidate(brain_home, "candidate-roi-4", expected_benefit_tokens=999)
    # Only an estimate exists for `other`.

    _make_skill(brain_home, name=SKILL)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="frontier", source_ref="manual", owner="steward"
    )
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 400))

    ledger = SkillROILedger(brain_home)
    ledger.record_from_evidence(brain_home, other)  # estimated_only, no row
    ledger.record_from_evidence(brain_home, SKILL)  # measured, one row

    all_summaries = {s.skill_name: s for s in ledger.list_all()}
    assert other not in all_summaries
    assert SKILL in all_summaries
    assert all_summaries[SKILL].net_tokens_saved == 600
    assert all_summaries[SKILL].health == SkillHealth.HEALTHY


def test_record_usage_backward_compatible_defaults_to_measured(brain_home):
    """Existing record_usage() callers (e.g. test_p3_gaps_live_integration.py)
    keep their exact original behavior: unnamed positional args, always
    counted as a measured row."""
    ledger = SkillROILedger(brain_home)
    ledger.record_usage(
        "legacy-skill", "sess-1", tokens_invested=100, tokens_saved=500, success=True
    )
    summary = ledger.get_summary("legacy-skill")
    assert summary.invocations == 1
    assert summary.net_tokens_saved == 400
    assert summary.health == SkillHealth.HEALTHY


# ---------------------------------------------------------------------------
# No promotion coupling
# ---------------------------------------------------------------------------


def test_record_from_evidence_never_mutates_skill_lifecycle_or_promotes(brain_home):
    from second_brain import promotion

    _make_skill(brain_home, level="candidate")
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="frontier", source_ref="manual", owner="steward"
    )
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(1000, 200))

    ledger = SkillROILedger(brain_home)
    ledger.record_from_evidence(brain_home, SKILL)

    # Still exactly at candidate level; nothing promoted, no promotion record
    # was written as a side effect of ROI evidence composition.
    assert promotion._level_of(brain_home, SKILL) == "candidate"
    assert not (brain_home / "state" / "promotions").exists() or not list(
        (brain_home / "state" / "promotions").glob(f"{SKILL}-*.json")
    )


def test_gardener_audit_portfolio_uses_real_composed_evidence(brain_home):
    _make_skill(brain_home)
    skillforge.bind_candidate(
        brain_home, SKILL, source_type="radar", source_ref="candidate-roi-5", owner="steward"
    )
    _seed_radar_candidate(brain_home, "candidate-roi-5", expected_benefit_tokens=200)
    skillforge.record_evaluation(brain_home, SKILL, _passing_evaluation_payload(500, 900))

    ledger = SkillROILedger(brain_home)
    ledger.record_from_evidence(brain_home, SKILL)

    gardener_instance = gardener.SkillGardener(brain_home)
    gardener_instance.ledger = ledger
    audit = gardener_instance.audit_portfolio()

    assert audit["total_skills_tracked"] == 1
    assert audit["degraded_count"] == 1  # net_tokens_saved = 500-900 = -400, negative
    assert audit["degraded_skills"][0]["skill_name"] == SKILL
    assert audit["degraded_skills"][0]["net_tokens_saved"] == -400
