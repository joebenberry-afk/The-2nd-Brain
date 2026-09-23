"""Tests for Context Virtual Memory (VMem) and Session Residency (Plan §6)."""

import json
import sqlite3
import subprocess
import sys
from typing import Any

import pytest

from conftest import clean_python_env
from second_brain import db, semantic
from second_brain.errors import BrainError
from second_brain.paths import db_path
from second_brain.vmem import (
    ResidencyState,
    SessionObject,
    SessionObjectKind,
    VMemStore,
    resolve_object,
)

_CLEAN_ENV = clean_python_env()


def test_vmem_store_uses_its_custom_home_calibration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(tmp_path / "default"))
    calibration = tmp_path / "custom" / "state" / "calibration"
    calibration.mkdir(parents=True)
    (calibration / "tokens.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "default",
                "default_chars_per_token": 2.0,
                "models": {},
            }
        ),
        encoding="utf-8",
    )
    store = VMemStore(tmp_path / "custom", "session-custom")
    obj = store.store_object(SessionObjectKind.GENERIC, "title", "x" * 10)
    assert obj.token_estimate == 5


def _run_vmem_cli(
    args: list[str], brain_home, stdin: str | None = None
) -> subprocess.CompletedProcess:
    """Small DRY helper matching TestVMemCLI's existing subprocess pattern."""
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "vmem", *args, "--home", str(brain_home)],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        input=stdin,
    )


@pytest.mark.parametrize("from_stdin", [False, True])
def test_cli_store_preserves_utf8_bytes_and_mixed_newlines(brain_home, tmp_path, from_stdin):
    payload = b"first\r\ncaf\xc3\xa9\rthird\n"
    args = ["store", "byte-preservation", "RESEARCH_RESULT", "Exact text"]
    if not from_stdin:
        source = tmp_path / "source.txt"
        source.write_bytes(payload)
        args.append(str(source))
    saved = subprocess.run(
        [sys.executable, "-m", "second_brain", "vmem", *args, "--home", str(brain_home), "--json"],
        input=payload if from_stdin else None,
        capture_output=True,
        env=_CLEAN_ENV,
        check=True,
    )
    obj_id = json.loads(saved.stdout)["obj_id"]
    assert (
        _run_vmem_cli(["compact-prep", "byte-preservation", "--json"], brain_home).returncode == 0
    )
    resolved = _run_vmem_cli(["resolve", "byte-preservation", obj_id, "--json"], brain_home)
    assert resolved.returncode == 0, resolved.stderr
    assert json.loads(resolved.stdout)["content"].encode("utf-8") == payload
    for command in ("page", "resolve"):
        plain = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "vmem",
                command,
                "byte-preservation",
                obj_id,
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            env=_CLEAN_ENV,
            check=True,
        )
        assert plain.stdout == payload


def test_cli_store_refuses_invalid_utf8_without_replacement(brain_home, tmp_path):
    source = tmp_path / "not-text.bin"
    source.write_bytes(b"invalid \xff content")
    result = _run_vmem_cli(
        ["store", "bad-encoding", "RESEARCH_RESULT", "Invalid text", str(source), "--json"],
        brain_home,
    )
    assert result.returncode == 2
    assert VMemStore(brain_home, "bad-encoding").list_objects() == []


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

    def test_store_object_registers_artifact_ref(self, brain_home):
        from second_brain import ledger as ledger_mod

        store = VMemStore(brain_home, "sess-vmem-artifact-ref")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC, title="ref check", content="registered content"
        )
        internal_id = ledger_mod.internal_session_id("sess-vmem-artifact-ref")
        conn = db.connect(db_path(brain_home), readonly=True)
        row = conn.execute(
            "SELECT COUNT(*) FROM artifact_refs WHERE sha = ? AND owner = ?",
            (obj.content_sha256, f"vmem:{internal_id}"),
        ).fetchone()
        conn.close()
        assert row[0] == 1

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


