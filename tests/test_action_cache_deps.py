"""T6.5 dependency-class and dirty-worktree action-cache proofs."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from second_brain import __version__, telemetry
from second_brain.action_cache import (
    DISTILLER_VERSION,
    RUNTIME_VERSION_ENV_KEY,
    ActionCacheStore,
    ActionProof,
    ActionType,
    DependencyClass,
    hash_file_content,
    proof_is_complete,
    worktree_fingerprint_for,
)
from second_brain.errors import BrainError


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "src" / "code.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "docs" / "outside.txt").write_text("outside v1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "cache@example.test")
    _git(repo, "config", "user.name", "Cache Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def _proof(target: Path) -> ActionProof:
    fingerprint = worktree_fingerprint_for(target)
    assert fingerprint is not None
    return ActionProof(
        dependency_class=DependencyClass.WORKTREE,
        worktree_root=fingerprint.repository_root,
        worktree_scope=fingerprint.scope,
        worktree_fingerprint=fingerprint.fingerprint,
        verification_predicate="git_tree_unchanged",
    )


def _store_worktree_entry(store: ActionCacheStore, target: Path):
    return store.store_action(
        ActionType.CODE_SEARCH,
        target=str(target.resolve()),
        content="cached result",
        proof=_proof(target),
        params={"pattern": "value"},
    )


def test_dirty_tracked_change_invalidates_worktree(brain_home, tmp_path):
    repo = _repo(tmp_path)
    store = ActionCacheStore(brain_home)
    entry = _store_worktree_entry(store, repo / "src")

    (repo / "src" / "code.py").write_text("value = 2\n", encoding="utf-8")

    result = store.query(entry.action_key)
    assert result.hit is False
    assert result.reason == "proof_validation_failed"


def test_staged_change_invalidates(brain_home, tmp_path):
    repo = _repo(tmp_path)
    store = ActionCacheStore(brain_home)
    entry = _store_worktree_entry(store, repo / "src")

    (repo / "src" / "code.py").write_text("value = 3\n", encoding="utf-8")
    _git(repo, "add", "src/code.py")

    assert store.query(entry.action_key).reason == "proof_validation_failed"


def test_untracked_file_in_scope_invalidates(brain_home, tmp_path):
    repo = _repo(tmp_path)
    store = ActionCacheStore(brain_home)
    entry = _store_worktree_entry(store, repo / "src")

    (repo / "src" / "new.py").write_text("new_value = 1\n", encoding="utf-8")

    assert store.query(entry.action_key).reason == "proof_validation_failed"


def test_out_of_scope_change_keeps_hit(brain_home, tmp_path):
    repo = _repo(tmp_path)
    store = ActionCacheStore(brain_home)
    entry = _store_worktree_entry(store, repo / "src")

    (repo / "docs" / "outside.txt").write_text("outside v2\n", encoding="utf-8")

    result = store.query(entry.action_key)
    assert result.hit is True
    assert result.content == "cached result"


def test_mutation_during_execution_prevents_store(brain_home, tmp_path):
    repo = _repo(tmp_path)
    target = repo / "src"
    store = ActionCacheStore(brain_home)

    def mutate_while_running() -> str:
        (target / "code.py").write_text("value = 99\n", encoding="utf-8")
        return "computed against changing inputs"

    content, hit, _ = store.get_or_execute(
        ActionType.CODE_SEARCH,
        target=str(target.resolve()),
        compute_fn=mutate_while_running,
        proof=_proof(target),
        params={"pattern": "value"},
    )

    assert content == "computed against changing inputs"
    assert hit is False
    assert store.get_stats()["total_entries"] == 0
    records = [
        json.loads(line)
        for path in (brain_home / "telemetry" / "agent-performance").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["kind"] == "cache_store_skipped_inputs_changed" for record in records)
    assert telemetry.validate(brain_home)["issues"] == []


def test_direct_put_mutation_after_compute_prevents_store(brain_home, tmp_path):
    repo = _repo(tmp_path)
    target = repo / "src"
    store = ActionCacheStore(brain_home)
    proof = _proof(target)
    fingerprint_before = proof.worktree_fingerprint
    content = (target / "code.py").read_text(encoding="utf-8")

    (target / "code.py").write_text("value = 100\n", encoding="utf-8")
    entry = store.put(
        ActionType.CODE_SEARCH,
        target=str(target.resolve()),
        content=content,
        proof=proof,
        params={"pattern": "value"},
        fingerprint_before=fingerprint_before,
    )

    assert entry is None
    assert store.get_stats()["total_entries"] == 0
    records = [
        json.loads(line)
        for path in (brain_home / "telemetry" / "agent-performance").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["kind"] == "cache_store_skipped_inputs_changed" for record in records)


def test_incomplete_proof_executes_but_not_cached(brain_home, tmp_path):
    store = ActionCacheStore(brain_home)
    target = tmp_path / "value.txt"
    target.write_text("value", encoding="utf-8")
    calls = 0

    def compute() -> str:
        nonlocal calls
        calls += 1
        return target.read_text(encoding="utf-8")

    for _ in range(2):
        content, hit, _ = store.get_or_execute(
            ActionType.FILE_READ,
            target=str(target),
            compute_fn=compute,
            proof=ActionProof(),
        )
        assert content == "value"
        assert hit is False

    assert calls == 2
    assert store.get_stats()["total_entries"] == 0


def test_dependency_table_and_direct_store_fail_closed(brain_home, tmp_path):
    target = tmp_path / "source.txt"
    target.write_text("source", encoding="utf-8")
    file_proof = ActionProof(
        input_hashes={str(target): hash_file_content(target)},
        dependency_class=DependencyClass.FILE_SET,
    )
    verification_proof = ActionProof.from_dict(file_proof.to_dict())
    verification_proof.env_fingerprint[RUNTIME_VERSION_ENV_KEY] = __version__
    distillation_proof = ActionProof(
        dependency_class=DependencyClass.PURE_CONSTANT,
        constant_fingerprint={
            "source_artifact_sha": "a" * 64,
            "distiller_version": DISTILLER_VERSION,
        },
    )

    assert proof_is_complete(ActionType.FILE_READ, file_proof)
    assert proof_is_complete(ActionType.CODE_SEARCH, file_proof)
    assert proof_is_complete(ActionType.PURE_VERIFICATION, verification_proof)
    assert proof_is_complete(ActionType.DISTILLATION, distillation_proof)
    assert not proof_is_complete(ActionType.DIR_SCAN, file_proof)
    assert not proof_is_complete(ActionType.GENERIC_PURE, ActionProof())

    assert not proof_is_complete(
        ActionType.PURE_VERIFICATION,
        ActionProof(
            dependency_class=DependencyClass.ENV,
            env_fingerprint={RUNTIME_VERSION_ENV_KEY: __version__},
        ),
    )
    with pytest.raises(BrainError, match="Incomplete action-cache proof"):
        ActionCacheStore(brain_home).store_action(
            ActionType.FILE_READ,
            target=str(target),
            content="unsafe",
            proof=ActionProof(),
        )


def test_economics_grouped_and_schema_reopen_is_idempotent(brain_home, tmp_path):
    target = tmp_path / "economic.txt"
    target.write_text("stable", encoding="utf-8")
    proof = ActionProof(
        input_hashes={str(target): hash_file_content(target)},
        dependency_class=DependencyClass.FILE_SET,
    )
    store = ActionCacheStore(brain_home)

    def compute() -> str:
        time.sleep(0.005)
        return "result with enough text to estimate tokens"

    assert store.get_or_execute(ActionType.FILE_READ, str(target), compute, proof=proof)[1] is False
    assert store.get_or_execute(ActionType.FILE_READ, str(target), compute, proof=proof)[1] is True
    before = store.get_stats()
    file_set = before["economics_by_dependency_class"]["FILE_SET"]
    assert file_set["lookups"] == 2
    assert file_set["hits"] == 1
    assert file_set["comparable_samples"] == 1
    assert file_set["avg_compute_ms_avoided"] is not None
    assert file_set["files_hashed"] >= 3
    assert file_set["bytes_hashed"] >= len("stable") * 3
    assert file_set["status"] == "ACTIVE"
    store.close()

    reopened = ActionCacheStore(brain_home)
    assert reopened.get_stats()["total_entries"] == 1
    objects = {
        row["name"]
        for row in reopened._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
        )
    }
    assert "action_cache_economics" in objects
    assert "idx_action_cache_economics_class" in objects
    assert (
        reopened.query(
            next(
                iter(
                    row["action_key"]
                    for row in reopened._get_conn().execute("SELECT action_key FROM action_cache")
                )
            )
        ).hit
        is True
    )


def test_retire_candidate_requires_comparable_hit_sample(brain_home):
    store = ActionCacheStore(brain_home)
    conn = store._get_conn()
    conn.executemany(
        """
        INSERT INTO action_cache_economics (
            action_key, dependency_class, outcome, validate_ms,
            files_hashed, bytes_hashed, tokens_saved_estimate,
            compute_ms, compute_ms_avoided, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("miss-only", "ENV", "miss", 100.0, 0, 0, 0, 1.0, None, "2026-01-01"),
            ("paired", "TIME", "hit", 5.0, 0, 0, 1, None, 1.0, "2026-01-01"),
        ],
    )
    conn.commit()

    economics = store.get_stats()["economics_by_dependency_class"]
    assert economics["ENV"]["status"] == "ACTIVE"
    assert economics["ENV"]["comparable_samples"] == 0
    assert economics["TIME"]["status"] == "RETIRE_CANDIDATE"
    assert economics["TIME"]["comparable_samples"] == 1


def test_old_proof_rows_parse_and_invalid_scope_is_rejected(tmp_path):
    old = ActionProof.from_dict(
        {
            "input_hashes": {"legacy.py": "abc"},
            "verification_predicate": "input_hashes_match",
        }
    )
    assert old.input_hashes == {"legacy.py": "abc"}
    assert old.dependency_class is None

    repo = _repo(tmp_path)
    with pytest.raises(BrainError, match="repository-relative"):
        worktree_fingerprint_for(repo, "../outside")
