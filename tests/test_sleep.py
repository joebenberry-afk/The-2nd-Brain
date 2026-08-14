"""Tests for the conservative sleep/consolidation pass (Phase 14)."""

from pathlib import Path

from second_brain import db, episodes, semantic, sleep
from second_brain.errors import BrainError  # noqa: F401


def _episode(brain_home, etype, summary, pe=None, salience=None, lesson=None):
    sections = None
    if lesson is not None:
        sections = {"Reusable lesson": lesson}
    return episodes.create_episode(
        brain_home,
        etype,
        summary,
        prediction_error=pe,
        salience=salience,
        sections=sections,
    )


def _memory(brain_home, title, strength=0.5, status="current", grade="TESTED"):
    mid = semantic.add_memory(brain_home, title, f"body for {title}", grade=grade)
    semantic.curate(brain_home, mid, status=status)
    conn = __import__("second_brain.db", fromlist=["connect"]).connect(
        __import__("second_brain.db", fromlist=["db_path"]).db_path(brain_home)
    )
    try:
        conn.execute("UPDATE memories SET strength = ? WHERE memory_id = ?", (strength, mid))
        conn.commit()
    finally:
        conn.close()
    return mid


def _memory_row(brain_home, mid):
    from second_brain import db

    conn = db.connect(db.db_path(brain_home))
    try:
        return dict(conn.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,)).fetchone())
    finally:
        conn.close()


def _file(brain_home, mid):
    return Path(brain_home) / "memory" / "semantic" / f"{mid}.md"


# ---------------------------------------------------------------------------
# Replay queue ranking
# ---------------------------------------------------------------------------


def test_replay_queue_ranking(brain_home):
    a = _episode(brain_home, "correction", "fix", pe=0.5, salience=0.5)  # 2.5
    b = _episode(brain_home, "success", "win", pe=1.0, salience=0.8)  # 2.8
    c = _episode(brain_home, "failure", "lost", pe=0.0, salience=0.1)  # 0.1
    queue = sleep.replay_queue(brain_home)
    assert [item["episode_id"] for item in queue] == [b, a, c]
    assert [item["priority"] for item in queue] == [2.8, 2.5, 0.1]
    assert queue[0]["episode_type"] == "success"
    assert "sections" in queue[0]
    # limit respected
    assert len(sleep.replay_queue(brain_home, limit=2)) == 2


def test_replay_queue_priority_tiebreak_by_created_at(brain_home):
    _episode(brain_home, "surprise", "first", pe=1.0, salience=0.0)  # 2.0
    _episode(brain_home, "surprise", "second", pe=1.0, salience=0.0)  # 2.0
    queue = sleep.replay_queue(brain_home)
    assert queue[0]["created_at"] <= queue[1]["created_at"]


def test_replay_queue_skips_missing_files(brain_home):
    eid = _episode(brain_home, "correction", "ghost")
    (brain_home / "memory" / "episodic" / f"{eid}.md").unlink()
    queue = sleep.replay_queue(brain_home)
    assert all(item["episode_id"] != eid for item in queue)
    assert len(queue) == 0


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _queue_episode(eid, lesson):
    return {
        "episode_id": eid,
        "sections": {"Reusable lesson": lesson},
        "episode_type": "correction",
        "created_at": "t",
        "priority": 1.0,
    }


def test_cluster_jaccard_boundaries(brain_home):
    queue = [
        _queue_episode("A", "restore the sidecar cleanup pattern"),
        _queue_episode("B", "restore sidecar cleanup prevents replay corruption"),
        _queue_episode("C", "deploy the database schema migration"),
        _queue_episode("D", ""),  # empty lesson never joins
    ]
    clusters = sleep.cluster(queue)
    assert len(clusters) == 3
    ids = [set(c["episode_ids"]) for c in clusters]
    assert {"A", "B"} in ids  # jaccard >= 0.3 joins
    assert {"C"} in ids
    assert {"D"} in ids


def test_cluster_deterministic_order(brain_home):
    queue = [
        _queue_episode("A", "restore sidecar cleanup"),
        _queue_episode("B", "restore sidecar cleanup prevents replay"),
        _queue_episode("C", "database migration deploy"),
        _queue_episode("D", "restore cleanup"),
    ]
    first = sleep.cluster(queue)
    second = sleep.cluster(queue)
    assert first == second
    # A joins the first matching cluster; D (restore+cleanup) joins A's cluster.
    assert [c["episode_ids"] for c in first] == [["A", "B", "D"], ["C"]]


def test_cluster_empty_queue():
    assert sleep.cluster([]) == []


