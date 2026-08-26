"""Focused tests for the read-only P3.15 portfolio observation boundary."""

import json
import pytest

from second_brain import skillforge
from pathlib import Path

from second_brain import paths
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
