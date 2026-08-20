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
    brain_home,
    delivery_id: str,
    memory_id: str,
    memory_version: int = 1,
    *,
    packet_id: str = "pkt-test",
    root_session_id: str = "sess-resolve",
    branch_id: str = "main",
) -> None:
    """Insert one row into the real, durable `deliveries` table (control DB
    `db/brain.sqlite`) — same table `autoinject.insert_deliveries` writes and
    `_delivered_keys` reads. Direct SQL here mirrors that existing schema
    exactly (no new table/abstraction) so the test does not need to drive
    the full retrieval/injection pipeline just to produce one row.

    `packet_id`/`root_session_id`/`branch_id` are overridable (defaulting to
    the original single-row test shape) so multi-item-packet tests can
    insert several rows that legitimately share one packet scope."""
    conn = db.connect(db_path(brain_home))
    try:
        conn.execute(
            "INSERT INTO deliveries (delivery_id, root_session_id, agent_session_id, "
            "branch_id, memory_id, memory_version, canonical_hash, packet_id, "
            "delivered_event_id, delivered_at, superseded_by_delivery_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                delivery_id,
                root_session_id,
                root_session_id,
                branch_id,
                memory_id,
                memory_version,
                "test-canonical-hash",
                packet_id,
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



def _snapshot(store: VMemStore, obj_id: str):
    """(residency_state, access_count, priority_score) for byte-for-byte
    unchanged-on-failure assertions. `None` if the object does not exist."""
    obj = store.get_object(obj_id)
    if obj is None:
        return None
    return (obj.residency_state, obj.access_count, obj.priority_score)


class TestVMemFaultInTransactional:
    """RC4 safety pass Part 1: `resolve_object` must be transactional w.r.t.
    recovery. On ANY failure (unknown object, missing/corrupt own backing
    artifact, missing delivery, missing memory, missing RTD artifact) NO DB
    write happens — residency_state/access_count/priority_score are
    byte-for-byte unchanged. The one DB write only happens after every
    read-only verification/resolution step has already succeeded."""

    def test_unknown_object_is_structured_failure_with_zero_mutation(self, brain_home):
        store = VMemStore(brain_home, "sess-tx-unknown")
        assert store.get_object("obj-neverexisted00") is None

        result = resolve_object(brain_home, "sess-tx-unknown", "obj-neverexisted00")

        assert result["ok"] is False
        assert "error" in result
        assert store.get_object("obj-neverexisted00") is None

    def test_missing_own_backing_artifact_is_structured_failure_with_zero_mutation(
        self, brain_home
    ):
        store = VMemStore(brain_home, "sess-tx-missing-own")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-irrelevant"}),
            metadata={"deliveryId": "del-irrelevant"},
        )
        before = _snapshot(store, obj.obj_id)

        # Remove the object's OWN tiny stored VMem backing artifact out from
        # under it (both meta and blob, matching "deleted... artifact file").
        meta_path = (
            brain_home / "state" / "artifacts" / "meta" / f"{obj.content_sha256}.json"
        )
        assert meta_path.exists()
        meta_path.unlink()

        result = resolve_object(brain_home, "sess-tx-missing-own", obj.obj_id)

        assert result["ok"] is False
        assert "error" in result
        after = _snapshot(store, obj.obj_id)
        assert after == before

    def test_corrupt_own_backing_artifact_is_structured_failure_with_zero_mutation(
        self, brain_home
    ):
        store = VMemStore(brain_home, "sess-tx-corrupt-own")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-irrelevant"}),
            metadata={"deliveryId": "del-irrelevant"},
        )
        before = _snapshot(store, obj.obj_id)

        # Corrupt the bytes in place: the blob file at the hash-named path
        # keeps existing, but its content no longer matches the sha256 the
        # stored VMem row records — a bit-rot / out-from-under-it scenario.
        blob_path = (
            brain_home / "state" / "artifacts" / "blobs" / f"{obj.content_sha256}.bin"
        )
        assert blob_path.exists()
        blob_path.write_bytes(b"corrupted bytes that do not match the recorded hash")

        result = resolve_object(brain_home, "sess-tx-corrupt-own", obj.obj_id)

        assert result["ok"] is False
        assert "error" in result
        after = _snapshot(store, obj.obj_id)
        assert after == before

    def test_missing_delivery_is_structured_failure_with_zero_mutation(self, brain_home):
        store = VMemStore(brain_home, "sess-tx-missing-delivery")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-does-not-exist-tx"}),
            metadata={"deliveryId": "del-does-not-exist-tx"},
        )
        before = _snapshot(store, obj.obj_id)

        result = resolve_object(brain_home, "sess-tx-missing-delivery", obj.obj_id)

        assert result["ok"] is False
        assert "del-does-not-exist-tx" in result["error"]
        after = _snapshot(store, obj.obj_id)
        assert after == before

    def test_missing_memory_is_structured_failure_with_zero_mutation(self, brain_home):
        _insert_delivery_row(brain_home, "del-tx-missing-memory", "mem-doesnotexisttx00")
        store = VMemStore(brain_home, "sess-tx-missing-memory")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-tx-missing-memory"}),
            metadata={"deliveryId": "del-tx-missing-memory"},
        )
        before = _snapshot(store, obj.obj_id)

        result = resolve_object(brain_home, "sess-tx-missing-memory", obj.obj_id)

        assert result["ok"] is False
        assert "error" in result
        after = _snapshot(store, obj.obj_id)
        assert after == before

    def test_missing_rtd_artifact_is_structured_failure_with_zero_mutation(self, brain_home):
        store = VMemStore(brain_home, "sess-tx-missing-rtd")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="rtd_artifact",
            content=json.dumps(
                {"artifact_ref": "[brain-artifact:sha256:" + "b" * 64 + "]"}
            ),
            metadata={"toolCallId": "call-tx-missing-rtd"},
        )
        before = _snapshot(store, obj.obj_id)

        result = resolve_object(brain_home, "sess-tx-missing-rtd", obj.obj_id)

        assert result["ok"] is False
        assert "error" in result
        after = _snapshot(store, obj.obj_id)
        assert after == before

    def test_successful_research_result_fault_in_mutates_exactly_once(self, brain_home):
        memory_id = semantic.add_memory(
            brain_home, "TX Success Memory", "TX success body text.", scope="global"
        )
        _insert_delivery_row(brain_home, "del-tx-success-1", memory_id)
        store = VMemStore(brain_home, "sess-tx-success-research")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-tx-success-1"}),
            metadata={"deliveryId": "del-tx-success-1"},
        )
        store.evict_to_budget(max_tokens=0)
        before = _snapshot(store, obj.obj_id)
        assert before is not None
        assert before[0] == ResidencyState.EVICTED

        result = resolve_object(brain_home, "sess-tx-success-research", obj.obj_id)

        assert result["ok"] is True
        assert result["resolution"] == "memory"
        assert result["memory_id"] == memory_id
        after = _snapshot(store, obj.obj_id)
        assert after is not None
        assert after[0] == ResidencyState.FAULTED_IN
        assert after[1] == before[1] + 1  # access_count incremented exactly once
        assert after[2] == before[2] + 5.0  # priority boosted exactly once

    def test_successful_tool_observation_fault_in_mutates_exactly_once_byte_exact(
        self, brain_home
    ):
        from second_brain import artifacts

        raw_text = "TX success tool observation byte-exact content\n"
        info = artifacts.store_text(brain_home, raw_text, kind="rtd_raw", tool="bash")
        store = VMemStore(brain_home, "sess-tx-success-tool")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="rtd_artifact",
            content=json.dumps({"artifact_ref": info["handle"]}),
            metadata={"toolCallId": "call-tx-success-1"},
        )
        store.evict_to_budget(max_tokens=0)
        before = _snapshot(store, obj.obj_id)
        assert before is not None
        assert before[0] == ResidencyState.EVICTED

        result = resolve_object(brain_home, "sess-tx-success-tool", obj.obj_id)

        assert result["ok"] is True
        assert result["byte_exact"] is True
        assert result["content"] == raw_text
        after = _snapshot(store, obj.obj_id)
        assert after is not None
        assert after[0] == ResidencyState.FAULTED_IN
        assert after[1] == before[1] + 1
        assert after[2] == before[2] + 5.0

    def test_repeated_successful_fault_in_keeps_working_and_keeps_incrementing(
        self, brain_home
    ):
        memory_id = semantic.add_memory(
            brain_home, "TX Repeat Memory", "TX repeat body text.", scope="global"
        )
        _insert_delivery_row(brain_home, "del-tx-repeat-1", memory_id)
        store = VMemStore(brain_home, "sess-tx-repeat")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-tx-repeat-1"}),
            metadata={"deliveryId": "del-tx-repeat-1"},
        )
        store.evict_to_budget(max_tokens=0)

        first = resolve_object(brain_home, "sess-tx-repeat", obj.obj_id)
        assert first["ok"] is True
        after_first = store.get_object(obj.obj_id)
        assert after_first is not None
        assert after_first.residency_state == ResidencyState.FAULTED_IN
        assert after_first.access_count == 2

        # Second call on an object already FAULTED_IN: no crash, state stays
        # FAULTED_IN (unchanged, not reset), access_count keeps incrementing.
        second = resolve_object(brain_home, "sess-tx-repeat", obj.obj_id)
        assert second["ok"] is True
        after_second = store.get_object(obj.obj_id)
        assert after_second is not None
        assert after_second.residency_state == ResidencyState.FAULTED_IN
        assert after_second.access_count == 3