# ---------------------------------------------------------------------------
# Strengthening (no invented facts)
# ---------------------------------------------------------------------------


def _strengthen_setup(brain_home):
    cluster = {
        "tokens": sleep._tokens("restore sidecar cleanup prevents replay corruption"),
        "episode_ids": ["correction-1", "correction-2"],
        "lesson": "restore sidecar cleanup",
    }
    m1 = _memory(brain_home, "restore hygiene rule", strength=0.5)  # shares 'restore'
    m2 = _memory(brain_home, "scout promotion criteria", strength=0.7)  # no shared token
    return cluster, m1, m2


def test_strengthen_dry_run_changes_nothing(brain_home):
    cluster, m1, _ = _strengthen_setup(brain_home)
    before_m1 = _file(brain_home, m1).read_text(encoding="utf-8")
    changes = sleep.strengthen_memories(brain_home, cluster, dry_run=True)
    assert [c["memory_id"] for c in changes] == [m1]
    assert changes[0]["strength_before"] == 0.5
    assert changes[0]["strength_after"] == 0.6
    assert changes[0]["sources_added"] == ["correction-1", "correction-2"]
    # Nothing written.
    assert _memory_row(brain_home, m1)["strength"] == 0.5
    assert _file(brain_home, m1).read_text(encoding="utf-8") == before_m1


def test_strengthen_live_bumps_and_sources(brain_home):
    from second_brain import db

    cluster, m1, m2 = _strengthen_setup(brain_home)
    before_body = _file(brain_home, m1).read_text(encoding="utf-8")
    changes = sleep.strengthen_memories(brain_home, cluster, dry_run=False)
    assert len(changes) == 1
    row = _memory_row(brain_home, m1)
    assert row["strength"] == 0.6
    assert row["title"] == "restore hygiene rule"  # title untouched
    assert row["evidence_grade"] == "TESTED"  # grade untouched
    assert _file(brain_home, m1).read_text(encoding="utf-8") == before_body  # body byte-identical
    conn = db.connect(db.db_path(brain_home))
    try:
        sources = [
            dict(r)
            for r in conn.execute(
                "SELECT source_ref, source_kind FROM memory_sources WHERE memory_id = ?", (m1,)
            ).fetchall()
        ]
    finally:
        conn.close()
    assert {(s["source_ref"], s["source_kind"]) for s in sources} == {
        ("correction-1", "episode"),
        ("correction-2", "episode"),
    }
    # Non-matching memory untouched.
    assert _memory_row(brain_home, m2)["strength"] == 0.7


def test_strengthen_caps_at_one(brain_home):
    m = _memory(brain_home, "restore hygiene rule", strength=0.95)
    cluster = {
        "tokens": sleep._tokens("restore sidecar"),
        "episode_ids": ["e1"],
        "lesson": "restore",
    }
    changes = sleep.strengthen_memories(brain_home, cluster, dry_run=True)
    assert changes[0]["strength_after"] == 1.0
    sleep.strengthen_memories(brain_home, cluster, dry_run=False)
    assert _memory_row(brain_home, m)["strength"] == 1.0


def test_strengthen_ignores_candidate_memories(brain_home):
    mid = _memory(brain_home, "restore hygiene rule", status="candidate")
    cluster = {
        "tokens": sleep._tokens("restore sidecar"),
        "episode_ids": ["e1"],
        "lesson": "restore",
    }
    assert sleep.strengthen_memories(brain_home, cluster, dry_run=True) == []
    assert _memory_row(brain_home, mid)["strength"] == 0.5


# ---------------------------------------------------------------------------
# Utility report
# ---------------------------------------------------------------------------


def test_utility_aggregation(brain_home):
    from second_brain import plasticity

    plasticity.utility_update(brain_home, "scout", "scout", 0.25, "localized")
    plasticity.utility_update(brain_home, "scout", "scout", -0.1, "looped")
    plasticity.utility_update(brain_home, "verify", "verification", 0.5, "caught bug")
    report = sleep.utility_report(brain_home)
    assert report["records"] == 3
    assert report["entries"][0] == {
        "subject_id": "verify",
        "subject_kind": "verification",
        "sum": 0.5,
        "count": 1,
    }
    assert report["entries"][1] == {
        "subject_id": "scout",
        "subject_kind": "scout",
        "sum": 0.15,
        "count": 2,
    }
    # Sorted by sum DESC.
    sums = [e["sum"] for e in report["entries"]]
    assert sums == sorted(sums, reverse=True)


def test_utility_report_empty(brain_home):
    assert sleep.utility_report(brain_home) == {"records": 0, "entries": []}


