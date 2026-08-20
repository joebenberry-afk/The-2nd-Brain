"""Tests for Context Virtual Memory (VMem) and Session Residency (Plan §6)."""

import json
import os
import subprocess
import sys

import pytest

from second_brain import db, semantic
from second_brain.errors import BrainError
from second_brain.paths import db_path
from second_brain.vmem import (
    ResidencyState,
    SessionObjectKind,
    VMemStore,
    resolve_object,
)

_CLEAN_ENV = {**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""}


def _run_vmem_cli(args: list[str], brain_home) -> subprocess.CompletedProcess:
    """Small DRY helper matching TestVMemCLI's existing subprocess pattern."""
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "vmem", *args, "--home", str(brain_home)],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


def _insert_delivery_row(
    brain_home, delivery_id: str, memory_id: str, memory_version: int = 1
) -> None:
    """Insert one row into the real, durable `deliveries` table (control DB
    `db/brain.sqlite`) — same table `autoinject.insert_deliveries` writes and
    `_delivered_keys` reads. Direct SQL here mirrors that existing schema
    exactly (no new table/abstraction) so the test does not need to drive
    the full retrieval/injection pipeline just to produce one row."""
    conn = db.connect(db_path(brain_home))
    try:
        conn.execute(
            "INSERT INTO deliveries (delivery_id, root_session_id, agent_session_id, "
            "branch_id, memory_id, memory_version, canonical_hash, packet_id, "
            "delivered_event_id, delivered_at, superseded_by_delivery_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                delivery_id,
                "sess-resolve",
                "sess-resolve",
                "main",
                memory_id,
                memory_version,
                "test-canonical-hash",
                "pkt-test",
                f"ev-{delivery_id}",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


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


class TestVMemStoreMetadata:
    """Part C: `--metadata` flag threads into VMemStore.store_object's
    existing (previously unused-by-any-caller) `metadata` field."""

    def test_metadata_roundtrips_through_store_and_list(self, brain_home):
        store = VMemStore(brain_home, "sess-meta-1")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="rtd_artifact",
            content="artifact pointer payload",
            metadata={"toolCallId": "call-abc123"},
        )
        assert obj.metadata == {"toolCallId": "call-abc123"}

        fetched = store.get_object(obj.obj_id)
        assert fetched is not None
        assert fetched.metadata == {"toolCallId": "call-abc123"}

        listed = store.list_objects(kind=SessionObjectKind.TOOL_OBSERVATION)
        assert len(listed) == 1
        assert listed[0].metadata == {"toolCallId": "call-abc123"}

    def test_absent_metadata_defaults_to_empty_dict(self, brain_home):
        store = VMemStore(brain_home, "sess-meta-2")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC, title="no-metadata", content="plain"
        )
        assert obj.metadata == {}
        refetched_default = store.get_object(obj.obj_id)
        assert refetched_default is not None
        assert refetched_default.metadata == {}

    def test_cli_metadata_flag_roundtrips_through_store_and_list(self, brain_home, tmp_path):
        content_file = tmp_path / "obs.txt"
        content_file.write_text("cli metadata roundtrip content", encoding="utf-8")
        store_res = _run_vmem_cli(
            [
                "store",
                "sess-meta-cli",
                "TOOL_OBSERVATION",
                "rtd_artifact",
                str(content_file),
                "--metadata",
                '{"toolCallId": "call-xyz"}',
                "--json",
            ],
            brain_home,
        )
        assert store_res.returncode == 0, store_res.stderr
        data = json.loads(store_res.stdout)
        assert data["metadata"] == {"toolCallId": "call-xyz"}

        list_res = _run_vmem_cli(["list", "sess-meta-cli", "--json"], brain_home)
        assert list_res.returncode == 0
        items = json.loads(list_res.stdout)
        assert items[0]["metadata"] == {"toolCallId": "call-xyz"}

    def test_cli_metadata_flag_absent_defaults_to_empty_dict(self, brain_home, tmp_path):
        content_file = tmp_path / "obs2.txt"
        content_file.write_text("no metadata here", encoding="utf-8")
        store_res = _run_vmem_cli(
            ["store", "sess-meta-cli-2", "GENERIC", "plain", str(content_file), "--json"],
            brain_home,
        )
        assert store_res.returncode == 0, store_res.stderr
        data = json.loads(store_res.stdout)
        assert data["metadata"] == {}

    def test_cli_metadata_flag_rejects_invalid_json(self, brain_home, tmp_path):
        content_file = tmp_path / "obs3.txt"
        content_file.write_text("x", encoding="utf-8")
        store_res = _run_vmem_cli(
            [
                "store",
                "sess-meta-cli-3",
                "GENERIC",
                "plain",
                str(content_file),
                "--metadata",
                "not-json",
                "--json",
            ],
            brain_home,
        )
        assert store_res.returncode != 0
        assert "metadata" in store_res.stderr.lower()

    def test_cli_metadata_flag_rejects_non_object_json(self, brain_home, tmp_path):
        content_file = tmp_path / "obs4.txt"
        content_file.write_text("x", encoding="utf-8")
        store_res = _run_vmem_cli(
            [
                "store",
                "sess-meta-cli-4",
                "GENERIC",
                "plain",
                str(content_file),
                "--metadata",
                "[1, 2, 3]",
                "--json",
            ],
            brain_home,
        )
        assert store_res.returncode != 0
        assert "metadata" in store_res.stderr.lower()


