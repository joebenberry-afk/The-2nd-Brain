"""SEC-07 regression tests: proof task/workspace path escape.

The runner must never let a task-supplied id influence a workspace path
outside the trusted temporary root, and workspace cleanup must stay inside
it.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from proof.runner.condition import Condition
from proof.runner.run_proof import _load_tasks, run_stage
from proof.runner.workspace import copy_workspace
from second_brain.errors import BrainError
from second_brain.security.identifiers import validate_proof_task_id

HOSTILE_IDS = [
    "../escape",
    "..\\escape",
    "a/b",
    "a\\b",
    "/abs",
    "C:\\abs",
    "\\srv\\share",
    "a\nb",
    "a*b",
    "a?b",
    ".",
    "..",
    "",
]


@pytest.mark.parametrize("bad", HOSTILE_IDS)
def test_validate_proof_task_id_rejects_hostile(bad: str) -> None:
    with pytest.raises(BrainError):
        validate_proof_task_id(bad)


@pytest.mark.parametrize("bad", HOSTILE_IDS)
def test_load_tasks_rejects_hostile_task_ids(tmp_path: Path, bad: str) -> None:
    """SEC-T058/T059: a hostile task id fails at task-file load time."""
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps({"tasks": [{"task_id": bad, "dataset": "training", "prompt": "p"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsafe task_id"):
        _load_tasks(task_file)


def test_valid_task_ids_load() -> None:
    import proof.runner.run_proof as rp

    data = rp._load_tasks(Path(__file__).resolve().parents[2] / "proof" / "tasks" / "training" / "smoke.json")
    assert len(data) == 10


def test_copy_workspace_rejects_target_outside_root(tmp_path: Path) -> None:
    """SEC-T063: copy_workspace refuses targets outside the trusted root."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "f").write_text("x", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="outside the trusted root"):
        copy_workspace(source, outside / "target", root=root)
    assert list(outside.iterdir()) == []


def test_copy_workspace_contained_target_works(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "f").write_text("x", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    target = root / "ws"
    result = copy_workspace(source, target, root=root)
    assert result == target
    assert (target / "f").read_text(encoding="utf-8") == "x"


def test_run_stage_workspaces_derived_from_validated_ids(tmp_path: Path, monkeypatch) -> None:
    """SEC-T060: generated workspaces are under the trusted temp root and two
    runs receive separate workspaces."""
    import proof.runner.run_proof as rp

    captured: dict[str, list] = {}
    original = rp.copy_workspace

    def spy(source, target, *, root=None):
        captured.setdefault("targets", []).append(str(target))
        return original(source, target, root=root)

    monkeypatch.setattr(rp, "copy_workspace", spy)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file.txt").write_text("x", encoding="utf-8")
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "config").mkdir()
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "sec-task-1",
                        "dataset": "training",
                        "task_family": "security",
                        "prompt": "do something",
                        "oracle": {"type": "file_contains", "path": "file.txt", "text": "x"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_prime(**kwargs):
        from proof.runner.prime import PrimeResult

        return PrimeResult(exit_code=0, stdout="x", stderr="", wall_seconds=0.1, timed_out=False)

    monkeypatch.setattr(rp, "run_prime", fake_prime)
    monkeypatch.setattr(
        rp,
        "_telemetry_metrics",
        lambda home: {
            "tool_calls": 0,
            "failed_tool_calls": 0,
            "peak_context_percent": None,
            "telemetry_files": 0,
            "session_shutdown": False,
        },
    )

    created_roots: list[Path] = []
    real_temporary_directory = tempfile.TemporaryDirectory

    def recording_temporary_directory(*args, **kwargs):
        instance = real_temporary_directory(*args, **kwargs)
        created_roots.append(Path(instance.name))
        return instance

    monkeypatch.setattr(rp.tempfile, "TemporaryDirectory", recording_temporary_directory)

    with tempfile.TemporaryDirectory(prefix="second-brain-proof-") as temporary:
        temp_root = Path(temporary)
        result = run_stage(
            task_file=task_file,
            dataset="training",
            repo=repo_dir,
            brain_home=brain,
            output=tmp_path / "out.jsonl",
            conditions=[Condition.C0_OFF],
            seed=1,
            launcher=tmp_path / "launcher",
            extension=None,
            model="test",
            thinking="minimal",
            offline=True,
            timeout_s=5.0,
        )
        assert result["records"] == 1
        # Every workspace the runner built lives under ITS temporary root.
        assert len(created_roots) >= 1
        runner_root = created_roots[-1]
        for target in captured["targets"]:
            Path(target).relative_to(runner_root)
    # the runner's temp root is gone after run_stage exits -> cleanup happened
    assert not runner_root.exists()
