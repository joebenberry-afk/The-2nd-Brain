"""Tests for Context Virtual Memory (VMem) and Session Residency (Plan §6)."""

import json
import os
import subprocess
import sys

import pytest

from second_brain.errors import BrainError
from second_brain.vmem import (
    ResidencyState,
    SessionObjectKind,
    VMemStore,
)


class TestVMemStorageAndResidency:
    """Tests for object storage, kind assignment, and residency state transitions."""

    def test_store_and_retrieve_session_object(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-1")
        content = "Detailed finding on memory indexing optimization: use FTS5."
        obj = store.store_object(
            kind=SessionObjectKind.WORKER_FINDING,
            title="FTS5 Memory Finding",
            content=content,
            summary="Use FTS5 index for faster retrieval",
            pinned=False,
        )

        assert obj.obj_id.startswith("obj-")
        assert obj.kind == SessionObjectKind.WORKER_FINDING
        assert obj.residency_state == ResidencyState.RESIDENT
        assert obj.token_estimate > 0
        assert obj.pinned is False

        # Retrieve
        fetched = store.get_object(obj.obj_id)
        assert fetched is not None
        assert fetched.title == "FTS5 Memory Finding"
        assert fetched.summary == "Use FTS5 index for faster retrieval"
        assert fetched.content_sha256 == obj.content_sha256

    def test_pinned_object_priority(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-2")
        obj_pinned = store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Architecture Decision",
            content="Use SQLite WAL mode",
            pinned=True,
        )
        obj_unpinned = store.store_object(
            kind=SessionObjectKind.LOG_EXCERPT,
            title="Verbose Log",
            content="Log output 123",
            pinned=False,
        )
        assert obj_pinned.priority_score > obj_unpinned.priority_score
        assert obj_pinned.pinned is True
        assert obj_unpinned.pinned is False

    def test_residency_filtering(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-3")
        store.store_object(
            kind=SessionObjectKind.BLOCKER,
            title="Missing Lib",
            content="libfoo not found",
            pinned=True,
        )
        store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Web Search",
            content="Search notes",
            pinned=False,
        )

        residents = store.list_objects(residency_state=ResidencyState.RESIDENT)
        assert len(residents) == 2

        blockers = store.list_objects(kind=SessionObjectKind.BLOCKER)
        assert len(blockers) == 1
        assert blockers[0].kind == SessionObjectKind.BLOCKER


class TestEvictionAndContextPaging:
    """Tests for token budget eviction and JIT context fault-in (§6.5, §6.6)."""

    def test_evict_to_budget_preserves_pinned(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-4")

        # Store a large unpinned log (e.g. ~500 tokens)
        large_log = "log line with extensive debug info\n" * 60
        obj_log = store.store_object(
            kind=SessionObjectKind.LOG_EXCERPT,
            title="Debug Trace",
            content=large_log,
            pinned=False,
        )

        # Store a pinned decision
        obj_dec = store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Core Decision",
            content="Do not evict pinned decisions",
            pinned=True,
        )

        # Set budget lower than total
        evicted = store.evict_to_budget(max_tokens=50)
        assert len(evicted) >= 1
        assert any(o.obj_id == obj_log.obj_id for o in evicted)

        # Verify unpinned object is EVICTED and pinned object remains RESIDENT
        refetched_log = store.get_object(obj_log.obj_id)
        refetched_dec = store.get_object(obj_dec.obj_id)
        assert refetched_log is not None
        assert refetched_log.residency_state == ResidencyState.EVICTED
        assert refetched_dec is not None
        assert refetched_dec.residency_state == ResidencyState.RESIDENT

    def test_fault_in_retrieves_exact_content_and_updates_state(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-5")
        secret_content = "Special test payload with unique content 998877"
        obj = store.store_object(
            kind=SessionObjectKind.TEST_EVIDENCE,
            title="Failing Test Trace",
            content=secret_content,
            pinned=False,
        )

        # Force eviction
        store.evict_to_budget(max_tokens=1)
        evicted_obj = store.get_object(obj.obj_id)
        assert evicted_obj is not None and evicted_obj.residency_state == ResidencyState.EVICTED

        # Fault-in (page-in on demand)
        paged_obj, recovered_content = store.fault_in(obj.obj_id)
        assert paged_obj.residency_state == ResidencyState.FAULTED_IN
        assert recovered_content == secret_content
        assert paged_obj.access_count == 2

    def test_fault_in_missing_raises_brain_error(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-6")
        with pytest.raises(BrainError, match="Session object not found"):
            store.fault_in("obj-nonexistent123")


class TestHotContextAndCompaction:
    """Tests for hot working set rendering and compaction recovery barriers (§6.4, §6.7)."""

    def test_render_hot_context_includes_resident_and_cold_refs(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-7")

        store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Keep in Context",
            content="Active decision text",
            pinned=True,
        )
        store.store_object(
            kind=SessionObjectKind.LOG_EXCERPT,
            title="Old Verbose Log",
            content="Verbose lines\n" * 100,
            pinned=False,
        )

        # Budget to force eviction of the verbose log
        ctx = store.render_hot_context(max_tokens=50)

        assert ctx["resident_count"] >= 1
        assert ctx["evicted_count"] >= 1
        assert "[SECOND_BRAIN_HOT_CONTEXT]" in ctx["rendered_text"]
        assert "Resident Working State" in ctx["rendered_text"]
        assert "Cold Indexed Refs" in ctx["rendered_text"]
        assert "Old Verbose Log" in ctx["rendered_text"]

    def test_compaction_barrier_lifecycle(self, brain_home):
        store = VMemStore(brain_home, "sess-vmem-8")

        store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Pinned Core Decision",
            content="Survives compaction",
            pinned=True,
        )
        store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Temporary Scratch",
            content="Evicted at compaction",
            pinned=False,
        )

        # Pre-compaction
        prep = store.prepare_compaction()
        assert prep["evicted_at_compaction"] == 1
        assert prep["pinned_preserved"] == 1

        # Post-compaction resume
        resume_text = store.resume_after_compaction(max_tokens=1500)
        assert "[SECOND_BRAIN_HOT_CONTEXT]" in resume_text
        assert "Pinned Core Decision" in resume_text
        assert "Temporary Scratch" in resume_text  # Referenced in cold table


class TestVMemCLI:
    """CLI tests for brainctl vmem subcommands."""

    def test_vmem_cli_store_list_and_page(self, brain_home, tmp_path):
        content_file = tmp_path / "finding.txt"
        content_file.write_text("Discovered cache optimization via CLI", encoding="utf-8")

        # 1. Store
        store_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "vmem",
                "store",
                "sess-cli-1",
                "WORKER_FINDING",
                "CLI Finding",
                str(content_file),
                "--pinned",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert store_res.returncode == 0
        data = json.loads(store_res.stdout)
        obj_id = data["obj_id"]
        assert data["pinned"] is True

        # 2. List
        list_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "vmem",
                "list",
                "sess-cli-1",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert list_res.returncode == 0
        items = json.loads(list_res.stdout)
        assert len(items) == 1
        assert items[0]["obj_id"] == obj_id

        # 3. Page
        page_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "vmem",
                "page",
                "sess-cli-1",
                obj_id,
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert page_res.returncode == 0
        assert "Discovered cache optimization via CLI" in page_res.stdout