class TestVMemResolve:
    """Part D: `vmem resolve` — explicit fault-in + durable backing
    resolution (RESEARCH_RESULT -> deliveries+memories, TOOL_OBSERVATION ->
    content-addressed artifact store, anything else -> raw passthrough).
    Fails open and clearly on any missing/corrupt backing reference."""

    def test_research_result_resolves_real_delivery_to_real_memory_content(self, brain_home):
        memory_id = semantic.add_memory(
            brain_home,
            "Resolve Test Memory",
            "Body text for the vmem resolve test.",
            scope="global",
        )
        _insert_delivery_row(brain_home, "del-resolve-1", memory_id)

        store = VMemStore(brain_home, "sess-resolve")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-resolve-1", "packet_tokens": 12}),
            metadata={"deliveryId": "del-resolve-1"},
        )
        # Evict so this is a real EVICTED->fault-in cycle, not just RESIDENT.
        store.evict_to_budget(max_tokens=0)
        evicted = store.get_object(obj.obj_id)
        assert evicted is not None
        assert evicted.residency_state == ResidencyState.EVICTED

        result = resolve_object(brain_home, "sess-resolve", obj.obj_id)
        assert result["ok"] is True
        assert result["resolution"] == "memory"
        assert result["memory_id"] == memory_id
        assert "Resolve Test Memory" in result["content"]
        assert "Body text for the vmem resolve test." in result["content"]

        # Fault-in transitioned residency (existing, reused fault_in()).
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.FAULTED_IN

    def test_research_result_missing_delivery_is_structured_failure_not_a_crash(self, brain_home):
        store = VMemStore(brain_home, "sess-resolve-2")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-does-not-exist"}),
            metadata={"deliveryId": "del-does-not-exist"},
        )
        result = resolve_object(brain_home, "sess-resolve-2", obj.obj_id)
        assert result["ok"] is False
        assert "del-does-not-exist" in result["error"]

    def test_tool_observation_resolves_byte_exact_via_artifact_store(self, brain_home):
        from second_brain import artifacts

        raw_text = "line one\nline two with éè unicode\n"
        info = artifacts.store_text(brain_home, raw_text, kind="rtd_raw", tool="bash")

        store = VMemStore(brain_home, "sess-resolve-3")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="rtd_artifact",
            content=json.dumps({"artifact_ref": info["handle"], "command_class": "pytest"}),
            metadata={"toolCallId": "call-1"},
        )
        store.evict_to_budget(max_tokens=0)

        result = resolve_object(brain_home, "sess-resolve-3", obj.obj_id)
        assert result["ok"] is True
        assert result["resolution"] == "artifact"
        assert result["byte_exact"] is True
        assert result["content"] == raw_text  # BYTE-EXACT (round-tripped as text)

    def test_tool_observation_missing_artifact_is_structured_failure_not_a_crash(self, brain_home):
        store = VMemStore(brain_home, "sess-resolve-4")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="rtd_artifact",
            content=json.dumps({"artifact_ref": "[brain-artifact:sha256:" + "a" * 64 + "]"}),
            metadata={"toolCallId": "call-2"},
        )
        result = resolve_object(brain_home, "sess-resolve-4", obj.obj_id)
        assert result["ok"] is False
        assert "error" in result

    def test_unparsable_metadata_and_content_is_structured_failure_not_a_crash(self, brain_home):
        store = VMemStore(brain_home, "sess-resolve-5")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content="not json at all",
        )
        result = resolve_object(brain_home, "sess-resolve-5", obj.obj_id)
        assert result["ok"] is False
        assert "delivery_id" in result["error"]

    def test_unknown_kind_is_raw_passthrough_not_a_crash(self, brain_home):
        store = VMemStore(brain_home, "sess-resolve-6")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC,
            title="scratch note",
            content="plain unresolved content",
        )
        result = resolve_object(brain_home, "sess-resolve-6", obj.obj_id)
        assert result["ok"] is True
        assert result["resolution"] == "raw"
        assert result["content"] == "plain unresolved content"

    def test_unknown_obj_id_is_structured_failure_not_a_crash(self, brain_home):
        result = resolve_object(brain_home, "sess-resolve-7", "obj-doesnotexist000")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_page_subcommand_contract_is_unchanged(self, brain_home, tmp_path):
        """Additive-only guardrail: `resolve` must not alter `page`'s
        existing behavior/contract."""
        content_file = tmp_path / "page.txt"
        content_file.write_text("page contract unchanged", encoding="utf-8")
        store_res = _run_vmem_cli(
            ["store", "sess-page-1", "GENERIC", "plain", str(content_file), "--json"],
            brain_home,
        )
        obj_id = json.loads(store_res.stdout)["obj_id"]
        page_res = _run_vmem_cli(["page", "sess-page-1", obj_id], brain_home)
        assert page_res.returncode == 0
        assert page_res.stdout == "page contract unchanged"

    def test_cli_resolve_research_result_json_mode(self, brain_home):
        memory_id = semantic.add_memory(
            brain_home, "CLI Resolve Memory", "CLI resolve body text.", scope="global"
        )
        _insert_delivery_row(brain_home, "del-cli-1", memory_id)
        store = VMemStore(brain_home, "sess-resolve-cli-1")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-cli-1"}),
            metadata={"deliveryId": "del-cli-1"},
        )
        res = _run_vmem_cli(["resolve", "sess-resolve-cli-1", obj.obj_id, "--json"], brain_home)
        assert res.returncode == 0, res.stderr
        data = json.loads(res.stdout)
        assert data["ok"] is True
        assert "CLI Resolve Memory" in data["content"]

    def test_cli_resolve_tool_observation_text_mode_byte_exact(self, brain_home):
        from second_brain import artifacts

        raw_text = "byte exact CLI recovery text\nsecond line\n"
        info = artifacts.store_text(brain_home, raw_text, kind="rtd_raw", tool="bash")
        store = VMemStore(brain_home, "sess-resolve-cli-2")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="rtd_artifact",
            content=json.dumps({"artifact_ref": info["handle"]}),
            metadata={"toolCallId": "call-cli-2"},
        )
        res = _run_vmem_cli(["resolve", "sess-resolve-cli-2", obj.obj_id], brain_home)
        assert res.returncode == 0, res.stderr
        assert res.stdout == raw_text

    def test_cli_resolve_failure_json_mode_structured_nonzero_exit(self, brain_home):
        store = VMemStore(brain_home, "sess-resolve-cli-3")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-missing-cli"}),
            metadata={"deliveryId": "del-missing-cli"},
        )
        res = _run_vmem_cli(["resolve", "sess-resolve-cli-3", obj.obj_id, "--json"], brain_home)
        assert res.returncode != 0
        data = json.loads(res.stdout)
        assert data["ok"] is False
        assert "error" in data

    def test_cli_resolve_failure_text_mode_stderr_nonzero_exit_never_crashes(self, brain_home):
        res = _run_vmem_cli(["resolve", "sess-resolve-cli-4", "obj-nope000000"], brain_home)
        assert res.returncode != 0
        assert "Error" in res.stderr
        assert "Traceback" not in res.stderr  # never an unhandled exception
