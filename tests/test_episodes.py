"""Tests for the episodic memory vault (Phase 9)."""

import json
import re
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import db, episodes
from second_brain.errors import BrainError

_ID_RE = re.compile(r"^[a-z-]+-20\d{6}-[0-9a-f]{8}$")

ALL_SECTIONS = {
    "Situation": "debugging the WAL replay bug",
    "Expected": "restore leaves no stale frames",
    "Actual": "stale -wal replayed data",
    "Actions": "dropped sidecars after restore",
    "Evidence": "test_restore_drops_stale_wal_shm",
    "Root cause": "missing sidecar cleanup",
    "What worked": "hash verification",
    "What failed": "first restore attempt",
    "Reusable lesson": "never leave -wal next to a restored DB",
    "Trigger signals": "restore after WAL",
    "Counter-signals": "clean shutdown",
    "Verification": "test_backup.py",
    "Related memories": "(none)",
}


def _create(brain_home, etype="correction", summary="fixed the bug", **kw):
    return episodes.create_episode(brain_home, etype, summary, **kw)


# ---------------------------------------------------------------------------
# Create / read roundtrip
# ---------------------------------------------------------------------------


def test_create_read_roundtrip_all_sections(brain_home):
    eid = _create(
        brain_home,
        summary="fixed the WAL replay bug",
        project_id="proj-a",
        session_id="sess-1",
        task_id="task-9",
        evidence_refs=["dc0e49d", "outputs/reports/m1.md"],
        prediction_error=0.6,
        salience=0.8,
        confidence="high",
        scope="project",
        sections=ALL_SECTIONS,
    )
    assert _ID_RE.match(eid)
    assert eid.startswith("correction-")

    path = brain_home / "memory" / "episodic" / f"{eid}.md"
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert body.startswith("---\n")
    assert f"id: {eid}" in body
    assert "type: correction" in body
    assert "evidence_grade: OBSERVED" in body
    assert 'evidence_refs: ["dc0e49d", "outputs/reports/m1.md"]' in body
    assert "# Summary\n\nfixed the WAL replay bug" in body
    for name in episodes.EPISODE_SECTIONS:
        assert f"# {name}" in body
        assert ALL_SECTIONS[name] in body

    shown = episodes.show_episode(brain_home, eid)
    assert shown["row"]["episode_id"] == eid
    assert shown["row"]["project_id"] == "proj-a"
    assert shown["row"]["evidence_refs"] == json.dumps(["dc0e49d", "outputs/reports/m1.md"])
    assert shown["path"] == str(path)
    assert shown["body"] == body


def test_unfilled_sections_none(brain_home):
    eid = _create(brain_home, sections={"Situation": "only this"})
    body = episodes.show_episode(brain_home, eid)["body"]
    assert "# Situation\n\nonly this" in body
    assert "# Expected\n\n(none)" in body
    assert "# Related memories\n\n(none)" in body


def test_db_row_matches_file(brain_home):
    eid = _create(brain_home, summary="row check", prediction_error=0.25, salience=0.5)
    conn = db.connect(db.db_path(brain_home))
    try:
        row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (eid,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["episode_type"] == "correction"
    assert row["status"] == "raw"
    assert row["scope"] == "project"
    assert row["summary"] == "row check"
    body = episodes.show_episode(brain_home, eid)["body"]
    assert f"id: {eid}" in body.split("---")[1]


def test_id_collision_retry_against_file(brain_home, monkeypatch):
    first = _create(brain_home)
    suffix = first.rsplit("-", 1)[1]
    monkeypatch.setattr(
        episodes.secrets, "token_hex", lambda n: suffix
    )  # keep colliding -> must give up after retries
    with pytest.raises(BrainError, match="unique episode id"):
        _create(brain_home)
    # Now collide once, then recover with a fresh suffix.
    monkeypatch.setattr(episodes.secrets, "token_hex", lambda n: "deadbeef")
    _create(brain_home, etype="success")  # different type prefix, no collision
    second_suffix = "cafebabe"
    calls = {"n": 0}

    def flaky(n):
        calls["n"] += 1
        return suffix if calls["n"] == 1 else second_suffix

    monkeypatch.setattr(episodes.secrets, "token_hex", flaky)
    eid = _create(brain_home, etype="correction")
    assert eid == f"correction-{eid.split('-')[1]}-{second_suffix}"
    assert (brain_home / "memory" / "episodic" / f"{eid}.md").exists()


def test_id_collision_retry_against_db(brain_home, monkeypatch):
    first = _create(brain_home)
    suffix = first.rsplit("-", 1)[1]
    # Remove the file but keep the DB row: collision must still be detected.
    (brain_home / "memory" / "episodic" / f"{first}.md").unlink()
    calls = {"n": 0}
    fresh = "01234567"

    def flaky(n):
        calls["n"] += 1
        return suffix if calls["n"] == 1 else fresh

    monkeypatch.setattr(episodes.secrets, "token_hex", flaky)
    eid = _create(brain_home, etype="correction")
    assert eid.endswith(fresh)


def test_immutable_body_annotate_appends_only(brain_home):
    eid = _create(brain_home, sections={"Situation": "original content"})
    original = episodes.show_episode(brain_home, eid)["body"]
    path = episodes.annotate_episode(brain_home, eid, "verifier confirmed the root cause")
    body = path.read_text(encoding="utf-8")
    assert original in body  # original body untouched
    assert body.count("## Addendum (") == 1
    assert "verifier confirmed the root cause" in body
    # DB row unchanged (no second row, same fields).
    rows = episodes.list_episodes(brain_home)
    assert len(rows) == 1
    assert rows[0]["summary"] == "fixed the bug"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_type_and_summary_validation(brain_home):
    with pytest.raises(BrainError, match="episode_type"):
        _create(brain_home, etype="bogus")
    with pytest.raises(BrainError, match="summary"):
        _create(brain_home, summary="   ")


def test_section_and_field_validation(brain_home):
    with pytest.raises(BrainError, match="Unknown episode section"):
        _create(brain_home, sections={"NotASection": "x"})
    with pytest.raises(BrainError, match="Section"):
        _create(brain_home, sections={"Situation": 5})  # type: ignore[dict-item]
    with pytest.raises(BrainError, match="prediction_error"):
        _create(brain_home, prediction_error=1.5)
    with pytest.raises(BrainError, match="prediction_error"):
        _create(brain_home, prediction_error="high")  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="evidence_refs"):
        _create(brain_home, evidence_refs=["ok", 5])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Lazy migration
