"""Focused T7.1 earned-memory friction-gate tests."""

import hashlib
import json
import shutil

from second_brain import contracts, db, decisions, semantic


SHA_A = "a" * 64
SHA_B = "b" * 64


def _ledger_event(event_id: str, event_type: str, **payload: object) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "internal_session_id": "session-1",
        "payload": payload,
    }


def _telemetry_event(ref: str, **record: object) -> dict:
    value = dict(record)
    value["record_hash"] = hashlib.sha256(
        contracts.canonical_json(value).encode("utf-8")
    ).hexdigest()
    value["telemetry_ref"] = ref
    return value


def _candidate_count(home) -> int:
    conn = db.connect(db.db_path(home), readonly=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM v2_candidates").fetchone()[0])
    finally:
        conn.close()


def test_no_friction_signal_creates_no_candidate(brain_home) -> None:
    result = semantic.evaluate_candidate(
        brain_home,
        "Model confidence is not evidence",
        "Do not capture this unsupported model assertion.",
        session_id="session-1",
        events=[
            _ledger_event(
                "event-no-friction",
                "finding",
                confidence=1.0,
                model_confidence="high",
            )
        ],
    )

    assert result is None
    assert _candidate_count(brain_home) == 0
    recorded = decisions.list_decisions(brain_home, kind="admission")
    assert len(recorded) == 1
    assert recorded[0]["chosen"] == {"candidate_id": None, "outcome": "no_candidate"}
    assert recorded[0]["rollout_stage"] == "SHADOW"


def test_repeated_verified_failure_creates_candidate(brain_home) -> None:
    events = [
        _ledger_event(
            "failure-2",
            "task_failed",
            failure_code="ASSERTION_MISMATCH",
            verified=True,
        ),
        _ledger_event(
            "failure-1",
            "task_failed",
            failure_code="ASSERTION_MISMATCH",
            verified=True,
        ),
    ]
    first = semantic.evaluate_candidate(
        brain_home,
        "Preserve assertion semantics",
        "The same verified assertion mismatch occurred twice.",
        session_id="session-1",
        events=events,
    )
    replay = semantic.evaluate_candidate(
        brain_home,
        "Preserve assertion semantics",
        "The same verified assertion mismatch occurred twice.",
        session_id="session-1",
        events=list(reversed(events)),
    )

    assert first is not None and replay is not None
    assert first["candidate_id"] == replay["candidate_id"]
    assert replay["triggers"] == ["REPETITION"]
    assert replay["source_event_refs"] == ["failure-1", "failure-2"]
    assert replay["lifecycle_state"] == "candidate"
    assert replay["rollout_stage"] == "SHADOW"
    assert _candidate_count(brain_home) == 1
    assert len(decisions.list_decisions(brain_home, kind="admission")) == 1


def test_model_inference_candidate_stays_advisory(brain_home) -> None:
    event = _ledger_event(
        "correction-model",
        "result_corrected",
        correction_sha256=SHA_A,
        result_sha256=SHA_B,
        confidence="certain",
        authority_ceiling="policy",
    )
    candidate = semantic.evaluate_candidate(
        brain_home,
        "Never trust caller authority",
        "Caller metadata cannot promote a model-authored candidate.",
        session_id="session-1",
        events=[event],
        origin_class="MODEL_INFERENCE",
    )

    assert candidate is not None
    assert candidate["authority_ceiling"] == "advisory"
    assert candidate["confidence"] == "low"
    assert candidate["lifecycle_state"] == "candidate"
    assert candidate["rollout_stage"] == "SHADOW"
    assert semantic.list_memories(brain_home) == []


def test_candidate_records_source_event_refs(brain_home) -> None:
    records = [
        _telemetry_event(
            "session.jsonl:9",
            kind="hermes_worker_result_corrected",
            session="session-real",
            correction_sha256=SHA_A,
            result_sha256=SHA_B,
        ),
        _telemetry_event(
            "session.jsonl:3",
            kind="hermes_worker_result_correction_requested",
            session="session-real",
            correction_sha256=SHA_A,
            original_result_sha256=SHA_B,
        ),
    ]
    candidate = semantic.evaluate_candidate(
        brain_home,
        "Correction evidence",
        "Correction events retain their exact telemetry references.",
        session_id="session-real",
        events=records,
    )

    assert candidate is not None
    assert candidate["triggers"] == ["CORRECTION"]
    assert candidate["source_event_refs"] == ["session.jsonl:3", "session.jsonl:9"]
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT trigger_set_json, source_event_refs_json, decision_ref "
            "FROM v2_candidates WHERE candidate_id = ?",
            (candidate["candidate_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert json.loads(row["trigger_set_json"]) == ["CORRECTION"]
    assert json.loads(row["source_event_refs_json"]) == [
        "session.jsonl:3",
        "session.jsonl:9",
    ]
    assert decisions.list_decisions(brain_home, kind="admission")[0]["decision_id"] == row[
        "decision_ref"
    ]


def test_authority_ceiling_is_origin_bound(brain_home) -> None:
    candidate = semantic.evaluate_candidate(
        brain_home,
        "Trusted candidate remains shadowed",
        "Trusted origin raises confidence only within the T1.7 ceiling.",
        session_id="session-1",
        events=[
            _ledger_event(
                "trusted-correction",
                "result_correction_requested",
                correction_sha256=SHA_A,
            )
        ],
        origin_class="TRUSTED_TEST",
        origin_root_sha=SHA_B,
    )

    assert candidate is not None
    assert candidate["authority_ceiling"] == "project_rule"
    assert candidate["confidence"] == "medium"
    assert candidate["rollout_stage"] == "SHADOW"
    assert candidate["lifecycle_state"] == "candidate"


def test_candidate_is_excluded_from_active_retrieval(brain_home) -> None:
    candidate = semantic.evaluate_candidate(
        brain_home,
        "Earned candidate isolation",
        "Unique earned candidate isolation phrase.",
        session_id="session-1",
        events=[
            _ledger_event(
                "isolated-correction",
                "result_corrected",
                correction_sha256=SHA_A,
            )
        ],
        origin_class="LOCAL_REPO",
    )

    assert candidate is not None
    assert semantic.search_memories(brain_home, "earned candidate isolation", top_k=10) == []
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM memory_index").fetchone()[0] == 0
    finally:
        conn.close()


def test_trigger_vocabulary_is_exact_and_sorted() -> None:
    assert semantic.CANDIDATE_TRIGGERS == (
        "CORRECTION",
        "REGRESSION",
        "REPETITION",
        "SUBTLETY",
        "SEVERITY",
        "INDEPENDENT_EVIDENCE",
        "CROSS_SESSION_REUSE",
    )
    events = [
        _ledger_event("subtle", "finding", subtle=True, verified=True),
        _ledger_event("regression", "test_observed", regression_verified=True),
        _ledger_event("severe", "finding", severity="CRITICAL", evidence_hash=SHA_A),
        _ledger_event(
            "independent",
            "independent_verification",
            verdict="PASS",
            evidence_hash=SHA_B,
        ),
    ]
    assert semantic.extract_candidate_triggers(events) == (
        "INDEPENDENT_EVIDENCE",
        "REGRESSION",
        "SEVERITY",
        "SUBTLETY",
    )


def test_fresh_reopen_and_repeat_migration_preserve_existing_rows(tmp_path) -> None:
    dbfile = db.db_path(tmp_path / "brain")
    prefix = tmp_path / "pre-earned-migrations"
    prefix.mkdir()
    migrations = db.migration_files()
    for path in migrations:
        if not path.name.startswith("0019_"):
            shutil.copy2(path, prefix / path.name)
    assert db.migrate(dbfile, migrations_dir=prefix) == list(range(1, 19))

    conn = db.connect(dbfile)
    try:
        conn.execute(
            "INSERT INTO projects(id, name, created_at) VALUES ('existing', 'Existing', '2026-01-01')"
        )
        conn.commit()
    finally:
        conn.close()

    assert db.migrate(dbfile) == [19]
    assert db.migrate(dbfile) == []
    conn = db.connect(dbfile, readonly=True)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(v2_candidates)")}
        project = conn.execute("SELECT name FROM projects WHERE id='existing'").fetchone()
    finally:
        conn.close()
    assert {
        "candidate_id",
        "lifecycle_state",
        "trigger_set_json",
        "source_event_refs_json",
        "authority_ceiling",
        "origin_class",
        "confidence",
        "rollout_stage",
        "decision_ref",
    } <= columns
    assert project["name"] == "Existing"
