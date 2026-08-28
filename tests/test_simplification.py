"""Focused P3.5 Simplification Review contract and debt lifecycle tests."""

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from second_brain.errors import BrainError
from second_brain.simplification import (
    SimplificationOutcome,
    SimplificationReview,
    canonical_task_body_sha256,
    record_review,
)


def _review(outcome: SimplificationOutcome, *, debt_ref: str | None = None) -> SimplificationReview:
    return SimplificationReview(
        review_id="review-001",
        project_id="second-brain",
        task_id="task-001",
        session_id="session-001",
        outcome=outcome,
        reason_code="duplicate-wrapper",
        affected_hashes=["a" * 64],
        changed_hashes=["b" * 64] if outcome is SimplificationOutcome.SIMPLIFY else [],
        deferred_hashes=["c" * 64] if outcome is SimplificationOutcome.DEFER else [],
        debt_ref=debt_ref,
        verification="passed",
        metrics={"loc_before": 12, "loc_after": 8},
    )


def test_semantic_task_body_hash_is_deterministic_before_augmentation() -> None:
    task = "Implement the smallest correct change."
    assert canonical_task_body_sha256(task) == canonical_task_body_sha256(task)
    assert len(canonical_task_body_sha256(task)) == 64


def test_four_outcomes_are_bounded_and_recorded(brain_home: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outcomes = [
        SimplificationOutcome.SIMPLIFY,
        SimplificationOutcome.REUSE,
        SimplificationOutcome.DEFER,
        SimplificationOutcome.NO_ACTION,
    ]
    for index, outcome in enumerate(outcomes):
        review = _review(outcome)
        review = dataclasses.replace(review, review_id=f"review-{index}")
        result = record_review(brain_home, project, review)
        assert result["outcome"] == outcome.value
        assert result["verification"] == "passed"
    debt = project / "simplification-debt.md"
    assert debt.exists()
    assert debt.read_text(encoding="utf-8").count("DEBT-") == 1


def test_defer_deduplicates_and_resolve_preserves_identity(
    brain_home: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    first = record_review(brain_home, project, _review(SimplificationOutcome.DEFER))
    second = record_review(brain_home, project, _review(SimplificationOutcome.DEFER))
    assert first["debt_ref"] == second["debt_ref"]
    text = (project / "simplification-debt.md").read_text(encoding="utf-8")
    assert text.count(first["debt_ref"]) == 1
    record_review(
        brain_home,
        project,
        dataclasses.replace(
            _review(SimplificationOutcome.SIMPLIFY, debt_ref=first["debt_ref"]),
            reason_code="cleanup-completed",
            affected_hashes=[],
        ),
    )
    resolved_text = (project / "simplification-debt.md").read_text(encoding="utf-8")
    assert "duplicate-wrapper" in resolved_text
    assert "a" * 64 in resolved_text
    assert "resolved" in (project / "simplification-debt.md").read_text(encoding="utf-8")


def test_corrupt_debt_file_fails_safe_without_overwrite(brain_home: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    debt = project / "simplification-debt.md"
    debt.write_text("not the canonical debt table\n", encoding="utf-8")
    with pytest.raises(BrainError, match="simplification-debt"):
        record_review(brain_home, project, _review(SimplificationOutcome.DEFER))
    assert debt.read_text(encoding="utf-8") == "not the canonical debt table\n"


def test_review_record_never_contains_raw_reasoning(brain_home: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = record_review(brain_home, project, _review(SimplificationOutcome.NO_ACTION))
    encoded = json.dumps(result, sort_keys=True)
    assert "reasoning" not in encoded
    assert "raw" not in encoded

def test_failed_verification_blocks_cleanup_outcomes(brain_home: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(BrainError, match="verification"):
        record_review(
            brain_home,
            project,
            dataclasses.replace(_review(SimplificationOutcome.SIMPLIFY), verification="failed"),
        )


def test_review_mirrors_bounded_ledger_and_telemetry(brain_home: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = record_review(brain_home, project, _review(SimplificationOutcome.NO_ACTION))
    telemetry = brain_home / "telemetry" / "agent-performance" / "session-001.jsonl"
    assert "simplification_review" in telemetry.read_text(encoding="utf-8")
    ledger_files = list((brain_home / "state" / "sessions").glob("*/ledger.sqlite"))
    assert ledger_files
    connection = sqlite3.connect(ledger_files[0])
    try:
        rows = connection.execute(
            "select event_id, payload_json from events where event_type = 'simplification_review'"
        ).fetchall()
    finally:
        connection.close()
    assert rows
    assert result["ledger_event_id"] == rows[0][0]

def test_debt_is_project_scoped(brain_home: Path, tmp_path: Path) -> None:
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    a = record_review(brain_home, project_a, _review(SimplificationOutcome.DEFER))
    b = record_review(
        brain_home,
        project_b,
        dataclasses.replace(_review(SimplificationOutcome.DEFER), review_id="review-b"),
    )
    assert a["debt_ref"] == b["debt_ref"]
    assert a["debt_ref"] in (
        project_a / "simplification-debt.md"
    ).read_text(encoding="utf-8")
    assert a["debt_ref"] in (
        project_b / "simplification-debt.md"
    ).read_text(encoding="utf-8")
