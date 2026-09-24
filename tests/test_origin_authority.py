import hashlib
import shutil
from pathlib import Path

import pytest

from second_brain import autoinject, db, semantic
from second_brain import ledger as ledger_mod
from second_brain.contracts import (
    BrainLifecycleEvent,
    BrainSessionIdentity,
    LifecycleEventType,
    MemoryItemStatus,
    SurfaceVisibility,
)
from second_brain.errors import BrainError


def _root(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_summary_of_web_source_stays_advisory(brain_home: Path) -> None:
    mid = semantic.add_memory(
        brain_home,
        "Web summary",
        "summarized web claim",
        scope="global",
        summary="short summary",
        origin_class="EXTERNAL_WEB",
        origin_root_sha=_root("https://example.test/source"),
    )
    row = semantic._row(brain_home, mid)
    assert row is not None
    assert row["origin_class"] == "EXTERNAL_WEB"
    assert row["origin_root_sha"] == _root("https://example.test/source")
    assert row["authority_ceiling"] == "advisory"


def test_two_summaries_same_root_count_as_one_corroboration(brain_home: Path) -> None:
    root = _root("https://example.test/source")
    first = semantic.add_memory(
        brain_home,
        "One",
        "summary one",
        scope="global",
        origin_class="EXTERNAL_WEB",
        origin_root_sha=root,
    )
    second = semantic.add_memory(
        brain_home,
        "Two",
        "summary two",
        scope="global",
        origin_class="EXTERNAL_WEB",
        origin_root_sha=root,
    )
    rows = [semantic._row(brain_home, first), semantic._row(brain_home, second)]
    assert semantic.corroboration_count(rows) == 1


def test_corroboration_ignores_non_iterable_input() -> None:
    assert semantic.corroboration_count(object()) == 0


def test_policy_lane_rejects_advisory_items(brain_home: Path) -> None:
    advisory = semantic.add_memory(
        brain_home,
        "Policy fact",
        "advisory claim",
        scope="global",
        origin_class="EXTERNAL_WEB",
        origin_root_sha=_root("web"),
    )
    intent = autoinject.RetrievalIntent(
        task_text="policy fact",
        project_id=None,
        agent_id="a1",
        role_profile="cli",
        session_id="policy-test",
        lane="policy",
    )
    rows = semantic.search_memories(brain_home, "policy fact", top_k=10)
    assert advisory in {row["memory_id"] for row in rows}
    assert autoinject._valid_candidates(intent, rows) == []


def test_invalid_origin_class_and_ceiling_rejected(brain_home: Path) -> None:
    with pytest.raises(BrainError):
        semantic.add_memory(brain_home, "Bad", "body", origin_class="NOT_REAL")
    mid = semantic.add_memory(
        brain_home, "Good", "body", scope="global", origin_class="USER_AUTHORED"
    )
    with pytest.raises(BrainError):
        semantic.curate(brain_home, mid, authority_ceiling="NOT_REAL")


def test_curate_cannot_raise_authority_ceiling(brain_home: Path) -> None:
    mid = semantic.add_memory(
        brain_home, "Fact", "body", scope="global", origin_class="USER_AUTHORED"
    )
    before = semantic._row(brain_home, mid)
    assert before is not None
    # A caller-declared origin mints no authority, so there is nothing to lower:
    # curation can only keep or lower the ceiling (SEC-AUTH-02 producer guard).
    assert before["authority_ceiling"] == "advisory"
    for ceiling in ("project_rule", "policy"):
        with pytest.raises(BrainError):
            semantic.curate(brain_home, mid, authority_ceiling=ceiling)
    semantic.curate(brain_home, mid, authority_ceiling="advisory")
    after = semantic._row(brain_home, mid)
    assert after is not None
    assert after["authority_ceiling"] == "advisory"


def test_origin_columns_migrate_fresh_database(tmp_path: Path) -> None:
    dbfile = tmp_path / "brain.sqlite"
    db.migrate(dbfile)
    conn = db.connect(dbfile)
    try:
        names = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
        assert {"origin_class", "origin_root_sha", "authority_ceiling"} <= names
        row = conn.execute(
            "SELECT origin_class, origin_root_sha, authority_ceiling FROM memories LIMIT 0"
        )
        assert row is not None
    finally:
        conn.close()


def test_origin_columns_migrate_existing_0012_database(tmp_path: Path) -> None:
    dbfile = tmp_path / "brain.sqlite"
    prefix = tmp_path / "legacy-migrations"
    prefix.mkdir()
    for migration in db.migration_files():
        if int(migration.name[:4]) <= 12:
            shutil.copy2(migration, prefix / migration.name)
    db.migrate(dbfile, migrations_dir=prefix)
    conn = db.connect(dbfile)
    for column in ("origin_class", "origin_root_sha", "authority_ceiling"):
        conn.execute(f"ALTER TABLE memories DROP COLUMN {column}")
    conn.execute(
        "INSERT INTO memories "
        "(memory_id, title, scope, project_id, status, evidence_grade, current_version, "
        "created_at, updated_at, last_verified_at, strength, stability, summary, body_path) "
        "VALUES ('mem-preexisting', 'Old fact', 'global', NULL, 'current', "
        "'OBSERVED', 1, '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z', NULL, 1.0, 1.0, NULL, NULL)"
    )
    conn.commit()
    conn.close()
    db.migrate(dbfile)
    conn = db.connect(dbfile)
    try:
        names = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
        assert {"origin_class", "origin_root_sha", "authority_ceiling"} <= names
        # Pre-existing row survives non-destructively and gets safe defaults.
        row = conn.execute(
            "SELECT origin_class, origin_root_sha, authority_ceiling FROM memories "
            "WHERE memory_id = 'mem-preexisting'"
        ).fetchone()
        assert row["origin_class"] == "MODEL_INFERENCE"
        assert row["origin_root_sha"] is None
        assert row["authority_ceiling"] == "advisory"
    finally:
        conn.close()


def test_origin_columns_migration_is_idempotent(tmp_path: Path) -> None:
    dbfile = tmp_path / "brain.sqlite"
    first = db.migrate(dbfile)
    assert first  # first run applies migrations
    second = db.migrate(dbfile)
    assert second == []  # nothing pending, no re-application, no error
    conn = db.connect(dbfile)
    try:
        names = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
        assert {"origin_class", "origin_root_sha", "authority_ceiling"} <= names
    finally:
        conn.close()


def test_writeback_candidate_binds_model_inference(brain_home: Path) -> None:
    lifecycle = autoinject.BrainLifecycle(brain_home)
    memory_id = lifecycle.writeback_candidate(
        session_id="sess-writeback-origin",
        project_id="proj-writeback",
        title="Observed retry pattern",
        observation="The tool always retries twice on timeout",
    )
    row = semantic._row(brain_home, memory_id)
    assert row is not None
    assert row["origin_class"] == "MODEL_INFERENCE"
    assert row["authority_ceiling"] == "advisory"


def test_extract_durable_binds_tool_observation(tmp_path: Path) -> None:
    host = "host-origin-extract"
    identity = BrainSessionIdentity(
        internal_session_id=ledger_mod.internal_session_id(host),
        host="prime",
        host_session_id=host,
        project_id="proj-extract",
        created_at="2026-01-01T00:00:00Z",
        status="active",
        pinned=False,
        schema_version=1,
    )
    with ledger_mod.LedgerStore(tmp_path, host, host="prime").open(create=True) as store:
        store.create_session(identity)
        store.append_events(
            [
                BrainLifecycleEvent(
                    seq=1,
                    event_id="dec-1",
                    internal_session_id=ledger_mod.internal_session_id(host),
                    agent_id="a1",
                    parent_event_id=None,
                    host_entry_id="h-dec-1",
                    host_parent_entry_id=None,
                    segment_id="seg-1",
                    event_type=LifecycleEventType.DECISION,
                    timestamp="2026-01-01T00:00:00Z",
                    surface_visibility=SurfaceVisibility.RAW_ONLY,
                    ignorable=False,
                    payload={"decision": "Use bounded retries", "rationale": "avoid runaway loops"},
                    artifact_sha256=None,
                    source_event_ids=[],
                )
            ]
        )
    life = ledger_mod.SessionLifecycle(tmp_path, host)
    ids = life.extract_durable(project_id="proj-extract")
    assert len(ids) == 1
    row = semantic._row(tmp_path, ids[0])
    assert row is not None
    assert row["origin_class"] == "TOOL_OBSERVATION"
    assert row["authority_ceiling"] == "advisory"


def test_policy_lane_renders_lower_authority_contradiction_without_withholding(
    brain_home: Path,
) -> None:
    """In the policy lane, a contradiction from a memory that did not itself
    clear admission is rendered via ``contradicts`` but never flips the item's
    status to CONTRADICTED or withholds it.

    The packet builder is exercised directly: the policy lane admits only
    issuer-granted authority, and no producer in this build can supply one
    (SEC-AUTH-02), so the admitted-row path itself is unavailable here.
    """
    low = semantic.add_memory(
        brain_home,
        "Timeout policy",
        "retry forever",
        scope="global",
        origin_class="EXTERNAL_WEB",
        origin_root_sha=_root("web-timeout"),
    )
    semantic.curate(brain_home, low, status="current")
    high = semantic.add_memory(
        brain_home,
        "Timeout policy",
        "retry once then fail",
        scope="global",
        origin_class="USER_AUTHORED",
    )
    semantic.curate(brain_home, high, grade="TESTED", status="current")

    row = semantic.show_memory(brain_home, high)["row"]
    row["contradiction_with"] = [low]
    items = autoinject._build_items(brain_home, [row], lane="policy")

    assert len(items) == 1
    assert items[0].status is MemoryItemStatus.CURRENT
    assert items[0].contradicts == (low,)
