"""Phase 7: retrieval hard filters (archived/rejected/superseded/project)."""

import sqlite3

from second_brain import db, paths, semantic


def _add(home, title, body, **kw):
    return semantic.add_memory(home, title, body, **kw)


def _search_ids(home, term, **kw):
    return {r["memory_id"] for r in semantic.search_memories(home, term, **kw)}


def _linear_ids(home, term, **kw):
    return {r["memory_id"] for r in semantic._search_linear(home, term, **kw)}


def test_archived_excluded_by_default_and_history_reincludes(brain_home):
    live = _add(brain_home, title="Live memory", body="active content")
    arch = _add(brain_home, title="Archived memory", body="archived content")
    semantic.curate(brain_home, arch, status="archived")
    assert _search_ids(brain_home, "content") == {live}
    assert _search_ids(brain_home, "content", include_history=True) == {live, arch}


def test_rejected_grade_always_excluded(brain_home):
    good = _add(brain_home, title="Good memory", body="solid content")
    bad = _add(brain_home, title="Bad memory", body="dubious content")
    semantic.curate(brain_home, bad, grade="REJECTED")
    assert _search_ids(brain_home, "content") == {good}
    # rejected is not historical evidence: even the history flag keeps it out
    assert _search_ids(brain_home, "content", include_history=True) == {good}


def test_superseded_all_excluded_by_default_history_reincludes(brain_home):
    current = _add(brain_home, title="Current memory", body="wal frame content")
    # v1 superseded copy: cleanly replaced -> excluded
    dup = _add(brain_home, title="Dup memory", body="wal frame content")
    semantic.curate(brain_home, dup, status="superseded")
    # self-versioned line then marked superseded (current_version=2):
    # review N1 — ALL superseded rows are excluded by default; memory_versions
    # preserves the history, so no carve-out
    line = _add(brain_home, title="Line memory", body="wal frame content")
    semantic.supersede(brain_home, line, new_body="wal frame content v2", change_note="v2")
    semantic.curate(brain_home, line, status="superseded")

    ids = _search_ids(brain_home, "wal")
    assert ids == {current}
    assert dup not in ids
    assert line not in ids

    with_history = _search_ids(brain_home, "wal", include_history=True)
    assert current in with_history
    assert dup in with_history
    assert line in with_history


def test_project_filter(brain_home):
    p1 = _add(brain_home, title="P1 memory", body="shared token", project_id="proj-a")
    p2 = _add(brain_home, title="P2 memory", body="shared token", project_id="proj-b")
    dom = _add(
        brain_home, title="Domain memory", body="shared token", scope="domain", project_id=None
    )

    # global query: everything
    assert _search_ids(brain_home, "token") == {p1, p2, dom}
    # project context: only that project (domain/global memories excluded too)
    assert _search_ids(brain_home, "token", project_id="proj-a") == {p1}
    assert _search_ids(brain_home, "token", project_id="proj-b") == {p2}
    # unknown project: no results
    assert _search_ids(brain_home, "token", project_id="nope") == set()


def test_linear_fallback_applies_same_filters(brain_home, monkeypatch):
    live = _add(brain_home, title="Live fallback", body="needle in haystack")
    arch = _add(brain_home, title="Archived fallback", body="needle in haystack")
    rej = _add(brain_home, title="Rejected fallback", body="needle in haystack")
    sup = _add(brain_home, title="Superseded fallback", body="needle in haystack")
    other = _add(brain_home, title="Other project", body="needle in haystack", project_id="other")
    semantic.curate(brain_home, arch, status="archived")
    semantic.curate(brain_home, rej, grade="REJECTED")
    semantic.curate(brain_home, sup, status="superseded")

    monkeypatch.setattr(semantic, "_fts_available", lambda conn: False)

    assert _search_ids(brain_home, "needle") == {live, other}
    assert _linear_ids(brain_home, "needle") == {live, other}
    assert _search_ids(brain_home, "needle", include_history=True) == {live, arch, sup, other}
    assert _search_ids(brain_home, "needle", project_id="other") == {other}
    assert _search_ids(brain_home, "needle", project_id="other", include_history=True) == {other}
    # rejected never comes back
    assert rej not in _search_ids(brain_home, "needle", include_history=True)


def test_deterministic_tie_ordering(brain_home):
    # distinct titles, identical short bodies (< body-similarity min tokens so
    # Phase 8 dedupe does not merge them) -> identical bm25 -> tie by memory_id
    a = _add(brain_home, title="Alpha memory", body="same words here")
    b = _add(brain_home, title="Beta memory", body="same words here")
    ids1 = [r["memory_id"] for r in semantic.search_memories(brain_home, "same words")]
    ids2 = [r["memory_id"] for r in semantic.search_memories(brain_home, "same words")]
    assert set(ids1) == {a, b}
    # deterministic: identical inputs -> identical order across runs
    assert ids1 == ids2


