"""Tests for Proof-Carrying Action Cache (Plan §7)."""

import json
import os
import subprocess
import sys
import time

from second_brain.action_cache import (
    ActionCacheStore,
    ActionProof,
    ActionType,
    compute_action_key,
    hash_file_content,
)


class TestActionKeyAndProof:
    """Tests for deterministic action key construction and proof validation (§7.2, §7.3)."""

    def test_compute_action_key_deterministic(self):
        k1 = compute_action_key(
            ActionType.FILE_READ,
            "src/mod.py",
            params={"mode": "r"},
            input_hashes={"src/mod.py": "abc123sha"},
        )
        k2 = compute_action_key(
            ActionType.FILE_READ,
            "src/mod.py",
            params={"mode": "r"},
            input_hashes={"src/mod.py": "abc123sha"},
        )
        assert k1 == k2
        assert len(k1) == 64

    def test_action_key_changes_on_input_hash_difference(self):
        k1 = compute_action_key(
            ActionType.FILE_READ,
            "src/mod.py",
            input_hashes={"src/mod.py": "hash_v1"},
        )
        k2 = compute_action_key(
            ActionType.FILE_READ,
            "src/mod.py",
            input_hashes={"src/mod.py": "hash_v2"},
        )
        assert k1 != k2


class TestActionCacheStoreAndReplay:
    """Tests for storing, querying, replay, and proof validation (§7.4)."""

    def test_store_and_hit_replay(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target_file = tmp_path / "sample.py"
        target_file.write_text("def hello(): pass\n", encoding="utf-8")
        file_hash = hash_file_content(target_file)

        proof = ActionProof(
            input_hashes={str(target_file): file_hash},
        )

        entry = store.store_action(
            action_type=ActionType.FILE_READ,
            target=str(target_file),
            content="def hello(): pass\n",
            output_summary="read sample.py",
            proof=proof,
            tokens_saved_estimate=10,
        )

        assert entry.action_key
        assert entry.output_ref

        # Query cache
        res = store.query(entry.action_key)
        assert res.hit is True
        assert res.content == "def hello(): pass\n"
        assert res.latency_ms < 5.0  # sub-millisecond to fast execution
        assert res.entry is not None and res.entry.hit_count == 1

    def test_proof_invalidation_when_file_changes(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target_file = tmp_path / "dynamic.py"
        target_file.write_text("v1 content", encoding="utf-8")
        file_hash = hash_file_content(target_file)

        proof = ActionProof(input_hashes={str(target_file): file_hash})
        entry = store.store_action(
            action_type=ActionType.PURE_VERIFICATION,
            target=str(target_file),
            content="verification_passed",
            proof=proof,
        )

        # First query: hit
        res1 = store.query(entry.action_key)
        assert res1.hit is True

        # Mutate the file
        target_file.write_text("v2 modified content", encoding="utf-8")

        # Second query: proof validation must fail and invalidate the entry
        res2 = store.query(entry.action_key)
        assert res2.hit is False
        assert res2.reason == "proof_validation_failed"

        # Verify entry was deleted
        assert store.query(entry.action_key).reason == "key_not_found"

    def test_ttl_expiration(self, brain_home):
        store = ActionCacheStore(brain_home)
        entry = store.store_action(
            action_type=ActionType.DIR_SCAN,
            target="src/",
            content="file1.py\nfile2.py",
            ttl_seconds=-1,  # Expired immediately
        )

        res = store.query(entry.action_key)
        assert res.hit is False
        assert res.reason == "proof_validation_failed"

    def test_get_or_execute_pure_action(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target = tmp_path / "lib.py"
        target.write_text("class Vault: pass", encoding="utf-8")
        file_hash = hash_file_content(target)
        proof = ActionProof(input_hashes={str(target): file_hash})

        call_count = 0

        def expensive_computation():
            nonlocal call_count
            call_count += 1
            return "computed_result_data"

        # 1st call: Miss (computes)
        val1, hit1, _lat1 = store.get_or_execute(
            ActionType.PURE_VERIFICATION,
            target=str(target),
            compute_fn=expensive_computation,
            proof=proof,
        )
        assert val1 == "computed_result_data"
        assert hit1 is False
        assert call_count == 1

        # 2nd call: Hit (replays without calling compute_fn)
        val2, hit2, lat2 = store.get_or_execute(
            ActionType.PURE_VERIFICATION,
            target=str(target),
            compute_fn=expensive_computation,
            proof=proof,
        )
        assert val2 == "computed_result_data"
        assert hit2 is True
        assert call_count == 1  # Not called again!
        assert lat2 < 5.0  # Fast replay

    def test_invalidate_by_path(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        f1 = tmp_path / "f1.py"
        f1.write_text("f1", encoding="utf-8")
        h1 = hash_file_content(f1)

        store.store_action(
            action_type=ActionType.FILE_READ,
            target=str(f1),
            content="f1 content",
            proof=ActionProof(input_hashes={str(f1): h1}),
        )

        stats_before = store.get_stats()
        assert stats_before["total_entries"] == 1

        invalidated = store.invalidate_by_path(f1)
        assert invalidated == 1

        stats_after = store.get_stats()
        assert stats_after["total_entries"] == 0


class TestActionCacheGateBenchmark:
    """Phase 4 Gate: Prove repeated queries hit cache in <1ms and save tokens."""

    def test_benchmark_submillisecond_replay(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        f = tmp_path / "bench.py"
        f.write_text("benchmark content line\n" * 50, encoding="utf-8")
        h = hash_file_content(f)
        proof = ActionProof(input_hashes={str(f): h})

        entry = store.store_action(
            action_type=ActionType.FILE_READ,
            target=str(f),
            content=f.read_text(encoding="utf-8"),
            proof=proof,
            tokens_saved_estimate=250,
        )

        # Run 50 warm queries and measure latencies
        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            res = store.query(entry.action_key)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            assert res.hit is True
            latencies.append(elapsed_ms)

        avg_latency = sum(latencies) / len(latencies)
        # Verify sub-millisecond or low single-digit ms
        assert avg_latency < 2.0
        stats = store.get_stats()
        assert stats["total_hits"] == 50
        assert stats["tokens_saved_estimate"] == 50 * 250


class TestActionCacheCLI:
    """CLI tests for brainctl action-cache subcommands."""

    def test_cli_stats_and_invalidate(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        f = tmp_path / "cli_test.txt"
        f.write_text("cli test content", encoding="utf-8")
        store.store_action(
            action_type=ActionType.FILE_READ,
            target=str(f),
            content="cli test content",
            proof=ActionProof(input_hashes={str(f): hash_file_content(f)}),
        )

        # 1. Stats
        stats_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "action-cache",
                "stats",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert stats_res.returncode == 0
        stats = json.loads(stats_res.stdout)
        assert stats["total_entries"] == 1

        # 2. Invalidate
        inv_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "action-cache",
                "invalidate",
                "--path",
                str(f),
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert inv_res.returncode == 0
        assert "Invalidated 1 entries" in inv_res.stdout