class TestVMemClaimPages:
    """Defect B (RC4 proactive-paging-repair pass): VMemStore.claim_pages --
    the atomic compare-and-set primitive proactive (pre-compaction) paging
    uses to cause the RESIDENT/FAULTED_IN -> EVICTED transition itself,
    before a real compaction event ever runs prepare_compaction()."""

    def test_claim_pages_transitions_resident_to_evicted(self, brain_home):
        store = VMemStore(brain_home, "sess-claim-1")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Claimable",
            content="claim me",
            pinned=False,
        )
        assert obj.residency_state == ResidencyState.RESIDENT

        claimed = store.claim_pages([{"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"}])

        assert claimed == [obj.obj_id]
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.EVICTED

    def test_claim_pages_faulted_in_object_is_claimable(self, brain_home):
        """Matches evict_to_budget's own existing precedent of treating
        FAULTED_IN as evictable too (documented policy choice, tested)."""
        store = VMemStore(brain_home, "sess-claim-2")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="Faulted back in",
            content="content",
            pinned=False,
        )
        store.evict_to_budget(max_tokens=0)  # force EVICTED
        store.fault_in(obj.obj_id)  # EVICTED -> FAULTED_IN
        faulted = store.get_object(obj.obj_id)
        assert faulted is not None and faulted.residency_state == ResidencyState.FAULTED_IN

        claimed = store.claim_pages([{"obj_id": obj.obj_id, "kind": "TOOL_OBSERVATION"}])

        assert claimed == [obj.obj_id]
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None and refetched.residency_state == ResidencyState.EVICTED

    def test_claim_pages_pinned_object_never_claimed(self, brain_home):
        store = VMemStore(brain_home, "sess-claim-3")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Pinned",
            content="content",
            pinned=True,
        )
        assert obj.residency_state == ResidencyState.RESIDENT

        claimed = store.claim_pages([{"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"}])

        assert claimed == []
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.RESIDENT  # unchanged

    def test_claim_pages_kind_mismatch_never_claims(self, brain_home):
        store = VMemStore(brain_home, "sess-claim-4")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Wrong kind claim attempt",
            content="content",
            pinned=False,
        )

        # The request's kind does not match the object's ACTUAL stored kind.
        claimed = store.claim_pages([{"obj_id": obj.obj_id, "kind": "TOOL_OBSERVATION"}])

        assert claimed == []
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.RESIDENT  # unchanged

    def test_claim_pages_already_evicted_is_idempotent_no_error(self, brain_home):
        store = VMemStore(brain_home, "sess-claim-6")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Already evicted",
            content="content",
            pinned=False,
        )
        first = store.claim_pages([{"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"}])
        assert first == [obj.obj_id]

        # Requesting an already-EVICTED object again: deterministic, safe,
        # idempotent -- not claimed again, no error.
        second = store.claim_pages([{"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"}])
        assert second == []
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.EVICTED

    def test_claim_pages_malformed_requests_silently_skipped(self, brain_home):
        store = VMemStore(brain_home, "sess-claim-7")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Real object",
            content="content",
            pinned=False,
        )
        malformed_requests: list[dict[str, Any]] = [
            {"obj_id": "", "kind": "RESEARCH_RESULT"},  # empty obj_id
            {"kind": "RESEARCH_RESULT"},  # missing obj_id
            {"obj_id": "obj-nonexistent"},  # missing kind
            {"obj_id": 123, "kind": "RESEARCH_RESULT"},  # non-string obj_id
            {"obj_id": obj.obj_id, "kind": None},  # non-string kind
            "not even a dict",  # type: ignore[list-item]  # malformed entry entirely
            {"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"},  # the one real, valid request
        ]
        claimed = store.claim_pages(malformed_requests)
        assert claimed == [obj.obj_id]

    def test_claim_pages_empty_requests_returns_empty(self, brain_home):
        store = VMemStore(brain_home, "sess-claim-8")
        assert store.claim_pages([]) == []

    def test_claim_pages_concurrency_cas_only_one_caller_wins(self, brain_home):
        """CAS guarantee (sequential proxy for real concurrency, per this
        campaign's testing precedent): two calls racing to claim the SAME
        obj_id -- only the first ever actually wins; the second's own
        UPDATE WHERE clause finds the row already EVICTED and reports it as
        NOT claimed, deterministically, with no error."""
        store = VMemStore(brain_home, "sess-claim-9")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Race target",
            content="content",
            pinned=False,
        )
        req = [{"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"}]

        first_result = store.claim_pages(req)
        second_result = store.claim_pages(req)

        assert first_result == [obj.obj_id]
        assert second_result == []  # lost the race -- current DB state is authoritative

    def test_claim_pages_session_isolation(self, brain_home):
        """An object belonging to a DIFFERENT session must never be
        claimable by another session's claim_pages call, and its state
        must remain unchanged."""
        store_a = VMemStore(brain_home, "sess-claim-session-a")
        store_b = VMemStore(brain_home, "sess-claim-session-b")
        obj_a = store_a.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Session A object",
            content="content",
            pinned=False,
        )

        # Attempt to claim session A's object through session B's store.
        claimed_by_b = store_b.claim_pages([{"obj_id": obj_a.obj_id, "kind": "RESEARCH_RESULT"}])

        assert claimed_by_b == []
        refetched = store_a.get_object(obj_a.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.RESIDENT  # unchanged


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

    def test_compaction_barrier_safe_with_already_proactively_evicted_object(self, brain_home):
        """Defect B regression: prepare_compaction() remains safe/idempotent
        when some objects were already proactively EVICTED (via
        claim_pages) before a real compaction event runs. An already-
        EVICTED object simply falls outside prepare_compaction()'s own
        `residency_state in (RESIDENT, FAULTED_IN)` filter -- it is not
        double-counted, and no error occurs."""
        store = VMemStore(brain_home, "sess-vmem-compaction-with-claim")

        pinned = store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Pinned",
            content="Survives compaction",
            pinned=True,
        )
        proactively_claimed = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Already proactively paged",
            content="Paged before compaction",
            pinned=False,
        )
        still_resident = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Still resident at compaction time",
            content="Evicted at compaction",
            pinned=False,
        )

        # Proactive claim happens BEFORE compaction (Defect B fix).
        claimed = store.claim_pages(
            [{"obj_id": proactively_claimed.obj_id, "kind": "RESEARCH_RESULT"}]
        )
        assert claimed == [proactively_claimed.obj_id]
        claimed_obj = store.get_object(proactively_claimed.obj_id)
        assert claimed_obj is not None and claimed_obj.residency_state == ResidencyState.EVICTED

        # Real compaction now runs -- must count only the OTHER still-
        # RESIDENT object, not the one already proactively evicted, and
        # must not error.
        prep = store.prepare_compaction()
        assert prep["evicted_at_compaction"] == 1  # only `still_resident`
        assert prep["pinned_preserved"] == 1

        pinned_after = store.get_object(pinned.obj_id)
        claimed_after = store.get_object(proactively_claimed.obj_id)
        resident_after = store.get_object(still_resident.obj_id)
        assert pinned_after is not None
        assert pinned_after.residency_state == ResidencyState.RESIDENT
        assert claimed_after is not None
        assert claimed_after.residency_state == ResidencyState.EVICTED
        assert resident_after is not None
        assert resident_after.residency_state == ResidencyState.EVICTED


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
            env=clean_python_env(),
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
            env=clean_python_env(),
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
            env=clean_python_env(),
        )
        assert page_res.returncode == 0
        assert "Discovered cache optimization via CLI" in page_res.stdout

    def test_vmem_cli_claim_pages_end_to_end(self, brain_home):
        """Defect B (RC4 proactive-paging-repair pass): the `claim-pages`
        CLI subcommand reads {"candidates": [...]} from stdin, calls
        VMemStore.claim_pages, and prints the JSON list of obj_ids
        actually claimed."""
        store = VMemStore(brain_home, "sess-cli-claim-1")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="CLI claim target",
            content="claim me via CLI",
            pinned=False,
        )
        assert obj.residency_state == ResidencyState.RESIDENT

        payload = json.dumps({"candidates": [{"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"}]})
        claim_res = _run_vmem_cli(
            ["claim-pages", "sess-cli-claim-1", "--json"], brain_home, stdin=payload
        )
        assert claim_res.returncode == 0, claim_res.stderr
        claimed = json.loads(claim_res.stdout)
        assert claimed == [obj.obj_id]

        # Real DB state check: the object transitioned to EVICTED.
        list_res = _run_vmem_cli(["list", "sess-cli-claim-1", "--json"], brain_home)
        assert list_res.returncode == 0
        items = json.loads(list_res.stdout)
        assert items[0]["obj_id"] == obj.obj_id
        assert items[0]["residency_state"] == "EVICTED"

    def test_vmem_cli_claim_pages_non_json_stdin_errors_cleanly(self, brain_home):
        res = _run_vmem_cli(
            ["claim-pages", "sess-cli-claim-2", "--json"], brain_home, stdin="not json"
        )
        assert res.returncode == 2
        assert "must be valid JSON" in res.stderr

    def test_vmem_cli_claim_pages_missing_candidates_key_errors_cleanly(self, brain_home):
        res = _run_vmem_cli(
            ["claim-pages", "sess-cli-claim-3", "--json"], brain_home, stdin=json.dumps({})
        )
        assert res.returncode == 2
        assert "candidates" in res.stderr

    def test_vmem_cli_claim_pages_non_json_mode_text_summary(self, brain_home):
        store = VMemStore(brain_home, "sess-cli-claim-4")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Text mode claim",
            content="claim me",
            pinned=False,
        )
        payload = json.dumps({"candidates": [{"obj_id": obj.obj_id, "kind": "RESEARCH_RESULT"}]})
        res = _run_vmem_cli(["claim-pages", "sess-cli-claim-4"], brain_home, stdin=payload)
        assert res.returncode == 0
        assert "Claimed 1 of 1" in res.stdout
        assert obj.obj_id in res.stdout


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
            metadata={"deliveryId": None},
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
        meta_path = brain_home / "state" / "artifacts" / "meta" / f"{obj.content_sha256}.json"
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
        blob_path = brain_home / "state" / "artifacts" / "blobs" / f"{obj.content_sha256}.bin"
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
            content=json.dumps({"artifact_ref": "[brain-artifact:sha256:" + "b" * 64 + "]"}),
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

    def test_successful_tool_observation_fault_in_mutates_exactly_once_byte_exact(self, brain_home):
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

    def test_repeated_successful_fault_in_keeps_working_and_keeps_incrementing(self, brain_home):
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


