"""
Brain Handoff Envelope tests (Plan §3 P3.17 closure).

Proves the standardized bounded lossless cross-harness handoff artifact and
readback path: losslessness, boundedness, integrity/negative controls, no
dependence on source transcript, and identical semantics across the OMP and
Hermes adapters.
"""

from __future__ import annotations

import datetime

import pytest

from second_brain import contracts, hermes_adapter, omp_adapter, working_set
from second_brain.contracts import HandoffError
from second_brain.handoff import create_handoff, create_handoff_envelope, read_handoff_envelope


def _seed_capsule(home, session_id="sess-p317-01"):
    working_set.init_capsule(
        home,
        session_id,
        objective="Close the P3.17 handoff seam",
        task_mode="STANDARD",
        risk="MEDIUM",
        constraints=["no scope creep", "reuse existing primitives"],
    )
    working_set.update_capsule(
        home,
        session_id,
        confirmed_facts=["handoff.py already existed", "Artifact Store is content-addressed"],
        decisions_this_session=["bind envelope identity to a content hash"],
        open_questions=["should schema allow bidirectional transfer?"],
        files_touched=["src/second_brain/handoff.py"],
        verification={"p3_16": "PROVEN", "envelope_bounded": True},
        next_action="Prove cross-harness dogfood",
        brain_refs=["mem-abc123"],
    )
    working_set.add_requirement(home, session_id, "Envelope stays bounded", importance="critical")
    working_set.add_requirement(home, session_id, "Payload stays lossless", importance="high")
    return session_id


def _resign(envelope_dict: dict) -> dict:
    """Recompute handoff_id after a caller mutates a field (simulates a
    caller re-signing tampered content — used to isolate one invariant at a
    time instead of tripping HANDOFF_ID_MISMATCH for every negative test)."""
    fields = {k: v for k, v in envelope_dict.items() if k != "handoff_id"}
    envelope_dict = dict(envelope_dict)
    envelope_dict["handoff_id"] = contracts.BrainHandoffEnvelope.compute_id(fields)
    return envelope_dict


class TestLosslessness:
    def test_full_capsule_state_survives_round_trip(self, brain_home):
        session_id = _seed_capsule(brain_home)
        source_capsule = working_set.show_capsule(brain_home, session_id)

        envelope, _artifact = create_handoff_envelope(
            brain_home, session_id, source_harness="omp", target_harness="hermes"
        )
        recovered = read_handoff_envelope(brain_home, envelope.to_dict())

        # Every capsule field the legacy artifact never carried (constraints,
        # confirmed_facts, verification, brain_refs) is present.
        assert recovered["constraints"] == source_capsule["constraints"]
        assert recovered["confirmed_facts"] == source_capsule["confirmed_facts"]
        assert recovered["verification"] == source_capsule["verification"]
        assert recovered["decisions_this_session"] == source_capsule["decisions_this_session"]
        assert recovered["open_questions"] == source_capsule["open_questions"]
        assert recovered["objective"] == source_capsule["objective"]
        assert recovered["next_action"] == source_capsule["next_action"]

    def test_create_handoff_envelope_registers_artifact_ref(self, brain_home):
        from second_brain import db, ledger as ledger_mod
        from second_brain.paths import db_path

        session_id = _seed_capsule(brain_home, "sess-p317-artifact-ref")
        envelope, _artifact = create_handoff_envelope(
            brain_home, session_id, source_harness="omp", target_harness="hermes"
        )
        payload_hash = envelope.payload_sha256
        internal_id = ledger_mod.internal_session_id(session_id)
        conn = db.connect(db_path(brain_home), readonly=True)
        row = conn.execute(
            "SELECT COUNT(*) FROM artifact_refs WHERE sha = ? AND owner = ?",
            (payload_hash, f"handoff:{internal_id}"),
        ).fetchone()
        conn.close()
        assert row[0] == 1

    def test_canonical_structural_hash_equals_raw_artifact_byte_hash(self, brain_home):
        """Two independent proofs converge: the artifact store's byte hash
        (generic to any bytes) and the structural hash recomputed from the
        parsed payload (typed, canonical-JSON) both match the envelope."""
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        recovered = read_handoff_envelope(brain_home, envelope.to_dict())
        assert recovered["payload_sha256"] == envelope.payload_sha256
        assert recovered["payload_canonical_sha256"] == envelope.payload_canonical_sha256

    def test_requirement_ledger_recovered_without_source_transcript(self, brain_home):
        """The destination never sees conversation history: only the Active
        State Capsule + requirement ledger via the Artifact Store."""
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        recovered = read_handoff_envelope(brain_home, envelope.to_dict())
        req_ids = {entry["id"] for entry in recovered["requirements"]}
        assert req_ids == set(envelope.requirement_summary)
        assert len(req_ids) == 2


