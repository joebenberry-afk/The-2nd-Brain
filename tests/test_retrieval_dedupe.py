"""Phase 8: retrieval deduplication (post-filter, pre-budget)."""

from second_brain import semantic


def _add(home, title, body, **kw):
    return semantic.add_memory(home, title, body, **kw)


def _search_ids(home, term, **kw):
    return {r["memory_id"] for r in semantic.search_memories(home, term, **kw)}


def _search_rows(home, term, **kw):
    return semantic.search_memories(home, term, **kw)


def test_superseded_family_keeps_current_only(brain_home):
    # two memory_ids, same fact (same title) — canonical (current, newest) wins
    older = _add(brain_home, title="WAL durability rule", body="wal durability details")
    newer = _add(brain_home, title="WAL durability rule", body="wal durability details v2")
    semantic.curate(brain_home, newer, status="current")
    semantic.curate(brain_home, older, status="superseded")
    ids = _search_ids(brain_home, "durability")
    assert ids == {newer}
    # comparison exception: duplicates flag alone does not bypass Phase 7
    # filters, so a supersede audit also needs include_history
    assert _search_ids(brain_home, "durability", include_duplicates=True) == {newer}
    assert _search_ids(brain_home, "durability", include_duplicates=True, include_history=True) == {
        older,
        newer,
    }


def test_near_identical_pair_keeps_canonical_deterministic(brain_home):
    # same title + near-identical body: representative = current > labile
    canonical = _add(brain_home, title="Router margin rule", body="margin must exceed noise floor")
    copy = _add(brain_home, title="Router margin rule", body="margin must exceed the noise floor")
    semantic.curate(brain_home, canonical, status="current")
    semantic.curate(brain_home, copy, status="labile")
    ids = _search_ids(brain_home, "margin")
    assert ids == {canonical}
    # tie-break determinism: same status/version -> updated_at then grade then id
    a = _add(brain_home, title="Identical fact", body="exact same body text")
    b = _add(brain_home, title="Identical fact", body="exact same body text")
    rows = _search_rows(brain_home, "identical")
    assert len(rows) == 1
    assert rows[0]["memory_id"] in (a, b)


def test_same_fact_different_scope_rule(brain_home):
    # same fact in project scope vs global scope, both project_id=p1
    proj = _add(
        brain_home,
        title="Telemetry budget rule",
        body="budget ceiling note",
        scope="project",
        project_id="p1",
    )
    glob = _add(
        brain_home,
        title="Telemetry budget rule",
        body="budget ceiling note",
        scope="global",
        project_id="p1",
    )
    # project context: kept DISTINCT (comparison may be required)
    ids_proj = _search_ids(brain_home, "budget", project_id="p1")
    assert ids_proj == {proj, glob}
    # global query: deduped to one representative
    ids_global = _search_ids(brain_home, "budget")
    assert len(ids_global) == 1


def test_dedupe_applied_after_filters_archived_never_representative(brain_home):
    current = _add(brain_home, title="Immune rule", body="fingerprint baseline note")
    archived = _add(brain_home, title="Immune rule", body="fingerprint baseline note")
    semantic.curate(brain_home, archived, status="archived")
    # default: archived filtered out, current remains
    assert _search_ids(brain_home, "fingerprint") == {current}
    # history query: both present after filters, dedupe keeps the CURRENT row
    ids = _search_ids(brain_home, "fingerprint", include_history=True)
    assert ids == {current}


def test_dedupe_not_merge_content_just_select_representative(brain_home):
    a = _add(brain_home, title="Shared fact title", body="body version a")
    b = _add(brain_home, title="Shared fact title", body="body version b")
    rows = _search_rows(brain_home, "shared")
    assert len(rows) == 1
    # the representative is a real row (one of the two), body untouched
    assert rows[0]["memory_id"] in (a, b)
    assert rows[0]["title"] == "Shared fact title"


def test_linear_fallback_applies_same_dedupe(brain_home, monkeypatch):
    older = _add(brain_home, title="Linear dup rule", body="linear dup body")
    newer = _add(brain_home, title="Linear dup rule", body="linear dup body v2")
    semantic.curate(brain_home, newer, status="current")
    semantic.curate(brain_home, older, status="superseded")
    monkeypatch.setattr(semantic, "_fts_available", lambda conn: False)
    assert _search_ids(brain_home, "linear dup") == {newer}
    assert _search_ids(brain_home, "linear dup", include_duplicates=True, include_history=True) == {
        older,
        newer,
    }


def test_distinct_memories_not_merged(brain_home):
    a = _add(brain_home, title="Completely different title", body="wal journal frames")
    b = _add(brain_home, title="Another distinct title", body="sleep replay consolidation")
    ids = _search_ids(brain_home, "journal")
    assert ids == {a}
    ids = _search_ids(brain_home, "replay")
    assert ids == {b}