class TestVMemByteExactAutoInjectRecovery:
    """RC4 byte-exact AutoInject recovery pass (Part A): the packet-artifact
    PRIMARY path returns EXACTLY what the model saw at delivery time,
    independent of later supersession; the FALLBACK path (no artifact) now
    resolves each packet member's DELIVERED version specifically instead of
    silently returning newer current content."""

    def test_artifact_preserved_packet_survives_supersede_byte_exact(self, brain_home):
        from second_brain import artifacts

        memory_id = semantic.add_memory(
            brain_home,
            "Byte-Exact Packet Memory",
            "Version 1 body text for the byte-exact packet test.",
            scope="global",
        )
        _insert_delivery_row(brain_home, "del-byteexact-1", memory_id)

        # Seed the EXACT v1 packet text the model actually saw, the same way
        # the real TS `cliArtifactPreserver` (kind="autoinject_packet",
        # tool="autoinject") would at admission time.
        packet_text = json.dumps(
            {
                "delivery_id": "del-byteexact-1",
                "packet_tokens": 42,
                "note": "This is the EXACT v1 packet text the model saw.",
            }
        )
        preserved = artifacts.store_text(
            brain_home, packet_text, kind="autoinject_packet", tool="autoinject"
        )

        store = VMemStore(brain_home, "sess-byteexact")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-byteexact-1", "packet_tokens": 42}),
            metadata={
                "deliveryId": "del-byteexact-1",
                "packetArtifactRef": preserved["handle"],
                "packetSha256": preserved["hash"],
            },
        )
        store.evict_to_budget(max_tokens=0)

        # Supersede the memory AFTER delivery -- the recovered packet must
        # NOT pick up this newer content.
        semantic.supersede(
            brain_home,
            memory_id,
            new_body="Version 2 body text -- MUST NOT appear in recovery.",
            change_note="v2 for byte-exact test",
        )

        result = resolve_object(brain_home, "sess-byteexact", obj.obj_id)

        assert result["ok"] is True
        assert result["resolution"] == "packet_artifact"
        assert result["byte_exact"] is True
        assert result["content"] == packet_text  # BYTE-EXACT v1, not v2
        assert "Version 2" not in result["content"]

        after = store.get_object(obj.obj_id)
        assert after is not None
        assert after.residency_state == ResidencyState.FAULTED_IN

    def test_fallback_no_artifact_resolves_delivered_version_not_current(self, brain_home):
        memory_id = semantic.add_memory(
            brain_home,
            "Fallback Delivered Version Memory",
            "Version 1 body for the fallback-path delivered-version test.",
            scope="global",
        )
        _insert_delivery_row(brain_home, "del-fallback-1", memory_id, memory_version=1)

        store = VMemStore(brain_home, "sess-fallback")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-fallback-1", "packet_tokens": 10}),
            metadata={"deliveryId": "del-fallback-1"},  # NO packetArtifactRef -> fallback path
        )
        store.evict_to_budget(max_tokens=0)

        semantic.supersede(
            brain_home,
            memory_id,
            new_title="Fallback Delivered Version Memory V2",
            new_body="Version 2 body -- MUST NOT be what fault-in returns.",
            change_note="v2 for fallback test",
        )

        result = resolve_object(brain_home, "sess-fallback", obj.obj_id)

        assert result["ok"] is True
        assert result["resolution"] == "memory"
        parsed = json.loads(result["content"])
        assert parsed["delivered_version"] == 1
        assert parsed["current_version"] == 2  # true current, reported distinctly
        assert "Version 1 body" in parsed["body"]
        assert "Version 2 body" not in parsed["body"]
        assert parsed["title"] == "Fallback Delivered Version Memory"  # v1 title, not v2's

    def test_four_item_packet_artifact_path_and_fallback_path_both_complete(self, brain_home):
        packet_id = "pkt-four-item-byteexact"
        root_session_id = "sess-byteexact-packet"
        branch_id = "main"

        memory_ids = []
        for i in range(4):
            mid = semantic.add_memory(
                brain_home,
                f"Byte-Exact Packet Member {i}",
                f"Byte-exact packet member body text {i}.",
                scope="global",
            )
            memory_ids.append(mid)

        delivery_ids = [f"del-byteexact-packet-{i}" for i in range(4)]
        for did, mid in zip(delivery_ids, memory_ids, strict=True):
            _insert_delivery_row(
                brain_home,
                did,
                mid,
                packet_id=packet_id,
                root_session_id=root_session_id,
                branch_id=branch_id,
            )

        # -- Fallback path (unchanged multi-item behavior, no artifact) --
        store = VMemStore(brain_home, root_session_id)
        fallback_obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": delivery_ids[0]}),
            metadata={"deliveryId": delivery_ids[0]},
        )
        store.evict_to_budget(max_tokens=0)
        fallback_result = resolve_object(brain_home, root_session_id, fallback_obj.obj_id)
        assert fallback_result["ok"] is True
        assert fallback_result["resolution"] == "memory_set"
        assert fallback_result["item_count"] == 4
        assert set(fallback_result["memory_ids"]) == set(memory_ids)

        # -- Artifact-preserved path (new): seed the exact packet bytes --
        from second_brain import artifacts

        packet_text = json.dumps({"packet_id": packet_id, "note": "byte-exact 4-item packet"})
        preserved = artifacts.store_text(
            brain_home, packet_text, kind="autoinject_packet", tool="autoinject"
        )
        artifact_obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            # Distinct content from `fallback_obj` above (obj_id is
            # content-hash-derived and re-storing IDENTICAL content only
            # bumps the EXISTING row's access_count -- it does not update
            # metadata_json) so this is genuinely a second, separate object.
            content=json.dumps({"delivery_id": delivery_ids[0], "variant": "artifact"}),
            metadata={
                "deliveryId": delivery_ids[0],
                "packetArtifactRef": preserved["handle"],
                "packetSha256": preserved["hash"],
            },
        )
        store.evict_to_budget(max_tokens=0)
        artifact_result = resolve_object(brain_home, root_session_id, artifact_obj.obj_id)
        assert artifact_result["ok"] is True
        assert artifact_result["resolution"] == "packet_artifact"
        assert artifact_result["content"] == packet_text


