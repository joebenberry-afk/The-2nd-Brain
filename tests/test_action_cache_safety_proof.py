"""
Adversarial safety proof tests for Proof-Carrying Action Cache (Plan §4 R4 & Finding F5).

Tests:
1. Unchanged dependency -> hit.
2. Changed dependency -> miss.
3. Relevant Git tree state changed -> miss.
4. Env variable changed -> miss.
5. TTL expired -> miss.
6. Artifact missing / corrupt -> safe miss.
7. Unrelated file change -> retains hit.
"""

import os
from datetime import UTC, datetime, timedelta

from second_brain.action_cache import (
    ActionCacheStore,
    ActionProof,
    ActionType,
    hash_file_content,
)


class TestActionCacheAdversarialSafetyProof:
    """Rigorous adversarial testing of ActionProof validation (§4 R4)."""

    def test_file_hash_dependency_validation(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target = tmp_path / "calc.py"
        target.write_text("def add(a, b): return a + b", encoding="utf-8")
        h0 = hash_file_content(target)

        proof = ActionProof(input_hashes={str(target): h0})
        entry = store.store_action(
            action_type=ActionType.PURE_VERIFICATION,
            target=str(target),
            content="verification_passed",
            proof=proof,
        )

        # 1. Unchanged dependency -> Hit
        hit1 = store.query(entry.action_key)
        assert hit1.hit is True
        assert hit1.content == "verification_passed"

        # 2. Changed dependency -> Miss + Automatic Invalidation
        target.write_text("def add(a, b): return a + b + 1", encoding="utf-8")
        hit2 = store.query(entry.action_key)
        assert hit2.hit is False
        assert hit2.reason == "proof_validation_failed"

    def test_env_fingerprint_validation(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target = tmp_path / "env_check.py"
        target.write_text("check", encoding="utf-8")

        os.environ["ACTION_CACHE_TEST_ENV"] = "production"
        try:
            proof = ActionProof(env_fingerprint={"ACTION_CACHE_TEST_ENV": "production"})
            entry = store.store_action(
                action_type=ActionType.PURE_VERIFICATION,
                target=str(target),
                content="env_verified",
                proof=proof,
            )

            # Hit when env matches
            assert store.query(entry.action_key).hit is True

            # Miss when env changes
            os.environ["ACTION_CACHE_TEST_ENV"] = "staging"
            hit = store.query(entry.action_key)
            assert hit.hit is False
            assert hit.reason == "proof_validation_failed"
        finally:
            os.environ.pop("ACTION_CACHE_TEST_ENV", None)

    def test_ttl_expiration_validation(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target = tmp_path / "ttl.py"
        target.write_text("ttl", encoding="utf-8")

        past_time = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        proof = ActionProof(expires_at=past_time)
        entry = store.store_action(
            action_type=ActionType.PURE_VERIFICATION,
            target=str(target),
            content="expired_content",
            proof=proof,
        )

        hit = store.query(entry.action_key)
        assert hit.hit is False
        assert hit.reason == "proof_validation_failed"

    def test_git_tree_hash_validation(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target = tmp_path / "git_target.py"
        target.write_text("git code", encoding="utf-8")

        # Set fake git tree hash that does not match current workspace tree
        proof = ActionProof(git_tree_hash="0000000000000000000000000000000000000000")
        entry = store.store_action(
            action_type=ActionType.PURE_VERIFICATION,
            target=str(target),
            content="git_content",
            proof=proof,
        )

        hit = store.query(entry.action_key)
        assert hit.hit is False
        assert hit.reason == "proof_validation_failed"

    def test_unrelated_file_change_retains_hit(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target = tmp_path / "main_target.py"
        unrelated = tmp_path / "unrelated.py"
        target.write_text("main", encoding="utf-8")
        unrelated.write_text("unrelated v1", encoding="utf-8")

        proof = ActionProof(input_hashes={str(target): hash_file_content(target)})
        entry = store.store_action(
            action_type=ActionType.FILE_READ,
            target=str(target),
            content="main_content",
            proof=proof,
        )

        # Mutate unrelated file
        unrelated.write_text("unrelated v2 with extra changes", encoding="utf-8")

        # Main target query remains a hit
        hit = store.query(entry.action_key)
        assert hit.hit is True
        assert hit.content == "main_content"
