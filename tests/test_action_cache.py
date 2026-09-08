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
    DependencyClass,
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
            dependency_class=DependencyClass.FILE_SET,
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
        assert res.latency_ms < 20.0  # sub-millisecond to fast execution
        assert res.entry is not None and res.entry.hit_count == 1

    def test_proof_invalidation_when_file_changes(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target_file = tmp_path / "dynamic.py"
        target_file.write_text("v1 content", encoding="utf-8")
        file_hash = hash_file_content(target_file)

        proof = ActionProof(
            input_hashes={str(target_file): file_hash},
            dependency_class=DependencyClass.FILE_SET,
        )
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
            action_type=ActionType.PURE_VERIFICATION,
            target="src/",
            content="file1.py\nfile2.py",
            proof=ActionProof(dependency_class=DependencyClass.TIME),
            ttl_seconds=-1,
        )

        res = store.query(entry.action_key)
        assert res.hit is False
        assert res.reason == "proof_validation_failed"

    def test_get_or_execute_pure_action(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        target = tmp_path / "lib.py"
        target.write_text("class Vault: pass", encoding="utf-8")
        file_hash = hash_file_content(target)
        proof = ActionProof(
            input_hashes={str(target): file_hash},
            dependency_class=DependencyClass.FILE_SET,
        )

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
        assert lat2 < 20.0  # Fast replay

    def test_invalidate_by_path(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        f1 = tmp_path / "f1.py"
        f1.write_text("f1", encoding="utf-8")
        h1 = hash_file_content(f1)

        store.store_action(
            action_type=ActionType.FILE_READ,
            target=str(f1),
            content="f1 content",
            proof=ActionProof(
                input_hashes={str(f1): h1},
                dependency_class=DependencyClass.FILE_SET,
            ),
        )

        stats_before = store.get_stats()
        assert stats_before["total_entries"] == 1

        invalidated = store.invalidate_by_path(f1)
        assert invalidated == 1

        stats_after = store.get_stats()
        assert stats_after["total_entries"] == 0

    def test_invalidate_by_path_uses_target_index(self, brain_home, tmp_path):
        """T6.2: invalidate_by_path's target-match branch must use the
        `idx_action_target` index via a direct `target IN (...)` lookup,
        not a full-table scan. Proof entries here carry no `input_hashes`,
        so a match is only reachable through the indexed target branch.

        Traces the exact SQL `invalidate_by_path` itself issues (via
        `sqlite3.Connection.set_trace_callback`) rather than running an
        independent hand-written query — asserting a query plan for a
        hardcoded query never actually proves what the method under test
        does. The old full-table-scan implementation issues an unfiltered
        `SELECT ... FROM action_cache` with no `WHERE target`, so this test
        fails against it both on "no WHERE-filtered target query observed"
        and (if it somehow did) on the query plan check."""
        store = ActionCacheStore(brain_home)
        f1 = tmp_path / "f1.py"
        f1.write_text("f1", encoding="utf-8")
        f2 = tmp_path / "f2.py"
        f2.write_text("f2", encoding="utf-8")

        store.store_action(
            action_type=ActionType.GENERIC_PURE,
            target=str(f1),
            content="f1 content",
            proof=ActionProof(
                dependency_class=DependencyClass.PURE_CONSTANT,
                constant_fingerprint={"value": "f1"},
            ),
        )
        store.store_action(
            action_type=ActionType.GENERIC_PURE,
            target=str(f2),
            content="f2 content",
            proof=ActionProof(
                dependency_class=DependencyClass.PURE_CONSTANT,
                constant_fingerprint={"value": "f2"},
            ),
        )
        assert store.get_stats()["total_entries"] == 2

        conn = store._get_conn()
        executed: list[str] = []
        conn.set_trace_callback(executed.append)
        try:
            invalidated = store.invalidate_by_path(f1)
        finally:
            conn.set_trace_callback(None)

        assert invalidated == 1
        assert store.get_stats()["total_entries"] == 1

        target_where_queries = [
            sql
            for sql in executed
            if "action_cache" in sql
            and "target" in sql.lower()
            and "where" in sql.lower()
            and sql.strip().upper().startswith("SELECT")
        ]
        assert target_where_queries, (
            executed
        )  # must actually filter by target in SQL, not in Python

        plan = conn.execute(f"EXPLAIN QUERY PLAN {target_where_queries[0]}").fetchall()
        details = [" ".join(str(v) for v in row) for row in plan]
        assert any("USING INDEX idx_action_target" in d for d in details), (
            target_where_queries,
            details,
        )


class TestActionCacheGateBenchmark:
    """Phase 4 Gate: Prove repeated queries hit cache in <1ms and save tokens."""

    def test_benchmark_submillisecond_replay(self, brain_home, tmp_path):
        store = ActionCacheStore(brain_home)
        f = tmp_path / "bench.py"
        f.write_text("benchmark content line\n" * 50, encoding="utf-8")
        h = hash_file_content(f)
        proof = ActionProof(
            input_hashes={str(f): h},
            dependency_class=DependencyClass.FILE_SET,
        )

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
            proof=ActionProof(
                input_hashes={str(f): hash_file_content(f)},
                dependency_class=DependencyClass.FILE_SET,
            ),
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


class TestActionCacheArtifactRefs:
    """T6.3: action_cache pairs artifact_refs registration/removal with its
    own store/delete lifecycle so artifacts.gc() can reap orphaned blobs."""

    def test_lru_eviction_removes_artifact_ref(self, tmp_path):
        from second_brain import db as db_mod

        cache = ActionCacheStore(tmp_path, max_entries=2)
        proof = ActionProof(
            dependency_class=DependencyClass.PURE_CONSTANT,
            constant_fingerprint={"test": "artifact-ref-lru"},
        )
        e1 = cache.put(
            action_type=ActionType.GENERIC_PURE,
            target="f1.py",
            content="c1",
            proof=proof,
            params={"p": 1},
        )
        time.sleep(0.01)
        e2 = cache.put(
            action_type=ActionType.GENERIC_PURE,
            target="f2.py",
            content="c2",
            proof=proof,
            params={"p": 2},
        )
        time.sleep(0.01)
        e3 = cache.put(
            action_type=ActionType.GENERIC_PURE,
            target="f3.py",
            content="c3",
            proof=proof,
            params={"p": 3},
        )
        assert e1 is not None and e2 is not None and e3 is not None
        conn = db_mod.connect(db_mod.db_path(tmp_path), readonly=True)
        owners = {r["owner"] for r in conn.execute("SELECT owner FROM artifact_refs").fetchall()}
        conn.close()
        assert f"action_cache:{e1.action_key}" not in owners  # evicted
        assert f"action_cache:{e2.action_key}" in owners
        assert f"action_cache:{e3.action_key}" in owners

    def test_invalidate_by_key_removes_artifact_ref(self, tmp_path):
        from second_brain import db as db_mod

        cache = ActionCacheStore(tmp_path)
        entry = cache.put(
            action_type=ActionType.GENERIC_PURE,
            target="f1.py",
            content="c1",
            proof=ActionProof(
                dependency_class=DependencyClass.PURE_CONSTANT,
                constant_fingerprint={"test": "artifact-ref-key"},
            ),
        )
        assert entry is not None
        owner = f"action_cache:{entry.action_key}"
        conn = db_mod.connect(db_mod.db_path(tmp_path), readonly=True)
        before = conn.execute(
            "SELECT COUNT(*) FROM artifact_refs WHERE owner = ?", (owner,)
        ).fetchone()[0]
        conn.close()
        assert before == 1

        cache.invalidate_by_key(entry.action_key)

        conn = db_mod.connect(db_mod.db_path(tmp_path), readonly=True)
        after = conn.execute(
            "SELECT COUNT(*) FROM artifact_refs WHERE owner = ?", (owner,)
        ).fetchone()[0]
        conn.close()
        assert after == 0

    def test_clear_bulk_removes_all_action_cache_refs(self, tmp_path):
        from second_brain import db as db_mod

        cache = ActionCacheStore(tmp_path)
        proof = ActionProof(
            dependency_class=DependencyClass.PURE_CONSTANT,
            constant_fingerprint={"test": "artifact-ref-clear"},
        )
        cache.put(
            action_type=ActionType.GENERIC_PURE,
            target="f1.py",
            content="c1",
            proof=proof,
        )
        cache.put(
            action_type=ActionType.GENERIC_PURE,
            target="f2.py",
            content="c2",
            proof=proof,
        )
        cache.clear()

        conn = db_mod.connect(db_mod.db_path(tmp_path), readonly=True)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM artifact_refs WHERE owner LIKE 'action_cache:%'"
        ).fetchone()[0]
        conn.close()
        assert remaining == 0
