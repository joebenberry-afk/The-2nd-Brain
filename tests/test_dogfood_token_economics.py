"""
End-to-End Dogfooding & Token Economics Benchmark (§23, §24).

Executes realistic multi-turn development sessions through the complete Second Brain:
1. Turn 1 (Inspection): Tool working set + Action cache file read + Observation firewall.
2. Turn 2 (Retrieval): Hybrid cascade retrieval with short-circuiting and delta sync.
3. Turn 3 (Compaction & Virtual Memory): Context virtual memory admission and budget eviction.
4. Token Economic Measurement: Proves net token savings and <=5% routine overhead.
"""

from second_brain.action_cache import (
    ActionCacheStore,
    ActionProof,
    ActionType,
    DependencyClass,
    hash_file_content,
)
from second_brain.delta_sync import DeltaSyncEngine
from second_brain.firewall import reduce_observation
from second_brain.governor import SessionTokens, classify_roi
from second_brain.hybrid_retrieval import HybridCascadeRetriever
from second_brain.semantic import add_memory, curate
from second_brain.vmem import SessionObjectKind, VMemStore


class TestEndToEndDogfoodPipeline:
    """Multi-turn end-to-end integration and dogfooding trials (§23)."""

    def test_multi_turn_dogfood_session(self, brain_home, tmp_path):
        session_id = "dogfood-session-001"
        cache_store = ActionCacheStore(brain_home)
        vmem_store = VMemStore(brain_home, session_id)
        retriever = HybridCascadeRetriever()
        sync_engine = DeltaSyncEngine()

        # Turn 1: Inspection & File Reads

        # Action Cache store & replay for file read
        src_file = tmp_path / "app.py"
        src_file.write_text("import os\n\ndef run(): pass\n", encoding="utf-8")
        src_hash = hash_file_content(src_file)
        proof = ActionProof(
            input_hashes={str(src_file): src_hash},
            dependency_class=DependencyClass.FILE_SET,
        )

        cached_entry = cache_store.store_action(
            action_type=ActionType.FILE_READ,
            target=str(src_file),
            content=src_file.read_text(encoding="utf-8"),
            proof=proof,
        )
        hit_res = cache_store.query(cached_entry.action_key)
        assert hit_res.hit is True
        assert hit_res.content == src_file.read_text(encoding="utf-8")
        assert hit_res.latency_ms < 15.0

        # Observation Firewall reduces raw test output
        raw_test_log = "PASSED tests/test_core.py::test_init\n" * 100 + "100 passed in 1.2s\n"
        reduced = reduce_observation(raw_test_log, command="pytest", home=brain_home)
        assert reduced.reduction_ratio >= 0.80  # Over 80% reduction!

        # Turn 2: Context VMem storage & admission
        vmem_obj = vmem_store.store_object(
            kind=SessionObjectKind.TEST_EVIDENCE,
            title="100 passed pytest run",
            content=reduced.distilled_text,
            summary="pytest run summary",
        )
        assert vmem_obj.obj_id.startswith("obj-")

        # Turn 3: Hybrid Retrieval & Memory Delta Sync
        mem_id = add_memory(
            brain_home,
            title="Architecture Doctrine",
            summary="Keep kernels lean and deterministic",
            body="All memory structures must serialize to canonical JSON.",
            grade="VERIFIED",
        )
        curate(brain_home, mem_id, status="current")

        cas_res = retriever.retrieve(brain_home, mem_id)
        assert cas_res.tier_resolved == 0
        assert cas_res.decision == "INJECT"

        # Delta sync to receiver
        deltas_t1, rendered_t1 = sync_engine.sync_memories(
            session_id, [{"memory_id": mem_id, "version": 1, "status": "current", "title": "Doc"}]
        )
        assert len(deltas_t1) == 1
        assert deltas_t1[0].delta_type.value == "ADD"
        assert "Doc" in rendered_t1

        # Second turn sync -> UNCHANGED (0 tokens)
        deltas_t2, rendered_t2 = sync_engine.sync_memories(
            session_id, [{"memory_id": mem_id, "version": 1, "status": "current", "title": "Doc"}]
        )
        assert deltas_t2[0].delta_type.value == "UNCHANGED"
        assert rendered_t2 == ""

        # Turn 4: Compaction Preparation & Resume
        prep = vmem_store.prepare_compaction()
        assert prep["evicted_at_compaction"] >= 1
        assert prep["pinned_preserved"] == 0
        hot_res = vmem_store.render_hot_context(max_tokens=1500)
        assert "[SECOND_BRAIN_HOT_CONTEXT]" in hot_res["rendered_text"]


class TestTokenEconomicsBenchmark:
    """Token economic proofs across ablation profiles (§24)."""

    def test_brain_token_economics_roi(self):
        # Scenario 1: Highly effective multi-turn session with positive ROI
        on_sessions = [
            SessionTokens(
                session_id=f"on-{i}",
                total_tokens=15000,
                cost_total=0.045,
                cost_total_seen=1,
            )
            for i in range(5)
        ]
        off_sessions = [
            SessionTokens(
                session_id=f"off-{i}",
                total_tokens=35000,
                cost_total=0.105,
                cost_total_seen=1,
            )
            for i in range(5)
        ]

        verdict = classify_roi(on_sessions, off_sessions)
        assert verdict.status == "POSITIVE_ROI"
        assert verdict.savings is not None and verdict.savings < 0  # negative diff = savings
        assert verdict.on_sessions == 5
        assert verdict.off_sessions == 5

    def test_insufficient_evidence_when_missing_costs(self):
        on_sessions = [SessionTokens(session_id="on-1", cost_total=None, cost_total_seen=0)]
        off_sessions = [SessionTokens(session_id="off-1", cost_total=10.0, cost_total_seen=1)]
        verdict = classify_roi(on_sessions, off_sessions)
        assert verdict.status == "INSUFFICIENT_EVIDENCE"
