"""Focused tests for the read-only P3.15 portfolio observation boundary."""

import json
import shutil
from pathlib import Path

import pytest

from second_brain import paths, skillforge
from second_brain.errors import BrainError
from second_brain.gardener import SkillGardener



def _make_skill(home: Path, name: str, level: str) -> Path:
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n- verified content"
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
        f"---\nname: {name}\nstatus: {level}\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    return directory


def _lifecycle_snapshot(home: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for level_dir in paths.SKILL_LEVEL_DIRS.values():
        root = home / level_dir
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    snapshot[path.relative_to(home).as_posix()] = path.read_bytes()
    promotions = home / "state" / "promotions"
    if promotions.is_dir():
        for path in promotions.rglob("*"):
            if path.is_file():
                snapshot[path.relative_to(home).as_posix()] = path.read_bytes()
    return snapshot


def test_observe_portfolio_returns_all_lifecycle_skills_and_economics(brain_home):
    _make_skill(brain_home, "candidate-one", "candidate")
    _make_skill(brain_home, "shadow-one", "shadow")
    _make_skill(brain_home, "active-one", "active")

    result = SkillGardener(brain_home).observe_portfolio()

    assert {item["skill_name"] for item in result["skills"]} == {
        "candidate-one",
        "shadow-one",
        "active-one",
    }
    assert set(result) == {"skills", "issues", "recommendations", "economics"}
    assert result["economics"]["model_calls"] == 0
    assert result["economics"]["tool_calls"] == 0
    assert result["economics"]["tokens"] == 0
    assert result["economics"]["maintenance_work_performed"] == 0
    assert result["economics"]["records_inspected"] >= 3
    assert result["economics"]["local_processing_time_ms"] >= 0
    assert len(result["recommendations"]) == 3


def test_observe_portfolio_composes_bounded_evidence_and_issue_shape(brain_home):
    directory = _make_skill(brain_home, "bounded-skill", "candidate")
    (directory / "candidate-binding.json").write_text(
        json.dumps(
            {
                "candidate_id": "candidate-1",
                "evaluation_state": "passed",
                "evidence_refs": ["radar:candidate-1", "telemetry:window-1"],
                "source_ref": "radar:candidate-1",
            }
        ),
        encoding="utf-8",
    )
    (directory / "evaluation.json").write_text(
        json.dumps({"evaluation_id": "eval-1", "candidate_id": "candidate-1"}),
        encoding="utf-8",
    )

    result = SkillGardener(brain_home).observe_portfolio()
    skill = result["skills"][0]

    assert skill["lifecycle_state"] == "candidate"
    assert skill["skill_version"] == "1"
    assert len(skill["content_hash"]) == 64
    assert skill["binding_present"] is True
    assert skill["evaluation_present"] is True
    assert "radar:candidate-1" in skill["evidence_refs"]
    assert "verified content" not in json.dumps(result)
    assert all(
        {
            "issue_id",
            "issue_type",
            "condition_code",
            "skill_name",
            "skill_version",
            "lifecycle_state",
            "reason_codes",
            "evidence_refs",
            "measurement_state",
        }
        <= issue.keys()
        for issue in result["issues"]
    )


def test_observe_portfolio_does_not_mutate_lifecycle_or_promotion_state(brain_home):
    _make_skill(brain_home, "stable-skill", "shadow")
    before = _lifecycle_snapshot(brain_home)
    gardener = SkillGardener(brain_home)

    gardener.observe_portfolio()

    assert _lifecycle_snapshot(brain_home) == before


def test_observe_portfolio_bounds_binding_state_metadata(brain_home):
    directory = _make_skill(brain_home, "oversized-binding", "candidate")
    (directory / "candidate-binding.json").write_text(
        json.dumps({"evaluation_state": "x" * 10_000}),
        encoding="utf-8",
    )

    result = SkillGardener(brain_home).observe_portfolio()

    assert len(result["skills"][0]["binding_state"]["evaluation_state"]) <= 256


def _write_binding(directory: Path, payload: dict) -> None:
    (directory / "candidate-binding.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("condition_code", "issue_type"),
    [
        ("evidence_stale", "stale"),
        ("dead_skill", "broken"),
        ("capability_overlap", "duplicate"),
        ("false_trigger", "broken"),
        ("measured_zero_use", "unused"),
        ("measured_negative", "negative_roi"),
        ("exact_duplicate", "duplicate"),
        ("scope_too_broad", "broken"),
        ("scope_too_narrow", "broken"),
        ("model_specific_quirk", "broken"),
    ],
)
def test_condition_codes_are_differentiated(brain_home, condition_code, issue_type):
    directory = _make_skill(brain_home, f"condition-{condition_code}", "shadow")
    if condition_code == "exact_duplicate":
        _make_skill(brain_home, "condition-exact-duplicate-peer", "shadow")
    if condition_code == "evidence_stale":
        _write_binding(directory, {"candidate_content_sha256": "stale"})
    elif condition_code == "dead_skill":
        _write_binding(
            directory,
            {"condition_evidence": {"dead_skill": {"detected": True}}},
        )
    elif condition_code == "capability_overlap":
        _write_binding(
            directory,
            {
                "condition_evidence": {
                    "capability_overlap": {
                        "detected": True,
                        "material": True,
                        "with": "other-skill",
                    }
                }
            },
        )
    elif condition_code == "measured_zero_use":
        _write_binding(directory, {"usage": {"invocations": 0, "window": "w1"}})
    elif condition_code == "measured_negative":
        _write_binding(directory, {})
        evaluation = {
            "evaluation_id": "negative-eval",
            "candidate_content_sha256": skillforge.lifecycle_content_hash(
                directory / "SKILL.md"
            ),
            "roi": {"net_tokens_saved": -1},
        }
        (directory / "evaluation.json").write_text(
            json.dumps(evaluation), encoding="utf-8"
        )
    else:
        _write_binding(
            directory,
            {"condition_evidence": {condition_code: {"detected": True}}},
        )

    result = SkillGardener(brain_home).observe_portfolio()
    matches = [
        issue for issue in result["issues"] if issue["condition_code"] == condition_code
    ]
    assert matches
    assert all(issue["issue_type"] == issue_type for issue in matches)


def test_missing_usage_is_unavailable_not_measured_zero(brain_home):
    _make_skill(brain_home, "unknown-use", "shadow")

    result = SkillGardener(brain_home).observe_portfolio()

    assert not any(i["condition_code"] == "measured_zero_use" for i in result["issues"])
    skill = result["skills"][0]
    assert skill["usage_state"] == "unknown"
    assert "usage_unavailable:unknown-use" in skill["usage_evidence_refs"]
    assert not any(i["issue_type"] == "unused" for i in result["issues"])


def test_estimated_or_unavailable_roi_is_not_negative(brain_home):
    directory = _make_skill(brain_home, "estimated-only", "candidate")
    _write_binding(
        directory,
        {"source_type": "radar", "source_ref": "candidate-without-measurement"},
    )
    (brain_home / "state" / "radar").mkdir(parents=True)
    (brain_home / "state" / "radar" / "candidates.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "candidate-without-measurement",
                        "expected_benefit_tokens": 50,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = SkillGardener(brain_home).observe_portfolio()

    assert not any(
        i["condition_code"] == "measured_negative" for i in result["issues"]
    )


def test_exact_duplicate_is_not_capability_overlap(brain_home):
    first = _make_skill(brain_home, "same-one", "shadow")
    second = _make_skill(brain_home, "same-two", "shadow")
    _write_binding(
        first,
        {
            "condition_evidence": {
                "capability_overlap": {
                    "detected": True,
                    "material": True,
                    "with": "same-two",
                }
            }
        },
    )

    issues = SkillGardener(brain_home).observe_portfolio()["issues"]

    assert any(
        i["skill_name"] == "same-one" and i["condition_code"] == "capability_overlap"
        for i in issues
    )
    assert any(i["condition_code"] == "exact_duplicate" for i in issues)

    assert not any(
        i["skill_name"] == "same-two" and i["condition_code"] == "capability_overlap"
        for i in issues
    )

def test_superseded_requires_replacement_capability_evidence(brain_home):
    replacement = _make_skill(brain_home, "new-skill", "shadow")
    _write_binding(replacement, {"capability_hash": "cap-new"})
    directory = _make_skill(brain_home, "old-skill", "active")
    _write_binding(
        directory,
        {
            "replacement_ref": {
                "skill_name": "new-skill",
                "version": "1",
                "capability_hash": "cap-new",
                "evidence_refs": ["promotion:new-skill"],
            }
        },
    )

    result = SkillGardener(brain_home).observe_portfolio()
    superseded = [
        i for i in result["issues"] if i["condition_code"] == "superseded"
    ]

    assert superseded
    assert superseded[0]["issue_type"] == "superseded"
    assert superseded[0]["replacement_ref"]["skill_name"] == "new-skill"
    assert superseded[0]["evidence_refs"]
    
def test_superseded_accepts_nested_normalized_capability_hash(brain_home):
    replacement = _make_skill(brain_home, "nested-replacement", "shadow")
    _write_binding(replacement, {"capability_hash": "cap-nested"})
    old = _make_skill(brain_home, "nested-old", "shadow")
    _write_binding(
        old,
        {
            "replacement_ref": {
                "skill_name": "nested-replacement",
                "version": "1",
                "capability_evidence": {"normalized_hash": "cap-nested"},
            }
        },
    )

    issues = SkillGardener(brain_home).observe_portfolio()["issues"]

    assert any(
        i["skill_name"] == "nested-old" and i["condition_code"] == "superseded"
        for i in issues
    )


def test_stale_broken_and_superseded_refs_are_bounded(brain_home):
    stale = _make_skill(brain_home, "stale-ref", "shadow")
    broken = _make_skill(brain_home, "broken-ref", "shadow")
    superseded = _make_skill(brain_home, "superseded-ref", "shadow")
    replacement = _make_skill(brain_home, "replacement", "shadow")
    _write_binding(replacement, {"capability_hash": "z" * 256})
    _write_binding(
        stale,
        {
            "candidate_content_sha256": "x" * 10_000,
            "condition_evidence": {"false_trigger": {"detected": True}},
        },
    )
    _write_binding(
        broken,
        {
            "condition_evidence": {
                "false_trigger": {"detected": True, "evidence_refs": ["y" * 10_000]}
            }
        },
    )
    _write_binding(
        superseded,
        {
            "replacement_ref": {
                "skill_name": "replacement",
                "version": "1",
                "capability_hash": "z" * 256,
                "evidence_refs": ["q" * 10_000],
            }
        },
    )

    issues = SkillGardener(brain_home).observe_portfolio()["issues"]
    assert not any(
        i["skill_name"] == "stale-ref" and i["condition_code"] == "false_trigger"
        for i in issues
    )

    for code in ("evidence_stale", "false_trigger", "superseded"):
        matched = [i for i in issues if i["condition_code"] == code]
        assert matched
        assert all(len(ref) <= 256 for i in matched for ref in i["evidence_refs"])

def test_negative_roi_recommends_review_only():
    recommendation = SkillGardener(Path(".")).recommend_maintenance(
        {
            "issue_id": "skill:measured_negative",
            "issue_type": "negative_roi",
            "condition_code": "measured_negative",
            "skill_name": "skill",
            "skill_version": "1",
            "content_hash": "a" * 64,
            "lifecycle_state": "shadow",
            "evidence_refs": ["ledger:1"],
            "measurement_state": "measured",
        }
    )
    assert recommendation["action_recommended"] in {"repair", "no_action"}
    assert recommendation["action_recommended"] != "archive_retire"
    assert recommendation["action_authorized"] is False
    assert recommendation["action_executed"] is False


@pytest.mark.parametrize("condition_code", ["", "unknown"])
def test_keep_or_no_action_has_no_mutation(brain_home, condition_code):
    gardener = SkillGardener(brain_home)
    before = _lifecycle_snapshot(brain_home)
    observation = {
        "skill_name": "stable",
        "skill_version": "1",
        "content_hash": "b" * 64,
        "lifecycle_state": "shadow",
        "condition_code": condition_code,
        "issue_ids": [],
        "evidence_refs": ["observation:stable"],
    }
    recommendation = gardener.recommend_maintenance(observation)
    assert recommendation["action_recommended"] in {"keep", "no_action"}
    assert recommendation["action_authorized"] is False
    assert recommendation["action_executed"] is False
    assert _lifecycle_snapshot(brain_home) == before


def test_authorization_refuses_missing_gate_evidence(brain_home):
    directory = _make_skill(brain_home, "gated", "shadow")
    _write_binding(
        directory,
        {
            "owner": "owner-1",
            "condition_evidence": {
                "false_trigger": {"detected": True, "evidence_refs": ["eval:gated"]}
            },
        },
    )
    observation = next(
        issue
        for issue in SkillGardener(brain_home).observe_portfolio()["issues"]
        if issue["skill_name"] == "gated"
    )
    recommendation = SkillGardener(brain_home).recommend_maintenance(observation)
    with pytest.raises(BrainError, match="approval|non-regression|rollback"):
        SkillGardener(brain_home).authorize_maintenance(
            recommendation,
            actor="owner-1",
            approval_ref="",
            non_regression_ref="",
            rollback_ref="",
        )


def test_authorization_refuses_stale_skill_hash(brain_home):
    directory = _make_skill(brain_home, "stale-auth", "shadow")
    _write_binding(
        directory,
        {"owner": "owner-1", "condition_evidence": {"false_trigger": {"detected": True}}},
    )
    observation = next(
        issue
        for issue in SkillGardener(brain_home).observe_portfolio()["issues"]
        if issue["skill_name"] == "stale-auth"
    )
    recommendation = SkillGardener(brain_home).recommend_maintenance(observation)
    recommendation["content_hash"] = "0" * 64
    with pytest.raises(BrainError, match="hash|stale"):
        SkillGardener(brain_home).authorize_maintenance(
            recommendation,
            actor="owner-1",
            approval_ref="approval:1",
            non_regression_ref="verification:1",
            rollback_ref="rollback:1",
        )


def test_duplicate_authorization_requires_verified_survivor(brain_home):
    recommendation = SkillGardener(brain_home).recommend_maintenance(
        {
            "issue_id": "duplicate:exact",
            "issue_type": "duplicate",
            "condition_code": "exact_duplicate",
            "skill_name": "duplicate",
            "skill_version": "1",
            "content_hash": "c" * 64,
            "lifecycle_state": "shadow",
            "evidence_refs": ["capability:c"],
        }
    )
    assert recommendation["action_recommended"] == "merge"
    with pytest.raises(BrainError, match="survivor|replacement|skill"):
        SkillGardener(brain_home).authorize_maintenance(
            recommendation,
            actor="owner-1",
            approval_ref="approval:1",
            non_regression_ref="verification:1",
            rollback_ref="rollback:1",
        )


def test_active_retirement_requires_production_safety_evidence(brain_home):
    directory = _make_skill(brain_home, "active-auth", "active")
    recommendation = {
        "skill_name": "active-auth",
        "skill_version": "1",
        "content_hash": skillforge.lifecycle_content_hash(directory / "SKILL.md"),
        "lifecycle_state": "active",
        "action_recommended": "archive_retire",
        "issue_ids": ["active-auth:dead_skill"],
        "evidence_refs": ["audit:active-auth:cannot execute"],
    }
    with pytest.raises(BrainError, match="production|safety"):
        SkillGardener(brain_home).authorize_maintenance(
            recommendation,
            actor="owner-1",
            approval_ref="approval:1",
            non_regression_ref="verification:1",
            rollback_ref="rollback:1",
        )


def test_delegated_authorization_does_not_mutate(brain_home):
    directory = _make_skill(brain_home, "delegated", "shadow")
    _write_binding(
        directory,
        {"owner": "owner-1", "condition_evidence": {"false_trigger": {"detected": True}}},
    )
    gardener = SkillGardener(brain_home)
    observation = next(
        issue
        for issue in gardener.observe_portfolio()["issues"]
        if issue["skill_name"] == "delegated"
    )
    recommendation = gardener.recommend_maintenance(observation)
    before = _lifecycle_snapshot(brain_home)
    result = gardener.authorize_maintenance(
        recommendation,
        actor="owner-1",
        approval_ref="approval:1",
        non_regression_ref="verification:1",
        rollback_ref="rollback:1",
    )
    assert result["action_authorized"] is True
    assert result["action_executed"] is False
    assert result["authority"] == "skill-development/evaluation"
    persisted = (
        brain_home
        / "state"
        / "maintenance"
        / "authorizations"
        / f"{result['authorization_id']}.json"
    )
    assert json.loads(persisted.read_text(encoding="utf-8")) == result
    assert _lifecycle_snapshot(brain_home) == before


def test_negative_roi_precedes_retirement_issue_in_observation():
    recommendation = SkillGardener(Path(".")).recommend_maintenance(
        {
            "issues": [
                {
                    "issue_id": "skill:dead_skill",
                    "issue_type": "broken",
                    "condition_code": "dead_skill",
                    "skill_name": "skill",
                    "skill_version": "1",
                    "content_hash": "a" * 64,
                    "lifecycle_state": "shadow",
                    "evidence_refs": ["audit:dead"],
                },
                {
                    "issue_id": "skill:measured_negative",
                    "issue_type": "negative_roi",
                    "condition_code": "measured_negative",
                    "skill_name": "skill",
                    "skill_version": "1",
                    "content_hash": "a" * 64,
                    "lifecycle_state": "shadow",
                    "measurement_state": "measured",
                    "evidence_refs": ["ledger:negative"],
                },
            ]
        }
    )
    assert recommendation["action_recommended"] == "repair"


def test_archive_authorization_rejects_incomplete_current_issue_set(brain_home):
    directory = _make_skill(brain_home, "archive-gated", "shadow")
    _write_binding(
        directory,
        {
            "owner": "owner-1",
            "usage": {"invocations": 0, "measured": True, "evidence_refs": ["usage:1"]},
            "condition_evidence": {
                "false_trigger": {"detected": True, "evidence_refs": ["eval:1"]}
            },
        },
    )
    gardener = SkillGardener(brain_home)
    issue = next(
        issue
        for issue in gardener.observe_portfolio()["issues"]
        if issue["skill_name"] == "archive-gated" and issue["condition_code"] == "false_trigger"
    )
    recommendation = {
        "skill_name": "archive-gated",
        "skill_version": issue["skill_version"],
        "content_hash": issue["content_hash"],
        "lifecycle_state": "shadow",
        "action_recommended": "archive_retire",
        "issue_ids": [issue["issue_id"]],
        "evidence_refs": issue["evidence_refs"],
        "archive_destination": "archive:archive-gated",
    }
    with pytest.raises(BrainError, match="complete current issue set"):
        gardener.authorize_maintenance(
            recommendation,
            actor="owner-1",
            approval_ref="approval:1",
            non_regression_ref="verification:1",
            rollback_ref="rollback:1",
        )


def test_merge_rejects_self_survivor(brain_home):
    directory = _make_skill(brain_home, "self-merge", "shadow")
    _write_binding(
        directory,
        {
            "owner": "owner-1",
            "condition_evidence": {"false_trigger": {"detected": True}},
        },
    )
    gardener = SkillGardener(brain_home)
    issue = next(
        issue
        for issue in gardener.observe_portfolio()["issues"]
        if issue["skill_name"] == "self-merge"
    )
    recommendation = gardener.recommend_maintenance(issue)
    recommendation["action_recommended"] = "merge"
    recommendation["replacement_ref"] = {
        "skill_name": "self-merge",
        "skill_version": "1",
        "capability_hash": "self",
    }
    with pytest.raises(BrainError, match="differ"):
        gardener.authorize_maintenance(
            recommendation,
            actor="owner-1",
            approval_ref="approval:1",
            non_regression_ref="verification:1",
            rollback_ref="rollback:1",
        )


def test_merge_rejects_unbound_stale_survivor_artifact(brain_home):
    source = _make_skill(brain_home, "merge-source", "shadow")
    survivor = _make_skill(brain_home, "merge-survivor", "shadow")
    _write_binding(source, {"owner": "owner-1"})
    gardener = SkillGardener(brain_home)
    issue = next(
        issue
        for issue in gardener.observe_portfolio()["issues"]
        if issue["skill_name"] == "merge-source"
        and issue["condition_code"] == "exact_duplicate"
    )
    recommendation = gardener.recommend_maintenance(issue)
    replacement = {
        "skill_name": "merge-survivor",
        "skill_version": "1",
        "capability_hash": "not-bound-to-current-artifact",
    }
    with pytest.raises(BrainError, match="capability"):
        gardener.authorize_maintenance(
            recommendation,
            actor="owner-1",
            approval_ref="approval:1",
            non_regression_ref="verification:1",
            rollback_ref="rollback:1",
            replacement=replacement,
        )


def test_merge_authorization_delegates_content_lifecycle(brain_home):
    source = _make_skill(brain_home, "merge-source-valid", "shadow")
    _make_skill(brain_home, "merge-survivor-valid", "shadow")
    _write_binding(source, {"owner": "owner-1"})
    gardener = SkillGardener(brain_home)
    issue = next(
        issue
        for issue in gardener.observe_portfolio()["issues"]
        if issue["skill_name"] == "merge-source-valid"
        and issue["condition_code"] == "exact_duplicate"
    )
    capability_ref = next(
        ref for ref in issue["evidence_refs"] if ref.startswith("capability:")
    )
    recommendation = gardener.recommend_maintenance(issue)
    result = gardener.authorize_maintenance(
        recommendation,
        actor="owner-1",
        approval_ref="approval:1",
        non_regression_ref="verification:1",
        rollback_ref="rollback:1",
        replacement={
            "skill_name": "merge-survivor-valid",
            "skill_version": "1",
            "capability_hash": capability_ref.removeprefix("capability:"),
        },
    )
    assert result["authority"] == "skill-lifecycle/content"
    assert result["action_executed"] is False

def _authorized_retirement(
    brain_home: Path,
    name: str,
    level: str = "shadow",
    archive_destination: Path | None = None,
) -> dict:
    directory = brain_home / paths.SKILL_LEVEL_DIRS[level] / name
    if not directory.exists():
        directory = _make_skill(brain_home, name, level)
    _write_binding(
        directory,
        {
            "owner": "owner-1",
            "condition_evidence": {
                "dead_skill": {
                    "detected": True,
                    "evidence_refs": [f"audit:{name}:dead"],
                }
            },
        },
    )
    gardener = SkillGardener(brain_home)
    observation = gardener.observe_portfolio()
    issue_ids = [
        issue["issue_id"]
        for issue in observation["issues"]
        if issue["skill_name"] == name
    ]
    evidence_refs = [
        ref
        for issue in observation["issues"]
        if issue["skill_name"] == name
        for ref in issue["evidence_refs"]
    ]
    recommendation = {
        "skill_name": name,
        "skill_version": "1",
        "content_hash": skillforge.lifecycle_content_hash(directory / "SKILL.md"),
        "lifecycle_state": level,
        "action_recommended": "archive_retire",
        "issue_ids": issue_ids,
        "evidence_refs": evidence_refs,
        "archive_destination": str(
            archive_destination or (brain_home / "archive")
        ),
    }
    if level == "active":
        recommendation["production_safety_ref"] = "production-safety:1"
    return gardener.authorize_maintenance(
        recommendation,
        actor="owner-1",
        approval_ref="approval:1",
        non_regression_ref="verification:1",
        rollback_ref="rollback:1",
    )


def test_archive_retirement_orders_copy_verify_record_before_source_mutation(brain_home, monkeypatch):
    source = _make_skill(brain_home, "ordered", "shadow")
    original = (source / "SKILL.md").read_bytes()
    authorization = _authorized_retirement(brain_home, "ordered")
    gardener = SkillGardener(brain_home)
    events: list[str] = []
    original_persist = gardener._persist_retirement_record

    def persist(record):
        events.append("record")
        assert source.exists()
        assert Path(record["archive_location"]).read_bytes() == original
        return original_persist(record)

    monkeypatch.setattr(gardener, "_persist_retirement_record", persist)
    result = gardener.execute_maintenance(authorization)
    assert events == ["record"]
    assert not source.exists()
    archive = Path(result["archive_location"])
    assert archive.read_bytes() == original
    assert result["action_executed"] is True
    persisted = (
        brain_home
        / "state"
        / "maintenance"
        / "retirements"
        / f"{result['retirement_record_id']}.json"
    )
    assert persisted.is_file()
    record = json.loads(persisted.read_text(encoding="utf-8"))
    assert {
        "retirement_record_id",
        "skill_name",
        "skill_version",
        "content_hash",
        "owner",
        "retirement_reason",
        "issue_ids",
        "evidence_refs",
        "previous_lifecycle_state",
        "archive_location",
        "archive_reference",
        "rollback_ref",
        "restore_reference",
        "timestamp",
    } <= record.keys()


def test_archive_copy_failure_preserves_source_and_cleans_staging(brain_home, monkeypatch):
    source = _make_skill(brain_home, "copy-fails", "shadow")
    original = (source / "SKILL.md").read_bytes()
    authorization = _authorized_retirement(brain_home, "copy-fails")

    def fail_copy(*args, **kwargs):
        raise OSError("copy failed")
    monkeypatch.setattr("second_brain.gardener.shutil.copytree", fail_copy)
    with pytest.raises(BrainError, match="archive|copy"):
        SkillGardener(brain_home).execute_maintenance(authorization)

    assert source.exists()
    assert (source / "SKILL.md").read_bytes() == original
    archive_root = brain_home / "archive"
    if archive_root.exists():
        assert not list(archive_root.rglob("*"))


def test_retirement_record_failure_preserves_source(brain_home, monkeypatch):
    source = _make_skill(brain_home, "record-fails", "shadow")
    original = (source / "SKILL.md").read_bytes()
    authorization = _authorized_retirement(brain_home, "record-fails")

    def fail_record(self, record):
        raise BrainError("record failed")

    monkeypatch.setattr(SkillGardener, "_persist_retirement_record", fail_record)
    with pytest.raises(BrainError, match="record"):
        SkillGardener(brain_home).execute_maintenance(authorization)
    assert source.exists()
    assert (source / "SKILL.md").read_bytes() == original
    archive_root = brain_home / "archive"
    if archive_root.exists():
        assert not list(archive_root.rglob("*"))

def test_archive_hash_mismatch_preserves_source(brain_home, monkeypatch):
    source = _make_skill(brain_home, "hash-fails", "shadow")
    original = (source / "SKILL.md").read_bytes()
    authorization = _authorized_retirement(brain_home, "hash-fails")
    original_hash = skillforge.lifecycle_content_hash

    def mismatched_hash(path):
        if (
            path.parent.name.startswith(".retirement")
            or path.parent.parent.name.startswith("retirement")
        ):
            return "0" * 64
        return original_hash(path)
    monkeypatch.setattr(
        "second_brain.gardener.skillforge.lifecycle_content_hash", mismatched_hash
    )
    with pytest.raises(BrainError, match="hash|verif"):
        SkillGardener(brain_home).execute_maintenance(authorization)
    assert source.exists()
    assert (source / "SKILL.md").read_bytes() == original
def test_archive_destination_inside_source_preserves_source(brain_home):
    source = _make_skill(brain_home, "overlap", "shadow")
    authorization = _authorized_retirement(
        brain_home, "overlap", archive_destination=source / "nested"
    )
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    with pytest.raises(BrainError, match="overlaps"):
        SkillGardener(brain_home).execute_maintenance(authorization)
    assert source.exists()
    assert {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    } == before
    assert not (source / "nested").exists()



def test_restore_returns_byte_identical_artifact_and_refuses_overwrite(brain_home):
    source = _make_skill(brain_home, "restore-me", "shadow")
    authorization = _authorized_retirement(brain_home, "restore-me")
    original_files = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    gardener = SkillGardener(brain_home)
    result = gardener.execute_maintenance(authorization)
    restored = gardener.restore_retirement(result["retirement_record_id"])
    restored_root = Path(restored["restored_path"])
    assert {
        path.relative_to(restored_root).as_posix(): path.read_bytes()
        for path in restored_root.rglob("*")
        if path.is_file()
    } == original_files
    with pytest.raises(BrainError, match="already exists"):
        gardener.restore_retirement(result["retirement_record_id"])

def test_executed_authorization_cannot_be_replayed_after_restore(brain_home):
    gardener = SkillGardener(brain_home)
    authorization = _authorized_retirement(brain_home, "replay")
    result = gardener.execute_maintenance(authorization)
    restored = gardener.restore_retirement(result["retirement_record_id"])
    shutil.rmtree(restored["restored_path"])
    with pytest.raises(BrainError, match="authorization|stale|current"):
        gardener.execute_maintenance(authorization)

def test_source_removal_failure_leaves_authorization_retryable(brain_home, monkeypatch):
    source = _make_skill(brain_home, "remove-fails", "shadow")
    authorization = _authorized_retirement(brain_home, "remove-fails")
    original_files = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    real_rename = Path.rename

    def fail_source(path, target):
        if path == source:
            raise OSError("remove failed")
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_source)
    with pytest.raises(BrainError, match="source removal|remove"):
        SkillGardener(brain_home).execute_maintenance(authorization)
    assert source.exists()
    assert {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    } == original_files
    auth_path = (
        brain_home
        / "state"
        / "maintenance"
        / "authorizations"
        / f"{authorization['authorization_id']}.json"
    )
    recovered = json.loads(auth_path.read_text(encoding="utf-8"))
    assert recovered["action_executed"] is False
    assert "execution_state" not in recovered
    monkeypatch.setattr(Path, "rename", real_rename)
    result = SkillGardener(brain_home).execute_maintenance(authorization)
    assert result["action_executed"] is True

def test_atomic_source_mutation_survives_partial_delete_scenario(brain_home, monkeypatch):
    source = _make_skill(brain_home, "atomic-remove", "shadow")
    authorization = _authorized_retirement(brain_home, "atomic-remove")
    original_files = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    real_rmtree = shutil.rmtree
    partial_delete_called = False

    def partial_delete(path, *args, **kwargs):
        nonlocal partial_delete_called
        if Path(path) == source:
            partial_delete_called = True
            (source / "SKILL.md").unlink()
            raise OSError("partial delete")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("second_brain.gardener.shutil.rmtree", partial_delete)
    gardener = SkillGardener(brain_home)
    result = gardener.execute_maintenance(authorization)
    assert partial_delete_called is False
    restored = gardener.restore_retirement(result["retirement_record_id"])
    restored_root = Path(restored["restored_path"])
    assert {
        path.relative_to(restored_root).as_posix(): path.read_bytes()
        for path in restored_root.rglob("*")
        if path.is_file()
    } == original_files


def test_restore_requires_complete_retirement_record(brain_home):
    gardener = SkillGardener(brain_home)
    result = gardener.execute_maintenance(_authorized_retirement(brain_home, "record-shape"))
    record_path = (
        brain_home
        / "state"
        / "maintenance"
        / "retirements"
        / f"{result['retirement_record_id']}.json"
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("owner")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(BrainError, match="incomplete"):
        gardener.restore_retirement(result["retirement_record_id"])


def test_active_retirement_execution_requires_production_safety_approval(brain_home):
    authorization = _authorized_retirement(brain_home, "active-unsafe", "active")
    authorization.pop("production_safety_ref", None)
    with pytest.raises(BrainError, match="production|safety"):
        SkillGardener(brain_home).execute_maintenance(authorization)


def test_delegated_execution_returns_metadata_without_mutating(brain_home):
    source = _make_skill(brain_home, "delegate-exec", "shadow")
    _write_binding(source, {"owner": "owner-1", "condition_evidence": {"false_trigger": {"detected": True, "evidence_refs": ["eval:delegate"]}}})
    gardener = SkillGardener(brain_home)
    issue = next(i for i in gardener.observe_portfolio()["issues"] if i["skill_name"] == "delegate-exec")
    recommendation = gardener.recommend_maintenance(issue)
    authorization = gardener.authorize_maintenance(
        recommendation,
        actor="owner-1",
        approval_ref="approval:1",
        non_regression_ref="verification:1",
        rollback_ref="rollback:1",
    )
    before = _lifecycle_snapshot(brain_home)
    result = gardener.execute_maintenance(authorization)
    assert result["action_recommended"] == "repair"
    assert result["action_executed"] is False
    assert result["delegated_to"] == "skill-development/evaluation"
    assert _lifecycle_snapshot(brain_home) == before
