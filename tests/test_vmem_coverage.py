"""Tests for coverage-before-reclaim (Deep Upgrade Plan U4 §5.3-5.7).

Two-phase reclaim: PREPARE (select victims, no writes) -> COVERAGE
(``cover()`` each; uncovered candidates stay resident/DIRTY) -> COMMIT
(atomic CAS on ``durability='CLEAN'``) -> VERIFY (re-read; write
``reclaim_manifest.jsonl``; advance ``durable_through_seq``).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from second_brain import ledger, working_set
from second_brain.errors import BrainError
from second_brain.vmem import (
    DURABILITY_CLEAN,
    DURABILITY_DIRTY,
    ResidencyState,
    SessionObjectKind,
    VMemStore,
)


def _delete_backing_artifact(home, sha256: str) -> None:
    """Simulate on-disk artifact loss/corruption: remove the metadata file
    for `sha256` so `artifacts.expand` can no longer resolve it."""
    meta_path = home / "state" / "artifacts" / "meta" / f"{sha256}.json"
    assert meta_path.exists()
    meta_path.unlink()


def _corrupt_backing_artifact_bytes(home, sha256: str) -> None:
    """Simulate silent bit-rot: overwrite the blob bytes in place so the
    file still exists (meta intact) but no longer hashes to its own name."""
    blob_path = home / "state" / "artifacts" / "blobs" / f"{sha256}.bin"
    assert blob_path.exists()
    blob_path.write_bytes(b"corrupted-bytes-do-not-match-hash")


class TestDirtyMaterialObjectNeverEvicted:
    """RED/GREEN: material kinds (DECISION/BLOCKER/WORKER_FINDING) can
    never be marked durability=CLEAN via DISPOSABLE_DERIVED coverage, so
    an uncoverable material object must never be evicted, no matter the
    budget pressure."""

    def test_dirty_material_object_never_evicted(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-material-1")
        obj = store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Uncovered decision",
            content="A decision with no durable canonical backing",
            pinned=False,
            metadata={"recovery_class": "DISPOSABLE_DERIVED", "derived_kind": "SEARCH_OUTPUT"},
        )
        assert obj.durability == DURABILITY_DIRTY

        evicted = store.evict_to_budget(max_tokens=0)

        assert evicted == []
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.RESIDENT
        assert refetched.durability == DURABILITY_DIRTY

    def test_dirty_blocker_object_never_evicted(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-material-2")
        obj = store.store_object(
            kind=SessionObjectKind.BLOCKER,
            title="Uncovered blocker",
            content="Blocking issue with no durable backing",
            pinned=False,
            metadata={"recovery_class": "DISPOSABLE_DERIVED", "derived_kind": "DIRECTORY_LISTING"},
        )

        store.evict_to_budget(max_tokens=0)

        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.RESIDENT


class TestUncoveredArtifactKeepsObjectResident:
    """RED/GREEN: EXACT_ARTIFACT coverage failing (missing or corrupt
    backing blob) must never destroy or evict the object."""

    def test_uncovered_artifact_keeps_object_resident(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-artifact-1")
        obj = store.store_object(
            kind=SessionObjectKind.LOG_EXCERPT,
            title="Doomed log",
            content="log content that will lose its backing artifact",
            pinned=False,
        )
        _delete_backing_artifact(brain_home, obj.content_sha256)

        evicted = store.evict_to_budget(max_tokens=0)

        assert evicted == []
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.residency_state == ResidencyState.RESIDENT
        assert refetched.durability == DURABILITY_DIRTY

    def test_bitrot_hash_mismatch_keeps_object_resident(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-artifact-2")
        obj = store.store_object(
            kind=SessionObjectKind.TOOL_OBSERVATION,
            title="Bit-rotted output",
            content="output content whose blob bytes get corrupted",
            pinned=False,
        )
        _corrupt_backing_artifact_bytes(brain_home, obj.content_sha256)

        covered = store.cover(obj)

        assert covered is False
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.durability == DURABILITY_DIRTY


class TestWatermarkAdvancesOnlyWhenAllClean:
    """RED/GREEN: `durable_through_seq` only advances over a CONTIGUOUS
    prefix of durability=CLEAN objects -- a single DIRTY object anywhere
    in that prefix halts the advance right before it."""

    def test_watermark_advances_only_when_all_clean(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-watermark-1")

        obj1 = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Coverable first",
            content="first content",
            pinned=False,
        )
        obj2 = store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Uncoverable middle",
            content="middle content, never coverable",
            pinned=False,
            metadata={"recovery_class": "DISPOSABLE_DERIVED", "derived_kind": "SEARCH_OUTPUT"},
        )
        obj3 = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Coverable last",
            content="last content",
            pinned=False,
        )

        with sqlite3.connect(store._dbfile) as conn:
            rowid1 = conn.execute(
                "SELECT rowid FROM session_vmem WHERE obj_id = ?", (obj1.obj_id,)
            ).fetchone()[0]
            rowid2 = conn.execute(
                "SELECT rowid FROM session_vmem WHERE obj_id = ?", (obj2.obj_id,)
            ).fetchone()[0]
            rowid3 = conn.execute(
                "SELECT rowid FROM session_vmem WHERE obj_id = ?", (obj3.obj_id,)
            ).fetchone()[0]
        assert rowid1 < rowid2 < rowid3

        # Force-evict everything: obj1/obj3 are trivially coverable
        # (EXACT_ARTIFACT), obj2 never is (material + DISPOSABLE_DERIVED).
        store.evict_to_budget(max_tokens=0)

        watermark = store.get_durable_through_seq()
        assert watermark == rowid1
        assert watermark < rowid2
        assert watermark < rowid3

        obj2_after = store.get_object(obj2.obj_id)
        assert obj2_after is not None
        assert obj2_after.residency_state == ResidencyState.RESIDENT
        assert obj2_after.durability == DURABILITY_DIRTY

        obj3_after = store.get_object(obj3.obj_id)
        assert obj3_after is not None
        assert obj3_after.durability == DURABILITY_CLEAN
        assert obj3_after.residency_state == ResidencyState.EVICTED

    def test_watermark_never_moves_backward(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-watermark-2")
        obj1 = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT, title="a", content="a", pinned=False
        )
        store.evict_to_budget(max_tokens=0)
        first_watermark = store.get_durable_through_seq()
        assert first_watermark > 0

        # A second, always-empty evict_to_budget call must never regress
        # the watermark.
        store.evict_to_budget(max_tokens=10_000_000)
        assert store.get_durable_through_seq() == first_watermark
        assert obj1  # keep reference; documents intent


class TestCompactionCancelledWhenMaterialDirty:
    """RED/GREEN: prepare_compaction()'s Python-side cancel contract for
    Prime's session_before_compact (plan U4 §5.7)."""

    def test_compaction_cancelled_when_material_dirty(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-cancel-1")
        pinned_obj = store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Pinned but uncoverable decision",
            content="a pinned decision with no durable canonical backing",
            pinned=True,
            metadata={"recovery_class": "DISPOSABLE_DERIVED", "derived_kind": "SEARCH_OUTPUT"},
        )

        result = store.prepare_compaction()

        assert result["cancel"] is True
        still_pinned = store.get_object(pinned_obj.obj_id)
        assert still_pinned is not None
        assert still_pinned.residency_state == ResidencyState.RESIDENT
        assert still_pinned.durability == DURABILITY_DIRTY

    def test_compaction_not_cancelled_when_pinned_covered(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-cancel-2")
        store.store_object(
            kind=SessionObjectKind.DECISION,
            title="Pinned coverable decision",
            content="a normal, artifact-backed pinned decision",
            pinned=True,
        )

        result = store.prepare_compaction()

        assert result["cancel"] is False

    def test_compaction_cancelled_when_unpinned_material_dirty(self, brain_home):
        """Unpinned material (DECISION/BLOCKER/WORKER_FINDING) objects that
        fail to cover also block compaction, even though they are never
        actually evicted by the same call."""
        store = VMemStore(brain_home, "sess-cov-cancel-3")
        store.store_object(
            kind=SessionObjectKind.BLOCKER,
            title="Unpinned uncoverable blocker",
            content="an unpinned blocker with no durable backing",
            pinned=False,
            metadata={"recovery_class": "DISPOSABLE_DERIVED", "derived_kind": "SEARCH_OUTPUT"},
        )

        result = store.prepare_compaction()

        assert result["cancel"] is True

    def test_compaction_not_cancelled_when_nothing_pinned_or_material(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-cancel-4")
        store.store_object(
            kind=SessionObjectKind.LOG_EXCERPT,
            title="Ordinary unpinned log",
            content="nothing special here",
            pinned=False,
        )

        result = store.prepare_compaction()

        assert result["cancel"] is False


class TestCoverageClassBoundaries:
    """Per-recovery_class boundary tests for `VMemStore.cover()`."""

    def test_exact_artifact_default_covers_normally_stored_object(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-1")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC, title="x", content="normal content", pinned=False
        )
        assert obj.recovery_class is None

        covered = store.cover(obj)

        assert covered is True
        assert obj.durability == DURABILITY_CLEAN
        assert obj.recovery_class == "EXACT_ARTIFACT"
        assert obj.covered_at is not None
        refetched = store.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.durability == DURABILITY_CLEAN
        assert refetched.recovery_class == "EXACT_ARTIFACT"
        assert refetched.covered_at == obj.covered_at

    def test_exact_artifact_missing_backing_fails_coverage(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-2")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC, title="x", content="will vanish", pinned=False
        )
        _delete_backing_artifact(brain_home, obj.content_sha256)

        assert store.cover(obj) is False

    def test_canonical_state_requirement_uncovered_until_requirement_exists(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-3")
        obj = store.store_object(
            kind=SessionObjectKind.WORKER_FINDING,
            title="Finding backed by a requirement",
            content="derived from REQ-001",
            pinned=False,
            metadata={
                "recovery_class": "CANONICAL_STATE",
                "canonical_ref": {"type": "requirement", "id": "REQ-001"},
            },
        )

        assert store.cover(obj) is False
        assert store.get_object(obj.obj_id).durability == DURABILITY_DIRTY

        working_set.add_requirement(
            brain_home, "sess-cov-class-3", "Do the thing", req_id="REQ-001"
        )

        assert store.cover(obj) is True
        assert store.get_object(obj.obj_id).durability == DURABILITY_CLEAN

    def test_canonical_state_capsule_ref_covers_when_capsule_exists(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-4")
        obj = store.store_object(
            kind=SessionObjectKind.WORKER_FINDING,
            title="Finding backed by the capsule",
            content="derived from the active state capsule",
            pinned=False,
            metadata={"recovery_class": "CANONICAL_STATE", "canonical_ref": {"type": "capsule"}},
        )
        assert store.cover(obj) is False

        working_set.init_capsule(brain_home, "sess-cov-class-4", objective="ship it")

        assert store.cover(obj) is True

    def test_canonical_state_memory_ref_uncovered_for_unknown_memory(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-5")
        obj = store.store_object(
            kind=SessionObjectKind.WORKER_FINDING,
            title="Finding backed by a memory",
            content="derived from a memory row that does not exist",
            pinned=False,
            metadata={
                "recovery_class": "CANONICAL_STATE",
                "canonical_ref": {"type": "memory", "id": "mem-does-not-exist"},
            },
        )

        assert store.cover(obj) is False

    def test_disposable_derived_covers_non_material_kind_with_valid_tag(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-6")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC,
            title="A stale directory listing",
            content="dir listing text",
            pinned=False,
            metadata={"recovery_class": "DISPOSABLE_DERIVED", "derived_kind": "DIRECTORY_LISTING"},
        )

        assert store.cover(obj) is True
        assert store.get_object(obj.obj_id).recovery_class == "DISPOSABLE_DERIVED"

    def test_disposable_derived_without_derived_kind_tag_never_covers(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-7")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC,
            title="Missing derived_kind tag",
            content="dir listing text",
            pinned=False,
            metadata={"recovery_class": "DISPOSABLE_DERIVED"},
        )

        assert store.cover(obj) is False

    def test_disposable_derived_never_covers_worker_finding_kind(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-class-8")
        obj = store.store_object(
            kind=SessionObjectKind.WORKER_FINDING,
            title="A worker finding masquerading as disposable",
            content="finding text",
            pinned=False,
            metadata={"recovery_class": "DISPOSABLE_DERIVED", "derived_kind": "SEARCH_OUTPUT"},
        )

        assert store.cover(obj) is False


class TestReclaimCommitCasSafety:
    """CAS-race safety for the COMMIT phase of `_reclaim` (sequential proxy
    for real concurrency, matching `claim_pages`'s own existing testing
    precedent)."""

    def test_reclaim_commit_cas_loses_race_to_concurrent_claim_pages(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-cas-1")
        obj = store.store_object(
            kind=SessionObjectKind.GENERIC, title="race target", content="content", pinned=False
        )

        # A concurrent proactive claim_pages call wins the race first.
        claimed = store.claim_pages([{"obj_id": obj.obj_id, "kind": "GENERIC"}])
        assert claimed == [obj.obj_id]

        # evict_to_budget's own COMMIT CAS must find the row already
        # EVICTED and skip it -- no error, not double-committed, no
        # duplicate manifest row.
        evicted = store.evict_to_budget(max_tokens=0)

        assert evicted == []
        manifest_path = store._sdir / "reclaim_manifest.jsonl"
        assert not manifest_path.exists()


class TestReclaimManifestWriteCorrectness:
    def test_reclaim_manifest_row_written_on_evict(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-manifest-1")
        obj = store.store_object(
            kind=SessionObjectKind.RESEARCH_RESULT,
            title="Manifest target",
            content="content to be evicted",
            pinned=False,
        )

        evicted = store.evict_to_budget(max_tokens=0)

        assert [e.obj_id for e in evicted] == [obj.obj_id]
        manifest_path = store._sdir / "reclaim_manifest.jsonl"
        assert manifest_path.exists()
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["obj_id"] == obj.obj_id
        assert row["sha"] == obj.content_sha256
        assert row["recovery_class"] == "EXACT_ARTIFACT"
        assert row["reason"] == "evict_to_budget"
        assert isinstance(row["seq"], int)

    def test_reclaim_manifest_appends_across_multiple_calls(self, brain_home):
        store = VMemStore(brain_home, "sess-cov-manifest-2")
        store.store_object(kind=SessionObjectKind.GENERIC, title="a", content="a", pinned=False)
        store.evict_to_budget(max_tokens=0)
        store.store_object(kind=SessionObjectKind.GENERIC, title="b", content="b", pinned=False)
        store.evict_to_budget(max_tokens=0)

        manifest_path = store._sdir / "reclaim_manifest.jsonl"
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2


class TestSchemaMigrationIdempotency:
    """Guarded-ALTER additive schema tests (plan U4 §5.3): fresh init,
    reopen, and upgrade of a pre-existing pre-T2.0 database must all be
    idempotent and never destroy existing rows."""

    def test_schema_migration_idempotent_fresh_and_reopen(self, brain_home):
        store1 = VMemStore(brain_home, "sess-cov-mig-1")
        obj = store1.store_object(
            kind=SessionObjectKind.GENERIC, title="a", content="b", pinned=False
        )
        store1.cover(obj)

        # Reopen: guarded ALTER must be idempotent -- no error, no data loss.
        store2 = VMemStore(brain_home, "sess-cov-mig-1")
        refetched = store2.get_object(obj.obj_id)
        assert refetched is not None
        assert refetched.durability == DURABILITY_CLEAN

        with sqlite3.connect(store2._dbfile) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(session_vmem)").fetchall()]
        assert cols.count("durability") == 1
        assert cols.count("recovery_class") == 1
        assert cols.count("covered_at") == 1

    def test_schema_migration_additive_on_pre_existing_old_schema_db(self, brain_home):
        session_id = "sess-cov-mig-old"
        internal_id = ledger.internal_session_id(session_id)
        sdir = brain_home / "state" / "sessions" / internal_id
        sdir.mkdir(parents=True, exist_ok=True)
        dbfile = sdir / "ledger.sqlite"

        # Simulate a pre-T2.0 ledger.sqlite: the OLD session_vmem schema,
        # with no durability/recovery_class/covered_at columns, and one
        # legacy row already present.
        with sqlite3.connect(dbfile) as conn:
            conn.executescript(
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "obj-legacy123",
                    internal_id,
                    "GENERIC",
                    "Legacy row",
                    "Legacy row",
                    "0" * 64,
                    5,
                    "RESIDENT",
                    10.0,
                    0,
                    1,
                    "2020-01-01T00:00:00+00:00",
                    "2020-01-01T00:00:00+00:00",
                    None,
                    "{}",
                ),
            )
            conn.commit()

        # Constructing VMemStore triggers the guarded ALTER -- additive
        # only, must not destroy the pre-existing legacy row.
        store = VMemStore(brain_home, session_id)
        legacy = store.get_object("obj-legacy123")
        assert legacy is not None
        assert legacy.title == "Legacy row"
        assert legacy.durability == DURABILITY_DIRTY  # DEFAULT applied
        assert legacy.recovery_class is None
        assert legacy.covered_at is None
