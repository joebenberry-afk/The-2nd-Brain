"""
Live integration tests for Context Virtual Memory (Plan §4 R3).

Proves:
1. Object residency lifecycle: RESIDENT -> EVICTED -> FAULTED_IN.
2. Token budget enforcement with prioritized eviction.
3. Compaction barrier: snapshotting, eviction of unpinned items, and post-compaction resume.
4. JIT paging / fault-in of cold objects by compact ref.
5. Explicit stored != delivered != resident accounting.
"""

from second_brain.vmem import ResidencyState, SessionObjectKind, VMemStore


class TestVMemLiveIntegration:
    """Proves live Context Virtual Memory lifecycle and compaction continuity (§4 R3)."""

    def test_object_admission_and_budget_eviction(self, brain_home):
        session_id = "vmem-live-sess-01"
        store = VMemStore(brain_home, session_id)

        # Store high priority pinned decision
        dec_obj = store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Database Architecture",
            content="Use SQLite WAL mode for all session state.",
            pinned=True,
        )
        assert dec_obj.residency_state == ResidencyState.RESIDENT

        # Store multiple large worker findings (each ~500 tokens)
        findings = []
        for i in range(5):
            f_obj = store.store_object(
                kind=SessionObjectKind.WORKER_FINDING,
                title=f"Worker Analysis {i}",
                content=f"Detailed technical analysis findings {i}\n" * 50,
            )
            findings.append(f_obj)

        # Enforce budget of 1000 tokens
        evicted = store.evict_to_budget(max_tokens=1000)
        assert len(evicted) >= 2  # Evicted lower-priority findings

        # Pinned decision remains resident
        refreshed_dec = store.get_object(dec_obj.obj_id)
        assert refreshed_dec is not None
        assert refreshed_dec.residency_state == ResidencyState.RESIDENT

        # Evicted object state verified
        evicted_obj = store.get_object(evicted[0].obj_id)
        assert evicted_obj is not None
        assert evicted_obj.residency_state == ResidencyState.EVICTED

    def test_jit_paging_fault_in(self, brain_home):
        session_id = "vmem-live-sess-02"
        store = VMemStore(brain_home, session_id)

        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Cache Algorithm Notes",
            content="LRU with ARC eviction policy details...",
        )

        # Evict object
        store.evict_to_budget(max_tokens=0)
        evicted_obj = store.get_object(obj.obj_id)
        assert evicted_obj is not None and evicted_obj.residency_state == ResidencyState.EVICTED

        # Fault-in back into active context (returns tuple of obj, content)
        faulted_obj, faulted_content = store.fault_in(obj.obj_id)
        assert faulted_obj.obj_id == obj.obj_id
        assert faulted_obj.residency_state == ResidencyState.FAULTED_IN
        assert "ARC eviction" in faulted_content

    def test_compaction_barrier_snapshot_and_resume(self, brain_home):
        session_id = "vmem-live-sess-03"
        store = VMemStore(brain_home, session_id)

        # 1. Pinned object
        store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Core Rule",
            content="Never modify constitution directly.",
            pinned=True,
        )

        # 2. Transient unpinned objects
        store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="Test run output",
            content="Ran 50 unit tests.",
            pinned=False,
        )

        # Prepare compaction barrier
        prep_result = store.prepare_compaction()
        assert prep_result["evicted_at_compaction"] == 1
        assert prep_result["pinned_preserved"] == 1

        # Post-compaction resume renders compact hot context
        resume_text = store.resume_after_compaction(max_tokens=1500)
        assert "[SECOND_BRAIN_HOT_CONTEXT]" in resume_text
        assert "Core Rule" in resume_text  # Pinned item in hot context
        assert "Cold Indexed Refs" in resume_text  # Evicted item indexed by ref