def test_filter_defaults_do_not_break_existing_behavior(brain_home):
    # candidate/current/labile statuses and non-rejected grades are unaffected
    c = _add(brain_home, title="Candidate memory", body="candidate body")
    lab = _add(brain_home, title="Labile memory", body="labile body")
    semantic.curate(brain_home, lab, status="labile")
    semantic.curate(brain_home, c, status="current")
    assert _search_ids(brain_home, "body") == {c, lab}


# ---------------------------------------------------------------------------
# Phase 7 review regressions: F1 (guarded FTS purge), F2 (non-ASCII fallback),
# F4 (index-failure observability)
# ---------------------------------------------------------------------------


def test_reindex_all_ftsless_build_with_missing_file_does_not_raise(
    brain_home, monkeypatch, caplog
):
    """F1: on an FTS5-less build, purging a missing file must not crash."""
    mid = _add(brain_home, title="Doomed memory", body="gone soon")
    semantic.index_memory(brain_home, mid)
    monkeypatch.setattr(semantic, "_fts_available", lambda conn: False)
    monkeypatch.setattr(semantic, "_FTS_MODULE_CHECKED", True)
    monkeypatch.setattr(semantic, "_FTS_MODULE_OK", False)
    # delete the canonical file, then reindex: purge path must skip memory_fts
    row = semantic.show_memory(brain_home, mid)
    paths.Path(row["path"]).unlink()
    counts = semantic.reindex_all(brain_home)  # must NOT raise
    assert counts["purged"] >= 1
    conn = db.connect(db.db_path(brain_home))
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM memory_index WHERE memory_id=?", (mid,)).fetchone()[
                0
            ]
            == 0
        )
    finally:
        conn.close()
    # search still falls back to linear (no error)
    assert semantic.search_memories(brain_home, "gone") == []


def test_non_ascii_term_falls_back_to_linear(brain_home):
    """F2: diacritic/CJK/punctuation terms must never build a fragment MATCH."""
    _add(brain_home, title="Deja vu memory", body="deja vu experience")
    # linear finds "déjà" nowhere, but must not crash and must equal linear
    assert semantic.search_memories(brain_home, "déjà") == semantic._search_linear(
        brain_home, "déjà"
    )
    # "über" in body: linear finds it, FTS must fall back instead of splitting
    mid2 = _add(brain_home, title="Unicode memory", body="über efficient")
    got = semantic.search_memories(brain_home, "über")
    assert {r["memory_id"] for r in got} == {
        r["memory_id"] for r in semantic._search_linear(brain_home, "über")
    }
    assert mid2 in {r["memory_id"] for r in got}
    # pure CJK / punctuation: fall back rather than error or silently return []
    assert semantic.search_memories(brain_home, "記憶") == semantic._search_linear(
        brain_home, "記憶"
    )
    assert semantic.search_memories(brain_home, "!!!") == semantic._search_linear(brain_home, "!!!")


def test_index_failure_is_logged_once_and_fail_open(brain_home, monkeypatch, caplog):
    """F4: _safe_index logs one warning, never breaks the memory lifecycle."""
    import logging

    def _boom(home, memory_id):
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(semantic, "_index_memory", _boom)
    with caplog.at_level(logging.WARNING, logger="second_brain.semantic"):
        mid = _add(brain_home, title="Still added", body="curation unaffected")
    assert mid  # memory added despite index failure
    assert any("index update failed" in r.message for r in caplog.records)


def test_linear_matching_token_and_and_legacy_substring(brain_home):
    """Linear fallback matching rules (FTS-consistent token AND + legacy
    substring for non-tokenizable queries)."""
    mid_all = _add(
        brain_home,
        title="Budget ceiling rule",
        body="wal frame durability note about the budget ceiling",
    )
    _add(brain_home, title="Unrelated telemetry", body="budget tracking only, no frame")
    _add(brain_home, title="Symbol note", body="bug !!! marker here")

    # tokenized multi-word query: EVERY token must be present (not verbatim
    # phrase, not any-token) — matches mid_all only
    ids = {r["memory_id"] for r in semantic._search_linear(brain_home, "wal frame budget")}
    assert ids == {mid_all}
    # single token keeps plain substring semantics (word middle included)
    ids = {r["memory_id"] for r in semantic._search_linear(brain_home, "frame")}
    assert mid_all in ids

    # non-tokenizable query keeps legacy verbatim substring matching
    ids = {r["memory_id"] for r in semantic._search_linear(brain_home, "!!!")}
    assert ids == {r["memory_id"] for r in semantic._search_linear(brain_home, "!!!")}
    assert "Symbol note" in {
        r["title"] for r in semantic._search_linear(brain_home, "!!!")
    }