class TestVMemMultiItemPacketResolution:
    """RC4 safety pass Part 2: an AutoInject delivery can carry MULTIPLE
    selected memories (one `deliveries` row per item, same `packet_id`).
    `_resolve_research_result` must recover the COMPLETE packet from the one
    delivery_id captured at VMem admission time, not just that one item."""

    def test_four_item_packet_reconstructs_all_members_not_just_first(self, brain_home):
        packet_id = "pkt-four-item-tx"
        root_session_id = "sess-tx-packet"
        branch_id = "main"

        memory_ids = []
        for i in range(4):
            mid = semantic.add_memory(
                brain_home,
                f"Packet Member Memory {i}",
                f"Unique packet member body text {i}.",
                scope="global",
            )
            memory_ids.append(mid)

        delivery_ids = [f"del-tx-packet-{i}" for i in range(4)]
        for did, mid in zip(delivery_ids, memory_ids, strict=True):
            _insert_delivery_row(
                brain_home,
                did,
                mid,
                packet_id=packet_id,
                root_session_id=root_session_id,
                branch_id=branch_id,
            )

        # VMem admission shape: only the FIRST delivery_id of the packet is
        # captured on the stored object (matches `lifecycle.last_delivery_ids[0]`
        # at the real CLI call sites).
        store = VMemStore(brain_home, "sess-tx-packet")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": delivery_ids[0]}),
            metadata={"deliveryId": delivery_ids[0]},
        )
        store.evict_to_budget(max_tokens=0)

        result = resolve_object(brain_home, "sess-tx-packet", obj.obj_id)

        assert result["ok"] is True
        assert result["resolution"] == "memory_set"
        assert result["item_count"] == 4
        assert set(result["memory_ids"]) == set(memory_ids)
        assert set(result["delivery_ids"]) == set(delivery_ids)

        parsed = json.loads(result["content"])
        assert parsed["packet_id"] == packet_id
        assert len(parsed["items"]) == 4
        # Deterministic order (rowid / insertion order), not just membership.
        assert [it["memory_id"] for it in parsed["items"]] == memory_ids
        assert [it["delivery_id"] for it in parsed["items"]] == delivery_ids
        for i, it in enumerate(parsed["items"]):
            assert f"Unique packet member body text {i}." in it["body"]

        # Recovery mutated residency exactly once, same as the single-item path.
        after = store.get_object(obj.obj_id)
        assert after is not None
        assert after.residency_state == ResidencyState.FAULTED_IN

    def test_packet_with_one_unresolvable_member_fails_whole_resolution_no_partial(
        self, brain_home
    ):
        packet_id = "pkt-partial-fail-tx"
        root_session_id = "sess-tx-packet-partial"
        branch_id = "main"

        good_memory_id = semantic.add_memory(
            brain_home, "Partial Packet Good Memory", "Good body.", scope="global"
        )
        _insert_delivery_row(
            brain_home,
            "del-tx-partial-good",
            good_memory_id,
            packet_id=packet_id,
            root_session_id=root_session_id,
            branch_id=branch_id,
        )
        _insert_delivery_row(
            brain_home,
            "del-tx-partial-bad",
            "mem-doesnotexistpartial",
            packet_id=packet_id,
            root_session_id=root_session_id,
            branch_id=branch_id,
        )

        store = VMemStore(brain_home, "sess-tx-packet-partial")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-tx-partial-good"}),
            metadata={"deliveryId": "del-tx-partial-good"},
        )
        before = _snapshot(store, obj.obj_id)

        result = resolve_object(brain_home, "sess-tx-packet-partial", obj.obj_id)

        # Simplest safe option: any unresolvable member fails the WHOLE
        # fault-in for this object — no silent partial/incomplete set.
        assert result["ok"] is False
        assert "error" in result
        after = _snapshot(store, obj.obj_id)
        assert after == before