class TestVMemFaultInDbWriteFailOpen:
    """RC4 byte-exact recovery pass Part B: `resolve_object`'s final DB
    write (`VMemStore._mutate_fault_in`) must itself be fail-open. A failure
    THERE (SQLite busy/locked, disk I/O) must not propagate as an unhandled
    exception, and must not be reported as a successful fault-in -- the
    object's residency/access_count/priority_score stay exactly what they
    were before the call."""

    def test_mutate_fault_in_db_write_failure_is_structured_failure_zero_mutation(
        self, brain_home, monkeypatch
    ):
        memory_id = semantic.add_memory(
            brain_home, "DB Write Failure Memory", "Body text.", scope="global"
        )
        _insert_delivery_row(brain_home, "del-dbfail-1", memory_id)
        store = VMemStore(brain_home, "sess-dbfail")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="autoinject_delivery",
            content=json.dumps({"delivery_id": "del-dbfail-1"}),
            metadata={"deliveryId": "del-dbfail-1"},
        )
        store.evict_to_budget(max_tokens=0)
        before = _snapshot(store, obj.obj_id)
        assert before is not None
        assert before[0] == ResidencyState.EVICTED

        def _boom(self, obj):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(VMemStore, "_mutate_fault_in", _boom)

        result = resolve_object(brain_home, "sess-dbfail", obj.obj_id)

        assert result["ok"] is False
        assert "error" in result

        after = _snapshot(store, obj.obj_id)
        assert after == before  # zero mutation despite a fully-succeeded read-only resolution