class TestBoundedness:
    def test_envelope_is_small_relative_to_full_state(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        assert envelope.envelope_bytes() <= contracts.HANDOFF_ENVELOPE_MAX_BYTES
        # The full payload (capsule + requirements) is materially larger than
        # the bounded envelope that references it.
        payload_bytes = len(
            working_set.show_capsule(brain_home, session_id).__repr__().encode("utf-8")
        )
        assert envelope.envelope_bytes() < payload_bytes + contracts.HANDOFF_ENVELOPE_MAX_BYTES

    def test_referenced_artifacts_not_counted_as_transported_context(self, brain_home):
        """Boundedness measures what crosses into model-visible context (the
        envelope), not what remains recoverable in storage (the payload)."""
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        # The envelope carries only a reference to the payload, not its content.
        assert "handoff.py already existed" not in envelope.canonical_json()
        assert "Close the P3.17 handoff seam" not in envelope.canonical_json()

    def test_oversized_context_refs_rejected(self, brain_home):
        session_id = _seed_capsule(brain_home)
        with pytest.raises(HandoffError) as exc_info:
            create_handoff_envelope(
                brain_home, session_id, source_harness="omp",
                context_refs=[f"artifact:{'a' * 64}"] * (contracts.HANDOFF_LIST_MAX_ITEMS + 1),
            )
        assert exc_info.value.code == "HANDOFF_MALFORMED"


class TestNegativeControls:
    def test_altered_envelope_rejected(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        tampered = dict(envelope.to_dict())
        tampered["objective_hint"] = "not a real field, but the hash below is unchanged"
        tampered["destination_harness"] = "attacker-harness"  # mutated without re-signing
        with pytest.raises(HandoffError) as exc_info:
            read_handoff_envelope(brain_home, tampered)
        assert exc_info.value.code == "HANDOFF_ID_MISMATCH"

    def test_altered_payload_artifact_rejected(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        forged = _resign({**envelope.to_dict(), "payload_sha256": "0" * 64})
        with pytest.raises(HandoffError) as exc_info:
            read_handoff_envelope(brain_home, forged)
        assert exc_info.value.code == "HANDOFF_HASH_MISMATCH"

    def test_missing_artifact_rejected_explicitly(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        missing_ref = f"[brain-artifact:sha256:{'a' * 64}]"
        forged = _resign({**envelope.to_dict(), "payload_ref": missing_ref})
        with pytest.raises(HandoffError) as exc_info:
            read_handoff_envelope(brain_home, forged)
        assert exc_info.value.code == "HANDOFF_ARTIFACT_UNRESOLVED"

    def test_wrong_project_rejected(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(
            brain_home, session_id, source_harness="omp", project_id="second-brain"
        )
        with pytest.raises(HandoffError) as exc_info:
            read_handoff_envelope(
                brain_home, envelope.to_dict(), expected_project_id="other-project"
            )
        assert exc_info.value.code == "HANDOFF_PROJECT_MISMATCH"

    def test_stale_state_rejected_or_explicitly_classified(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        old = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=3)
        ).isoformat()
        stale = _resign({**envelope.to_dict(), "capsule_updated_at": old})
        with pytest.raises(HandoffError) as exc_info:
            read_handoff_envelope(brain_home, stale)
        assert exc_info.value.code == "HANDOFF_STALE"
        recovered = read_handoff_envelope(brain_home, stale, allow_stale=True)
        assert recovered["freshness"] == "STALE"

    def test_unsupported_schema_rejected(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(brain_home, session_id, source_harness="omp")
        forged = _resign({**envelope.to_dict(), "schema_version": 999})
        with pytest.raises(HandoffError) as exc_info:
            read_handoff_envelope(brain_home, forged)
        assert exc_info.value.code == "HANDOFF_SCHEMA_MISMATCH"

    def test_unavailable_evidence_distinct_from_empty(self, brain_home):
        session_id = _seed_capsule(brain_home)
        envelope, _ = create_handoff_envelope(
            brain_home, session_id, source_harness="omp",
            unavailable_evidence=["current_omp_primary_session_id"],
        )
        assert envelope.unavailable_evidence == ["current_omp_primary_session_id"]
        assert envelope.evidence_refs == []

        envelope_empty, _ = create_handoff_envelope(
            brain_home, session_id, source_harness="omp"
        )
        assert envelope_empty.unavailable_evidence == []
        assert envelope_empty.evidence_refs == []


class TestCrossHarnessAdapters:
    """OMP and Hermes must use identical semantics: same functions, same
    validation, same failure codes — proven by round-tripping through both
    adapter entry points."""

    def test_omp_creates_hermes_reads(self, brain_home):
        session_id = _seed_capsule(brain_home, "sess-p317-omp")
        create_resp = omp_adapter.handle_request(brain_home, {
            "operation": "handoff_create",
            "host_session_id": session_id,
            "source_harness": "omp",
            "target_harness": "hermes",
            "project_id": "second-brain",
        })
        assert "envelope" in create_resp
        read_resp = hermes_adapter.handle_request(brain_home, {
            "event": "handoff_read",
            "bot_name": "claude",
            "session_id": "consumer-session",
            "project_id": "second-brain",
            "envelope": create_resp["envelope"],
        })
        assert read_resp["status"] == "recovered"
        assert read_resp["objective"] == "Close the P3.17 handoff seam"
        assert read_resp["next_action"] == "Prove cross-harness dogfood"

    def test_hermes_creates_omp_reads(self, brain_home):
        binding = hermes_adapter.resolve_binding(
            brain_home,
            {"bot_name": "codex", "session_id": "sess-p317-reverse", "project_id": "second-brain"},
        )
        _seed_capsule(brain_home, binding.brain_session_id)
        create_resp = hermes_adapter.handle_request(brain_home, {
            "event": "handoff_create",
            "bot_name": "codex",
            "session_id": "sess-p317-reverse",
            "project_id": "second-brain",
            "target_harness": "omp",
        })
        assert create_resp["status"] == "created"
        read_resp = omp_adapter.handle_request(brain_home, {
            "operation": "handoff_read",
            "project_id": "second-brain",
            "envelope": create_resp["envelope"],
        })
        assert read_resp["objective"] == "Close the P3.17 handoff seam"

    def test_omp_and_hermes_reject_wrong_project_identically(self, brain_home):
        session_id = _seed_capsule(brain_home, "sess-p317-omp-2")
        create_resp = omp_adapter.handle_request(brain_home, {
            "operation": "handoff_create",
            "host_session_id": session_id,
            "source_harness": "omp",
            "project_id": "second-brain",
        })
        envelope = create_resp["envelope"]

        omp_bad = omp_adapter.handle_request(brain_home, {
            "operation": "handoff_read", "project_id": "other-project", "envelope": envelope,
        })
        hermes_bad = hermes_adapter.handle_request(brain_home, {
            "event": "handoff_read", "bot_name": "claude", "session_id": "x",
            "project_id": "other-project", "envelope": envelope,
        })
        assert omp_bad["failure_code"] == "HANDOFF_PROJECT_MISMATCH"
        assert hermes_bad["failure_code"] == "HANDOFF_PROJECT_MISMATCH"


class TestLegacyHandoffObjective:
    """T6.2: `create_handoff` must read the capsule's real `objective` field,
    not a nonexistent `current_objective` key (which always fell through to
    the "Continue session task" default, silently discarding the capsule's
    actual objective on every handoff)."""

    def test_handoff_uses_capsule_objective(self, brain_home):
        session_id = _seed_capsule(brain_home, "sess-p317-objective")

        artifact = create_handoff(brain_home, session_id)

        assert artifact.objective == "Close the P3.17 handoff seam"
        assert artifact.objective != "Continue session task"