# ---------------------------------------------------------------------------
# Consolidate
# ---------------------------------------------------------------------------


def test_consolidate_dry_run_writes_report_changes_nothing(brain_home):
    _, m1, _ = _strengthen_setup(brain_home)  # cluster not needed here
    _episode(
        brain_home,
        "correction",
        "restore bug",
        pe=0.5,
        salience=0.5,
        lesson="restore the sidecar cleanup pattern",
    )
    _episode(
        brain_home,
        "success",
        "scout win",
        pe=0.0,
        salience=0.2,
        lesson="candidate shrink improves outcomes",
    )
    from second_brain import plasticity

    plasticity.utility_update(brain_home, "scout", "scout", 0.25, "localized")

    result = sleep.consolidate(brain_home, dry_run=True)
    assert set(result) == {
        "queue",
        "clusters",
        "strengthened",
        "utility",
        "contradictions",
        "report_path",
    }
    assert len(result["queue"]) == 2
    assert len(result["clusters"]) == 2
    assert [c["memory_id"] for c in result["strengthened"]] == [m1]
    assert result["utility"]["records"] == 1

    reports = list((brain_home / "sleep" / "reports").glob("consolidation-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert text.startswith("# Consolidation Report")
    assert "mode: dry-run" in text
    assert "clusters: 2" in text
    assert "strengthened: 1" in text
    assert "utility: 1" in text
    assert "contradictions:" in text
    # Nothing changed in dry run.
    assert _memory_row(brain_home, m1)["strength"] == 0.5


def test_consolidate_determinism(brain_home):
    _episode(
        brain_home,
        "correction",
        "restore bug",
        pe=0.5,
        salience=0.5,
        lesson="restore the sidecar cleanup pattern",
    )
    _episode(
        brain_home,
        "success",
        "scout win",
        pe=0.0,
        salience=0.2,
        lesson="candidate shrink improves outcomes",
    )
    first = sleep.consolidate(brain_home, dry_run=True)
    second = sleep.consolidate(brain_home, dry_run=True)
    # report_path embeds the timestamp; determinism is over the rest
    first_body = {k: v for k, v in first.items() if k != "report_path"}
    second_body = {k: v for k, v in second.items() if k != "report_path"}
    assert first_body == second_body
    assert len(list((brain_home / "sleep" / "reports").glob("consolidation-*.md"))) == 2


def test_consolidate_empty_queue(brain_home):
    result = sleep.consolidate(brain_home, dry_run=True)
    assert result["queue"] == []
    assert result["clusters"] == []
    assert result["strengthened"] == []
    assert result["utility"] == {"records": 0, "entries": []}
    reports = list((brain_home / "sleep" / "reports").glob("consolidation-*.md"))
    assert len(reports) == 1


def test_no_dream_pass_exists():
    public = {name for name in dir(sleep) if not name.startswith("_")}
    expected = {
        "annotations",  # from __future__ import annotations
        "JACCARD_THRESHOLD",
        "STRENGTH_BUMP",
        "STRENGTH_CAP",
        "TOKEN_MIN_LEN",
        "REPORT_DIR",
        "replay_queue",
        "cluster",
        "strengthen_memories",
        "utility_report",
        "consolidate",
        "BrainError",
        "episodes",
        "semantic",
        "plasticity",
        "db",
        "Path",
        "re",
        "json",
        "os",
        "tempfile",
        "contextlib",
        "datetime",
        "UTC",
    }
    assert public <= expected, public - expected
    assert not hasattr(sleep, "dream_pass")


def test_apply_twice_does_not_duplicate_sources(brain_home):
    """Verifier finding: re-apply must not grow provenance rows unboundedly."""
    _episode(
        brain_home,
        "correction",
        "sidecar cleanup",
        pe=0.5,
        salience=0.5,
        lesson="restore sidecar cleanup pattern",
    )
    mid = semantic.add_memory(
        brain_home,
        "Sidecar cleanup rule",
        "restore sidecar pattern",
        scope="project",
        grade="TESTED",
    )
    semantic.curate(brain_home, mid, status="current")

    q = sleep.replay_queue(brain_home)
    for c in sleep.cluster(q):
        sleep.strengthen_memories(brain_home, c, dry_run=False)
    sleep.consolidate(brain_home, dry_run=False)

    conn = db.connect(db.db_path(brain_home))
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM memory_sources WHERE memory_id = ? AND source_kind='episode'",
            (mid,),
        ).fetchone()[0]
        # one source per episode even after consolidate re-applies clusters
        assert rows == 1
    finally:
        conn.close()