class TestCostModelEvictionT21:
    """T2.1 Cost-model eviction tests (Deep Upgrade Plan U4 §5.3-5.7)."""

    def test_recent_large_cold_object_evicted_before_old_one(self, brain_home):
        """Recent large cold object (low suffix, high tokens -> high benefit,
        low invalidation cost) evicts before an older object with high suffix
        invalidation, even if the older object had lower base priority."""
        store = VMemStore(brain_home, "sess-cost-1")
        # Old object A: base priority 10 (tool observation), smaller tokens (200)
        obj_a = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="Old tool observation",
            content="a" * 800,  # ~200 tokens
            pinned=False,
        )
        # Recent object B: base priority 50 (research result), larger tokens (400)
        obj_b = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Recent research result",
            content="b" * 1600,  # ~400 tokens
            pinned=False,
        )
        total = obj_a.token_estimate + obj_b.token_estimate
        # Set budget so exactly one object needs to be evicted to fit
        budget = max(obj_a.token_estimate, obj_b.token_estimate)
        assert total > budget

        evicted = store.evict_to_budget(max_tokens=budget)

        # Cost model: obj_b has suffix 0, benefit = 400 * 8 * 0.1 = 320, cost ~ 22.5 -> net ~ +297.5
        # obj_a has suffix 400, cost = 400 * 1.15 + ... ~ 470, benefit = 160 -> net < 0
        # Therefore obj_b must be evicted before obj_a!
        assert len(evicted) == 1
        assert evicted[0].obj_id == obj_b.obj_id
        stored_a = store.get_object(obj_a.obj_id)
        stored_b = store.get_object(obj_b.obj_id)
        assert stored_a is not None
        assert stored_b is not None
        assert stored_a.residency_state == ResidencyState.RESIDENT
        assert stored_b.residency_state == ResidencyState.EVICTED

    def test_no_positive_net_means_no_eviction_under_budget_slack(self, brain_home):
        """Under-budget session performs no evictions even if candidates exist."""
        store = VMemStore(brain_home, "sess-cost-slack")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Cold result",
            content="some result content",
            pinned=False,
        )
        # Budget is well above resident tokens (budget slack)
        budget = obj.token_estimate + 1000
        evicted = store.evict_to_budget(max_tokens=budget)
        assert evicted == []
        stored = store.get_object(obj.obj_id)
        assert stored is not None
        assert stored.residency_state == ResidencyState.RESIDENT

    def test_forced_eviction_logged_when_over_budget(self, brain_home, caplog):
        """When all candidates have net <= 0 but session is over budget,
        fallback eviction occurs and logs forced_eviction=1."""
        import logging

        store = VMemStore(brain_home, "sess-forced-evict")
        # Store objects where net <= 0 for all
        # (e.g. decision/blocker with high p_fault and very low tokens or R=0)
        store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Decision 1",
            content="small 1",
            pinned=False,
        )
        store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Decision 2",
            content="small 2",
            pinned=False,
        )
        with caplog.at_level(logging.INFO):
            # Force budget to 0 so we must evict despite net <= 0
            evicted = store.evict_to_budget(max_tokens=0)

        assert len(evicted) > 0
        # forced_eviction=1 must appear in logs
        assert "forced_eviction=1" in caplog.text

    def test_eviction_records_decision_with_top_5_alternatives(self, brain_home):
        """Record decisions(kind='eviction', propensity=1.0) with chosen
        objects and top-5 alternative candidates by net score."""
        store = VMemStore(brain_home, "sess-decision-rec")
        # Store 7 candidates
        objs = []
        for i in range(7):
            o = store.store_object(
                kind=SessionObjectKind.RESEARCH_RESULT,
                title=f"Result {i}",
                content=f"content {i} " * 50,
                pinned=False,
            )
            objs.append(o)

        total = sum(o.token_estimate for o in objs)
        # Budget to evict top 1 or 2
        budget = total - objs[-1].token_estimate
        evicted = store.evict_to_budget(max_tokens=budget)
        assert len(evicted) >= 1

        conn = db.connect(db.db_path(brain_home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE session_id = ? AND kind = 'eviction'",
                ("sess-decision-rec",),
            ).fetchall()
        finally:
            conn.close()

        assert len(rows) >= 1
        row = rows[0]
        assert row["propensity"] == 1.0
        chosen_data = json.loads(row["chosen_json"])
        alt_data = json.loads(row["alternatives_json"])
        # chosen should contain the evicted obj_ids
        evicted_ids = {e.obj_id for e in evicted}
        if isinstance(chosen_data, list):
            chosen_ids = {c["obj_id"] if isinstance(c, dict) else c for c in chosen_data}
            assert evicted_ids.issubset(chosen_ids) or chosen_ids == evicted_ids
        elif isinstance(chosen_data, dict):
            assert "chosen_ids" in chosen_data or "obj_ids" in chosen_data
        # alternatives should have at most 5 items
        assert len(alt_data) <= 5


class TestFaultInHysteresisT22:
    """T2.2 Fault-in hysteresis tests."""

    def test_faulted_in_object_not_evictable_for_n_turns(self, brain_home):
        """RED test: fault-in an object at turn T; verify pinned_until_turn == T + 3;
        advance turns to T+1, T+2; verify evict_to_budget skips it under budget pressure;
        at turn T+3 verify it is now evictable."""
        store = VMemStore(brain_home, "sess-hysteresis-1")
        # Store two objects
        obj1 = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Obj 1",
            content="content 1 " * 50,
            pinned=False,
        )
        store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Obj 2",
            content="content 2 " * 50,
            pinned=False,
        )
        # Evict obj1 via claim_pages
        claimed = store.claim_pages([{"obj_id": obj1.obj_id, "kind": obj1.kind.value}])
        assert obj1.obj_id in claimed
        stored = store.get_object(obj1.obj_id)
        assert stored is not None
        assert stored.residency_state == ResidencyState.EVICTED

        # Advance session to turn T=2 by inserting 2 turn_start events
        with sqlite3.connect(store._dbfile) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "seq INTEGER PRIMARY KEY, "
                "event_id TEXT, "
                "internal_session_id TEXT, "
                "event_type TEXT"
                ")"
            )
            conn.execute(
                "INSERT INTO events (event_id, internal_session_id, event_type) VALUES (?, ?, ?)",
                ("evt-1", store.internal_id, "turn_start"),
            )
            conn.execute(
                "INSERT INTO events (event_id, internal_session_id, event_type) VALUES (?, ?, ?)",
                ("evt-2", store.internal_id, "turn_start"),
            )
            conn.commit()

        assert store.current_turn() == 2

        # Fault-in obj1 at turn T=2
        faulted, _ = store.fault_in(obj1.obj_id)
        assert faulted.residency_state == ResidencyState.FAULTED_IN
        # Pinned until T + 3 = 2 + 3 = 5
        assert faulted.pinned_until_turn == 5
        persisted = store.get_object(obj1.obj_id)
        assert persisted is not None
        assert persisted.pinned_until_turn == 5

        # Turn T+1 = 3: insert 1 more turn_start
        with sqlite3.connect(store._dbfile) as conn:
            conn.execute(
                "INSERT INTO events (event_id, internal_session_id, event_type) VALUES (?, ?, ?)",
                ("evt-3", store.internal_id, "turn_start"),
            )
            conn.commit()
        assert store.current_turn() == 3

        # Under severe budget pressure (max_tokens=0), evict_to_budget must skip obj1
        evicted = store.evict_to_budget(max_tokens=0)
        evicted_ids = {e.obj_id for e in evicted}
        assert obj1.obj_id not in evicted_ids
        stored = store.get_object(obj1.obj_id)
        assert stored is not None
        assert stored.residency_state == ResidencyState.FAULTED_IN

        # Turn T+2 = 4: insert 1 more turn_start
        with sqlite3.connect(store._dbfile) as conn:
            conn.execute(
                "INSERT INTO events (event_id, internal_session_id, event_type) VALUES (?, ?, ?)",
                ("evt-4", store.internal_id, "turn_start"),
            )
            conn.commit()
        assert store.current_turn() == 4

        # Still pinned: 5 > 4 -> must skip obj1
        evicted = store.evict_to_budget(max_tokens=0)
        evicted_ids = {e.obj_id for e in evicted}
        assert obj1.obj_id not in evicted_ids
        stored = store.get_object(obj1.obj_id)
        assert stored is not None
        assert stored.residency_state == ResidencyState.FAULTED_IN

        # Turn T+3 = 5: insert 1 more turn_start
        with sqlite3.connect(store._dbfile) as conn:
            conn.execute(
                "INSERT INTO events (event_id, internal_session_id, event_type) VALUES (?, ?, ?)",
                ("evt-5", store.internal_id, "turn_start"),
            )
            conn.commit()
        assert store.current_turn() == 5

        # Now pinned_until_turn (5) > current_turn (5) is False!
        # obj1 is no longer pinned and is evictable
        evicted = store.evict_to_budget(max_tokens=0)
        evicted_ids = {e.obj_id for e in evicted}
        assert obj1.obj_id in evicted_ids
        stored = store.get_object(obj1.obj_id)
        assert stored is not None
        assert stored.residency_state == ResidencyState.EVICTED

    def test_pinned_until_turn_schema_idempotency(self, brain_home, tmp_path):
        """Fresh and existing DBs get pinned_until_turn INTEGER DEFAULT 0 idempotently."""
        # 1. Fresh DB
        store = VMemStore(brain_home, "sess-fresh-hysteresis")
        with sqlite3.connect(store._dbfile) as conn:
            cols = {
                row[1]: row for row in conn.execute("PRAGMA table_info(session_vmem)").fetchall()
            }
            assert "pinned_until_turn" in cols
            assert "INTEGER" in str(cols["pinned_until_turn"][2]).upper()
            assert str(cols["pinned_until_turn"][4]) == "0"

        # 2. Re-running _init_db is idempotent
        store._init_db()
        with sqlite3.connect(store._dbfile) as conn:
            cols = {
                row[1]: row for row in conn.execute("PRAGMA table_info(session_vmem)").fetchall()
            }
            assert "pinned_until_turn" in cols

        # 3. Existing DB without pinned_until_turn column gets upgraded via guarded ALTER
        custom_db = tmp_path / "legacy_vmem" / "ledger.sqlite"
        custom_db.parent.mkdir(parents=True)
        with sqlite3.connect(custom_db) as conn:
            conn.execute(
                """
                CREATE TABLE session_vmem (
                    obj_id TEXT PRIMARY KEY,
                    internal_session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    residency_state TEXT NOT NULL,
                    priority_score REAL NOT NULL DEFAULT 1.0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    access_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    segment_id TEXT,
                    metadata_json TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO session_vmem (
                    obj_id, internal_session_id, kind, title, summary,
                    content_sha256, token_estimate, residency_state,
                    priority_score, pinned, access_count, created_at,
                    last_accessed_at, segment_id, metadata_json
                ) VALUES (
                    'obj-legacy', 'sess-legacy', 'RESEARCH_RESULT', 'Title', 'Summary',
                    'sha256', 100, 'RESIDENT', 1.0, 0, 1, 'now', 'now', NULL, '{}'
                )
                """
            )
            conn.commit()

        store_legacy = VMemStore(tmp_path / "legacy_vmem_home", "sess-legacy")
        store_legacy._dbfile = custom_db
        store_legacy._init_db()

        with sqlite3.connect(custom_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM session_vmem WHERE obj_id = 'obj-legacy'").fetchone()
            assert row["pinned_until_turn"] == 0

    def test_session_object_serialization_pinned_until_turn(self):
        """SessionObject dataclass and to_dict preserve pinned_until_turn with default 0."""
        obj = SessionObject(
            obj_id="obj-test",
            session_id="sess-test",
            kind=SessionObjectKind.GENERIC,
            title="Test",
            summary="Summary",
            content_sha256="abc",
            token_estimate=50,
            residency_state=ResidencyState.RESIDENT,
        )
        assert obj.pinned_until_turn == 0
        d = obj.to_dict()
        assert d["pinned_until_turn"] == 0

        obj.pinned_until_turn = 7
        d2 = obj.to_dict()
        assert d2["pinned_until_turn"] == 7

    def test_current_turn_telemetry_fallback(self, brain_home):
        """When events table is missing/empty, fallback to telemetry turn_start count, or 0."""
        store = VMemStore(brain_home, "sess-turn-fallback")
        assert store.current_turn() == 0

        from second_brain import telemetry

        tdir = telemetry.telemetry_dir(brain_home)
        tdir.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "v": 2,
                "session": "sess-turn-fallback",
                "kind": "turn_start",
                "ts": "2026-09-03T00:00:00Z",
            },
            {
                "v": 2,
                "session": "sess-turn-fallback",
                "kind": "turn_start",
                "ts": "2026-09-03T00:01:00Z",
            },
        ]
        (tdir / "sess-turn-fallback.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n",
            encoding="utf-8",
        )
        assert store.current_turn() == 2

    def test_faulted_in_pin_turns_config_override(self, brain_home):
        """faulted_in_pin_turns in config/v2.toml overrides default 3."""
        config_dir = brain_home / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "v2.toml").write_text(
            "[economics]\nfaulted_in_pin_turns = 5\n",
            encoding="utf-8",
        )
        store = VMemStore(brain_home, "sess-custom-pin")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Obj Custom Pin",
            content="test custom pin",
            pinned=False,
        )
        store.claim_pages([{"obj_id": obj.obj_id, "kind": obj.kind.value}])
        faulted, _ = store.fault_in(obj.obj_id)
        assert faulted.pinned_until_turn == 5