# ---------------------------------------------------------------------------


def test_lazy_migration_0002_on_v1_brain(brain_home):
    dbfile = db.db_path(brain_home)
    # Simulate a v1 brain: drop the phase 9/10 tables and forget versions >= 2.
    conn = db.connect(dbfile)
    try:
        for table in (
            "model_skill_outcomes",
            "model_profiles",
            "memory_activations",
            "memory_retrievals",
            "credit_events",
            "prediction_errors",
            "outcomes",
            "predictions",
            "memory_versions",
            "memory_sources",
            "memories",
            "episodes",
            "memory_index",
            "memory_fts",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DELETE FROM schema_version WHERE version >= 2")
        conn.commit()
    finally:
        conn.close()
    eid = _create(brain_home)
    assert db.pending_migrations(dbfile) == []
    assert episodes.show_episode(brain_home, eid)["row"]["episode_id"] == eid


# ---------------------------------------------------------------------------
# List / search / errors
# ---------------------------------------------------------------------------


def test_list_filters(brain_home):
    e1 = _create(brain_home, etype="success", summary="first win", project_id="p1")
    e2 = _create(brain_home, etype="correction", summary="second fix", project_id="p2")
    e3 = _create(brain_home, etype="correction", summary="third fix", project_id="p1")

    assert [r["episode_id"] for r in episodes.list_episodes(brain_home)] == [e3, e2, e1]
    by_type = episodes.list_episodes(brain_home, episode_type="correction")
    assert [r["episode_id"] for r in by_type] == [e3, e2]
    by_project = episodes.list_episodes(brain_home, project_id="p1")
    assert [r["episode_id"] for r in by_project] == [e3, e1]
    since = episodes.show_episode(brain_home, e2)["row"]["created_at"]
    assert [r["episode_id"] for r in episodes.list_episodes(brain_home, since=since)] == [e3, e2]


def test_search_summary_and_body(brain_home):
    _create(brain_home, summary="fixed the WAL replay bug", sections={"Evidence": "stale sidecar"})
    _create(brain_home, etype="success", summary="scout experiment won")
    hits = episodes.search_episodes(brain_home, "wal")
    assert len(hits) == 1 and hits[0]["summary"].startswith("fixed")
    hits = episodes.search_episodes(brain_home, "SIDECAR")  # body-only, case-insensitive
    assert len(hits) == 1 and hits[0]["episode_type"] == "correction"
    assert episodes.search_episodes(brain_home, "zzz-no-match") == []
    with pytest.raises(BrainError, match="term"):
        episodes.search_episodes(brain_home, "  ")


def test_search_limit(brain_home):
    for i in range(5):
        _create(brain_home, etype="success", summary=f"common word {i}")
    assert len(episodes.search_episodes(brain_home, "common", limit=3)) == 3


def test_show_unknown_and_missing_file(brain_home):
    with pytest.raises(BrainError, match="Unknown episode"):
        episodes.show_episode(brain_home, "success-20260814-00000000")
    eid = _create(brain_home)
    (brain_home / "memory" / "episodic" / f"{eid}.md").unlink()
    with pytest.raises(BrainError, match="file missing"):
        episodes.show_episode(brain_home, eid)


def test_corrupt_episode_file_raises(brain_home):
    eid = _create(brain_home)
    path = brain_home / "memory" / "episodic" / f"{eid}.md"
    path.write_text("not frontmatter at all", encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        episodes.show_episode(brain_home, eid)
    assert str(path) in str(exc.value)


def test_annotate_unknown_episode_raises(brain_home):
    with pytest.raises(BrainError, match="Unknown episode"):
        episodes.annotate_episode(brain_home, "nope-20260814-00000000", "note")


# ---------------------------------------------------------------------------
# Hypothesis: multi-agent-safe unique writes
# ---------------------------------------------------------------------------


@settings(
    max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.sampled_from(episodes.EPISODE_TYPES), min_size=1, max_size=10))
def test_create_sequences_unique(brain_home, types):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    ids = []
    for index, etype in enumerate(types):
        eid = episodes.create_episode(home, etype, f"summary {index}")
        ids.append(eid)
        assert len(episodes.list_episodes(home)) == index + 1
    assert len(set(ids)) == len(ids)  # all unique
    files = list((home / "memory" / "episodic").glob("*.md"))
    assert len(files) == len(ids)  # one file per episode
    rows = episodes.list_episodes(home)
    assert {r["episode_id"] for r in rows} == set(ids)  # one row per episode
    assert all(f.name.endswith(".md") for f in files)
