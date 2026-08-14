from pathlib import Path

from second_brain import crossmodel, db, paths


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "brain"
    paths.ensure_layout(home)
    db.migrate(db.db_path(home))
    return home


def _outcome(home: Path, model: str, task: str, success: bool) -> None:
    crossmodel.record_model(home, model)
    crossmodel.record_skill_outcome(home, model, "proof", task, success)


def test_zero_success_and_single_overlap_never_certify_transfer(tmp_path: Path):
    home = _home(tmp_path)
    _outcome(home, "a", "both-fail", False)
    _outcome(home, "b", "both-fail", False)
    assert crossmodel.transfer_test(home, "proof", "a", "b")["verdict"] == "does_not_transfer"

    _outcome(home, "a", "one", False)
    _outcome(home, "b", "one", True)
    result = crossmodel.transfer_test(home, "proof", "a", "b")
    assert result["verdict"] == "insufficient_evidence"
    assert result["strong_evidence"] is False
